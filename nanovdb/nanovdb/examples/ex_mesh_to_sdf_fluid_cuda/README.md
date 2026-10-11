# GPU APIC on a NanoVDB sparse domain

This example includes the original three-stage mesh-obstacle liquid demo and a
dancing-character scene with a continuous emitter, foam/spray, anisotropic surfaces,
and an ovrtx animation pipeline. All solver, obstacle adapter, validation,
and output conversion code is local to this directory. The existing library operators
and the ovrtx renderer are not modified.

The current implementation is documented in
[IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md), including operator reuse, MAC/APIC
data layout, the pressure equation and MGPCG, topology lifetime, obstacle SDF
decoding, substep order, validation scope, and current limitations.

GPU resident particle management, float/double selection, compact cells and cooperative
GPU MGPCG are documented in [SCALABILITY.md](SCALABILITY.md). Scene settings remain
unchanged. The pipeline accepts `--precision float|double --pressure mgpcg|jacobi`.

The character extension is documented in [SCENE_IMPLEMENTATION.md](SCENE_IMPLEMENTATION.md).
See [SCENE_RESULTS.md](SCENE_RESULTS.md) for its commands, measurements and output files.
Configurations and reusable scripts are in `scene/`. CPU surface extraction additionally
requires `OPENVDB_BUILD_CORE=ON` and `NANOVDB_USE_OPENVDB=ON`.

The latest twelve-second scene uses `scene/clear_shower_fine.json`: a 42 cm emitter,
20 mm fluid / 10 mm obstacle / 6.25 mm meshing grids, an initial 6.4 cm pool,
and corrected pressure handling of partially blocked cells. See
[STREAM_REFINEMENT_RESULTS.md](STREAM_REFINEMENT_RESULTS.md) for the clumping diagnosis,
matched-resolution comparisons, full validation, timings, and final movies.
The previous 52 cm / 32 mm scene is preserved in `scene/grounded_shower.json` and
[GROUNDED_SHOWER_RESULTS.md](GROUNDED_SHOWER_RESULTS.md), including the isovalue
explanation and foot-motion comparison.

The twelve-second scene starts with 6.4 cm of water and uses `scene/wet_pool.json`.
Its visible white foam, initial pool, measurements and movies are documented in
[WET_POOL_RESULTS.md](WET_POOL_RESULTS.md).
The previous six-second accumulating water scene uses `scene/pool.json` (`drain_enabled: false`).
Its basin boundaries, mass/height measurements, and new movie are described in
[POOL_RESULTS.md](POOL_RESULTS.md). `scene/water.json` preserves the draining scene
for comparison. The free-slip/contact fixes,
whitewater visibility diagnosis, regression measurements and before/after movies
are described in [WATER_FIX_REPORT.md](WATER_FIX_REPORT.md).
`scene/final.json` and `output/scene_final` retain the previous scene baseline.

## Source-only checkout

Simulation caches, character mesh sequences, rendered images/videos, and the local
Python environment under `output/` are intentionally excluded from Git. Supply your
own character FBX and run `scene/export_character.py` before running the dance scene;
see `SCENE_IMPLEMENTATION.md` for the export and pipeline commands.

The obstacle adapters support both MeshToSDF root-interior representations: the
committed library's `uint8` bitmap with `root_extent`, and the newer local `int32`
root-tile origin list. The channel type selects the decoder. No library changes are
required by this example. Timing/results documents describe previously measured
runs; those generated artifacts are not included in a source checkout.

## Build and run

From the repository root, using the existing CUDA-enabled release configuration:

```bash
cmake --build build/release --target ex_mesh_to_sdf_fluid_cuda -j 4
python3 nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda/validate.py \
  build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
```

For a fresh configuration, the relevant options are:

