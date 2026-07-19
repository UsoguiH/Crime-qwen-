"""Stage 5 — timeline (pure code, deterministic, no model).

Global clock: earliest metadata_creation_time = epoch; each source's offset =
creation_time − epoch (`auto_metadata`), manual overrides preserved, everything
else `unanchored` (offset 0, flagged in UI/report as unreliable across sources).
Events: first_seen / moved (centroid shift) / disappeared / reappeared / last_seen.
"""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, select, update

from app.db.models import (EntityObservation, EvidenceEntity, Frame, MediaFile,
                           SourceOffset, TimelineEvent, TriageResult)
from app.pipeline.ctx import Ctx
from app.services.numerals import entity_label_ar, fmt_seconds

EVENT_TEXT = {
    "first_seen": "أول ظهور",
    "moved": "تغيّر الموضع",
    "disappeared": "اختفاء من مجال الرؤية",
    "reappeared": "معاودة الظهور",
    "last_seen": "آخر رصد",
}


async def run(ctx: Ctx) -> None:
    media = await ctx.selected_media()
    await ctx.set_step(5, total=4, current=0)
    offsets = await _resolve_offsets(ctx, media)
    await ctx.set_step(5, current=1)
    await _apply_global_times(ctx, offsets, media)
    await ctx.set_step(5, current=2)
    await _build_events(ctx, offsets, media)
    await ctx.set_step(5, current=4)


async def _resolve_offsets(ctx: Ctx, media: list[MediaFile]) -> dict[str, SourceOffset]:
    anchored = [m for m in media if m.metadata_creation_time is not None]
    epoch: datetime | None = min(
        (m.metadata_creation_time for m in anchored), default=None)

    async with ctx.factory() as session:
        existing = {o.media_file_id: o for o in (await session.execute(
            select(SourceOffset).where(SourceOffset.run_id == ctx.run_id)
        )).scalars().all()}
        for m in media:
            row = existing.get(m.id)
            if row is not None and row.method == "manual":
                continue  # investigator's judgment survives rebuilds
            if m.metadata_creation_time is not None and epoch is not None:
                offset = (m.metadata_creation_time - epoch).total_seconds()
                method = "auto_metadata"
            else:
                offset, method = 0.0, "unanchored"
            if row is None:
                row = SourceOffset(run_id=ctx.run_id, media_file_id=m.id,
                                   offset_seconds=offset, method=method)
                session.add(row)
                existing[m.id] = row
            else:
                row.offset_seconds = offset
                row.method = method
        await session.commit()
        return existing


async def _apply_global_times(ctx: Ctx, offsets: dict[str, SourceOffset],
                              media: list[MediaFile]) -> None:
    kinds = {m.id: m.kind for m in media}
    async with ctx.factory() as session:
        entity_ids = (await session.execute(
            select(EvidenceEntity.id).where(EvidenceEntity.run_id == ctx.run_id)
        )).scalars().all()
        if not entity_ids:
            return
        obs = (await session.execute(
            select(EntityObservation)
            .where(EntityObservation.entity_id.in_(entity_ids)))).scalars().all()
        for o in obs:
            off = offsets.get(o.media_file_id)
            offset = off.offset_seconds if off else 0.0
            anchored = off is not None and off.method != "unanchored"
            if o.timestamp_source_s is not None:
                o.timestamp_global_s = offset + o.timestamp_source_s
            else:  # still image: position = its creation time when anchored
                o.timestamp_global_s = offset if anchored else None
                if kinds.get(o.media_file_id) == "image" and not anchored:
                    o.timestamp_global_s = None
        await session.commit()


async def _build_events(ctx: Ctx, offsets: dict[str, SourceOffset],
                        media: list[MediaFile]) -> None:
    move_thr = float(ctx.thr("move_centroid_threshold",
                             ctx.settings.move_centroid_threshold))
    media_by_id = {m.id: m for m in media}

    async with ctx.factory() as session:
        await session.execute(delete(TimelineEvent)
                              .where(TimelineEvent.run_id == ctx.run_id))
        entities = (await session.execute(
            select(EvidenceEntity).where(EvidenceEntity.run_id == ctx.run_id)
            .order_by(EvidenceEntity.entity_seq))).scalars().all()
        if not entities:
            await session.commit()
            return
        all_obs = (await session.execute(
            select(EntityObservation)
            .where(EntityObservation.entity_id.in_([e.id for e in entities]))
        )).scalars().all()
        frames = {f.id: f for f in (await session.execute(
            select(Frame).where(Frame.media_file_id.in_(list(media_by_id))))
        ).scalars().all()}
        analyzed = (await session.execute(
            select(TriageResult.frame_id).where(
                TriageResult.run_id == ctx.run_id,
                TriageResult.selected_for_detection.is_(True)))).scalars().all()

        # analyzed-frame ordering per media → gap/disappearance detection
        frame_pos: dict[str, dict[str, int]] = defaultdict(dict)
        frame_seq: dict[str, list[str]] = defaultdict(list)
        for fid in analyzed:
            f = frames.get(fid)
            if f is None:
                continue
            frame_seq[f.media_file_id].append(fid)
        for mid, fids in frame_seq.items():
            fids.sort(key=lambda fid: frames[fid].frame_index)
            for pos, fid in enumerate(fids):
                frame_pos[mid][fid] = pos

        obs_by_entity: dict[str, list[EntityObservation]] = defaultdict(list)
        for o in all_obs:
            obs_by_entity[o.entity_id].append(o)

        for entity in entities:
            label = f"«{entity.canonical_name_ar}» ({entity_label_ar(entity.entity_seq)})"
            events = _entity_events(entity, obs_by_entity[entity.id], frames,
                                    frame_pos, media_by_id, offsets, move_thr, label)
            for ev in events:
                session.add(ev)
                if ev.event_type == "moved" and ev.source_observation_ids_json:
                    await session.execute(
                        update(EntityObservation)
                        .where(EntityObservation.id.in_(ev.source_observation_ids_json))
                        .values(state="moved"))
        await session.commit()


