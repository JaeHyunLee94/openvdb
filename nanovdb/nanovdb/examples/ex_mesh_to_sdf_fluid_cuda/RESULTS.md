# Measured validation results

The subsequent five-second tests and 3D animations are reported in [LONG_RUN_RESULTS.md](LONG_RUN_RESULTS.md).

Measured on 2026-10-06, NVIDIA RTX PRO 3000 Blackwell (12 GB), driver 580.178.04.
Release build, CUDA `compute_90` PTX JIT, double-precision transfer/pressure arithmetic.
Branch: `mesh-to-sdf-fluid`, based on `76a49296f532fc1e1e5a20680c8baeb24e3358e5`.

The starting working tree already contained changes to MeshToSDF, PropagateSign, and other examples.
Those changes were preserved; this task changed only this example directory and its CMake registration.
Tested MeshToSDF SHA-256: `cba9e839b7896e8741812c662797910d60a5e30287efbd1ec982afe15923e613`.

## Numerical results

All checks passed. These values come from `output/summary.json` and the per-scenario CSV/log files.

| Scene | Substeps | End time (s) | Max true relative residual | Max RMS divergence before / after (s^-1) | Leaf blocks |
|---|---:|---:|---:|---:|---:|
| stage1 | 80 | 0.276267 | 9.972e-10 | 2.198e+00 / 1.990e-09 | 180–180 |
| stage2 | 80 | 0.276267 | 9.972e-10 | 2.198e+00 / 1.990e-09 | 80–100 |
| static | 160 | 0.415761 | 9.979e-10 | 2.180e+00 / 1.840e-09 | 80–108 |
| moving | 200 | 0.489722 | 9.996e-10 | 2.895e+00 / 2.455e-09 | 75–105 |
| deforming | 200 | 0.487322 | 9.998e-10 | 2.478e+00 / 2.313e-09 | 80–111 |

Divergence is the full open/blocked moving-wall flux, not just fluid-velocity divergence.
The independently reconstructed analytic-wall flux also passed <= 1e-6 s^-1 in all obstacle runs.
The table reports maxima of before/after series; they need not occur on the same substep.

- Constant-field APIC: velocity max <= 1.12e-15 m/s, affine max <= 2.43e-14 s^-1.
- Affine-field APIC: velocity max <= 1.67e-15 m/s, affine max <= 4.15e-14 s^-1.
- Acceptance: velocity 1e-10, affine 1e-9; all test particles are away from boundaries.
- Fixed/sparse max position difference: 1.000e-10 m.
- Fixed/sparse max velocity difference: 1.000e-09 m/s.
- Fixed/sparse acceptance: 1e-6; every saved particle frame is compared, not only the last.
- Missing particle/pressure/velocity stencils: 0. Sidecar coordinate/neighbor correspondence passed.
- SDF deep interior: -0.075 m at index zero; exterior +0.075 m.
- Face sampling error at initial cube: 7.60e-8 m; acceptance 0.0125 m.
- Manufactured collision: starts approximately 0.005 m inside, ends outside both SDF and exact mesh.
- Vertex-velocity derivative error <= 4.60e-11 m/s; acceptance 1e-8 m/s.

| Scene | Max blocked-face normal error (m/s) | Max contact normal error (m/s) | Remaining penetrations / max depth | Contact events | Max partial faces | Max particle CFL |
|---|---:|---:|---:|---:|---:|---:|
| static | 0.000e+00 | 2.168e-16 | 0 / 0 m | 15133 | 64 | 0.161 |
| moving | 1.110e-16 | 4.365e-16 | 0 / 0 m | 5854 | 113 | 0.168 |
| deforming | 5.551e-17 | 3.796e-16 | 0 / 0 m | 22736 | 162 | 0.157 |

The final simulations also had zero pre-correction negative-SDF penetration attempts: the positive
contact margin activated before crossing the surface. This is not the sole collision test; the
manufactured negative-SDF contact explicitly verifies recovery. Contact counts include pre- and
post-advection events, not unique particles. Remaining penetration is checked independently
against both trilinear SDF and the analytic cube/deforming cuboid, with a 1e-7 m depth tolerance.

Blocked-face trace accuracy is a discrete boundary-condition check. It does not claim
pointwise interpolated velocity accuracy everywhere on an arbitrary curved/oblique surface.

## Performance

Mean synchronized elapsed wall time per substep, milliseconds. Setup/JIT and rendering are excluded.
No rendering was run concurrently with the measured final validation suite.

