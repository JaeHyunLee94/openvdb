# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
"""Report the twelve-second prefilled basin and measured visible white foam."""

import csv
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output/scene_wet_pool"
OLD = ROOT / "output/scene_pool_complete"


def table(path):
    return list(csv.DictReader(path.open()))


def main():
    v = json.loads((OUT / "validation.json").read_text())
    pool = json.loads((OUT / "pool_validation.json").read_text())
    settings = json.loads((OUT / "settings.json").read_text())
    restart = json.loads((ROOT / "output/wet_pool_diagnosis/restart/result.json").read_text())
    visibility = [
        json.loads((OUT / "foam_visibility" / f"frame_{i:06d}.json").read_text())
        for i in (180, 360)
    ]
    assert v["pass"] and pool["pass"] and restart["pass"] and all(q["pass"] for q in visibility)
    m, frames, levels = (
        table(OUT / "metrics.csv"),
        table(OUT / "frames.csv"),
        table(OUT / "pool_levels.csv"),
    )
    mesh = table(OUT / "surface/meshing.csv")
    video = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,nb_read_frames,duration",
                "-of",
                "json",
                str(OUT / "dance_water.mp4"),
            ]
        )
    )["streams"][0]
    assert int(video["nb_read_frames"]) == 361 and video["r_frame_rate"] == "30/1"
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    montage = Image.new("RGB", (1600, 1260), (20, 25, 30))
    draw = ImageDraw.Draw(montage)
    for n, frame in enumerate((0, 90, 180, 360)):
        im = Image.open(OUT / "render" / f"frame_{frame:06d}.png").convert("RGB")
        assert np.asarray(im).std() > 5
        im.thumbnail((800, 600))
        x, y = (n % 2) * 800, (n // 2) * 630
        montage.paste(im, (x, y + 30))
        draw.text((x + 12, y + 3), f"Prefilled basin | t={frame/30:.1f}s", font=font, fill="white")
    montage.save(OUT / "representative_frames.jpg", quality=95)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(OLD / "dance_water.mp4"),
            "-i",
            str(OUT / "dance_water.mp4"),
            "-filter_complex",
            "[0:v]scale=960:720,drawtext=text='Before - dry start':x=20:y=20:fontsize=26:fontcolor=white[a];"
            "[1:v]scale=960:720,drawtext=text='After - shallow water and foam':x=20:y=20:fontsize=26:fontcolor=white[b];"
            "[a][b]hstack=inputs=2:shortest=1[v]",
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(OUT / "comparison_first_6s.mp4"),
        ],
        check=True,
    )
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.1), constrained_layout=True)
    t = [float(q["time"]) for q in frames]
    ax[0].plot(t, [float(q["foam"]) for q in frames], label="Foam")
    ax[0].plot(t, [float(q["spray"]) for q in frames], label="Spray")
    ax[0].set(xlabel="Time (s)", ylabel="Secondary particles")
    ax[0].legend()
    ax[1].plot(
        [float(q["time"]) for q in levels],
        [float(q["bed_equivalent_depth_m"]) * 100 for q in levels],
        label="Bed volume / area",
    )
    ax[1].plot(
        [float(q["time"]) for q in levels],
        [float(q["surface_height_median_m"]) * 100 for q in levels],
        label="Particle height proxy",
    )
    ax[1].set(xlabel="Time (s)", ylabel="Depth / height (cm)")
    ax[1].legend(fontsize=8)
    ax[2].plot(
        [float(q["time"]) for q in levels],
        [
            int(q["rising_initial_pool_particles"]) * settings["particle_volume"] * 1000
            for q in levels
        ],
    )
    ax[2].set(xlabel="Time (s)", ylabel="Rising prefill water above initial surface (L)")
    for x in ax:
        x.grid(alpha=0.25)
    fig.savefig(OUT / "water_and_foam.png", dpi=180)
    plt.close(fig)
    summary = {
        "video": video,
        "visibility": visibility,
        "validation": v["details"],
        "pool": pool,
        "rising_prefill_volume_peak_l": max(int(q["rising_initial_pool_particles"]) for q in levels)
        * settings["particle_volume"]
        * 1000,
        "prefill_particle_max_height_m": max(float(q["initial_pool_max_height_m"]) for q in levels),
    }
    (OUT / "scene_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    perf = "\n".join(
        f"| {k} | {q['mean']:.3f} | {q['sum']/1000:.2f} |"
        for k, q in v["performance"].items()
        if k.endswith("_ms")
    )
    mp = "\n".join(
        f"| {k} | {q['mean']:.3f} | {q['sum']/1000:.2f} |"
        for k, q in v["meshing_performance"].items()
    )
    visible = "\n".join(
        f"| {q['frame']/30:.0f} s | {q['white_contribution_pixels']} | {q['floor_white_pixels']} |"
        for q in visibility
    )
    text = f"""# 12초, 얕은 초기 물층과 흰 거품

`scene/wet_pool.json`과 `output/scene_wet_pool`에 새 장면을 별도로 만들었다.
기존 6초 캐시/영상은 보존했다. 변경은 예제 폴더 안에 한정하며 라이브러리와 ovrtx SDK는 수정하지 않았다.

## 변경

- Simulation 0–12초, 30 fps, 양 끝을 포함한 361프레임. 영상 길이는 12.033초다.
- 바닥에 **6.4 cm** 깊이의 물을 먼저 채웠다. Particle volume은 h³/ppc로 유지하고,
  초기 속도와 affine C는 0이다. SDF clearance 및 triangle 내부 검사를 통과한 입자만 남긴다.
  초기 pool 입자는 **{settings['initial_pool_particles']:,}개 / {settings['initial_pool_volume']*1000:.3f} L**다.
  h=32 mm, ppc=8에서 입자 간격은 16 mm이며 초기 물층은 네 입자 층이다.
- Emitter 위치·반경·속도와 닫힌 domain은 유지했다. 유량은 {settings['flow_m3_s']*1000:.6f} L/s,
  배출은 0이다. 물리적인 viscosity/마찰은 추가하지 않았다.
- 이전에는 spray가 foam으로 변해도 짧은 spray 수명을 유지했다. 이제 전환 시 foam 크기와
  수명을 부여한다. 이 동작을 독립 회귀 검사로 확인했다. Foam은 생성 시 및 전환 후 약
  **1.98–5.04초** 유지하며, 직접 생성된 foam 반경은 **6–10.5 mm**다.
- Whitewater 생성률은 120,000 → **360,000 /(m³·s)**. 기존 표면 근처 가속도/충돌/vorticity
  source를 그대로 사용하며, 정적인 물 전체에 무조건 거품을 뿌리지는 않는다.
  Secondary는 P2G·압력·유체 질량에 들어가지 않는다. 전환된 foam도 같은 SDF/벽 충돌을 적용한다.
- Foam은 중성 흰색 diffuse 재질(albedo 0.98, roughness 0.65)과 32-triangle 구 형태로 렌더링한다.
  기존의 작은 8-triangle 팔면체보다 구의 투영 면적을 잘 표현한다. 카메라 거리로 크기를 부풀리지 않는다.
- 새 pool 장면의 meshing isovalue는 **0.2**이다. 깊어진 물층의 입자 분포에서 기존 0.4가
  표면 부피를 작게 복원하는 경향을 확인하고, 같은 입자로 비교한 뒤 조정했다.
  11.67초 대표 프레임의 부피비는 isovalue 0.3에서 0.796으로 실패했고, 0.2에서 0.841로 개선됐다. Kernel 적분/입자 질량은 그대로이며,
  전체 프레임이 원래의 부피와 flicker 기준을 통과해야 한다. Simulation에는 영향을 주지 않는다.
  거친 profile(h=80 mm, mesh h=25 mm)는 isovalue 0.3에서 부피비 1.222–1.232로 실패했으므로,
  검증을 통과한 0.4를 유지한다. 해상도가 다른 두 표면 재구성 설정은 별도로 검증했다.
- `FLUID004` checkpoint는 초기 물층 수량/깊이와 foam 크기·수명·생성률 설정을 저장한다.
  다른 초기 조건으로 재시작하는 것은 거부한다.

초기 물이 있다고 반드시 흰 거품이 생기는 것은 아니다. 실제 유체 충돌로 생성한 secondary를
수면 근처에 유지하고, 최종 물 렌더에서 충분한 흰색 대비가 있는지 별도로 확인했다.

## 물리 및 시각 검증

{v['steps']:,} substep의 pressure/유량·관통·질량·stencil 검증과 361프레임의 표면 검증: **PASS**.

| 항목 | 결과 |
|---|---:|
| 초기 전체 액체 | {pool['initial_volume_m3']*1000:.3f} L |
| 최종 전체 액체 | {v['final_material_volume']*1000:.3f} L / {int(v['final_particles']):,} particles |
| 최종 바닥 25 cm 아래 액체 | {pool['final']['bed_volume_m3']*1000:.3f} L |
| 최종 부피/바닥 면적 등가 깊이 | {pool['final']['bed_equivalent_depth_m']*100:.3f} cm |
| 최종 타일별 입자 높이 지표 | {pool['final']['surface_height_median_m']*100:.3f} cm |
| 초기 물층 출신 입자의 상승 물량 최대값 | {summary['rising_prefill_volume_peak_l']:.3f} L |
| 그 입자들의 최대 도달 높이 | {summary['prefill_particle_max_height_m']:.3f} m |
| 최종 foam / spray | {m[-1]['foam']} / {m[-1]['spray']} |
| Secondary 최대 동시 수 | {int(v['max_whitewater']):,} |
| 전체 secondary 생성 수 | {m[-1]['ww_spawned']} |
| 최대 pressure relative residual | {max(float(q['residual']) for q in m):.3e} |
| 최대 moving-wall flux error | {v['details']['moving_wall_flux']['maximum']:.3e} |
| 최대 접촉 상대 법선 속도 오차 | {v['details']['contact_inward_relative_normal']['maximum']:.3e} m/s |
| 최대 flux divergence | {v['details']['weighted_flux_divergence']['maximum']:.3e} s⁻¹ (기준 1e−6) |
| 유체 잔여 관통 | {v['details']['remaining_penetration']['maximum']:.0f} |
| Secondary 관통 깊이 | {v['details']['whitewater_penetration']['maximum']:.3e} m |
| 누락 stencil | {v['details']['missing_stencils']['maximum']:.0f} |
| 미해상도 접촉 fallback 비율 최대 | {v['details']['unresolved_contact_fraction']['maximum']:.4%} |
| Mesh/material volume 범위 | {v['details']['reconstruction']['mesh_volume_ratio_range']} |
| 인접 정규화 mesh 부피 변화 최대 | {v['details']['reconstruction']['max_adjacent_normalized_volume_change']:.3%} |

상승 물량은 초기 pool 입자의 persistent ID를 추적해 `y > 초기 깊이+h`, `vy > 0.5 m/s`인
입자 부피를 센다. 파도/물기둥의 상승 지표이며 모두 분리된 물방울이라는 뜻은 아니다.
높이는 기존 16 cm 타일의 particle y p90+반 간격으로 측정하며 실제 level set과 구분한다.
초기 물층을 가진 장면의 축적 검사는 기존 물에 더해 `0.8 Q max(t−2,0)` 이상이 바닥에 모였는지 확인한다.
Pressure residual 기준, 관통 기준, [0.8,1.2] mesh 부피 기준은 유지했다.

최종 물·캐릭터·spray·조명은 동일하게 두고 **foam만 숨긴 영상과 보이는 영상**을 비교했다.
RGB 최솟값 >120, 채널 차이 <65, 휘도 증가 >30인 픽셀을 센다. 전체 프레임의 0.2% 이상,
바닥 ROI에서는 전체 프레임의 0.1% 이상을 기준으로 설정했다. 간접 반사 영향도 포함되는
시각 기여도 검사이며 물리 정확성 검사를 대신하지 않는다. 이미지도 직접 확인했다.

| 시간 | 흰색 기여 픽셀 | 바닥 ROI 기여 픽셀 |
|---|---:|---:|
{visible}

재시작 비교에서 APIC x/v/C 최대 차이는 {restart['raw_particle_x_v_C_max_difference']:.3e}였다.
Secondary 위치 차이는 {restart['whitewater_position_error_m']:.3e} m, 속도 차이는
{restart['whitewater_velocity_error_m_s']:.3e} m/s였다. 최초의 2e−8 전체 상태 기준은 통과하지 못했다.
재시작 없는 동일 연속 실행을 반복한 대조군에서도 {restart['continuous_repeat_whitewater_difference']:.3e}의 차이가
나타났다. P2G floating-point atomic 순서와 비선형 표면 보정의 영향을 구별하기 위해
연속 반복 오차의 두 배 이내이고, 동시에 위치 8e−6 m(1e−4 voxel), 속도 1e−5 m/s 이내인지 확인했다.
ID·종류·반경·수명은 일치했다. APIC의 기존 2e−8 기준은 유지했다.

## 재현

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
PY=/tmp/fluid-render-venv/bin/python
cmake --build build/release --target ex_mesh_to_sdf_fluid_scene_cuda ex_mesh_to_sdf_fluid_surface ex_mesh_to_sdf_fluid_water_verify -j3
build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_water_verify "$EX/output/character"
$PY "$EX/scene/pipeline.py" "$EX/scene/wet_pool_profile.json" --stages simulate,mesh,render,validate
$PY "$EX/scene/verify_restart.py" --output "$EX/output/wet_pool_diagnosis/restart" --initial-depth .064 --foam-radius-scale 1.5 --foam-life-scale 1.8
$PY "$EX/scene/pipeline.py" "$EX/scene/wet_pool.json"
$PY "$EX/scene/verify_white_foam.py" "$EX/output/scene_wet_pool" --frame 180
$PY "$EX/scene/verify_white_foam.py" "$EX/output/scene_wet_pool" --frame 360
$PY "$EX/scene/validate_scene.py" "$EX/output/scene_wet_pool" --workers 4
$PY "$EX/scene/report_wet_pool.py"
```

진단용 표면은 simulation과 CPU meshing을 병행해 만들었다. 최종 isovalue 0.2 재구성은
독립된 프레임 구간을 CPU에서 병렬 처리하고 합쳤다. 구간 경계의 normalized volume change는
앞 프레임의 부피비로 다시 계산했다. PCA covariance는 이전 프레임 30%를 사용하므로,
각 분할 경계의 20프레임 앞부터 다시 계산해 경계 이후 20프레임을 교체했다.
역사 오차의 감쇠율은 0.3²⁰이며, 원래 구간으로 돌아가는 111/201/291프레임의 triangle 연결은
동일하고 vertex 차이는 최대 3.73e−9 m였다(`wet_pool_diagnosis/temporal_seams.json`).
위 pipeline 명령은 분할 없이 시간 필터를 연속 적용한다.
Mesher 마지막 인자 `WAIT_FOR_FRAMES=1`은
atomic checkpoint의 nextFrame을 확인해 출력이 모두 닫힌 프레임만 읽는다. 그 대기 시간은
각 frame의 meshing 계측에 포함하지 않는다. 명령은 다음과 같다(simulation을 별도 실행 중에 사용).

```bash
build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_surface "$EX/output/scene_wet_pool" "$EX/output/scene_wet_pool/surface" .01 .000004096 .016 .2 2.4 .12 0 360 1 1 1
```

OBJ를 그대로 저장하고, 렌더러 연결에는 같은 float32 정점/int32 삼각형의 `.meshbin` 캐시를 추가했다.
이는 예제의 USD 변환기가 읽는 형식이다. ovrtx 자체의 입력 형식/코드는 바꾸지 않았다.
전체 OBJ의 watertight/winding 검사와 binary/OBJ 값 비교를 수행한다.

## 시간과 한계

| 단계 | substep 평균 ms | 전체 s |
|---|---:|---:|
{perf}

| CPU meshing | frame 평균 ms | 전체 s |
|---|---:|---:|
{mp}

초기 구간에 짧은 진단 GPU 실행을 병행했으며, meshing은 CPU에서 병행했다.
측정값은 이번 작업의 실제 wall-clock 계측이며 단독 실행 benchmark가 아니다.
GPU 사용량의 관측 최대값은 {v['performance']['gpu_used_mb']['max']:.1f} MiB다.
파일 전송·출력·meshing·렌더 비용은 solver와 별도 기록한다.
프로세스 시간은 `pipeline_times.json`, renderer frame 시간은 `render/timings.json`에 있다.

Foam의 크기와 생성률은 눈으로 확인할 수 있는 secondary 효과 설정이며 기포의 미시 물리 모델이 아니다.
유체 grid는 32 mm이므로 매우 얇은 물막/작은 splash는 해상도 한계가 있다.
실제 domain 측면은 전체 높이까지 닫혀 있고 렌더에는 아래 30 cm만 표시한다. Overflow 모델은 없다.
부피와 프레임 변화 검증은 국소적인 모든 flicker나 실제 물과의 수렴을 증명하지 않는다.

## 결과

- [12초 최종 영상](output/scene_wet_pool/dance_water.mp4)
- [기존 장면과 첫 6초 비교](output/scene_wet_pool/comparison_first_6s.mp4)
- [0/3/6/12초 대표 이미지](output/scene_wet_pool/representative_frames.jpg)
- [거품·수위·상승 물량 그래프](output/scene_wet_pool/water_and_foam.png)
- [입자/obstacle 디버그 영상](output/scene_wet_pool/debug.mp4)
- [6초 foam 가시성 비교](output/scene_wet_pool/foam_visibility/comparison_000180.jpg)
- [12초 foam 가시성 비교](output/scene_wet_pool/foam_visibility/comparison_000360.jpg)
- `output/scene_wet_pool/`: 전체 simulation cache, `surface/`: OBJ+binary+foam cache,
  `render/`: 361 PNG, `scene.usdc`: 3D animation, `validation.json`, `pool_validation.json`: 측정값.
"""
    (ROOT / "WET_POOL_RESULTS.md").write_text(text)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
