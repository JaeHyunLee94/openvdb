# High-resolution continuation and mild surface filtering

Completed 2026-10-09: **10.0 simulation seconds at 384 x 384 x 288**, with
301 cache/mesh/render frames, 13,898,049 maximum APIC particles, and all physical,
pool, mesh-export and delivery checks passing. Every delivered frame reached
the requested 96-sample path-tracing convergence criterion.

- [Final H.264 video](output/scene_clear_shower_384_float_12s/dance_water.mp4)
- [Delivery checks](output/scene_clear_shower_384_float_12s/delivery_validation.json)
- [Physical and mesh checks](output/scene_clear_shower_384_float_12s/validation.json)
- [Pool checks](output/scene_clear_shower_384_float_12s/pool_validation.json)
- Representative renders: [0 s](output/scene_clear_shower_384_float_12s/render/frame_000000.png),
  [5 s](output/scene_clear_shower_384_float_12s/render/frame_000150.png),
  [10 s](output/scene_clear_shower_384_float_12s/render/frame_000300.png).
- Matching particle/block/halo views are in the run's `debug/` directory.

The folder retains its historical `_12s` name; the completed physical duration
is 10 s. Both endpoints are included, so the 301-frame, 30 fps movie is 10.033333 s.
The sections below preserve implementation decisions and diagnosed interruptions.


## Scene and selected resolution

The accepted `scene/clear_shower_fine.json` physical settings are retained:
0.21 m emitter radius, 0.36 m/s inflow, 0.064 m initial pool, closed basin,
unchanged character animation, whitewater generation, camera and materials.
The current run uses float/MGPCG, 384 x 384 x 288, fluid h=8.333333 mm,
obstacle h=4.166667 mm, 8 particles/cell, 30 output fps and a 10-second target (revised from 12 seconds on October 9).
Meshing remains independently set to 6.25 mm, rendering 1600 x 1200 / 96 samples.

384 is a practical choice for the existing approximately 12-hour simulation
budget and available disk, **not a measured GPU-memory maximum**. Both 384 and
512 passed earlier 0.1-second probes (78.853 and 227.946 wall seconds). Full
12-second particle CSV estimates are 354 GiB at 384, 562 GiB at 448 and 838 GiB
at 512; about 432 GiB was free at this continuation. Interaction later in the
animation costs more than the initial probe. No full-duration runtime is promised
from that probe.

## Contact failures repaired before continuation

The failure at t=0.728990251693 involved an exact-mesh exterior point with a
negative interpolated SDF. The prior revision enabled the SDF-aware fallback.
At t=1.772240988059 a similar point remained inside the sampled field because
the fallback searched only along the nearest triangle normal. Concave and
overlapping component regions need lateral escape candidates as well.

Revision `gpu-mgpcg-11`, entirely within the example:

- Backtracks normal projection steps and accepts only an improved SDF value.
- Searches the nearest normal and 26 local directions in expanding shells.
- Chooses the nearest valid candidate in the first successful shell, checking
  both the SDF and independent mesh parity after float-position rounding.
- Leaves unresolved contacts visible to the independent failure checks.
  It does not drop particles or relax tolerances.

`scene/verify_contact_escape.cu` re-evaluates the two recorded meshes/points and
runs the actual APIC contact kernel. Both pass: correction distances 9.87231 mm
and 7.60311 mm, remaining depth zero, inward relative speed at most 4.21e-9 m/s.
The displacement regression limit is 20 mm. These exceptional projections are
discrete contact repair, not continuous collision detection.

The full checkpoint replay from 1.766667 to 1.8 seconds passed. Its cumulative
metrics through 1.8 seconds (6,554 steps) are:

| Check | Maximum / result | Unchanged criterion |
|---|---:|---:|
| Remaining penetrations / depth | 0 / 0 m | 0 / 2e-5 m |
| Missing stencils | 0 | 0 |
| Relative-normal contact error | 8.011e-7 m/s | 2e-5 m/s |
| Reported relative pressure residual | 9.446e-5 | absolute <= max(1e-12, 1e-4 * RHS norm) |
| Moving-boundary flux divergence | 2.577e-4 | 2e-3 |
| Fluid and secondary ledgers, inflow quantization, CFL | PASS | existing tests |

The run resumes with 8,244,274 APIC particles at frame 54. Evidence is under
`output/filter_20261008/contact_shell_replay/`; the original failed checkpoint,
metrics and revision-10 executable remain under `output/overnight_20261008/failure_177/`.

