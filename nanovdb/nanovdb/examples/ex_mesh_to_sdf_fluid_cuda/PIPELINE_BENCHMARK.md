# Full pipeline benchmark — 2026-10-10

현재 노트북에서 원본 체크포인트를 복사해 **8.7–8.8초, 3개 출력 프레임
(262–264)**을 실제로 계산하고, meshing → USD → ovrtx → PNG → H.264까지
순차 실행했다. 총 1046.689초, **프레임당 348.896초**다.
검증용 영상 decode 시간은 별도 0.101초다.

가장 큰 단일 작업은 CPU의 입자 이웃 탐색·PCA·kernel 구성이다.
GPU simulation에서는 이번 구간의 whitewater가 가장 크고, 전체 10초 기록에서는
캐릭터 접촉 처리가 더 크다. 기존처럼 simulation과 CPU meshing을 streaming으로
겹치면, 이번 구간의 처리량을 제한하는 단계는 simulation이다.

## 측정 조건과 범위

- GPU: NVIDIA RTX PRO 3000 Blackwell Generation Laptop GPU, 580.178.04, 12227 MiB, [N/A].
- CPU: Intel Core Ultra 7 265H, 16 logical CPUs. 기존 powersave 정책을 유지했다.
- Simulation: 384×384×288, h=0.008333333333333333 m, float/MGPCG, 8 ppc.
- 입자: 13,001,881–13,070,668.
- 419 substeps, 평균 139.67 substeps/output frame,
  평균 dt=0.000238663 s. 30 fps의 영상 프레임과 solver substep을 구분한다.
- Mesh: h=0.00625 m, iso=0.3, support=2.4, smoothing=0.12,
  dilation/half-strength mean-curvature/erosion radius=0.25 voxel, PCA threads=4.
- Render: 1600×1200, 96 samples, foam render radius ×0.7, spray ×0.8.
- Emitter, 초기 pool, 캐릭터 animation, 물리 계수, pressure tolerance와 라이브러리 코드는 유지했다.
  복사된 benchmark config의 종료 시각만 8.8초로 설정했다.
- Simulation과 meshing executable은 기존 release binary이며 SHA256은 `benchmark.json`에 있다.
  예제 renderer에는 계측과 0이 아닌 시작 프레임의 FFmpeg 입력 지원을 추가했다.
- 원본 cache/checkpoint/metrics/settings 및 MeshToSDF SHA256 보존 검사를 통과했다.
  새로운 데이터는 `.gitignore`의 `output/` 아래에 있다.

## 프레임당 전체 비용

| 단계 | 초/frame | 전체 비중 |
|---|---:|---:|
| Simulation + cache/checkpoint | 197.111 | 56.5% |
| CPU surface reconstruction + export | 137.718 | 39.5% |
| USD + ovrtx + PNG + H.264 | 14.068 | 4.0% |
| 합계 | **348.896** | 100% |

이는 단계별 순차 실행의 프레임당 비용이다. 기존 streaming 실행에서는 CPU meshing이
simulation과 겹치므로 두 시간을 전체 wall time으로 그대로 더하면 안 된다.
이번 분리 측정값으로 이상적인 steady-state simulation/meshing 처리량은
max(197.1, 137.7)=197.1초/frame 정도가 기준이고, 실제 겹친 실행은 CPU/GPU 전력,
메모리와 I/O 경쟁으로 달라진다. 렌더링은 GPU를 쓰므로 simulation과 별도 예약하는
현재 작업 방식도 고려해야 한다. 3프레임 평균에는 각 프로세스 시작 비용이 분산되어 있다.
A6000 또는 multi-GPU에서 측정한 값은 아니다.

## Simulation 내부

다음은 동기화된 단계별 wall timer다. 독점 kernel 시간이나 하드웨어 counter는 아니다.

| 단계 | 초/output frame |
|---|---:|
| Births + update/collision + compaction + diagnostics | 46.466 |
| Pressure assembly + MGPCG + projection | 36.112 |
| 6-layer extrapolation + G2P/advection | 30.919 |
| Pre/post particle contact + contact checks | 25.638 |
| Fluid classification + P2G + normalize/gravity | 20.600 |
| Obstacle cells/faces | 10.003 |
| CSV, obstacle/block cache, checkpoint write | 9.130 |
| Sparse topology | 3.463 |
| Character evaluate/BVH refit/upload + MeshToSDF | 3.250 |
| Emitter/particle management + cache staging | 0.418 |
| 분류되지 않은 wall time: startup, diagnostics/sync/allocations outside timers | 11.112 |

Pressure 내 MG setup은 1.484초/frame,
MG solve는 34.101초/frame이며 **pressure 합계에 포함된다**.
평균 PCG 반복은 12.95회다.
현재 timer가 구분하지 않는 비용을 임의로 특정 kernel에 귀속하지 않았다.
예를 들어 G2P와 extrapolation, contact correction과 독립 검사,
whitewater source와 secondary update의 개별 kernel 비율은 후속 세부 계측 대상이다.
CPU user time에는 CUDA 동기화 대기가 포함될 수 있어 CPU 연산 병목의 증거로 쓰지 않았다.