```bash
cmake -S . -B build/fluid -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DOPENVDB_BUILD_CORE=OFF \
  -DOPENVDB_BUILD_BINARIES=OFF -DOPENVDB_BUILD_NANOVDB=ON \
  -DNANOVDB_USE_OPENVDB=OFF -DNANOVDB_USE_CUDA=ON \
  -DNANOVDB_BUILD_EXAMPLES=ON -DNANOVDB_BUILD_TOOLS=OFF \
  -DNANOVDB_BUILD_UNITTESTS=OFF -DCMAKE_CUDA_ARCHITECTURES=90-virtual \
  '-DCMAKE_CUDA_FLAGS=-Xcompiler=-D_AMXTILEINTRIN_H_INCLUDED -Xcompiler=-D_AMXINT8INTRIN_H_INCLUDED -Xcompiler=-D_AMXBF16INTRIN_H_INCLUDED'
cmake --build build/fluid --target ex_mesh_to_sdf_fluid_cuda -j 4
```

The last compiler flags match the installed Ubuntu CUDA/GCC combination. Choose a
CUDA architecture supported by your compiler/GPU. This branch's NanoVDB configuration
fetches CCCL; a fresh build may need network access. The example target disables only
CCCL's umbrella-header advisory, needed because existing operators include `cub.cuh`
and the repository treats CUDA warnings as errors.

Individual runs use `ex_mesh_to_sdf_fluid_cuda MODE OUTPUT_DIRECTORY SUBSTEPS`.
Modes are `stage1`, `stage2`, `static`, `moving`, and `deforming`. The validation driver
runs them in that order with 80, 80, 160, 200, and 200 substeps. A failed C++ check returns
a nonzero exit status and stops the driver. Use a new output directory when changing
the number of substeps, to avoid including older frames in a glob.

`output/summary.json` summarizes every metrics column and compares every stored
fixed/sparse particle frame. `output/*.log` records transfer, SDF, manufactured-contact,
and vertex-velocity tests. Output artifacts are intentionally git-ignored.

## Stage 1: fixed topology

- Domain: 32 x 32 x 24 cells, h = 0.05 m; Y is up. The initial dam has eight
  equally weighted particles per occupied cell. No particles are reseeded or deleted
  during a run. Initial particles inside an obstacle/contact margin are omitted.
- `ValueOnIndex` stores topology only. Cell center is `(ijk + 0.5) h`;
  component `a` of the MAC velocity is at that center minus `0.5 h e_a`.
  Slot zero is a permanently empty background sentinel.
- Equal particle masses and quadratic B-spline weights transfer mass and APIC momentum
  independently to each staggered component. G2P reconstructs velocity and
  `C_a = 4/h^2 sum(w u_a (x_face - x_particle))`.
- Fluid/air classification is a **separate particle-position occupancy mask**.
  P2G face mass is neither a fluid SDF nor the pressure-domain mask. The fluid
  pressure domain includes every occupied interior cell, not just a surface band.
- Gravity is followed by a matrix-free MGPCG solve. A cooperative GPU kernel controls
  iterations and accumulates dot products in double; storage is selectable float/double. The solved
  variable is the velocity potential `q = dt p / (rho h)`. Thus `A q = -net_flux`
  and face projection subtracts `q_right - q_left`. Air has zero pressure, with
  full-cell first-order fluid/air coupling and no subcell interface-distance correction;
  no fluid level set is advected.
- Tank boundary faces prescribe zero normal velocity. Projected fluid-adjacent faces
  seed four synchronous velocity-extrapolation layers; unprojected air face values
  are not retained as valid seeds. G2P checks both topology and velocity validity.
- Particle advection is first order. Tank contact clamps position and removes inward
  velocity. The next timestep is capped at 0.005 s and bounded by particle velocity
  plus the APIC affine contribution over the transfer support. Measured particle CFL
  must remain below 0.5; exceeding it fails the run rather than silently continuing.

## Stage 2: dynamic topology

`voxelsToGrid<ValueOnIndex>` (from `PointsToGrid.cuh`) creates a GPU grid from
**all particle cell coordinates**, followed by six 26-neighbor `DilateGrid` passes.
This covers interior pressure cells, both sides of their faces, quadratic transfer
stencils, and velocity extrapolation. The grid is sparse at voxel and 8^3 leaf level;
leaf allocation does not imply that all voxels in the leaf are active.

