"""Stage 2 — fast triage (non-thinking, batched). FAIL-OPEN: a broken batch marks
its frames selected — over-analysis is safer than a silently skipped evidence frame."""
import logging

from sqlalchemy import select

from app.db.models import Frame, MediaFile, TriageResult
from app.modelclient.client import BudgetExceeded, FrameImage
from app.pipeline.ctx import Ctx
from app.schemas.model_io import TriageBatch

log = logging.getLogger("athar.s2")
BATCH = 4


async def run(ctx: Ctx) -> None:
    media = await ctx.selected_media()
    media_by_id = {m.id: m for m in media}
    async with ctx.factory() as session:
        frames = (await session.execute(
            select(Frame).where(Frame.media_file_id.in_(list(media_by_id)),
                                Frame.dropped_dedup.is_(False))
            .order_by(Frame.media_file_id, Frame.frame_index))).scalars().all()
        done_ids = set((await session.execute(
            select(TriageResult.frame_id).where(TriageResult.run_id == ctx.run_id)
        )).scalars().all())

    todo = [f for f in frames if f.id not in done_ids]
    await ctx.set_step(2, total=len(frames), current=len(frames) - len(todo))
    relevance_thr = float(ctx.thr("triage_relevance_threshold",
                                  ctx.settings.triage_relevance_threshold))

    processed = len(frames) - len(todo)
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        rows = await _triage_batch(ctx, batch, media_by_id, relevance_thr)
        async with ctx.factory() as session:
            session.add_all(rows)
            await session.commit()
        processed += len(batch)
        await ctx.set_step(2, current=processed)


async def _triage_batch(ctx: Ctx, batch: list[Frame], media_by_id: dict,
                        relevance_thr: float) -> list[TriageResult]:
    images = [FrameImage(data=ctx.frame_jpeg(f, max_px=1024), ref=f.id,
                         name_hint=ctx.media_stem(media_by_id[f.media_file_id]))
              for f in batch]
    try:
        result = await ctx.vlm.complete_json(
            prompt_files=("10_triage.md",), schema=TriageBatch, purpose="triage",
            thinking=False, images=images,
            context={"frame_refs": [f.id for f in batch]},
            run_id=ctx.run_id, stage=2)
        items = {item.frame_ref: item for item in result.value.items}
        call_id = result.model_call_id
    except BudgetExceeded:
        raise
    except Exception as exc:
        log.warning("triage batch fail-open: %s", exc)
        items, call_id = {}, None

    rows = []
    for frame in batch:
        media: MediaFile = media_by_id[frame.media_file_id]
        item = items.get(frame.id)
        if item is None:  # fail-open default
            rows.append(TriageResult(
                run_id=ctx.run_id, frame_id=frame.id, relevance=relevance_thr,
                scene_type_ar="", contains_evidence=True, complexity="low",
                human_presence_suspected=False, selected_for_detection=True,
                model_call_id=call_id, raw_json={"fail_open": True}))
            continue
        selected = (media.kind == "image" or item.relevance >= relevance_thr
                    or item.contains_evidence)
        rows.append(TriageResult(
            run_id=ctx.run_id, frame_id=frame.id, relevance=item.relevance,
            scene_type_ar=item.scene_type_ar,
            contains_evidence=item.contains_evidence, complexity=item.complexity,
            human_presence_suspected=item.human_presence_suspected,
            selected_for_detection=selected, model_call_id=call_id,
            raw_json=item.model_dump()))
    return rows