## OpenVDB surface processing

The reconstruction starts as anisotropic **density**, not signed distance.
`levelSetRebuild` reconstructs its iso=0.3 surface into a negative-inside SDF.
Only then does `LevelSetFilter` perform:

1. Dilation by 0.25 meshing voxel (1.5625 mm; negative offset).
2. One mean-curvature step with a constant 0.5-strength mask.
3. Erosion by the same distance (positive offset).

Mean curvature targets small surface irregularities with one mild step rather
than repeated broad averaging. Afterwards solid/floor/side constraints are
restored and `volumeToMesh` extracts iso=0 with adaptivity=0. Rendered foam is
projected against the filtered field. No simulation positions or mass change.
Configuration key `mesh_closing_radius` is in meshing-voxel units; default 0
preserves the old reconstruction. The new long-run config sets it to 0.25.

The mesher measures both filtered and unfiltered mesh volume on the same frame.
`filter_ms`, `unfiltered_mesh_volume` and `filter_volume_ratio` are appended to
`meshing.csv`; the filter-specific validation limit is 3% absolute volume change.
This is separate from mesh/material-volume bias and the simulation mass ledger.

| 384 frame | Filtered / unfiltered volume | Filtered / particle volume | Filter cost |
|---|---:|---:|---:|
| 0 | 0.998529 | 1.03391 | see initial probe CSV |
| 52 | 1.024349 | 1.056151 | 1.511 s |
| 53 | 1.024348 | 1.055023 | 1.600 s |

The adjacent normalized volume change for frames 52–53 is 0.10685%. All three
exported meshes pass closed-edge incidence, finite positions, volume/winding,
floor and side bounds, and OBJ/binary agreement. These checks do not prove
absence of local temporal flicker. A 0.5-voxel preliminary test added about 2.89%
volume on the later frames; the selected 0.25-voxel setting is milder.

Outputs:

- `output/filter_20261008/filter_validation.json`
- `output/filter_20261008/high_quarter/` and `initial_quarter/`
- [384 representative render](output/scene_clear_shower_384_float_12s/preview_curvature_filter/frame_000053.png)
- Preliminary 160-resolution filter render:
  `output/scene_clear_shower_fine/preview_curvature_filter/frame_000036.png`

The accepted original video has not been overwritten. The final new video is
available at the delivery link above, after full simulation/surface checks and
per-frame path-tracing convergence verification.

## Checkpoints and overlapping CPU meshing

`scene/overnight_run.py --stream-mesh` runs one sequential CPU mesher alongside
the GPU solver. It waits for atomic checkpoint publication before reading each
frame, so the temporal anisotropic-kernel history is preserved and partially
written frame data is not consumed. Frozen executables live in the run directory.
On normal exit/failure/pause the supervisor terminates its mesher. A plain resume
rebuilds surfaces from frame zero; `--resume-mesh` retains the committed prefix
and verifies a warm overlap as described below. Particle caches remain intact.
After both stages finish, validation precedes rendering. CPU per-stage sums and
streaming wall time (which includes waits) are reported separately.

The supervisor integration test resumed a low-resolution checkpoint at 14/30 s,
completed 0.5 s and produced all 16 mesh frames. Numerical failures still stop
with the checkpoint and evidence intact; they are not fixed by blind retries.
The active continuation uses the diagnosed contact fix above.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
BIN=build/release/nanovdb/nanovdb/examples
PY=$EX/output/render-venv/bin/python

cmake --build build/release --target ex_mesh_to_sdf_fluid_scene_float_cuda \
  ex_mesh_to_sdf_fluid_surface ex_mesh_to_sdf_fluid_contact_escape_verify -j 3
$BIN/ex_mesh_to_sdf_fluid_contact_escape_verify "$EX/output/character_grounded"

# Existing active run: inspect, do not start a duplicate.
cat "$EX/output/scene_clear_shower_384_float_12s/status.json"

# Resume only after a deliberate pause or a diagnosed/repaired failure.
python3 "$EX/output/scene_clear_shower_384_float_12s/resume.py"

# Representative filtered mesh pair, separate from the active full sequence.
$BIN/ex_mesh_to_sdf_fluid_surface \
  "$EX/output/scene_clear_shower_384_float_12s" /tmp/fluid_filter_comparison \
  .00625 7.2337962962963e-8 .004166666666666667 .3 2.4 .12 52 53 1 1 0 .25
