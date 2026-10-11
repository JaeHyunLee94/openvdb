# GPU resident APIC / MGPCG

Scene의 emitter, 초기 pool, animation, whitewater 계수, meshing kernel과 재질은
`scene/clear_shower_fine.json` 그대로 유지한다. 이 문서는 solver 변경을 설명한다.

## 실행 옵션

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
PY="$EX/output/render-venv/bin/python"
cmake --build build/release --target ex_mesh_to_sdf_fluid_scene_cuda \
  ex_mesh_to_sdf_fluid_scene_float_cuda ex_mesh_to_sdf_fluid_scale_double_verify \
  ex_mesh_to_sdf_fluid_scale_float_verify -j3
$PY "$EX/scene/pipeline.py" "$EX/scene/clear_shower_fine.json" \
  --precision float --pressure mgpcg --output "$EX/output/scene_float_mgpcg" \
  --stages simulate,mesh,validate,render
```

`--precision double`은 double 입자/셀/pressure vector를 사용한다.
`--pressure jacobi`는 GPU Jacobi-PCG 대조군이다. 기본값은 double/MGPCG다.
두 precision은 같은 소스의 별도 executable이며, 외부 pipeline에서 명시적으로 선택한다.
Checkpoint는 particle/secondary 구조체 크기를 검사하므로 다른 precision의 binary를
묵시적으로 재해석하지 않는다. CSV/OBJ/렌더 입력 형식은 유지한다.

A6000 등 다른 GPU에서는 해당 GPU에 맞는 `CMAKE_CUDA_ARCHITECTURES`로 빌드해야 한다.
현재 머신의 기존 build는 90-virtual이다. 예를 들어 Ampere 지원을 포함하려면
configure 시 `-DCMAKE_CUDA_ARCHITECTURES='86;90-virtual'`을 사용한다.

## CPU 전송과 GPU 입자 관리

- 매 substep APIC 전체 download → CPU drain/emitter → upload를 제거했다.
  `scalable/ParticleOps.cuh`가 GPU에서 drain 조건을 평가하고 stable stream compaction으로
  입자와 ID를 함께 압축한다. Emitter의 동일 ID 기반 난수와 물리적 유량 적분은 유지한다.
- Foam/spray도 GPU resident다. 생성/이동/충돌/수명 삭제는 GPU에서 수행하며, 생성 buffer가
  넘치면 용량을 늘려 동일 source를 재계산한다. 생성 입자를 조용히 버리지 않는다.
- CFL의 최대 속도/affine bound, divergence RMS, 접촉 오차, 벽 flux, whitewater 통계를
  GPU reduction으로 계산한다. 진단을 생략하거나 불검사 step을 0으로 기록하지 않는다.
- CPU로 전달되는 값은 timestep 제어용 scalar, count와 최종 solver 통계다.
  CG 반복 중 CPU readback은 없다. 출력 frame/checkpoint를 저장할 때는 데이터 전송이 있다.
- 캐릭터 sequence 보간과 BVH refit은 기존 CPU 경로다. MeshToSDF에 넘길 작은 mesh 자료,
  NanoVDB operator의 topology metadata 동기화도 남는다. 프로그램 전체가 CPU 없이
  실행되거나 host synchronization이 0이라는 의미는 아니다.
- 초기 pool 구성과 restart 입력은 한 번의 host staging을 사용한다.

## 데이터와 메모리

| resident 항목 | 이전 double | 새 double | 새 float |
|---|---:|---:|---:|
| APIC particle (`x,v,C`) | 120 B | 120 B | 60 B |
| Cell | 216 B | 144 B | 72 B |
| 셀 inverse address | Cell의 좌표/이웃에 포함 | 4 B | 4 B |

Cell에서 `ijk`, 6개 이웃 표, extrapolation 임시값을 제거했다. Inverse address는
`(leafIndex << 9) | leafOffset`이며, 좌표는 NanoVDB leaf에서 복원한다.
이웃은 accessor로 조회한다. P2G/G2P는 thread-local cached accessor를 재사용한다.
Topology가 바뀔 때 address와 sidecar를 함께 다시 만들며 이전 인덱스를 재사용하지 않는다.
Export용 `HostCell`만 좌표와 이웃을 복원한다. Scene의 block debug 출력은 셀 전체 대신
leaf별 core flag를 내려받는다.

Extrapolation은 `3 × Real + 3 bytes`/cell scratch를 해당 단계에서만 사용하고 해제한다.
Whitewater source의 이전 상태는 Particle 전체 대신 velocity만 보존한다.
캐릭터 접촉 진단은 block reduction 후 작은 summary를 보관한다.

MG/CG vector, coarse topology, 입자 ID, capacity 여유분, operator 임시 메모리와
출력 staging은 위 Cell 크기에 포함되지 않는다. Cell 크기만으로 A6000에서 1024³/8 ppc가
반드시 들어간다고 판단하지 않는다. 전체 할당 수와 유체 점유율을 기준으로 계산해야 한다.
단일 GPU/32-bit sidecar/particle index가 현재 범위이며 multi-GPU는 구현하지 않았다.

## MGPCG

`scalable/Multigrid.cuh`의 matrix-free GPU MGPCG를 사용한다.

1. Fine operator는 기존 moving-wall flux와 face open fraction으로 조립한다.
2. 좌표를 2로 나눈 sparse NanoVDB topology를 반복 생성한다.
3. 2×2×2 aggregate의 piecewise-constant prolongation `P`와 sum restriction `R=Pᵀ`를 사용한다.
4. Coarse operator는 **Galerkin `A_c=Pᵀ A_f P`**다. 내부 edge는 상쇄하고, aggregate 사이
   edge와 fluid/air Dirichlet 기여를 합산한다. 후속 level에서도 Dirichlet 대각 성분을 보존한다.
5. 각 level에서 weighted Jacobi(ω=2/3)를 전/후 2회 대칭 적용한다. 최하위에서는
   동일 smoother 48회로 고정된 선형 preconditioner를 만든다. 최하위 크기 <128 또는
   최대 10 levels에서 멈춘다.
6. CUDA cooperative persistent kernel 하나에서 PCG 반복, scalar reduction, V-cycle,
   수렴 판단을 수행한다. Thread 수는 cooperative residency/occupancy로 제한하고,
   큰 문제는 각 thread가 grid-stride로 처리한다. 문제 크기만큼 resident block을 요구하지 않는다.
7. CG 내적은 입력을 double로 변환해 곱한 뒤 block/global double 합산을 한다.
   Float에서도 단순히 최종 합만 double로 cast하는 방식이 아니다.
8. 수렴 직전 `b-Ap`를 다시 계산한다. Float는 64회마다 reliable restart를 추가해
   recurrence residual과 true residual의 차이를 제한한다. 최종 true residual을 별도 검사한다.

Pressure/coarse coefficient/vector는 선택 precision으로 저장한다. 시간·유량 원장,
진단 합산과 캐릭터 보간/triangle·SDF 기하 질의는 double을 유지한다.
기하 계산을 fluid precision과 분리하여 같은 mesh animation과 충돌 형상을 사용한다. MeshToSDF 자체의 저장/연산 precision은
기존 operator 규칙을 그대로 따른다. 모든 FP64 명령을 제거했다고 주장하지 않는다.

Piecewise-constant aggregate MG이므로 반복 수의 완전한 resolution independence를
보장하지 않는다. 작은 문제에서는 V-cycle overhead가 Jacobi-PCG보다 클 수 있다.
Hierarchy는 바뀐 face 계수를 반영해 매 pressure solve마다 생성한다. Hierarchy 재사용,
고차 보간, AMG, multi-GPU는 현재 범위가 아니다.

## precision별 기준

| 검사 | double | float |
|---|---:|---:|
| 반복 중 relative residual 목표 | 1e-9 | 2e-5 |
| 최종 true residual 허용 | max(1e-12, 2e-8 × RHS norm) | max(1e-12, 1e-4 × RHS norm) |
| full-cell 정규화 RMS flux divergence | 1e-6 /s | 2e-3 /s |
| 벽 flux error | 1e-9 | 2e-5 |
| inward relative contact velocity | 1e-8 m/s | 2e-5 m/s |
| SDF penetration depth | 1e-7 m | 2e-5 m |

관통 횟수, 누락 stencil, 입자 원장 오류의 허용 횟수는 계속 0이다.
CFL 상한 0.5와 유입 양자화 오차 1 particle volume도 유지한다.
`scene/validate_scene.py`는 settings의 precision을 보고 고정된 기준표를 적용한다.
측정값에 맞춰 임계값을 자동으로 변경하지 않는다.

## 검증 도구

```bash
$PY "$EX/scalable/run_verification.py" --max-size 128
$PY "$EX/scalable/report_scalability.py"
```

제조해, fractional faces, 분리된 영역, 닫힌 Neumann 문제, 각 level의 Galerkin identity,
상수/affine APIC 전송, stable ID compaction, emitter의 CPU 수식 대조, CFL reduction을 검사한다.
Scene 비교는 동일 20 mm / 8 ppc에서 이전 cache 및 float/double의 0 / 0.6 / 1.2초를 비교한다.
입자 궤적의 bitwise 동일성을 요구하지 않으며 위치 RMS 1 cell, p99 3 cells,
centroid 0.1 cell, 속도 RMS 0.5 m/s, kinetic energy 상대차 5%라는 사전 기준을 사용한다.
이것은 짧은 구간의 회귀 검사이며 장시간의 수렴 차수/에너지 보존 증명은 아니다.

## 추가로 발견한 접촉 문제

Float APIC의 world-coordinate 반올림으로 바닥 margin 보정이 발생했을 때, 기존의
단일 `touched` flag가 바닥 보정까지 캐릭터 접촉으로 해석했다. 캐릭터에서 떨어진
입자에도 가장 가까운 캐릭터 면의 속도를 적용하여, 거의 평행한 floor/mesh velocity
조건에서 큰 속도를 만들 수 있었다. 실제 실패는 0.739초의 contact 단계에서 잡혔다.
속도 제한을 늘리거나 velocity를 임의로 clamp하지 않았다.

바닥 보정과 mesh 접촉 flag를 분리하고, float의 tank/contact floor margin을 같은 값으로
계산하도록 수정했다. Floor-only 입자는 정상적인 stationary-floor 조건만 받는다.
같은 문제를 가진 secondary contact 경로도 수정했다. `verify_water.cu`에
멀리 있는 캐릭터가 floor-only 입자의 접선 속도에 영향을 주지 않는 회귀 검사를 추가했다.
최종 revision은 `gpu-mgpcg-9`이다. 초기 prototype의 성공/실패 로그도 output/scalability에 보존했다.

기본 검증 스크립트에는 거의 0인 RHS에서 상대 residual만 검사하는 문제가 있었다.
`Run.cuh`에 absolute residual과 RHS norm을 추가하고 기존 solver와 같은
`absolute <= max(1e-12, 2e-8 * RHS norm)`을 검사하도록 정정했다. 작은 RHS의
표시용 relative residual을 0으로 바꾸거나 숨기지 않았다.

## 최종 측정 결과 — revision gpu-mgpcg-9

GPU는 RTX PRO 3000 Blackwell Laptop, 12,227 MiB, driver 580.178.04다.
GPU 작업을 순차 실행했다. 아래 값은 단일 실행 측정이며 통계적인 benchmark 평균은 아니다.
CPU 전원 정책은 기존 powersave 상태다. 머신/전원 정책이 달라지면 절대 시간도 달라진다.

### 동일 장면의 실행 비용

20 mm, 8 ppc, 같은 초기 pool/42 cm emitter/캐릭터의 0–0.2초를 비교했다.
양쪽 모두 110 substeps, 7 cache frames를 기록했다. 이전 executable을
`output/scalability/baseline_scene_cuda`에 보존했다.

| 전체 process wall time | 이전 CPU 입자 관리 + double/Jacobi | 새 GPU 입자 관리 + float/MGPCG |
|---|---:|---:|
| 초기화·시뮬레이션·cache 저장 포함 | 40.754 s | 12.500 s |

**3.26배 속도 향상**이다. Float 전환, precision별 수렴 기준, 메모리 구조와 입자 관리가
함께 바뀐 결과이므로 MG 하나의 효과로 해석하면 안 된다. Meshing/rendering은 포함하지 않는다.

다음은 CSV의 substep 평균이다. File I/O와 출력 전송을 별도로 표시했다.
합계가 process wall time과 같지는 않다. 초기화, frame 0 출력, 계측하지 않은
제어/동기화 비용 등이 별도로 있다.

| 단계, ms/substep | 이전 | 새 float |
|---|---:|---:|
| sparse topology | 12.138 | 11.199 |
| MeshToSDF | 13.940 | 13.866 |
| obstacle sampling / boundary | 6.863 | 7.864 |
| P2G | 12.499 | 3.293 |
| pressure 전체 | 23.359 | 15.604 |
| G2P | 27.674 | 5.121 |
| contact | 12.112 | 14.027 |
| whitewater | 4.437 | 6.048 |
| particle 관리 + 출력 transfer (`transfer_ms`) | 79.373 | 0.467 |
| file I/O | 20.987 | 20.099 |

`transfer_ms`는 순수 PCIe 시간만을 뜻하지 않는다. 이전에는 CPU drain/emitter와
입자 왕복이 들어갔고, 새 경로에서는 GPU drain/emitter 실행과 명시적인 frame 출력
download를 포함한다. 작은 scalar readback과 MeshToSDF 내부 동기화는 남아 있다.
설치된 Nsight Systems 2022.4는 importer 부재로 trace 변환에 실패했다.
따라서 유효한 CUPTI transfer trace를 확보했다고 주장하지 않는다.

### pressure 크기별 비교

같은 float operator/수렴 기준의 GPU Jacobi-PCG와 GPU MGPCG를 비교했다.
Fractional face coefficient를 가진 제조해 cube이며, 시간은 hierarchy setup을 포함한다.
`N`은 제조해 cube의 한 변이다. Halo와 sentinel까지 포함한 sidecar 수는 N³보다 크다.

| N | sidecar cells | Jacobi 반복 / 시간 | MGPCG 반복 / 시간 | 속도비 |
|---|---:|---:|---:|---:|
| 32 | 110,593 | 80 / 5.422 ms | 12 / 11.867 ms | 0.46× |
| 64 | 512,001 | 193 / 48.561 ms | 17 / 37.784 ms | 1.29× |
| 128 | 2,985,985 | 426 / 1,118.707 ms | 23 / 346.120 ms | 3.23× |
| 256 | 20,123,649 | 584 / 13,347.132 ms | 30 / 4,047.491 ms | 3.30× |

256 검사에서 MGPCG는 8 levels, setup 38.240 ms, solve 3,980.444 ms였다.
True relative residual은 1.9463e-5, divergence는 38.3814 → 7.4438e-4 /s,
Galerkin identity 상대 오차는 6.3439e-7, pressure gradient 최대 오차는 3.1948e-5다.
검사 기준은 각각 1e-4, 2e-3 /s, 2e-5, 2e-3이며 모두 통과했다.
MG 추가 자료는 약 423.3 MiB였다. 전체 GPU 메모리를 의미하지 않는다.
작은 32³에서는 MG overhead로 더 느리다. 반복 수 역시 12→30으로 증가하므로
완전한 resolution independence를 주장하지 않는다.

최종 float 원자료: [pressure_benchmarks.json](output/scalability/pressure_benchmarks.json),
[크기별 반복 수·시간 그래프](output/scalability/pressure_scaling.png).
이전 double 검사 원자료는 `pressure_benchmarks_initial.json`에 보존했다.
분리된 영역과 닫힌 Neumann 제조해도 통과했다.

### 실제 장면의 검증 범위

| 실행 | simulation h | 길이 | 최종 APIC 입자 | process wall | 관측 GPU 사용량 최대 |
|---|---:|---:|---:|---:|---:|
| float/MGPCG | 20 mm | 1.2 s | 566,118 | 238.411 s | 424.125 MiB |
| double/MGPCG | 20 mm | 1.2 s | 566,118 | 320.636 s | 552.125 MiB |
| float/MGPCG | 12.5 mm | 0.2 s | 2,115,599 | 45.491 s | 648.125 MiB |

메모리는 substep 끝의 `cudaMemGetInfo` 관측값이다. CUDA context/다른 GPU 사용자와
allocator 상태의 영향을 받으며, operator 실행 중 transient peak를 측정한 값은 아니다.
이 수치만으로 더 큰 GPU의 최대 해상도를 외삽하면 안 된다.

20 mm float 1.2초, 1,584 substeps의 결과:

| 검사 | 측정 최대값 | 판정 기준 |
|---|---:|---:|
| pressure true relative residual | 1.99983e-5 | absolute-or-relative, 위 기준표 |
| moving-wall flux divergence RMS | 7.39413e-5 /s | ≤2e-3 /s |
| 벽 flux error | 5.95983e-8 | ≤2e-5 |
| inward relative contact velocity | 7.30893e-7 m/s | ≤2e-5 m/s |
| 잔여 관통 / 최대 깊이 | 0 / 0 m | 0 / ≤2e-5 m |
| whitewater 관통 깊이 | 0 m | ≤2e-5 m |
| 누락 stencil / 질량 원장 오류 | 0 / 0 | 0 / 0 |
| CFL | 0.23825 | ≤0.5 |
| 유입 양자화 오차 | 9.99215e-7 m³ | ≤1e-6 m³, 입자 1개 |

Double 장면의 divergence 최대값은 3.20509e-9 /s였다.
12.5 mm 장면은 175 substeps, divergence 최대 1.16401e-5 /s,
관통·stencil 누락·원장 오류 0으로 통과했다. 고해상도 장면의 전체 12초를
새 backend로 다시 검증한 것은 아니다. 1024³ 장면/A6000 실측도 아직 없다.

추가 검사:

- Float APIC constant field: velocity 최대 오차 6.55651e-7,
  affine field: velocity 7.74860e-7, C 2.19941e-5. 기준은 velocity 5e-6, C 5e-4다.
- 고정/동적 topology 기본 회귀의 최대 위치·속도 차이 각각 약 1e-9; 기준 1e-6.
- Floor-only 접촉 velocity 오차 0, 불필요한 mesh contact 0.
- 실제 캐릭터 SDF 784,930 samples 중 sign mismatch 0. Inactive interior 239개 포함.
- GPU compaction의 ID 정합, emitter 수식, CFL, secondary source 검사 통과.
- Float restart: APIC/secondary ID 동일. 최대 위치 차이 9.53e-7 m,
  속도 차이 6.71e-6 m/s, secondary 상태 차이 1.12e-5; 기준 5e-5 이내.

### 이전 결과와의 궤적 비교 — 실패 항목 포함

같은 ID의 위치를 비교하는 **RMS 2 cm 기준은 float에서 실패했다**.
보고용 명령의 정상 종료를 모든 비교 검사의 통과로 해석하면 안 된다.
`final_scene_comparison.json`에는 `simulation_pass=true`, `bulk_comparison_pass=true`,
**`trajectory_pass=false`**를 각각 기록했다.
`report_scalability.py --strict-trajectories`는 이 경우 실패 exit code를 반환한다.

1.2초에서 이전 accepted cache와 비교하면:

| 항목 | 새 double | 새 float | 기존 기준 |
|---|---:|---:|---:|
| ID별 위치 RMS | 1.053 cm | **2.790 cm, FAIL** | ≤2 cm |
| 위치 p99 | 1.468 cm | 4.547 cm | ≤6 cm |
| centroid 차이 | 0.0439 mm | 0.4024 mm | ≤2 mm |
| 속도 RMS 차이 | 0.0786 m/s | 0.1104 m/s | ≤0.5 m/s |
| 운동에너지 상대차 | 0.0199% | 0.2998% | ≤5% |
| 8 cm bin 물 질량 histogram L1 | 0.6472% | 1.1870% | ≤5% |

0.6초까지 float 위치 RMS는 0.109 mm였지만, 이후 충돌/분리되는 splash 입자 경로가
갈라진다. 최대 ID별 거리는 1.728 m이며, 10 cm 이상 차이 나는 입자 비율은 약 0.441%다.
이것은 수치 정밀도/접촉 분기 민감성과 일치하지만 장시간 동등성을 증명하지 않는다.
Histogram은 bin 경계를 넘은 질량을 양쪽에서 세는 L1 척도다.
물 분포·질량·압력 검사가 통과해도 원래 궤적 기준을 통과로 바꾸지 않았다.
보수적인 재현성을 원하면 double을 선택할 수 있도록 기본값을 유지했다.

### surface / 시각 검증

Float 20 mm의 37 frames 전부를 기존 6.25 mm anisotropic reconstruction으로 meshing했다.
Meshing process wall time 200.317 s, validation 67.324 s로 simulation 시간과 분리했다.
표면 부피 / 입자 물질 부피는 1.04186–1.06557, 인접 frame의 정규화 부피 변화 최대
0.21954%였다. 기준은 부피 비율 0.8–1.2, 변화 ≤8%다.
실제 유체 원장의 질량 증가와 reconstruction 부피 편향은 별도로 계산했다.
Watertightness, winding, floor/side clipping, OBJ와 renderer binary 정합도 통과했다.
부피 변화만으로 국소 flicker가 없음을 증명하지는 않는다.

기존 ovrtx renderer로 1.2초 대표 frame을 1600×1200, 96 samples로 렌더했다.
Renderer process wall은 약 10.56 s이며 simulation에 포함하지 않았다.
Camera/material/물리적 장면 설정은 변경하지 않았다.

- [대표 렌더](output/scalability/final_float/preview/frame_000036.png),
  [이전 결과와 나란히 비교](output/scalability/render_comparison.jpg)
- [초기 debug](output/scalability/final_float/debug/frame_000000.png),
  [중간 debug](output/scalability/final_float/debug/frame_000018.png),
  [마지막 particles / blocks / halo](output/scalability/final_float/debug/frame_000036.png)
- [장면·surface 검증](output/scalability/final_float/validation.json),
  [pool 검증](output/scalability/final_float/pool_validation.json),
  [scene 비교](output/scalability/final_scene_comparison.json),
  [restart 검증](output/scalability/restart_validation.json)

## 재현 및 남은 병목

위 build 후 동일한 짧은 검증을 재현하려면:

```bash
$PY "$EX/scalable/run_verification.py" --precision float --max-size 256
$PY "$EX/scene/pipeline.py" "$EX/output/scalability/fine_float.json" \
  --stages simulate,mesh,validate --output "$EX/output/scalability/reproduce_float"
