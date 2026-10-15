# Interactive MeshToSDF renderer

[한국어 사용 설명서](USER_GUIDE.ko.md) · [Code and data contracts](ARCHITECTURE.md)

A standalone CUDA renderer for this branch's **ValueOnIndex + SDF + interior-mask**
`.nvdb` files, and conventional float NanoVDB level sets. It adds no targets to the
parent build and changes no existing library/example files. All source, build
products and optional figures live in this directory.

The browser is a local control panel; the CUDA backend renders the original sparse
grid on the GPU. No voxel meshes, dense 3D textures, downsampled grids or marching
cubes are generated. Python uses only its standard library. No Polyscope, OpenGL,
GLFW, npm packages or external web services are needed.

## Start here

From the repository root:

```bash
cd nanovdb/nanovdb/examples/ex_mesh_to_sdf_cuda/standalone/sdf_viewer
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12
cmake --build build --target sdf_renderer -j2
python3 viewer.py /path/to/result.nvdb --open
```

Visit **http://127.0.0.1:8765** if a browser does not open. Ctrl+C stops the server.
The GCC 12 override is appropriate for this workstation's CUDA 12.0; on other
machines use a host compiler supported by the installed CUDA toolkit.
`-DCMAKE_CUDA_ARCHITECTURES=90-virtual` is the default, producing PTX that this
Blackwell GPU can JIT. Override it for other GPUs/toolkits, e.g. `86` on Ampere.
First use may take several seconds to JIT; subsequent frames are much faster.

Dependencies: CMake >= 3.24, a CUDA toolkit and NVIDIA driver, C++17 compiler,
zlib development headers/library, Python >= 3.9, and a browser. Blosc-compressed
files are supported when CMake finds Blosc. Default uncompressed and ZIP files
work without Blosc. For an alternate library location use `--library PATH`.
For a multi-grid file select `--grid-index N` (zero based).

### Produce a MeshToSDF file

The **current** example driver already writes self-contained `.nvdb` files; the
older `CC_EXPORT_VIS` / `.ccvis` instructions refer to a previous interface.
From the repository root, with a current example binary:

```bash
build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_cuda \
  /path/to/meshes/hairball.obj 0.01 3 0 /tmp/hairball.nvdb
```

Arguments are `mesh.obj voxelSize bandWidth isoValue output.nvdb`. `bandWidth` is
in voxels; the converter's `isoValue` is in world units. The viewer's iso control
is in **voxels** relative to the resulting SDF.

To ensure the converter uses your current source without rebuilding or editing
anything in the parent project, this standalone build can compile the two
existing driver files:

```bash
cmake -S . -B build -DBUILD_MESH_CONVERTER=ON \
  -DCCCL_SOURCE_DIR=/path/to/openvdb/build/release/_deps/cccl-src
cmake --build build --target sdf_from_mesh -j2
build/sdf_from_mesh /path/to/meshes/hairball.obj 0.01 3 0 /tmp/hairball.nvdb
python3 viewer.py /tmp/hairball.nvdb --open
```

The optional converter needs the recent CCCL headers used by this branch;
CUDA 12.0's bundled CCCL alone lacks `cuda::minimum`. The default
`CCCL_SOURCE_DIR` points to the existing repository's `build/release/_deps/cccl-src`.
The renderer itself does not need that extra dependency or the MeshToSDF headers.

## Interaction and figures

- Left drag orbits; Shift-drag / right drag pans; wheel zooms. **F / Fit** resets
  camera framing. X/Y/Z buttons look along positive world axes.
- **SDF surface** renders a refined crossing of the trilinear SDF, with gradient
  normals, diffuse/specular shading and optional local SDF occlusion.
- **Transmittance volume** integrates an absorbing shell around the isosurface:
  `rho = max(0, 1 - abs(sdf - iso)/shellWidth)` and
  `alpha = 1 - exp(-density * rho * raySegmentLengthInVoxels)`. Front-to-back
  compositing uses gradient/view-dependent shading. This is a visualization
  transfer function, not a physically calibrated material or path tracer.
