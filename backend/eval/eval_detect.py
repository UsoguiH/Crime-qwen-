"""Detection-engine accuracy iteration harness. Runs the labeled set through
one of several strategies and writes score.py-compatible outputs so the SAME
matcher/metrics apply to every iteration (valid before/after comparison).

Modes (one variable at a time):
  baseline  : single-shot, non-thinking (production-speed detect)
  thinking  : single-shot, thinking mode
  recheck   : detect (non-thinking) then a second-look pass that adds ONLY
              missed instances; union with IoU dedup   [recall lever]
  recheck-t : same as recheck but the first detect pass uses thinking
  union2    : two independent detect passes (temp 0.5), union + IoU dedup

Usage (api mode, provider pinned recommended):
  python eval/eval_detect.py <mode> <tag> [--max-px 2560] [--concurrency 4]
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
from app.schemas.model_io import BoxRefine, DetectionResult  # noqa: E402

DATA = _HERE / "data"
OUT = _HERE / "outputs"
DETECT_PROMPT = "91_eval_grounding.md"
RECHECK_PROMPT = "94_eval_recheck.md"


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua


def _dedup(dets: list[dict]) -> list[dict]:
    """Drop later detections that duplicate an earlier one (same first word, IoU>0.5)."""
    kept: list[dict] = []
    for d in sorted(dets, key=lambda x: -x.get("confidence", 0)):
        head = d["name_ar"].split()[:1]
        dup = False
        for k in kept:
            if k["name_ar"].split()[:1] == head and _iou(d["bbox_2d"], k["bbox_2d"]) >= 0.5:
                dup = True
                break
        if not dup:
            kept.append(d)
    return kept


def _jpeg(path: Path, max_px: int) -> bytes:
    with Image.open(path) as im:
        img = im.convert("RGB")
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    elif max(img.size) < 960:
        s = 960 / max(img.size)
        img = img.resize((round(img.width*s), round(img.height*s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["baseline", "thinking", "recheck",
                                     "recheck-t", "union2", "thinking-verify"])
    ap.add_argument("tag")
    ap.add_argument("--max-px", type=int, default=2560)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    settings = get_settings()
    if settings.model_mode != "api":
        print("MODEL_MODE must be api"); return 2
    db_engine.init_engine(settings)
    async with db_engine.init_engine(settings).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    vlm = VLMClient(settings, db_engine.session_factory())

    gt = json.loads((DATA / "groundtruth.json").read_text(encoding="utf-8"))
    if args.limit:
        gt["images"] = gt["images"][:args.limit]
    out = OUT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({
        "tag": args.tag, "mode": args.mode, "model": settings.model_name_fast,
        "images": len(gt["images"]), "gt_boxes": gt["total_boxes"]}, indent=1))

    todo = [im for im in gt["images"] if not (out / f"{im['id']}.json").exists()]
    print(f"[{args.tag}] mode={args.mode} model={settings.model_name_fast} "
          f"provider_order={settings.openrouter_provider_order} "
          f"→ {len(todo)}/{len(gt['images'])} to run", flush=True)
    sem = asyncio.Semaphore(args.concurrency)
    done = 0

    async def detect(img_bytes, thinking, temp=None):
        r = await vlm.complete_json(
            prompt_files=(DETECT_PROMPT,), schema=DetectionResult,
            purpose="detect", thinking=thinking,
            images=[FrameImage(data=img_bytes, ref="x")],
            context={"media_label": "صورة فحص", "timestamp_s": None},
            max_output_tokens=6000, temperature=temp)
        return [d for d in r.value.model_dump()["detections"]]

    async def verify(img_bytes, det):
        """Single-target grounding as a confirm-or-drop + retighten filter."""
        try:
            r = await vlm.complete_json(
                prompt_files=("23_ground.md",), schema=BoxRefine,
                purpose="refine", thinking=False,
                images=[FrameImage(data=img_bytes, ref="x")],
                context={"target_name_ar": det["name_ar"],
                         "target_hint_ar": det.get("description_ar", "")[:160]},
                max_output_tokens=200)
        except Exception:
            return det  # keep original on error
        if not r.value.visible:
            return None  # grounding can't find it → drop as unconfirmed
        b = [max(0, min(1000, int(v))) for v in r.value.bbox_2d]
        if b[2] - b[0] >= 3 and b[3] - b[1] >= 3:
            det = dict(det, bbox_2d=b)
        return det

    async def recheck(img_bytes, found, thinking):
        r = await vlm.complete_json(
            prompt_files=(RECHECK_PROMPT,), schema=DetectionResult,
            purpose="detect", thinking=thinking,
            images=[FrameImage(data=img_bytes, ref="x")],
            context={"already_found": [{"name_ar": d["name_ar"],
                                        "bbox_2d": d["bbox_2d"]} for d in found]},
            max_output_tokens=4000)
        return [d for d in r.value.model_dump()["detections"]]

    async def one(im):
        nonlocal done
        path = DATA / "images" / im["file"]
        img_bytes = _jpeg(path, args.max_px)
        started = time.monotonic()
        async with sem:
            try:
                if args.mode == "baseline":
                    dets = await detect(img_bytes, thinking=False)
                elif args.mode == "thinking":
                    dets = await detect(img_bytes, thinking=True)
                elif args.mode in ("recheck", "recheck-t"):
                    first = await detect(img_bytes, thinking=(args.mode == "recheck-t"))
                    extra = await recheck(img_bytes, first, thinking=False)
                    dets = _dedup(first + extra)
                elif args.mode == "union2":
                    a, b = await asyncio.gather(
                        detect(img_bytes, False, 0.5), detect(img_bytes, False, 0.5))
                    dets = _dedup(a + b)
                elif args.mode == "thinking-verify":
                    found = await detect(img_bytes, thinking=True)
                    verified = await asyncio.gather(*[verify(img_bytes, d) for d in found])
                    dets = [d for d in verified if d is not None]
                payload = {"pred": {"detections": dets, "scene_summary_ar": ""},
                           "latency_ms": int((time.monotonic()-started)*1000)}
            except Exception as exc:
                payload = {"error": f"{type(exc).__name__}: {exc}"[:400]}
        (out / f"{im['id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        if done % 10 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)}", flush=True)

    await asyncio.gather(*[one(im) for im in todo])
    print(f"[{args.tag}] complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
