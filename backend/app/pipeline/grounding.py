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
GROUND_CONCURRENCY = 12  # small non-thinking calls; wall-clock ∝ 1/concurrency
DUP_IOU = 0.55         # boxes overlapping ≥ this (same category) = same object → merge
DUP_CONTAIN = 0.75     # one box ≥ this fraction inside another (same category) → merge
# Pre-grounding (raw model boxes drift): merge only near-identical boxes, else a
# sloppy raw box can swallow a DIFFERENT nearby object of the same category
# (e.g. two adjacent evidence markers) and it vanishes before grounding sees it.
DUP_IOU_RAW = 0.80
DUP_CONTAIN_RAW = 0.92
# Multi-instance evidence: many small distinct items of the same category near
# each other (individual footprints inside a trail, scattered blood drops, glass
# shards). Containment-merge would collapse them into one box → IoU rule only.
SCATTER_CATEGORIES = {"impressions", "biological", "trace"}
# Boxes this overlapped are the SAME physical object no matter what the two
# passes read on it (a misread marker digit must not resurrect a duplicate).
IDENT_IOU = 0.85
IDENT_CONTAIN = 0.92   # same-category: one box essentially inside the other

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _digits(d: Detection) -> str:
    """Digits mentioned on/about the object (marker numbers etc.), Arabic-Indic
    normalized. Two numbered objects with different numbers are never duplicates."""
    txt = f"{d.name_ar or ''} {d.visible_text_ar or ''}".translate(_ARABIC_DIGITS)
    return "".join(sorted(c for c in txt if c.isdigit()))


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


async def dedup_frame(ctx: Ctx, run_id: str, frame_id: str, *,
                      strict: bool = False) -> int:
    """Merge duplicate boxes on the SAME object within one frame: same category
    + high overlap/containment → keep the highest-confidence one, drop the rest.
    Distinct adjacent objects (side by side) barely overlap and are preserved.
    strict=True is the pre-grounding mode: raw boxes are unreliable, so only
    near-identical boxes merge; the real merge happens post-grounding on
    accurate coordinates. Returns the number of duplicates removed."""
    iou_thr = DUP_IOU_RAW if strict else DUP_IOU
    contain_thr = DUP_CONTAIN_RAW if strict else DUP_CONTAIN
    async with ctx.factory() as session:
        dets = (await session.execute(
            select(Detection).where(Detection.run_id == run_id,
                                    Detection.frame_id == frame_id))).scalars().all()
        kept: list[Detection] = []
        drop_ids: list[str] = []
        # grounded boxes outrank raw ones: a detection whose grounding failed or
        # was rejected must never displace the accurately-placed duplicate
        for d in sorted(dets, key=lambda x: (x.coord_space != "grounded",
                                             -x.confidence)):
            dup = False
            for k in kept:
                iou = _iou(d, k)
                contain = _containment(d, k)
                if k.category != d.category:
                    # cross-category identity: same extent, and the loser is an
                    # ungrounded leftover — double-classification of one object
                    if iou >= IDENT_IOU and k.coord_space == "grounded" \
                            and d.coord_space != "grounded":
                        dup = True
                        break
                    continue
                # identity: same extent = same object, even when the two passes
                # read different digits on it (marker-number OCR misreads)
                if iou >= IDENT_IOU or contain >= IDENT_CONTAIN:
                    dup = True
                    break
                # numbered objects (evidence markers) with different numbers
                # are always distinct — never merge marker 2 into marker 6
                dk, dd = _digits(k), _digits(d)
                if dk and dd and dk != dd:
                    continue
                contain_ok = d.category not in SCATTER_CATEGORIES
                if iou >= iou_thr or (contain_ok and contain >= contain_thr):
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
    sem = asyncio.Semaphore(max(GROUND_CONCURRENCY,
                                ctx.settings.model_max_concurrency))
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
        # instance-jump guard: a grounded box with ZERO overlap of the original
        # detection almost always latched onto a different same-looking object
        # (e.g. the other footprint across the room). Keep the original box and
        # flag for review instead of silently moving evidence.
        orig = [det.bbox_x1, det.bbox_y1, det.bbox_x2, det.bbox_y2]
        if _iou_norm(list(coarse), orig) < 0.02:
            async with ctx.factory() as session:
                row = await session.get(Detection, det.id)
                if row is not None:
                    row.needs_human_review = True
                    await session.commit()
            return
        # no separate crop-refine call here: the verify pass (verify_frame)
        # confirms AND tightens each box on an upscaled crop in a single call
        final = coarse
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