## CPU surface reconstruction

| 단계 | 초/frame |
|---|---:|
| Particle CSV + obstacle cache read/parse | 10.551 |
| Spatial bins + neighbors + covariance/PCA + temporal smoothing/kernel shapes | 114.552 |
| Anisotropic scalar FloatGrid construction | 8.935 |
| Solid/floor/side clipping | 0.208 |
| Reference contour + levelSetRebuild + dilate/meanCurvature/erode | 1.980 |
| Final VolumeToMesh + mesh conversion/volume calculations | 0.033 |
| OBJ/meshbin output + foam surface projection/CSV | 0.782 |
| Cleanup/startup outside phase timers | 0.677 |

PCA 범주가 meshing 단계 wall time의 83.2%다.
이는 eigenvalue 계산만의 시간이 아니다. 각 입자가 27개 공간 bin에서 이웃을 모으고,
가중 covariance와 고유분해, kernel 크기와 방향을 계산하는 전체 구간이다.
`VolumeToMesh`와 SDF filter를 우선 최적화할 근거는 작다.
CSV read는 OS cache의 영향을 받으며 여기서는 방금 출력한 파일을 읽었다.

짧은 benchmark meshing은 첫 프레임에서 covariance history가 비어 있고 이후 두
프레임에서만 history를 누적한다. 최종 원본 영상의 temporal state를 재현한 검사는 아니다.
원본의 4-thread, warm-history 프레임 230–300에서 PCA는 평균
109.339초/frame,
meshing phase 합계는 132.557초/frame이었다.
따라서 원본 기록에서도 동일한 주요 병목이 확인된다. 두 구간은 장면/동시 실행
조건이 달라 속도 개선 비율로 비교하지 않는다.

## 렌더링과 인코딩

| 단계 | 초/frame, 3프레임 평균 |
|---|---:|
| USD authoring/save | 1.222 |
| Renderer creation + stage load | 1.169 |
| USD time update | 0.025 |
| Renderer reset/step (including its scene work) | 10.674 |
| LdrColor map/readback | 0.262 |
| PNG output | 0.117 |
| H.264 encode | 0.067 |

3프레임 모두 converged, progression 96–97이었다. 전체 영화에선 stage load/startup이
301프레임에 분산된다. 기존 301프레임 smaller-whitewater 렌더의 author/output/encode 포함
평균은 3547.285/301=11.785초/frame으로, 짧은 클립의 14.068초/frame과 구분한다.
마지막 대표 이미지를 직접 확인했고 인코딩 영상은 전체 decode 및 frame count 검사를 통과했다.

## 메모리

| 단계 | 관측 GPU 최대 (GiB, NVML v1 total used) | CPU process 최대 RSS (GiB) |
|---|---:|---:|
| simulate | 3.170 | 2.049 |
| mesh | 0.459 | 6.247 |
| render | 3.980 | 4.680 |

GPU는 100ms 간격의 NVML 샘플이며 allocation-exact peak가 아니다.
이 드라이버의 NVML v1 used에는 reserved 영역도 포함된다. 작업 후 같은 시점에
`nvidia-smi`는 used=16 MiB / reserved=455 MiB,
NVML v1은 used=470.625 MiB를 보고했다. CPU mesher가 GPU를 사용한 것으로
0.459 GiB의 baseline을 해석하면 안 된다. Simulation 관측 최대 3245.625 MiB에서
baseline 469.5625 MiB를 빼면 약 2.711 GiB 증가분이다.

CPU meshing 최대 RSS는 6.247 GiB다. 입자 수에 비례하는 neighbor/shape/history
자료가 커지므로 큰 VRAM의 GPU로 옮길 때 host RAM도 함께 확인해야 한다.
Renderer RSS는 3프레임 USD에 대한 수치이며 301프레임 전체 USD의 최대 RAM을
대표하지 않는다. GPU와 CPU peak는 서로 다른 시점의 값이므로 합산하지 않는다.

## 전체 10초 기록과 최적화 우선순위

짧은 구간에서 whitewater가 GPU simulation의 가장 큰 항목이지만,
캐릭터 자세에 따른 접촉 비용 변화가 크다. 기존 완성된 300개 simulation output
구간을 누적하면 contact는 평균 53.445초/frame, p95 106.104초/frame,
최대 130.860초/frame이다. 이 기록은 여러 continuation 및 당시의 CPU meshing
동시 실행 조건을 포함하므로 새 3프레임의 독립 성능 반복 측정으로 취급하지 않는다.

다음은 코드 검토로 확인한 후보이며, 아직 구현하거나 속도 향상을 실측한 결과는 아니다.

1. **GPU whitewater의 반복 grid lookup 축소.** 현재 birth kernel이 전체 약 1,300만
   APIC 입자에 density와 여섯 방향의 density sampling을 수행한다.
   Secondary 입자가 약 5만 개여도 source 비용은 APIC 입자 수에 따라 커진다.
   Cell density/gradient의 동등한 재사용, 후보의 보수적 분류와 batch 처리를 검토한다.
   생성 rate/수명/foam·spray 계수와 충돌 검사는 유지한다.
