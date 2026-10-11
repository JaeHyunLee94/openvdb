# Dancing water scene: 실행 결과

최종 산출물은 **6초 구간, 30 fps, 1600×1200, 181개 상태**다. MP4에는 끝 상태도 한 frame 들어가므로
encoded duration은 6.033초다. 영상은 무음이다.

- [최종 영상](output/scene_final/dance_water.mp4)
- [입자·캐릭터 경계·sparse halo 디버그 영상](output/scene_final/debug.mp4)
- [초기·중간·최종 대표 이미지](output/scene_final/representative.png)
- [수치 검증 그래프](output/scene_final/validation_overview.png)
- [Foam/spray 단독 디버그 이미지](output/scene_final/whitewater_debug.png)
- [FBX 추출 pose 비교](output/character/extracted_poses.png)
- [구현 상세](SCENE_IMPLEMENTATION.md), [기계 판독용 전체 결과](output/scene_final/validation.json)

## 환경과 설정

Branch: `mesh-to-sdf-fluid`. GPU: NVIDIA RTX PRO 3000 Blackwell Laptop, 12,227 MiB.
Blender 5.2.2 LTS, CUDA `/usr/bin/nvcc`, OpenVDB 13.0.1, ovrtx 0.5.1.385782 /
ovstage 0.2.1.385922를 사용했다. 기존 라이브러리와 렌더러 코드는 수정하지 않았다.

FBX는 30 fps / frame 1–660, 24,746 vertices / 49,112 triangles다. 두 skinned mesh를 포함하고
660개 OBJ의 connectivity hash가 일치한다. Boundary/nonmanifold edge는 모두 0이다.
원본 animation 전체를 bake했고 최종 simulation은 처음 6초를 사용한다. World 좌표는 Y-up, m다.
원본·rig·material은 `output/character/source.fbx`, `source.blend`에 보존했다.

| 설정 | 최종 값 |
|---|---:|
| Simulation h | 0.032 m |
| Obstacle SDF h | 0.016 m |
| 독립 meshing h | 0.0125 m |
| Target particles per cell | 8 |
| Particle material volume | 4.096e-6 m³ |
| dt 상한 / 실제 substeps | 0.004 s / 6,275 |
| 실제 dt 범위 | 1.03035e-05–0.00334394 s |
| Emitter 중심 / 반경 | (1.62, 2.55, 1.0) m / 0.15 m |
| 초기 emitter 하강 속도 / 유량 | 0.9 m/s / 0.0636172512 m³/s |
| Whitewater source rate | 40,000 / (m³·s), event drive 별도 |
| Meshing support / isovalue / adaptivity | 2.8·Vp^(1/3) / 0.5 / 0 |
| 렌더링 | ovrtx PathTracing, 96 samples/pixel |

배출은 바닥 근처 y < 0.18 m, x/z 가장자리 폭 0.14 m의 흡수 입자 sink다.
Pressure grid 자체는 닫힌 바닥/외벽 조건이다. 유입·배출과 animation offset은 config에 명시한다.

## 저해상도 → 성능 시험 → 최종 결과

| 실행 | h [m] | 구간 [s] | 최대 액체 입자 | 최대 flux div [1/s] | step 끝 GPU 사용 최대 [MiB] | 검사 |
|---|---:|---:|---:|---:|---:|---|
| low | 0.080 | 1.2 | 4,778 | 2.757e-09 | 261.75 | PASS |
| profile | 0.040 | 1.2 | 38,226 | 6.218e-09 | 261.75 | PASS |
| final | 0.032 | 6.0 | 85,578 | 7.274e-09 | 325.75 | PASS |

Low/profile은 동일한 넓은 emitter의 해상도 시험이다. 최종 장면에서는 캐릭터 가독성을 위해
emitter 반경·유량·위치를 바꿨으므로 final을 두 시험의 수치 수렴 비교로 사용하지 않는다.
GPU 메모리 값은 substep 끝의 `cudaMemGetInfo`이며 operator 내부의 순간 임시 할당 최대치가 아니다.

## 수치 검증과 판정 기준