```

Full launch/configuration are recorded in the run's `launch.json`,
`pipeline_config.json` and `RUN.md`. Only example code and example CMake were
changed for these fixes; existing NanoVDB library and ovrtx sources were not edited.

## 2026-10-09: continue to 10 seconds, including after interruption

The user subsequently requested active supervision until at least 10 seconds.
The process was still running when checked, and has remained under observation.
At 10:17 local time, a controlled checkpoint handoff at exactly 8.2 simulation
seconds changed the target to 10 seconds and the supervisor wall budget to
24 hours. It has continued past 8.29 seconds without a new numerical failure.
Only duration changes from the former physical configuration.
The existing cache folder keeps its historical `...384_float_12s` name.

`scene/overnight_run.py --resume --stream-mesh --resume-mesh` can now retain
already published surface frames. `scene/surface_resume.py` reconstructs the
last 32 preceding frames into a separate staging directory, then checks the
last overlapping mesh and rendered whitewater before publishing new frames.
The only temporal reconstruction state is covariance with 0.3 previous-state
weight; 32 frames reduce the unrounded history difference by 0.3^32. This
mathematical decay is supplemented by an actual overlap comparison on every
resume: identical connectivity and whitewater identity, coordinates within
1 micrometre, and material/kernel/mesh volumes within 1e-8 relative error.
An overlap mismatch stops the mesher and is reported without orphaning the GPU
solver. Original frames are retained; staging output is linked into the main
surface directory only after the overlap passes. The CSV report is published
atomically. Warmup costs are reported separately in pipeline_times.json.

Completed checks:

- A coarse checkpoint resumed from 0.5 to 16/30 seconds, preserving all existing
  surface files exactly and adding the new frame. The usual simulation checks
  passed. Repeating resume at the completed target also passed.
- The overlap mesh and whitewater coordinate errors were zero in both tests.
- A deliberately displaced overlap vertex (1 mm) was rejected, and the
  published prefix remained byte-for-byte unchanged.
- The real 384 cache was reconstructed from frames 148 through 180, independently
  of its original frame-0 history. At frame 180, mesh coordinates, connectivity,
  rendered whitewater positions and identity, and all three volume measures
  matched the original continuous reconstruction exactly.

Evidence: `output/filter_20261008/surface_resume_test/`,
`output/filter_20261008/surface_resume_rejection.json`, and
`output/filter_20261008/warm_resume/overlap_validation.json`.
Next-resume configuration: `output/overnight_20261008/run_384_10s.json`.
These changes have not interrupted the active simulation or altered its scene.


## Deterministic parallel surface PCA (October 9)

The independent per-particle covariance/eigendecomposition work now runs inside
an optional TBB task arena (`mesh_pca_threads`, default 4). Neighbor enumeration,
per-particle summation order, temporal covariance, and serial scalar-field
accumulation are unchanged. Read-only bins/history are shared; each particle
writes a distinct preallocated result. Reductions combine only maxima and integer
counts. A temporary destination-pointer array adds about 8 CPU bytes/particle;
there is no GPU-memory or solver-state change.

For the same 384-resolution cache, frames 148–180 were reconstructed both ways:

| Check | Result |
|---|---:|
| Compared frames | 33 |
| Maximum mesh-coordinate difference | 0 m |
| Triangle connectivity | identical |
| Maximum rendered-whitewater position difference | 0 m |
| Whitewater identity/state and non-timing CSV fields | identical |
| Original summed complete-frame processing time | 7,680.010 s |
| Four-thread summed complete-frame processing time | 2,711.004 s |
| Observed whole-stage speedup | 2.833x |

The measurements include PCA, grid construction, filtering, contouring and I/O,
and were made while the GPU scene and the old production mesher also ran; they
are not isolated CPU microbenchmarks. Evidence is
`output/filter_20261008/parallel_pca/parallel_validation.json`.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
$EX/output/render-venv/bin/python $EX/scene/verify_surface_parallel.py   $EX/output/filter_20261008/warm_resume   $EX/output/filter_20261008/parallel_pca
```

At 11:10 local time, the run was checkpointed at 8.7 s, the frozen surface
executable was replaced, and the same GPU executable resumed immediately.
`restarts/parallel_pca/` contains the checkpoint hardlink, prior reports,
configuration and serial executable. At that handoff the 10-second physical simulation was still in progress;
it subsequently completed as recorded below.


