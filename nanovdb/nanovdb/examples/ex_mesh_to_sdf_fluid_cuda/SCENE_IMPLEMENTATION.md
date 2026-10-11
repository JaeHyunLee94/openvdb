# Dancing character / continuous water scene

이 문서는 `scene/` 확장 구현이다. 기존 solver의 MAC/APIC·pressure 식과 기본 검증은
[IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md)에 있다. 측정 결과와 최종 영상 위치는
[STREAM_REFINEMENT_RESULTS.md](STREAM_REFINEMENT_RESULTS.md)에 기록한다.
최초 캐릭터 장면의 결과는 [SCENE_RESULTS.md](SCENE_RESULTS.md)에 보존한다.

## 코드와 재사용 범위

- `scene/export_character.py`: Blender evaluated geometry를 고정 connectivity sequence로 bake.
- `scene/Character.cuh`: 시간 보간, vertex velocity, BVH, MeshToSDF 연결, 캐릭터 접촉.
- `scene/scene_main.cu`: 연속 emitter, 흡수 배출 영역, substep, cache, 검증/시간 기록.
- `scene/Whitewater.cuh`: APIC와 분리된 GPU foam/spray.
- `scene/mesh_surface.cc`: CPU anisotropic implicit field → OpenVDB `volumeToMesh`.
- `scene/RawSdf.h`: signed sidecar와 invert mask의 CPU decoder.
- `scene/render_scene.py`: local USD 작성과 기존 ovrtx의 attached-mode rendering.
- `scene/debug_scene.py`: APIC 입자, 캐릭터 삼각형, fluid/halo leaf의 디버그 뷰.
- `scene/verify_scene.cu`, `scene/validate_scene.py`: 독립적인 수치/산출물 검증.
- `scene/Checkpoint.h`: 위치·속도·APIC affine matrix·ID·secondary 상태를 보존하는 local restart.
- `scene/pipeline.py`, `scene/*.json`: 재실행과 단계별 설정. 최신 설정은 `clear_shower_fine.json`.

기존 라이브러리/렌더러는 수정하지 않았다. `MeshToSDF_NEW`, `PropagateSign_*` 실험 구현을
호출하지 않는다. 기존 `MeshToSDF<ValueOnIndex>`와 `BarrierSigning::Heuristic`,
`NestingRule::Solid`를 사용한다. 겹치는 캐릭터 부품을 빈 cavity로 해석하지 않기 위한 solid 설정이다.

Fluid topology는 기존 `voxelsToGrid<ValueOnIndex>`와 여섯 번의 `DilateGrid`를 재사용한다.
`voxelsToGrid`는 내부적으로 `PointsToGrid` 계열을 사용하지만, APIC P2G 질량/운동량 scatter는
기존 예제의 quadratic MAC CUDA kernel이다. 모든 액체 입자의 cell에서 topology를 만들므로
pressure를 풀 내부도 포함한다. 매번 새 topology/sidecar를 만들어 이전의 불필요한 영역을
버린다. 별도 pruning/merging을 하지 않는다. Obstacle grid도 합치지 않는다.

기존 `Fluid.cuh`에는 기본값을 유지하는 계산 영역 크기 인자를 추가했다. PCG 수렴 검사는
반복문의 기준과 동일한 절대/상대 기준을 사용하도록 정리했다. 낙수 초기의 거의 0인 RHS는
상대 residual만으로 판정하면 실패하기 때문이다. 유의미한 RHS에 대한 상대 기준이나 실제
flux divergence 허용치는 느슨하게 바꾸지 않았다.

## 캐릭터: bake, 좌표, 시간과 속도

입력은 `~/Downloads/Arms Hip Hop Dance.fbx`다. Blender 5.2.2의 FBX importer가 확인한
animation은 30 fps, source frame 1–660이다. 두 skinned object `Beta_Joints`, `Beta_Surface`를
모두 포함한다. 합계 24,746 vertices, 49,112 triangles이다.

각 프레임에서 dependency graph의 evaluated object에 `to_mesh()`를 적용하고
`matrix_world`까지 곱한다. 첫 프레임의 loop triangulation을 고정한다. 모든 프레임에서
vertex 수와 polygon vertex connectivity를 비교하고, 실제 출력 OBJ의 모든 `f` 줄의 SHA256도
비교한다. Modifier가 topology를 바꾸는 입력은 조용히 처리하지 않고 실패한다.

