"""Decoupled visual grounding: detection says WHAT, grounding says WHERE.

Multi-object grounding (many boxes in one call) is where Qwen3-VL localization
degrades — boxes cluster and drift. Re-grounding each object with a single-target
call on the upscaled full image is markedly more accurate; a light crop-refine
then tightens the winner. Boxes that the model cannot confidently place are left
as-is and flagged, never silently moved.
"""
import asyncio
import io

from PIL import Image
from sqlalchemy import delete, select

from app.db.models import Detection, Frame, MediaFile
from app.modelclient.client import FrameImage
from app.pipeline.ctx import Ctx
from app.schemas.model_io import BoxRefine

GROUND_MIN_PX = 1280   # upscale target for the grounding pass — more pixels, tighter boxes
CROP_PAD = 0.25        # generous context around the coarse box for the refine crop
DUP_IOU = 0.55         # boxes overlapping ≥ this (same category) = same object → merge
DUP_CONTAIN = 0.75     # one box ≥ this fraction inside another (same category) → merge


def _iou(a: Detection, b: Detection) -> float:
    ix1, iy1 = max(a.bbox_x1, b.bbox_x1), max(a.bbox_y1, b.bbox_y1)
    ix2, iy2 = min(a.bbox_x2, b.bbox_x2), min(a.bbox_y2, b.bbox_y2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    aa = (a.bbox_x2 - a.bbox_x1) * (a.bbox_y2 - a.bbox_y1)
    ab = (b.bbox_x2 - b.bbox_x1) * (b.bbox_y2 - b.bbox_y1)
    return inter / (aa + ab - inter)


def _containment(a: Detection, b: Detection) -> float:
    """Fraction of the SMALLER box that lies inside the larger — catches the
    'whole object' + 'part of same object' duplicate (e.g. gun + gun barrel)."""
    ix1, iy1 = max(a.bbox_x1, b.bbox_x1), max(a.bbox_y1, b.bbox_y1)
    ix2, iy2 = min(a.bbox_x2, b.bbox_x2), min(a.bbox_y2, b.bbox_y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    aa = (a.bbox_x2 - a.bbox_x1) * (a.bbox_y2 - a.bbox_y1)
    ab = (b.bbox_x2 - b.bbox_x1) * (b.bbox_y2 - b.bbox_y1)
    smaller = min(aa, ab)
    return inter / smaller if smaller > 0 else 0.0


async def dedup_frame(ctx: Ctx, run_id: str, frame_id: str) -> int:
    """Merge duplicate boxes on the SAME object within one frame: same category
    + high overlap/containment → keep the highest-confidence one, drop the rest.
    Distinct adjacent objects (side by side) barely overlap and are preserved.
    Returns the number of duplicates removed."""
    async with ctx.factory() as session:
        dets = (await session.execute(
            select(Detection).where(Detection.run_id == run_id,
                                    Detection.frame_id == frame_id))).scalars().all()
        kept: list[Detection] = []
        drop_ids: list[str] = []
        for d in sorted(dets, key=lambda x: -x.confidence):
            dup = False
            for k in kept:
                if k.category != d.category:
                    continue
                if _iou(d, k) >= DUP_IOU or _containment(d, k) >= DUP_CONTAIN:
                    dup = True
                    break
            (drop_ids.append(d.id) if dup else kept.append(d))
        if drop_ids:
            await session.execute(delete(Detection).where(Detection.id.in_(drop_ids)))
            await session.commit()
        return len(drop_ids)


MIN_SIDE = 18          # reject grounded boxes thinner than 1.8% of the image
MAX_ASPECT = 14.0      # reject absurdly elongated boxes (a sliver, not an object)


def _clamp_box(b: list[int]) -> tuple[float, float, float, float] | None:
    if len(b) != 4:
        return None
    x1, y1, x2, y2 = (max(0, min(1000, int(v))) for v in b)
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    w, h = x2 - x1, y2 - y1
    # degenerate: too thin, or a sliver with an extreme aspect ratio → reject,
    # so the caller keeps the object's original (usually better) box
    if w < MIN_SIDE or h < MIN_SIDE:
        return None
    if max(w, h) / max(1, min(w, h)) > MAX_ASPECT:
        return None
    return x1 / 1000, y1 / 1000, x2 / 1000, y2 / 1000


def _load_upscaled(ctx: Ctx, frame: Frame) -> tuple[Image.Image, bytes]:
    path = ctx.abs_path(frame.stored_path)
    with Image.open(path) as im:
        img = im.convert("RGB")
    if max(img.size) < GROUND_MIN_PX:
        scale = GROUND_MIN_PX / max(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return img, buf.getvalue()


def _iou_norm(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    aa = (a[2]-a[0]) * (a[3]-a[1])
    ab = (b[2]-b[0]) * (b[3]-b[1])
    return inter / (aa + ab - inter)


async def refine_answer_boxes(vlm, full_bytes: bytes,
                              boxes: list[dict]) -> list[dict]:
    """Q&A boxes get the same accuracy treatment as detection: single-target
    grounding to tighten each box, degenerate-filter, then IoU-dedup. boxes are
    dicts {label_ar, bbox:[x1,y1,x2,y2] normalized 0..1}."""
    if not boxes:
        return boxes

    async def refine(b: dict) -> dict:
        try:
            r = await vlm.complete_json(
                prompt_files=("23_ground.md",), schema=BoxRefine,
                purpose="refine", thinking=False,
                images=[FrameImage(data=full_bytes, ref="qa")],
                context={"target_name_ar": b["label_ar"],
                         "target_hint_ar": b["label_ar"]},
                max_output_tokens=200)
        except Exception:
            return b
        if not r.value.visible:
            return b
        c = _clamp_box(r.value.bbox_2d)  # degenerate boxes rejected → keep original
        return {**b, "bbox": list(c)} if c else b

    refined = await asyncio.gather(*[refine(b) for b in boxes])
    kept: list[dict] = []
    for b in refined:
        if not any(_iou_norm(b["bbox"], k["bbox"]) >= DUP_IOU for k in kept):
            kept.append(b)
    return kept


async def ground_detections(ctx: Ctx, frame: Frame, media: MediaFile,
                            detections: list[Detection]) -> int:
    """Re-ground every detection in place. Returns count re-grounded."""
    if not detections:
        return 0
    img, full_bytes = _load_upscaled(ctx, frame)
    W, H = img.size
    sem = asyncio.Semaphore(max(4, ctx.settings.model_max_concurrency))
    regrounded = 0

    async def ground_one(det: Detection) -> None:
        nonlocal regrounded
        async with sem:
            try:
                res = await ctx.vlm.complete_json(
                    prompt_files=("23_ground.md",), schema=BoxRefine,
                    purpose="refine", thinking=False,
                    images=[FrameImage(data=full_bytes, ref=det.id)],
                    context={"target_name_ar": det.name_ar,
                             "target_hint_ar": det.description_ar[:200]},
                    run_id=ctx.run_id, stage=3, frame_id=frame.id,
                    media_file_id=media.id, max_output_tokens=256)
            except Exception:
                return
        box = res.value
        if not box.visible:
            return
        coarse = _clamp_box(box.bbox_2d)
        if coarse is None:
            return
        tight = await _crop_refine(ctx, img, W, H, det, coarse)
        final = tight or coarse
        async with ctx.factory() as session:
            row = await session.get(Detection, det.id)
            if row is not None:
                row.bbox_x1, row.bbox_y1, row.bbox_x2, row.bbox_y2 = final
                row.coord_space = "grounded"
                await session.commit()
        det.bbox_x1, det.bbox_y1, det.bbox_x2, det.bbox_y2 = final
        regrounded += 1

    await asyncio.gather(*[ground_one(d) for d in detections])
    return regrounded


async def _crop_refine(ctx: Ctx, img: Image.Image, W: int, H: int,
                       det: Detection, coarse: tuple) -> tuple | None:
    """Crop a padded region around the coarse box, ask for a tight box within
    the crop, map back to full-image normalized coords. Skips huge boxes
    (already whole-image) where a crop adds nothing."""
    x1, y1, x2, y2 = coarse
    if (x2 - x1) > 0.6 and (y2 - y1) > 0.6:
        return None
    pad_x = (x2 - x1) * CROP_PAD + 0.02
    pad_y = (y2 - y1) * CROP_PAD + 0.02
    cx1, cy1 = max(0.0, x1 - pad_x), max(0.0, y1 - pad_y)
    cx2, cy2 = min(1.0, x2 + pad_x), min(1.0, y2 + pad_y)
    px1, py1, px2, py2 = int(cx1 * W), int(cy1 * H), int(cx2 * W), int(cy2 * H)
    if px2 - px1 < 20 or py2 - py1 < 20:
        return None
    crop = img.crop((px1, py1, px2, py2))
    if max(crop.size) < 768:
        s = 768 / max(crop.size)
        crop = crop.resize((round(crop.width * s), round(crop.height * s)),
                           Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=92)
    try:
        res = await ctx.vlm.complete_json(
            prompt_files=("22_box_refine.md",), schema=BoxRefine,
            purpose="refine", thinking=False,
            images=[FrameImage(data=buf.getvalue(), ref=det.id)],
            context={"target_name_ar": det.name_ar},
            run_id=ctx.run_id, stage=3, frame_id=det.frame_id,
            media_file_id=det.media_file_id, max_output_tokens=256)
    except Exception:
        return None
    inner = _clamp_box(res.value.bbox_2d)
    if not res.value.visible or inner is None:
        return None
    # map crop-relative → full-image normalized
    cw, ch = cx2 - cx1, cy2 - cy1
    return (round(cx1 + inner[0] * cw, 4), round(cy1 + inner[1] * ch, 4),
            round(cx1 + inner[2] * cw, 4), round(cy1 + inner[3] * ch, 4))
