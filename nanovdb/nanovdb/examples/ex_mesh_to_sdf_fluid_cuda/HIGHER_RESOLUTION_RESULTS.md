# Higher resolution: five-second validation and 3D animation

Fluid resolution increases from 32 × 32 × 24 at 0.05 m to 40 × 40 × 30 at 0.04 m.
The defined pressure, topology, CFL, energy stability, and penetration checks pass.
**Occupied-cell volume falls by 19.90–27.43%, more than at 0.05 m; geometric volume preservation is unverified.**

All scenes run to physical simulation time 5.000000 s. Obstacle motion repeats 4.77 periods.
Fluid cell size is 0.04 m, the domain has [40, 40, 30] cells, and obstacle SDF cell size is 0.02 m.
The physical tank remains [1.6, 1.6, 1.2] m. Contact clearance is 0.01 m; particle marker radius is 0.0056 m.
Adaptive substeps stop exactly at scheduled output times. Baselines save 10 fps; obstacle scenes save 30 fps.
Every simulation substep checks pressure, topology/velocity stencils, finite particles/affine matrices,
tank bounds, and CFL. Obstacle runs additionally check analytic wall flux and SDF/analytic-mesh penetration.

| Scene | Particles | Substeps | Max relative residual | Max physical RMS divergence (1/s) | Max speed / final speed (m/s) | Leaves |
|---|---:|---:|---:|---:|---:|---:|
| stage1 | 64395 | 1554 | 9.999e-10 | 3.531e-09 | 4.795 / 0.392 | 294–294 |
| stage2 | 64395 | 1554 | 9.999e-10 | 3.531e-09 | 4.795 / 0.392 | 126–185 |
| static | 63673 | 1629 | 1.000e-09 | 3.506e-09 | 4.730 / 0.393 | 118–184 |
| moving | 63673 | 1629 | 9.998e-10 | 3.140e-09 | 4.870 / 0.242 | 120–184 |
| deforming | 63673 | 1663 | 1.000e-09 | 3.682e-09 | 4.680 / 0.368 | 118–184 |

Criteria: residual <= 2e-8; RMS divergence <= 1e-6 1/s; CFL <= 0.5;
blocked/contact normal error <= 1e-8 m/s; zero remaining penetration deeper than 1e-7 m.
Particle count remains constant within each scene. No NaN/Inf, missing stencil, tank escape, or progress stall.
Stationary-wall energy must not increase more than 5% over its first substep. This check passed.
Moving-wall energy is recorded but not treated as conserved, because the obstacle performs work.
Total energy includes the particle affine contribution with quadratic-kernel moment h^2/4;
it is a useful diagnostic, not an independently conserved discretized mechanical-energy theorem.

| Scene | Wall error (m/s) | Contact error (m/s) | SDF / mesh remaining penetrations | Max attempted depth (m) |
|---|---:|---:|---:|---:|
| static | 0.000e+00 | 3.298e-16 | 0 / 0 | 0.000e+00 |
| moving | 1.110e-16 | 3.359e-16 | 0 / 0 | 0.000e+00 |
| deforming | 8.327e-17 | 3.204e-16 | 0 / 0 | 0.000e+00 |

Fixed/sparse particle comparison: **PASS**, max position 1.000e-09 m, max velocity 1.000e-09 m/s, tolerance 1e-6.
All 51 stored physical-time frames are compared, not independently numbered substeps.

## Volume limitation exposed by the longer run

Particle mass/count is conserved. Occupied-cell volume is a separate coarse free-surface diagnostic.
It is not an exact material volume. These runs do not establish geometric volume conservation.

| Scene | Initial occupied-cell volume (m^3) | Final (m^3) | Change |
|---|---:|---:|---:|
| stage1 | 0.55642 | 0.44570 | -19.90% |
| stage2 | 0.55642 | 0.44570 | -19.90% |
| static | 0.55066 | 0.41626 | -24.41% |
| moving | 0.55066 | 0.39962 | -27.43% |
| deforming | 0.55066 | 0.41056 | -25.44% |

The first-order particle occupancy mask has no reseeding or volume correction, and these runs show a measurable
change in the occupied-cell volume. Mask quantization and particle redistribution both affect this diagnostic.
Small projected divergence alone must not be interpreted as
a proof that the material volume stays constant. A fluid SDF/subcell free surface and a dedicated
volume test remain necessary before treating this as a production obstacle solver.