| 항목 | 측정값 | 기준 / 판정 |
|---|---:|---|
| Pressure true relative residual, RHS norm >1e-8 | 9.999e-10 | ≤2e-8 |
| Pressure absolute/relative combined | PASS | `abs ≤ max(1e-12, 2e-8*norm(b))` |
| 움직이는 고체 유량 기준 divergence | 7.274e-09 s⁻¹ | ≤1e-6 |
| Face wall flux 재계산 오차 | 0.000e+00 m/s | ≤1e-9 |
| 접촉 후 상대 법선 속도 | 1.067e-15 m/s | ≤1e-8 |
| 잔여 액체 입자 중심 관통 / 최대 깊이 | 0 / 0 m | SDF + 원본 triangle union |
| 잔여 whitewater 관통 / 최대 깊이 | 0 / 0 m | SDF + 원본 triangle union + floor |
| 누락 stencil / sidecar 대응 오류 | 0 / 0 | 누락 시 즉시 실패 |
| CFL 최대 | 0.242440 | ≤0.5 |
| 입자 질량 장부 오차 | 0 particles | initial + emitted − drained |
| 누적 유입 부피 오차 | 4.096e-06 m³ | <1 particle volume |
| Whitewater births / 기대값 | 4679 / 4633.132 | 6σ+5 허용 범위 통과 |
| Mesh / material volume | 0.858529–1.024068 | 사전 기준 0.80–1.20 |
| 인접 frame 정규화 부피 변화 | 2.254% | ≤8% |
| Kernel integral 물질 부피 오차 | 0.159% | ≤3% |
| Mesh boundary/nonmanifold edge | 0 | 181개 실제 OBJ 전체 검사 |
| OBJ winding/volume roundtrip 오차 | 9.425e-11 | <1e-4 |

초기 거의 0인 RHS까지 포함한 raw residual 지표의 최대값은 0.0109203다.
거의 0인 초기 RHS에서 상대 residual만의 값은 커질 수 있다. 위의 combined 기준과
독립적인 flux divergence로 판정했으며 이를 보고에서 숨기지 않았다.

최종 물질 부피는 **0.350519296 m³**, 유입 **0.381702144 m³**,
배출 **0.039661568 m³**다. 최종 mesh 부피는 **0.312150608 m³**다.
물질 장부가 정확하다는 사실을 기하학적 부피 보존의 증명으로 해석하지 않는다.
Occupied-cell volume, kernel integral, 최종 표면 부피를 별도로 그래프에 표시했다.

별도 CUDA 검증에서는 8개 pose의 800,000개 후보점 중 표면에서 2 obstacle voxel 이상 떨어진
784,930개 점에서 SDF와 원본 closed-component union의 sign 불일치가 0이었다.
실제 내부 869개, inactive interior 239개도 포함한다. Vertex velocity 미분 검사의 최대 오차는
0.000864402 m/s (기준 0.005)였다.

Whitewater의 자유 낙하 기대 생성량은 0, 같은 물리 상태의 ppc 8/16 기대 생성량은 각각
3.92328533333으로 일치했다. Sparse grid 밖 spray의 analytic gravity/drag 비교 오차는 0이었다.
기존 APIC 회귀 검사의 affine velocity error는 1.67e-15, affine matrix error는 4.21e-14 이하다.

0.4초 checkpoint에서 0.6초까지 재시작한 결과와 연속 실행의 raw `x,v,C` 최대 차이는
1.673e-12, whitewater 상태 차이는
0.000e+00였다. Secondary atomic append 순서는 달라질 수 있어 ID로
정렬한 물리 상태를 비교했다. 초기에 wall 재계산 검사를 실패했던 넓은 emitter도 수정 후
2.3초 구간을 다시 통과했다 (`output/scene_wall_regression/simulation.log`).

## 성능: simulation과 파일·표면·렌더링을 분리

최종 simulation 프로그램 wall time은 **745.084초**다. 아래 합계에 포함되지 않는
host 검증, CFL 계산, wall 재계산 검사, CPU 제어 비용도 있으므로 단계 합을 전체 실행 시간으로
표시하지 않았다. Transfer 항목은 입자 유입/배출 관리와 cache readback까지 포함한다.

| Simulation 단계 | 평균 ms/substep | p95 ms | 합계 s |
|---|---:|---:|---:|
| Sparse topology | 7.663 | 8.840 | 48.088 |
| 캐릭터 평가/BVH refit + MeshToSDF | 12.414 | 13.199 | 77.899 |
| SDF sampling / face 경계 데이터 | 17.309 | 23.230 | 108.611 |
| APIC P2G / mask / 외력 | 1.387 | 2.354 | 8.705 |
| Jacobi PCG / projection | 14.251 | 16.209 | 89.423 |
| Velocity extrapolation / APIC G2P | 2.023 | 3.260 | 12.691 |
| SDF + 원본 mesh 접촉/관통 검사 | 22.632 | 34.450 | 142.016 |
| Foam / spray | 6.077 | 8.496 | 38.135 |
| 입자 관리·전송·cache readback | 3.227 | 5.466 | 20.249 |
| Cache 파일 출력 | 1.102 | 0.000 | 6.913 |

