# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
"""Final artifacts and numerical report for grounded feet and a wider shower."""

import csv
import json
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output/scene_grounded_shower"
DIAG = ROOT / "output/foot_diagnosis"
OLD = ROOT / "output/scene_wet_pool"


def load(p):
    return json.loads(p.read_text())


def movie_pair(first, second, destination, slow=False):
    suffix = ",setpts=2*PTS" if slow else ""
    filters = (
        "[0:v]scale=960:720,drawtext=text='Before':x=20:y=20:fontsize=28:fontcolor=white[a];[1:v]scale=960:720,drawtext=text='After':x=20:y=20:fontsize=28:fontcolor=white[b];[a][b]hstack=inputs=2:shortest=1"
        + suffix
        + "[v]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(first),
            "-i",
            str(second),
            "-filter_complex",
            filters,
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
            str(destination),
        ],
        check=True,
    )


def main():
    v = load(OUT / "validation.json")
    pool = load(OUT / "pool_validation.json")
    foot = load(DIAG / "foot_motion.json")
    energy = [load(DIAG / f"{name}_energy.json") for name in ["foot", "pre_spike", "final"]]
    visible = load(OUT / "foam_visibility/frame_000360.json")
    assert v["pass"] and pool["pass"] and foot["pass"] and visible["pass"]
    metrics = list(csv.DictReader((OUT / "metrics.csv").open()))
    settings = load(OUT / "settings.json")
    config = load(ROOT / "scene/grounded_shower.json")
    video = load(OUT / "video_metadata.json")
    times = load(OUT / "pipeline_times.json")
    assert int(video["nb_read_frames"]) == 361 and video["r_frame_rate"] == "30/1"
    montage = Image.new("RGB", (1600, 1260), (20, 25, 30))
    draw = ImageDraw.Draw(montage)
    for k, frame in enumerate([0, 90, 330, 360]):
        im = Image.open(OUT / "render" / f"frame_{frame:06d}.png").convert("RGB")
        im.thumbnail((800, 600))
        x, y = k % 2 * 800, k // 2 * 630
        montage.paste(im, (x, y + 30))
        draw.text(
            (x + 12, y + 8), f"t={frame/30:.1f} s | grounded feet, 52 cm emitter", fill="white"
        )
    montage.save(OUT / "representative_frames.jpg", quality=95)
    feet = Image.new("RGB", (1920, 1500), (20, 25, 30))
    draw = ImageDraw.Draw(feet)
    for j, frame in enumerate([5, 15]):
        for i, name in enumerate(["scene_foot_original_test", "scene_foot_grounded_test_limited"]):
            im = (
                Image.open(ROOT / "output" / name / "render_feet" / f"frame_{frame:06d}.png")
                .convert("RGB")
                .resize((960, 720))
            )
            feet.paste(im, (i * 960, j * 750 + 30))
            draw.text(
                (i * 960 + 12, j * 750 + 8),
                f'{"Before" if i==0 else "After"} | t={frame/30:.3f}s | isolated foot-driven waves',
                fill="white",
            )
    feet.save(OUT / "feet_comparison.jpg", quality=95)
    movie_pair(
        ROOT / "output/scene_foot_original_test/dance_water_feet.mp4",
        ROOT / "output/scene_foot_grounded_test_limited/dance_water_feet.mp4",
        OUT / "feet_comparison_half_speed.mp4",
        True,
    )
    movie_pair(OLD / "dance_water.mp4", OUT / "dance_water.mp4", OUT / "before_after.mp4")
    vertices = np.load(ROOT / "output/character_grounded/vertices.npy", mmap_mode="r")
    old_vertices = np.load(ROOT / "output/character/vertices.npy", mmap_mode="r")
    head_ids = np.flatnonzero(old_vertices[0, :, 1] > 1.65)
    head = vertices[:361, head_ids, :][:, :, [0, 2]].mean(1)
    distances = np.linalg.norm(head - np.array([config["emitter_x"], config["emitter_z"]]), axis=1)
    assert distances.max() < config["emitter_radius"]
    peak = max(float(q["cfl"]) * settings["h"] / float(q["dt"]) for q in metrics)
    limited_fraction = max(
        int(q["limited_affine_rows"]) / (3 * int(q["particles"])) for q in metrics
    )
    perf = "\n".join(
        f"| {k} | {q['mean']:.3f} | {q['sum']/1000:.2f} |"
        for k, q in v["performance"].items()
        if k.endswith("_ms")
    )
    meshing = "\n".join(
        f"| {k} | {q['mean']:.3f} | {q['sum']/1000:.2f} |"
        for k, q in v["meshing_performance"].items()
    )
    energy_rows = "\n".join(
        f"| {q['time']:.1f}s | {q['apic_energy_before_J']:.6g} | {q['apic_energy_after_J']:.6g} | {100*q['removed_energy_fraction']:.3f}% | {q['mean_velocity_max_difference']:.3e} |"
        for q in energy
    )
    text = f"""# 바닥의 발 반응과 넓힌 물줄기 — 12초 결과

## isovalue는 무엇인가

`mesh_surface.cc`는 anisotropic kernel을 합친 무차원 렌더용 밀도
`rho_render(x) = sum(Vp * W_A(x - xp))`를 OpenVDB FloatGrid에 저장한다.
`volumeToMesh`가 `rho_render(x) = isovalue`인 표면을 추출한다. 내부는 대체로
그 값 이상이다. 이번 값은 **{config['mesh_isovalue']}**이며 이전 영상은 0.2였다.
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
0–0.633초, 발 주변 반경 45 cm의 평균 속도 RMS는 **{foot['old_mean_rms_m_s']*100:.3f} →
{foot['new_mean_rms_m_s']*100:.3f} cm/s ({foot['mean_rms_ratio']:.3f}배)**였다.
입자 최고 높이는 {foot['grounded_peak_height_m']*100:.3f} cm였다. 확대 이미지와 0.5배속
비교 영상에서 작은 물결을 확인했다. 발 비교의 두 렌더는 isovalue 0.2를 동일하게 사용했고,
최종 낙수 영상의 0.3과 구분한다. 발 자체가 외부 일을 하므로 이 에너지 증가는
에너지 보존/무감쇠 증명으로 사용하지 않는다.

## 물줄기

| 항목 | 이전 | 현재 |
|---|---:|---:|
| 방출 지름 | 30 cm | 52 cm |
| x/z 중심 | (1.62,1.0) m | (1.67,1.145) m |
| 출구 속도 | 0.9 m/s | 0.36 m/s |
| 유량 | 63.617 L/s | {settings['flow_m3_s']*1000:.3f} L/s |

유량은 `pi*r²*speed`로 계산한다. 지름만 늘려 유량이 약 세 배가 되도록 하지 않고
약 20% 증가로 제한했다. 고정된 머리 vertex 집합의 중심은 12초 동안 방출 원 중심에서
최대 {distances.max()*100:.2f} cm 떨어져 반경 26 cm 안에 있다. 이는 배치 검사이며,
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
  {foot['mean_rms_ratio']:.2f}배 크며, 물결 개선을 최종 limiter 상태로 다시 검증했다.
- 한 checkpoint에서 force/advection 없이 같은 projected grid를 G2P한 진단 결과는 다음과 같다.
  `E = sum(0.5*m*(|v|² + h²/4*||C||²))`다. 이것은 한 번의 limiter 영향이며 누적 감쇠율이 아니다.

| Snapshot | 제한 전 APIC E (J) | 제한 후 (J) | 제거 비율 | 평균 속도 차이 |
|---|---:|---:|---:|---:|
{energy_rows}

`limited_affine_rows`의 전체 최대 비율은 {limited_fraction:.2%}다. 2-cell 깊이의 초기 물층은
stencil 대부분이 자유표면/바닥 ghost를 포함하고 작은 속도 성분도 이 개수에 포함된다.
따라서 적용 개수만을 에너지 손실률로 해석하지 않는다. 장시간 실제 물에 대한 수렴이나
모든 파장의 감쇠율을 증명한 것은 아니다.

## 전체 검증

{v['steps']:,} substep, 361 프레임, 30 fps, simulation 12초: pressure/접촉/질량/sparse/표면 검사 PASS.

| 항목 | 결과 |
|---|---:|
| 최종 APIC 입자 | {int(v['final_particles']):,} |
| 최종 물 부피(입자 질량) | {v['final_material_volume']*1000:.3f} L |
| 바닥에서 높이 25 cm 이내의 물 | {pool['final']['bed_volume_m3']*1000:.3f} L |
| 최대 pressure relative residual | {max(float(q['residual']) for q in metrics):.3e} |
| 최대 moving-wall flux error | {v['details']['moving_wall_flux']['maximum']:.3e} |
| 최대 flux divergence | {v['details']['weighted_flux_divergence']['maximum']:.3e} s⁻¹ |
| 최대 접촉 상대 법선 오차 | {v['details']['contact_inward_relative_normal']['maximum']:.3e} m/s |
| 잔여 유체/secondary 관통 | {v['details']['remaining_penetration']['maximum']:.0f} / {v['details']['whitewater_penetration']['maximum']:.1e} m |
| 누락 stencil / 질량 장부 오차 | {v['details']['missing_stencils']['maximum']:.0f} / {v['details']['mass_ledger']['maximum']:.0f} |
| 매 substep 최대 속도 성분 | {peak:.3f} m/s |
| Mesh / material volume | {v['details']['reconstruction']['mesh_volume_ratio_range']} |
| 정규화 인접 mesh 부피 변화 최대 | {v['details']['reconstruction']['max_adjacent_normalized_volume_change']:.3%} |
| 마지막 foam / spray | {metrics[-1]['foam']} / {metrics[-1]['spray']} |
| 12초 흰 foam 기여 픽셀 | {visible['white_contribution_pixels']} |

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
{perf}

| CPU meshing | frame 평균 ms | 전체 s |
|---|---:|---:|
{meshing}

전체 simulation 실행(출력 포함)은 {times['simulate']:.1f}초, CPU meshing의 프레임별 계산 합계는
{times['mesh_compute_sum_s']:.1f}초였다. 렌더 파이프라인(USD 구성/렌더/인코딩 포함)은
{times['render']:.1f}초, 디버그 영상 생성은 {times['debug']:.1f}초였다.
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
"""
    (ROOT / "GROUNDED_SHOWER_RESULTS.md").write_text(text)
    print("PASS final report and videos")


if __name__ == "__main__":
    main()