- **Surface normals** displays outward world-space normals mapped to RGB.
- **Sign slice · full field** displays nearest-voxel signs: warm = negative, cool = positive.
  It includes inactive interior voxels and tiles. Near-zero values are brightened;
  that stripe does not indicate the active band width.
- **Signed active voxels** draws the actual active unit cubes with orange negative
  and blue positive faces. No interpolation or zero crossing is used. Opaque outer
  voxels hide inner ones; use clipping to reveal the negative band.
- **Sign slice · active band** displays only active voxels on a plane, with uniform
  sign colors. Use this to inspect the full narrow-band width. Use 1 spp for raw
  pixel-level sign inspection; supersampling can mix adjacent colors.
- **Full-space signed cells** adds the negative inactive regions stored in
  PropagateSign's invert masks to the active band. Leaf/lower/upper/root fill is
  drawn as 1³/8³/128³/4096³ cubes, preserving sparse storage granularity. All
  negative cells have the same orange base color. The **Interior fill** controls
  independently toggle the band and four fill levels, with stored-box counts.
  Enable clipping to see the filled interior; turn off the band to inspect fill alone.
- Clip/slice planes use **index-space** axes and coordinates. Surface clipping
  keeps the region at or below the plane; it does not cap the cut with a new surface.
  The slice auto-view assumes the unrotated transform used by the MeshToSDF driver.
- During dragging only image resolution drops (to 480 pixels on the long edge).
  The input grid stays at full resolution. On release, the selected preview size
  and sample count are restored. Stale frames are discarded.
- Export uses the same camera, projection and aspect ratio as the preview.
  Use 3840×2160 or 7680×4320, 16–64 samples/pixel and 0.25 or 0.125 voxel steps.
  Figure export supports up to 16384 pixels per side and 100 MP total.
- **Export PNG** writes RGBA PNG with an sRGB tag, 300 dpi metadata, and camera,
  settings and source-grid metadata embedded as the `MeshSDF` PNG text field.
  Transparent backgrounds are supported. Supersampling averages in linear light;
  exported alpha is straight, not premultiplied. UI and legends are not exported.
- **Save/Load camera** stores/restores settings and image dimensions as JSON.
  Keep this JSON, the `.nvdb`, the source revision and the mesh-conversion
  parameters alongside a paper figure. An image alone cannot establish SDF accuracy.

An identical headless render needs no browser or X server:

```bash
python3 viewer.py /tmp/hairball.nvdb --settings sdf-camera.json \
  --render output/figure.png --width 3840 --height 2160 --samples 16
```

CLI width/height/samples control export dimensions; the JSON supplies camera and
render settings. Output is written atomically, so a failed render does not replace
an existing figure. For SSH, forward port 8765 and keep the server on loopback:
`ssh -L 8765:127.0.0.1:8765 HOST`.

## Data fidelity and limits

