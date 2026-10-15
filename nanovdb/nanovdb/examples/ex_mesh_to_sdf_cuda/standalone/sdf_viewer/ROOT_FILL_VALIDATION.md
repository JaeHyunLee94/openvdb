# Testing actual root-tile filling

This executable tests **the real `PropagateSign.cuh` implementation**, not just
viewer interpretation of a hand-authored root mask. It adds a standalone CUDA
target and does not change any library files.

A root tile covers **4096³ voxels**. Ordinary bunny data at the tested resolutions
contains no deep negative region at that scale. Making a physically huge dense
voxel shell merely to test this stage would be expensive; these tests instead
isolate the root algorithm using independent connectivity and topology oracles.

## Build and run

From the viewer directory:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12 -DBUILD_ROOT_FILL_VALIDATION=ON
cmake --build build --target sdf_validate_root_fill -j2
build/sdf_validate_root_fill --output output/root-fill-validation.nvdb
# Or run the assertions without exporting a grid:
ctest --test-dir build -R sdf_root_fill --output-on-failure
```

This target requires CUDA and the NanoVDB headers, but no OpenVDB, Polyscope,
Python packages, external meshes, or recent CCCL checkout. Match the CUDA host
compiler and architecture to the machine, as for the renderer.

The source includes the `PropagateSign.cuh` under `NANOVDB_INCLUDE_DIR`. By default
that is the enclosing checkout's `nanovdb` directory. To test a particular working
tree from a separate build/worktree, set it explicitly:

```bash
cmake -S . -B /tmp/root-fill-current-build \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12 \
  -DBUILD_ROOT_FILL_VALIDATION=ON \
  -DNANOVDB_INCLUDE_DIR=/absolute/path/to/working-tree/nanovdb
cmake --build /tmp/root-fill-current-build --target sdf_validate_root_fill -j2
/tmp/root-fill-current-build/sdf_validate_root_fill
```

The tiny API adapter accepts both the tuple-return `propagate()` implementation
and the earlier void-return implementation with owning output getters. The
internal root functor name is intentionally version-specific: this is a test of
the actual library implementation, not a separately reimplemented GPU fill.

## 1. Root flood compared with independent CPU BFS

`testRootKernel()` launches the library's real `RootPropagationFunctor` on a
nondefault nonblocking CUDA stream. Its output is compared byte for byte with a
CPU queue-based, six-connected BFS. The CPU oracle does not call the renderer or
any sign helper from the library.

| Case | Expected behavior |
|---|---|
| Closed 5³ shell inside a 7³ domain, interior seed | Exactly the 27 interior cells are reached |
| Same closed shell, no seeds | No fill is invented |
| Seed placed on a wall | Seed is cleared; zero cells are filled |
| Exterior seed with the closed wall | 218 exterior cells reached; interior remains isolated |
| A one-cell opening in the wall | Interior and exterior connect, reaching all 246 free cells |
| Two disconnected closed cavities, one seeded | Only the seeded cavity's 27 cells are reached |
| Eight deterministic random wall/seed grids | Exact equality with BFS, including non-cubic grids and 5,525 cells (more than one thread per cell) |

An opening connecting two regions is a **connectivity test**. It does not assert
that an open triangle mesh has a well-defined inside, or that mesh signing should
choose a particular interpretation of an opening.

## 2. Complete PropagateSign pipeline

`testPipeline()` constructs a sparse index grid at root scale. Every boundary
root position has an Upper child, containing one active leaf seed. Interior
root positions have **no Upper child**. This requires only a few MB, not an
allocation proportional to 4096³ times the number of root cells.

The real operator runs from active voxel signs through leaf fill, coarser face
seeding, lower/upper fill, root wall construction and root flooding, and finally
root-origin collection. All active signs are either negative or positive as
specified for each test. The expected absent interior root-origin set is computed
independently from the enclosing rectangular topology:

| Pipeline case | Upper children | Expected negative root tiles |
|---|---:|---:|
| 3×3×3 root shell with negative seeds | 26 | 1, at `(4096,4096,4096)` |
| Same root shell with positive seeds | 26 | 0 |
| Negative shell translated to root minimum `(-4,-3,-2)` | 26 | 1, at `(-12288,-8192,-4096)` |
| 4×5×6 shell translated to `(-2,1,-3)` | 96 | 24 |
| Fully occupied 2×2×2 root range | 8 | 0 |

Tests compare complete sets, not just counts. Each returned origin must be aligned
to 4096, unique, and associated with no Upper child. This catches missing/extra
tiles, duplicate output, axis-order errors, negative-coordinate mistakes and
incorrect overlap with existing child nodes. Both empty and nonempty root outputs
are exercised on the same nondefault stream.

**Scope:** these are synthetic sparse-topology fixtures, not voxelizations of a
watertight OBJ surface. An Upper child acts as a wall for the root algorithm, even
though the fixture stores only one leaf seed in it. Thus the tests validate root
connectivity, seeding through the hierarchy, and returned coordinates; they do
not establish correctness of triangle rasterization, active-voxel signing, or
all possible fine-scale surface configurations inside an Upper node. Root-flood
correctness and mesh-signing correctness are separate claims.

## 3. Inspect the actual generated root tile

`--output` reserves space for the expected root count, but fills the file with
**the actual GPU-returned masks and root origins only after all assertions pass**.
It does not insert the expected root coordinates as the result. The exported grid
has `sdf`, leaf/lower/upper masks and the coordinate-list `root_interior` channel.
Its sign/magnitude samples are a topology fixture, not a calibrated geometric SDF.

The transform uses voxel size `1/4096`, so the central 4096³ tile has world side
length 1. In the exported 3×3×3 example, the viewer reports inactive box counts
`[13286, 106470, 851942, 1]` for sizes `[1,8,128,4096]`.

Open it with:

```bash
python3 viewer.py output/root-fill-validation.nvdb --port 8767 --open
```

Select **Full-space signed cells**. In **Interior fill**, disable the active band,
Leaf, Lower and Upper while leaving Root checked. Exactly one orange 4096³ cube
should remain. Enable other levels and clip through its center to see that cube
surrounded by smaller stored fill cells. This visual inspection complements the
numeric tests; the assertions establish which tile the operator actually returned.

The development workstation also has saved camera presets and PNGs (not in Git):

```bash
python3 viewer.py output/root-fill-validation.nvdb \
  --settings output/root-fill-only-camera.json --port 8767 --open