전체 animation bounds로 uniform scale과 위치를 정한다. Blender right-handed Z-up의
`(x,y,z)`를 simulation right-handed Y-up의 `(x,z,-y)`로 바꾼다. 단위는 m,
전체 pose 범위의 높이는 1.75 m, 최저점은 바닥 위 0.035 m다. 변환 값은
`output/character/metadata.json`에 기록한다.
최신 장면의 `character_grounded`는 바닥 여유를 0.001 m로 낮춘 별도 bake이며,
아래 발 접촉 항목에 설명한다.

OBJ는 `frame_000001.obj`부터 시작한다. GPU 입력 효율을 위해 같은 데이터를 little-endian
float32 `vertices.bin`, int32 `triangles.bin`과 NumPy 파일에도 쓴다. `sequence.txt`는
frame/vertex/triangle 수와 FPS를 담는다. 원본 FBX 복사본 `source.fbx` 및 원래 rig, skinning,
material, action을 유지하는 `source.blend`도 보존한다. 시작/중간/끝 pose 이미지가 있다.
마지막 pose가 첫 pose와 같은 것은 원본의 loop이며 export 정지 오류가 아니다.

Simulation은 bake frame 사이에서 cubic Hermite로 vertex 위치를 보간한다. 접선은 인접
bake frame의 차분이며, obstacle velocity는 그 Hermite 식의 시간 미분이다. 따라서
위치와 속도가 같은 시간 보간식을 사용한다. 매 substep 끝 시점의 형상으로 SDF를 다시 만든다.
렌더링도 같은 보간식과 같은 시간 offset을 사용한다.

캐릭터 triangle BVH는 첫 pose에서 median split로 만들고 substep마다 bounds를 refit한다.
고체 face 위치에서 가장 가까운 triangle을 구하고, 세 vertex velocity를 barycentric 보간한다.
최근접 거리 tie는 triangle ID로 결정한다. 최근접 계산은 동일 device 함수 경로를 사용해
서로 다른 CUDA kernel의 inlining에 따른 재계산 차이를 줄인다.

## 경계 조건과 실제 검증 범위

기존 `ObstacleView`를 재사용한다. Fluid cell/face의 world position을 obstacle grid의
`worldToIndex`로 바꾼 뒤 trilinear sampling한다. 활성 voxel 값은 blind channel 0의 signed
float sidecar이며 이미 world distance다. 비활성 영역은 channel 1/2/3의 leaf/lower/upper
invert mask와 선택적인 channel 4의 root origin 목록으로 해석한다. `index == 0`이나
비활성 voxel이라는 이유로 outside로 바꾸지 않는다. Band 밖은 부호를 유지한 ±3·obstacle_h다.

고체 cell, 4×4 face quadrature의 open fraction, central-difference normal을 만든다.
현재 캐릭터 경로는 cell-center 부호로 face 전체를 막지 않는다. 충돌 검사 후 입자가
존재하는 부분 셀은 중심이 고체여도 pressure unknown에 포함한다 (`includeCutCells`).
고체에서 충분히 먼 곳의 빠른 판정을 제외하면 실제 face 샘플로 open fraction을 구한다.
정확한 cut-cell 부피/centroid 또는 swept-volume 적분은 구현하지 않았다.
보고하는 flux divergence는 전체 셀 부피를 기준으로 한 RMS 값이다.
Pressure flux는 `open*u + (1-open)*wallVelocity`이다. 완전히 막힌 face는 벽 속도,
부분 차단 face는 액체와 벽의 면적 비율 유량으로 평가한다. 선택 precision의 matrix-free MGPCG와 free-surface air pressure 0 조건을 사용한다.
GPU 입자 관리·압력·메모리 변경은 [SCALABILITY.md](SCALABILITY.md)를 참조한다.

압력 후 검사하는 divergence도 위의 유량 식을 사용한다. 단순한 velocity difference나
선형 solver residual만으로 움직이는 경계의 검증을 대신하지 않는다. Face의 벽 속도는
캐릭터 geometry에서 재계산해 검사하며, 막힌 face의 속도도 비교한다.

