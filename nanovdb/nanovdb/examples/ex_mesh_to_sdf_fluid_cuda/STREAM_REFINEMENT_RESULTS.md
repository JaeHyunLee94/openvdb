# 물줄기 축소와 젤리처럼 보이는 흐름: 최종 결과

GPU 재부팅 후 **42 cm emitter / 20 mm fluid grid로 12초 시뮬레이션과 전체 렌더를 완료**했다.
기존 52 cm보다 유량을 34.8% 줄였고, 같은 유량의 32 mm 대조군과 비교했다.
굵은 덩어리는 재질만의 문제가 아니었다. 입자 간격과 표면 kernel의 물리적 크기를 줄이자
몸 주변 표면의 입자 지지 거리 p95가 36.2% 감소했다. 별도로 드러난 부분 셀의 압력 경계 오류도
수정했다. 마찰, 물 재질, isovalue를 바꿔 현상을 가리지는 않았다.
기존 라이브러리와 ovrtx SDK는 이번 작업에서 수정하지 않았다.

- [최종 12초 영상](output/scene_clear_shower_fine/dance_water.mp4)
- [이전 장면과 비교](output/stream_diagnosis/previous_vs_refined.mp4)
- [동일 유량에서 두 해상도 비교, 3초](output/stream_diagnosis/resolution_motion.mp4)
- [대표 프레임 0 / 3 / 11 / 12초](output/stream_diagnosis/fine_representative.jpg)
- [전체 구간 수치 그래프](output/scene_clear_shower_fine/validation_overview.png)

센티미터 단위의 물막과 연결부는 여전히 보인다. 밀리미터 물막까지 해상하거나
누적 수치 감쇠가 없음을 입증한 결과는 아니다. 최종 부피 편향과 검증 범위는 아래에 명시했다.

## 확인한 사실

- 이전 emitter 지름 52 cm, 출구 속도 0.36 m/s, 유량 76.454 L/s.
  새 설정은 42 cm, 0.36 m/s, 49.876 L/s (유량 약 34.8% 감소).
  중심 x/z=(1.67,1.1551) m. 12초 머리 vertex 중심 이동 범위를 이용한 배치다.
  배치 검사에 더해 최종 11초와 12초 렌더에서도 머리·상체와 물줄기의 접촉을 확인했다.
- 3초 기존 캐시의 몸 근처(y>0.3 m, obstacle SDF<32 mm) APIC 입자 1,521개:
  속도 중앙값 2.755 m/s, 수직 속도 중앙값 -2.627 m/s.
  입자가 몸에 멈춰 붙어 있다는 설명은 이 프레임과 맞지 않는다.
- Blender CPU에서 동일 mesh를 불투명하게 표시해도 굵은 연결부가 남는다.
  따라서 반사/굴절 재질만으로 생기는 현상은 아니다.
- 현재 solver에는 물리적인 점성/표면장력/접촉각 모델이 없고 접선 접촉은 free-slip이다.
  마찰을 더하는 것이 현재 형상 문제의 해법이라는 증거는 없다.
- 기존 h=32 mm, ppc=8은 입자 간격 16 mm, 고립 입자의 등부피 구 지름 19.85 mm,
  기본 anisotropic kernel 반경 38.4 mm다. aspect ratio 상한 3에서 최대 축 반경의
  이론상 상한은 79.88 mm다. 이 상한이 모든 입자에 실제 적용된다는 뜻은 아니다.
  센티미터 규모의 입자/커널과 셀 분류는 얇은 물막·작은 물방울에 한계가 있다.

## 동일 캐시의 표면 후보 검사

기존 입자 위치/속도/질량은 모두 그대로 두었다.

- support=2.0, smoothing=0.04, mesh_h=8 mm, iso=0.3:
  3초 몸 근처 mesh vertex–최근접 입자 거리 p95 17.91 → 17.08 mm.
  전체 공중 mesh vertex 중 입자 간격보다 멀리 떨어진 비율 16.58 → 11.11%.
  그러나 12초 mesh/material 부피비가 0.7878로 기존 하한 0.8을 밑돌아 채택하지 않았다.
