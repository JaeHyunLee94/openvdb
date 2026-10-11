# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
"""Reproducible measurements and before/after presentation of the water fix."""

import csv
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "output/scene_final"
NEW = ROOT / "output/scene_water"
DIAG = ROOT / "output/water_diagnosis"


def table(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def particle_stats(folder, frame):
    p = np.genfromtxt(folder / f"frame_{frame:06d}.csv", delimiter=",", names=True)
    floor = p["y"] < 0.05
    speed = np.hypot(p["vx"][floor], p["vz"][floor])
    r = np.hypot(p["x"][floor] - 1.62, p["z"][floor] - 1)
    return {
        "floor_particles": int(floor.sum()),
        "floor_speed_mean": float(speed.mean()),
        "floor_speed_p90": float(np.quantile(speed, 0.9)),
        "floor_radius_p95": float(np.quantile(r, 0.95)),
    }


def main():
    validation = json.loads((NEW / "validation.json").read_text())
    assert validation["pass"]
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
    assert int(video["nb_read_frames"]) == validation["frames"]
    assert video["r_frame_rate"] == "30/1"
    images = [
        np.asarray(Image.open(NEW / "render" / f"frame_{f:06d}.png"), dtype=float)
        for f in (0, 90, 180)
    ]
    assert all(a.std() > 5 for a in images)
    assert np.abs(images[0] - images[-1]).mean() > 1
    comparison = {
        str(frame): {"before": particle_stats(OLD, frame), "after": particle_stats(NEW, frame)}
        for frame in (36, 90, 180)
    }
    m = table(NEW / "metrics.csv")
    oldm = table(OLD / "metrics.csv")
    meshing = table(NEW / "surface/meshing.csv")
    result = {
        "video": video,
        "unresolved_contact_droplets_max": max(int(r["unresolved_contact_droplets"]) for r in m),
        "unresolved_contact_fraction_max": max(
            int(r["unresolved_contact_droplets"]) / int(r["particles"]) for r in m
        ),
        "floor_comparison": comparison,
        "validation": validation["details"],
        "whitewater": {
            "before_final_foam": int(oldm[-1]["foam"]),
            "before_final_spray": int(oldm[-1]["spray"]),
            "after_final_foam": int(m[-1]["foam"]),
            "after_final_spray": int(m[-1]["spray"]),
            "after_total_births": int(m[-1]["ww_spawned"]),
            "render_buried_before": int(meshing[-1]["foam_buried_before"]),
            "render_buried_after": int(meshing[-1]["foam_buried_after"]),
        },
    }
    (NEW / "water_comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    montage = Image.new("RGB", (1600, 3 * 630), (18, 22, 28))
    draw = ImageDraw.Draw(montage)
    for row, frame in enumerate((36, 90, 180)):
        for col, (folder, label) in enumerate(((OLD, "Before"), (NEW, "Free-slip + whitewater"))):
            image = Image.open(folder / "render" / f"frame_{frame:06d}.png").convert("RGB")
            image.thumbnail((800, 600))
            montage.paste(image, (col * 800, row * 630 + 30))
            draw.text(
                (col * 800 + 12, row * 630 + 2),
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
            "[0:v]scale=960:720,drawtext=text='Before':x=20:y=20:fontsize=28:fontcolor=white[a];"
            "[1:v]scale=960:720,drawtext=text='Free-slip + whitewater':x=20:y=20:fontsize=28:fontcolor=white[b];"
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
    rows = []
    for frame, value in comparison.items():
        a, b = value["before"], value["after"]
        rows.append(
            f"| {int(frame)/30:.1f} s | {a['floor_speed_mean']:.3f} → {b['floor_speed_mean']:.3f} m/s | "
            f"{a['floor_radius_p95']:.3f} → {b['floor_radius_p95']:.3f} m |"
        )
    d = validation["details"]
    ww = result["whitewater"]
    timing_path = NEW / "pipeline_times.json"
    timings = json.loads(timing_path.read_text()) if timing_path.exists() else {}
    visibility = json.loads((NEW / "render_visibility.json").read_text())
    assert visibility["pass"]
    performance = "\n".join(
        f"| {k} | {v['mean']:.3f} | {v['sum']/1000:.3f} |"
        for k, v in validation["performance"].items()
        if k.endswith("_ms")
    )
    text = f"""# Water 동작 수정: 원인과 검증

기존 `mesh-to-sdf-fluid`의 예제 코드만 수정했다. NanoVDB operator와 ovrtx 라이브러리는 수정하지 않았다.
원본 6초 결과 `output/scene_final`을 보존했고, 새 결과는 `output/scene_water`에 있다.

## 확인한 원인

1. 물리적 viscosity 항은 원래 없었다. 하지만 `normalize/project`가 고체 내부의 모든 MAC 속도 성분을
   벽 속도로 설정했고, G2P가 이를 그대로 읽어 인공적인 no-slip 감쇠가 생겼다.
   수평 속도 1 m/s의 입자를 바닥 위 0.1h에 놓은 무중력·dt=0 전송 테스트에서,
   기존 속도는 한 번에 **0.595 m/s**, 100번 후 **0.5901639344 m/s**였다. 벌크에서는 1 m/s였다.
2. 접촉 보정이 벽 안으로 들어가는 속도와 벽에서 떨어지는 속도를 모두 제거했다.
   실제 캐릭터 SDF에서 바깥쪽 1 m/s를 준 테스트는 속도 약 **0.999996 m/s**를 잃었다.
   접촉 때 APIC C 전체도 0으로 초기화했다.
3. Spray는 출생 위치의 액체 밀도가 높으면 즉시 foam으로 바뀌었다. Secondary의 바닥 접촉은
   매 substep 접선 속도를 0.8배로 만들어 timestep에 따라 매우 강한 마찰을 적용했다.
4. Foam 밀도 표면과 렌더링 표면이 달랐고, 고체 쪽 밀도 경계를 따라가거나 실제 물 mesh 안에 묻혔다.
   수정 장면 1.2초에서 렌더 보정 전 **549/772**개 중심이 물 내부였다. 보정 후 **7/772**개였다.
   기존 장면의 물을 숨긴 diagnostic 렌더에서도 foam/spray의 존재를 확인했다.

## 구현

- `Cell::u`는 pressure/벽 유량 전용으로 유지한다. `transport`는 열린 유체 face에서 시작해
  6회의 face-neighbor 평균 연장으로 공기와 고체 ghost에 채운다. G2P와 secondary velocity sampling은
  `transport`를 사용한다. 고체 ghost를 벽 속도로 채우던 인공 접선 마찰을 제거했다.
  4회로는 곡면 접촉의 일부 대각 stencil이 부족했으며, 검증 실패를 확인한 후 6회로 수정했다.
  고체 분류 셀에 있는 subcell droplet에 속도 연장이 도달하지 않으면 해당 입자만 ballistic 이동/C 초기화 후
  SDF 접촉을 적용한다. `unresolved_contact_droplets`로 별도 계측하며, 표현된 fluid cell의 누락은 여전히 오류다.
  Unprojected 저질량 air face를 모두 seed로 유지하는 방식은 affine feedback을 증폭시켜 사용하지 않는다.
- 입자 접촉은 `v_rel·n < 0`일 때만 normal 성분을 제거한다. 분리는 허용하며 tangential C는 유지한다.
  충돌 시 `C ← (I − nnᵀ)C`. Pressure의 닫힌 face 속도는 여전히 벽 속도다.
  따라서 `contact_normal_error`는 이제 **max(0, −v_rel·n)**를 뜻한다. 분리 중의 양의 속도는 오류가 아니다.
- Spray 재흡수는 80 ms 이후, 밀도가 높고 액체에 다시 들어가는 상대 속도일 때만 허용한다.
  바닥의 substep당 20% 마찰을 없앴다. 기존 시간 기반 air drag `exp(−0.35 dt)`는 유지했다.
  Foam과 출생 secondary는 고체 내부/바닥을 공기로 오인하지 않는 density 표면을 따라간다.
  Whitewater 가속도 source에 moving-obstacle pre-contact impulse도 포함한다.
- Foam 반경은 4–7 mm, spray는 기존 2.5–5 mm다. 생성률은 40,000 → 120,000 /(m³·s)로 조절했다.
  이 생성률은 시각 효과 설정이며 유체 질량이나 pressure에는 영향을 주지 않는다.
- Anisotropic support는 입자 간격의 2.8 → 2.4배, render-only smoothing은 0.20 → 0.12,
  meshing h는 12.5 → 10 mm다. 동일 캐시로 비교한 후 isovalue는 0.5 → 0.4를 사용했다.
  1.2초 프레임 mesh/material 부피비가 0.786 → 0.955로 개선됐다. 물리 입자는 바꾸지 않았다.
- Foam render copy는 Newton 표면 보정이 고체 쪽 경계를 선택하면 6방향의 가까운 액체–공기 경계를
  탐색한다. 이동 상한 6 cm, obstacle clearance, 바닥 높이를 확인한다. 보정 후 남은 매몰도 CSV에 기록한다.
- 새 물리 모델의 checkpoint magic을 `FLUID002`로 구분해 기존 `FLUID001` 재시작을 거부한다.
- 오목한 부위에서는 triangle mesh 밖이어도 샘플된 SDF가 음수일 수 있다. Secondary fallback은
  두 조건을 모두 검사한다. 재현 위치의 SDF −3.408 mm → +0.360 mm, triangle 내부 판정은 전후 모두 false였다.
  이 보정은 기존의 반복 normal 이동이 끝난 뒤 남은 음수 SDF만 해결한다.

## 수치 검증

`scene/verify_water.cu`: 바닥 수평 속도는 1회/100회 모두 **1 m/s**. 분리 접촉의 속도/C 변화는 **0**.
Secondary 바닥 접촉에서 해석적 air drag 오차 **0**, 출생 2 ms 후 spray 상태 유지.
벌크 constant/affine APIC 최대 속도 오차 ≤1.67e−15, C 오차 ≤4.17e−14.
고정/동적 topology 30 step 비교 CSV의 최대 위치 차이 1.1e−11 m, 속도 차이 1.1e−9 m/s 이하.
SDF 독립 검사 784,930점(비활성 interior 239점 포함)의 부호 오류 0,
자유낙하 whitewater 생성 기대값 0, ppc 8/16 정규화 동일, sparse 밖 spray 해석해 오차 0.

최종 {validation['steps']} substep, {validation['frames']} 프레임 전체 검증: **PASS**.
격자 미해상도 접촉 물방울 fallback: substep당 최대 {result['unresolved_contact_droplets_max']}개,
전체 입자 대비 최대 {result['unresolved_contact_fraction_max']:.4%}. Pressure cell 미해상도의 한계로 별도 집계한다.

| 항목 | 최대값 | 기준 |
|---|---:|---:|
| 벽 운동/차단율 포함 flux divergence | {d['weighted_flux_divergence']['maximum']:.3e} s⁻¹ | 1e−6 |
| 움직이는 벽 face flux 오차 | {d['moving_wall_flux']['maximum']:.3e} | 1e−9 |
| 입자 inward relative normal 오차 | {d['contact_inward_relative_normal']['maximum']:.3e} m/s | 1e−8 |
| 유체 입자 잔여 관통 | {d['remaining_penetration']['maximum']:.0f} | 0 |
| Secondary 관통 깊이 | {d['whitewater_penetration']['maximum']:.3e} m | 1e−7 |
| 누락 stencil | {d['missing_stencils']['maximum']:.0f} | 0 |
| 질량 ledger 오차 | {d['mass_ledger']['maximum']:.0f} | 0 |

Pressure residual은 `max(1e−12, 2e−8 × ||b||)` 기준을 모든 step에서 통과했다.
자유표면/압력 분류와 particle mass는 기존처럼 별도로 유지한다.

동일 h=0.032 m, ppc=8, emitter 위치/유량/animation으로 비교했다.
바닥 지표는 y<0.05 m의 APIC 입자에서 측정하며, 동일 입자 집합 비교는 아니다.

| 시간 | 바닥 평균 수평 유속: 이전 → 수정 | 바닥 반경 p95: 이전 → 수정 |
|---|---|---|
{chr(10).join(rows)}

마지막 프레임 foam/spray: 이전 **{ww['before_final_foam']}/{ww['before_final_spray']}** →
수정 **{ww['after_final_foam']}/{ww['after_final_spray']}**. 새 secondary 총 출생 {ww['after_total_births']}개.
최종 foam 중심 매몰: 렌더 보정 전 {ww['render_buried_before']}개 → 후 {ww['render_buried_after']}개.
빈 whitewater mesh로 시작한 animation과 마지막 프레임 직접 로딩도 비교했다.
8-bit RGB 평균 차이는 {visibility['mean_absolute_8bit_pixel_difference']:.5f}/255로 기준 0.5/255 이내였다.
빈 mesh의 후속 기하 갱신은 정상이며, renderer에서 particle이 누락되는 문제는 재현되지 않았다.
Meshing 부피비 범위 {d['reconstruction']['mesh_volume_ratio_range']}, 인접 정규화 부피 변화 최대
{d['reconstruction']['max_adjacent_normalized_volume_change']:.4%}. 상세 판정은 `output/scene_water/validation.json`.

## 재현

저장소 root에서 실행한다.

```bash
cmake --build build/release --target ex_mesh_to_sdf_fluid_scene_cuda ex_mesh_to_sdf_fluid_surface ex_mesh_to_sdf_fluid_water_verify ex_mesh_to_sdf_fluid_scene_verify -j3
EX=nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_cuda
build/release/nanovdb/nanovdb/examples/ex_mesh_to_sdf_fluid_water_verify "$EX/output/character"
/tmp/fluid-render-venv/bin/python "$EX/scene/pipeline.py" "$EX/scene/water.json"
/tmp/fluid-render-venv/bin/python "$EX/scene/render_scene.py" "$EX/output/scene_water" --character "$EX/output/character" --only-frame 180 --width 1600 --height 1200 --samples 96 --whitewater-mode diagnostic
/tmp/fluid-render-venv/bin/python "$EX/scene/verify_render_visibility.py" "$EX/output/scene_water"
/tmp/fluid-render-venv/bin/python "$EX/scene/report_water.py"
```

## 출력과 비용

- [수정 영상](output/scene_water/dance_water.mp4), [동시 비교 영상](output/scene_water/before_after.mp4)
- [초중후 비교 이미지](output/scene_water/before_after.jpg), [APIC/경계 debug 영상](output/scene_water/debug.mp4)
- [Whitewater 진단 이미지](output/scene_water/preview_diagnostic/frame_000180.png)
- 캐시 `output/scene_water/frame_*.csv`, 표면 `surface/water_*.obj`, 전체 이미지 `render/`
- 재현 설정 `scene/water.json`, 수치 비교 `output/scene_water/water_comparison.json`
- 회귀 테스트 로그 `output/water_diagnosis/`

단계 wall time (초): `{json.dumps(timings)}`.
이번 cache는 2.233333초의 검증된 checkpoint에서 secondary 접촉 수정 후 재개했다.
`simulate` wall time은 이 재개 구간의 비용이다. 아래 substep 계측 합계는 전체 0–6초를 포함한다.
아래는 simulation 계측 합계이며 IO를 별도로 표시한다. 초기 회귀 검사와 GPU 사용이 일부 겹쳤으므로
전용 성능 benchmark로 해석하지 않는다.

| 작업 | substep 평균 ms | 누적 s |
|---|---:|---:|
{performance}

## 남은 한계

이 수정은 인공적인 접착/마찰을 없애는 것이다. 순수 APIC의 수치 소산, 셀 단위 fluid mask,
3.2 cm simulation 해상도에서 표현하지 못하는 얇은 물막은 남는다. 실제 물의 점성 계수,
표면장력, 접촉각, 미세 난류를 정량적으로 재현했다고 주장하지 않는다.
질량 ledger 보존은 기하학적 부피 보존과 다르며 meshing 부피비도 별도로 보고했다.
Foam/spray는 유체에 피드백하지 않는 시각 효과이며, 6 cm render 보정은 물리적 이동이 아니다.
부피 기반 flicker 검사는 국소 표면의 모든 시간적 불연속을 증명하지 않는다.
"""
    (ROOT / "WATER_FIX_REPORT.md").write_text(text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
