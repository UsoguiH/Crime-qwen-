from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import (CurrentUser, get_current_user, get_factory, get_session,
                      get_worker, require_role, settings_dep)
from app.db.models import (CATEGORY_NAMES_AR, Detection, EntityObservation,
                           EvidenceEntity, Frame, MediaFile, Narrative,
                           ComparisonFinding, SourceOffset, TimelineEvent)
from app.pipeline import worker as worker_mod
from app.services import audit
from app.services.numerals import entity_code, entity_label_ar

router = APIRouter(tags=["results"])


class OffsetPut(BaseModel):
    offset_seconds: float
    note_ar: str = ""


def _entity_dict(e: EvidenceEntity, settings: Settings,
                 sources: list[str] | None = None, obs_count: int = 0) -> dict:
    base = f"derived/annotated/{e.run_id}/entities/{e.id}"
    return {
        "id": e.id, "run_id": e.run_id, "entity_seq": e.entity_seq,
        "code": entity_code(e.entity_seq), "label_ar": entity_label_ar(e.entity_seq),
        "canonical_name_ar": e.canonical_name_ar, "category": e.category,
        "category_ar": CATEGORY_NAMES_AR.get(e.category, e.category),
        "description_ar": e.description_ar,
        "forensic_significance_ar": e.forensic_significance_ar,
        "handling_recommendation_ar": e.handling_recommendation_ar,
        "merge_rationale_ar": e.merge_rationale_ar,
        "confidence_max": e.confidence_max, "confidence_mean": e.confidence_mean,
        "needs_human_review": e.needs_human_review,
        "review_status": e.review_status, "review_note_ar": e.review_note_ar,
        "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
        "best_frame_id": e.best_frame_id,
        "has_crop": (settings.data_dir / f"{base}.jpg").exists(),
        "has_before_after": (settings.data_dir / f"{base}_before.jpg").exists(),
        "sources": sources or [], "observations": obs_count,
    }


@router.get("/runs/{run_id}/detections")
async def list_detections(run_id: str, media_id: str | None = None,
                          frame_id: str | None = None, category: str | None = None,
                          session: AsyncSession = Depends(get_session),
                          user: CurrentUser = Depends(get_current_user)):
    stmt = select(Detection).where(Detection.run_id == run_id)
    if media_id:
        stmt = stmt.where(Detection.media_file_id == media_id)
    if frame_id:
        stmt = stmt.where(Detection.frame_id == frame_id)
    if category:
        stmt = stmt.where(Detection.category == category)
    rows = (await session.execute(stmt.order_by(Detection.created_at))).scalars().all()
    return [{"id": d.id, "frame_id": d.frame_id, "media_file_id": d.media_file_id,
             "name_ar": d.name_ar, "category": d.category,
             "bbox": [d.bbox_x1, d.bbox_y1, d.bbox_x2, d.bbox_y2],
             "confidence": d.confidence, "needs_human_review": d.needs_human_review,
             "description_ar": d.description_ar,
             "location_description_ar": d.location_description_ar,
             "visible_text_ar": d.visible_text_ar,
             "thinking_used": d.thinking_used} for d in rows]


