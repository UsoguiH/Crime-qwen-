"""Crop-verify pass over candidate detections (the precision+IoU optimizer).

For each candidate detection: crop the image around it (padded), send only the
crop to the VLM with a single-target confirm/reject prompt. Rejected → dropped
(kills false positives → precision up). Confirmed → box tightened in crop coords
and mapped back (IoU up). Verifying on a CROP (not the full cluttered image)
avoids the round-2 grounding-verify recall collapse.

  python eval/crop_verify.py <src_tag> <dst_tag> [--model ...] [--thinking]
      [--prompt 96_crop_verify.md] [--pad 0.35] [--min-crop 512] [--concurrency 3]
Reads eval/outputs/<src_tag>/*.json (DetectionResult payloads), writes <dst_tag>.
"""
import argparse
import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from PIL import Image  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.modelclient.client import FrameImage, VLMClient  # noqa: E402
from app.schemas.model_io import BoxRefine, CropVerify  # noqa: E402

DATA = _HERE / "data"
OUT = _HERE / "outputs"


def _bytes(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.save(b, "JPEG", quality=92)
    return b.getvalue()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--model", default="qwen/qwen3-vl-30b-a3b-thinking")
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--classify", action="store_true",
                    help="classify-then-confirm: model names the object first, "
                         "keep only if it IS the target (strongest FP filter)")
    ap.add_argument("--pad", type=float, default=0.35)
    ap.add_argument("--min-crop", type=int, default=512)
    ap.add_argument("--full-min", type=int, default=1280)
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument("--votes", type=int, default=1,
                    help="verify each detection N times; keep only if ALL confirm "
                         "(self-consistency → stricter, drops more false positives)")
    ap.add_argument("--no-drop", action="store_true",
                    help="never drop a detection; only tighten its box when "
                         "confirmed (pure box-refine pass — lifts IoU without "
                         "touching recall/precision counts except via matching)")
    ap.add_argument("--classes", default="",
                    help="comma-sep COCO classes to verify (e.g. book,bottle); "
                         "detections of other classes pass through unchanged "
                         "(selective verify — spend strictness only where FPs are)")
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()

    args.prompt = args.prompt or ("97_crop_classify.md" if args.classify
                                  else "96_crop_verify.md")
    schema = CropVerify if args.classify else BoxRefine
    verify_classes = ([c.strip() for c in args.classes.split(",") if c.strip()]
                      if args.classes else None)
    from eval.score import resolve_class  # noqa: E402
    settings = get_settings()
    if settings.model_mode != "api":
        print("MODEL_MODE must be api")
        return 2
    object.__setattr__(settings, "model_name_fast", args.model)
    object.__setattr__(settings, "model_name_thinking", args.model)
    db_engine.init_engine(settings)
    async with db_engine.init_engine(settings).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    vlm = VLMClient(settings, db_engine.session_factory())

    gt = json.loads((DATA / "groundtruth.json").read_text(encoding="utf-8"))
    src = OUT / args.src
    dst = OUT / args.dst
    dst.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)
    kept_n = dropped_n = 0

    async def verify(img: Image.Image, det: dict, W: int, H: int) -> dict | None:
        nonlocal kept_n, dropped_n
        raw = det.get("bbox_2d")
        if not raw or len(raw) != 4:
            return None
        b = [max(0, min(1000, v)) / 1000 for v in raw]
        x1, y1, x2, y2 = b
        px = (x2 - x1) * args.pad + 0.02
        py = (y2 - y1) * args.pad + 0.02
        cx1, cy1 = max(0.0, x1 - px), max(0.0, y1 - py)
        cx2, cy2 = min(1.0, x2 + px), min(1.0, y2 + py)
        crop = img.crop((int(cx1 * W), int(cy1 * H), int(cx2 * W), int(cy2 * H)))
        if min(crop.size) < 8:
            return None
        if max(crop.size) < args.min_crop:
            s = args.min_crop / max(crop.size)
            crop = crop.resize((round(crop.width * s), round(crop.height * s)),
                               Image.LANCZOS)
        target = det.get("name_ar", "") or "العنصر"
        crop_bytes = _bytes(crop)

        async def _ask():   # -> (keep: bool, bbox_2d: list[int]) | None
            async with sem:
                try:
                    r = await vlm.complete_json(
                        prompt_files=(args.prompt,), schema=schema,
                        purpose="refine", thinking=args.thinking,
                        images=[FrameImage(data=crop_bytes, ref="x")],
                        context={"target_name_ar": target}, max_output_tokens=1500)
                    v = r.value
                    keep = v.is_target if args.classify else v.visible
                    return (keep, v.bbox_2d)
                except Exception:
                    return None

        votes = await asyncio.gather(*[_ask() for _ in range(args.votes)])
        good = [v for v in votes if v is not None]
        if not good:
            return det  # all transient failures → keep original (don't lose recall)
        # self-consistency: keep only if EVERY successful vote confirms the target
        if not all(k for k, _ in good):
            if args.no_drop:
                return det  # keep original box (pure box-refine mode)
            dropped_n += 1
            return None
        boxes = [bb for _, bb in good]
        pick = max(boxes, key=lambda bb: (bb[2] - bb[0]) * (bb[3] - bb[1]))
        ib = [max(0, min(1000, v)) / 1000 for v in pick]
        cw, ch = cx2 - cx1, cy2 - cy1
        fb = [round((cx1 + ib[0] * cw) * 1000), round((cy1 + ib[1] * ch) * 1000),
              round((cx1 + ib[2] * cw) * 1000), round((cy1 + ib[3] * ch) * 1000)]
        kept_n += 1
        return {**det, "bbox_2d": fb}

    async def one(im: dict) -> None:
        p = src / f"{im['id']}.json"
        outp = dst / f"{im['id']}.json"
        if not p.exists():
            outp.write_text(json.dumps({"error": "no src"}), encoding="utf-8")
            return
        d = json.loads(p.read_text(encoding="utf-8"))
        if "error" in d:
            outp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            return
        img = Image.open(DATA / "images" / im["file"]).convert("RGB")
        if max(img.size) < args.full_min:
            s = args.full_min / max(img.size)
            img = img.resize((round(img.width * s), round(img.height * s)),
                             Image.LANCZOS)
        W, H = img.size
        dets = d["pred"]["detections"]

        async def route(det: dict) -> dict | None:
            if verify_classes is not None:
                cls = resolve_class(det.get("name_ar", ""),
                                    det.get("category", ""), "name")
                if not cls or cls[0] not in verify_classes:
                    return det  # class not in the verify set → pass through
            return await verify(img, det, W, H)

        kept = await asyncio.gather(*[route(det) for det in dets])
        kept = [k for k in kept if k is not None]
        outp.write_text(json.dumps(
            {"pred": {"detections": kept, "scene_summary_ar": ""}, "status": "ok"},
            ensure_ascii=False, indent=1), encoding="utf-8")

    t = time.time()
    await asyncio.gather(*[one(im) for im in gt["images"]])
    print(f"crop-verify {args.src} -> {args.dst}: kept={kept_n} dropped={dropped_n} "
          f"in {time.time()-t:.0f}s (model={args.model}, thinking={args.thinking})",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
