# MeshToSDF 시각화 도구 사용 설명서

이 도구는 **MeshToSDF가 계산한 sparse SDF 값과 sign**을 GPU에서 직접 읽어
렌더링한다. 브라우저는 카메라와 렌더 설정을 조절하는 UI이고, 실제 계산은
로컬 CUDA backend가 한다. 원본 OBJ를 대신 렌더링하거나 voxel마다 큐브를
만들지 않으므로 Polyscope에서 voxel geometry 수가 병목이었던 데이터도
GPU 메모리에 들어가는 한 열 수 있다.

[빌드 및 성능 요약](README.md) · [코드 구조와 알고리즘](ARCHITECTURE.md)

## 1. 무엇을 보는가

### SDF와 narrow band

SDF(signed distance field)는 위치에서 표면까지의 거리와 내부/외부 부호를
함께 나타낸다. 여기서는 음수가 내부, 양수가 외부다. `sdf = 0`인 위치가
표면이다. MeshToSDF는 표면 주변 narrow band의 값만 명시적으로 저장하고,
멀리 떨어진 내부/외부는 잘린 거리값 `-background` / `+background`로 표현한다.
따라서 깊은 내부에서 보이는 거리의 크기는 실제 표면까지의 정확한 거리가 아니다.

이 브랜치의 `ValueOnIndex` grid에서 tree의 숫자는 거리가 아니라 **배열 인덱스**다.
실제 거리는 `sdf` blind-data 채널에 있고, 비활성 영역의 내부 여부는
`leaf_invert`, `lower_invert`, `upper_invert`, `root_interior`에 있다.
뷰어는 이 채널들을 모두 반영한다. `activeVoxelCount`는 narrow band의
active voxel 개수이며 내부의 모든 공간 셀을 더한 수는 아니다.

### 일곱 가지 보기 모드

| 모드 | 표시하는 양 | 용도와 해석 |
|---|---|---|
| SDF surface | trilinear SDF의 iso crossing | 표면 형상, 구멍, 끊김, sign 이상이 만드는 가짜 표면 확인 |
| Transmittance volume | iso 주변 shell의 흡수·투과도 누적 | hairball처럼 가는 구조가 겹치는 장면의 논문용 시각화 |
| Surface normals | SDF gradient의 world-space 방향 | 표면 방향의 불연속, 거친 gradient 확인 |
| Sign slice · full field | 비활성 영역을 포함한 단면의 nearest voxel sign | 깊은 내부/외부, cavity 확인 |
| Signed active voxels | 실제 active voxel의 unit cube | 전체 narrow band의 ± voxel을 입체적으로 확인 |
| Sign slice · active band | 단면의 active voxel만 표시 | band 폭과 양쪽 부호를 직접 확인 |
| Full-space signed cells | active band + invert mask의 비활성 내부 fill | 1³·8³·128³·4096³ 계층 크기를 보존해 내부 공간 확인 |

**Sign 모드의 주황색은 음수(내부), 파란색은 양수(외부)**다. 표면에 가까운
작은 `abs(sdf)` 값은 full-field 단면에서만 밝게 섞인다. 밝은 띠는 별도 sign 분류가 아니다.
영역 밖 흰색은 선택한 배경이다. 부호는 IEEE sign bit로 판정하므로 `-0.0`도
내부 색을 갖는다. 단면 값 자체에는 trilinear interpolation을 적용하지 않는다.
다만 samples/pixel을 높이면 한 이미지 픽셀 안의 여러 ray가 평균되어 색 경계가
부드러워질 수 있다. voxel 경계를 엄밀히 보려면 줌인하고 `Settled samples = 1`을 쓴다.

표면 모드가 매끄러워 보여도 sign 정확성이 증명되는 것은 아니다. 반대로
거친 표면이 보인다면 renderer 문제뿐 아니라 voxelization 해상도, 원래 SDF의
barrier signing, 잘못된 내부 mask 등을 살펴야 한다. 뷰어는 sign을 수정하지 않는다.
원본 mesh overlay, OpenVDB mismatch 비교, CC label, voxel 클릭 수치 조회는
현재 UI에 없다. Python API의 `Renderer.probe()`로 정수 좌표의 값을 조회할 수 있다.

## 2. 설치와 첫 실행

Linux에서 CMake 3.24 이상, CUDA toolkit/driver, 호환 C++17 host compiler,
zlib 개발 패키지, Python 3.9 이상이 필요하다. Python 추가 패키지와 npm 설치는
필요 없다. 아래 명령은 저장소 루트에서 시작한다.

