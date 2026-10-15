# Inspect actual MeshToSDF root tiles in Polyscope

Yes: Polyscope can visualize these root tiles. The existing
[`scripts/mesh_to_sdf_viewer.py`](../../scripts/mesh_to_sdf_viewer.py) already registers
one sparse volume grid per fill level, with cell widths 1, 8, 128 and 4096 times
the voxel size. A root is **one coarse cell**, not 4096³ individual cells.

A fixed voxel-count ceiling was not established for Polyscope. The practical cost
depends on the cells actually registered, their quantities, topology and available
CPU/GPU memory. The default mode registers actual root flags and a small reference mesh.
`--all-levels` adds exact leaf/lower/upper/root fill and signed active cells for an
ROI, while `--whole-grid` explicitly requests every stored cell. No coarse tile is
expanded to fine voxels. The default is not a registration of 1.9 billion active cells.

The original viewer and library sources remain unchanged. This separate viewer
imports the original OBJ helper and sign palette, and uses its exact cell convention.

## Build and run

From this directory:

```bash
cmake -S . -B build
cmake --build build --target sdf_export_polyscope_roots -j2

# Use a Python environment containing Polyscope and NumPy.
python polyscope_root_viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb \
  --label 'band 3' --upper-fill
```

The development workstation already has the dependencies in
`/home/jaehlee/Desktop/work/.venv/bin/python` (Polyscope 2.6.1, NumPy 2.5.1).
The CMake project retains its existing CUDA configuration requirement, but the new
exporter itself is C++/CPU-only and this viewer does not allocate a CUDA grid.

`--mesh` defaults to the grid's sibling `.obj`, which is the translated copy used
for the actual conversion. An explicit OBJ must be in the **same world coordinates**
as the grid. Passing the original untranslated bunny would give a misleading overlay.
The inherited minimal OBJ loader expects positive vertex indices and triangulates
polygon faces with a fan, as in the original viewer.

The first launch reads the `.nvdb` on the CPU, temporarily requiring RAM for the
whole file (about 9.51 GiB for the passing bunny). It extracts small metadata and
caches `<grid-stem>.polyscope-roots.json` beside the grid. Subsequent launches use
that cache if the source path, byte size and modification time match; `--refresh`
forces an actual reread. Requesting upper fill refreshes a cache that lacks it.
The full NanoVDB grid is never uploaded to Polyscope's GPU.

## Structures and colors

Each structure has its own visibility checkbox in Polyscope:

| Structure | Meaning | Initially enabled |
|---|---|---|
| `negative root tiles (4096³)` | Actual `root_interior` flags, one full-size cell each, sign −1 | Yes |
| `input triangle mesh (reference)` | Actual converter input OBJ, translucent blue-gray | Yes |
| `unmarked root positions (+background)` | Childless, unflagged positions within active root bounds; implicit positive background, blue | No |
| `Upper children (root-scale wireframe)` | Root positions occupied by an Upper child, gray outline containers, not homogeneous signed tiles | No |
| `negative upper fill (128³)` | Actual childless negative upper mask cells | No; only registered with `--upper-fill` |

All negative fill uses the original viewer's same warm orange sign color; there
is no special sign color for root versus upper. Shading/transparency affects its
appearance. An unmarked root position is **not independently certified geometric
exterior**: it shows the file's implicit positive-background interpretation.

The triangle mesh is a positional reference, **not an extracted SDF zero crossing**.
The default mode focuses on root logic and optional coarse fill. The all-level
mode below also draws selected active, leaf and lower cells from the real data;
the triangle mesh remains an independent reference in both modes.
For the existing CCVIS workflow and all its active/fill structures, use the
original viewer. For direct full-field traversal, use the CUDA viewer in this directory.

Useful controls:

- Rotate/zoom with the standard Polyscope camera controls.
- Toggle the mesh to isolate root cells; adjust its transparency in its options.
- Enable `Upper children` and `unmarked root positions` to inspect the entire
  root-scale topology used by the fill.
- With `--upper-fill`, enable `negative upper fill (128³)` to compare node sizes.
- `--show-upper-fill` also extracts it but starts it visible.
- `--slice` creates a draggable clipping plane through index Z=2047.5 of the
  first scene. Coarse cells are cut open rather than culled as whole elements.

## Exact size/alignment and data provenance

For base index b, cell size s∈{128,4096}, voxel size dx and transform translation t:

```
Polyscope integer cell = b / s
Polyscope origin       = t - 0.5*dx
Polyscope cell width   = s*dx
world lower corner    = t + (b - 0.5)*dx
world upper corner    = t + (b + s - 0.5)*dx
```

