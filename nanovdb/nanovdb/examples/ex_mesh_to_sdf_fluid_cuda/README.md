# NanoVDB GPU APIC fluid example: setup and run guide

이 문서는 **새 Linux/NVIDIA 컴퓨터에서 사람 또는 에이전트가 source checkout 부터
simulation, surface meshing, debug 이미지, 최종 영상까지 실행하기 위한 시작점**이다.
기본 APIC 데모와 춤추는 캐릭터/연속 낙수 장면을 모두 포함한다.

## 1. 먼저 알아둘 사항

- 브랜치는 `mesh-to-sdf-fluid`, 예제 디렉터리는
  `nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda` 다.
- Solver, CUDA kernel, obstacle adapter, mesher, renderer 연결 코드는 이 디렉터리에 있다.
  예제 밖의 변경은 빌드 등록용 `nanovdb/nanovdb/examples/CMakeLists.txt` 다.
- 기존 NanoVDB `MeshToSDF`, topology operator 와 OpenVDB `volumeToMesh` 를 재사용한다.
  `MeshToSDF_NEW`, `PropagateSign_*` 실험 코드는 사용하지 않는다.
- `output/` 의 FBX/mesh sequence, simulation cache, checkpoint, 영상, Python 환경은
  **Git 에 포함되지 않는다**. 새 컴퓨터에서 생성하거나 별도로 복사해야 한다.
- `CMakePresets.json` 은 이전 개발 머신의 로컬 파일이며 이 커밋에 포함되지 않는다.
  아래의 명시적인 configure 명령을 사용한다.
- `scene/pipeline.py`, `scene/overnight_run.py`, benchmark/일부 검증 스크립트는
  **저장소의 `build/release/nanovdb/nanovdb/examples`**에서 실행 파일을 찾는다.
  아래 가이드는 이 경로에 빌드한다. 다른 build 디렉터리의 binary 는 직접 실행해야 한다.
- 현재 solver 는 **단일 GPU**다. GPU 두 개의 VRAM 을 자동으로 합치거나 OOM 시 다른
  GPU 로 넘어가지 않는다. 실행별 GPU 선택은 `CUDA_VISIBLE_DEVICES` 로 한다.
- 기존 라이브러리나 ovrtx 렌더러를 수정하지 않는다. 수치 실패를 허용치 변경으로
  숨기지 말고 로그와 재현 설정을 남겨 원인을 조사한다.

## 2. 환경 확인과 checkout

```bash
git clone --branch mesh-to-sdf-fluid https://github.com/JaeHyunLee94/openvdb.git
cd openvdb
export EX="$PWD/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda"
export BINS="$PWD/build/release/nanovdb/nanovdb/examples"
export PY="$EX/output/render-venv/bin/python"
export CHARACTER="$EX/output/character_grounded"
export CUDA_VISIBLE_DEVICES=0

nvidia-smi
nvcc --version
cmake --version
ninja --version
python3 --version
blender --version
ffmpeg -version
git rev-parse HEAD
```

이미 checkout 했다면 올바른 브랜치인지 확인하고 기존 dirty 파일/캐시를 보존한다.
`EX`, `BINS`, `PY`, `CHARACTER` 는 이 문서의 이후 명령에서 사용한다. 새 shell 에서는
저장소 root 로 이동해 다시 설정한다. `blender` 가 PATH 에 없으면 실제 실행 경로로 바꾼다.

필요한 구성 요소:

| 구성 요소 | 용도/확인사항 |
|---|---|
| NVIDIA driver + CUDA toolkit | GPU kernel 실행과 `nvcc`; toolkit 이 target GPU 와 host compiler 를 지원해야 함 |
| C++17 compiler, CMake, Ninja | C++/CUDA 빌드; 저장소 CMake 의 최소 버전 검사 확인 |
| Boost iostreams, TBB, Imath, Blosc, zlib | OpenVDB core 와 CPU meshing |
| Blender 의 FBX importer | Armature/skinning 적용 mesh sequence export |
| Python venv + `scene/requirements-render.txt` | 검증/분석, USD 작성, ovrtx/ovstage 렌더링 |
| FFmpeg | PNG sequence 를 H.264 MP4 로 인코딩 |
| NVML / `nvidia-smi` | 장시간 실행과 benchmark 의 GPU 메모리 관측 |

Linux 빌드/실행 경로를 기준으로 검증했다. Supervisor 는 `fcntl`, `/proc`, Linux NVML 을
사용하므로 Windows 에서 그대로 실행할 수 있다고 가정하지 않는다.