```bash
cd nanovdb/nanovdb/examples/ex_mesh_to_sdf_cuda/standalone/sdf_viewer
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12
cmake --build build --target sdf_renderer -j2
python3 viewer.py /path/to/result.nvdb --open
```

`g++-12`는 개발 머신의 CUDA 12.0에 맞춘 선택이다. 다른 머신은 해당 toolkit이
지원하는 host compiler를 지정한다. 기본 CUDA target은 `90-virtual`이다.
더 오래된 GPU에서는 `-DCMAKE_CUDA_ARCHITECTURES=86`처럼 GPU에 맞게 바꾼다.

브라우저 주소는 `http://127.0.0.1:8765`다. 첫 실행의 PTX JIT가 몇 초 걸릴 수 있다.
`Ctrl+C`로 서버를 종료한다. 다른 포트는 `--port 8766`으로 지정한다.
GPU가 없는 환경의 CPU rendering fallback은 없다.

### Clone 직후 mesh 없이 실행하기

큰 OBJ, `.nvdb`, PNG, 개인 카메라 파일은 Git에 포함하지 않는다. 우선 analytic
sphere fixture를 생성하면 외부 mesh 없이 설치와 sign rendering을 확인할 수 있다.

```bash
cmake -S . -B build -DBUILD_VIEWER_TESTS=ON
cmake --build build --target sdf_renderer sdf_test_grids -j2
build/sdf_test_grids output/fixtures
python3 viewer.py output/fixtures/sphere-index.nvdb --open
python3 test_viewer.py
```

fixture의 sphere는 MeshToSDF 정확도를 평가하는 데이터가 아니라 renderer 자체의
기준 데이터다. 테스트는 float grid와 index+mask grid의 동일한 영상도 비교한다.

### 실제 OBJ에서 SDF 생성하기

호환되는 MeshToSDF example 실행 파일의 인자는 다음과 같다.

```text
mesh.obj voxelSize bandWidth isoValue output.nvdb
```

`voxelSize`, converter의 `isoValue`는 world 단위이고 `bandWidth`는 voxel 단위다.
예를 들어 다음은 실제 작업에서 사용한 bunny/hairball 설정이다. 실행 파일과
mesh 경로는 자신의 머신에 맞게 지정한다.

```bash
/path/to/ex_mesh_to_sdf_cuda /path/to/bunny.obj 0.004 3 0 output/bunny.nvdb
/path/to/ex_mesh_to_sdf_cuda /path/to/hairball.obj 0.01 3 0 output/hairball.nvdb
python3 viewer.py output/bunny.nvdb --port 8766 --open
```

renderer와 converter는 별개다. 선택적 `sdf_from_mesh` target은 저장소의 기존
converter 소스를 그대로 컴파일한다. converter의 개발 중 코드 상태와 CCCL
의존성에 영향을 받으며, renderer를 사용하는 데 이 target은 필요하지 않다.
구체적인 호환성 상태는 [README](README.md)의 converter 절을 참고한다.

## 3. Bunny active voxel과 sign 확인 순서

**active voxel 큐브 자체를 보려면 `Signed active voxels`를 선택한다.** 표면의
zero crossing을 찾는 모드가 아니라 active mask가 켜진 모든 셀을 대상으로
정수 index 중심의 한 변 1 voxel 큐브를 ray tracing한다. 색은 저장된 sign이다.
큐브는 불투명하므로 외부에서 보면 양수 band가 음수 band를 가린다.
`Clip / slice axis = Z`, `Plane = 중앙`으로 잘라 보면 band의 양쪽이 드러난다.
단면에서 band만 보고 싶다면 `Sign slice · active band`를 선택한다. 이 모드는
비활성 내부/외부를 숨기고 양수·음수 active voxel만 표시한다.

실제 개발용 bunny(dx=0.004, band=3)에서는 active voxel 2,121,564개 중
양수 782,270개, 음수 1,339,294개였고 거리 범위는 [-3,+3] voxel이었다.
Z=0 단면에서도 양수 3,494개, 음수 6,591개의 active voxel이 있었으며,
양쪽 모두 표면으로부터 1–2, 2–3 voxel 거리의 샘플이 존재했다.
즉 데이터가 1-shell로 잘린 것이 아니라 이전 full-field 단면의 near-zero
밝기 표시가 약 1 voxel scale이었던 것이다. 이 수치는 해당 데이터의 관찰이며
일반적인 양수/음수 voxel 수가 같아야 한다는 의미는 아니다.