VERIFY_PAD = 0.35        # context around the box for the verify crop
VERIFY_MIN_CROP = 512    # upscale small crops so the judge sees detail
VERIFY_BIG_FRAC = 0.45   # boxes covering more than this of the image: crop≈image,
                         # verification is meaningless (tape, whole-scene boxes)
VERIFY_DROP_CONF = 0.9   # rejected + confidence below this (or ungrounded) → delete;
                         # rejected but solid → review flag only (protects recall)


def _crop_around(img: Image.Image, W: int, H: int, det: Detection,
                 pad: float) -> tuple[bytes, tuple] | None:
    x1, y1, x2, y2 = det.bbox_x1, det.bbox_y1, det.bbox_x2, det.bbox_y2
    px = (x2 - x1) * pad + 0.02
    py = (y2 - y1) * pad + 0.02
    cx1, cy1 = max(0.0, x1 - px), max(0.0, y1 - py)
    cx2, cy2 = min(1.0, x2 + px), min(1.0, y2 + py)
    crop = img.crop((int(cx1 * W), int(cy1 * H), int(cx2 * W), int(cy2 * H)))
    if min(crop.size) < 8:
        return None
    if max(crop.size) < VERIFY_MIN_CROP:
        s = VERIFY_MIN_CROP / max(crop.size)
        crop = crop.resize((round(crop.width * s), round(crop.height * s)),
                           Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=92)
    return buf.getvalue(), (cx1, cy1, cx2, cy2)