입자는 G2P/advection 전후에 SDF 밖으로 보정하고 고체로 들어가는 상대 법선 속도만 제거한다.
분리 속도를 유지하고, 충돌 시 affine matrix의 normal 출력만 제거한다: `C=(I-nnᵀ)C`.
G2P/secondary는 압력용 속도와 분리된 free-slip ghost extension을 읽는다.
얇은 부품은 SDF sampling에서 사라질 수 있으므로
원본 triangle connected-component별 ray parity를 추가로 사용한다. 부품이 겹칠 때는
parity를 모두 XOR하지 않고 각 closed component 내부의 union을 취한다. SDF 밖이지만
원본 mesh 내부인 입자는 가까운 표면 양쪽을 검사해 union 밖으로 보정한다.

매 substep 액체와 secondary particle의 잔여 내부 판정을 검사한다. 검사값은 **입자 중심의
관통**이다. APIC 입자는 유한 반경 구의 물리적 충돌체가 아니다. SDF가 해상도보다 얇은 부품의
pressure 차단 면적을 정확히 재현한다고 주장하지 않는다. Triangle 기반 fallback은 접촉을
보완하며 sub-voxel geometry의 정확한 cut-cell pressure를 구현하는 것은 아니다.

## 유입·배출·질량과 timestep

Domain은 3.2 × 3.2 × 2.4 m다. 최종 emitter는 `(1.62, 2.55, 1.0)` m의 수평 disk,
radius 0.15 m, 초기 하강 속도 0.9 m/s다. 유량은 `Q = π R² v = 0.0636172512 m³/s`다.
초기에는 outlet 아래 길이 0.12 m의 짧은 물 column을 채운다.

액체 입자당 물리적 부피는 `Vp = h³/ppc`다. APIC의 동일 입자 질량은 정규화 계산에서
공통 인자로 소거되며, 물리적인 장부에서는 Vp를 별도로 사용한다. 유입 누적량 `Q·dt/Vp`의
소수 부분을 유지하므로 누적 유입 오차는 한 입자 부피 미만이다. ID는 배출 후 재사용하지 않는다.

바닥은 움직이지 않는 벽이다. `drain_enabled: true`인 기존 장면에서는 x/z 가장자리의
폭 0.14 m 영역에서 y < 0.18 m인 입자를 흡수 배출한다. 이것은 pressure grid의 열린
outflow face가 아니라 **입자 sink**다. 밖의 계산 영역은 기존 닫힌 경계 조건을 유지한다.
`scene/pool.json`은 `drain_enabled: false`로 sink를 끄고 물을 모은다. CLI는
`--drain-enabled 0`이다. Pressure/G2P의 닫힌 측면 경계는 그대로 재사용한다.
수조 모드에서는 secondary도 측면에서 반경만큼 떨어지도록 보정하고 바깥으로 향하는
법선 속도만 제거한다. Foam 표면 탐색은 벽을 공기로 취급하지 않는다.
Meshing field를 같은 x/z 평면에서 자르며, 렌더에는 그 벽의 아래 30 cm를 투명하게 표시한다.
계산 경계는 영역 전체 높이까지 닫혀 있다. 30 cm 높이에서 넘쳐 흐르는 모델은 아니다.
이 변경은 viscosity나 바닥 접선 마찰을 추가하지 않는다.
배출 입자 수/부피를 모두 장부에 더한다.
매 step `N = N_initial + N_emitted - N_drained`를 독립적으로 확인한다.
현재 checkpoint `FLUID004`에는 배출 설정, 초기 pool 수량/깊이, foam 크기·수명·생성률을 저장하며,
다른 설정의 재시작은 거부한다.
이전 checkpoint는 재사용하지 않고 동일 설정으로 다시 계산한다.

`scene/wet_pool.json`은 12초 장면이며 `initial_depth=0.064` m로 시작한다.
같은 Vp를 가진 정지 입자를 바닥에 채우고 SDF clearance/triangle 내부 검사로 캐릭터 내부를 제외한다.
부분 top stratum은 두께 비율로 샘플링하므로 낮은 해상도에서도 초기 깊이를 설정할 수 있다.
실제 초기 부피는 보존된 입자 수×Vp로 기록하며, 높은 해상도 설정은 정확히 네 입자 층이다.