깊은 내부의 sign까지 확인하려면 다음을 따른다.

1. `View → Sign slice · full field`를 선택한다. 처음 선택하면 Z 중앙 단면과 orthographic
   카메라로 전환된다.
2. `Clip / slice axis`에서 X, Y, Z를 고른다. 축을 바꾼 뒤 같은 이름의 **X/Y/Z
   카메라 버튼**을 눌러 정면으로 본다. 축 선택과 카메라 방향은 별개의 설정이다.
3. `Plane` 슬라이더로 단면 위치를 옮긴다. 옆 숫자는 world 좌표가 아니라
   index 좌표다. 예를 들어 원점 이동이 없고 voxel size가 0.004라면 index 50은
   world 0.2다.
4. 몸통 내부가 주황색인지, 외부가 파란색인지 살펴본다. 주황색 속 파란 pocket이
   보이면 실제 cavity인지 sign 오류인지 원본 형상과 비교한다.
5. 줌인하고 `Settled samples = 1`로 voxel 단위 경계를 확인한다. 깊은 내부의
   색도 비활성 mask에서 복원된 실제 부호다.
6. 표면과 비교하려면 `View → SDF surface`로 바꾼다. 이전 clip 설정은 유지되므로
   전체 형상을 보려면 `Clip / slice axis → Off`도 선택한다.

카메라를 단면에 평행하게 돌리면 단면이 거의 보이지 않을 수 있다. 해당 축의
카메라 버튼을 누른다. `Fit`은 최초 카메라 구도를 복원하므로 sign slice를 보던
중에는 축 버튼을 다시 누를 수 있다. 회전된 grid의 index 단면은 world 축
카메라와 일치하지 않을 수 있다. 기본 MeshToSDF driver의 변환은 회전이 없다.

### 내부 공간과 invert mask 확인

`View → Full-space signed cells`를 선택한다. 이 모드는 active narrow band에
PropagateSign의 **비활성 음수 영역**까지 추가한다. 내부 fill은 음수 active
voxel과 같은 주황색이며, 외부 active voxel은 파란색이다.

| 저장 위치 | 한 큐브의 크기 (voxel 단위) | 실제 world 한 변 |
|---|---|---|
| leaf invert의 inactive voxel | 1³ | voxelSize |
| lower invert의 childless tile | 8³ | 8 × voxelSize |
| upper invert의 childless tile | 128³ | 128 × voxelSize |
| root interior | 4096³ | 4096 × voxelSize |

`Clip / slice axis = Z`와 중앙 `Plane`으로 내부를 잘라 보자. 경계 근처의 작은
voxel과 깊은 내부의 큰 tile 경계가 함께 보인다. 같은 색을 유지하면서 셀 크기
차이를 확인할 수 있다. 바깥에서 보면 band가 내부를 가리므로 clip이 필요하다.

**Interior fill** 패널에서 `Active narrow band`와 네 계층을 개별적으로 켜고 끌
수 있다. band를 끄면 fill만 남고, lower를 끄면 8³ tile이 차지하던 내부 영역이
비어 보인다. 계층 옆 숫자는 저장된 inactive box 개수이며 active voxel은 제외한다.
큰 tile 하나를 1³ voxel 여러 개로 펼친 개수가 아니다. 예를 들어 8³ tile 하나는
512개 voxel의 공간을 표현하지만 UI에는 box 1개로 센다.

개발용 bunny에는 1³ fill 1,567,773개, 8³ fill 17,793개가 있다. 128³·4096³
fill은 이 해상도의 bunny에 없으므로 0개로 표시된다. 큰 계층도 renderer가 지원하며,
각 크기의 독립 fixture로 검증한다.

더 높은 해상도인 bunny(dx=0.001, band=3)에서는 active voxel 33,978,756개와
1³ fill 27,898,860개, 8³ fill 700,271개, **128³ fill 165개**를 얻었다. 현재
로컬 데모는 이 데이터로 띄워서 작은 voxel, 중간 tile, 큰 tile을 동시에 확인할
수 있게 했다. 4K 결과는 `output/bunny-hi-full-space-4k.png`에 저장한다.

