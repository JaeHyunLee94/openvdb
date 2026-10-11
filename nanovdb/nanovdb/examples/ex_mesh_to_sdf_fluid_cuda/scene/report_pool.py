# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
"""Measured drainage/retention comparison; preserves both simulation caches."""

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
OLD = ROOT / "output/scene_water"
NEW = ROOT / "output/scene_pool_complete"


def table(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def main():
    val = json.loads((NEW / "validation.json").read_text())
    pool = json.loads((NEW / "pool_validation.json").read_text())
    restart = json.loads((ROOT / "output/pool_diagnosis/restart/result.json").read_text())
    assert val["pass"] and pool["pass"] and restart["pass"]
    settings = json.loads((NEW / "settings.json").read_text())
    oldsettings = json.loads((OLD / "settings.json").read_text())
    oldm, newm = table(OLD / "metrics.csv"), table(NEW / "metrics.csv")
    meshes = table(NEW / "surface/meshing.csv")
    levels = table(NEW / "pool_levels.csv")
    vp = settings["particle_volume"]
    olddrained = int(oldm[-1]["drained"]) * oldsettings["particle_volume"]
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
                str(NEW / "dance_water.mp4"),
            ]
        )
    )["streams"][0]
    assert int(video["nb_read_frames"]) == val["frames"] and video["r_frame_rate"] == "30/1"
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    montage = Image.new("RGB", (1600, 3 * 630), (18, 22, 28))
    draw = ImageDraw.Draw(montage)
    for row, frame in enumerate((36, 90, 180)):
        for col, (folder, label) in enumerate(
            ((OLD, "Before: perimeter drain"), (NEW, "After: closed basin"))
        ):
            im = Image.open(folder / "render" / f"frame_{frame:06d}.png").convert("RGB")
            assert np.asarray(im).std() > 5
            im.thumbnail((800, 600))
            montage.paste(im, (800 * col, 630 * row + 30))
            draw.text(
                (800 * col + 12, 630 * row + 2),
                f"{label} | t={frame/30:.1f}s",
                font=font,
                fill="white",
            )
    montage.save(NEW / "before_after.jpg", quality=95)
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
            str(NEW / "dance_water.mp4"),
            "-filter_complex",
            "[0:v]scale=960:720,drawtext=text='Before - perimeter drain':x=20:y=20:fontsize=26:fontcolor=white[a];"
            "[1:v]scale=960:720,drawtext=text='After - closed basin':x=20:y=20:fontsize=26:fontcolor=white[b];"
            "[a][b]hstack=inputs=2[v]",
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
            str(NEW / "before_after.mp4"),
        ],
        check=True,
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), constrained_layout=True)
    for rows, label in ((oldm, "Perimeter drain"), (newm, "Closed basin")):
        axes[0].plot(
            [float(r["time"]) for r in rows],
            [float(r["mass_volume"]) * 1000 for r in rows],
            label=label,
        )
    axes[0].set(xlabel="Time (s)", ylabel="Liquid material volume (L)")
    axes[0].legend()
    times = [float(r["time"]) for r in levels]
    axes[1].plot(
        times,
        [float(r["surface_height_median_m"]) * 100 for r in levels],
        label="Tile particle height (p90 median)",
    )
    axes[1].plot(
        times,
        [float(r["bed_equivalent_depth_m"]) * 100 for r in levels],
        label="Bed volume / basin area",
    )
    axes[1].set(xlabel="Time (s)", ylabel="Height / equivalent depth (cm)", xlim=(1.2, 6))
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=0.25)
    fig.savefig(NEW / "accumulation.png", dpi=180)
    plt.close(fig)
    summary = {
        "video": video,
        "old_drained_m3": olddrained,
        "new_drained_m3": int(newm[-1]["drained"]) * vp,
        "pool": pool,
        "restart": restart,
    }
    (NEW / "pool_comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    d, perf = val["details"], val["performance"]
    start, end = pool["height_reference"], pool["final"]
    timings = json.loads((NEW / "pipeline_times.json").read_text())
    timing_rows = "\n".join(
        f"| {k} | {v['mean']:.3f} | {v['sum']/1000:.2f} |"
        for k, v in perf.items()
        if k.endswith("_ms")
    )
    mesh_rows = "\n".join(
        f"| {k} | {v['mean']:.3f} | {v['sum']/1000:.2f} |"
        for k, v in val["meshing_performance"].items()
    )
    report = f"""# 바닥에 물이 쌓이도록 배출 조건 수정

## 원인과 변경

이전 장면은 `y < 0.18 m`이면서 바닥 가장자리에서 14 cm 이내인 입자를 삭제하는
흡수 배출 영역을 사용했다. 인공적인 접선 감쇠를 제거한 후 물이 빠르게 가장자리로
퍼지면서, 6초 동안 **{olddrained*1000:.3f} L**가 배출됐다. 이 장면 설정을 그대로 둔 것이
바닥에 물이 쌓이지 않은 원인이다. 바닥 관통이나 pressure solver의 질량 소실이 아니었다.

- `scene/pool.json`: `drain_enabled: false`. 기존 유입량, APIC, free-slip/contact,
  캐릭터 animation, 해상도, whitewater 설정을 유지한다. 인공 점성/바닥 마찰은 추가하지 않았다.
- 기존 닫힌 pressure/G2P domain 경계를 재사용한다. Secondary는 측면에서 반경만큼
  안쪽으로 이동시키고 바깥으로 향하는 법선 속도만 제거한다. Foam 표면 탐색에서 벽을
  공기로 취급하지 않으며, CPU meshing field와 렌더 foam 위치도 같은 경계에서 제한한다.
- Renderer 입력에는 투명한 테두리를 추가했다. 표시 높이는 아래 30 cm이고,
  실제 계산 영역 측면은 전체 높이 3.2 m까지 닫혀 있다. 유한 높이에서 넘치는 모델은 아니다.
- `mesh_floor_boundary: true`: 바닥 가까이에서 PCA kernel의 법선 방향 분산이
  접선 분산보다 지나치게 작아지지 않도록 보정한다. 바닥에서 멀어질수록 보정을 줄여
  kernel support의 두 배 거리에서 0이 된다. 접선 방향 anisotropy와 공중의 kernels는 유지한다.
  이어서 고체 안의 kernel 부분을 바닥 반대편으로 반사한다. 바닥 half-space에서의 적분은
  원래 정규화 kernel 적분과 같으며, 경계 평면에는 trapezoid 가중치 1/2를 사용해 검증한다.
  입자 위치/속도/질량, isovalue, 실제 유체 운동은 바꾸지 않는다.
- `FLUID003` checkpoint에 배출 설정을 저장해 서로 다른 배출 모드의 재시작을 거부한다.
- 4.65초의 좁은 캐릭터 접촉 부위에서 유체 셀의 위/아래 MAC face가 모두 막혀,
  세로 G2P 속도를 연장할 수 없는 경우를 발견했다. 이 표현되지 않은 성분만
  이전 속도+중력으로 진행하고 C 행을 초기화한 뒤 실제 SDF/triangle 접촉으로 제한한다.
  가로 성분의 projected G2P 값은 보존한다. 열린 face가 있는 성분의 누락은 계속 오류다.
  이 동작과 실제 누락을 구별하는 양성/음성 회귀 검사를 추가했다.
- 변경은 이 예제 폴더 안에 한정한다. 기존 NanoVDB operator와 ovrtx 코드는 수정하지 않았다.
  `output/scene_water`의 이전 결과는 보존한다.

## 측정 결과

6초, {val['frames']}프레임, {val['steps']} substep. 유량 {pool['inflow_m3_s']*1000:.6f} L/s,
초기 물 {pool['initial_volume_m3']*1000:.6f} L, 입자당 부피 {vp*1e6:.3f} mL.

| 항목 | 결과 |
|---|---:|
| 최종 APIC 입자 수 | {end['particles']} |
| 최종 물의 material volume | {end['total_volume_m3']*1000:.3f} L |
| 새 장면 배출량 | {int(newm[-1]['drained'])*vp*1000:.6f} L |
| 유입량 대비 최대 장부 오차 | {pool['mass_error_m3']*1e6:.3f} mL (한 입자 이내) |
| 바닥 25 cm 아래 material volume: 1.2 → 6 s | {start['bed_volume_m3']*1000:.3f} → {end['bed_volume_m3']*1000:.3f} L |
| 같은 영역의 부피/바닥 면적 | {start['bed_equivalent_depth_m']*100:.3f} → {end['bed_equivalent_depth_m']*100:.3f} cm |
| 입자 위치로 측정한 타일별 높이 중앙값 | {start['surface_height_median_m']*100:.3f} → {end['surface_height_median_m']*100:.3f} cm |
| 최종 물이 있는 높이 측정 타일 | {end['wet_probe_tiles']} |
| 최종 foam / spray | {newm[-1]['foam']} / {newm[-1]['spray']} |

높이 측정은 바닥을 16 cm 타일로 나누고, 충돌 중심 반경 65 cm를 제외한 타일의
`particle y p90 + 입자 간격/2`를 사용했다. 파도와 입자 샘플링의 영향을 받는 proxy다.
`volume/area`는 평균 등가 깊이로, 실제 표면 높이와 구분한다. 액체 질량 증가만으로
수위 상승을 판정하지 않고 이 두 값, 입자 영상, 표면 메시를 함께 확인했다.

| 검증 | 최대값 | 기준 |
|---|---:|---:|
| 벽 운동/차단율 포함 flux divergence | {d['weighted_flux_divergence']['maximum']:.3e} s⁻¹ | 1e−6 |
| 움직이는 벽 face flux 오차 | {d['moving_wall_flux']['maximum']:.3e} | 1e−9 |
| 입자 inward normal 속도 오차 | {d['contact_inward_relative_normal']['maximum']:.3e} m/s | 1e−8 |
| 유체 잔여 관통 | {d['remaining_penetration']['maximum']:.0f} | 0 |
| Secondary 관통 깊이 | {d['whitewater_penetration']['maximum']:.3e} m | 1e−7 |
| 누락 stencil | {d['missing_stencils']['maximum']:.0f} | 0 |
| APIC domain 밖 위치 오차 | {pool['max_fluid_bound_error_m']:.3e} m | 1e−7 |
| Secondary 반경 포함 domain 밖 오차 | {pool['max_secondary_bound_error_m']:.3e} m | 1e−7 |
| 추출 mesh의 측면 밖 확장 | {d['mesh_export']['max_side_extension_m']:.3e} m | 1e−5 |

Pressure residual은 매 step `max(1e−12, 2e−8 ||b||)` 기준을 통과했다.
Meshing 부피비 범위 {d['reconstruction']['mesh_volume_ratio_range']}, 인접 프레임 정규화
부피 변화 최대 {d['reconstruction']['max_adjacent_normalized_volume_change']:.3%}.
모든 mesh의 닫힌 edge/winding 검사도 통과했다. 이는 부피 안정성 지표이며 모든 국소 flicker를
배제하는 증명은 아니다. 물리적 입자 장부와 표면 재구성 부피를 별도로 기록한다.
바닥 재구성 보완 전 마지막 mesh 부피비는 0.694695로 실패했다. 보완 후 같은 cache의
마지막 부피비는 {float(meshes[-1]['volume_ratio']):.6f}이다. 반사 전 전체 kernel 적분과
반사 후 바닥 half-space 적분의 최대 상대 차이는
{d['floor_kernel_conservation']['maximum']:.3e} (기준 1e−6)이다.
수조 검증 기준이나 기존 부피 허용 범위 [0.8, 1.2]는 완화하지 않았다.
미해상도 접촉 fallback은 substep당 최대 {max(int(r['unresolved_contact_droplets']) for r in newm)}개,
전체 입자 대비 최대 {d['unresolved_contact_fraction']['maximum']:.4%}였다.
30 fps cache에서 측정한 측면 접촉 입자의 최대 높이는 물
{pool['sampled_max_side_contact_height_m']:.3f} m, secondary
{pool['sampled_max_secondary_side_contact_height_m']:.3f} m다. Substep 사이의 최고점 측정은 아니다.

`verify_water`의 무중력 바닥 전송은 1회/100회 모두 1 m/s를 유지했다.
추가한 secondary 측면 충돌은 바깥 방향 속도를 제거하면서 해석적 접선 속도 오차 0이었다.
차단된 성분의 ballistic/다른 성분의 G2P 혼합 검사는 오차 1e−12 이내였으며,
표현된 성분의 값을 고의로 지운 검사는 누락을 정상 검출했다.
0.4초 checkpoint에서 0.6초까지 재시작한 결과와 연속 실행의 APIC x/v/C 최대 차이는
{restart['raw_particle_x_v_C_max_difference']:.3e}, secondary 차이는
{restart['whitewater_max_difference']:.3e} (기준 2e−8)였다.

## 실행과 비용

설정: fluid h=32 mm, obstacle h=16 mm, mesh h=10 mm, ppc=8,
최대 dt=4 ms + adaptive CFL, whitewater 120,000 /(m³·s), 1600×1200 / 96 spp / 30 fps.

```bash
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
cmake --build build/release --target ex_mesh_to_sdf_fluid_scene_cuda ex_mesh_to_sdf_fluid_surface ex_mesh_to_sdf_fluid_water_verify -j3
build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_water_verify "$EX/output/character"
/tmp/fluid-render-venv/bin/python "$EX/scene/pipeline.py" "$EX/scene/pool_profile.json" --stages simulate
/tmp/fluid-render-venv/bin/python "$EX/scene/verify_pool.py" "$EX/output/scene_pool_profile"
/tmp/fluid-render-venv/bin/python "$EX/scene/verify_restart.py" --output "$EX/output/pool_diagnosis/restart"
/tmp/fluid-render-venv/bin/python "$EX/scene/pipeline.py" "$EX/scene/pool.json" --output "$EX/output/scene_pool_complete"
/tmp/fluid-render-venv/bin/python "$EX/scene/report_pool.py"
```

측정 중 짧은 restart 회귀 검사를 별도 실행했으므로 초기 simulation timing에는 GPU 경쟁이
포함될 수 있다. 다음 값은 실제 이번 실행의 wall-clock 계측이며 단독 실행 benchmark가 아니다.
첫 실행은 4.65초에 검증 실패로 멈췄다. 원본 부분 캐시를 보존하고 복사본의
4.63333초 checkpoint에서 수정 후 재개했다. 수정 전 성공한 구간에는 새 fallback 조건이
발생하지 않았으므로 기존 상태를 그대로 재사용했다. 단계별 합계는 전체 성공한 substep을
포함하며, `pipeline_times.json`의 simulate wall time은 재개 이후 구간만 포함한다.

| 단계 | substep 평균 ms | 전체 s |
|---|---:|---:|
{timing_rows}

| CPU mesh 단계 | frame 평균 ms | 전체 s |
|---|---:|---:|
{mesh_rows}

프로세스 전체 시간(초): `{json.dumps(timings)}`.
`transfer_ms`, `io_ms`, CPU meshing 및 렌더 시간은 solver 비용과 분리했다.
GPU 사용량 관측 최대 {perf['gpu_used_mb']['max']:.1f} MB.

## 결과 파일과 한계

- [최종 영상](output/scene_pool_complete/dance_water.mp4), [이전 배출 장면과 비교](output/scene_pool_complete/before_after.mp4)
- [1.2/3/6초 비교 이미지](output/scene_pool_complete/before_after.jpg), [질량과 높이 그래프](output/scene_pool_complete/accumulation.png)
- [입자/obstacle 디버그 영상](output/scene_pool_complete/debug.mp4)
- [수치 검증](output/scene_pool_complete/validation.json), [수조/높이 검증](output/scene_pool_complete/pool_validation.json)
- `output/scene_pool_complete/`: APIC/secondary/SDF cache, `surface/`: OBJ,
  `render/`: 181 PNG, `scene.usdc`: 3D animation.

6초 동안의 유한 시간 검증이다. 닫힌 영역에 무한히 계속 물을 넣는 장면의 평형이나 overflow를
구현하지 않았다. 현재 해상도에서 수 cm 깊이의 바닥 물은 몇 voxel에 불과하므로 수면/얇은 막의
정밀한 수렴 결과로 해석하지 않는다. 기존 subcell contact ballistic fallback은 유지하고
`unresolved_contact_fraction`으로 감시한다. 표면 장력이나 실제 점성 모델은 추가하지 않았다.
"""
    (ROOT / "POOL_RESULTS.md").write_text(report)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
