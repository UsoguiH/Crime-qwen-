"""Stage 4 — canonical evidence entities.

Pass A (code): union-find pre-merge inside each (media, category) — IoU across
temporally adjacent analyzed frames. Pass B (model, thinking): merge clusters
across frames/sources. Validator guarantees NOTHING is dropped: unassigned
clusters become singleton entities, duplicate assignments keep first use.
"""
import logging

from sqlalchemy import delete, select

from app.db.models import (Detection, EntityObservation, EvidenceEntity, Frame,
                           MediaFile)
from app.pipeline.ctx import Ctx
from app.schemas.model_io import AggregateResult

log = logging.getLogger("athar.s4")


async def run(ctx: Ctx) -> None:
    async with ctx.factory() as session:
        rows = (await session.execute(
            select(Detection, Frame, MediaFile)
            .join(Frame, Detection.frame_id == Frame.id)
            .join(MediaFile, Detection.media_file_id == MediaFile.id)
            .where(Detection.run_id == ctx.run_id)
            .order_by(MediaFile.uploaded_at, Frame.frame_index))).all()
        # idempotent re-run
        entity_ids = (await session.execute(
            select(EvidenceEntity.id).where(EvidenceEntity.run_id == ctx.run_id)
        )).scalars().all()
        if entity_ids:
            await session.execute(delete(EntityObservation)
                                  .where(EntityObservation.entity_id.in_(entity_ids)))
            await session.execute(delete(EvidenceEntity)
                                  .where(EvidenceEntity.run_id == ctx.run_id))
            await session.commit()

    if not rows:
        await ctx.set_step(4, total=0, current=0)
        return
    await ctx.set_step(4, total=3, current=0)

    clusters = _premerge(ctx, rows)
    await ctx.set_step(4, current=1)

    merged_groups, rationale, validator = await _model_merge(ctx, clusters)
    await ctx.set_step(4, current=2)

    await _persist_entities(ctx, clusters, merged_groups, rationale)
    await ctx.set_step(4, current=3, checkpoint={"validator": validator})


def _premerge(ctx: Ctx, rows) -> list[dict]:
    iou_thr = float(ctx.thr("iou_merge_threshold", ctx.settings.iou_merge_threshold))
    frame_pos: dict[str, dict[str, int]] = {}
    for _d, f, m in rows:
        frame_pos.setdefault(m.id, {})
        if f.id not in frame_pos[m.id]:
            frame_pos[m.id][f.id] = len(frame_pos[m.id])

    items = [{"det": d, "frame": f, "media": m,
              "pos": frame_pos[m.id][f.id]} for d, f, m in rows]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    by_group: dict[tuple, list[int]] = {}
    for idx, it in enumerate(items):
        by_group.setdefault((it["media"].id, it["det"].category), []).append(idx)

    for members in by_group.values():
        for a_pos, i in enumerate(members):
            for j in members[a_pos + 1:]:
                a, b = items[i], items[j]
                gap = abs(a["pos"] - b["pos"])
                if gap == 0 or gap > 3:
                    continue
                if _iou(a["det"], b["det"]) >= iou_thr:
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(len(items)):
        groups.setdefault(find(idx), []).append(idx)

    clusters = []
    for n, member_idx in enumerate(sorted(groups.values(),
                                          key=lambda g: _sort_key(items, g)), start=1):
        dets = [items[i] for i in member_idx]
        first = dets[0]["det"]
        timestamps = [d["frame"].timestamp_s for d in dets
                      if d["frame"].timestamp_s is not None]
        clusters.append({
            "cluster_id": f"C{n}",
            "items": dets,
            "summary": {
                "cluster_id": f"C{n}",
                "name_ar": first.name_ar,
                "category": first.category,
                "source_label": ctx.media_label(dets[0]["media"]),
                "observations": len(dets),
                "first_ts_s": min(timestamps) if timestamps else None,
                "last_ts_s": max(timestamps) if timestamps else None,
                "confidence_max": max(d["det"].confidence for d in dets),
                "locations_ar": list(dict.fromkeys(
                    d["det"].location_description_ar for d in dets))[:3],
                "description_ar": first.description_ar[:400],
            },
        })
    return clusters


