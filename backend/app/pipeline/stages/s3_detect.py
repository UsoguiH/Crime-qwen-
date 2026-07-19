"""Stage 3 — structured detection per selected frame; thinking-mode escalation."""
import asyncio
import logging

from sqlalchemy import select

from app.db.models import Case, Detection, Frame, MediaFile, TriageResult
from app.modelclient.client import BudgetExceeded, FrameImage, ModelJSONError
from app.pipeline.ctx import Ctx
from app.schemas.model_io import DetectionResult

log = logging.getLogger("athar.s3")


async def run(ctx: Ctx) -> None:
    async with ctx.factory() as session:
        case = (await session.execute(
            select(Case).where(Case.id == ctx.case_id))).scalar_one()
        rows = (await session.execute(
            select(TriageResult, Frame, MediaFile)
            .join(Frame, TriageResult.frame_id == Frame.id)
            .join(MediaFile, Frame.media_file_id == MediaFile.id)
            .where(TriageResult.run_id == ctx.run_id,
                   TriageResult.selected_for_detection.is_(True))
            .order_by(MediaFile.uploaded_at, Frame.frame_index))).all()

    checkpoint = await ctx.get_checkpoint(3)
    done: list[str] = checkpoint.get("done", [])
    failed: list[str] = checkpoint.get("failed", [])
    todo = [(t, f, m) for t, f, m in rows if f.id not in done]
    total = len(rows)
    await ctx.set_step(3, total=total, current=len(done))

    policy = (ctx.options.get("thinking_policy") or "auto").lower()
    review_thr = float(ctx.thr("confidence_review_threshold",
                               ctx.settings.confidence_review_threshold))
    notes = (case.notes_ar or "")[:500]
    concurrency = max(2, ctx.settings.model_max_concurrency)

    for i in range(0, len(todo), concurrency):
        chunk = todo[i:i + concurrency]
        results = await asyncio.gather(
            *[_detect_frame(ctx, t, f, m, policy, review_thr, notes)
              for t, f, m in chunk],
            return_exceptions=True)
        for (t, f, m), outcome in zip(chunk, results):
            if isinstance(outcome, BudgetExceeded):
                await ctx.set_step(3, checkpoint={"done": done, "failed": failed})
                raise outcome
            if isinstance(outcome, Exception):
                log.warning("detect failed for frame %s: %s", f.id, outcome)
                failed.append(f.id)
            else:
                done.append(f.id)
        await ctx.set_step(3, current=len(done),
                           checkpoint={"done": done, "failed": failed})
        if len(failed) > max(3, 0.2 * total):
            raise RuntimeError(
                f"معدل فشل مرتفع في تحليل الإطارات ({len(failed)}/{total}) — "
                "أوقف التحليل؛ يمكن الاستئناف بعد معالجة السبب")

    if failed:
        await ctx.set_step(3, status="completed_with_errors",
                           error=f"فشل تحليل {len(failed)} إطاراً")


async def _detect_frame(ctx: Ctx, triage: TriageResult, frame: Frame,
                        media: MediaFile, policy: str, review_thr: float,
                        notes: str) -> None:
    human = triage.human_presence_suspected
    thinking = {"always": True, "never": False}.get(
        policy, triage.complexity == "high" or human)
    await detect_one(ctx, frame, media, thinking=thinking,
                     human_addendum=human, review_thr=review_thr, notes=notes)


