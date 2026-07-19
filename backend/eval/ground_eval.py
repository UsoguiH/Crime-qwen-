"""Measures BOXING accuracy (the user's complaint) on real COCO images with
known boxes: single-shot detect boxes vs the decoupled ground+refine pass.
Reports mean IoU + fraction of boxes with IoU≥0.5 (a 'correct' box).

  python eval/ground_eval.py <n_images>
Requires eval/data/groundtruth.json (from eval/dataset.py) and api mode.
"""
import asyncio
import io
import json
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"  # no run logging here
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from PIL import Image  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.modelclient.client import FrameImage, VLMClient  # noqa: E402
from app.schemas.model_io import BoxRefine  # noqa: E402

DATA = _HERE / "data"


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua


NAME = {"knife": "سكين", "scissors": "مقص", "cell phone": "هاتف محمول",
        "laptop": "حاسوب محمول", "bottle": "زجاجة", "book": "كتاب"}


def _upscaled(path, min_px):
    with Image.open(path) as im:
        img = im.convert("RGB")
    if max(img.size) < min_px:
        s = min_px / max(img.size)
        img = img.resize((round(img.width*s), round(img.height*s)), Image.LANCZOS)
    return img


def _bytes(img):
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=92); return buf.getvalue()


async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    settings = get_settings()
    db_engine.init_engine(settings)
    async with db_engine.init_engine(settings).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    vlm = VLMClient(settings, db_engine.session_factory())

    gt = json.loads((DATA / "groundtruth.json").read_text(encoding="utf-8"))
    # one clear GT box per image (largest), across the first n images
    samples = []
    for im in gt["images"]:
        g = max(im["gt"], key=lambda x: x["area_ratio"])
        samples.append((im, g))
        if len(samples) >= n:
            break

    async def ground_full(img_bytes, name):
        r = await vlm.complete_json(prompt_files=("23_ground.md",), schema=BoxRefine,
            purpose="refine", thinking=False, images=[FrameImage(data=img_bytes, ref="x")],
            context={"target_name_ar": name, "target_hint_ar": name},
            max_output_tokens=256)
        return r.value

    async def refine_crop(img, name, coarse):
        W, H = img.size
        x1, y1, x2, y2 = coarse
        px = (x2-x1)*0.25+0.02; py = (y2-y1)*0.25+0.02
        cx1, cy1 = max(0, x1-px), max(0, y1-py)
        cx2, cy2 = min(1, x2+px), min(1, y2+py)
        crop = img.crop((int(cx1*W), int(cy1*H), int(cx2*W), int(cy2*H)))
        if max(crop.size) < 768:
            s = 768/max(crop.size); crop = crop.resize((round(crop.width*s), round(crop.height*s)))
        r = await vlm.complete_json(prompt_files=("22_box_refine.md",), schema=BoxRefine,
            purpose="refine", thinking=False, images=[FrameImage(data=_bytes(crop), ref="x")],
            context={"target_name_ar": name}, max_output_tokens=256)
        if not r.value.visible:
            return coarse
        b = [max(0, min(1000, v))/1000 for v in r.value.bbox_2d]
        cw, ch = cx2-cx1, cy2-cy1
        return (cx1+b[0]*cw, cy1+b[1]*ch, cx1+b[2]*cw, cy1+b[3]*ch)

    single_ious, ground_ious = [], []
    for im, g in samples:
        path = DATA / "images" / im["file"]
        name = NAME[g["cls"]]
        truth = [v/1000 for v in g["rel1000"]]
        # A) single-shot grounding at 2560 cap (≈ old detect behaviour)
        try:
            a = await ground_full(_bytes(_upscaled(path, 640)), name)
            ab = [max(0, min(1000, v))/1000 for v in a.bbox_2d] if a.visible else [0,0,0,0]
        except Exception:
            ab = [0,0,0,0]
        single_ious.append(iou(ab, truth))
        # B) upscaled ground + crop-refine (new pipeline)
        try:
            img = _upscaled(path, 1280)
            b0 = await ground_full(_bytes(img), name)
            coarse = [max(0, min(1000, v))/1000 for v in b0.bbox_2d] if b0.visible else [0,0,0,0]
            fine = await refine_crop(img, name, tuple(coarse)) if b0.visible else coarse
        except Exception:
            fine = [0,0,0,0]
        ground_ious.append(iou(list(fine), truth))
        print(f"  {im['file']} [{g['cls']}] single={single_ious[-1]:.2f} ground={ground_ious[-1]:.2f}")

    def summ(v):
        return (sum(v)/len(v), sum(1 for x in v if x >= 0.5)/len(v))
    sm, sh = summ(single_ious); gm, gh = summ(ground_ious)
    print(f"\n== BOXING ACCURACY (n={len(samples)}) ==")
    print(f"single-shot : mean IoU {sm:.3f}  correct@0.5 {sh:.0%}")
    print(f"ground+refine: mean IoU {gm:.3f}  correct@0.5 {gh:.0%}")
    print(f"delta       : IoU {gm-sm:+.3f}  correct {gh-sh:+.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