| Scene | Topology | MeshToSDF | SDF sampling / face data | P2G | Pressure + projection | Extrapolation + G2P | Contact |
|---|---:|---:|---:|---:|---:|---:|---:|
| stage1 | 0.000 | 0.000 | 0.000 | 0.882 | 18.059 | 1.530 | 0.000 |
| stage2 | 9.747 | 0.000 | 0.000 | 0.858 | 17.727 | 1.331 | 0.000 |
| static | 9.978 | 3.683 | 0.683 | 0.851 | 20.390 | 1.372 | 1.513 |
| moving | 10.033 | 3.673 | 0.685 | 0.852 | 20.377 | 1.378 | 1.195 |
| deforming | 10.471 | 3.978 | 0.704 | 0.853 | 20.774 | 1.387 | 1.569 |

Fixed topology is allocated once; its per-step update cost is zero. Dynamic topology is rebuilt
and reindexed every substep. Pressure timing includes allocations, CG host scalar synchronization,
and projection. Contact timing includes kernel and diagnostic readback. Independent divergence,
index, and CFL diagnostics have additional CPU/download cost outside these stage timers.
These are measured component costs, not end-to-end frames-per-second claims.
At this problem size, sparse rebuilding costs more than it saves in the fluid solve.

All file output is outside the simulation timers. Debug rendering costs are separately recorded
in `output/render_times.json`; `render_all.py --rtx` also records renderer costs separately.
The completed 15-image RTX batch plus debug GIF generation took about 53 seconds wall time.

## Images and sequences

Each folder contains CSV data, all 5-substep debug frames, a GIF, and three representative RTX renders.
The GIF uses uniform playback intervals; actual simulation times are in `metrics.csv` because dt adapts.

| Stage | Initial / middle / final RTX gallery | Particle + block/halo gallery | Debug animation |
|---|---|---|---|
| stage1 | [RTX](output/stage1/overview_rtx.png) | [Debug](output/stage1/overview.png) | [GIF](output/stage1/sequence.gif) |
| stage2 | [RTX](output/stage2/overview_rtx.png) | [Debug](output/stage2/overview.png) | [GIF](output/stage2/sequence.gif) |
| static | [RTX](output/static/overview_rtx.png) | [Debug](output/static/overview.png) | [GIF](output/static/sequence.gif) |
| moving | [RTX](output/moving/overview_rtx.png) | [Debug](output/moving/overview.png) | [GIF](output/moving/sequence.gif) |
| deforming | [RTX](output/deforming/overview_rtx.png) | [Debug](output/deforming/overview.png) | [GIF](output/deforming/sequence.gif) |

The existing ovrtx renderer successfully loaded locally generated USD and rendered actual solver
particles, tank edges, and obstacle meshes. No Blender fallback or renderer source edit was needed.
Both the 3D views and particle slab/block views were inspected. Image appearance was not used
as a substitute for the numerical acceptance checks above.

## Problems found and resolved; remaining limits

- Empty `root_interior` channels are omitted by MeshToSDF. The sampler now checks channel presence.
- A 0.005 m collision margin allowed 0.00142 m analytic-mesh penetration at a trilinear SDF corner.
  A half-obstacle-voxel margin (0.0125 m) resolved it; final analytic-mesh checks pass.
- A fixed 0.005 s timestep eventually exceeded the added CFL bound. The final runs use the
  affine-aware adaptive timestep and record actual time/dt. They represent approximately
  0.28–0.49 seconds of physical time, not a long-duration stability study.
- Air face extrapolation is seeded by projected fluid-adjacent faces, and G2P verifies validity.
- CUDA compute-sanitizer could not instrument the application on this installation (terminated
  before its first instrumented API call). No sanitizer pass is claimed. Real GPU runs, explicit
  CUDA error checks, finite/CFL checks, and numerical regression checks passed.
- Fluid surface and solid-cell blocking remain first order; there is no fluid volume correction
  or general sealed-domain pressure treatment. Collision clearance is visible.
- Arbitrary character animation, oblique/curved deforming meshes, reseeding, and performance
  optimization remain follow-up work. See README for the precise discretization and limitations.

## Reproduction

```bash
cmake --build build/release --target ex_mesh_to_sdf_fluid_cuda -j 4
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
python3 "$EX/validate.py" build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
/tmp/fluid-render-venv/bin/python "$EX/render_all.py" --rtx
```

See README for fresh CMake configuration and Python renderer environment setup.
