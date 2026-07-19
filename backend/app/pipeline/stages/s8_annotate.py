"""Stage 8 — annotated copies + gallery crops + before/after pairs (originals untouched)."""
import asyncio
from collections import defaultdict

from sqlalchemy import select

from app.db.models import (Case, EntityObservation, EvidenceEntity, Frame,
                           TimelineEvent)
from app.pipeline.ctx import Ctx
from app.services.annotate import BoxSpec, annotate_image, crop_entity
from app.services.storage import derived_path


async def run(ctx: Ctx) -> None:
    async with ctx.factory() as session:
        case = (await session.execute(
            select(Case).where(Case.id == ctx.case_id))).scalar_one()
        entities = (await session.execute(
            select(EvidenceEntity).where(EvidenceEntity.run_id == ctx.run_id)
        )).scalars().all()
        obs = (await session.execute(
            select(EntityObservation).where(
                EntityObservation.entity_id.in_([e.id for e in entities] or [""])
            ))).scalars().all()
        frame_ids = {o.frame_id for o in obs}
        frames = {f.id: f for f in (await session.execute(
            select(Frame).where(Frame.id.in_(frame_ids or [""])))).scalars().all()}

    blur_on = case.face_blur_enabled
    ent_by_id = {e.id: e for e in entities}

    by_frame: dict[str, list[BoxSpec]] = defaultdict(list)
    for o in obs:
        e = ent_by_id[o.entity_id]
        by_frame[o.frame_id].append(BoxSpec(
            x1=o.bbox_x1, y1=o.bbox_y1, x2=o.bbox_x2, y2=o.bbox_y2,
            entity_seq=e.entity_seq, category=e.category,
            blur=blur_on and e.category == "human_presence"))

    total = len(by_frame) + len(entities)
    await ctx.set_step(8, total=total, current=0)
    done = 0

    for frame_id, boxes in by_frame.items():
        frame = frames.get(frame_id)
        if frame:
            src = ctx.abs_path(frame.stored_path)
            dst = derived_path(ctx.settings, "annotated", ctx.run_id,
                               "frames", f"{frame_id}.jpg")
            await asyncio.to_thread(annotate_image, src, dst, boxes)
        done += 1
        await ctx.set_step(8, current=done)

    obs_by_entity: dict[str, list[EntityObservation]] = defaultdict(list)
    for o in obs:
        obs_by_entity[o.entity_id].append(o)

    async with ctx.factory() as session:
        moved_ids = set((await session.execute(
            select(TimelineEvent.entity_id).where(
                TimelineEvent.run_id == ctx.run_id,
                TimelineEvent.event_type == "moved"))).scalars().all())

    for e in entities:
        e_obs = obs_by_entity[e.id]
        best = next((o for o in e_obs if o.detection_id == e.best_detection_id),
                    e_obs[0] if e_obs else None)
        if best is None:
            done += 1
            continue
        blur = blur_on and e.category == "human_presence"
        frame = frames.get(best.frame_id)
        if frame:
            src = ctx.abs_path(frame.stored_path)
            dst = derived_path(ctx.settings, "annotated", ctx.run_id,
                               "entities", f"{e.id}.jpg")
            spec = BoxSpec(best.bbox_x1, best.bbox_y1, best.bbox_x2, best.bbox_y2,
                           e.entity_seq, e.category, blur)
            await asyncio.to_thread(crop_entity, src, dst, spec)
        if e.id in moved_ids and len(e_obs) >= 2:
            seq = sorted(e_obs, key=lambda o: (o.timestamp_source_s or 0.0))
            first, moved = seq[0], next((o for o in seq if o.state == "moved"), seq[-1])
            for tag, o in (("before", first), ("after", moved)):
                frame = frames.get(o.frame_id)
                if frame:
                    src = ctx.abs_path(frame.stored_path)
                    dst = derived_path(ctx.settings, "annotated", ctx.run_id,
                                       "entities", f"{e.id}_{tag}.jpg")
                    spec = BoxSpec(o.bbox_x1, o.bbox_y1, o.bbox_x2, o.bbox_y2,
                                   e.entity_seq, e.category, blur)
                    await asyncio.to_thread(crop_entity, src, dst, spec)
        done += 1
        await ctx.set_step(8, current=done)