@router.get("/runs/{run_id}/entities")
async def list_entities(run_id: str, category: str | None = None,
                        review_status: str | None = None,
                        needs_review: bool | None = None,
                        session: AsyncSession = Depends(get_session),
                        settings: Settings = Depends(settings_dep),
                        user: CurrentUser = Depends(get_current_user)):
    stmt = select(EvidenceEntity).where(EvidenceEntity.run_id == run_id)
    if category:
        stmt = stmt.where(EvidenceEntity.category == category)
    if review_status:
        stmt = stmt.where(EvidenceEntity.review_status == review_status)
    if needs_review is not None:
        stmt = stmt.where(EvidenceEntity.needs_human_review.is_(needs_review))
    rows = (await session.execute(
        stmt.order_by(EvidenceEntity.entity_seq))).scalars().all()

    obs = (await session.execute(
        select(EntityObservation.entity_id, MediaFile.source_label_ar,
               MediaFile.original_filename)
        .join(MediaFile, EntityObservation.media_file_id == MediaFile.id)
        .where(EntityObservation.entity_id.in_([e.id for e in rows] or [""]))
    )).all()
    sources: dict[str, set] = {}
    counts: dict[str, int] = {}
    for eid, label, filename in obs:
        sources.setdefault(eid, set()).add(label or filename)
        counts[eid] = counts.get(eid, 0) + 1
    return [_entity_dict(e, settings, sorted(sources.get(e.id, set())),
                         counts.get(e.id, 0)) for e in rows]


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, session: AsyncSession = Depends(get_session),
                     settings: Settings = Depends(settings_dep),
                     user: CurrentUser = Depends(get_current_user)):
    e = (await session.execute(
        select(EvidenceEntity).where(EvidenceEntity.id == entity_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="دليل غير موجود")
    obs = (await session.execute(
        select(EntityObservation, Frame, MediaFile)
        .join(Frame, EntityObservation.frame_id == Frame.id)
        .join(MediaFile, EntityObservation.media_file_id == MediaFile.id)
        .where(EntityObservation.entity_id == entity_id)
        .order_by(EntityObservation.timestamp_source_s))).all()
    events = (await session.execute(
        select(TimelineEvent).where(TimelineEvent.entity_id == entity_id)
        .order_by(TimelineEvent.timestamp_global_s))).scalars().all()
    labels = sorted({(m.source_label_ar or m.original_filename) for _o, _f, m in obs})
    return {
        **_entity_dict(e, settings, labels, len(obs)),
        "observations": [{
            "id": o.id, "frame_id": o.frame_id, "media_file_id": m.id,
            "media_label": m.source_label_ar or m.original_filename,
            "timestamp_source_s": o.timestamp_source_s,
            "timestamp_global_s": o.timestamp_global_s,
            "bbox": [o.bbox_x1, o.bbox_y1, o.bbox_x2, o.bbox_y2],
            "confidence": o.confidence, "state": o.state,
        } for o, _f, m in obs],
        "events": [{"event_type": ev.event_type,
                    "timestamp_source_s": ev.timestamp_source_s,
                    "timestamp_global_s": ev.timestamp_global_s,
                    "description_ar": ev.description_ar,
                    "frame_id": ev.frame_id} for ev in events],
    }


@router.get("/runs/{run_id}/timeline")
async def timeline(run_id: str, media_id: str | None = None,
                   session: AsyncSession = Depends(get_session),
                   user: CurrentUser = Depends(get_current_user)):
    stmt = (select(TimelineEvent, EvidenceEntity)
            .join(EvidenceEntity, TimelineEvent.entity_id == EvidenceEntity.id)
            .where(TimelineEvent.run_id == run_id))
    if media_id:
        stmt = stmt.where(TimelineEvent.media_file_id == media_id)
    rows = (await session.execute(
        stmt.order_by(TimelineEvent.timestamp_global_s.nullslast(),
                      TimelineEvent.timestamp_source_s))).all()
    return [{
        "id": ev.id, "entity_id": e.id, "entity_seq": e.entity_seq,
        "label_ar": entity_label_ar(e.entity_seq),
        "name_ar": e.canonical_name_ar, "category": e.category,
        "event_type": ev.event_type,
        "timestamp_source_s": ev.timestamp_source_s,
        "timestamp_global_s": ev.timestamp_global_s,
        "media_file_id": ev.media_file_id, "frame_id": ev.frame_id,
        "description_ar": ev.description_ar,
    } for ev, e in rows]


@router.get("/runs/{run_id}/offsets")
async def get_offsets(run_id: str, session: AsyncSession = Depends(get_session),
                      user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(SourceOffset, MediaFile)
        .join(MediaFile, SourceOffset.media_file_id == MediaFile.id)
        .where(SourceOffset.run_id == run_id))).all()
    return [{"media_file_id": o.media_file_id,
             "media_label": m.source_label_ar or m.original_filename,
             "offset_seconds": o.offset_seconds, "method": o.method,
             "note_ar": o.note_ar} for o, m in rows]


@router.put("/runs/{run_id}/offsets/{media_id}")
async def put_offset(run_id: str, media_id: str, body: OffsetPut,
                     session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(require_role("investigator")),
                     factory=Depends(get_factory)):
    row = (await session.execute(
        select(SourceOffset).where(SourceOffset.run_id == run_id,
                                   SourceOffset.media_file_id == media_id))
    ).scalar_one_or_none()
    if row is None:
        row = SourceOffset(run_id=run_id, media_file_id=media_id)
        session.add(row)
    row.offset_seconds = body.offset_seconds
    row.method = "manual"
    row.set_by = user.id
    row.note_ar = body.note_ar
    await session.commit()
    await audit.append(factory, action="offsets.update", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="run",
                       object_id=run_id,
                       detail={"media_id": media_id,
                               "offset_seconds": body.offset_seconds})
    return {"ok": True, "hint_ar": "أعد بناء الجدول الزمني لتطبيق الإزاحة الجديدة"}


@router.post("/runs/{run_id}/timeline/rebuild", status_code=202)
async def rebuild_timeline(run_id: str,
                           session: AsyncSession = Depends(get_session),
                           user: CurrentUser = Depends(require_role("investigator")),
                           factory=Depends(get_factory),
                           worker=Depends(get_worker)):
    await worker_mod.enqueue(session, "rebuild_timeline", run_id)
    await session.commit()
    worker.notify()
    await audit.append(factory, action="timeline.rebuild", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="run",
                       object_id=run_id)
    return {"ok": True}


@router.get("/runs/{run_id}/comparisons")
async def comparisons(run_id: str, session: AsyncSession = Depends(get_session),
                      user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(ComparisonFinding).where(ComparisonFinding.run_id == run_id)
    )).scalars().all()
    return [{"id": c.id, "kind": c.kind, "entity_id": c.entity_id,
             "detail_ar": c.detail_ar, "confidence": c.confidence} for c in rows]


@router.get("/runs/{run_id}/narratives")
async def narratives(run_id: str, session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(get_current_user)):
    max_version = (await session.execute(
        select(func.max(Narrative.version)).where(Narrative.run_id == run_id)
    )).scalar_one()
    if not max_version:
        return []
    rows = (await session.execute(
        select(Narrative).where(Narrative.run_id == run_id,
                                Narrative.version == max_version))).scalars().all()
    return [{"section": n.section, "content_ar": n.content_ar,
             "cited": n.cited_entity_ids_json or [],
             "version": n.version} for n in rows]
