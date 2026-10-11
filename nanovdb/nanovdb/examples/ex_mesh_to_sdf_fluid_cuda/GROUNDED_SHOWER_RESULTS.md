# 바닥의 발 반응과 넓힌 물줄기 — 12초 결과

## isovalue는 무엇인가

`mesh_surface.cc`는 anisotropic kernel을 합친 무차원 렌더용 밀도
`rho_render(x) = sum(Vp * W_A(x - xp))`를 OpenVDB FloatGrid에 저장한다.
`volumeToMesh`가 `rho_render(x) = isovalue`인 표면을 추출한다. 내부는 대체로
그 값 이상이다. 이번 값은 **0.3**이며 이전 영상은 0.2였다.
값을 낮추면 보통 표면이 넓어진다. **고체 SDF의 0 등위면, APIC 입자 질량,
fluid/air mask, pressure solve, 물리적인 점성 계수와는 다른 값**이다.
메시의 부피 감소와 시뮬레이션의 운동 에너지 손실은 별도로 기록했다.
부피를 맞추기 위해 입자 위치·질량·속도를 변경하지 않았다.

## 발 반응

기존 FBX 추출 옵션의 바닥 여유는 35 mm였다. 초반 발의 최저점은 약 37.4 mm여서
64 mm 초기 물층에 잠기는 깊이가 한 simulation voxel(32 mm)보다 작았다.
`--floor-clearance 0.001`로 다시 추출해 초반 발 최저점을 약 3.4 mm로 낮췄다.
이전 mesh/cache와 원본 FBX를 보존했으며 삼각형 연결/FPS는 같다.

낮아진 발에 대한 mesh-only contact는 물 입자를 바닥 아래로 밀어내는 오류가 있었다.
`resolveFloor`는 바닥과 캐릭터 바깥의 가까운 위치를 찾고, `contactVelocity`는
두 경계의 허용 속도 half-space에 최소 변화로 투영한다. APIC와 secondary 모두 적용한다.
임의의 splash impulse나 접선 마찰을 추가하지 않았다. 두 면 접촉/분리 속도의
회귀 검사 오차는 0이고 기존 free-slip 검사도 통과했다.

낙수 입자가 바닥에 도달하지 않는 별도 0.8초 시험에서 초기 pool ID만 추적했다.
0–0.633초, 발 주변 반경 45 cm의 평균 속도 RMS는 **1.550 →
2.897 cm/s (1.869배)**였다.
입자 최고 높이는 7.153 cm였다. 확대 이미지와 0.5배속
비교 영상에서 작은 물결을 확인했다. 발 비교의 두 렌더는 isovalue 0.2를 동일하게 사용했고,
최종 낙수 영상의 0.3과 구분한다. 발 자체가 외부 일을 하므로 이 에너지 증가는
에너지 보존/무감쇠 증명으로 사용하지 않는다.

## 물줄기

| 항목 | 이전 | 현재 |
|---|---:|---:|
| 방출 지름 | 30 cm | 52 cm |
| x/z 중심 | (1.62,1.0) m | (1.67,1.145) m |
| 출구 속도 | 0.9 m/s | 0.36 m/s |
| 유량 | 63.617 L/s | 76.454 L/s |

유량은 `pi*r²*speed`로 계산한다. 지름만 늘려 유량이 약 세 배가 되도록 하지 않고
약 20% 증가로 제한했다. 고정된 머리 vertex 집합의 중심은 12초 동안 방출 원 중심에서
최대 20.97 cm 떨어져 반경 26 cm 안에 있다. 이는 배치 검사이며,
실제 물 충돌은 11/12초 렌더에서도 확인했다.

## 자유표면 affine 증폭과 dissipation

넓힌 물줄기에서 약 1.13초에 극소수 입자가 비정상적으로 빨라졌다. pressure residual과
CFL은 통과했지만 전체 기록에서 최대 속도 성분은 약 1051 m/s까지 올라갔다.
해당 결과는 `scene_grounded_shower_unlimited`에 진단용으로 보존하고 최종 영상에 사용하지 않았다.
1.1초 checkpoint 재현에서 P2G peak가 137.65 m/s까지 증가했고 pressure 전후 값이 같아,
압력 solve 이전의 외삽/affine 재전송 증폭으로 원인을 좁혔다.