Ubuntu 계열에서 일반적인 개발 패키지 설치 예시는 다음과 같다. 시스템 설치는
해당 컴퓨터의 권한 정책을 따른다. CUDA/driver 는 별도로 준비한다.

```bash
sudo apt-get update
sudo apt-get install build-essential cmake ninja-build git python3-venv \
  libboost-iostreams-dev libtbb-dev libimath-dev libblosc-dev zlib1g-dev ffmpeg
```

**패키지 이름이 같아도 버전이 충분한지 확인해야 한다.** 이 브랜치의
`cmake/config/OpenVDBVersions.cmake` 는 Boost >= 1.82, Imath >= 3.2,
TBB >= 2020.3, Blosc >= 1.17.0 을 요구한다. 배포판 패키지가 오래됐다면 적절한 버전을
별도 prefix 에 설치하고 `-DCMAKE_PREFIX_PATH=/path/to/dependency-prefix` 를 configure 에
추가한다. 버전 검사를 꺼서 해결하지 않는다. 개발 머신의 `~/local` 이나 `ext/imath`
설치가 새 머신에도 있다고 가정하지 않는다.

## 3. CUDA/OpenVDB 빌드

A6000 은 compute capability 8.6 이므로 아래 예시는 `86` 을 사용한다.
다른 GPU 에서는 설치된 nvcc 가 지원하는 해당 architecture 로 바꾼다.
기존 Blackwell laptop 의 측정 binary 는 `90-virtual` PTX 를 사용했으며 A6000 용 설정과 다르다.

```bash
cmake -S . -B build/release -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DOPENVDB_BUILD_CORE=ON \
  -DOPENVDB_BUILD_BINARIES=OFF \
  -DOPENVDB_BUILD_UNITTESTS=OFF \
  -DOPENVDB_BUILD_NANOVDB=ON \
  -DNANOVDB_USE_OPENVDB=ON \
  -DNANOVDB_USE_CUDA=ON \
  -DNANOVDB_BUILD_EXAMPLES=ON \
  -DNANOVDB_BUILD_TOOLS=OFF \
  -DNANOVDB_BUILD_UNITTESTS=OFF

cmake --build build/release --target \
  ex_mesh_to_sdf_fluid_cuda \
  ex_mesh_to_sdf_fluid_scene_cuda \
  ex_mesh_to_sdf_fluid_scene_float_cuda \
  ex_mesh_to_sdf_fluid_surface \
  ex_mesh_to_sdf_fluid_scene_verify \
  ex_mesh_to_sdf_fluid_scale_float_verify \
  ex_mesh_to_sdf_fluid_scale_double_verify -j 3
```

- CPU surface reconstruction 에는 **OpenVDB core 와 `NANOVDB_USE_OPENVDB=ON` 둘 다** 필요하다.
- 빌드 RAM 이 부족하면 `-j 1` 로 줄인다. 오래된 build 의 compiler/architecture 를 바꾸려면
  기존 캐시를 보존한 뒤 별도 fresh build 로 확인한다.
- NanoVDB CMake 는 CCCL 을 GitHub 의 `main` 에서 가져온다. 첫 configure 에는 네트워크가
  필요하며, 재현 보고에 OpenVDB 및 CCCL commit, toolkit/compiler 버전을 기록한다.
- Ubuntu CUDA/GCC 조합에서 AMX intrinsic header 오류가 발생하는 경우에만 기존
  개발 환경에서 사용한 아래 configure 옵션을 검토한다. 일반적인 필수 옵션은 아니다:
  `'-DCMAKE_CUDA_FLAGS=-Xcompiler=-D_AMXTILEINTRIN_H_INCLUDED -Xcompiler=-D_AMXINT8INTRIN_H_INCLUDED -Xcompiler=-D_AMXBF16INTRIN_H_INCLUDED'`.
- 기존 MeshToSDF 의 dense `uint8` root bitmap + `root_extent`, 더 최근의 sparse `int32`
  root-origin 목록을 CPU/GPU adapter 가 구분해서 읽는다. 라이브러리 변경 없이 빌드한다.

## 4. Python 과 렌더러 준비

```bash
python3 -m venv "$EX/output/render-venv"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r "$EX/scene/requirements-render.txt"
"$PY" -c 'import numpy, PIL, matplotlib, scipy, ovrtx, ovstage; from pxr import Usd; print("imports OK")'
"$PY" -m pip freeze > "$EX/output/render-venv-packages.txt"
```