수조용 `mesh_floor_boundary`는 바닥 가까운 PCA kernel의 법선 분산을 regularize하고,
바닥 안으로 잘린 kernel을 위쪽 half-space로 반사하는 렌더링 전용 옵션이다.
정규화된 원래 kernel 적분과 반사 후 half-space 적분을 CSV에 각각 기록한다.
이 옵션은 입자 위치/질량이나 APIC 운동을 수정하지 않는다. 물리적 입자 장부와
meshing 부피를 혼동하지 않으며, 두 검증을 별도로 통과해야 한다.

기존 APIC 속도·affine 성분 기반 timestep, 최대 dt, 캐릭터 최대 vertex speed 기반 이동 제한,
다음 출력 프레임 시간까지의 간격 중 최소를 사용한다. Animation source와 output은 모두
30 fps이며 simulation은 훨씬 작은 adaptive substep이다. 기존 cache는 0–6초이며, `wet_pool` cache는 0–12초다.

## Foam과 spray

Secondary는 위치, 속도, 반경, 나이, 수명, 종류, ID를 가진다. 별도 배열과 별도 CUDA kernel을
사용하며 P2G, fluid mask, pressure solve에는 절대 넣지 않는다.

`foam_radius_scale`과 `foam_life_scale`은 foam의 반경과 수명을 별도로 조절한다.
Spray가 foam으로 전환될 때도 이 종류에 맞는 반경과 새 수명을 부여한다.
`wet_pool.json`의 값은 각각 1.5/1.8, 생성률은 360,000 /(m³·s)다.
최종 물 렌더와 foam만 숨긴 렌더의 흰색 기여를 `verify_white_foam.py`로 비교한다.
입자가 존재한다는 사실이나 물을 숨긴 diagnostic 영상만으로 가시성을 통과시키지 않는다.

MAC mass sidecar를 ppc로 정규화한 주변 density와 그 gradient로 표면 근처 6 cm를 찾는다.
생성 drive는 `|Δv/dt - gravity|`와 APIC affine matrix의 curl이다. 절대 속도 자체는 생성원으로
사용하지 않는다. 기대 생성 수는 `rate [1/(m³·s)] · Vp · dt · drive`이며 drive는 0–3으로 제한한다.
결정적인 hash 난수로 fractional birth를 샘플링한다. 생성 buffer 초과는 조용히 누락하지 않고
실패한다. 동일 물리 상태에서 입자 수와 ppc를 모두 두 배로 해도 기대 생성 수가 같음을 검사한다.
일정 속도의 ballistic 낙하에서는 기대 생성량 0도 검사한다.

Spray는 초기 fluid velocity와 작은 표면 바깥 방향 impulse를 받아 중력·선형 drag로 움직인다.
Fluid sparse grid 밖에서도 자체 속도로 계속 이동한다. 80 ms 이후 액체 밀도가 높고
상대 속도가 액체 안쪽을 향하면 foam으로 전환한다. 출생 직후의 자동 재흡수를 방지한다.
Foam은 grid velocity로 이동하고 고체 내부와 바닥을 제외한 density 0.5 표면으로 보정한다.
바닥 접촉은 접선 속도를 감쇠하지 않으며, spray의 시간 기반 air drag만 유지한다.
Field가 없으면 spray로 바뀐다. 수명 종료 시 제거하고 생성/소멸 장부를 검사한다.

캐릭터의 SDF·triangle fallback·wall velocity와 바닥을 이용해 secondary 충돌도 처리한다.
Foam이 simulation field와 render field의 차이 때문에 물 mesh 안에 숨는 것을 줄이기 위해,
mesher가 **렌더용 foam 복사본만** 재구성한 iso surface로 보정한다. 이동은 최대 6 cm로 제한하고,
고체와 바닥의 여유 거리를 확인한다. 원래 secondary trajectory와 물리 검증 cache는 바꾸지 않는다.

## Anisotropic 표면과 부피 측정

Meshing은 CPU 후처리다. `dx = Vp^(1/3)`이고 3·dx 이웃의 weighted covariance를 PCA로
분해한다. OpenVDB `math::diagonalizeSymmetricMatrix`를 사용한다. 고유축 비율은 최대 3,
축 길이 곱은 일정하게 유지한다. 이웃이 부족하면 isotropic kernel로 되돌린다.
같은 particle ID의 covariance에 이전 프레임 30%, 현재 70% temporal filtering을 적용한다.
Position smoothing도 렌더링 복사본에만 적용한다.

