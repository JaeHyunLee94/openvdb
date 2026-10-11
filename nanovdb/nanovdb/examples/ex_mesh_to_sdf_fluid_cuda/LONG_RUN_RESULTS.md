# Five-second physical-time validation and 3D animation

All five scenes run to physical simulation time 5.000000 s. Obstacle motion repeats 4.77 periods.
Adaptive substeps stop exactly at scheduled output times. Baselines save 10 fps; obstacle scenes save 30 fps.
Every simulation substep checks pressure, topology/velocity stencils, finite particles/affine matrices,
tank bounds, and CFL. Obstacle runs additionally check analytic wall flux and SDF/analytic-mesh penetration.

| Scene | Substeps | Max relative residual | Max physical RMS divergence (1/s) | Max speed / final speed (m/s) | Leaves |
|---|---:|---:|---:|---:|---:|
| stage1 | 1285 | 9.988e-10 | 2.821e-09 | 4.691 / 0.102 | 180–180 |
| stage2 | 1285 | 9.988e-10 | 2.821e-09 | 4.691 / 0.102 | 80–120 |
| static | 1340 | 9.997e-10 | 2.544e-09 | 4.435 / 0.234 | 80–118 |
| moving | 1290 | 9.998e-10 | 2.647e-09 | 4.612 / 0.257 | 75–120 |
| deforming | 1315 | 9.997e-10 | 3.387e-09 | 4.366 / 0.245 | 80–119 |

Criteria: residual <= 2e-8; RMS divergence <= 1e-6 1/s; CFL <= 0.5;
blocked/contact normal error <= 1e-8 m/s; zero remaining penetration deeper than 1e-7 m.
Particle count remains constant within each scene. No NaN/Inf, missing stencil, tank escape, or progress stall.
Stationary-wall energy must not increase more than 5% over its first substep. This check passed.
Moving-wall energy is recorded but not treated as conserved, because the obstacle performs work.
Total energy includes the particle affine contribution with quadratic-kernel moment h^2/4;
it is a useful diagnostic, not an independently conserved discretized mechanical-energy theorem.

| Scene | Wall error (m/s) | Contact error (m/s) | SDF / mesh remaining penetrations | Max attempted depth (m) |
|---|---:|---:|---:|---:|
| static | 0.000e+00 | 1.957e-16 | 0 / 0 | 0.000e+00 |
| moving | 1.110e-16 | 3.875e-16 | 0 / 0 | 0.000e+00 |
| deforming | 1.110e-16 | 3.544e-16 | 0 / 0 | 0.000e+00 |

Fixed/sparse particle comparison: **PASS**, max position 1.000e-09 m, max velocity 1.000e-09 m/s, tolerance 1e-6.
All 51 stored physical-time frames are compared, not independently numbered substeps.

## Volume limitation exposed by the longer run

Particle mass/count is conserved. Occupied-cell volume is a separate coarse free-surface diagnostic.
It is not an exact material volume. These runs do not establish geometric volume conservation.

| Scene | Initial occupied-cell volume (m^3) | Final (m^3) | Change |
|---|---:|---:|---:|
| stage1 | 0.51975 | 0.47050 | -9.48% |
| stage2 | 0.51975 | 0.47050 | -9.48% |
| static | 0.51275 | 0.45763 | -10.75% |
| moving | 0.51275 | 0.43638 | -14.90% |
| deforming | 0.51275 | 0.46825 | -8.68% |

The first-order particle occupancy mask and lack of reseeding/volume correction cause a measurable
change in the occupied-cell volume. Small projected divergence alone must not be interpreted as
a proof that the material volume stays constant. A fluid SDF/subcell free surface and a dedicated
volume test remain necessary before treating this as a production obstacle solver.

## Timing

Means in milliseconds/substep. CUDA stage wall timers include synchronization and orchestration;
I/O and independent CPU diagnostics are excluded. Simulation and rendering were run sequentially.

| Scene | Topology | MeshToSDF | Boundary sampling | P2G | Pressure | Extrapolation/G2P | Contacts |
|---|---:|---:|---:|---:|---:|---:|---:|
| stage1 | 0.000 | — | — | 0.885 | 20.898 | 1.583 | — |
| stage2 | 11.094 | — | — | 0.864 | 20.518 | 1.436 | — |
| static | 10.811 | 4.004 | 0.683 | 0.854 | 21.796 | 1.457 | 1.680 |
| moving | 10.544 | 3.840 | 0.664 | 0.855 | 21.889 | 1.437 | 1.364 |
| deforming | 10.654 | 3.920 | 0.700 | 0.854 | 21.627 | 1.448 | 1.554 |

## Animation artifacts

The 3D scene contains actual particle markers, animated obstacle vertices, tank edges, lights, and camera.
The USD contains 151 time samples per obstacle scene at 30 time codes/second.
ovstage.update_from_usd_time takes seconds; the authoring code converts seconds to USD time codes.
ovrtx reuses one renderer and stage through the sequence. Forty warmup steps happen before capture;
render accumulation steps at a fixed pose do not advance simulation time.

| Scene | 3D MP4 | Particle/block debug MP4 | Animated USD scene |
|---|---|---|---|
| static | [static/animation.mp4](output/long/static/animation.mp4) | [debug](output/long/static/debug.mp4) | [scene.usdc](output/long/static/scene.usdc) |
| moving | [moving/animation.mp4](output/long/moving/animation.mp4) | [debug](output/long/moving/debug.mp4) | [scene.usdc](output/long/moving/scene.usdc) |
| deforming | [deforming/animation.mp4](output/long/deforming/animation.mp4) | [debug](output/long/deforming/debug.mp4) | [scene.usdc](output/long/deforming/scene.usdc) |

[Combined three-scene video](output/long/demo.mp4) concatenates the three separate 5 s simulations;
it does not claim a single 15 s simulated trajectory. The endpoint frame adds one display interval.
All video frames are also preserved under each scenario’s `rtx/` and `debug/` folders.
Rendering and USD-authoring durations are in `animation_times.json`, separate from simulation metrics.

![Stability diagnostics](output/long/stability.png)

## Reproduction

```bash
cmake --build build/release --target ex_mesh_to_sdf_fluid_cuda -j 4
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
/tmp/fluid-render-venv/bin/python "$EX/validate_long.py" \
  build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda --duration 5
for scene in static moving deforming; do
  /tmp/fluid-render-venv/bin/python "$EX/animate.py" "$EX/output/long/$scene"
done
/tmp/fluid-render-venv/bin/python "$EX/assemble_animation.py"
/tmp/fluid-render-venv/bin/python "$EX/report_long.py"
```

Additional Python packages for animation/plots: `usd-core`, `matplotlib`; encoding uses installed ffmpeg.
All implementation changes remain in the new example folder; library and ovrtx sources are untouched.