async def verify_frame(ctx: Ctx, frame: Frame, media: MediaFile) -> tuple:
    """Crop classify-verify pass over the frame's final detections — the
    benchmark-winning precision+IoU optimizer (see eval/REPORT_30B.md), now in
    the live pipeline. For each detection: crop around the box (padded,
    upscaled) and ask the model to NAME what it sees before judging whether it
    is the claimed object.
      - rejected → the detection is a look-alike or a hallucination → deleted
        (this is what kills 'phone' boxes with no phone and boxes on bare floor)
      - confirmed → the returned tight box (crop coords) replaces the old box
    Evidence markers get a dedicated digit-read instead, so a misread marker
    number (a '6' reported as '1') is corrected from the actual pixels.
    human_presence rows are never auto-deleted — safety rule: humans are
    flagged for mandatory review, not silently dropped.
    Returns (verified, dropped, digit_fixed)."""
    from app.schemas.model_io import CropVerify, MarkerRead

    async with ctx.factory() as session:
        dets = (await session.execute(
            select(Detection).where(Detection.run_id == ctx.run_id,
                                    Detection.frame_id == frame.id))).scalars().all()
    if not dets:
        return 0, 0, 0
    img, _ = _load_upscaled(ctx, frame)
    W, H = img.size
    sem = asyncio.Semaphore(max(GROUND_CONCURRENCY,
                                ctx.settings.model_max_concurrency))
    verified = dropped = digit_fixed = 0

    async def _delete(det: Detection) -> None:
        async with ctx.factory() as session:
            await session.execute(delete(Detection).where(Detection.id == det.id))
            await session.commit()

    async def _update_box(det: Detection, reg: tuple, bbox: list[int]) -> None:
        inner = _clamp_box(bbox)
        if inner is None:
            return
        cx1, cy1, cx2, cy2 = reg
        cw, ch = cx2 - cx1, cy2 - cy1
        final = (round(cx1 + inner[0] * cw, 4), round(cy1 + inner[1] * ch, 4),
                 round(cx1 + inner[2] * cw, 4), round(cy1 + inner[3] * ch, 4))
        async with ctx.factory() as session:
            row = await session.get(Detection, det.id)
            if row is not None:
                row.bbox_x1, row.bbox_y1, row.bbox_x2, row.bbox_y2 = final
                row.coord_space = "grounded"
                await session.commit()

    async def verify_one(det: Detection) -> None:
        nonlocal verified, dropped, digit_fixed
        area = (det.bbox_x2 - det.bbox_x1) * (det.bbox_y2 - det.bbox_y1)
        if area > VERIFY_BIG_FRAC:
            return
        made = _crop_around(img, W, H, det, VERIFY_PAD)
        if made is None:
            return
        crop_bytes, reg = made

        # ── evidence markers: read the number off the pixels ──
        if det.category == "scene_markers" and _digits(det):
            async with sem:
                try:
                    res = await ctx.vlm.complete_json(
                        prompt_files=("98_read_marker.md",), schema=MarkerRead,
                        purpose="verify", thinking=False,
                        images=[FrameImage(data=crop_bytes, ref=det.id)],
                        context={"target_name_ar": det.name_ar},
                        run_id=ctx.run_id, stage=3, frame_id=frame.id,
                        media_file_id=media.id, max_output_tokens=300)
                except Exception:
                    return   # transient failure → keep as-is (protect recall)
            v = res.value
            if not v.is_marker:
                if det.coord_space != "grounded":
                    await _delete(det)        # ghost marker box → remove
                    dropped += 1
                else:
                    async with ctx.factory() as session:
                        row = await session.get(Detection, det.id)
                        if row is not None:
                            row.needs_human_review = True
                            await session.commit()
                return
            read = "".join(c for c in v.marker_number.translate(_ARABIC_DIGITS)
                           if c.isdigit())
            if read and read != _digits(det):
                # correct the misread number everywhere it appears in the text
                import re
                async with ctx.factory() as session:
                    row = await session.get(Detection, det.id)
                    if row is not None:
                        row.name_ar = re.sub(r"[0-9٠-٩]+", read, row.name_ar)
                        row.visible_text_ar = read
                        await session.commit()
                digit_fixed += 1
            verified += 1
            return

        # ── everything else: classify-then-confirm ──
        async with sem:
            try:
                res = await ctx.vlm.complete_json(
                    prompt_files=("97_crop_classify.md",), schema=CropVerify,
                    purpose="verify", thinking=False,
                    images=[FrameImage(data=crop_bytes, ref=det.id)],
                    context={"target_name_ar": det.name_ar},
                    run_id=ctx.run_id, stage=3, frame_id=frame.id,
                    media_file_id=media.id, max_output_tokens=1500)
            except Exception:
                return       # transient failure → keep as-is (protect recall)
        v = res.value
        if not v.is_target:
            # delete only SUSPECT detections (failed/rejected grounding or low
            # confidence) — that is where hallucinations live. A grounded,
            # high-confidence detection that fails one crop-verify vote is more
            # often a hard-to-see real object (thin knife on dark floor) than a
            # fake → flag for review, never silently delete. human_presence is
            # never auto-deleted regardless.
            suspect = (det.coord_space != "grounded"
                       or det.confidence < VERIFY_DROP_CONF)
            if det.category != "human_presence" and suspect:
                await _delete(det)
                dropped += 1
                return
            async with ctx.factory() as session:
                row = await session.get(Detection, det.id)
                if row is not None:
                    row.needs_human_review = True
                    await session.commit()
            return
        await _update_box(det, reg, v.bbox_2d)
        verified += 1

    await asyncio.gather(*[verify_one(d) for d in dets])
    return verified, dropped, digit_fixed
