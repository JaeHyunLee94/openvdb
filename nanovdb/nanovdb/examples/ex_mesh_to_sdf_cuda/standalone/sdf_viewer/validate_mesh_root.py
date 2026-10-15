#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Translate a closed OBJ, run real MeshToSDF, verify root geometry and GPU signs."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess
import time
from validate_cube_mesh_root import memory_reader
from viewer import Renderer

HERE=Path(__file__).resolve().parent


def run_json(command,allow_failure=False,**kwargs):
    result=subprocess.run([str(v) for v in command],text=True,capture_output=True,**kwargs)
    if result.returncode and not (allow_failure and result.returncode==2):raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def check_signs(mesh,grid,geometry,library):
    renderer=Renderer(grid,library)
    try:
        info=renderer.info;dx=info['voxelSize'][0]
        axis=[-4096,-1,0,512,2048,3584,4095,4096,8192]
        points=list(itertools.product(axis,repeat=3))
        rng=random.Random(20261015)
        points += [tuple(rng.randint(info['indexMin'][a]-128,info['indexMax'][a]+128) for a in range(3)) for _ in range(1024)]
        query=''.join(' '.join(str(v*dx) for v in p)+f' {2*dx}\n' for p in points)
        truth=run_json([geometry,mesh,'--points'],input=query)
        values=renderer.probe(points);checked=0;negative=0;skipped=0;mismatches=[]
        for p,v,t in zip(points,values,truth):
            if t['skip']:skipped+=1;continue
            if (v<0)!=t['inside']:mismatches.append(dict(index=p,value=v,oracle=t))
            checked+=1;negative+=t['inside']
        if not checked or negative==0 or negative==checked:raise RuntimeError('Probe coverage needs both signs')
        return dict(passed=not mismatches,checked=checked,inside=negative,outside=checked-negative,skipped_near_surface=skipped,mismatches=mismatches),info
    finally:renderer.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mesh',type=Path)
    parser.add_argument('--resolution',type=int,default=4096)
    parser.add_argument('--band',type=float,default=3.0)
    parser.add_argument('--managed',action='store_true',help='use the separately linked Unified Memory driver')
    parser.add_argument('--output-dir',type=Path,default=HERE/'output/general-mesh-root')
    parser.add_argument('--geometry',type=Path,default=HERE/'build/sdf_analyze_mesh_root')
    parser.add_argument('--converter',type=Path)
    parser.add_argument('--library',type=Path,default=HERE/'build/libsdf_renderer.so')
    parser.add_argument('--verify-only',action='store_true',help='check existing outputs without redoing conversion')
    args=parser.parse_args()
    if args.resolution<32 or not .8661<args.band<3.5:parser.error('resolution >=32 and .8661 < band <3.5 required')
    geometry=args.geometry.resolve()
    analysis=run_json([geometry,args.mesh.resolve()])
    if abs(abs(analysis['winding'])-1)>1e-5:raise RuntimeError('Candidate cube center has ambiguous winding')
    # A surface-free inner cube with eight extra voxels of margin on each face.
    dx=2*analysis['cube_half_width']/(args.resolution+16)
    shift=[(args.resolution/2-.5)*dx-c for c in analysis['cube_center']]
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    name=f'{args.mesh.stem}-r{args.resolution}'
    mesh=out/(name+'.obj');grid=out/(name+'.nvdb');report_path=out/(name+'.json');log=out/(name+'.log')
    report=dict(source_mesh=str(args.mesh.resolve()),source_sha256=hashlib.sha256(args.mesh.read_bytes()).hexdigest(),
                analysis=analysis,resolution=args.resolution,voxel_size=dx,band_width=args.band,translation=shift,
                output_grid=str(grid),managed=args.managed)
    if not args.verify_only:
        lines=[]
        for line in args.mesh.read_text().splitlines():
            words=line.split()
            if words[:1]==['v']:
                p=[float(v) for v in words[1:4]]
                line='v '+' '.join(format(p[a]+shift[a],'.12g') for a in range(3))
            lines.append(line)
        mesh.write_text('\n'.join(lines)+'\n')
        converter=(args.converter or HERE/('build/sdf_from_mesh_managed' if args.managed else 'build/sdf_from_mesh')).resolve()
        command=[str(converter),str(mesh),str(dx),str(args.band),'0',str(grid)]
        report['command']=command
        read=memory_reader();before=read() if read else None;peak=before;start=time.perf_counter()
        with log.open('w') as stream:
            process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    v=read() if read else None
                    if v is not None:peak=max(peak or 0,v)
                    time.sleep(.05)
            except BaseException:
                process.terminate();process.wait();raise
        report.update(seconds=round(time.perf_counter()-start,3),converter_returncode=process.returncode,
                      device_used_before_bytes=before,sampled_device_peak_bytes=peak)
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        print(log.read_text(),end='',flush=True)
        if process.returncode:raise RuntimeError(f'Converter failed; see {log}')
    else:
        previous=json.loads(report_path.read_text())
        for key in ['source_sha256','resolution','band_width']:
            if previous[key]!=report[key]:raise RuntimeError(f'Existing output has different {key}; use matching arguments')
        report=previous
    result=run_json([geometry,mesh,grid],allow_failure=True);report['root_geometry_verification']=result
    report['expected_origin_present']=args.resolution<4096 or any(p['origin']==[0,0,0] for p in result['roots'])
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    report['sign_probes'],report['viewer_info']=check_signs(mesh,grid,geometry,args.library.resolve())
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    if not (result['passed'] and report['expected_origin_present'] and report['sign_probes']['passed']):
        raise RuntimeError('Root geometry or GPU signs disagree with the independent mesh oracle; see report')


if __name__=='__main__':main()