이 requirements 는 기존 측정 환경의 고정 버전이다. wheel 이 없는 Python/platform 이라면
설치 오류를 기록하고 호환되는 Python 환경을 먼저 준비한다. ovrtx 와 ovstage 를 임의로
서로 다른 API 세대로 교체하지 않는다. 기존 개발 머신의 별도 ovrtx 저장소 README 와
예제는 연결 조사에 사용했지만, 이 예제 실행은 **설치된 Python SDK**를 import 한다.
`~/Desktop/Code/NVIDIA/ovrtx` 라는 특정 경로를 새 머신에 만들 필요는 없다.

Import 성공은 RTX 렌더링 성공을 의미하지 않는다. 아래의 **대표 프레임 렌더링**으로
GPU/driver/headless 환경까지 확인한 뒤 전체 영상을 생성한다. `debug_scene.py` 도
`pxr` 를 import 하는 예제 helper 를 사용하므로 USD Python package 가 필요하다.

## 5. 캐릭터 없이 기본 solver 부터 검증

```bash
"$PY" "$EX/validate.py" "$BINS/ex_mesh_to_sdf_fluid_cuda" \
  --output "$EX/output/base_validation_new_machine"
"$BINS/ex_mesh_to_sdf_fluid_scale_float_verify" 32 0 mgpcg
"$BINS/ex_mesh_to_sdf_fluid_scale_double_verify" 32 0 mgpcg
"$PY" "$EX/scalable/run_verification.py" --max-size 32 --precision all
```

기본 검증은 고정 topology → 동적 topology → 정지/이동/변형 cube 순서로 실행한다.
일정/affine velocity APIC transfer, pressure residual/flux divergence,
고정·동적 결과 비교, obstacle SDF 와 접촉을 검사한다. Nonzero exit 면 다음 단계로
진행하지 않는다. 더 큰 pressure 문제는 작은 검증이 통과한 뒤 실행한다.
이 기본 데모에는 FBX 나 캐릭터 cache 가 필요 없다.

## 6. FBX 검사와 grounded 캐릭터 export

입력 파일은 사용자가 별도로 제공한다. 기존 장면은 `Arms Hip Hop Dance.fbx` 를 사용했다.

### Mixamo에서 입력 FBX 다운로드