`field.cuh` samples active `sdf` values and resolves missing values with the
`leaf_invert`, `lower_invert`, `upper_invert`, and optional `root_interior` channels.
Both root-origin lists (int32 triplets) and older dense uint8 masks with
`root_extent` are supported; see [the format contract](ARCHITECTURE.md#file-and-field-interpretation).
A regular ChannelAccessor alone returns the positive background for inactive
interior locations and would introduce false surfaces. Required channels are
validated; incompatible files fail explicitly. Active values are never modified,
re-signed or smoothed. Conventional float level sets use their native tile values.
UDF-only MeshToGrid files, `.ccvis`, `.vdb`, quantized grids and ValueIndex grids
are not accepted by this version.

`render.cuh` uses NanoVDB HDDA to skip absent tree regions. In leaf intervals it
samples at a bounded step, refines sign crossings by bisection and uses a halo
for trilinear support at leaf boundaries. This follows the sparse ray traversal
approach of `ex_raytrace_iso_surface`; it does not directly call the stock
`zeroCrossing`/`isoCrossing` helpers, whose default channel access does not decode
this branch's interior masks. Steps are in voxel units, not SDF-based sphere
tracing distances, so a sign-debug field is not assumed to be a perfect distance
bound. Sub-step tangencies and undersampled thin features can still be missed;
check step/sample convergence for the chosen figure. This viewer does not restore
features already lost during voxelization.

Both image sampling and model voxel resolution affect quality independently.
A 4K image of a coarse SDF still shows its discretization. The converter's current
barrier signing can produce a rough zero surface; this viewer preserves that
result instead of replacing it with a render of the original mesh.

The **entire grid and its sidecars must fit in GPU memory**. PNG rendering uses
64-row strips and never allocates a full 4K/8K device framebuffer, but this is
not out-of-core grid streaming. The loader reports an insufficient-memory error.
It briefly holds the grid in CPU memory during upload, then releases that copy.
The workstation has 12 GB VRAM. Fig. 9's 9.88 billion voxels require about
39.5 GB for the float distance channel alone, before topology/masks; reproducing
that exact voxel count needs a larger GPU or a separate out-of-core design.

Uniform scale with translation/rotation is supported; anisotropic scale and shear
are rejected. The current MeshToSDF driver uses uniform scale. The volume shell
and iso offset must stay strictly inside the truncated SDF band; otherwise the
viewer rejects the settings instead of rendering background tiles as fog.

## Can nanovdb_viewer do this?

This checkout has no `nanovdb_viewer` source or build target. Its NanoVDB command
folder contains convert, print and validate; `openvdb_cmd/vdb_view` is a separate
OpenVDB tool. The upstream [viewer discussion](https://github.com/AcademySoftwareFoundation/openvdb/discussions/1636)
records the old viewer's removal and compatibility problems.

In principle, a ported NanoVDB ray-tracing viewer can render high-resolution level
sets. However, an old viewer cannot be assumed to understand this branch's current
NanoVDB layout or custom `sdf`/interior-mask channels. It needs an updated loader
and the same signed accessor used here, or a conversion to a conventional signed
float level set that preserves **all** inactive interior tile values. Renaming the
grid or treating sidecar indices as distances is insufficient. The supplied
`ex_raytrace_iso_surface`, `ex_raytrace_level_set` and `ex_raytrace_fog_volume`
examples provide rendering primitives, not this interactive inspection/export UI.

The local paper's Fig. 9 (page 13) describes an index-grid **UDF** rendering with
HDDA; this tool implements a related visualization of the current **SDF** output.
It does not claim to reproduce the lost renderer's transfer function exactly.

## Verification

```bash
cmake -S . -B build -DBUILD_VIEWER_TESTS=ON
cmake --build build --target sdf_renderer sdf_test_grids -j2
python3 test_viewer.py
```

Tests check analytic sphere silhouettes, byte-identical float/index-mask images
in all seven modes, all four sign-mask levels including negative coordinates, both root formats,
active voxel cubes and band-only slices, native-size interior fill, per-level
visibility, fill extending beyond active bounds,
tiled/full-frame equivalence, rays starting inside the object and parallel to
box planes, clipping, PNG CRC/metadata, invalid inputs and atomic output failure.
The fixtures are independent of MeshToSDF so renderer correctness is not inferred
from the appearance of a potentially incorrect sign field.

Manual/browser integration testing on this workstation also exercised Firefox
mode switching, zoom, export and settings serialization. Measured after CUDA JIT,
including PNG encoding, on an RTX PRO 3000 Blackwell Laptop GPU (12 GB):

| Dataset | Active voxels | Grid bytes | Render | Time |
|---|---:|---:|---|---:|
| Bunny, dx 0.008 | 529,727 | 5,038,464 | Surface, 640×480, 1 spp | 27 ms |
| Hairball, dx 0.01, band 3 | 118,262,653 | 569,671,968 | Surface, 640×480, 1 spp | 62 ms |
| Same hairball | 118,262,653 | 569,671,968 | Volume, 640×480, 1 spp | 165 ms |
| Same hairball | 118,262,653 | 569,671,968 | Volume, 1280×960, 4 spp | 1.60 s |
| Same hairball, 0.25 step / 0.6 shell / 1.4 density | 118,262,653 | 569,671,968 | Volume, 3840×2160, 16 spp | 47.13 s |

Timings are observations, not guarantees; volume density, camera, step size,
GPU clocks and scene depth affect traversal costs substantially.

On the development workstation, the tested local demo is in `output/` (ignored
by Git and not included in a clone): `hairball.nvdb`,
`hairball-4k.png`, and `hairball-camera.json`. Start it with:

```bash
python3 viewer.py output/hairball.nvdb --settings output/hairball-camera.json --open
```

A fresh clone can start without an external mesh:

```bash
cmake -S . -B build -DBUILD_VIEWER_TESTS=ON
cmake --build build --target sdf_renderer sdf_test_grids -j2
build/sdf_test_grids output/fixtures
python3 viewer.py output/fixtures/sphere-index.nvdb --open
```

The standalone renderer, fixture generator and optional mesh converter were also
built against the clean committed base `a1d407f2a`, not only the development
working tree. The converter uses the existing producer code and its CCCL dependency;
the viewer's root-format decoder supports its dense root mask as well as the
newer coordinate-list output.

## Visualizing full-space interior fill

Select **Full-space signed cells**, choose a clipping axis and move the plane
through the object. This renders negative inactive cells as stored, rather than
expanding all coarse tiles to unit voxels. Toggle **Active narrow band** off to
isolate fill; toggle the four levels separately to inspect the representation.
The displayed counts exclude active voxels and child pointers, so leaf invert
bits that also mark active negative voxels are not counted twice.

The existing [Polyscope fill implementation](../../scripts/mesh_to_sdf_viewer.py)
uses the same sizes and half-voxel corner convention. The GPU viewer retains
that convention while tracing the hierarchy directly, without allocating one
mesh or cube instance per inactive voxel. World cube side length is the listed
size times `voxelSize`.

For the tested bunny (`voxelSize=0.004`, band=3), stored inactive fill consists
of 1,567,773 leaf voxels and 17,793 lower tiles (8³ each); no upper/root fill is
present. Zero in a level's count means that dataset has no stored negative fill
at that level. All four levels, including 128³ and 4096³, are independently tested
with coordinate-list and dense root-mask fixtures. The saved hairball dataset
has zero inactive fill boxes according to its masks; the viewer does not invent
interior where the input masks contain none.

Local demo (outputs remain ignored by Git):

```bash
python3 viewer.py output/bunny.nvdb --settings output/bunny-full-space-camera.json --port 8766 --open
python3 viewer.py output/bunny.nvdb --settings output/bunny-full-space-camera.json \
  --render output/bunny-full-space-4k.png --width 3840 --height 2160 --samples 4
```

Old camera JSONs remain supported: missing `fillMask` defaults to 31 (all groups).
`fillMask` bits 0,1,2,3 select inactive sizes 1,8,128,4096; bit 4 selects the active
band. A value of 15 shows fill only, 16 shows band only, and 0 hides all cells in
this mode. Rebuild the CUDA library after updating: Python and the renderer now
check ABI version 2 to prevent accidentally using an older struct layout.

For a real three-level example, `bunny.obj` at `voxelSize=0.001`, band=3 produced
33,978,756 active voxels and inactive fill counts `[27,898,860, 700,271, 165, 0]`
for sizes `[1,8,128,4096]`. The saved development outputs are
`output/bunny-hi-fill.nvdb`, `output/bunny-hi-full-space-camera.json`, and
`output/bunny-hi-full-space-4k.png`. These remain local, ignored files. Start with:

```bash
python3 viewer.py output/bunny-hi-fill.nvdb --settings output/bunny-hi-full-space-camera.json --port 8766 --open
```
