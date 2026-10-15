#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run after building with -DBUILD_VIEWER_TESTS=ON. No Python dependencies."""
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib
from viewer import HERE, Renderer, validate_settings, render_file


class RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="sdf-viewer-test-")
        cls.directory = Path(cls.tmp.name)
        subprocess.run([str(HERE/"build/sdf_test_grids"), cls.tmp.name], check=True)
        cls.library = HERE/"build/libsdf_renderer.so"
        cls.sphere = Renderer(cls.directory/"sphere.nvdb", cls.library)
        cls.index = Renderer(cls.directory/"sphere-index.nvdb", cls.library)

    @classmethod
    def tearDownClass(cls):
        cls.sphere.close()
        cls.index.close()
        cls.tmp.cleanup()

    def settings(self, **kwargs):
        result = self.sphere.defaults()
        result.update(eye=[0,0,4], target=[0,0,0], up=[0,1,0], orthographic=1,
                      orthoScale=3, transparent=1, ao=0, step=.25)
        result.update(kwargs)
        return validate_settings(result)

    def test_sphere_silhouette_against_analytic_rays(self):
        width = 128
        rgba = self.sphere.tile(self.settings(), width, width, 0, 0, width, width, 1)
        tested = 0
        for y in range(width):
            for x in range(width):
                radius = math.hypot(((x+.5)/width-.5)*3, ((y+.5)/width-.5)*3)
                if abs(radius-1) < .025:
                    continue  # silhouette discretization within roughly two voxels
                alpha = rgba[(y*width+x)*4+3]
                self.assertEqual(alpha, 255 if radius<1 else 0, (x,y,radius))
                tested += 1
        self.assertGreater(tested, 15000)

    def test_index_masks_match_float_field_in_all_modes(self):
        for mode in range(7):
            settings = self.settings(mode=mode, clipAxis=2 if mode in (3,5) else -1, clipPosition=0)
            a = self.sphere.tile(settings, 128, 96, 0, 0, 128, 96, 4)
            b = self.index.tile(settings, 128, 96, 0, 0, 128, 96, 4)
            self.assertEqual(a, b, f"mode {mode}: float and index+mask differ")

    def test_tiles_are_identical_to_one_frame(self):
        settings = self.settings(mode=1)
        full = self.index.tile(settings, 95, 71, 0, 0, 95, 71, 4)
        tiled = b"".join(self.index.tile(settings,95,71,0,y,95,min(13,71-y),4) for y in range(0,71,13))
        self.assertEqual(full,tiled)
        tile = self.index.tile(settings,95,71,19,23,27,11,4)
        expected = b"".join(full[((23+y)*95+19)*4:((23+y)*95+46)*4] for y in range(11))
        self.assertEqual(tile,expected)

    def test_every_sign_mask_level_and_negative_coordinates(self):
        renderer = Renderer(self.directory/"masks.nvdb",self.library)
        try:
            points = [(0,0,0),(7,7,7),(1,1,1),(2,2,2),(8,0,0),(16,0,0),
                      (128,0,0),(256,0,0),(4096,0,0),(8192,0,0),(-8,0,0),(-7,0,0)]
            expected = [-.25,.25,-3,3,-3,.5,-3,3,-3,3,-.5,3]
            self.assertEqual(renderer.probe(points),expected)
        finally:
            renderer.close()

    def test_legacy_dense_root_mask(self):
        renderer = Renderer(self.directory/"dense-masks.nvdb",self.library)
        try:
            points = [(1,1,1),(8,0,0),(128,0,0),(4096,0,0),(8192,0,0),
                      (-4097,0,0),(4096,4096,0),(4096,0,4096)]
            self.assertEqual(renderer.probe(points),[-3,-3,-3,-3,3,3,3,3])
        finally:
            renderer.close()
        with self.assertRaisesRegex(RuntimeError,"root_extent"):
            Renderer(self.directory/"missing-extent.nvdb",self.library)

    def test_active_voxels_show_both_signs_and_hide_inactive_interior(self):
        # Looking at the z=0 cut: sphere center is inactive, both band sides are active.
        for mode in (4,5):
            settings=self.settings(mode=mode,clipAxis=2,clipPosition=0)
            image=self.index.tile(settings,256,256,0,0,256,256,1)
            if mode==5:
                self.assertEqual(image[(128*256+128)*4+3],0)
            warm=cool=0
            for i in range(0,len(image),4):
                if image[i+3]:
                    warm+=image[i]>image[i+2]
                    cool+=image[i+2]>image[i]
            self.assertGreater(warm,100,mode)
            self.assertGreater(cool,100,mode)
        # Positive-side camera hits the + band first when clipping is disabled.
        image=self.index.tile(self.settings(mode=4),64,64,0,0,64,64,1)
        center=image[(32*64+32)*4:(32*64+32)*4+4]
        self.assertGreater(center[2],center[0])

    def test_full_space_fill_preserves_each_box_size(self):
        # Independent one-box fixtures at every level: 1, 8, 128, 4096 voxels.
        # The fixture intentionally extends outside the active-value bounding box.
        for filename in ("masks.nvdb", "dense-masks.nvdb"):
            renderer=Renderer(self.directory/filename,self.library)
            try:
                self.assertEqual(renderer.info["fillBoxes"],[1,1,1,1])
                self.assertEqual(renderer.info["fillIndexMax"],[8191,4095,4095])
                for level,dim,origin in [(0,1,[1,1,1]),(1,8,[8,0,0]),
                                         (2,128,[128,0,0]),(3,4096,[4096,0,0])]:
                    target=[v+(dim-1)/2 for v in origin]
                    eye=target.copy();eye[2]+=2*dim
                    data=renderer.defaults()
                    data.update(mode=6,fillMask=1<<level,eye=eye,target=target,up=[0,1,0],
                                orthographic=1,orthoScale=2*dim,transparent=1)
                    settings=validate_settings(data)
                    image=renderer.tile(settings,64,64,0,0,64,64,1)
                    count=sum(a==255 for a in image[3::4])
                    self.assertEqual(count,32*32,(filename,level))
                    center=image[(32*64+32)*4:(32*64+32)*4+4]
                    self.assertGreater(center[0],center[2])
                    # Disabled level must disappear, with no inactive exterior cubes.
                    data["fillMask"]=0
                    hidden=renderer.tile(validate_settings(data),64,64,0,0,64,64,1)
                    self.assertFalse(any(hidden[3::4]))
                    # A clipping plane through the cube must expose the same sign.
                    data.update(fillMask=1<<level,clipAxis=2,clipPosition=target[2])
                    clipped=renderer.tile(validate_settings(data),64,64,0,0,64,64,1)
                    self.assertEqual(sum(a==255 for a in clipped[3::4]),32*32)
            finally:
                renderer.close()

    def test_fill_can_be_hidden_without_changing_active_band(self):
        self.assertEqual(self.sphere.info["fillBoxes"],self.index.info["fillBoxes"])
        self.assertGreater(self.index.info["fillBoxes"][0],0)
        self.assertGreater(self.index.info["fillBoxes"][1],0)
        active=self.index.tile(self.settings(mode=4,clipAxis=2,clipPosition=0),96,96,0,0,96,96,1)
        band_only=self.index.tile(self.settings(mode=6,fillMask=16,clipAxis=2,clipPosition=0),96,96,0,0,96,96,1)
        self.assertEqual(active,band_only)
        fill=self.index.tile(self.settings(mode=6,fillMask=15,clipAxis=2,clipPosition=0),96,96,0,0,96,96,1)
        center=fill[(48*96+48)*4:(48*96+48)*4+4]
        self.assertEqual(center[3],255)
        self.assertGreater(center[0],center[2])
        # Fill traversal is independent of continuous-SDF march step.
        a=self.index.tile(self.settings(mode=6,step=.125),96,96,0,0,96,96,1)
        b=self.index.tile(self.settings(mode=6,step=1),96,96,0,0,96,96,1)
        self.assertEqual(a,b)
        # Strip rendering still agrees for the hierarchical mode.
        settings=self.settings(mode=6,clipAxis=2,clipPosition=0)
        whole=self.index.tile(settings,95,71,0,0,95,71,4)
        strips=b"".join(self.index.tile(settings,95,71,0,y,95,min(13,71-y),4) for y in range(0,71,13))
        self.assertEqual(whole,strips)

    def test_sign_slice_and_clip(self):
        settings = self.settings(mode=3,clipAxis=2,clipPosition=0)
        image = self.index.tile(settings,128,128,0,0,128,128,1)
        center = image[(64*128+64)*4:(64*128+64)*4+4]
        self.assertGreater(center[0],center[2])  # negative interior is warm
        # A plane behind the whole object must remove every surface hit.
        settings = self.settings(clipAxis=2,clipPosition=-100)
        image = self.index.tile(settings,64,64,0,0,64,64,1)
        self.assertFalse(any(image[3::4]))

    def test_camera_inside_and_parallel_slabs(self):
        settings = self.settings(eye=[0,0,0],target=[0,0,1],orthographic=0)
        image = self.index.tile(settings,32,32,0,0,32,32,1)
        self.assertTrue(all(v==255 for v in image[3::4]))

    def test_png_metadata_crc_and_failure_atomicity(self):
        path=self.directory/"figure.png"
        settings=self.sphere.defaults()
        render_file(self.sphere,path,settings,97,73,4)
        content=path.read_bytes()
        self.assertEqual(content[:8],b"\x89PNG\r\n\x1a\n")
        offset=8; compressed=b""; metadata=None
        while offset<len(content):
            size=struct.unpack_from(">I",content,offset)[0]
            kind=content[offset+4:offset+8]; data=content[offset+8:offset+8+size]
            crc=struct.unpack_from(">I",content,offset+8+size)[0]
            self.assertEqual(crc,zlib.crc32(kind+data)&0xffffffff)
            if kind==b"IDAT":compressed+=data
            if kind==b"tEXt":metadata=json.loads(data.split(b"\x00",1)[1])
            offset+=size+12
        self.assertEqual(metadata["settings"],settings)
        self.assertEqual(len(zlib.decompress(compressed)),73*(97*4+1))
        settings["iso"]=1000
        with self.assertRaisesRegex(RuntimeError,"narrow band"):
            render_file(self.sphere,path,settings,97,73,4)
        self.assertEqual(path.read_bytes(),content)

    def test_invalid_input_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"Missing MeshToSDF channel"):
            Renderer(self.directory/"missing-channel.nvdb",self.library)
        invalid=self.sphere.defaults(); invalid["step"]=0
        with self.assertRaises(ValueError):validate_settings(invalid)
        invalid=self.sphere.defaults(); invalid["eye"]=[math.nan,0,0]
        with self.assertRaises(ValueError):validate_settings(invalid)
        with self.assertRaises(ValueError):list(self.sphere.png(self.sphere.defaults(),-1,100,1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