Every substep creates a new topology and freshly allocates cell sidecars. Cell coordinates
and six neighbor indices are re-enumerated from that new grid. Pressure, fluid
mask, mass, velocity, validity, and obstacle data are regenerated. Only particle
position, velocity, and affine matrices persist. No old voxel index is reused, and
there is no pressure warm start requiring remapping.

`PruneGrid` was inspected: it retains an explicit leaf-indexed voxel mask and returns
new indices. Rebuilding from particles already removes obsolete voxels, so an
additional prune is unnecessary. `MergeGrids` performs an active-mask union and
requires compatible transforms; it neither merges physical channels nor implements
wall boundary conditions. The obstacle grid is sampled separately, so no merge is used.

The tests check missing stencils on GPU and bijective coordinate/neighbor correspondence
on downloaded sidecars. Fixed versus sparse results are compared with a 1e-6 maximum
absolute tolerance for both position and velocity. Double atomic accumulation order
and reduction order can differ between runs/topologies.

## Stage 3: MeshToSDF and walls

The original `MeshToSDF.cuh` is instantiated once per substep, including for the static
case to measure the same path. Experimental `MeshToSDF_NEW` and `PropagateSign_*`
implementations are not included. Mesh topology is eight vertices/twelve triangles:

- Static cube: center `(0.85, 0.38, 0.60)`, half-size 0.18 m.
- Moving cube: `center.x += 0.12 sin(6t)`, velocity `(0.72 cos(6t), 0, 0)`.
- Deforming mesh: half-size `(0.18 s, 0.18/s, 0.18)`, `s = 1 + 0.2 sin(6t)`.
  This is a volume-preserving deformation with unchanged vertex connectivity.
  Velocity is `(s'/s (x-c)_x, -s'/s (x-c)_y, 0)`.

The same continuous motion generates vertices and wall velocity; a central-difference
vertex test checks that correspondence. Geometry and velocity are evaluated at the
substep's end time (first-order implicit wall position). Contact is checked both after
wall motion and after fluid advection.

Obstacle voxel size is 0.025 m with a three-voxel narrow band. Fluid cell/face positions
are converted to world space and then through the obstacle grid's `worldToIndex` map.
Trilinear sampling reads signed float channel `sdf` for active voxels; inactive leaf,
lower, and upper regions read their respective invert masks. Absent root regions read
`root_interior` when present. **The root channel is omitted by MeshToSDF when empty**.
Inactive interior samples return negative band width, never positive background.
The deep-interior test requires both a negative sample and index zero.

Face open area is estimated with 4 x 4 SDF quadrature. A solid-centered neighboring
cell conservatively blocks the full face. Solid cells are excluded from pressure.
Projection and diagnostics use the same discrete physical flux:

```
F_face = open_area * u_fluid + (1 - open_area) * u_wall
D = sum(F_positive_face - F_negative_face) / h
```

The matrix coefficients contain open area; blocked flux enters the right-hand side.
Fully blocked velocities are prescribed, so pressure cannot overwrite their wall
condition. A second CPU flux check reconstructs the analytic wall velocity rather
than trusting the wall sidecar. Normal-velocity diagnostics check the blocked face
trace (including the blocked part of partially open faces), after projection.

Particle collision uses the sampled SDF and its finite-difference normal. Iterative
position correction applies a 0.0125 m contact margin; this accommodates trilinear
corner error. Relative normal velocity is removed at contact, while tangent velocity
is retained. Contact resets the affine matrix. Penetration is measured against both
sampled SDF and the independent analytic mesh geometry. A manufactured inward-moving
particle starts 0.005 m inside the cube and must be recovered. Simulation logs count
pre-correction penetration attempts separately from remaining penetrations.

## Visualization