원래 Polyscope의 `FILL_LEVELS`와 같은
저장 단위 및 `base - 0.5 voxel` 모서리 정렬을 쓴다.

이 모드는 0 등치면을 재구성하거나 누락된 sign을 추측하지 않는다. 이미 저장된
mask의 음수 영역을 표시한다. **내부 sign을 전체 공간에 표현하는 것과, 표면까지의
정확한 거리를 깊은 내부까지 계산하는 것은 구분해야 한다.** 이 파일 형식에서
band 밖 거리 크기는 ±background로 잘려 있고, 해당 위치의 부호만 mask로 복원한다.
양수 비활성 외부 공간은 무한하므로 큐브로 채워 표시하지 않는다.

예전 camera JSON도 사용할 수 있다. 새 `fillMask` 설정이 없으면 모든 그룹을
켜는 값 31을 사용한다. headless 재현에서는 `fillMask=15`로 fill만, 16으로 band만
표시할 수 있다. Python/CUDA 인터페이스가 바뀌었으므로 업데이트 후 backend를
다시 빌드해야 한다. ABI 오류가 보이면 `cmake --build build --target sdf_renderer`를
실행하고 서버를 재시작한다.

## 4. 카메라와 렌더 설정

- 왼쪽 drag: orbit. Shift+drag 또는 오른쪽 drag: pan. Wheel: zoom.
- `F` 또는 `Fit`: 서버 시작 시 카메라의 위치·중심·크기로 복원.
- `Perspective` / `Orthographic`: 원근 / 평행 투영.
- `Surface color`, `Background`, `Transparent PNG`: 재질색, 배경색, alpha 출력.
- `Iso (voxels)`: 렌더할 SDF 등치값. 0은 원래 zero surface다. converter의
  world-unit iso와 단위가 다르며, 이미 생성된 grid의 topology를 확장하지 않는다.
- `Occlusion`: 표면 모드의 SDF 기반 local ambient occlusion. volume 모드에서는
  적용하지 않는다. 전역 조명이나 물리적 shadow 계산이 아니다.
- `Density`, `Shell`: volume 모드의 불투명도와 iso 주변 shell 두께. shell은
  voxel 단위다. `abs(iso) + shell < bandWidth`를 만족해야 한다.
- `Exposure`: linear-light RGB의 배율을 `2^exposure`로 바꾼다.
- `Ray step`: leaf 내부 ray 샘플 간격, voxel 단위. 작을수록 느리지만 세부 형상이
  안정적이다. sign 단면은 ray march를 하지 않으므로 이 값의 영향을 받지 않는다.
- `Preview`: 화면 이미지 해상도. **grid voxel 해상도는 바뀌지 않는다.**
- `Settled samples`: 카메라를 놓았을 때의 antialiasing. drag 중에는 낮은 image
  해상도와 1 sample로 반응성을 확보한다.

표면 clip은 index 좌표가 plane 이하인 영역만 남긴다. 잘린 부분에 새 cap 표면을
생성하지 않는다. 잘린 내부의 색을 보려면 sign slice를 사용한다.

## 5. 확대된 논문용 PNG 만들기

1. `Transmittance volume` 또는 `SDF surface`로 구도를 정한다.
2. wheel로 확대하고 pan으로 관심 부분을 중앙에 둔다. 사후 이미지 확대와 달리
   바뀐 카메라의 ray를 원본 grid에 다시 쏘므로 세부 정보를 새로 샘플링한다.
3. `Width = 3840`, `Height = 2160`, `Samples / pixel = 16`부터 시작한다.
4. `Ray step = 0.25`를 쓰고, 필요하면 0.125 및 64 spp와 비교해 수렴을 확인한다.
5. `Save camera`로 JSON을 저장하고 `Export PNG`를 누른다.

PNG에는 UI와 sign 범례가 포함되지 않는다. 논문에서 sign 색상을 쓰면 caption에
음수/양수 색상 의미를 명시한다. alpha가 필요하면 `Transparent PNG`를 켠다.
출력은 8-bit RGBA sRGB PNG이고 300 dpi 메타데이터를 갖는다. HDR/EXR 출력은 없다.
300 dpi는 배치 크기 정보이며 실제 픽셀 수를 늘리지 않는다.

헤드리스 재현:

```bash
python3 viewer.py output/hairball.nvdb --settings sdf-camera.json \
  --render output/figure-4k.png --width 3840 --height 2160 --samples 16
```

