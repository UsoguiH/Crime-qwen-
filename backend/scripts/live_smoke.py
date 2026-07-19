"""LIVE Qwen3-VL smoke test (spends a few cents of API credit):

1. Calibration grid → proves the 0–1000 relative bbox convention maps onto
   original pixels correctly (the plan's biggest accuracy risk).
2. Staged knife sample → detection quality + strict-schema round trip.

Run inside the backend container:  python scripts/live_smoke.py
"""
import asyncio
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))  # project root FIRST — never site-packages
from make_samples import ensure_samples  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.modelclient.client import FrameImage, VLMClient  # noqa: E402
from app.schemas.model_io import DetectionResult  # noqa: E402

EXPECTED = {
    "red": [100, 100, 300, 300],
    "green": [700, 100, 900, 250],
    "blue": [150, 650, 350, 900],
    "gold": [600, 600, 900, 900],
}


async def main() -> int:
    settings = get_settings()
    if settings.model_mode != "api":
        print(f"MODEL_MODE={settings.model_mode} — live smoke needs api mode")
        return 2
    settings.ensure_dirs()
    engine = db_engine.init_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    vlm = VLMClient(settings, db_engine.session_factory())

    samples = ensure_samples(with_videos=False)
    calib = samples.parent / "calibration" / "grid.png"

    print(f"model_fast = {settings.model_name_fast}")
    print("=== 1) CALIBRATION GRID (bbox convention) ===")
    result = await vlm.complete_json(
        prompt_files=("90_calibration.md",), schema=DetectionResult,
        purpose="detect", thinking=False,
        images=[FrameImage(data=calib.read_bytes(), ref="calibration",
                           name_hint="", mime="image/png")],
        context={"frame_ref": "calibration", "media_label": "شبكة معايرة"})
    detections = result.value.detections
    matched = 0
    for d in detections:
        cx = (d.bbox_2d[0] + d.bbox_2d[2]) / 2
        cy = (d.bbox_2d[1] + d.bbox_2d[3]) / 2
        hit = None
        for name, exp in EXPECTED.items():
            ecx, ecy = (exp[0] + exp[2]) / 2, (exp[1] + exp[3]) / 2
            if abs(cx - ecx) <= 60 and abs(cy - ecy) <= 60:
                hit = name
                matched += 1
                break
        print(f"  {d.name_ar}  bbox={d.bbox_2d}  conf={d.confidence}  → "
              f"{'✔ ' + hit if hit else '✘ no expected match'}")
    calib_ok = matched >= 3 and len(detections) >= 3
    print(f"calibration verdict: matched {matched}/{len(detections)} "
          f"(expected 4 rectangles) → {'PASS' if calib_ok else 'FAIL'}")

    print("=== 2) KNIFE SAMPLE (detection quality, strict schema) ===")
    knife = samples / "kitchen_knife_table.jpg"
    result2 = await vlm.complete_json(
        prompt_files=("20_detect.md",), schema=DetectionResult,
        purpose="detect", thinking=False,
        images=[FrameImage(data=knife.read_bytes(), ref="knife", name_hint="")],
        context={"frame_ref": "knife", "media_label": "صورة اختبار مُصطنعة",
                 "timestamp_s": None,
                 "case_notes": "صورة تجريبية اصطناعية لطاولة خشبية."})
    print(json.dumps(result2.value.model_dump(), ensure_ascii=False, indent=1)[:2200])
    # ground truth: the sample draws the knife at rel-1000 [417, 419, 717, 469]
    truth_c = ((417 + 717) / 2, (419 + 469) / 2)
    knife = next((d for d in result2.value.detections
                  if d.category == "weapons" or "سكين" in d.name_ar), None)
    knife_ok = False
    if knife:
        cx = (knife.bbox_2d[0] + knife.bbox_2d[2]) / 2
        cy = (knife.bbox_2d[1] + knife.bbox_2d[3]) / 2
        knife_ok = abs(cx - truth_c[0]) <= 80 and abs(cy - truth_c[1]) <= 80
        print(f"knife bbox center=({cx:.0f},{cy:.0f}) truth≈({truth_c[0]:.0f},"
              f"{truth_c[1]:.0f}) → {'PASS' if knife_ok else 'FAIL (anchoring?)'}")
    else:
        print(f"knife not detected — model reported: {result2.value.scene_summary_ar}")

    print("=== USAGE ===")
    print(json.dumps({"calibration": result.usage, "knife": result2.usage}))
    return 0 if (calib_ok and knife_ok) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