## Timing

Means in milliseconds/substep. CUDA stage wall timers include synchronization and orchestration;
I/O and independent CPU diagnostics are excluded. Simulation and rendering were run sequentially.

| Scene | Topology | MeshToSDF | Boundary sampling | P2G | Pressure | Extrapolation/G2P | Contacts |
|---|---:|---:|---:|---:|---:|---:|---:|
| stage1 | 0.000 | — | — | 1.766 | 27.896 | 2.416 | — |
| stage2 | 11.053 | — | — | 1.674 | 26.642 | 2.116 | — |
| static | 10.747 | 4.114 | 0.782 | 1.680 | 26.971 | 2.134 | 2.275 |
| moving | 10.559 | 4.076 | 0.744 | 1.678 | 27.143 | 2.112 | 2.142 |
| deforming | 10.817 | 4.018 | 0.806 | 1.679 | 26.711 | 2.123 | 2.218 |

## Animation artifacts

The 3D scene contains actual particle markers, animated obstacle vertices, tank edges, lights, and camera.
The USD contains 151 time samples per obstacle scene at 30 time codes/second.
ovstage.update_from_usd_time takes seconds; the authoring code converts seconds to USD time codes.
ovrtx reuses one renderer and stage through the sequence. Forty warmup steps happen before capture;
render accumulation steps at a fixed pose do not advance simulation time.

| Scene | Frames | 3D MP4 | Particle/block debug MP4 | Animated USD scene |
|---|---:|---|---|---|
| stage1 | 51 | [stage1/animation.mp4](output/higher_resolution/stage1/animation.mp4) | [debug](output/higher_resolution/stage1/debug.mp4) | [scene.usdc](output/higher_resolution/stage1/scene.usdc) |
| stage2 | 51 | [stage2/animation.mp4](output/higher_resolution/stage2/animation.mp4) | [debug](output/higher_resolution/stage2/debug.mp4) | [scene.usdc](output/higher_resolution/stage2/scene.usdc) |
| static | 151 | [static/animation.mp4](output/higher_resolution/static/animation.mp4) | [debug](output/higher_resolution/static/debug.mp4) | [scene.usdc](output/higher_resolution/static/scene.usdc) |
| moving | 151 | [moving/animation.mp4](output/higher_resolution/moving/animation.mp4) | [debug](output/higher_resolution/moving/debug.mp4) | [scene.usdc](output/higher_resolution/moving/scene.usdc) |
| deforming | 151 | [deforming/animation.mp4](output/higher_resolution/deforming/animation.mp4) | [debug](output/higher_resolution/deforming/debug.mp4) | [scene.usdc](output/higher_resolution/deforming/scene.usdc) |

[Combined three-scene video](output/higher_resolution/demo.mp4) concatenates the three separate 5 s simulations;
the endpoint frame adds one display interval.
All video frames are also preserved under each scenario’s `rtx/` and `debug/` folders.
Rendering and USD-authoring durations are in `animation_times.json`, separate from simulation metrics.

![Stability diagnostics](output/higher_resolution/stability.png)

## Reproduction

```bash
cmake --build build/release --target ex_mesh_to_sdf_fluid_cuda -j 4
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
OUT="$EX/output/higher_resolution"
/tmp/fluid-render-venv/bin/python "$EX/validate_long.py" \
  build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda --duration 5 \
  --voxel-size 0.04 --output "$OUT"
for scene in stage1 stage2; do
  /tmp/fluid-render-venv/bin/python "$EX/animate.py" "$OUT/$scene" --fps 10
done
for scene in static moving deforming; do
  /tmp/fluid-render-venv/bin/python "$EX/animate.py" "$OUT/$scene"
done
/tmp/fluid-render-venv/bin/python "$EX/assemble_animation.py" --output "$OUT"
/tmp/fluid-render-venv/bin/python "$EX/report_long.py" --output "$OUT"
```

Additional Python packages for animation/plots: `usd-core`, `matplotlib`; encoding uses installed ffmpeg.
All implementation changes remain in the new example folder; library and ovrtx sources are untouched.

## Additional numerical checks