$PY "$EX/scalable/verify_resident_restart.py"
# 엄격한 궤적 검사: 현재 float의 RMS 기준 실패로 nonzero 반환
$PY "$EX/scalable/report_scalability.py" --strict-trajectories
```

설정 파일의 character 경로는 이 머신에서 bake한 sequence의 절대 경로다.
다른 머신에서는 config의 character 경로와 build의 CUDA architecture를 바꿔야 한다.
`fine_float.json`, `fine_double.json`, `high_float.json`에 실제 실행값이 남아 있다.
위 benchmark 명령은 benchmark JSON/log를 갱신하므로 이전 측정을 보존하려면 복사해 둔다.

NanoVDB의 `voxelsToGrid`/`DilateGrid`를 입자 전체 내부와 halo 생성에 재사용하고,
MG coarse topology도 `voxelsToGrid`로 생성한다. APIC 전송은 자체 CUDA scatter/gather다.
`PointsToGrid`가 APIC의 질량·MAC momentum 전송을 대신하지는 않는다.
MeshToSDF 및 기존 라이브러리/renderer에는 이번 작업의 수정을 넣지 않았다.

이제 장면에서는 obstacle sampling/contact, MeshToSDF, 매번 생성하는 topology의 비중이
상대적으로 커졌다. CPU 캐릭터 보간/BVH refit, geometry double 계산, hierarchy 재생성,
동기식 CSV/checkpoint 출력과 CPU surface reconstruction도 남은 병목이다.
기존 scene의 장시간 캐시는 보존했지만, 새 backend의 장시간 고해상도 결과와
GPU transient peak는 추가 실측이 필요하다.