현재는 **외삽 face가 포함된 stencil**에서만 affine reconstruction이 입력 속도 성분의
min/max를 벗어날 때 C 행을 축소한다. 평균 입자 속도 v는 바꾸지 않고, 완전히 projected된
bulk stencil과 정확한 affine field에는 적용하지 않는다. 속도 clamp나 점성 항이 아니다.
그러나 미해상도 affine 운동에는 수치 감쇠가 있으므로 이를 숨기지 않는다.
같은 재현 구간의 peak는 6.37 m/s 이내였다.

- 일정 속도 전송 오차: v 9.99e−16, C 2.43e−14.
- Affine field 전송 오차: v 1.67e−15, C 4.16e−14.
- 고정/sparse topology, 0.15초 동일 장면 CSV 차이: 최대 1.0e−10.
- 발 시험의 RMS는 안정화 전 같은 낮은 캐릭터보다 약 14% 작다. 그래도 이전 장면보다
  1.87배 크며, 물결 개선을 최종 limiter 상태로 다시 검증했다.
- 한 checkpoint에서 force/advection 없이 같은 projected grid를 G2P한 진단 결과는 다음과 같다.
  `E = sum(0.5*m*(|v|² + h²/4*||C||²))`다. 이것은 한 번의 limiter 영향이며 누적 감쇠율이 아니다.

| Snapshot | 제한 전 APIC E (J) | 제한 후 (J) | 제거 비율 | 평균 속도 차이 |
|---|---:|---:|---:|---:|
| 0.8s | 0.0511676 | 0.0500146 | 2.253% | 0.000e+00 |
| 1.1s | 472.585 | 471.276 | 0.277% | 0.000e+00 |
| 12.0s | 405.148 | 404.455 | 0.171% | 0.000e+00 |

`limited_affine_rows`의 전체 최대 비율은 90.22%다. 2-cell 깊이의 초기 물층은
stencil 대부분이 자유표면/바닥 ghost를 포함하고 작은 속도 성분도 이 개수에 포함된다.
따라서 적용 개수만을 에너지 손실률로 해석하지 않는다. 장시간 실제 물에 대한 수렴이나
모든 파장의 감쇠율을 증명한 것은 아니다.

## 전체 검증

10,349 substep, 361 프레임, 30 fps, simulation 12초: pressure/접촉/질량/sparse/표면 검사 PASS.

| 항목 | 결과 |
|---|---:|
| 최종 APIC 입자 | 349,723 |
| 최종 물 부피(입자 질량) | 1432.465 L |
| 바닥에서 높이 25 cm 이내의 물 | 1368.113 L |
| 최대 pressure relative residual | 1.000e-09 |
| 최대 moving-wall flux error | 0.000e+00 |
| 최대 flux divergence | 3.855e-09 s⁻¹ |
| 최대 접촉 상대 법선 오차 | 1.663e-15 m/s |
| 잔여 유체/secondary 관통 | 0 / 0.0e+00 m |
| 누락 stencil / 질량 장부 오차 | 0 / 0 |
| 매 substep 최대 속도 성분 | 6.413 m/s |
| Mesh / material volume | [0.835119029538, 1.11679157641] |
| 정규화 인접 mesh 부피 변화 최대 | 0.420% |
| 마지막 foam / spray | 15938 / 2211 |
| 12초 흰 foam 기여 픽셀 | 10041 |

`--max-speed 50`은 G2P 및 mesh contact 직후 **실행을 중단하는 검사**이며 속도를 제한하지 않는다.
정확한 판정 기준/나머지 측정값은 `validation.json`, `pool_validation.json`에 있다.

별도 낮은 해상도 재시작 시험에서 APIC 원시 x/v/C는 2e−8 기준을 통과했지만,
secondary 속도 차이는 1.0109e−5 m/s로 기존 1e−5 기준을 소폭 넘었다. 위치 차이는
5.88e−6 m이고 연속 반복의 속도 차이도 3.39e−6 m/s였다. 임계값을 완화하지 않았다.
이는 **미해결인 secondary 재시작 정밀도 한계**이며 최종 캐시는 resume 없이 연속 실행했다.
측정은 `foot_diagnosis/restart_limited/diagnostic.json`에 있다.