세 반축 a,b,c와 회전 좌표의 타원 거리 q에 대해

```
rho(x) = Σ Vp * 315/(64*pi*a*b*c) * max(1 - q², 0)³
```

를 합친다. Grid는 독립적인 `openvdb::FloatGrid`, background 0, linear world transform
`mesh_h`다. 현재 water 설정은 `mesh_h=0.01 m`, support=2.4·dx, isovalue=0.4다. 이전 final 설정은 baseline으로 보존한다.
12초 `wet_pool`은 같은 mesh 해상도에서 isovalue=0.2를 사용하며, 거친 profile은 0.4를 유지한다.
전체 프레임의 mesh/material 부피와 시간 변화를 별도로 검증한다.
따라서 이 scalar는 SDF가 아니라 **정규화된 입자 density**다. `iso=0`을 쓰지 않는다.

고립된 실제 액체 입자는 작은 kernel로 처리하고, iso에 둘러싸이는 구의 부피가 Vp에
가깝도록 peak를 보정한다. 이 보정은 density integral을 바꿀 수 있으므로 실제 integral도
장부 부피와 비교한다. 해상도 이하의 물방울이나 물막을 완벽히 보존한다고 보장하지 않는다.

캐릭터의 원래 NanoVDB buffer를 blind data 포함 그대로 cache한다. CPU decoder가 동일한
signed sidecar와 invert mask, world transform을 복원해 fluid field를 고체·바닥 밖으로
clip한다. `openvdb::tools::volumeToMesh(..., isovalue=configured, adaptivity=0)`를 호출하고 quad를
두 triangle로 바꾼다. Fog field의 inside 방향에 맞춰 triangle winding을 outward로 정리한다.
새 contouring 알고리즘은 구현하지 않았다.

아래 값을 서로 구분한다.

1. `N·Vp`: 유입·배출을 반영한 material volume/mass 장부. 공간적 부피 보존의 증명은 아니다.
2. `fluidCells·h³`: simulation occupancy proxy. 단순 cell 분류로 인한 경계 오차가 있으므로
   이를 정확한 물 부피라고 해석하지 않는다.
3. `Σrho·mesh_h³`: kernel integral, 그리고 obstacle clip 후의 integral.
4. Triangle mesh의 signed enclosed volume. 이 값과 material volume의 비율 및 프레임 간
   비율 변화를 기록한다. Meshing 변화와 물리적인 유입·배출을 혼동하지 않기 위한 정규화다.

부피 안정성 지표만으로 국소적인 표면 flicker가 없다고 판단하지 않는다. 실제 영상과 debug
sequence도 확인한다. 이 구현은 별도 advected level set을 통한 기하학적 volume 보정이나
고차 free-surface cut cell을 추가하지 않았다.

## 렌더링과 시간 기록

기존 ovrtx README·예제·application-flow, binding-materials, warmup 지침을 확인한 뒤 사용했다.
NanoVDB index sidecar를 렌더러가 직접 읽도록 확장하지 않았다. 표면은 USD triangle mesh,
캐릭터도 동일 evaluated mesh, foam/spray는 별도의 작은 구 형태 mesh로 전달한다.

물은 OmniGlass, IOR 1.333, 별도 foam은 밝은 diffuse material이다. 제공된 FBX의 두 uniform
untextured material의 base color/roughness/metallic을 유지한다. 복잡한 다른 FBX shader의 완전한
자동 변환을 구현한 것은 아니다. 원본 material graph는 source.blend/source.fbx에 보존돼 있다.

Time-sampled USD는 frame마다 달라지는 points, indices, counts, normals, extent를 모두 기록한다.
ovstage attached mode에서 seconds 단위로 sample을 갱신하고 write floor를 올린 뒤 render한다.
PathTracing은 설정된 sample 수를 한 step 안에서 누적한다. Texture가 없는 이 장면에서는
실시간 모드의 여러 프레임 warmup을 영상 프레임으로 섞지 않는다.

CUDA 단계별 시간은 동기화한 wall clock이며 topology, MeshToSDF, boundary, P2G, pressure,
G2P, 접촉, whitewater를 구분한다. Transfer/particle-management와 cache 파일 출력도 별도다.
Pressure 항목에는 PCG와 projection이 포함되며 추가 host 진단의 모든 비용을 포함하지는 않는다.
합산 단계 비용을 전체 프로그램 wall time과 동일시하지 않는다.