At 12:08 local time, the production warm replay (frames 197–229) passed its
independent overlap check at frame 229: mesh and rendered-whitewater coordinate
errors both zero, with identical mesh connectivity and whitewater identity.
The validated continuation then began publishing frame 230 onward. Evidence:
`output/scene_clear_shower_384_float_12s/surface_resume_bolmgo8o/overlap_validation.json`.


## Ten-second physical simulation completed

At 13:53 local time on October 9, the solver printed `PASS scene` and committed
checkpoint time 10.0, next frame 301. There are 40,984 steps, 301 output frames,
and 13,898,049 final/maximum APIC particles. Maximum allocated leaf-block count
is 12,090 (6,190,080 leaf slots; this is not an exact active-voxel count).
The observed system GPU-memory sample maximum is 3,310.5 MiB; this is neither
an allocation-exact peak nor an isolated solver-only measurement.

`simulation_completion.json` in the run directory records the independent audit:
all pressure residuals satisfy max(1e-12, 1e-4 RHS norm); remaining fluid and
secondary penetration depth, stencil misses and mass ledger errors are zero.
Maximum moving-boundary flux divergence is 2.5766485987e-4 (limit 2e-3),
wall-flux error 1.19209080829e-7 (limit 2e-5), inward relative-normal contact
error 8.01076964763e-7 m/s (limit 2e-5), and CFL 0.217874 (limit 0.5).
Independent primary/secondary ledgers, emitter quantization and statistical
whitewater births pass. The full mesh audit remains separate.

Representative debug images (particle mass, secondary particles, character,
allocated blocks and halo) are in the run's `debug/` directory at frames
000000, 000150 and 000300. These correspond to 0, 5 and 10 seconds.
The accepted physical scene is unchanged; duration is the latest requested 10 s.


## Full surface export audit and measured costs

All 301 exported meshes passed: zero non-two-face edges, minimum y=0, zero
extension beyond the closed sidewalls, matching OBJ/binary connectivity and
maximum OBJ/binary vertex difference 7.45e-9 m. The filter-only volume ratio
range is 0.998426–1.024554. Reconstructed/particle volume ranges from 0.911175
to 1.097904; this reconstruction bias is separate from the exactly conserved
particle ledger. Maximum adjacent normalized volume change is 0.5610% (limit
8%); it is a global flicker proxy, not proof of local temporal coherence.

The tables below sum recorded phase timers over the accepted 40,984-step
trajectory. They exclude discarded failed attempts. Meshing overlaps simulation;
its costs must not be added to simulation wall time. The current
`simulate_this_session` value (9,751.507 s) covers only the final 8.7–10 s resume,
not the complete 0–10 s trajectory. The observed memory peak precedes final
rendering and is not a rendering-memory measurement.

| Recorded simulation phase | Mean per step (ms) | Sum (s) |
|---|---:|---:|
| Sparse topology | 23.066 | 945.331 |
| MeshToSDF | 23.512 | 963.631 |
| Obstacle sampling/boundaries | 80.967 | 3318.361 |
| P2G | 108.091 | 4430.011 |
| Pressure | 225.436 | 9239.265 |
| G2P | 157.630 | 6460.322 |
| Particle contacts | 391.215 | 16033.558 |
| Whitewater | 217.549 | 8916.035 |
| Transfers/output staging | 2.444 | 100.164 |
| File output (separate from simulation) | 55.011 | 2254.579 |

| CPU surface phase | Mean per frame (s) | Sum (s) |
|---|---:|---:|
| read | 8.959 | 2696.692 |
| pca | 130.313 | 39224.101 |
| grid | 7.078 | 2130.410 |
| clip | 0.182 | 54.755 |
| contour | 0.030 | 9.062 |
| write | 0.616 | 185.512 |
| filter | 1.800 | 541.825 |

The 44,842.356 s aggregate surface cost mixes the original serial prefix and
parallel continuation. The successful production warm replay cost another
3,405.927 s, reported separately. Earlier test/replay attempts are retained as
benchmark evidence and are not included in these canonical per-frame sums.
The bottlenecks in this scene include character contact and secondary-particle
updates; MGPCG alone does not make the whole solver resolution-independent.

A final-quality midpoint render is available at
`output/scene_clear_shower_384_float_12s/preview_filtered_midpoint/frame_000150.png`
(1600 x 1200, 96 samples, unchanged ovrtx/camera/materials). The renderer's
single-frame measured step was 11.223 s, excluding USD authoring and PNG I/O.