async def detect_one(ctx: Ctx, frame: Frame, media: MediaFile, *,
                     thinking: bool, human_addendum: bool,
                     review_thr: float, notes: str) -> int:
    """Shared by the full pipeline (s3) and photo mode. Returns detections stored."""
    prompt_files = ("20_detect.md", "21_detect_human_addendum.md") \
        if human_addendum else ("20_detect.md",)
    image = FrameImage(data=ctx.frame_jpeg(frame, max_px=2560), ref=frame.id,
                       name_hint=ctx.media_stem(media))
    context = {
        "frame_ref": frame.id,
        "media_label": ctx.media_label(media),
        "timestamp_s": frame.timestamp_s,
        "case_notes": notes,
    }
    try:
        result = await ctx.vlm.complete_json(
            prompt_files=prompt_files, schema=DetectionResult, purpose="detect",
            thinking=thinking, images=[image], context=context,
            run_id=ctx.run_id, stage=3, frame_id=frame.id,
            media_file_id=media.id, max_output_tokens=6000)
    except ModelJSONError:
        raise
    payload: DetectionResult = result.value

    rows = []
    for item in payload.detections:
        bbox = _sanitize_bbox(item.bbox_2d)
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        needs_review = (item.confidence < review_thr
                        or item.category == "human_presence")
        rows.append(Detection(
            run_id=ctx.run_id, frame_id=frame.id, media_file_id=media.id,
            local_id=item.local_id, name_ar=item.name_ar, category=item.category,
            bbox_raw_json=item.bbox_2d,
            bbox_x1=x1 / 1000, bbox_y1=y1 / 1000,
            bbox_x2=x2 / 1000, bbox_y2=y2 / 1000,
            coord_space="rel1000", confidence=item.confidence,
            description_ar=item.description_ar,
            location_description_ar=item.location_description_ar,
            forensic_significance_ar=item.forensic_significance_ar,
            handling_recommendation_ar=item.handling_recommendation_ar,
            visible_text_ar=item.visible_text_ar,
            needs_human_review=needs_review, thinking_used=thinking,
            model_call_id=result.model_call_id,
            raw_json=item.model_dump()))
    async with ctx.factory() as session:
        session.add_all(rows)
        await session.commit()
    return len(rows)


async def run_photo(ctx: Ctx) -> None:
    """Photo mode — detect-only over one media file's frames. No aggregation,
    timeline, narrative, raster annotation, or report; the UI overlays boxes
    client-side from the stored coordinates."""
    async with ctx.factory() as session:
        case = (await session.execute(
            select(Case).where(Case.id == ctx.case_id))).scalar_one()
    media = await ctx.selected_media()
    if not media:
        raise RuntimeError("photo run has no media")
    m = media[0]
    async with ctx.factory() as session:
        frames = (await session.execute(
            select(Frame).where(Frame.media_file_id == m.id,
                                Frame.dropped_dedup.is_(False))
            .order_by(Frame.frame_index))).scalars().all()

    checkpoint = await ctx.get_checkpoint(3)
    done: list[str] = checkpoint.get("done", [])
    todo = [f for f in frames if f.id not in done]
    await ctx.set_step(3, total=len(frames), current=len(done))

    policy = (ctx.options.get("thinking_policy") or "always").lower()
    thinking = policy != "never"
    review_thr = float(ctx.thr("confidence_review_threshold",
                               ctx.settings.confidence_review_threshold))
    notes = (case.notes_ar or "")[:500]

    from app.pipeline.grounding import ground_detections

    for frame in todo:
        # human addendum always on: no triage signal exists in photo mode
        await detect_one(ctx, frame, m, thinking=thinking, human_addendum=True,
                         review_thr=review_thr, notes=notes)
        # decoupled grounding: detection said WHAT, now fix WHERE (accurate boxes)
        if ctx.settings.model_mode != "mock":
            async with ctx.factory() as session:
                dets = (await session.execute(
                    select(Detection).where(Detection.run_id == ctx.run_id,
                                            Detection.frame_id == frame.id))
                ).scalars().all()
            n = await ground_detections(ctx, frame, m, dets)
            log.info("photo grounding: re-grounded %d/%d boxes", n, len(dets))
        done.append(frame.id)
        await ctx.set_step(3, current=len(done), checkpoint={"done": done})


def _sanitize_bbox(bbox: list[int]) -> tuple[int, int, int, int] | None:
    if len(bbox) != 4:
        return None
    x1, y1, x2, y2 = (max(0, min(1000, int(v))) for v in bbox)
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2