CPU meshing은 cache read, neighbor/PCA, FloatGrid 구성, obstacle clip, contouring, OBJ/foam
출력을 나눈다. Cache를 읽는 시간은 GPU에서 simulation을 수행하는 시간이 아니다.
Rendering과 debug/MP4 인코딩도 simulation과 별도로 기록한다. `cudaMemGetInfo`는 substep
끝의 사용량이므로 operator 내부 임시 할당의 순간 최대치까지 보장하는 계측은 아니다.

초기 water 수정 원인, 검증 수치와 비교 영상은 [WATER_FIX_REPORT.md](WATER_FIX_REPORT.md)를 참고한다.


## 발 접촉과 이전 52 cm 낙수 장면

`scene/grounded_shower.json`은 `character_grounded`를 사용한다. FBX 추출의
`--floor-clearance`를 0.035 m에서 0.001 m로 줄였으며 원래 cache는 보존했다.
캐릭터 단독 위치 보정으로 발 아래/바닥 안으로 밀린 입자를 `resolveFloor`에서 두 고체
바깥의 가까운 위치로 보정한다. 속도는 mesh normal과 floor normal의 두 half-space에
최소 변화로 투영한다. 동일 처리를 secondary에도 적용한다.

Emitter 반경은 0.26 m, x/z 중심은 (1.67,1.145) m, 출구 속도는 0.36 m/s다.
기존보다 약 20% 큰 유량이며 넓은 방출 원이 12초 머리 중심 경로를 포함한다.
Meshing isovalue 0.3은 렌더용 density의 등위면 값이다. SDF=0의 고체 경계,
입자 질량 및 APIC/pressure 계산과 구분한다.

외삽 stencil의 affine overshoot 제한은 `IMPLEMENTATION_SPEC.md`에 설명한다.
`--max-speed`(기본 50 m/s)는 G2P 직후 및 접촉 직후 비정상 입자를 발견하면 실행을
중단하는 검증 장치이며 속도 clamp가 아니다. `--diagnose-transfer 1`은 P2G/pressure
단계의 질량 가중 grid 에너지를 추가 출력한다.

## 42 cm 물줄기와 해상도 비교

최신 설정은 `scene/clear_shower_fine.json`이다. 물줄기 지름 42 cm, 중심
(1.67,1.1551) m, 출구 속도 0.36 m/s, 유량 49.876 L/s를 사용한다.
계산 h=20 mm, obstacle h=10 mm, 표면 h=6.25 mm이며 ppc=8, iso=0.3,
support=2.4, smoothing=0.12다. `clear_shower_coarse.json`은 같은 42 cm 유량과
현재 부분 셀 경계 처리를 쓰는 h=32 mm 비교 장면이다.

고해상도에서 발견한 잘못 닫힌 발 아래 pressure 셀을 수정했으며, 압력의
반복 제한(500)과 residual/divergence 판정 기준은 유지한다.
`Solver::pressureDiagnostic`을 설정하면 실패 시 실제 행렬/RHS/해/잔차를 CSV로 보존한다.
`scene/inspect_pressure.py`가 그 행렬의 연결 성분, 대칭성, RHS 적합성을 독립적으로 검사한다.
[원인 분석과 결과](STREAM_REFINEMENT_RESULTS.md)를 참조한다.

새 렌더 Python 환경은 재부팅 후에도 유지되는 `output/render-venv`에 두었으며,
`scene/requirements-render.txt`로 설치할 수 있다. `render_scene.py`의 `--water-style clay`,
`--camera-view body`, `--surface-dir`, `--tag`는 같은 기하를 비교하기 위한 진단 옵션이다.
기본 물 재질과 ovrtx SDK는 그대로다.
`--last-frame N --tag NAME`으로 이미 생성된 앞부분만 별도 영상으로 렌더할 수 있다.
`verify_pool.py`의 수위 tile 검색과 `validate_scene.py`의 edge incidence 계산은
동일한 판정 결과를 유지하도록 최적화했다. 기존 정의와의 비교는 각각
`verify_pool_tiles.py`, `verify_mesh_edges.py`에 있으며 기준을 완화하거나 프레임을 생략하지 않는다.