- support=2.2, smoothing=0.04, mesh_h=8 mm, iso=0.4:
  마지막 mesh/material 부피비 0.7208. 과도한 부피 감소로 탈락했다.
- 이 거리 지표는 표면의 입자 지지 범위를 측정한다. 점성이나 전체 동역학의
  정확성을 측정하는 지표가 아니다. 정지 이미지로 시간적 젤리 현상 해결을 주장하지 않는다.

## 비교 설정

`scene/clear_shower_coarse.json`: h=32 mm, obstacle_h=16 mm, mesh_h=10 mm, 3초.
`clear_shower_coarse_probe`는 경계 수정 전 비교로 보존했다.
`scene/clear_shower_fine.json`: h=20 mm, obstacle_h=10 mm, mesh_h=6.25 mm, 12초.
양쪽 ppc=8, iso=0.3, support=2.4, smoothing=0.12와 emitter 유량이 동일하다.
임계값이나 마찰을 바꾸지 않고 계산/경계/표면 해상도를 함께 올리는 비교다.

## 실행 환경 복구

첫 실행은 GPU가 `GPU requires reset`인 상태라 CUDA error 100으로 시작하지 못했다.
사용자가 재부팅한 뒤 GPU를 다시 확인하고 새 실행을 시작했다.
재부팅으로 사라진 /tmp Python 환경은 예제 output/render-venv에 다시 설치했다.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
python3 -m venv "$EX/output/render-venv"
PY="$EX/output/render-venv/bin/python"
$PY -m pip install -r "$EX/scene/requirements-render.txt"
cmake --build build/release --target ex_mesh_to_sdf_fluid_cuda \
  ex_mesh_to_sdf_fluid_scene_cuda ex_mesh_to_sdf_fluid_surface \
  ex_mesh_to_sdf_fluid_surface_inspect ex_mesh_to_sdf_fluid_water_verify \
  ex_mesh_to_sdf_fluid_affine_verify -j3
$PY "$EX/scene/pipeline.py" "$EX/scene/clear_shower_coarse.json"
$PY "$EX/scene/pipeline.py" "$EX/scene/clear_shower_fine.json"
```

진단 코드: `scene/inspect_surface.cc`, `scene/render_surface_diagnostic.py`.
진단 산출물: `output/stream_diagnosis/`.
CPU 비교 이미지: `baseline_clay.png`, `support20_clay.png`, `support22_iso40_clay.png`, `particles.png`.
최종 시뮬레이션/표면/렌더와 전체 cache 검증을 모두 완료했다.

## 고해상도에서 드러난 경계 처리 오류

기존 center-mask 모델은 0.9초 직후 pressure 검증에서 중단됐다. 덤프한 87,840개
unknown 중 [87,0,54]의 한 셀은 diagonal=0인데 rhs=-0.02697317이었다.
나머지 큰 component의 true residual norm은 3.30e-14였고, SciPy 독립 CG도
2,500회 뒤 상대 residual=0.0016817로 동일하게 정체했다. 반복 횟수 문제가 아니다.

`characterFaces`의 "둘 중 한 셀 중심이 고체면 face 전체 폐쇄" 규칙을 제거했다.
인터페이스 근처는 실제 face의 4×4 SDF 샘플로 열린 비율을 계산하며,
contact 검사를 통과한 입자가 존재하는 부분 셀은 중심 SDF 부호와 무관하게
pressure unknown에 포함한다. 입자를 삭제하거나 pressure residual을 숨기지 않는다.
미해상도 transport fallback도 이미 표현된 부분 셀 전체를 ballistic으로 바꾸지 않도록 수정했다.

실패 전 0.9초 checkpoint의 진단 재실행은 1.2초까지 PASS. 최종 캐시는 변경 전
checkpoint에서 이어붙이지 않고 처음부터 생성했다. 물리 버전은 `cut-cell-contact-7`이다.
원본 형상을 전제로 한 고정 좌표 회귀 검사는 `output/character`로 통과했다.
그 회귀 검사에 34 mm 내려간 character_grounded를 넣은 실행은 fixture 좌표 불일치로
실패했으며, 그 실행도 로그에 보존했다. 지침/판정 기준은 변경하지 않았다.

실패 캐시: `output/scene_clear_shower_fine_center_mask_failed`.
독립 압력 진단: `scene/inspect_pressure.py`, `output/stream_diagnosis/pressure_system.json`.
실패 재현 및 수정 후 구간: `output/stream_diagnosis/pressure_probe*`.

## 완료된 회귀 검사와 기존 해상도 대조군

- 고정/sparse topology 0.15초 동일 조건: 비시간 측정값 최대 차이
  `2.9810e-15` (허용 `1e-7`). 일정 속도 APIC 왕복 최대 오차 `9.9920e-16`,
  affine field 속도 오차 `1.6653e-15`, affine matrix 오차 `4.2036e-14`.
- 수정된 경계의 32 mm / 42 cm 대조군 3초: 2,670 substeps, 91 frames,
  160,105 APIC particles. 기존 `validate_scene.py`, `verify_pool.py` 모두 PASS.
  full-cell 정규화 RMS flux divergence의 시간상 최대 `2.95866e-9` (허용 `1e-6`), 관통/누락 stencil/질량 원장 오차 0.
  표면 부피비 `0.98658–1.10297`, 인접 프레임 정규화 부피 변화 최대 `0.00372235`
  (허용 `0.08`). 최종 결과 파일은 `output/scene_clear_shower_coarse/validation.json`.
- 같은 대조군의 3초 상태에서 affine limiter on/off를 동일한 projected grid로 비교:
  평균 입자 속도 차이 0, 한 번의 G2P에서 APIC 에너지 감소율 `0.00173704` (0.174%).
  평균 속도를 직접 감쇠하지 않는다는 검사이며, 전체 시간 적분의 누적 numerical
  dissipation이 0이라는 뜻은 아니다. free-slip과 이 limiter는 이번에 변경하지 않았다.

```bash
BIN=build/release/nanovdb/nanovdb/examples
$BIN/ex_mesh_to_sdf_fluid_water_verify "$EX/output/character"
$BIN/ex_mesh_to_sdf_fluid_affine_verify "$EX/output/character_grounded" \
  "$EX/output/scene_clear_shower_coarse"