| CPU 후처리 단계 | 평균 ms/frame | 합계 s |
|---|---:|---:|
| CPU cache 읽기 | 38.784 | 7.020 |
| 이웃 / covariance / PCA | 136.417 | 24.691 |
| FloatGrid scalar 구성 | 235.551 | 42.635 |
| Obstacle/floor clip | 14.482 | 2.621 |
| OpenVDB VolumeToMesh | 8.337 | 1.509 |
| OBJ / foam render cache | 44.307 | 8.019 |

전체 surface 후처리 wall time은 **87.202초**다. GPU→CPU cache readback은 simulation
transfer 범주, CPU mesher의 파일 읽기는 위의 별도 read 범주다.
USD 작성·ovrtx rendering·MP4 인코딩은 **100.090초**, debug 작성·인코딩은
**44.569초**, 전체 OBJ/수치 후검사는 **77.050초**다.
ovrtx `step + output readback` 자체는 평균 **0.110초/frame**, 합계 **19.991초**다.
첫 프레임 초기화 비용이 포함된다. 이 값은 전용 benchmark 환경의 성능 보장이 아닌 이 실행의 계측이다.

## 재현 명령

저장소 root에서 실행한다. 기존 release preset은 OpenVDB core와 CUDA가 켜져 있다.
아래 Python 환경은 NumPy, Pillow, matplotlib, pxr/USD, ovrtx, ovstage를 포함한다.

```bash
cmake --preset release
cmake --build build/release --target \
  ex_mesh_to_sdf_fluid_scene_cuda ex_mesh_to_sdf_fluid_surface \
  ex_mesh_to_sdf_fluid_scene_verify -j 3

EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
PY=/tmp/fluid-render-venv/bin/python

/snap/bin/blender -b --python-exit-code 1 \
  --python "$EX/scene/export_character.py" -- \
  --input "$HOME/Downloads/Arms Hip Hop Dance.fbx" \
  --output "$EX/output/character"

$PY "$EX/scene/pipeline.py" "$EX/scene/low.json"
$PY "$EX/scene/pipeline.py" "$EX/scene/profile.json"
$PY "$EX/scene/pipeline.py" "$EX/scene/final.json"

# Cache를 재사용하는 후처리와 검사
$PY "$EX/scene/pipeline.py" "$EX/scene/final.json" --stages mesh,render,debug,validate
$PY "$EX/scene/pipeline.py" "$EX/scene/final.json" --stages verify
$PY "$EX/scene/verify_restart.py"
$PY "$EX/scene/report_scene.py"

# 같은 설정으로 마지막 checkpoint부터 이어서 계산
$PY "$EX/scene/pipeline.py" "$EX/scene/final.json" --stages simulate --resume
```

다른 FBX는 exporter의 `--input`, 다른 bake cache는 pipeline의 `--character`로 교체한다.
Simulation h, meshing h, ppc, 최대 dt, whitewater rate는 JSON의 독립 항목이다.
`checkpoint.bin`은 같은 빌드/설정의 local binary restart이고 CSV를 restart로 오인하지 않는다.

## 산출물과 남은 한계

- `output/character/`: 원본 FBX/Blender, 660 OBJ, binary/NumPy sequence, metadata, pose 이미지.
- `output/scene_final/frame_*.csv`: 181 fluid cache, 별도 whitewater 및 blocks CSV.
- `output/scene_final/frame_*_obstacle.grid`: blind data를 포함한 원래 MeshToSDF buffer.
- `output/scene_final/surface/`: 181 water OBJ와 렌더용 foam 복사본, `meshing.csv`.
- `output/scene_final/scene.usdc`, `render/`, `dance_water.mp4`: 최종 3D scene과 영상.
- `output/scene_final/debug/`, `debug.mp4`, `whitewater_debug.png`: 확대 표시를 포함한 진단용 뷰.
- `metrics.csv`, `validation.json`, `pipeline_times.json`, `render/timings.json`: 모든 측정값.

Pressure 자유표면은 여전히 입자 occupancy 기반의 1차 조건이다. 정교한 ghost-fluid/cut-cell,
surface tension, 기하학적 volume correction, bubble은 구현하지 않았다. SDF 해상도보다 작은
부품은 pressure에서 근사하며 triangle 기반 입자 접촉으로 보완한다. Mesh 부피에는 최대 약
14.1%의 축소가 있고, 부피 flicker 검사는 국소적 flicker 부재의 증명이 아니다.
폼의 render-only 표면 보정 최대값은 0.04423 m이며 원래 simulation
상태를 바꾸지 않는다. Secondary는 시각 효과이고 실제 액체 질량으로 세지 않는다.

최종 renderer는 제공된 FBX의 uniform untextured material을 변환한다. 다른 FBX의 복잡한
material graph를 전부 자동 변환하는 범용 importer는 아니다. 원본 데이터는 보존한다.
