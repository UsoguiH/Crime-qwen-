"""Stage 6 — cross-source comparison (thinking mode; only for multi-source runs)."""
from collections import defaultdict

from sqlalchemy import delete, select

from app.db.models import (ComparisonFinding, EntityObservation, EvidenceEntity,
                           SourceOffset, TimelineEvent)
from app.pipeline.ctx import Ctx
from app.schemas.model_io import ComparisonResult
from app.services.numerals import entity_code, entity_label_ar, fmt_seconds


async def run(ctx: Ctx) -> None:
    media = await ctx.selected_media()
    async with ctx.factory() as session:
        entities = (await session.execute(
            select(EvidenceEntity).where(EvidenceEntity.run_id == ctx.run_id)
            .order_by(EvidenceEntity.entity_seq))).scalars().all()
        obs = (await session.execute(
            select(EntityObservation).where(
                EntityObservation.entity_id.in_([e.id for e in entities] or [""])
            ))).scalars().all()
        await session.execute(delete(ComparisonFinding)
                              .where(ComparisonFinding.run_id == ctx.run_id))
        await session.commit()

    sources_with_obs = {o.media_file_id for o in obs}
    if len(sources_with_obs) < 2:
        await ctx.set_step(6, status="skipped")
        return
    await ctx.set_step(6, total=1, current=0)

    async with ctx.factory() as session:
        offsets = (await session.execute(
            select(SourceOffset).where(SourceOffset.run_id == ctx.run_id)
        )).scalars().all()
        events = (await session.execute(
            select(TimelineEvent).where(TimelineEvent.run_id == ctx.run_id)
            .order_by(TimelineEvent.timestamp_global_s))).scalars().all()

    media_by_id = {m.id: m for m in media}
    label = {m.id: ctx.media_label(m) for m in media}

    per_entity_sources = defaultdict(lambda: defaultdict(list))
    for o in obs:
        per_entity_sources[o.entity_id][o.media_file_id].append(o)

    entities_ctx = []
    for e in entities:
        srcs = []
        for mid, olist in per_entity_sources[e.id].items():
            stamps = [x.timestamp_source_s for x in olist if x.timestamp_source_s is not None]
            srcs.append({
                "source_label": label.get(mid, ""),
                "observations": len(olist),
                "first_ts": fmt_seconds(min(stamps)) if stamps else None,
                "last_ts": fmt_seconds(max(stamps)) if stamps else None,
            })
        entities_ctx.append({
            "code": entity_code(e.entity_seq),
            "label_ar": entity_label_ar(e.entity_seq),
            "name_ar": e.canonical_name_ar,
            "category": e.category,
            "sources": srcs,
        })

    context = {
        "entities": entities_ctx,
        "offsets": [{"source_label": label.get(o.media_file_id, ""),
                     "offset_seconds": o.offset_seconds, "method": o.method}
                    for o in offsets if o.media_file_id in media_by_id],
        "timeline_events": [e.description_ar for e in events][:80],
    }

    result = await ctx.vlm.complete_json(
        prompt_files=("40_compare.md",), schema=ComparisonResult,
        purpose="compare", thinking=True, context=context,
        run_id=ctx.run_id, stage=6, max_output_tokens=6000)
    payload: ComparisonResult = result.value

    known = {entity_code(e.entity_seq): e for e in entities}
    async with ctx.factory() as session:
        for finding in payload.findings:
            codes = [c for c in finding.entity_codes if c in known]
            if not codes and finding.entity_codes:
                continue  # model referenced unknown entities → drop
            session.add(ComparisonFinding(
                run_id=ctx.run_id, kind=finding.kind,
                entity_id=known[codes[0]].id if codes else None,
                media_file_ids_json=[],
                detail_ar=finding.detail_ar, confidence=finding.confidence,
                model_call_id=result.model_call_id,
                raw_json=finding.model_dump()))
        await session.commit()
    await ctx.set_step(6, current=1)