The origin offset is **half a fine voxel**, not half a coarse tile. Every sparse
cell receives this same origin, matching the old fill viewer. `cube_size_factor=0`
means no shrink; it must not be set to 1 to request full size. See the
[official sparse-grid API](https://polyscope.run/py/structures/sparse_volume_grid/basics/).
The tool verifies alignment and the registered cell count.

The exporter accepts actual coordinate-list and legacy dense root metadata, validates
sizes/extents, and preserves every raw root flag. It reports overlap with Upper
children rather than filtering such flags out. Field lookup would give children
precedence; these diagnostics deliberately expose raw metadata. Upper fill is
`upper_invert & ~childMask`, with one 128³ cell per stored negative childless slot.
No dense interior reconstruction, inferred mask, geometry correction or voxel
sampling is used. Preferences are confined to ignored `output/polyscope/`.

## Compare the passing and failing bunny results

```bash
python polyscope_root_viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb \
  --label 'band 3' \
  --compare output/general-mesh-root/bunny-r4096.nvdb --compare-label 'band 2'
```

The two panels are shifted apart in world X **for display only**. Each reference
mesh and all its cells receive the same shift.

Verified actual file counts:

| Dataset | Negative roots | Upper children | Unmarked childless root positions |
|---|---:|---:|---:|
| Bunny, band 3 | 1 | 33 | 14 |
| Bunny, band 2 | 15 | 33 | 0 |

The earlier independent triangle oracle established that the band=3 root at
`(0,0,0)` is fully inside the bunny. At band=2, that one is inside but the other
14 returned roots are outside. The Polyscope viewer preserves this failing result
and draws all 15 raw negative cells with the same sign color. Color alone is not
proof of geometric containment. See [the verification record](GENERAL_MESH_ROOT_VALIDATION.md).

With `--upper-fill`, the passing bunny exports exactly **103,346** negative 128³
cells, matching the previous independent record. Coordinate-list and dense fixture
exports both reproduced root `(4096,0,0)` and one upper-fill cell; missing dense
`root_extent` was correctly rejected. Both EGL screenshots and a live GLFW window
were exercised on the development workstation. The original viewer was not edited.

## 4K screenshots

```bash
python polyscope_root_viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb \
  --label 'band 3' --headless --width 3840 --height 2160 \
  --screenshot output/polyscope/bunny-root-4k.png
```

Headless mode explicitly uses Polyscope's EGL backend; a functioning EGL/OpenGL
installation is required. Without `--headless`, `--screenshot` saves the initial
view and leaves the interactive window open. Screenshots use 2× SSAA and extra
transparency passes; interactive-only launches use lighter settings. `--frames N`
closes a GUI after N frames for a bounded smoke check.

Local artifacts (ignored, not pushed): `output/polyscope/bunny-root-4k.png` and
`output/polyscope/bunny-band-comparison-4k.png`. The latter uses the comparison
command above plus the headless screenshot flags; band 3 is left, band 2 is right.

## Every level plus signed active cells

```bash
python polyscope_root_viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb \
  --label 'all levels' --all-levels

# Explicit inclusive selection in index coordinates; implies --all-levels.
python polyscope_root_viewer.py output/general-mesh-root/band3/bunny-r4096.nvdb \
  --roi -8192 -4096 2048 8191 12287 2048
```

Without an explicit ROI, `--all-levels` selects a **one-fine-voxel Z slab** through
the root center, covering the mesh's full X/Y root bounds. It is an exact spatial
selection, not subsampling. The five independently toggleable structures are:

| Group | Actual native cell side | Color/value |
|---|---:|---|
| Negative leaf fill | 1 voxel | Inside orange, inactive leaf mask bits only |
| Negative lower fill | 8 voxels | Same inside orange, childless lower slots |
| Negative upper fill | 128 voxels | Same inside orange, childless upper slots |
| Negative root fill | 4096 voxels | Same inside orange; effective childless negative roots |
| Active signed voxels | 1 voxel | Negative orange, positive blue, plus optional signed-SDF scalar |

Selection retains a whole native cell if its index box intersects the ROI.
A root intersecting a one-voxel slab therefore remains a **4096³ cell**, not a
flattened 4096×4096×1 substitute. Its footprint can extend outside the selection
bounds. Use `--slice` or Polyscope's slice plane to cut cells visually. The UI
shows the ROI and counts so a selection cannot be mistaken for the entire grid.
ROI edits currently use command-line arguments; the scene supports interactive
camera, clipping and per-level visibility.

The passing high-resolution bunny's default slab is index
`[-8192,-4096,2048]…[8191,12287,2048]`. Actual selected counts were:

| Leaf | Lower | Upper | Root | Active |
|---:|---:|---:|---:|---:|
| 187,319 | 48,107 | 3,127 | 1 | 240,224 |

Inactive fill is `invertMask & ~valueMask` at leaf level and
`invertMask & ~childMask` internally, avoiding duplication of active/child cells.
Active SDF values are copied exactly. The cached per-level binary files store
little-endian `{int32 base[3]; float sdf;}` records (16 bytes each), with a JSON
completion manifest, in `<grid-stem>.polyscope-cells/<selection>/`. File sizes and
source size/mtime are checked before reuse. `--refresh` regenerates them. NumPy
memory maps these arrays; Polyscope still builds its own topology and GPU buffers.

```bash
# Entire volume: useful for smaller datasets that fit the available memory.
python polyscope_root_viewer.py /path/to/small-grid.nvdb --whole-grid --mesh /path/to/matching.obj
```

`--whole-grid` imposes no application cell-count cap and does not downsample.
It can require much more memory than the sparse NanoVDB renderer. The high-res
bunny contains 3,560,571,946 native inactive-plus-active cells: the 16-byte export
alone would occupy about **53.06 GiB**, before Polyscope's topology, colors and
rendering buffers. That whole-grid registration was not attempted on this laptop.
The ROI scene above was rendered and opened interactively instead. An actual small
bunny whole-grid export matched all stored counts exactly:
`[480391,2916,0,0,719507]` (leaf/lower/upper/root/active).

Both coordinate-list and dense fixtures reproduced all four fill origins and all
four signed active values. Point ROIs inside an 8³ or 4096³ cell retained the whole
coarse cell even when its origin lay outside the ROI. The high-res 4K artifact is
`output/polyscope/bunny-all-levels-4k.png`, with selection metadata embedded in PNG.