$PY "$EX/scene/validate_scene.py" "$EX/output/scene_clear_shower_coarse" --workers 3
$PY "$EX/scene/verify_pool.py" "$EX/output/scene_clear_shower_coarse"
```

완료된 simulation/surface cache의 전체 렌더와 검증 자동화는
`scene/finish_clear_shower.py`이며 `output/stream_diagnosis/postprocess.log`에 기록한다.
`scene/preview_clear_shower.py`는 3초 두 해상도를 동일한 world-space 20 mm body band에서
비교한다. 3초 대조 영상은 동일한 새 경계/유량을 비교하며, 이전 12초 영상과의 비교는
유량과 경계 모델도 달라서 순수한 해상도 실험으로 해석하면 안 된다.

## 완료된 3초 해상도 비교

32 mm, 같은 42 cm emitter에서 경계 수정만 비교하면 몸 근처 표면 지지 거리 p95는
17.577 → 17.617 mm로 거의 같았다. 속도 중앙값은 2.979 → 3.151 m/s다.
따라서 경계 수정만으로 굵은 재구성 형상이 없어졌다고 볼 근거는 없다.
그 수정은 고해상도에서 확인된 압력 불능 셀을 해결하는 데 필요했으며,
형상 두께의 주된 개선 근거는 아래 해상도 비교다. 두 coarse 설정의 차이는
`solver_revision`뿐이다. 원시 수치는 `coarse_old_boundary_geometry.json`에 있다.

`output/stream_diagnosis/resolution_comparison.jpg`는 위쪽에 원래 물 재질,
아래쪽에 거품을 숨긴 불투명 재질을 나란히 보여준다. 두 경우 모두 같은 emitter와
수정된 경계 모델이다. 몸 근처(y>0.3 m, obstacle SDF<20 mm)의 결과:

| 항목 | 32 mm | 20 mm |
|---|---:|---:|
| APIC 입자 수(해당 영역) | 363 | 2,190 |
| 입자 속도 중앙값 (m/s) | 3.151 | 4.487 |
| 수직 속도 중앙값 (m/s) | -2.918 | -4.168 |
| mesh vertex–최근접 입자 거리 p95 (mm) | 17.617 | 11.241 |

렌더 표면이 입자로부터 뻗는 절대 거리는 36.2% 줄었다. 단, 전체 공중 vertex 중
각 해상도의 입자 간격보다 멀리 있는 비율은 15.7%에서 19.1%로 늘었다.
모든 무차원 형상 지표가 개선됐다고 주장하지 않는다. 속도 중앙값은 서로 다른
입자 집합의 통계이며 동일 입자의 가속도 비교도 아니다.

고해상도 3.1667초 checkpoint의 affine limiter 검사: 평균 속도 차이 0,
단일 G2P APIC 에너지 감소율 0.0889%. `fine_prefix_affine_energy.log`에 보존했다.
처음 3초 영상: `output/scene_clear_shower_fine/dance_water_first3s.mp4`
(1280×960, 48 spp, 30 fps, 초기 프레임을 포함한 91프레임).
0.2초 간격의 몸 주변 프레임은 `output/stream_diagnosis/fine_motion_samples.jpg`.
12초 최종본은 1600×1200, 96 spp이며 아래 전체 구간 검증을 통과했다.

6초 중간 캐시: 805,522 APIC 입자, 15,569 foam, 1,697 spray.
0–6초 9,074 substeps에서 residual 최대 `9.99974e-10`, weighted divergence 최대
`4.12776e-9`, 관통/누락 stencil/질량 원장 오차 0이다.
`output/scene_clear_shower_fine/foam_visibility/frame_000180.json`의 동일 조건
foam on/off 렌더 검사는 PASS: 밝고 흰 foam 기여가 화면의 0.7007%
(기준 0.2%)이며, 바닥 ROI의 기여는 전체 화면의 0.6948% (기준 0.1%).
이 검사는 foam의 영상 기여를 측정하며, 간접 조명 효과도 포함한다.
중간 대표 이미지: `output/scene_clear_shower_fine/preview/frame_000180.png`.

## 전체 cache 검사 비용

물리 계산을 바꾸지 않고 CPU 검증의 두 반복 검색을 최적화했다.
`verify_pool.py`는 16 cm tile마다 전체 입자를 다시 검색하는 대신 한 번 분류한다.
타일 경계와 바로 옆 floating-point 값, 빈 입력, 실제 0/3/6초 프레임에서 기존
수위 배열과 NaN 위치까지 정확히 일치했다. 6초 프레임의 해당 계산은
1.474 → 0.057초였다. `validate_scene.py`는 두 32-bit vertex index를 충돌 없는
64-bit 정수로 묶어 edge incidence를 센다. 열린 삼각형, non-manifold edge,
넓은 index, 실제 0/3/6초 mesh에서 기존 incidence 배열과 정확히 일치했다.
6초 프레임의 해당 계산은 2.101 → 0.274초였다. 기준을 완화하거나 프레임을 생략하지 않았다.

```bash
$PY "$EX/scene/verify_pool_tiles.py" "$EX/output/scene_clear_shower_fine" \
  --output "$EX/output/stream_diagnosis/pool_validator_optimization.json"