The existing ovrtx checkout's README, minimal Python example, USD examples, driver
requirements, and `skills/application-flow/SKILL.md` were inspected. No public input
path for an index grid plus arbitrary sidecar was found. `render.py` converts particle
positions to small octahedral marker meshes in local USD, adds the obstacle and tank
wireframe, and uses the existing renderer API without modifying the ovrtx checkout.
This visualizes the actual particles, not a fitted fluid surface.

```bash
python3 -m venv /tmp/fluid-render-venv
/tmp/fluid-render-venv/bin/pip install \
  ovrtx==0.5.1.385782 ovstage==0.2.1.385922 numpy pillow
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
/tmp/fluid-render-venv/bin/python "$EX/render.py" --rtx \
  "$EX/output/stage1/frame_0040.csv"
python3 "$EX/render.py" --gif "$EX/output/moving/sequence.gif" \
  "$EX"/output/moving/frame_*.csv
```

`frame_NNNN_rtx.png` is the ovrtx render. `frame_NNNN.png` is an X-Y particle slab
(0.5 < z < 0.7) with allocated leaf blocks intersecting the mid-Z plane. Orange blocks
contain fluid cells; cyan blocks are halo-only. These are block-allocation diagnostics,
not claims that every voxel of a leaf is active. Red shows the actual obstacle outline.
Particles are colored by speed. The debug sequence remains available alongside the
3D renders so opaque geometry cannot conceal penetration.

To regenerate all representative images and animations:

```bash
/tmp/fluid-render-venv/bin/python "$EX/render_all.py" --rtx
```

All CUDA stage timers synchronize the default stream and report elapsed wall time,
including allocations and host orchestration. Pressure time includes GPU CG reductions
and projection, but not the independent diagnostics. Collision time includes contact
kernel/readback. CSV/PNG/USD output and rendering occur outside these simulation stage
timers. Do not add output/render wall time to the reported simulation costs.

## Validation thresholds and limitations

- APIC constant/affine field: max velocity error <= 1e-10, max affine error <= 1e-9,
  away from all boundaries.
- True recomputed residual norm <= max(1e-12, 2e-8 * RHS norm); fluid-cell RMS flux
  divergence <= 1e-6 s^-1, including moving wall flux. CG requests 1e-9 relative convergence.
- Fixed/sparse particle differences <= 1e-6; missing topology/velocity stencils = 0.
- Blocked-face and contact relative normal velocity <= 1e-8 m/s.
- Remaining sampled-SDF and analytic-mesh penetration deeper than 1e-7 m = 0.
- Positive contact counts ensure obstacle tests actually exercise wall interaction.

This is a small validation demo, not a production liquid solver. The fluid occupancy
mask is first order, without subcell fluid SDF, surface tension, viscosity, reseeding,
or a volume-conservation correction. Cut-face quadrature plus solid-cell blocking is
not a geometrically exact cut-cell method; blocked-face errors do not establish
pointwise accuracy of an interpolated fluid velocity on arbitrary oblique surfaces.
The basic executable validates axis-aligned translation and volume-preserving box
deformation. The separate scene executable also supports the evaluated character
sequence and closest-triangle wall velocities; see [SCENE_IMPLEMENTATION.md](SCENE_IMPLEMENTATION.md).

The collision margin creates a visible clearance. Deep penetration into the clamped
SDF interior cannot be resolved using its zero gradient; bounded substeps and per-step
contacts avoid it in these scenes. Closed Neumann manufactured pressure systems are
also tested by the scalability verifier; this does not establish arbitrary sealed,
deforming-container compatibility. The thresholds above describe the basic double
tests. Current float thresholds, GPU reductions, persistent MGPCG, measured speedups
and the remaining strict trajectory comparison failure are in
[SCALABILITY.md](SCALABILITY.md). `RESULTS.md` retains the original basic-demo measurements.

## Physical-time runs and 3D animation

Long runs stop at actual simulation time rather than at a fixed substep count:

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda moving \
  "$EX/output/long/moving" --duration 5 --fps 30
/tmp/fluid-render-venv/bin/python "$EX/validate_long.py" \
  build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda --duration 5
