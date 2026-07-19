"""Runs the whole ground-truth set through the live Qwen3-VL client.

Usage (inside container, mounted, --env-file .env):
  python eval/run_eval.py <tag> --prompt 20_detect.md [--max-px 2560] [--model <slug>]

Every image's raw structured output is saved to eval/outputs/<tag>/<image_id>.json.
Existing outputs are skipped (resume-safe). The config is frozen into
outputs/<tag>/config.json so no run can be misattributed.
"""
import argparse
import asyncio
import io
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from PIL import Image  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.modelclient.client import FrameImage, VLMClient  # noqa: E402
from app.schemas.model_io import DetectionResult  # noqa: E402

DATA_DIR = _HERE / "data"
OUT_DIR = _HERE / "outputs"


def _jpeg(path: Path, max_px: int) -> bytes:
    with Image.open(path) as im:
        img = im.convert("RGB")
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--prompt", default="20_detect.md")
    ap.add_argument("--max-px", type=int, default=2560)
    ap.add_argument("--model", default=None)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--no-schema", action="store_true",
                    help="disable strict json_schema enforcement (prompt-JSON only)")
    ap.add_argument("--per-class", action="store_true",
                    help="decomposed grounding: one call per target class per image")
    args = ap.parse_args()

    settings = get_settings()
    if settings.model_mode != "api":
        print("MODEL_MODE must be api for evaluation")
        return 2
    if args.model:
        object.__setattr__(settings, "model_name_fast", args.model)

    gt = json.loads((DATA_DIR / "groundtruth.json").read_text(encoding="utf-8"))
    out = OUT_DIR / args.tag
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({
        "tag": args.tag, "prompt": args.prompt, "max_px": args.max_px,
        "model": settings.model_name_fast, "temperature": 0.1,
        "enforce_schema": not args.no_schema, "per_class": args.per_class,
        "images": len(gt["images"]), "gt_boxes": gt["total_boxes"],
    }, indent=1), encoding="utf-8")

    settings.ensure_dirs()
    engine = db_engine.init_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    vlm = VLMClient(settings, db_engine.session_factory())

    todo = [im for im in gt["images"]
            if not (out / f"{im['id']}.json").exists()]
    print(f"[{args.tag}] prompt={args.prompt} max_px={args.max_px} "
          f"model={settings.model_name_fast} → {len(todo)}/{len(gt['images'])} to run",
          flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    done = 0
    failed = 0

    PER_CLASS_TARGETS = [
        {"cls": "knife", "target_class_ar": "السكاكين والأدوات ذات النصل",
         "target_name_prefix": "سكين", "target_category": "weapons"},
        {"cls": "scissors", "target_class_ar": "المقصات",
         "target_name_prefix": "مقص", "target_category": "weapons"},
        {"cls": "cell phone", "target_class_ar": "الهواتف المحمولة",
         "target_name_prefix": "هاتف محمول", "target_category": "documents_devices"},
        {"cls": "laptop", "target_class_ar": "الحواسيب المحمولة",
         "target_name_prefix": "حاسوب محمول", "target_category": "documents_devices"},
        {"cls": "bottle", "target_class_ar": "الزجاجات والقوارير والعبوات",
         "target_name_prefix": "زجاجة", "target_category": "trace"},
        {"cls": "book", "target_class_ar": "الكتب والمجلدات (بما فيها المصفوفة على الرفوف)",
         "target_name_prefix": "كتاب", "target_category": "documents_devices"},
    ]

    async def call(image: FrameImage, im: dict, extra_ctx: dict) -> dict:
        started = time.monotonic()
        async with sem:
            result = await vlm.complete_json(
                prompt_files=(args.prompt,), schema=DetectionResult,
                purpose="detect", thinking=False, images=[image],
                context={"frame_ref": str(im["id"]), "media_label": "صورة فحص",
                         "timestamp_s": None, "case_notes": "", **extra_ctx},
                max_output_tokens=6000,
                enforce_schema=not args.no_schema)
        return {"pred": result.value.model_dump(), "usage": result.usage,
                "status": result.status,
                "latency_ms": int((time.monotonic() - started) * 1000)}

    async def one(im: dict) -> None:
        nonlocal done, failed
        path = DATA_DIR / "images" / im["file"]
        image = FrameImage(data=_jpeg(path, args.max_px), ref=str(im["id"]),
                           name_hint="")
        try:
            if args.per_class:
                parts = await asyncio.gather(
                    *[call(image, im, t) for t in PER_CLASS_TARGETS],
                    return_exceptions=True)
                detections, usages, errors = [], [], []
                for target, part in zip(PER_CLASS_TARGETS, parts):
                    if isinstance(part, Exception):
                        errors.append(f"{target['cls']}: {part}")
                        continue
                    detections.extend(part["pred"]["detections"])
                    usages.append({**part["usage"], "cls": target["cls"]})
                payload = {"pred": {"detections": detections,
                                    "scene_summary_ar": ""},
                           "usage": {"parts": usages}, "status": "ok",
                           "part_errors": errors}
                if errors and not usages:
                    raise RuntimeError("; ".join(errors))
            else:
                payload = await call(image, im, {})
        except Exception as exc:
            failed += 1
            payload = {"error": f"{type(exc).__name__}: {exc}"[:500]}
        (out / f"{im['id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        if done % 5 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)} (failed={failed})", flush=True)

    await asyncio.gather(*[one(im) for im in todo])
    print(f"[{args.tag}] complete; errors={failed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
