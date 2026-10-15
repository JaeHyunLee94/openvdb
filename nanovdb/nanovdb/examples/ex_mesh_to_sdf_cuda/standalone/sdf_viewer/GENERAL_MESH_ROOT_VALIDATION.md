# Root tiles from an ordinary closed mesh

`validate_mesh_root.py` extends the cube experiment to ordinary triangle OBJs.
It runs the existing MeshToSDF driver, reads its actual root mask, and independently
checks the returned cubes against the input triangles. No library files are edited.
The selected development input is **bunny.obj**, not a procedural grid or cube.
**The N=4096, band=3 run passed:** exactly one interior root and 1,749 independent
GPU sign comparisons. Band=2 at the same voxel size is a retained failing case.

## Geometry and grid alignment

`sdf_analyze_mesh_root` builds a CPU BVH over double-precision triangles. It requires
nondegenerate triangles and closed, consistently oriented edges. It searches a
coarse lattice, then refines several seeds to find a large axis-aligned cube
inside the mesh. This is a heuristic search, **not a globally optimal cube solver**.
Triangle/cube intersection uses separating-axis tests. Final root centers use
summed triangle solid angles to establish interior winding independently of SDF.

The source mesh is unchanged. A translated copy aligns a candidate interior cube
with root index origin `(0,0,0)`; no scaling, clipping, capping or mesh replacement
is performed. Given candidate half-width r and resolution N:

```
voxel_size = 2*r / (N + 16)
translation[a] = (N/2 - 0.5)*voxel_size - candidate_center[a]
```

At N=4096, this leaves approximately eight voxels of clearance between the root
cube footprint and the candidate surface contact. Smaller N values are controls;
they do not make a 4096³ interior root cube fit.

For the supplied bunny, the search found r=0.274624566064 around original world
position `(0.139458075, -0.354110601, 0.109449426)`. At N=4096 the voxel size is
approximately `0.000133572260`. Shape, topology, source vertices and triangles are
preserved apart from translation in the copied OBJ.

## Build

From this directory:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12 \
  -DBUILD_ROOT_FILL_VALIDATION=ON -DBUILD_MESH_CONVERTER=ON \
  -DBUILD_MANAGED_MESH_CONVERTER=ON \
  -DCCCL_SOURCE_DIR=/absolute/path/to/cccl
cmake --build build --target sdf_analyze_mesh_root sdf_from_mesh \
  sdf_from_mesh_managed sdf_renderer -j2
```

The optional managed driver is for GNU/Linux. It compiles the **same existing
MeshToSDF driver sources** and links `managed_alloc.cu`. GNU ld `--wrap` redirects
application `cudaMalloc`/`cudaMallocAsync` calls to `cudaMallocManaged`; asynchronous
free synchronizes its stream before freeing. The algorithms and parameters are
unchanged, while allocation and scheduling behavior differ. This requires a CUDA
GPU/platform supporting managed-memory oversubscription and sufficient system RAM.
It can be much slower than resident device memory; these runs are correctness
experiments, not MeshToSDF performance benchmarks. The original converter target
retains its original allocation behavior.

## Run and verify

```bash
# CPU analysis only; no CUDA allocation.
build/sdf_analyze_mesh_root /path/to/bunny.obj

# Small managed and ordinary-allocation controls.
python3 validate_mesh_root.py /path/to/bunny.obj --resolution 256 --band 2 --managed \
  --output-dir output/general-mesh-root/managed-control
python3 validate_mesh_root.py /path/to/bunny.obj --resolution 256 --band 2 \
  --output-dir output/general-mesh-root/native-control

# Actual root-scale bunny; substantial system RAM and VRAM required.
python3 validate_mesh_root.py /path/to/bunny.obj --resolution 4096 --band 3 --managed \
  --output-dir output/general-mesh-root/band3

# Recheck saved outputs without rerunning expensive conversion.
python3 validate_mesh_root.py /path/to/bunny.obj --resolution 4096 --band 3 --managed --verify-only \
  --output-dir output/general-mesh-root/band3