$PY "$EX/scene/verify_mesh_edges.py" "$EX/output/scene_clear_shower_fine" \
  --output "$EX/output/stream_diagnosis/edge_validator_optimization.json"
$PY "$EX/scene/plot_clear_shower.py" "$EX/output/scene_clear_shower_fine"
```

최종 plot 명령은 전체 cache 검증이 PASS인 경우에만 실행한다. 진행 중 그래프에는
`--allow-partial`이 필요하고, 제목과 파일명에 partial을 명시한다.


## 최종 설정과 12초 검증

설정 원본: [clear_shower_fine.json](scene/clear_shower_fine.json).
GPU는 RTX PRO 3000 Blackwell Laptop 12 GB, 드라이버 580.178.04다.

| 항목 | 최종 설정 |
|---|---|
| fluid / obstacle / meshing voxel | 20 / 10 / 6.25 mm |
| particles per cell / nominal spacing | 8 / 10 mm |
| 시간 | 12초, 18,468 substeps, 30 fps, 초기 상태 포함 361프레임 |
| timestep | 최대 0.004초, CFL 적응형, 평균 0.00064977초 |
| emitter | 지름 42 cm, 0.36 m/s, 49.8759 L/s |
| 초기 수심 / 배수 | 6.4 cm / 배수 없는 닫힌 basin |
| 표면 | iso=0.3, support=2.4, smoothing=0.12, OpenVDB VolumeToMesh adaptivity=0 |
| whitewater | rate=360000, foam radius scale=1.5, lifetime scale=1.8 |
| 물 재질 | IOR=1.333, roughness=0.025 |
| solver revision | cut-cell-contact-7 |

`iso=0.3`은 anisotropic kernel 합으로 만든 scalar field에서 표면을 추출하는 등치값이다.
물리적인 점성 계수가 아니다. 높이면 일반적으로 표면이 입자 쪽으로 줄어든다.
이번에는 iso를 높이는 후보가 부피 검사에 실패해 기존 값을 유지했다.
고립 입자는 별도 등부피 구 보정을 이미 사용하고 있다.

전체 결과: [validation.json](output/scene_clear_shower_fine/validation.json),
[pool_validation.json](output/scene_clear_shower_fine/pool_validation.json). 모든 항목 PASS.

| 검사 | 전체 구간 측정 | 판정 기준 |
|---|---:|---:|
| PCG 상대 residual 최대 | 9.99974e-10 | 각 step 절대 residual ≤ max(1e-12, 2e-8 × RHS norm) |
| projection 후 RMS flux divergence의 시간상 최대 | 4.12776e-9 /s | < 1e-6 /s |
| moving-wall flux error | 0 | ≤ 1e-9 |
| contact 후 inward 상대 법선 속도 | 1.95761e-15 m/s | < 1e-8 m/s |
| 남은 fluid 관통 횟수 / 깊이 | 0 / 0 m | 0 / ≤ 1e-7 m |
| foam/spray 관통 깊이 | 0 m | ≤ 1e-7 m |
| 누락 stencil / 입자 질량 원장 오차 | 0 / 0 | 0 |
| CFL 최대 | 0.210555 | < 0.5 |
| 유입 양자화 오차 | 9.99919e-7 m³ | ≤ 입자 하나: 1e-6 m³ |
| 미해상도 접촉 fallback 비율 | 0 | ≤ 0.005 |
| mesh/material 부피비 범위 | 0.835322–1.065544 | 0.8–1.2 |
| 인접 프레임 정규화 부피 변화 최대 | 0.00317711 | < 0.08 |
| kernel 적분 상대 오차 최대 | 3.17053e-5 | < 0.03 |
| 바닥 반사 kernel 보존 상대 오차 | 6.51850e-11 | < 1e-6 |
| watertight 검사 | 361/361, 잘못된 edge incidence 0 | 전 프레임 0 |
| 렌더 binary와 OBJ | 동일 faces, vertex 오차 7.45058e-9 m | ≤ 5e-7 m |

Divergence는 움직이는 벽 속도와 face의 열린 비율을 포함하는 유량으로 계산하며,
전체 셀 부피로 정규화한 **RMS**다. 위 값은 RMS의 시간상 최대이며,
각 셀의 pointwise 최대나 정확한 cut-cell 유체 부피로 나눈 divergence는 아니다.
접촉 검사는 discrete substep 종료 상태와 사용한 obstacle SDF에 대한 검사다.
연속 시간 swept 충돌 또는 원본 triangle에 대한 오차가 0이라는 뜻은 아니다.

최종 APIC 입자 **1,104,778개**, foam **15,721개**, spray **1,543개**다.
초기 material volume 0.506267 m³에 0.598511 m³가 유입되어 최종 1.104778 m³,
배출은 0이다. 바닥 25 cm 아래의 material volume은 1.06589 m³이고,
면적으로 나눈 등가 수심은 13.8788 cm다. 별도 입자 tile 수위 proxy는 11.9058 cm다.
이 proxy는 물줄기 밖 tile의 입자 p90에 반 입자 간격을 더한 값으로, 파도와 표본 분포에
영향을 받으며 정확한 자유표면 측정값은 아니다.

Whitewater 생성은 실제 63,644개, 기대값 63,802.6개로 6σ 범위 1,520.55개 이내이며
수명 원장도 일치했다. 최종 [foam on/off 검사](output/scene_clear_shower_fine/foam_visibility/frame_000360.json)는
흰색 기여 13,320 pixels (화면 0.69375%, 기준 0.2%), 바닥 영역 기여 13,116 pixels
(전체 화면 0.683125%, 기준 0.1%)로 PASS다. 같은 물/카메라/조명에서 foam만 숨겨 비교했다.
min RGB>120, channel spread<65, 양의 휘도 차이>30을 사용했다. 간접 조명 변화도
포함하므로 이 수치를 입자 수 또는 유체 정확성 지표로 해석하면 안 된다.

12초 checkpoint에서 같은 projected grid를 사용한 affine limiter on/off 검사:
평균 입자 속도 차이 0, APIC 에너지 290.36026 → 290.03286 J,
한 G2P의 에너지 감소율 0.112758%. 전체 시퀀스의 누적 numerical dissipation 검사는 아니다.

## 부피와 영상 품질의 남은 한계

최종 렌더 mesh의 부피는 **0.922845 m³**, material volume의 **83.5322%**다.
이전 52 cm 장면의 마지막 비율 83.855%와 비슷한 감소 편향이 남는다.
입자 원장에 질량 손실이 없다는 사실만으로 실제 공간상 유체 부피가 보존됐다고 할 수는 없다.
현재 fluid/air 분류는 입자 점유 기반이고, 정확한 fluid SDF/ghost-fluid 또는 별도
geometric volume controller는 없다. 따라서 16.5% 차이 전부를 meshing에만 돌리거나,
simulation의 geometric volume drift가 없다고 단정하지 않는다.

인접 프레임 부피 변화 0.318%는 전체 부피의 안정성 지표다. 얇은 부분의 연결/분리나
국소 flickering이 전혀 없음을 보장하지 않는다. 10 mm 입자 간격은 밀리미터 물막과
미세 물방울을 충분히 해상하지 못한다. 점성/표면장력/접촉각이 없는 현 모델에서
물리적인 젖음과 가는 물막까지 재현했다고 주장하지 않는다.

## 시간과 메모리

CPU meshing과 일부 비교/preview를 병행한 실제 실행 값이다. 독립 benchmark가 아니다.
시뮬레이션 프로세스 wall time은 **11,105.651초 (185.09분)**이며 파일 출력과 host 진단도 포함한다.

| 시뮬레이션 구간 | 평균 ms/substep | 전체 초 |
|---|---:|---:|
| sparse topology | 13.996 | 258.479 |
| MeshToSDF | 15.513 | 286.488 |
| obstacle sampling / 경계 생성 | 25.881 | 477.965 |
| P2G | 20.031 | 369.940 |
| pressure | 44.397 | 819.929 |
| G2P | 45.713 | 844.233 |
| particle contact | 32.950 | 608.525 |
| whitewater | 20.134 | 371.843 |
| transfer 및 emitter의 host 작업 | 126.084 | 2328.517 |
| 파일 출력 | 11.947 | 220.629 |

`transfer_ms`는 순수 PCIe 대역폭 측정이 아니다. 입자 download/upload와 host에서의
유입·유출 처리, 출력 프레임의 grid/sidecar download를 포함한다.
계측 구간 합과 wall time 사이 약 4,519초는 CFL scan, 추가 host 검사, 할당, 초기화 등
별도 계측하지 않은 작업/대기를 포함한다. 항목별 시간을 단순 합산해 전체 GPU 시간으로 부르지 않는다.

| CPU 표면 후처리 | 평균 ms/frame | 전체 초 |
|---|---:|---:|
| cache 읽기 | 663.633 | 239.571 |
| 이웃 분석 / PCA | 6252.997 | 2257.332 |
| scalar grid 구성 | 4710.122 | 1700.354 |
| 경계 clip | 219.773 | 79.338 |
| OpenVDB contour | 58.470 | 21.108 |
| mesh 파일 출력 | 479.487 | 173.095 |

CPU meshing 계측 합은 4,470.798초이며 simulation과 병행해 별도로 더한 경과 시간이 아니다.
최종 361프레임 렌더 프로세스는 **981.740초**: USD 작성/저장, SDK 준비,
GPU 렌더와 인코딩을 모두 포함한다. RTX step+readback 계측 합은 **79.040초**, 평균
**0.21895초/frame**다. 대부분의 추가 시간은 약 11.05 GiB USD 시퀀스 저장 등에 사용됐다.
최종 cache 수치 검사는 358.821초, pool 검사는 96.257초, 대표 debug는 2.912초,
마지막 foam 가시성 검사는 57.381초다.

substep 종료 시 `cudaMemGetInfo`로 관측한 장치 전체 사용량 최대는 **2964.8125 MiB**다.
동시 실행한 preview/RTX/대조군이 포함되며, operator 내부 순간 peak를 측정하지 않으므로
isolated solver 최대 메모리라고 볼 수 없다.
원본 계측: [validation.json](output/scene_clear_shower_fine/validation.json),
[pipeline_times.json](output/scene_clear_shower_fine/pipeline_times.json),
[postprocess_complete.json](output/stream_diagnosis/postprocess_complete.json).

## 산출물과 재현

- 전체 simulation cache: `output/scene_clear_shower_fine/`.
- 물 OBJ/binary mesh sequence: `output/scene_clear_shower_fine/surface/`.
- 재질/캐릭터/whitewater 포함 3D animation: [scene.usdc](output/scene_clear_shower_fine/scene.usdc).
- 최종 영상: [dance_water.mp4](output/scene_clear_shower_fine/dance_water.mp4),
  1600×1200, 96 spp, 30 fps, 361프레임. 0초 상태를 포함하므로 파일 재생 길이는 12.033333초다.
  ffmpeg 전체 decode와 ffprobe 프레임 수 검사를 통과했다.
- 비교 영상: [이전/최종 12초](output/stream_diagnosis/previous_vs_refined.mp4),
  [동일 유량 32/20 mm 3초](output/stream_diagnosis/resolution_motion.mp4).
- debug: [초기](output/scene_clear_shower_fine/debug/frame_000000.png),
  [6초](output/scene_clear_shower_fine/debug/frame_000180.png),
  [12초](output/scene_clear_shower_fine/debug/frame_000360.png).
  APIC, foam/spray, obstacle, fluid block/halo 단면을 함께 표시한다.
- [불투명 표면을 포함한 해상도 비교](output/stream_diagnosis/resolution_comparison.jpg),
  [최종 foam 비교](output/scene_clear_shower_fine/foam_visibility/comparison_000360.jpg).
- 소스/설정 SHA256와 기반 commit: [source_manifest.json](output/stream_diagnosis/source_manifest.json).
  기존부터 수정된 작업 트리 위의 결과이며 clean commit 재현이라고 주장하지 않는다.

위 빌드 후 시뮬레이션부터 순차 재현하려면 다음 명령을 사용한다.
`output/character_grounded`는 기존에 검증한 고정 connectivity 캐릭터 sequence다.
입력 생성 절차는 [SCENE_IMPLEMENTATION.md](SCENE_IMPLEMENTATION.md)에 있다.
기존 최종 cache를 보존하려면 새 `--output` 경로를 지정한다.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
PY="$EX/output/render-venv/bin/python"
OUT="$EX/output/scene_clear_shower_fine_reproduce"
$PY "$EX/scene/pipeline.py" "$EX/scene/clear_shower_fine.json" \
  --output "$OUT" --stages simulate,mesh,validate,render
$PY "$EX/scene/debug_scene.py" "$OUT" \
  --character "$EX/output/character_grounded" --representative
$PY "$EX/scene/verify_white_foam.py" "$OUT" \
  --character "$EX/output/character_grounded" --frame 360
$PY "$EX/scene/plot_clear_shower.py" "$OUT"
```

`scene/finish_clear_shower.py`는 이번 coarse/fine 경로가 이미 생성된 뒤 전체 검증과
렌더/비교를 묶어 실행하는 전용 스크립트다. 이전 영상 비교에는 기존
`output/scene_grounded_shower/dance_water.mp4`도 필요하다.
