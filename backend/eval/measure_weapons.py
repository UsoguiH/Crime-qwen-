"""Measure BOXING accuracy on REAL weapon photos (UGR OD-WeaponDetection) through
the exact production box pipeline: forensic thinking-detect -> dedup ->
per-object grounding -> degenerate-filter -> dedup. Scores weapon detections
against expert VOC boxes: recall, mean IoU, and correct@0.5.

Usage: python eval/measure_weapons.py [--limit 40] [--concurrency 4]
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

from PIL import Image, ImageDraw  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.modelclient.client import FrameImage, VLMClient  # noqa: E402
from app.schemas.model_io import BoxRefine, DetectionResult  # noqa: E402

GT = _HERE / "realdata" / "weapons_gt.json"
DETECT = ("00_common_rules.md", "20_detect.md")   # the real forensic product prompt
DUP_IOU = 0.55
MIN_SIDE = 0.018
MAX_ASPECT = 14.0
WEAPON_WORDS = ("سلاح", "مسدس", "سكين", "خنجر", "نصل", "بندقية", "شفرة", "مدية", "سكّين")


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2-ix1) * max(0, iy2-iy1)
    if inter <= 0:
        return 0.0
    return inter / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)


def valid(box):
    w, h = box[2]-box[0], box[3]-box[1]
    if w < MIN_SIDE or h < MIN_SIDE:
        return False
    return max(w, h) / max(1e-6, min(w, h)) <= MAX_ASPECT


def dedup(boxes):
    kept = []
    for d in sorted(boxes, key=lambda x: -x["conf"]):
        if not any(iou(d["box"], k["box"]) >= DUP_IOU for k in kept):
            kept.append(d)
    return kept


def load_upscaled(path, min_px=1280, max_px=2560):
    with Image.open(path) as im:
        img = im.convert("RGB")
    if max(img.size) > max_px:
        img.thumbnail((max_px, max_px))
    elif max(img.size) < min_px:
        s = min_px / max(img.size)
        img = img.resize((round(img.width*s), round(img.height*s)), Image.LANCZOS)
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def draw_box(img_bytes: bytes, box) -> bytes:
    """Render the candidate box (red) on the image for visual self-correction."""
    with Image.open(io.BytesIO(img_bytes)) as im:
        img = im.convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img)
    d.rectangle((box[0]*W, box[1]*H, box[2]*W, box[3]*H),
                outline="#ff0000", width=max(2, min(W, H)//200))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--feedback", action="store_true",
                    help="add a visual box-correction pass after grounding")
    args = ap.parse_args()
    settings = get_settings()
    if settings.model_mode != "api":
        print("api mode required"); return 2
    db_engine.init_engine(settings)
    async with db_engine.init_engine(settings).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    vlm = VLMClient(settings, db_engine.session_factory())

    gt = json.loads(GT.read_text(encoding="utf-8"))
    images = gt["images"][:args.limit]
    sem = asyncio.Semaphore(args.concurrency)
    print(f"measuring {len(images)} REAL weapon images "
          f"(src: {gt['source']}), model={settings.model_name_fast}", flush=True)

    ious, hits, gt_total, det_weapons = [], 0, 0, 0
    done = 0

    async def ground(img_bytes, name, hint):
        try:
            r = await vlm.complete_json(prompt_files=("23_ground.md",), schema=BoxRefine,
                purpose="refine", thinking=False, images=[FrameImage(data=img_bytes, ref="x")],
                context={"target_name_ar": name, "target_hint_ar": hint[:160]},
                max_output_tokens=200)
        except Exception:
            return None
        if not r.value.visible:
            return None
        b = [max(0, min(1000, int(v)))/1000 for v in r.value.bbox_2d]
        if not (b[2] > b[0] and b[3] > b[1] and valid(b)):
            return None
        if args.feedback:
            b = await feedback(img_bytes, name, b)
        return b

    async def feedback(img_bytes, name, box):
        """Draw the box, ask the model to tighten it to the object's true edges."""
        try:
            fb = draw_box(img_bytes, box)
            r = await vlm.complete_json(prompt_files=("24_box_feedback.md",),
                schema=BoxRefine, purpose="refine", thinking=False,
                images=[FrameImage(data=fb, ref="fb")],
                context={"target_name_ar": name}, max_output_tokens=200)
        except Exception:
            return box
        if not r.value.visible:
            return box
        nb = [max(0, min(1000, int(v)))/1000 for v in r.value.bbox_2d]
        return nb if (nb[2] > nb[0] and nb[3] > nb[1] and valid(nb)) else box

    async def one(im):
        nonlocal hits, gt_total, det_weapons, done
        path = Path(im["src"])
        gt_boxes = [[v/1000 for v in g["rel1000"]] for g in im["gt"]]
        img_bytes = load_upscaled(path)
        async with sem:
            try:
                r = await vlm.complete_json(prompt_files=DETECT, schema=DetectionResult,
                    purpose="detect", thinking=True, images=[FrameImage(data=img_bytes, ref="x")],
                    context={"frame_ref": "x", "media_label": "صورة فحص",
                             "timestamp_s": None, "case_notes": ""}, max_output_tokens=6000)
                raw = r.value.model_dump()["detections"]
            except Exception as exc:
                print(f"  detect fail {im['id']}: {exc}", flush=True); raw = []
            # keep weapon detections, ground each, degenerate-filter, dedup
            weap = [d for d in raw if d["category"] == "weapons"
                    or any(w in d["name_ar"] for w in WEAPON_WORDS)]
            grounded = []
            for d in weap:
                b0 = [max(0, min(1000, int(v)))/1000 for v in d["bbox_2d"]]
                gb = await ground(img_bytes, d["name_ar"], d.get("description_ar", ""))
                fb = gb if gb else (b0 if valid(b0) else None)
                if fb:
                    grounded.append({"box": fb, "conf": d["confidence"]})
            grounded = dedup(grounded)
        # score: greedy match detections→GT by IoU
        gt_total += len(gt_boxes)
        det_weapons += len(grounded)
        used = set()
        for d in sorted(grounded, key=lambda x: -x["conf"]):
            best, bi = 0.0, -1
            for i, g in enumerate(gt_boxes):
                if i in used:
                    continue
                v = iou(d["box"], g)
                if v > best:
                    best, bi = v, i
            if bi >= 0 and best >= 0.5:
                used.add(bi); hits += 1; ious.append(best)
        done += 1
        if done % 5 == 0 or done == len(images):
            print(f"  {done}/{len(images)}", flush=True)

    await asyncio.gather(*[one(im) for im in images])
    recall = hits / gt_total if gt_total else 0
    prec = hits / det_weapons if det_weapons else 0
    miou = sum(ious)/len(ious) if ious else 0
    print("\n===== REAL WEAPON BOXING ACCURACY (production pipeline) =====")
    print(f"images={len(images)}  GT weapon boxes={gt_total}  weapon detections={det_weapons}")
    print(f"recall (weapons found)      : {recall:.3f}  ({hits}/{gt_total})")
    print(f"precision (dets that hit GT): {prec:.3f}")
    print(f"mean IoU of matched boxes   : {miou:.3f}")
    print(f"correct@0.5 (of GT weapons) : {recall:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