2. **Fluid 쪽 character contact의 보수적 후보 처리와 중복 질의 축소.**
   Pre/post contact와 triangle parity/nearest queries가 각 substep마다 반복된다.
   이미 root AABB culling은 존재하므로 그보다 세밀한 culling이 필요하다.
   SDF inactive interior와 독립 관통 검사 의미를 보존하며 기존 MeshToSDF는 재사용한다.
3. **APIC 전송/velocity extrapolation의 메모리 접근 최적화.** P2G와
   extrapolation/G2P 합계가 이번 측정에서 약 51.5초/frame이다.
   입자 공간 정렬과 tile별 처리 등을 별도 정확성 검증과 함께 검토한다.
4. **CPU neighbor/PCA의 자료 배치, 임시 할당과 병렬성 개선.** 순차 프레임
   latency에서 가장 큰 단일 작업이다. GPU 이관은 여유 VRAM과 transfer 비용을
   먼저 측정해야 한다. 입자 smoothing, kernel 정의, iso/filter 설정은 유지한다.
5. **캐시 I/O의 binary 경로.** 현재 출력 약 9.13초와 읽기/parse 약 10.55초/frame이다.
   큰 해상도에서는 시간 외에도 디스크 용량이 중요하다. APIC restart용 상태와
   meshing용 입력 필드를 구분하고, 원래 필드 precision을 보존하는 경로가 후보다.
6. **MGPCG 세부 개선.** Pressure는 여전히 큰 항목이지만 현재 hierarchy setup은
   1.48초/frame으로 작다. 반복 solve, 전처리기와 finest-level 접근을 세부 계측한 뒤
   개선한다. Hierarchy 재사용만으로 전체 병목이 해결되지는 않는다.

기존처럼 simulation과 meshing이 겹치는 실행의 완료 시간을 줄이는 데에는
simulation 측 최적화가 우선이다. CPU PCA 개선은 latency와 host 자원, 더 높은
해상도에서 mesher가 뒤처지는 상황에 중요하다. 렌더링 전체는 이번 순차 비용의
약 4%이며, MeshToSDF를 포함한 character build는 약 0.9%다.

## 검증

- 419 substeps에서 fluid/secondary 잔여 관통, 누락 stencil, 질량 원장 오류 0.
- Pressure true residual의 기존 absolute-or-relative 기준 모두 통과.
- 최대 relative residual 1.99597e-05.
- 최대 moving-wall flux divergence 7.46549e-05 (기준 2e-3).
- 최대 wall flux error 1.19204e-07 (기준 2e-5).
- 최대 inward contact normal error 6.69187e-07 (기준 2e-5).
- 3프레임 렌더 수렴, H.264 1600×1200 / 30fps / 3프레임, 전체 decode 통과.
- 원본 파일 hash 검사 통과. 이 단계에서는 최적화나 라이브러리 변경을 적용하지 않았다.

## 재현 명령과 산출물

저장소 루트에서 실행한다. 출력 경로는 새 디렉터리여야 한다.
이 checkpoint는 로컬 생성 데이터이므로 Git에 올리지 않으며,
다른 컴퓨터에서는 동일 설정의 checkpoint를 별도로 준비해야 한다.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
RUN=$EX/output/scene_clear_shower_384_float_12s
BENCH=$EX/output/benchmark_pipeline_repeat
python3 "$EX/scene/benchmark_pipeline.py" \
  --cache "$RUN" \
  --checkpoint "$RUN/restarts/parallel_pca/checkpoint.bin" \
  --output "$BENCH" --frames 3
"$EX/output/render-venv/bin/python" "$EX/scene/report_pipeline_benchmark.py" "$BENCH"
```

- [비용 그래프](output/benchmark_pipeline_384_20261010/pipeline_costs.png)
- [벡터 그래프](output/benchmark_pipeline_384_20261010/pipeline_costs.svg)
- [요약/검증 JSON](output/benchmark_pipeline_384_20261010/summary.json)
- [명령·환경·binary hash·단계 wall time](output/benchmark_pipeline_384_20261010/benchmark.json)
- [프레임별 CSV](output/benchmark_pipeline_384_20261010/frame_costs.csv)
- [벤치마크 영상](output/benchmark_pipeline_384_20261010/cache/dance_water_benchmark.mp4)
- [대표 이미지](output/benchmark_pipeline_384_20261010/cache/render_benchmark/frame_000264.png)

각 단계의 `*_resources.txt`, `*_memory.csv`, 로그와 원시 metrics도 같은 출력 폴더에 있다.
실제 checkpoint 복사/사전 hash 준비 및 보고서 작성 시간은 simulation 비용에서 제외했다.
FBX baking은 이미 완료된 asset preparation이므로 이번 per-frame benchmark에서 제외했다.