python3 viewer.py output/root-fill-validation.nvdb \
  --settings output/root-fill-context-camera.json --render output/root-fill-context.png \
  --width 1600 --height 1200 --samples 4
```

## Validation record and limits

On the development workstation, all **14 root-kernel/BFS cases plus 5 full-pipeline
cases** passed against both the current working-tree header and the committed
header in the separate publishing worktree (CTest passed in 1.29 s). The viewer loaded and
rendered the exported masks with one root cube, and the existing library edits
were preserved unchanged.

A separate Compute Sanitizer memcheck was attempted, but the installed tool could
not locate `libsanitizer-collection.so`, so it did not run the test. Functional
success must not be reported as a clean sanitizer result. On a complete toolkit
installation, the additional check is:

```bash
compute-sanitizer --tool memcheck --leak-check full --error-exitcode 99 \
  build/sdf_validate_root_fill
```

If a future library change causes an assertion or an origin-set mismatch, the
executable exits nonzero and should be investigated before changing expected
results. Library fixes belong in a separately reviewed change; this tool does
not alter `PropagateSign.cuh` or silently compensate for algorithm errors.

Header fingerprints for the validated runs (SHA-256):

- Working tree, tuple-return API: `681c7086c4c023d82cece05dbc9b98161cc79188e104d6f32aa15fc8af1244f0`
- Committed header, owning-getter API: `1b3837eb6461e6d3ce2064cae2cfbdd43d98e819aa5cb438bc96502b9c861214`

## Actual triangle-mesh companion test

[REAL_MESH_ROOT_VALIDATION.md](REAL_MESH_ROOT_VALIDATION.md) adds a real closed
cube OBJ test at progressively smaller voxel sizes. Unlike the synthetic topology
fixtures above, it runs the complete existing MeshToSDF converter and verifies
its exported root origins against independent analytic cube geometry.