## 성능

| 단계 | substep 평균 ms | 전체 s |
|---|---:|---:|
| topology_ms | 13.042 | 134.97 |
| mesh_sdf_ms | 14.257 | 147.54 |
| boundary_ms | 17.500 | 181.11 |
| p2g_ms | 6.127 | 63.41 |
| pressure_ms | 25.600 | 264.93 |
| g2p_ms | 14.848 | 153.66 |
| contact_ms | 14.878 | 153.97 |
| whitewater_ms | 17.102 | 176.99 |
| transfer_ms | 28.681 | 296.82 |
| io_ms | 7.051 | 72.98 |

| CPU meshing | frame 평균 ms | 전체 s |
|---|---:|---:|
| read_ms | 197.492 | 71.29 |
| pca_ms | 1165.917 | 420.90 |
| grid_ms | 1400.708 | 505.66 |
| clip_ms | 78.401 | 28.30 |
| contour_ms | 25.814 | 9.32 |
| write_ms | 283.279 | 102.26 |

전체 simulation 실행(출력 포함)은 2528.8초, CPU meshing의 프레임별 계산 합계는
1137.7초였다. 렌더 파이프라인(USD 구성/렌더/인코딩 포함)은
392.8초, 디버그 영상 생성은 169.0초였다.
이 pipeline 시간은 위의 순수 solver 시간과 구분한다.

CPU meshing은 simulation과 순차 프레임으로 병행해 PCA 시간 필터를 연속 유지했다.
대기 시간은 meshing frame 계측에서 제외한다. 짧은 진단/렌더를 병행했으므로 이 시간은
격리된 benchmark가 아니다. 파일 전송/출력/meshing/render는 solver와 별도 기록한다.

## 재현과 결과

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
PY=/tmp/fluid-render-venv/bin/python
blender -b --python "$EX/scene/export_character.py" -- --input "$HOME/Downloads/Arms Hip Hop Dance.fbx" --output "$EX/output/character_grounded" --floor-clearance .001
cmake --build build/release --target ex_mesh_to_sdf_fluid_scene_cuda ex_mesh_to_sdf_fluid_surface ex_mesh_to_sdf_fluid_water_verify ex_mesh_to_sdf_fluid_affine_verify -j3
$PY "$EX/scene/pipeline.py" "$EX/scene/grounded_shower.json"
$PY "$EX/scene/validate_scene.py" "$EX/output/scene_grounded_shower" --workers 4
$PY "$EX/scene/verify_white_foam.py" "$EX/output/scene_grounded_shower" --character "$EX/output/character_grounded" --frame 360
build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_affine_verify "$EX/output/character_grounded" "$EX/output/scene_grounded_shower"
```

- [최종 12초 영상](output/scene_grounded_shower/dance_water.mp4)
- [이전/현재 12초 비교](output/scene_grounded_shower/before_after.mp4)
- [발 반응 비교, 0.5배속](output/scene_grounded_shower/feet_comparison_half_speed.mp4)
- [발 확대 이미지](output/scene_grounded_shower/feet_comparison.jpg)
- [0/3/11/12초 이미지](output/scene_grounded_shower/representative_frames.jpg)
- [발 움직임 측정 그래프](output/foot_diagnosis/foot_motion.png)
- `output/scene_grounded_shower`: simulation cache, `surface/` mesh/foam cache,
  `scene.usdc` 3D animation, `render/` PNG, `debug.mp4`, 각종 검증 JSON/CSV.

모든 변경은 예제 폴더와 예제 CMake에 한정했다. 기존 NanoVDB operator와 ovrtx SDK는 수정하지 않았다.
해상도는 h=32 mm, meshing=10 mm다. 작은 물막/밀리미터 splash는 미해상도이며,
초기 발 반응은 큰 물보라가 아니라 얕은 물의 작은 물결이다. Mesh 부피 지표는 국소적인
모든 surface flicker를 증명하지 않는다. 닫힌 계산 측면은 전체 높이까지이며 overflow 모델은 없다.