1. [Mixamo](https://www.mixamo.com/)에 Adobe ID로 로그인한다. 계정/서비스 조건은
   [Adobe Mixamo FAQ](https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html)를 참조한다.
2. 캐릭터를 선택하고 Animations에서 **Arms Hip Hop Dance**를 검색해 적용한다.
   기존 입력의 mesh 이름은 `Beta_Joints`, `Beta_Surface`였다. 원래 다운로드 당시의
   캐릭터 UI 이름과 motion slider 값은 기록하지 않았으므로 같은 animation 이름만으로
   기존 영상과 동일한 geometry/motion을 보장할 수 없다. 아래 검사값과 preview를 비교한다.
3. 전체 animation 구간을 유지하고 Download에서 **FBX Binary**, **With Skin**,
   **30 fps**, **Keyframe Reduction: None**으로 받는다. 이는 재현용 권장 설정이며
   원래 다운로드 대화상자의 모든 선택값을 복원한 기록은 아니다. Speed/Trim 등 motion
   조정값도 변경했다면 별도로 기록한다. With Skin 없이 받으면 mesh가 없어 exporter가 실패한다.
4. 파일을 `~/Downloads/Arms Hip Hop Dance.fbx`에 저장한다. 아래 `FBX` 환경변수로
   다른 경로도 사용할 수 있다. 로그인/캐릭터 선택이 필요한 서비스이므로 직접 FBX URL이나
   자동 다운로드 스크립트는 제공하지 않는다.
5. 아래 `--inspect-only` 명령을 실행해 `inspection.json`을 확인하고, 전체 export 후
   `metadata.json`의 topology 검증 결과와 Blender에서 `source.blend`의 초기·중간·마지막
   pose를 확인한다. Animation 길이는
   simulation duration + animation offset을 충분히 덮어야 한다.

기존 입력의 확인용 fingerprint는 다음과 같다. 새 다운로드의 hash는 FBX exporter의
metadata 등에 따라 달라질 수 있다. Hash가 다르면 byte-identical 입력으로 간주하지 말고
geometry, animation timing과 preview를 비교한다.

| Property | Original input |
|---|---|
| File name | `Arms Hip Hop Dance.fbx` |
| File size | 3,455,696 bytes (3.296 MiB) |
| SHA-256 | `5b233159115778201f1de250a7d9df69d917b9cbd434d4a996610859a3502823` |
| Imported FPS / frame range | 30 fps / 1–660 |
| Evaluated vertices / triangles | 24,746 / 49,112 |
| Mesh objects | `Beta_Joints`, `Beta_Surface` |
| Import environment | Blender 5.2.2 LTS; evaluated world-space mesh |

```bash
sha256sum "$HOME/Downloads/Arms Hip Hop Dance.fbx"
```

FBX 원본은 저장소에 포함하지 않는다. Adobe Community의
[Mixamo 배포 안내](https://community.adobe.com/questions-696/mixamo-faq-licensing-royalties-ownership-eula-and-tos-589400?lang=en)는
원본 character/animation 파일의 공개 재배포를 제한한다고 설명한다. 각 사용자가 직접
다운로드하고 적용되는 이용 조건을 확인한다. Exporter가 만드는 `source.fbx`, `source.blend`,
OBJ sequence도 로컬 `output/`에 유지하며 Git에 추가하지 않는다.

### 입력 검사와 simulation용 mesh sequence 생성

```bash
export FBX="$HOME/Downloads/Arms Hip Hop Dance.fbx"
test -f "$FBX"
blender -b --python-exit-code 1 --python "$EX/scene/export_character.py" -- \
  --input "$FBX" --output "$EX/output/character_inspection" --inspect-only

blender -b --python-exit-code 1 --python "$EX/scene/export_character.py" -- \
  --input "$FBX" --output "$CHARACTER" \
  --height 1.75 --center-x 1.6 --center-z 1.2 --floor-clearance 0.001
```

Exporter 는 Blender evaluated mesh 와 world transform 을 사용한다. 모든 mesh object 를
포함하고 첫 프레임 triangulation 을 고정한다. 매 프레임 vertex 수/polygon connectivity 를
검사하며 topology 가 변하면 실패한다. Blender Z-up 을 simulation Y-up `(x,z,-y)` 으로
변환하고 단위 m 로 저장한다. 원본 FBX/rig 는 별도로 보존한다.

확인할 산출물: `inspection.json`, `metadata.json`, `sequence.txt`,
`frame_000001.obj` 등의 OBJ, `vertices.bin`, `triangles.bin`, `vertices.npy`,
`triangles.npy`, `source.fbx`, `source.blend` 와 pose 미리보기.
첫/중간/마지막 pose, FPS·프레임 범위·bounds·topology 일관성·실제 vertex 변형을 확인한다.
원본 dance 는 30 fps, source frame 1–660 이었다. 다른 입력의 결과를 이 숫자에 맞추지 않는다.
`--inspect-only` 는 검사만 수행하며 simulation 용 전체 sequence 를 생성하지 않는다.

```bash
"$BINS/ex_mesh_to_sdf_fluid_scene_verify" "$CHARACTER" 0.01
```

`pipeline.py --character` 는 export **디렉터리**를 받는다. FBX 나 OBJ 한 파일을 직접
전달하지 않는다. 전체 bake 가 simulation duration + animation offset 을 충분히 덮는지
확인한다. FBX 가 없다면 기본 cube 데모는 진행할 수 있지만 dance 재현은 할 수 없다.

## 7. 최신 장면 설정과 저해상도 smoke test

커밋된 `scene/clear_shower_fine.json` 은 **h=0.02 m 인 이전 fine 장면**이다.
이후 승인된 384 × 384 × 288, 10 초 장면의 config 는 원래 ignored cache 에만 있었다.
아래 명령으로 새 환경의 경로를 사용해 그 설정과 짧은 smoke 설정을 생성한다.
장면의 emitter/pool/animation/whitewater 값은 유지한다.

```bash
"$PY" - <<'PY'
import json, os
from pathlib import Path
ex = Path(os.environ['EX'])
cfg = json.loads((ex / 'scene/clear_shower_fine.json').read_text())
cfg.update(character=os.environ['CHARACTER'], h=3.2/384,
           obstacle_h=(3.2/384)/2, duration=10, precision='float', pressure='mgpcg',
           mesh_closing_radius=0.25, mesh_pca_threads=4, validation_workers=4)
folder = ex / 'output/configs'
folder.mkdir(parents=True, exist_ok=True)
(folder / 'production_384.json').write_text(json.dumps(cfg, indent=2) + '\n')
smoke = dict(cfg, h=0.04, obstacle_h=0.02, duration=0.25,
             mesh_h=0.02, width=640, height=480, samples=16, validation_workers=1)
(folder / 'smoke.json').write_text(json.dumps(smoke, indent=2) + '\n')
PY
export CONFIG="$EX/output/configs/smoke.json"
export CACHE="$EX/output/smoke_new_machine"
"$PY" "$EX/scene/pipeline.py" "$CONFIG" --character "$CHARACTER" \
  --precision float --pressure mgpcg --output "$CACHE" --stages verify,simulate
"$PY" "$EX/scene/pipeline.py" "$CONFIG" --character "$CHARACTER" \
  --output "$CACHE" --stages mesh,validate
"$PY" "$EX/scene/debug_scene.py" "$CACHE" --character "$CHARACTER" --representative
```

짧은 smoke test 는 연결과 초기 pool/발 접촉을 확인하는 용도다. 낙하수가 바닥에
도달한 뒤의 splash 나 10 초 장면의 안정성을 검증한 것으로 보지 않는다.

설정의 의미:

| 항목 | 최신 384 설정 / 의미 |
|---|---|
| `h`, `obstacle_h` | 0.008333… / 0.004166… m; fluid/obstacle voxel 크기 |
| `duration`, `fps` | 10 초 / 출력 30 fps; solver substep 수와 다름 |
| `ppc`, `dt` | 8 / 최대 0.004 초; CFL 에 따라 실제 dt 는 더 작아짐 |
| `emitter_radius`, `emitter_speed` | 0.21 m / 아래 방향 0.36 m/s; 지름 0.42 m |
| `emitter_x`, `emitter_z` | 1.67 / 1.1551 m |
| `initial_depth`, `drain_enabled` | 초기 pool 0.064 m / false(닫힌 basin) |
| `whitewater_rate` | 360000; secondary 생성 모델의 계수 |
| `foam_radius_scale`, `foam_life_scale` | 1.5 / 1.8; simulation secondary 설정 |
| `mesh_h` | 0.00625 m; simulation 과 독립적인 meshing voxel 크기 |
| `mesh_isovalue`, `mesh_support`, `mesh_smoothing` | 0.3 / 2.4 / 0.12 |
| `mesh_closing_radius` | 0.25; mesher 의 표면 filter 설정 |
| `mesh_pca_threads`, `validation_workers` | 4 / 4; CPU 병렬도 |
| `width`, `height`, `samples` | 1600 × 1200 / 96; 최종 render |

Domain 은 X/Y/Z = 3.2/3.2/2.4 m 다. 해상도를 올릴 때 같은 월드 크기를 유지하고
`h=3.2/N`, `obstacle_h=h/2` 를 별도 config 에 설정한다. `mesh_h` 는 독립적으로 선택한다.
`ppc` 변경은 질량과 메모리에 영향을 주므로 기록한다. 입자 수/active cells/VRAM 은
시간과 sparse occupancy 에 따라 변한다. 48 GB 에서 특정 해상도가 반드시 실행된다고
보장하지 않는다.

## 8. 대표 프레임 렌더링과 전체 실행

먼저 smoke cache 의 한 프레임을 렌더링한다. Mesh stage 가 선행되어야 한다.

```bash
"$PY" "$EX/scene/render_scene.py" "$CACHE" --character "$CHARACTER" \
  --only-frame 0 --width 640 --height 480 --samples 16 --tag smoke_frame
```

이미지와 `render_smoke_frame/timings.json` 을 확인한다. 단일프레임 시험은 영상을
생성하지 않는다. 검은 이미지, 미수렴, SDK/driver 오류를 여기서 해결한다.

전체 production 은 smoke 검증이 통과한 뒤 **별도 output**에서 실행한다.

```bash
export CONFIG="$EX/output/configs/production_384.json"
export CACHE="$EX/output/scene_384_new_machine"
"$PY" "$EX/scene/pipeline.py" "$CONFIG" --character "$CHARACTER" \
  --precision float --pressure mgpcg --output "$CACHE" --stages simulate,mesh,validate
"$PY" "$EX/scene/debug_scene.py" "$CACHE" --character "$CHARACTER" --representative
"$PY" "$EX/scene/render_scene.py" "$CACHE" --character "$CHARACTER" \
  --width 1600 --height 1200 --samples 96 \
  --foam-render-scale 0.7 --spray-render-scale 0.8 --tag smaller_whitewater
```

마지막 명령은 승인된 작은 foam/spray 외관을 재현한다. **렌더링에만 적용하는 반경 scale**로
simulation 질량이나 secondary cache 는 바꾸지 않는다. `pipeline.py` 의 render stage 는
기본 scale=1 을 사용하며 이외관 option 을 전달하지 않는다. `--tag` 로 원래 render 를 보존한다.
생성영상은 `dance_water_smaller_whitewater.mp4`, 이미지는 `render_smaller_whitewater/` 에 있다.

캐시를 재사용해서 후처리만 다시 실행하려면:

```bash
"$PY" "$EX/scene/pipeline.py" "$CONFIG" --character "$CHARACTER" \
  --output "$CACHE" --stages mesh,validate
"$PY" "$EX/scene/render_scene.py" "$CACHE" --character "$CHARACTER" \
  --only-frame 150 --camera-view feet --water-style clay --tag feet_clay
```

마지막 명령은 frame150 이 있는 cache 에서만 사용한다. `--author-only` 는 USD 작성만,
`--surface-dir` 는 대체 surface 디렉터리 지정이다. Meshing 에는 시간 filter 이력이 있으므로
임의의 중간 frame 을 cold 상태로 추가하지 않는다. 전체재생성 또는 다음절의 이력재생을 쓴다.

## 9. 장시간 실행·정지·재개

일반적인 simulation 재개는 같은 config, precision, character, cache 를 사용한다.

```bash
"$PY" "$EX/scene/pipeline.py" "$CONFIG" --character "$CHARACTER" \
  --output "$CACHE" --stages simulate --resume
```

Checkpoint 는 각출력 frame 마다 임시파일에서 atomic rename 으로 저장한다. 위치·속도·
APIC affine matrix·ID·secondary 상태를 포함하며 CSV 는 restart 입력이 아니다.
다른 precision/build/layout 으로 binary checkpoint 를 옮기는 호환성은 보장하지 않는다.
새 simulation 은 새 output 을 사용하고 기존 cache 를 덮어쓰지 않는다.

Float 장시간관리와 CPU streaming meshing 에는 전용 supervisor 를 사용할 수 있다.

```bash
"$PY" "$EX/scene/overnight_run.py" "$CONFIG" "$CACHE" \
  --hours 12 --stream-mesh
# 완료된surface 이력도 검사하면서 이어서 실행:
"$PY" "$EX/scene/overnight_run.py" "$CONFIG" "$CACHE" \
  --resume --stream-mesh --resume-mesh --hours 12
```

첫 명령은 **새 cache**용이다. `CONFIG` 의 `character` 는 절대경로, `precision` 은 float 로
설정한다. 위에서 생성한 config 는 이조건을 만족한다. `--hours` 는 wall-clock 실행시간
상한으로 simulation duration 과 다르다. `--postprocess` 는 완료후 후처리도 실행한다.
GPU driver 가 reset 되면 checkpoint 보존과 GPU 복구 확인을 별도로 수행한다.

```bash
touch "$CACHE/STOP"
# status.json에서 정지와checkpoint를 확인한 뒤:
rm "$CACHE/STOP"
```

STOP 은 다음 checkpoint 부근에서 정지하는 요청이며 즉시 kill 이 아니다. Resume 전에 STOP 을
제거한다. 같은 cache 에 복수 supervisor 를 실행하지 않는다. `surface_resume.py` 는
supervisor 가 사용하는 **helper module**로 직접실행하는 CLI 가 아니다. 이전 32frame 의
이력을 재생하고 겹치는 mesh 를 검증한다. **Supervisor 는 수치실패를 자동 retry 하지 않는다.**
Nonzero exit 이면 로그를 확인하고 원인을 해결한 뒤 동일설정으로 안전하게 resume 한다.
허용치완화나 무제한재시작을 자동으로 수행하지 않는다.

## 10. 출력·판정·benchmark

| 위치 | 내용 |
|---|---|
| `pipeline_config.json`, `settings.json` | 실행설정 / solver 가 기록한 실제설정 |
| `metrics.csv` | substep 별시간, pressure/divergence, 접촉, CFL, 영역/질량등 |
| `frames.csv` | 출력 frame 과 simulation time 의 manifest |
| `frame_XXXXXX.csv` | APIC particles |
| `frame_XXXXXX_whitewater.csv` | 별도관리하는 foam/spray |
| `frame_XXXXXX_blocks.csv` | 할당된 sparse blocks 의 debug 정보 |
| `checkpoint.bin` | 마지막완전한 simulation restart |
| `surface/` | water OBJ/meshbin, 렌더링용 whitewater, meshing timing/report |
| `debug/` | 입자·obstacle·blocks 대표이미지 |
| `render[_tag]/` | 최종 PNG 와 `timings.json` |
| `dance_water[_tag].mp4` | 최종영상 |
| `pipeline_times.json` | stage 별 wall time |
| `status.json`, supervisor 로그 | supervisor 진행상태/로그(사용시) |

통과여부는 exit code 와검증 report 로 판단한다. 이미지가 자연스럽다는 이유만으로 통과시키지
않는다. 움직이는벽의 `open*u + (1-open)*wallVelocity` 에 기반한 divergence, pressure
residual, primary/secondary penetration, missing stencil, 유입·배출을 포함한 mass ledger 를
확인한다. Meshing volume 과 particle volume 을 구분하고 render convergence 도 확인한다.
고해상도 frame CSV/mesh/전체 USD 는 크므로 disk 공간과 CPU RAM 을 GPU VRAM 과 별도로 관측한다.

기존 **float checkpoint/cache**에서 짧은 독립 benchmark 를 실행하려면:

```bash
"$PY" "$EX/scene/benchmark_pipeline.py" \
  --cache "$CACHE" --checkpoint "$CACHE/checkpoint.bin" \
  --output "$EX/output/benchmark_new_machine" --frames 3 --python "$PY"
"$PY" "$EX/scene/report_pipeline_benchmark.py" "$EX/output/benchmark_new_machine"
```

Benchmark output 은 새 디렉터리여야 한다. Checkpoint 뒤의 3frame 을 생성하므로 필요한
animation 시간과원 config 의 character 경로를 확인한다. Source cache 는 읽기전용이다.
Simulation, CPU meshing, USD/render/PNG/encode 를 구분하고메모리 sampling, 영상 decode,
수치검증을 기록한다. Meshing 은 cold covariance 이력으로 시작하므로 production 의 warm
측정과 동일조건은 아니다. 자세한설명과기존측정은[PIPELINE_BENCHMARK.md](PIPELINE_BENCHMARK.md).

## 11. 스크립트 전체 색인

아래 path 는 이 예제 디렉터리 기준이다. CLI 는 `--help` 와 source 를 확인한다.
**Helper 와과거 experiment runner 에는 `--help` 가 없는파일도 있으므로 일괄실행하지 않는다.**

### 장면 실행의 주요 스크립트

| 파일 | 역할·사용방법 |
|---|---|
| `scene/export_character.py` | Blender 전용 FBX export; 6 절 |
| `scene/pipeline.py` | config 와 `--stages` 로 단계별실행; 7–9 절 |
| `scene/overnight_run.py` | float 장시간관리와 stream meshing; 9 절 |
| `scene/surface_resume.py` | temporal mesh continuation helper; supervisor 에서사용 |
| `scene/render_scene.py` | cache→USD/PNG/MP4; 8 절 |
| `scene/debug_scene.py` | 입자/obstacle/block 이미지; `--representative` 로 대표 3frame |
| `scene/validate_scene.py` | cache 수치/geometry 검증; pipeline 의 validate stage |
| `scene/verify_pool.py` | 닫힌 basin 의질량·축적·경계검증; validate stage 에서도호출 |
| `scene/benchmark_pipeline.py` | checkpoint continuation 으로전체 pipeline 측정; 10 절 |
| `scene/report_pipeline_benchmark.py` | benchmark folder→summary/CSV/그래프; 10 절 |

### 개별 진단·비교

| 파일 | 역할 |
|---|---|
| `scene/inspect_pressure.py` | 저장된 pressure 진단조사 |
| `scene/render_surface_diagnostic.py` | 표면/입자 비교이미지 |
| `scene/verify_foot_motion.py` | grounded/원래 bake 의발주변움직임비교 |
| `scene/verify_mesh_edges.py` | water mesh edge/connectivity 검사 |
| `scene/verify_pool_tiles.py` | pool 의국소 tile 분포검사 |
| `scene/verify_render_visibility.py` | foam/spray 렌더링가시성검사 |
| `scene/verify_restart.py` | scene restart 재현검증 |
| `scene/verify_secondary_roundoff.py` | secondary 경계반올림오차검증 |
| `scene/verify_surface_parallel.py` | CPU surface 병렬계산비교 |
| `scene/verify_white_foam.py` | white foam 가시성검사 |
| `scalable/run_verification.py` | float/double pressure 크기·형상·방법비교 |
| `scalable/compare_distribution.py` | reference/candidate cache 분포비교 |
| `scalable/report_scalability.py` | scalability regression 집계 |
| `scalable/verify_resident_restart.py` | GPU resident 입자관리/restart 비교 |

### 기본 3 단계데모

| 파일 | 역할 |
|---|---|
| `validate.py` | 고정/동적/cube 기본검증을순서대로실행 |
| `validate_long.py` | duration/voxel size 를지정하는장시간기본검증 |
| `render.py` | 기본데모 particle/block/SDF 이미지와 GIF |
| `render_all.py` | 기본데모 각 mode 의대표이미지 |
| `animate.py` | 기본데모 3D frame sequence 렌더링 |
| `assemble_animation.py` | 기본데모영상조립 |
| `report_long.py` | 기본장시간실험 report |
| `compare_resolution.py` | 기본데모해상도비교 |
| `scene_config.py` | 기본데모공통설정 helper |

### 과거 실험 runner/report: source 확인후사용

과거 output 이름, baseline binary, 여러 config 를전제로하는파일이있다.
새 환경의표준 실행 경로는위 pipeline/supervisor 다. JSON/report 는개발이력으로보존했다.

| 파일 | 역할 |
|---|---|
| `scene/finish_clear_shower.py` | 과거 clear shower 후처리완료 driver |
| `scene/plot_clear_shower.py` | clear shower 측정그래프 |
| `scene/preview_clear_shower.py` | clear shower 미리보기 |
| `scene/report_grounded_shower.py` | grounded shower 결과집계 |
| `scene/report_pool.py` | accumulating pool 결과집계 |
| `scene/report_scene.py` | 초기 dance scene 결과집계 |
| `scene/report_water.py` | water 개선실험결과집계 |
| `scene/report_wet_pool.py` | 초기 pool 실험결과집계 |
| `scalable/final_checks.py` | 과거 scalability 최종 check driver |
| `scalable/finish_verification.py` | 과거 verification 계속실행 driver |
| `scalable/validate_final.py` | 과거 final config 군의검증 driver |

C++ 구현/검증 source 대응은[IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md),
[SCENE_IMPLEMENTATION.md](SCENE_IMPLEMENTATION.md), [SCALABILITY.md](SCALABILITY.md)에 있다.
`scene/requirements-render.txt` 는 Python 의존성, `.gitignore` 는 generated output 제외설정이다.

## 12. 문제 해결

- Binary 가없는경우: branch, target, `build/release`, `BINS` 를확인한다.
- CMake dependency/version 오류: prefix/version 을확인한다. 새 환경에는 local preset 이없다.
- CUDA architecture/host compiler 오류: driver/toolkit/compiler 조합을확인한다.
- FBX import/topology 오류: Blender importer, evaluated modifier, 모든 mesh 연결을확인한다.
- RTX 초기화/검은이미지: SDK import 만으로판단하지말고단일 frame render 와로그를확인한다.
- OOM: checkpoint 를보존하고 VRAM/CPU RAM/동시 meshing/render 사용량을구분해서측정한다.
  일반 pipeline 은단계별실행, `--stream-mesh` 는 simulation 과 CPU meshing 을병행한다.
- 수치실패: 첫실패 substep 과 config 를저장한다. Scene/허용치/library 를임의로바꾸지않는다.
- Resume mismatch: precision, binary layout, character, 물리설정이동일한지확인한다.
- Render 만변경: cache 를사용해 `--tag` 를붙여 render 한다. Simulation 재실행은필요없다.

## 13. 구현 상세·과거 결과 문서

- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md): MAC/APIC, operator 재사용, SDF 표현.
- [SCALABILITY.md](SCALABILITY.md): precision, GPU resident 관리, MGPCG, 측정과한계.
- [SCENE_IMPLEMENTATION.md](SCENE_IMPLEMENTATION.md): character, whitewater, surface, render.
- [SURFACE_FILTER_RESULTS.md](SURFACE_FILTER_RESULTS.md): surface filter 와작은 whitewater render.
- [PIPELINE_BENCHMARK.md](PIPELINE_BENCHMARK.md): 전체 pipeline 측정과병목.
- [SCENE_RESULTS.md](SCENE_RESULTS.md), [STREAM_REFINEMENT_RESULTS.md](STREAM_REFINEMENT_RESULTS.md):
  이전 scene/run 의재현기록. 과거 `--preset release`, config, output path 는새 환경에서
  위의명시적인 build/config 절차로바꿔사용한다.

아래는이전기본데모의상세설명과실험명령을보존한내용이다.
최신 384 scene 의 setup/run 에는 **이 문서의 1–12 절**을사용한다.

---

## Appendix: original demo guide and historical scene notes



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