def _entity_events(entity, obs, frames, frame_pos, media_by_id, offsets,
                   move_thr, label) -> list[TimelineEvent]:
    def sort_key(o):
        g = o.timestamp_global_s
        return (0, g) if g is not None else (1, o.timestamp_source_s or 0.0)

    ordered = sorted(obs, key=sort_key)
    if not ordered:
        return []
    events: list[TimelineEvent] = []

    def add(event_type, o, ts_source=None, ts_global=None, obs_ids=None):
        media = media_by_id.get(o.media_file_id)
        src_label = (media.source_label_ar or media.original_filename) if media else ""
        ts = ts_source if ts_source is not None else o.timestamp_source_s
        when = f" عند {fmt_seconds(ts)}" if ts is not None else ""
        events.append(TimelineEvent(
            run_id=entity.run_id, entity_id=entity.id, event_type=event_type,
            timestamp_global_s=ts_global if ts_global is not None else o.timestamp_global_s,
            timestamp_source_s=ts,
            media_file_id=o.media_file_id, frame_id=o.frame_id,
            description_ar=f"{label}: {EVENT_TEXT[event_type]} في المصدر «{src_label}»{when}.",
            source_observation_ids_json=obs_ids or []))

    add("first_seen", ordered[0])

    by_media: dict[str, list[EntityObservation]] = defaultdict(list)
    for o in ordered:
        by_media[o.media_file_id].append(o)

    video_obs_present = False
    for mid, seq in by_media.items():
        positions = frame_pos.get(mid, {})
        seq = sorted(seq, key=lambda o: positions.get(o.frame_id, 0))
        if any(o.timestamp_source_s is not None for o in seq):
            video_obs_present = True
        for prev, curr in zip(seq, seq[1:]):
            dx = ((prev.bbox_x1 + prev.bbox_x2) - (curr.bbox_x1 + curr.bbox_x2)) / 2
            dy = ((prev.bbox_y1 + prev.bbox_y2) - (curr.bbox_y1 + curr.bbox_y2)) / 2
            if (dx * dx + dy * dy) ** 0.5 > move_thr:
                add("moved", curr, obs_ids=[curr.id])
            gap = positions.get(curr.frame_id, 0) - positions.get(prev.frame_id, 0)
            if gap > 2:
                missed = _frame_at(frames, mid, positions,
                                   positions.get(prev.frame_id, 0) + 1)
                if missed is not None:
                    off = offsets.get(mid)
                    offset = off.offset_seconds if off else 0.0
                    tsrc = missed.timestamp_s
                    events.append(TimelineEvent(
                        run_id=entity.run_id, entity_id=entity.id,
                        event_type="disappeared",
                        timestamp_global_s=(offset + tsrc) if tsrc is not None else None,
                        timestamp_source_s=tsrc, media_file_id=mid,
                        frame_id=missed.id,
                        description_ar=f"{label}: {EVENT_TEXT['disappeared']}"
                                       f"{f' عند {fmt_seconds(tsrc)}' if tsrc is not None else ''}.",
                        source_observation_ids_json=[]))
                add("reappeared", curr)
        # disappeared for good: ≥2 analyzed frames after the last sighting
        last = seq[-1]
        last_pos = positions.get(last.frame_id, 0)
        if positions and (max(positions.values()) - last_pos) >= 2:
            missed = _frame_at(frames, mid, positions, last_pos + 1)
            if missed is not None:
                off = offsets.get(mid)
                offset = off.offset_seconds if off else 0.0
                tsrc = missed.timestamp_s
                events.append(TimelineEvent(
                    run_id=entity.run_id, entity_id=entity.id,
                    event_type="disappeared",
                    timestamp_global_s=(offset + tsrc) if tsrc is not None else None,
                    timestamp_source_s=tsrc, media_file_id=mid, frame_id=missed.id,
                    description_ar=f"{label}: {EVENT_TEXT['disappeared']}"
                                   f"{f' عند {fmt_seconds(tsrc)}' if tsrc is not None else ''}.",
                    source_observation_ids_json=[]))

    if video_obs_present and len(ordered) > 1:
        add("last_seen", ordered[-1])
    return events


def _frame_at(frames, media_id, positions, pos):
    for fid, p in positions.items():
        if p == pos and frames.get(fid) is not None:
            return frames[fid]
    return None