async def _model_merge(ctx: Ctx, clusters: list[dict]):
    known = {c["cluster_id"] for c in clusters}
    validator = {"missing": [], "duplicates": [], "unknown": []}
    if len(clusters) <= 1:
        return [[c["cluster_id"]] for c in clusters], {}, validator

    result = await ctx.vlm.complete_json(
        prompt_files=("30_aggregate.md",), schema=AggregateResult,
        purpose="aggregate", thinking=True,
        context={"clusters": [c["summary"] for c in clusters]},
        run_id=ctx.run_id, stage=4, max_output_tokens=8000)
    payload: AggregateResult = result.value

    seen: set[str] = set()
    groups: list[list[str]] = []
    rationale: dict[int, dict] = {}
    for entity in payload.entities:
        members = []
        for cid in entity.member_cluster_ids:
            if cid not in known:
                validator["unknown"].append(cid)
                continue
            if cid in seen:
                validator["duplicates"].append(cid)
                continue
            seen.add(cid)
            members.append(cid)
        if members:
            rationale[len(groups)] = entity.model_dump()
            groups.append(members)
    for c in clusters:  # nothing is ever dropped
        if c["cluster_id"] not in seen:
            validator["missing"].append(c["cluster_id"])
            groups.append([c["cluster_id"]])
    return groups, rationale, validator


async def _persist_entities(ctx: Ctx, clusters: list[dict],
                            groups: list[list[str]], rationale: dict) -> None:
    review_thr = float(ctx.thr("confidence_review_threshold",
                               ctx.settings.confidence_review_threshold))
    by_id = {c["cluster_id"]: c for c in clusters}

    def group_key(members):
        stamps = [c["summary"]["first_ts_s"] for cid in members
                  for c in [by_id[cid]] if c["summary"]["first_ts_s"] is not None]
        return (min(stamps) if stamps else float("inf"),
                members[0])

    ordered = sorted(range(len(groups)), key=lambda gi: group_key(groups[gi]))

    async with ctx.factory() as session:
        for seq, gi in enumerate(ordered, start=1):
            members = groups[gi]
            dets = [item for cid in members for item in by_id[cid]["items"]]
            spec = rationale.get(gi)
            best = max(dets, key=lambda d: d["det"].confidence)
            confidences = [d["det"].confidence for d in dets]
            category = spec["category"] if spec else best["det"].category
            needs_review = (any(d["det"].needs_human_review for d in dets)
                            or max(confidences) < review_thr
                            or category == "human_presence")
            entity = EvidenceEntity(
                run_id=ctx.run_id, entity_seq=seq,
                canonical_name_ar=(spec["canonical_name_ar"] if spec
                                   else best["det"].name_ar),
                category=category,
                description_ar=(spec["description_ar"] if spec
                                else best["det"].description_ar),
                forensic_significance_ar=(spec["forensic_significance_ar"] if spec
                                          else best["det"].forensic_significance_ar),
                handling_recommendation_ar=(spec["handling_recommendation_ar"] if spec
                                            else best["det"].handling_recommendation_ar),
                confidence_max=max(confidences),
                confidence_mean=sum(confidences) / len(confidences),
                needs_human_review=needs_review,
                best_frame_id=best["frame"].id,
                best_detection_id=best["det"].id,
                merge_rationale_ar=(spec["merge_rationale_ar"] if spec else ""),
                merged_from_json=[d["det"].id for d in dets],
            )
            session.add(entity)
            await session.flush()
            for d in dets:
                session.add(EntityObservation(
                    entity_id=entity.id, detection_id=d["det"].id,
                    frame_id=d["frame"].id, media_file_id=d["media"].id,
                    timestamp_source_s=d["frame"].timestamp_s,
                    bbox_x1=d["det"].bbox_x1, bbox_y1=d["det"].bbox_y1,
                    bbox_x2=d["det"].bbox_x2, bbox_y2=d["det"].bbox_y2,
                    confidence=d["det"].confidence))
        await session.commit()


def _iou(a: Detection, b: Detection) -> float:
    ix1, iy1 = max(a.bbox_x1, b.bbox_x1), max(a.bbox_y1, b.bbox_y1)
    ix2, iy2 = min(a.bbox_x2, b.bbox_x2), min(a.bbox_y2, b.bbox_y2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (a.bbox_x2 - a.bbox_x1) * (a.bbox_y2 - a.bbox_y1)
    area_b = (b.bbox_x2 - b.bbox_x1) * (b.bbox_y2 - b.bbox_y1)
    return inter / (area_a + area_b - inter)


def _sort_key(items, group):
    stamps = [items[i]["frame"].timestamp_s for i in group
              if items[i]["frame"].timestamp_s is not None]
    return (min(stamps) if stamps else float("inf"), min(group))
