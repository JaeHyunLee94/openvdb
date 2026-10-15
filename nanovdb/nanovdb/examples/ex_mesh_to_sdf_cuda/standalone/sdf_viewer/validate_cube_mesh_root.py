#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run actual closed-cube OBJ -> MeshToSDF -> analytic root-tile verification."""
import argparse
from collections import Counter
import ctypes as C
import hashlib
import json
import itertools
import math
from pathlib import Path
import subprocess
import time

HERE=Path(__file__).resolve().parent


def read_cube(path):
    vertices=[];faces=[];text=path.read_text().splitlines()
    for line in text:
        words=line.split("#",1)[0].split()
        if not words:continue
        if words[0]=='v':vertices.append([float(v) for v in words[1:4]])
        elif words[0]=='f':
            ids=[int(v.split('/')[0]) for v in words[1:]]
            ids=[v-1 if v>0 else len(vertices)+v for v in ids]
            faces.extend((ids[0],ids[i-1],ids[i]) for i in range(2,len(ids)))
    if not vertices or not faces:raise ValueError('OBJ has no triangle geometry')
    lo=[min(v[a] for v in vertices) for a in range(3)]
    hi=[max(v[a] for v in vertices) for a in range(3)]
    length=hi[0]-lo[0];tol=length*1.e-6
    if length<=0 or any(abs(hi[a]-lo[a]-length)>tol for a in range(3)):
        raise ValueError('This analytic oracle requires an axis-aligned cube')
    edges=Counter();directed=Counter();area=0.;volume=0.
    for face in faces:
        if any(i<0 or i>=len(vertices) for i in face):raise ValueError('Bad OBJ face index')
        if not any(all(abs(vertices[i][a]-bound)<tol for i in face) for a in range(3) for bound in (lo[a],hi[a])):
            raise ValueError('A triangle is not on the analytic cube boundary')
        a,b,c=[vertices[i] for i in face]
        u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        triangle_area=sum(x*x for x in cross)**.5/2
        if triangle_area<=length*length*1.e-14:raise ValueError('Degenerate triangle')
        area+=triangle_area
        center=[(lo[i]+hi[i])/2 for i in range(3)]
        volume+=sum((a[i]-center[i])*cross[i] for i in range(3))/6
        for a,b in zip(face,face[1:]+face[:1]):
            edges[tuple(sorted((a,b)))]+=1;directed[(a,b)]+=1
    if any(count!=2 for count in edges.values()):raise ValueError('Mesh is not closed: edge incidence is not two')
    if any(directed[(a,b)]!=1 or directed[(b,a)]!=1 for a,b in edges):
        raise ValueError('Inconsistent face orientation')
    if abs(area-6*length**2)>length**2*1.e-5 or abs(abs(volume)-length**3)>length**3*1.e-5:
        raise ValueError('Surface area or enclosed volume differs from an exact cube')
    return text,vertices,lo,hi,length,len(faces),dict(surface_area=area,signed_volume=volume,consistent_orientation=True)


class Memory(C.Structure):
    _fields_=[('total',C.c_uint64),('free',C.c_uint64),('used',C.c_uint64)]


def memory_reader():
    try:
        nvml=C.CDLL('libnvidia-ml.so.1')
        if nvml.nvmlInit_v2()!=0:return None
        device=C.c_void_p()
        if nvml.nvmlDeviceGetHandleByIndex_v2(0,C.byref(device))!=0:return None
        def read():
            data=Memory()
            if nvml.nvmlDeviceGetMemoryInfo(device,C.byref(data))!=0:return None
            return data.used
        return read
    except OSError:return None


def verify_probes(grid,bounds,resolution,library):
    from viewer import Renderer
    renderer=Renderer(grid,library)
    try:
        axis=sorted(set([-4096,-8,-6,-2,0,resolution//8,resolution//2,resolution-1,
                         resolution+1,resolution+3,resolution+6,resolution+8,max(8192,resolution+4096)]))
        positions=list(itertools.product(axis,repeat=3))
        values=renderer.probe(positions)
        dx=renderer.info['voxelSize'][0]
        for p,v in zip(positions,values):
            inside=all(bounds[a]<p[a]*dx<bounds[a+3] for a in range(3))
            if (math.copysign(1,v)<0)!=inside:
                raise RuntimeError(f'Analytic sign mismatch at {p}: {v}, expected inside={inside}')
        return dict(passed=True,count=len(positions),coordinates_per_axis=axis),renderer.info['fillBoxes']
    finally:renderer.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mesh',type=Path)
    parser.add_argument('--resolution',type=int,default=4096,help='interior grid span; actual side is resolution+8 cells')
    parser.add_argument('--band',type=float,default=1.5)
    parser.add_argument('--output-dir',type=Path,default=HERE/'output/mesh-root')
    parser.add_argument('--converter',type=Path,default=HERE/'build/sdf_from_mesh')
    parser.add_argument('--checker',type=Path,default=HERE/'build/sdf_check_cube_mesh_roots')
    parser.add_argument('--probe',action='store_true',help='also verify GPU full-space sign lookups against the analytic cube')
    parser.add_argument('--library',type=Path,default=HERE/'build/libsdf_renderer.so')
    args=parser.parse_args()
    if args.resolution<16 or not 0.8661<args.band<3.5:parser.error('resolution >=16 and .8661 < band < 3.5 required')
    text,vertices,lo,hi,length,triangles,proof=read_cube(args.mesh)
    dx=length/(args.resolution+8)
    shift=[-lo[a]-4*dx for a in range(3)]
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    name=f'cube-r{args.resolution}'
    mesh=out/(name+'.obj');grid=out/(name+'.nvdb');log=out/(name+'.log')
    lines=[];n=0
    for line in text:
        if line.split()[:1]==['v']:
            lines.append('v '+' '.join(format(vertices[n][a]+shift[a],'.12g') for a in range(3)));n+=1
        else:lines.append(line)
    mesh.write_text('\n'.join(lines)+'\n')
    bounds=[lo[a]+shift[a] for a in range(3)]+[hi[a]+shift[a] for a in range(3)]
    report=dict(source_mesh=str(args.mesh.resolve()),source_sha256=hashlib.sha256(args.mesh.read_bytes()).hexdigest(),
                vertices=len(vertices),triangles=triangles,closed_edge_incidence=True,mesh_geometry_proof=proof,resolution=args.resolution,
                voxel_size=dx,band_width=args.band,translation=shift,world_bounds=bounds,output_grid=str(grid))
    command=[str(args.converter.resolve()),str(mesh),str(dx),str(args.band),'0',str(grid)]
    report['command']=command
    read_memory=memory_reader();before=read_memory() if read_memory else None;peak=before
    start=time.perf_counter()
    with log.open('w') as output:
        process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT)
        while process.poll() is None:
            current=read_memory() if read_memory else None
            if current is not None:peak=max(peak or 0,current)
            time.sleep(.005)
    report.update(seconds=round(time.perf_counter()-start,3),device_used_before_bytes=before,
                  sampled_device_peak_bytes=peak,converter_returncode=process.returncode)
    print(log.read_text(),end='',flush=True)
    if process.returncode:
        (out/(name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        raise RuntimeError(f'MeshToSDF failed; see {log}')
    verification=subprocess.run([str(args.checker.resolve()),str(grid)]+[str(v) for v in bounds],text=True,capture_output=True)
    if verification.returncode:raise RuntimeError(verification.stderr)
    report['verification']=json.loads(verification.stdout)
    if args.probe:
        report['full_space_sign_probes'],report['fill_boxes']=verify_probes(grid,bounds,args.resolution,args.library)
    (out/(name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