Constant-velocity APIC roundtrip: max velocity error 8.882e-16 m/s, max affine error 2.524e-14 1/s.
Affine-velocity roundtrip: max velocity error 1.554e-15 m/s, max affine error 7.269e-14 1/s.
Acceptance limits are 1e-10 m/s and 1e-9 1/s. Tests run away from all boundaries.
The inactive obstacle center has voxel index 0 yet samples negative distance −0.06 m;
the inactive exterior samples +0.06 m. The manufactured 5 mm penetration is resolved
with zero remaining SDF/analytic-mesh depth and zero relative normal speed.
The moving-cube vertex velocity agrees with a centered position derivative to 4.591e-11 m/s.

| Scene | Mean pre-projection RMS divergence (1/s) | Mean post-projection (1/s) |
|---|---:|---:|
| stage1 | 7.403e-01 | 6.671e-10 |
| stage2 | 7.403e-01 | 6.671e-10 |
| static | 7.550e-01 | 6.825e-10 |
| moving | 7.636e-01 | 6.932e-10 |
| deforming | 7.646e-01 | 6.912e-10 |

## Visualization review and cost

Initial, middle (2.5 s), and final (5 s) views were inspected. The particle dam collapses,
flows around the cube, and settles. Sparse block edges show no obvious spatial jumps;
the independent numerical stencil and fixed/sparse checks remain the correctness tests.
Advected particle layers and uneven particle distribution are visible. These markers
do not reconstruct a liquid surface, and the images do not establish volume conservation.

| Scene | USD authoring (s) | RTX render/capture (s) | Debug output/encode (s) | Representative frames |
|---|---:|---:|---:|---|
| stage1 | 2.677 | 12.721 | 6.448 | [overview](output/higher_resolution/stage1/overview.png) |
| stage2 | 2.636 | 10.385 | 6.558 | [overview](output/higher_resolution/stage2/overview.png) |
| static | 6.313 | 22.221 | 18.512 | [overview](output/higher_resolution/static/overview.png) |
| moving | 6.336 | 21.684 | 18.944 | [overview](output/higher_resolution/moving/overview.png) |
| deforming | 6.297 | 25.701 | 18.032 | [overview](output/higher_resolution/deforming/overview.png) |

All 11 MP4 files (five 3D, five debug, and the obstacle montage) pass full decoding checks.
The montage has 453 frames at 30 fps, 960 × 720, and lasts 15.1 s, including endpoint intervals.
Simulation stage costs above exclude these visualization costs, file output, and independent diagnostics.
The warmup/rendering policy comes from the existing ovrtx renderer checkout. Renderer sources are unchanged.

## Resolution comparison

Both resolutions use the same physical tank, dam bounds, obstacle dimensions,
analytic motion, gravity, five-second duration, output schedule, and solver tolerances.
The particle counts, contact clearance, and SDF cell size scale with resolution.
This is a two-resolution sensitivity check; it is not a convergence proof.

| Scene | Particles: old → new | Occupied-volume drift: old → new | Max speed: old → new (m/s) | Simulation stages: old → new (s) |
|---|---:|---:|---:|---:|
| stage1 | 33264 → 64395 | -9.48% → -19.90% | 4.691 → 4.795 | 30.02 → 49.85 |
| stage2 | 33264 → 64395 | -9.48% → -19.90% | 4.691 → 4.795 | 43.58 → 64.47 |
| static | 32784 → 63673 | -10.75% → -24.41% | 4.435 → 4.730 | 55.32 → 79.34 |
| moving | 32784 → 63673 | -14.90% → -27.43% | 4.612 → 4.870 | 52.37 → 78.93 |
| deforming | 32784 → 63673 | -8.68% → -25.44% | 4.366 → 4.680 | 53.60 → 80.44 |

Simulation stage sums exclude file output, rendering, and independent diagnostics.
The first-order occupancy mask quantizes geometric volume; conserved particle mass
and small projected divergence do not establish exact material-volume conservation.
Differences between these trajectories are recorded, not used as a stability pass criterion.
Fixed/sparse equivalence is tested independently within each resolution.

![Resolution sensitivity](output/higher_resolution/resolution_comparison.png)

Reproduce the comparison after both runs exist:

```bash
/tmp/fluid-render-venv/bin/python "$EX/compare_resolution.py" \
  --low "$EX/output/long" --high "$OUT"
```