CLI export에서는 width/height/samples를 명령행에서 지정한다. JSON 안의 해당
세 값은 CLI 기본값을 덮어쓰지 않는다. 현재 서버의 초기 화면 크기 역시 UI 기본
3840×2160이며, JSON의 출력 크기는 브라우저의 `Load camera`로 복원할 수 있다.
PNG의 `MeshSDF` text metadata에는 실제 카메라와 render 설정이 저장된다.
파일명과 메타데이터는 원본 파일의 content hash를 보장하지 않으므로 논문 재현에는
mesh, `.nvdb`, 변환 옵션, 소스 commit, 카메라 JSON을 함께 보관한다.

## 6. 성능 및 오류 해결

| 증상 | 확인할 사항 |
|---|---|
| shared library가 없음 | `cmake --build build --target sdf_renderer` 실행 |
| CUDA compiler 오류 | toolkit과 host compiler 호환성, GPU architecture 설정 |
| Missing MeshToSDF channel | `.ccvis`/UDF grid가 아닌 완성된 SDF `.nvdb`인지 확인 |
| root_extent 오류 | 구형 dense root mask의 extent가 누락되거나 손상됨 |
| narrow band 오류 | iso/shell을 band 안으로 줄임; 더 큰 band는 converter로 재생성 |
| GPU 메모리 부족 | 더 큰 GPU 또는 더 큰 voxelSize 사용; preview 해상도만 줄여서는 grid가 작아지지 않음 |
| UI가 느림 | Preview 640, settled 1, step 0.5–1, surface mode로 탐색 |
| 검은/빈 단면 | clip 위치, 선택 축, 카메라 방향 확인 |
| 표면이 계단처럼 보임 | voxel 해상도와 입력 sign 확인; 출력 PNG 해상도만 올려서는 해결되지 않음 |
| 포트가 이미 사용 중 | `--port 8766` 등으로 변경 |

전체 grid는 GPU resident다. 이미지의 타일 렌더링은 framebuffer 메모리만 줄이고
out-of-core grid streaming은 제공하지 않는다. 12 GB GPU에서 실제 검증한
hairball은 약 1.18억 active voxel, grid 570 MB이다. 선행 논문 Fig. 9의 98.8억
voxel은 float sidecar만 약 39.5 GB라 같은 GPU에서 그대로 재현할 수 없다.

SSH에서는 `ssh -L 8765:127.0.0.1:8765 HOST`로 포트를 전달한 뒤 로컬 브라우저로
연다. 서버는 loopback에만 bind하고 외부 CDN을 사용하지 않는다. 인증이 있는
다중 사용자 웹 서비스로 설계된 도구는 아니다.

## 7. Root tile을 채우는 알고리즘 검증

이전 renderer fixture는 주어진 root mask를 **읽고 그리는 것**을 검증했다.
실제 `PropagateSign.cuh`가 root mask를 만드는 과정은 별도 실행 파일로 검사한다.

```bash
cmake -S . -B build -DBUILD_ROOT_FILL_VALIDATION=ON
cmake --build build --target sdf_validate_root_fill -j2
build/sdf_validate_root_fill --output output/root-fill-validation.nvdb
```

실제 GPU root flood와 독립 CPU BFS를 비교하는 14개 사례, leaf부터 root까지
전체 전파를 실행하는 5개 사례가 있다. 중앙 root tile 1개 생성, 양수만 있을 때
0개, 음수 좌표, 여러 내부 tile 24개, Upper child가 모든 root 위치를 차지할 때
0개 등을 확인한다. 모든 예상 좌표의 집합을 비교하고 중복·정렬·child 겹침도 검사한다.

합성 root-scale sparse topology를 쓰므로 거대한 실제 mesh나 수십억 voxel
할당이 필요 없다. 이는 root 로직 검증이며 triangle rasterization이나 mesh
signing의 모든 경우를 증명하는 테스트는 아니다. 자세한 설계와 범위는
[ROOT_FILL_VALIDATION.md](ROOT_FILL_VALIDATION.md)를 참고한다.

실제 GPU 출력 mask를 저장한 파일은 다음과 같이 볼 수 있다.

```bash
python3 viewer.py output/root-fill-validation.nvdb --port 8767 --open
```

`Full-space signed cells`에서 **Root만 켜면 4096³ 주황 큐브 1개**가 남는다.
다른 계층을 함께 켜고 중앙을 clipping하면 작은 fill과 root tile의 관계가 보인다.