## Float32 secondary-wall audit correction

The independent pool audit initially stopped on one precision mismatch:
`secondary_inside_basin` compared float32 wall-clamped particles to exact 3.2 m /
2.4 m planes with the old double-only 1e-7 m tolerance. Maximum reported excess
was 2.873e-7 m (0.2873 micrometre), at frame 272, secondary ID 4084458940214.
The stored h is float32 0.008333333767950535. Its x endpoint is
3.200000286102295 with a separate float32 multiply, or 3.2000001668930054 before
a fused subtract/round. Thus a correctly clamped float32 position can fail the
old exact-plane comparison.

All saved secondary particles were independently checked against the actual
float32 `n*h-radius` clamp, covering fused and unfused IEEE evaluation orders:
zero particles and zero excess beyond that representable envelope. The corrected
`verify_pool.py` uses this envelope with **zero extra tolerance** for float runs,
while retaining the exact-plane 1e-7 m criterion for double runs. Physical-plane
excess is still separately reported; no particles, cache, solver, scene or
boundary dynamics were changed.

`verify_secondary_roundoff.py` accepts the recorded real boundary point and
rejects positions moved 1 micrometre through either side or the floor, rejects
nonfinite input, and confirms the double criterion remains unchanged. The
failed report/logs remain in `restarts/secondary_roundoff/`; diagnosis and
regression evidence are `secondary_roundoff_diagnosis.json` and
`secondary_roundoff_regression.json` in the run directory. Only validation and
rendering were restarted via `finish_validated.py` / `postprocess_launch.json`.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
$EX/output/render-venv/bin/python $EX/scene/verify_secondary_roundoff.py \
  $EX/output/scene_clear_shower_384_float_12s
```


## Final-render convergence correction

Visual comparison caught a separate output issue after physical and mesh audits
passed. The old loop saved one `renderer.step` after each animated USD update.
The first frame reached the requested 96-sample PT stop criterion, but subsequent
updated frames could return `progression=1, converged=false`. This suppressed
small whitewater detail and differed from a directly loaded still frame.

A controlled 0 -> 5 s test measured progression 97 / converged=true initially,
then progression 1 / false after the update. Resetting history produced a
converged result and reduced mean 8-bit RGB error against direct loading from
4.467 to 0.346. A second test reset **before** rendering updated frames at 5 and
10 s; both returned progression 96 and converged=true.

The example adapter now calls the existing `renderer.reset(time=frame_time)`
after the USD update and refuses to save an unconverged frame. It records each
frame's convergence/progression in `render/timings.json`. No renderer library,
material, lighting, camera, geometry or simulation setting changed. The
empty-to-nonempty whitewater diagnostic also passed its original criteria:
mean RGB difference 0.4712 < 0.5, fraction of pixels differing by more than 10
is 0.004537 < 0.005, and 4,063 orange diagnostic spray pixels > 50.

The initial unconverged movie and frames are retained in
`restarts/render_convergence/`; they are **not the delivery movie**. Its 332.690 s
render-stage time / 55.149 s summed frame-step time must not be presented as
96-sample animation performance. The final converged rerender has completed and passed delivery checks.
Evidence: `render_history_probe/telemetry.json`,
`render_reset_before_probe/telemetry.json`, `render_visibility.json`, and their
corresponding diagnostic images/logs in the run directory.


## Final delivery and reproduction

`delivery_validation.json` verifies all 301 ordered PNGs and all 301 convergence
records, 96 requested samples, the 1600 x 1200 H.264 High / yuv420p / 30 fps stream,
and complete error-free FFmpeg decoding. The final file is 28,969,460 bytes.
Its SHA-256 is `7ec362f29de22e2be2ddb80611e5f9a8b3fc3e334b65dc730daf3b97c42b151d`.
The corrected movie's frame 150 differs from the independently rendered still by
0.3339 mean 8-bit RGB units (criterion 0.5), versus 4.4751 for the discarded
unconverged output. The delivered frames have convergence progression 96–97,
all marked converged by ovrtx.

Successful full validation cost 1,284.955 s. The final render stage took
3,553.667 s (including USD authoring, image output and encoding). Recorded render
steps sum to 3,293.852 s, averaging 10.943 s/frame, maximum 11.478 s/frame. These
postprocessing costs are separate from simulation and meshing costs above.
Diagnostic and discarded attempts are archived and excluded from these final
successful-stage timings.

The pool audit confirms no drain, conserved inflow, contained fluid and secondary
particles under the documented precision model, and increasing floor volume.
The independent median height proxy rises from 0.06304 m at 1.2 s to 0.10796 m
at 10 s; this is a particle quantile proxy, not an exact level-set height.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
PY=$EX/output/render-venv/bin/python
RUN=$EX/output/scene_clear_shower_384_float_12s

# Inspect the completed deliverable; do not restart the finished simulation.
cat "$RUN/delivery_validation.json"

# Reproduce from the same configuration into a NEW cache directory.
cmake --build build/release --target ex_mesh_to_sdf_fluid_scene_float_cuda \
  ex_mesh_to_sdf_fluid_surface -j 3
systemd-inhibit --what=sleep:idle --mode=block "$PY" "$EX/scene/overnight_run.py" \
  "$EX/output/overnight_20261008/run_384_10s.json" "$EX/output/reproduce_384_10s" \
  --hours 24 --stream-mesh --postprocess

# Optional: rerender the completed cache using the fixed convergence guard.
"$PY" "$EX/scene/pipeline.py" "$RUN/pipeline_config.json" \
  --output "$RUN" --stages render
```

