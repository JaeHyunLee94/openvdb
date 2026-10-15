# Root validation from a real triangle mesh

This test runs an ordinary closed OBJ through the existing **MeshToSDF converter**,
including rasterization, active-voxel signing and `PropagateSign`. It then checks
the actual exported root mask against an independent geometric oracle. No mask
is manually inserted and no existing library source is modified.

The earlier [root tests](ROOT_FILL_VALIDATION.md) isolate connectivity with small
synthetic topologies. This test additionally exercises real triangle input.

## Why a cube and why translate it?

A root tile covers 4096³ sample positions. Reducing voxel size can create an
entirely negative root tile in a closed mesh, provided a complete **grid-aligned**
4096³ block lies inside it with no surface/active Upper child. A large bounding
box alone is insufficient: thin or curved geometry may contain no such block.

The input is a real axis-aligned closed cube OBJ, not a procedural NanoVDB grid.
The script checks edge incidence, consistent face orientation, nondegenerate
triangles on box faces, surface area and enclosed volume. This analytic oracle
is deliberately restricted to cubes; it rejects arbitrary meshes.

For cube side length L and requested resolution N, the script uses:

- `voxel_size = L / (N + 8)`
- `band_width = 1.5` voxels, `iso_value = 0`
- A translated **copy** of the mesh, placing its minimum at `-4 * voxel_size`
  on each axis. Its maximum is `(N + 4) * voxel_size`.

Shape, size, topology and the source OBJ remain unchanged. At N=4096, root
origin `(0,0,0)` covers sample coordinates 0…4095 on each axis, fully inside
the surface and beyond the narrow band. A cube centered at the origin would
straddle root boundaries and need a much larger voxelized surface to obtain
an interior root tile. Translation makes this test practical on a 12 GB GPU.

## Build and reproduce

From this directory, using the same CUDA host compiler as the renderer:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12 \
  -DBUILD_ROOT_FILL_VALIDATION=ON -DBUILD_MESH_CONVERTER=ON \
  -DCCCL_SOURCE_DIR=/absolute/path/to/cccl
cmake --build build --target sdf_from_mesh sdf_check_cube_mesh_roots sdf_renderer -j2

# Cheap control; should contain no root fill.
python3 validate_cube_mesh_root.py /path/to/cube.obj --resolution 64 --probe
# Real high-resolution root test. Requires substantial GPU memory.
python3 validate_cube_mesh_root.py /path/to/cube.obj --resolution 4096 --probe
```

`CCCL_SOURCE_DIR` defaults to the enclosing checkout's
`build/release/_deps/cccl-src`. Use a CCCL checkout compatible with the existing
MeshToSDF driver. `--converter`, `--checker` and `--library` allow testing binaries
from a different build. The script does not replace the implementation with its
own converter. The tested library revision is the one used to build those binaries.

Outputs are ignored by Git: `output/mesh-root/cube-rN.obj`, `.nvdb`, `.log` and
`.json`. Reports record the source hash, translation, mesh proof, converter
command, runtime, sampled GPU memory, complete root origins and sign probes.
Memory sampling uses NVML device 0; unavailable readings remain null.

## What is checked

`check_cube_mesh_roots.cpp` reads either coordinate-list or legacy dense root
metadata. It derives expected interior tile positions directly from the analytic
cube bounds, voxel size and band width, without using the library's fill algorithm.
It compares **complete sets** of expected and returned root origins and rejects
duplicates, misalignment, overlap with an Upper child and cube footprints crossing
the true mesh boundary. These checks are assertions, not visual judgments.

With `--probe`, the viewer's GPU lookup is also checked against analytic inside/
outside signs on a Cartesian lattice spanning the root interior, near-boundary
regions and exterior. The N=4096 run checks 2,197 locations. Deep interior values
are negative background magnitudes interpreted through masks, not exact distances
to the distant surface. This verifies full-space **sign**, not deep distance accuracy.

## Measured actual-mesh results

Input: 26 vertices, 48 triangles, side length 2, original bounds [-1,1]³.
Source SHA-256: `c096c7193e0216e0e42e98bd0f37a7551d46a7a32b9eec91ef510d4eb9f39767`.
The original working-tree converter was used with band=1.5, iso=0.

| N | Voxel size | Active voxels | Grid bytes | Expected / returned root tiles |
|---|---:|---:|---:|---:|
| 512 | 0.00384615385 | 4,867,246 | 30,947,456 | 0 / 0 |
| 1024 | 0.00193798450 | 19,170,478 | 111,627,392 | 0 / 0 |
| 4096 | 0.000487329435 | 303,170,734 | 1,697,094,784 | 1 / 1 |

All three complete-set geometric checks passed. The 4096 case returned exactly
`(0,0,0)`, with no Upper child there, and all 2,197 sign probes passed. That single
root tile represents **68,719,476,736** inside sample positions without allocating
a dense field of that size. Viewer inactive fill counts `[1,8,128,4096]` were
`[251965565,0,0,1]`, reflecting the actual masks, not a forced coarsening.

On the RTX PRO 3000 Blackwell Laptop GPU, conversion plus file writing took
6.182 s. The largest sampled **total device usage** was 10,830,807,040 bytes
(10.09 GiB), including approximately 1.30 GiB already occupied before conversion.
Sampling every 5 ms is an observation, not an exact allocator peak or a portable
memory requirement. The grid itself occupies about 1.58 GiB. Finer voxel sizes,
wider bands or complex geometry can exceed available memory.

The N=64 control and its 2,197 sign probes also passed against both the current
working-tree converter (no root channel) and the committed converter (legacy dense
root metadata). The high-resolution measurements above use the current working
tree, not a rerun against the older committed converter.

This demonstrates a successful real mesh pipeline case. It does not prove all
mesh-signing cases or guarantee that a bunny/hairball will contain root fill.

## Inspect the real result

```bash
python3 viewer.py output/mesh-root/cube-r4096.nvdb --port 8768 --open
```

Choose **Full-space signed cells**. Leave only **Root** checked to see the one
4096³ orange cell. Re-enable active cells and other fill levels, then clip through
the interior to see the negative root together with the thin signed surface band.
All negative levels use the same orange base color; positive active voxels are blue.
This is a direct cell rendering, not an extracted isosurface.

The development workstation also has local camera/export artifacts (not in Git):

- `output/mesh-root/cube-real-mesh-camera.json`: clipped band plus interior fill.
- `output/mesh-root/cube-real-root-only-camera.json`: only the real root cell.
- `output/mesh-root/cube-real-mesh-root-4k.png`: 3840×2160, 4 samples/pixel.
- `output/mesh-root/cube-real-mesh-root-only.png`: isolated root cell.

```bash
python3 viewer.py output/mesh-root/cube-r4096.nvdb \
  --settings output/mesh-root/cube-real-mesh-camera.json --port 8768 --open
python3 viewer.py output/mesh-root/cube-r4096.nvdb \
  --settings output/mesh-root/cube-real-mesh-camera.json \
  --render output/mesh-root/cube-real-mesh-root-4k.png \
  --width 3840 --height 2160 --samples 4
```