```

`--fps` controls output sampling in physical time. The adaptive step is clipped to
reach every frame time exactly. `frames.csv` maps frame number, substep, time, and
particle count; it avoids treating unequal substeps as equal animation intervals.
The original positional `SUBSTEPS` interface still works. Long runs additionally
record maximum/mean speed, finite affine matrices, APIC particle energy, center of
mass, particle count, and tank escape depth. A progress guard rejects collapsed
adaptive timesteps. Tiny frame-boundary clipping steps are allowed and are distinct
from a collapsed proposed timestep.

For animation authoring and diagnostic plots, add these packages to the renderer environment:

```bash
/tmp/fluid-render-venv/bin/pip install usd-core matplotlib
/tmp/fluid-render-venv/bin/python "$EX/animate.py" "$EX/output/long/moving"
/tmp/fluid-render-venv/bin/python "$EX/assemble_animation.py"
/tmp/fluid-render-venv/bin/python "$EX/report_long.py"
```

`animate.py` writes a binary, time-sampled `scene.usdc`, replays it through one ovrtx
renderer using `ovstage.population.update_from_usd_time`, and encodes `animation.mp4`.
The USD time codes are seconds multiplied by the scene's timeCodesPerSecond;
ovstage's update API accepts seconds. Each 5 s obstacle scene has 151 samples at 30 fps,
including both endpoints. The output also includes `debug.mp4` for particle/block
inspection, all rendered PNG frames, and separate authoring/render timings.
Forty initial warmup renders follow the ovrtx warmup skill; these do not advance the
solver. Rendering does not run concurrently with the measured simulation.

The five-second results and 3D video links are in [LONG_RUN_RESULTS.md](LONG_RUN_RESULTS.md).
They include the measured occupied-cell-volume drift. Conserved particle count and
small pressure divergence do not, by themselves, prove conserved material volume.

## Higher simulation resolution

`--voxel-size` scales the fluid discretization while preserving the 1.6 × 1.6 × 1.2 m
tank and the physical dimensions and motion of the dam and obstacle. The cell size
must divide all tank dimensions. A modest increase from 0.05 to 0.04 m changes the
fixed domain from 32 × 32 × 24 to 40 × 40 × 30 cells. Particle spacing scales with
the cell size; the dam keeps its original physical bounds. Obstacle SDF cells are
half the fluid cell size, contact clearance is one quarter, and rendered particle
marker radius is 0.14 times the fluid cell size. `scene.json` records these values
for validation, volume measurements, USD authoring, and block debug views.

```bash
cmake --build build/release --target ex_mesh_to_sdf_fluid_cuda -j 4
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
OUT="$EX/output/higher_resolution"
/tmp/fluid-render-venv/bin/python "$EX/validate_long.py" \
  build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda \
  --duration 5 --voxel-size 0.04 --output "$OUT"
for scene in stage1 stage2; do
  /tmp/fluid-render-venv/bin/python "$EX/animate.py" "$OUT/$scene" --fps 10
done
for scene in static moving deforming; do
  /tmp/fluid-render-venv/bin/python "$EX/animate.py" "$OUT/$scene"
done
/tmp/fluid-render-venv/bin/python "$EX/assemble_animation.py" --output "$OUT"
/tmp/fluid-render-venv/bin/python "$EX/report_long.py" --output "$OUT"
/tmp/fluid-render-venv/bin/python "$EX/compare_resolution.py" \
  --low "$EX/output/long" --high "$OUT"
```

The original 0.05 m output remains under `output/long`; higher-resolution results
are separate. Comparing the two cell sizes is a sensitivity check, not a convergence
proof: there are only two discretizations, the particle populations differ, and
the contact clearance also scales. Within each resolution, fixed/sparse comparisons
still use identical initial particles and compare matching physical-time frames.

Measured higher-resolution results and artifact links are in
[HIGHER_RESOLUTION_RESULTS.md](HIGHER_RESOLUTION_RESULTS.md). The measured loss of
occupied-cell volume is larger at 0.04 m; passing pressure and penetration tests
does not validate geometric volume conservation.