The requested mild SDF dilation/mean-curvature/erosion is render-only. It does
not remove all physical small-scale surface motion, and global volume stability
is not a proof of local flicker absence. Contact repair remains discrete, and
384 is the selected practical run resolution rather than a measured GPU-memory
ceiling. Existing NanoVDB and ovrtx library sources were not modified.


## Render-only whitewater size adjustment (2026-10-10)

The completed 384 x 384 x 288, 10-second simulation cache was reused. Foam
render radii (and diameters) are multiplied by 0.70; spray radii by 0.80.
The example's `scene/render_scene.py` applies these factors around the cached
particle centers. Particle count, trajectories, collision radii, liquid meshes,
character animation, materials, lighting and camera remain as cached/authored.
Simulation and surface reconstruction were not rerun. NanoVDB and ovrtx library
code was not changed.

The new CLI options default to 1.0 for compatibility. Non-default size variants
require `--tag`, keeping the accepted original render separate. The factors are
recorded in both USD layer metadata and render `timings.json`.

From the repository root, reproduce this render only:

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
RUN=$EX/output/scene_clear_shower_384_float_12s
"$EX/output/render-venv/bin/python" "$EX/scene/render_scene.py" "$RUN" \
  --character "$EX/output/character_grounded" \
  --width 1600 --height 1200 --samples 96 \
  --tag smaller_whitewater --foam-render-scale 0.7 --spray-render-scale 0.8
# Add --only-frame 150 to render the midpoint preview instead of the full movie.
```

Outputs relative to `RUN`:

- `dance_water_smaller_whitewater.mp4`: H.264/yuv420p, 1600 x 1200,
  30 fps, 301 frames / 10.033333 seconds including the endpoint.
- `render_smaller_whitewater/frame_000000.png` through `frame_000300.png`.
- `whitewater_size_comparison.png`: unchanged pixel crops from the original
  midpoint and the smaller-particle preview, with labels.
- `smaller_whitewater_validation.json`, `smaller_whitewater_geometry_check.json`,
  and `smaller_whitewater_midpoint_validation.json`: verification evidence.
- `smaller_whitewater_source_hashes.json`: before/after preservation manifest.

All 301 frames converged at progression
96–97.
Full video decoding, dimensions, frame count, frame order, FPS and codec passed.
The 307 source hashes match: all 301 surface-projected whitewater CSVs, three
representative liquid mesh caches, settings, frame metadata and the original
video. The original `dance_water.mp4` is preserved.

The midpoint geometry check covers 41,473 foam and 2,635 spray particles;
triangle connectivity is unchanged and scaled vertices agree with scaling
about each cached center to within 2.39e-7 m (float rounding). The independent
midpoint preview versus full-sequence render has mean absolute RGB difference
0.468353 / 255 (criterion < 0.5).
Early, midpoint and final appearance were inspected. Foam remains
visible with less prominent individual spheres.

Full authoring/rendering/output/encoding wall time: 3547.285 s
(59.12 min). Recorded render steps total
3282.231 s; simulation and meshing cost for this adjustment: zero.
New movie SHA256: `b0d15392a80d0aa373c982585f61cc02da02bb54d1d0bf101f67400f41104aa9`.
