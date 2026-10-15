#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Inspect actual NanoVDB root tiles in Polyscope with a triangle-mesh reference.

Reuses the original scripts/mesh_to_sdf_viewer.py's OBJ loader and sign palette.
Root size/alignment uses that viewer's sparse-volume-grid convention unchanged.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import zlib
from viewer import png_chunk

import numpy as np
import polyscope as ps

HERE=Path(__file__).resolve().parent


def original_helpers():
    path=HERE.parents[1]/'scripts/mesh_to_sdf_viewer.py'
    spec=importlib.util.spec_from_file_location('original_mesh_sdf_viewer',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def load_scene(grid,exporter,upper_fill=False,refresh=False):
    grid=grid.resolve();cache=grid.with_suffix('.polyscope-roots.json');stat=grid.stat()
    source=dict(path=str(grid),size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    if cache.exists() and not refresh:
        data=json.loads(cache.read_text())
        if data.get('source')==source and (not upper_fill or data.get('upper_fill_included')):return data
    command=[str(exporter.resolve()),str(grid)]+(['--upper-fill'] if upper_fill else [])
    result=subprocess.run(command,text=True,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr)
    data=json.loads(result.stdout);data['source']=source
    cache.write_text(json.dumps(data,separators=(',',':'))+'\n')
    return data


CELL_NAMES=('leaf','lower','upper','root','active')
CELL_SIZES=(1,8,128,4096,1)
CELL_DTYPE=np.dtype([('base','<i4',(3,)),('sdf','<f4')])


def load_cells(grid,data,exporter,roi,whole,refresh):
    grid=grid.resolve()
    if roi is None:
        if not data['upper_origins']:raise ValueError('No Upper nodes for automatic ROI')
        bounds=np.asarray(data['upper_origins'],dtype=np.int64)
        roots=data['root_origins']
        anchor=[0,0,0] if [0,0,0] in roots else (roots[0] if roots else bounds[0].tolist())
        z=anchor[2]+2048
        roi=[int(bounds[:,0].min()),int(bounds[:,1].min()),z,int(bounds[:,0].max())+4095,int(bounds[:,1].max())+4095,z]
    if any(roi[a]>roi[a+3] for a in range(3)):raise ValueError('Inverted ROI')
    key='whole-grid' if whole else 'roi_'+'_'.join(str(v) for v in roi)
    directory=grid.with_suffix('.polyscope-cells')/key
    directory.mkdir(parents=True,exist_ok=True);manifest=directory/'manifest.json'
    source=data['source']
    selected=None
    if manifest.exists() and not refresh:
        cached=json.loads(manifest.read_text())
        if cached.get('source')==source:
            counts=cached['cell_selection']['counts']
            if all((directory/(name+'.bin')).exists() and (directory/(name+'.bin')).stat().st_size==count*CELL_DTYPE.itemsize
                   for name,count in zip(CELL_NAMES,counts)):selected=cached
    if selected is None:
        manifest.unlink(missing_ok=True)
        command=[str(exporter.resolve()),str(grid),'--cells-dir',str(directory)]
        command+=['--all-cells'] if whole else ['--roi']+[str(v) for v in roi]
        result=subprocess.run(command,text=True,capture_output=True)
        if result.returncode:raise RuntimeError(result.stderr)
        selected=json.loads(result.stdout);selected['source']=source
        manifest.write_text(json.dumps(selected,separators=(',',':'))+'\n')
    result={}
    for name,count in zip(CELL_NAMES,selected['cell_selection']['counts']):
        result[name]=np.memmap(directory/(name+'.bin'),dtype=CELL_DTYPE,mode='r',shape=(count,)) if count else np.empty(0,dtype=CELL_DTYPE)
    return result,selected['cell_selection']


def find_mesh(grid,explicit):
    if explicit:return explicit.resolve()
    copied=grid.with_suffix('.obj')
    if copied.exists():return copied.resolve()
    raise ValueError('Pass --mesh with the mesh in the same world coordinates as the grid')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('grid',type=Path)
    parser.add_argument('--mesh',type=Path,help='reference OBJ in grid world coordinates; default: sibling .obj')
    parser.add_argument('--compare',type=Path,help='second actual grid, shown beside the first')
    parser.add_argument('--compare-mesh',type=Path)
    parser.add_argument('--label',default='result')
    parser.add_argument('--compare-label',default='comparison')
    parser.add_argument('--all-levels',action='store_true',help='show exact leaf/lower/upper/root fill and active cells in a selected ROI; default is a one-voxel Z slab')
    parser.add_argument('--roi',nargs=6,type=int,metavar=('MIN_X','MIN_Y','MIN_Z','MAX_X','MAX_Y','MAX_Z'),help='inclusive index-space cell selection, implies --all-levels')
    parser.add_argument('--whole-grid',action='store_true',help='explicitly export/register every cell at all levels; intended for grids that fit memory')
    parser.add_argument('--upper-fill',action='store_true',help='also extract stored inactive negative 128-cubed tiles (initially hidden)')
    parser.add_argument('--show-upper-fill',action='store_true',help='extract and initially show negative 128-cubed tiles')
    parser.add_argument('--mesh-alpha',type=float,default=.22)
    parser.add_argument('--slice',action='store_true',help='add an adjustable scene slice through the intended root center')
    parser.add_argument('--exporter',type=Path,default=HERE/'build/sdf_export_polyscope_roots')
    parser.add_argument('--refresh',action='store_true',help='ignore cached metadata and reread the actual grid')
    parser.add_argument('--headless',action='store_true',help='use Polyscope EGL backend; requires --screenshot')
    parser.add_argument('--screenshot',type=Path)
    parser.add_argument('--width',type=int,default=1440)
    parser.add_argument('--height',type=int,default=1000)
    parser.add_argument('--frames',type=int,help='exit the GUI after this many frames (smoke check)')
    args=parser.parse_args()
    if not 0<args.mesh_alpha<=1:parser.error('mesh alpha must be in (0,1]')
    if args.headless and not args.screenshot:parser.error('--headless requires --screenshot')
    if args.width<1 or args.height<1:parser.error('positive image dimensions required')
    if '#' in args.label or '#' in args.compare_label:parser.error('Polyscope structure names cannot contain #')
    screenshot=args.screenshot.resolve() if args.screenshot else None
    helper=original_helpers();scenes=[]
    all_levels=args.all_levels or args.roi is not None or args.whole_grid
    for grid,mesh,label in [(args.grid,args.mesh,args.label)]+([(args.compare,args.compare_mesh,args.compare_label)] if args.compare else []):
        data=load_scene(grid,args.exporter,(args.upper_fill or args.show_upper_fill) and not all_levels,args.refresh)
        cells,selection=load_cells(grid,data,args.exporter,args.roi,args.whole_grid,args.refresh) if all_levels else (None,None)
        vertices,faces=helper.load_obj(str(find_mesh(grid,mesh)))
        if not len(vertices) or not len(faces):raise ValueError('Empty reference mesh')
        scenes.append((data,vertices,faces,label,cells,selection))
    state_dir=HERE/'output/polyscope';state_dir.mkdir(parents=True,exist_ok=True)
    os.chdir(state_dir)  # Keep Polyscope preferences out of the user's existing .polyscope.ini.
    ps.init('openGL3_egl' if args.headless else 'openGL3_glfw')
    ps.set_window_size(args.width,args.height);ps.set_up_dir('y_up');ps.set_ground_plane_mode('none')
    ps.set_transparency_mode('pretty');ps.set_transparency_render_passes(32 if screenshot else 8);ps.set_SSAA_factor(2 if screenshot else 1)
    visible=[];shifts=[];previous_high=None
    for data,vertices,faces,label,cells,selection in scenes:
        dx=data['voxel_size'];tr=np.asarray(data['translation']);roots=np.asarray(data['root_origins'],dtype=np.int64).reshape(-1,3)
        low=vertices.min(axis=0);high=vertices.max(axis=0)
        if len(roots):
            low=np.minimum(low,tr+(roots.min(axis=0)-.5)*dx)
            high=np.maximum(high,tr+(roots.max(axis=0)+4095.5)*dx)
        offset=np.zeros(3)
        if previous_high is not None:offset[0]=previous_high-low[0]+.35*max(high-low)
        previous_high=high[0]+offset[0];shifts.append(offset)
        visible.extend([low+offset,high+offset])
        # Exactly the old viewer's convention: base//size, cell_width=size*dx,
        # shared origin translation - 0.5*dx (not half a coarse cell).
        origin=tr-.5*dx+offset
        def register(name,bases,size,sign=None,enabled=True,wire=False):
            bases=np.asarray(bases,dtype=np.int64).reshape(-1,3)
            if not len(bases):return None
            if np.any(bases%size):raise ValueError(f'Unaligned {name}')
            grid=ps.register_sparse_volume_grid(f'{label}: {name}',origin,(size*dx,)*3,bases//size,
                enabled=enabled,cube_size_factor=0.,wireframe_radius=.005,edge_width=0.,color=helper.INTERIOR_RGB if sign==-1 else (.55,.57,.6),
                render_mode='wireframe' if wire else 'gridcube')
            if grid.n_cells()!=len(bases):raise RuntimeError(f"Polyscope cell count differs for {name}")
            grid.set_cull_whole_elements(False)
            if sign is not None:
                grid.add_color_quantity('sign',helper.sign_to_rgb(np.full(len(bases),sign)),defined_on='cells',enabled=True)
            return grid
        if cells is None:
            register('negative root tiles (4096³)',roots,4096,-1)
        else:
            for name,size in zip(CELL_NAMES[:4],CELL_SIZES[:4]):
                register(f'negative {name} fill ({size}³)',cells[name]['base'],size,-1)
            active=register('active signed voxels (1³)',cells['active']['base'],1)
            if active is not None:
                values=cells['active']['sdf'];signs=np.where(np.signbit(values),-1,1)
                active.add_color_quantity('sign',helper.sign_to_rgb(signs),defined_on='cells',enabled=True)
                active.add_scalar_quantity('signed SDF',values,defined_on='cells',enabled=False)
            print(f"{label}: exact cell selection {selection}; all five groups are independently toggleable",flush=True)
        register('unmarked root positions (+background)',data['unmarked_root_origins'],4096,+1,enabled=False)
        register('Upper children (root-scale wireframe)',data['upper_origins'],4096,enabled=False,wire=True)
        if (args.upper_fill or args.show_upper_fill) and not all_levels:
            register('negative upper fill (128³)',data['upper_fill_origins'],128,-1,enabled=args.show_upper_fill)
        if data['root_child_overlaps']:print(f"WARNING {label}: raw root flags overlap Upper children: {data['root_child_overlaps']}")
        mesh=ps.register_surface_mesh(f'{label}: input triangle mesh (reference)',vertices+offset,faces,
            color=(.48,.62,.76),smooth_shade=True,transparency=args.mesh_alpha)
        mesh.set_cull_whole_elements(False)
        print(f"{label}: {len(roots)} raw negative roots, {len(data['upper_origins'])} Upper children, "
              f"{len(data['unmarked_root_origins'])} unmarked root positions; {data['active_voxels']:,} active voxels in source",flush=True)
    if all_levels:
        import polyscope.imgui as ui
        def selection_info():
            ui.TextUnformatted('Exact stored cells at native sizes; no sampling.')
            for scene in scenes:
                selected=scene[5];ui.TextUnformatted(f"{scene[3]}: "+('whole grid' if selected['all'] else f"index ROI {selected['roi']}"))
                ui.TextUnformatted('leaf / lower / upper / root / active: '+str(selected['counts']))
        ps.set_user_callback(selection_info)
    if args.slice:
        plane=ps.add_scene_slice_plane();data=scenes[0][0]
        center=np.asarray(data['translation'])+2047.5*data['voxel_size']+shifts[0]
        plane.set_pose(center,(0,0,1));plane.set_draw_plane(False)
    bounds=np.asarray(visible);center=(bounds.min(axis=0)+bounds.max(axis=0))/2
    radius=np.linalg.norm(bounds.max(axis=0)-bounds.min(axis=0))/2
    direction=np.array([.55,.25,1.]);direction/=np.linalg.norm(direction)
    ps.set_bounding_box(bounds.min(axis=0),bounds.max(axis=0));ps.set_length_scale(2*radius)
    ps.look_at(center+direction*radius*2.8,center)
    if args.screenshot:
        path=screenshot;path.parent.mkdir(parents=True,exist_ok=True)
        # Buffer capture is synchronous; named screenshots may be queued by the backend.
        ps.frame_tick();ps.frame_tick()
        rgba=ps.screenshot_to_buffer(transparent_bg=False,vertical_flip=True,include_UI=False)
        height,width=rgba.shape[:2];compressor=zlib.compressobj(3)
        with path.open('wb') as output:
            output.write(b'\x89PNG\r\n\x1a\n')
            output.write(png_chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0)))
            output.write(png_chunk(b'sRGB',b'\x00'));output.write(png_chunk(b'pHYs',struct.pack('>IIB',11811,11811,1)))
            metadata=[dict(label=s[3],source=s[0]['source'],selection=s[5]) for s in scenes]
            output.write(png_chunk(b'tEXt',b'PolyscopeMeshSDF\x00'+json.dumps(metadata).encode('ascii')))
            for row in rgba:
                compressed=compressor.compress(b'\x00'+row.tobytes())
                if compressed:output.write(png_chunk(b'IDAT',compressed))
            output.write(png_chunk(b'IDAT',compressor.flush()));output.write(png_chunk(b'IEND',b''))
        print(f'Saved {path}',flush=True)
    if not args.headless:ps.show(forFrames=args.frames)
    ps.shutdown()


if __name__=='__main__':main()