```

Reports, translated meshes, logs and grids stay under ignored `output/` directories.
The report records the original source hash, geometry analysis, transform, converter
command, runtime, sampled total device memory, root origins and sign probes.
NVML readings measure device 0 and include other processes. Managed allocation
high-water messages measure live wrapped allocations, not physical GPU residency.

For **each actual returned root**, the independent checker asserts:

- 4096 alignment, uniqueness and absence of an overlapping Upper child.
- No triangle intersects the entire world-space cube footprint, including the
  half-voxel footprint outside the outermost sample centers.
- Absolute solid-angle winding at the cube center is 1 within tolerance.

The script additionally requires the deliberately aligned root `(0,0,0)` for
N≥4096. This tests that known interior tile's presence and checks all returned
tiles for leakage. It does **not** enumerate every possible missing interior tile
of an arbitrary mesh, prove the whole field, or certify self-intersection-free
input. The geometry checker assumes the axis-aligned uniform transform used by
this converter; arbitrary rotated/anisotropic external grids are outside scope.

GPU full-space sign queries cover a fixed root-scale lattice plus 1,024 reproducible
random positions spanning the active index bounds and exterior. CPU solid-angle
winding and ray parity must agree. Samples whose small cube intersects the surface
within two voxel widths are excluded, avoiding claims about near-surface discretization.
Both inside and outside samples are required, and mismatches fail the run.

## Band-width observations

With the current working-tree implementation and translated N=256 bunny, bands
1 and 1.5 produced a negative full-space lookup at `(-4096,-4096,-4096)`, while
independent triangle winding classified that location outside. Bands 2 and 3
passed the sampled sign checks. The high-resolution band=2 run below nevertheless failed. The default is therefore
band=3, which passed the high-resolution checks; reducing band merely to fit VRAM
did not give a valid high-resolution result for this input. This observation
has not isolated the cause to a particular signing, propagation or decoding step.
No library fix or mask correction is applied by this test.

## View the generated grid

```bash
python3 viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb --port 8768 --open
```

Use **Full-space signed cells**. With only **Root** enabled, inspect the actual
4096³ cell. Enable active cells and the other interior levels, then clip through
the root center (Z=2047.5 in index space) to see it inside the recognizable bunny.
All negative cells retain the same orange base color; positive active cells are blue.
This mode renders stored cells at their native sizes, not a zero-crossing mesh.

## Recorded high-resolution band=2 counterexample

The current working-tree bunny converter completed N=4096, band=2 in 119.13 s
using Unified Memory. It exported **1,270,113,740 active voxels**, a
7,466,385,728-byte grid and **15 negative root tiles**. Live wrapped allocations
reached approximately 36.24 GiB (including nonresident managed pages).

The intended `(0,0,0)` root is fully inside the triangles: winding=1 and no surface
intersection. **The other 14 returned roots are outside**: winding≈0, also with
no surface intersection. For example `(-8192,-4096,-4096)` is an exterior root
classified as negative by the actual exported metadata. This test therefore
**fails**, despite successfully producing the intended interior root. No invalid
tiles are removed or recolored by the tool.

The independent checker accepted the previously verified real cube root and
passed known cube inside/outside/near-surface point controls. N=256 bunny with
band=2 gave matching active counts, fill counts and sampled sign results with
the native and managed drivers. These controls support investigating the actual
pipeline output, but do not establish the failing stage or exhaustively prove
allocation-adapter equivalence at oversubscribed sizes.

The failed dataset is retained at `output/general-mesh-root/bunny-r4096.nvdb`,
with full coordinate/winding details in the adjacent JSON report. This is a
useful regression input, not a claim of successful full-space signing. The
library must be investigated separately before these settings are used for
paper figures that assert correct signs.

## Passing high-resolution band=3 result

The same working-tree converter, geometry, voxel size and translation with band=3
produced the following actual output:

| Property | Observed result |
|---|---:|
| Source vertices / triangles | 3,301 / 6,598 |
| Source SHA-256 | `d97f4aa37c2f3bfb14eceb3d06ac1f466062dc45f08e019bfbae9704c28654b6` |
| Voxel size, requested | 0.00013357225975875247 |
| Voxel size, stored float | 0.000133572262711823 |
| Active voxels | 1,905,116,810 |
| Grid bytes | 10,214,521,472 (9.51 GiB) |
| Negative root tiles | **1, at (0,0,0)** |
| Root center absolute winding | 1.0000000000000049 |
| Root footprint intersects triangles | **false** |
| GPU sign probes | **1,749 passed**, 587 inside / 1,162 outside |
| Excluded probes within two voxels of surface | 4 |
| Inactive box counts, sizes [1,8,128,4096] | [1603740796,51610993,103346,1] |
| Converter plus file writing | 256.606 s |
| Live managed allocation high water, rounded log | 51.60 GiB |

The single root represents 68,719,476,736 interior sample locations without dense
storage. No exterior root was returned in this run. This proves the stated checks
for this input/settings, not every voxel's exact distance or universal correctness.
The failing band=2 result remains important: passing at one band does not make
narrower bands automatically safe or identify which pipeline stage is responsible.

The workstation has 62 GiB host RAM and a 12,227 MiB GPU. Unified Memory used
system memory and swap pressure occurred during the large comparison. This is
not a timing benchmark, nor a claim that the conversion fits in 12 GB VRAM.
The existing viewer, which remains GPU-resident, successfully loaded the final
9.51 GiB grid with about 0.95 GiB device memory free after upload in the probe run.
Avoid loading a second copy concurrently on this GPU.

The high-resolution records above use the **current working-tree library**, not
a rerun of the older library committed on the publishing branch. The new tools
also built on that branch; a small N=64, band=3 managed bunny control passed 1,748
sign probes with its legacy dense root format. The original working-tree edits
were preserved. Header SHA-256 for the high-resolution converter build:

- `PropagateSign.cuh`: `681c7086c4c023d82cece05dbc9b98161cc79188e104d6f32aa15fc8af1244f0`

## Local paper-resolution artifacts

Under `output/general-mesh-root/band3/` (not committed):

- `bunny-root-context-camera.json`: active signed band plus Root only, clipped
  at Z=2047.5, so the large cell is visible inside the bunny.
- `bunny-root-full-space-camera.json`: all actual interior fill levels plus band.
- `bunny-root-only-camera.json`: isolated actual root, without clipping.
- Corresponding `bunny-root-context-4k.png`, `bunny-root-full-space-4k.png` and
  `bunny-root-only-4k.png`: 3840×2160, 4 samples/pixel.

```bash
python3 viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb \
  --settings output/general-mesh-root/band3/bunny-root-context-camera.json \
  --port 8768 --open
python3 viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb \
  --settings output/general-mesh-root/band3/bunny-root-full-space-camera.json \
  --render output/general-mesh-root/band3/bunny-root-full-space-4k.png \
  --width 3840 --height 2160 --samples 4
```
