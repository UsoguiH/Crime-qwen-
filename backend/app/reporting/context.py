"""Assembles the full report context (shared by PDF, DOCX, and live HTML preview)."""
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.core import utcnow
from app.db.models import (CATEGORY_NAMES_AR, AnalysisRun, Case,
                           ComparisonFinding, Detection, EntityObservation,
                           EvidenceEntity, Frame, MediaFile, Narrative,
                           SourceOffset, TimelineEvent, TriageResult, User)
from app.services import audit
from app.services.hijri import dual_date_str
from app.services.numerals import (entity_code, entity_label_ar, fmt_percent,
                                   fmt_seconds, to_arabic_indic)

REVIEW_STATUS_AR = {"pending": "بانتظار المراجعة", "confirmed": "مؤكد",
                    "rejected": "مرفوض", "edited": "معدّل ومعتمد"}
SOURCE_TYPE_AR = {"cctv": "كاميرا مراقبة", "bodycam": "كاميرا جسدية",
                  "handheld": "تصوير يدوي", "photo": "صورة فوتوغرافية",
                  "other": "مصدر آخر"}
OFFSET_METHOD_AR = {"auto_metadata": "آلي من البيانات الوصفية",
                    "manual": "ضبط يدوي", "unanchored": "غير مرسوّى"}
DISCLAIMER = ("تحليل بمساعدة الذكاء الاصطناعي — يتطلب تحقيق خبير مؤهل قبل أي "
              "استخدام قانوني. درجات الثقة تعبّر عن تقدير النموذج الآلي ولا تمثل "
              "احتمالات إحصائية معتمدة.")


async def build_report_context(settings: Settings, factory: async_sessionmaker,
                               run_id: str, generated_by: str | None = None) -> dict:
    async with factory() as session:
        run = (await session.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id))).scalar_one()
        case = (await session.execute(
            select(Case).where(Case.id == run.case_id))).scalar_one()
        media = (await session.execute(
            select(MediaFile).where(MediaFile.case_id == case.id,
                                    MediaFile.excluded.is_(False))
            .order_by(MediaFile.uploaded_at))).scalars().all()
        entities = (await session.execute(
            select(EvidenceEntity).where(EvidenceEntity.run_id == run_id)
            .order_by(EvidenceEntity.entity_seq))).scalars().all()
        obs = (await session.execute(
            select(EntityObservation).where(
                EntityObservation.entity_id.in_([e.id for e in entities] or [""])
            ))).scalars().all()
        events = (await session.execute(
            select(TimelineEvent).where(TimelineEvent.run_id == run_id)
            .order_by(TimelineEvent.timestamp_global_s.nullslast(),
                      TimelineEvent.timestamp_source_s))).scalars().all()
        max_version = (await session.execute(
            select(func.max(Narrative.version)).where(Narrative.run_id == run_id)
        )).scalar_one()
        narratives = (await session.execute(
            select(Narrative).where(Narrative.run_id == run_id,
                                    Narrative.version == (max_version or 0))
        )).scalars().all()
        comparisons = (await session.execute(
            select(ComparisonFinding).where(ComparisonFinding.run_id == run_id)
        )).scalars().all()
        offsets = (await session.execute(
            select(SourceOffset).where(SourceOffset.run_id == run_id)
        )).scalars().all()
        frames_analyzed = (await session.execute(
            select(func.count(TriageResult.id)).where(
                TriageResult.run_id == run_id,
                TriageResult.selected_for_detection.is_(True)))).scalar_one()
        det_count = (await session.execute(
            select(func.count(Detection.id)).where(Detection.run_id == run_id)
        )).scalar_one()
        frames = {f.id: f for f in (await session.execute(
            select(Frame).where(Frame.media_file_id.in_([m.id for m in media] or [""]))
        )).scalars().all()}
        user_label = ""
        if generated_by:
            u = (await session.execute(
                select(User).where(User.id == generated_by))).scalar_one_or_none()
            user_label = u.display_name_ar if u else ""
        audit_head = await audit.head(session)

    label = {m.id: (m.source_label_ar or m.original_filename) for m in media}
    obs_by_entity = defaultdict(list)
    for o in obs:
        obs_by_entity[o.entity_id].append(o)

    def _exists(rel: str) -> str | None:
        return rel if (settings.data_dir / rel).exists() else None

    entities_ctx = []
    for e in entities:
        e_obs = obs_by_entity[e.id]
        stamps = [o.timestamp_source_s for o in e_obs if o.timestamp_source_s is not None]
        best_frame = frames.get(e.best_frame_id)
        best_det_location = ""
        for o in e_obs:
            if o.detection_id == e.best_detection_id:
                break
        entities_ctx.append({
            "code": entity_code(e.entity_seq),
            "label_ar": entity_label_ar(e.entity_seq),
            "name_ar": e.canonical_name_ar,
            "category": e.category,
            "category_ar": CATEGORY_NAMES_AR.get(e.category, e.category),
            "confidence_pct": fmt_percent(e.confidence_max),
            "confidence_val": e.confidence_max,
            "needs_review": e.needs_human_review,
            "review_status": e.review_status,
            "review_status_ar": REVIEW_STATUS_AR.get(e.review_status, e.review_status),
            "review_note_ar": e.review_note_ar,
            "description_ar": e.description_ar,
            "forensic_significance_ar": e.forensic_significance_ar,
            "handling_recommendation_ar": e.handling_recommendation_ar,
            "merge_rationale_ar": e.merge_rationale_ar,
            "sources": sorted({label.get(o.media_file_id, "") for o in e_obs}),
            "observations": len(e_obs),
            "first_ts": fmt_seconds(min(stamps)) if stamps else None,
            "last_ts": fmt_seconds(max(stamps)) if stamps else None,
            "crop": _exists(f"derived/annotated/{run_id}/entities/{e.id}.jpg"),
            "before": _exists(f"derived/annotated/{run_id}/entities/{e.id}_before.jpg"),
            "after": _exists(f"derived/annotated/{run_id}/entities/{e.id}_after.jpg"),
            "best_frame_annotated": _exists(
                f"derived/annotated/{run_id}/frames/{e.best_frame_id}.jpg")
            if e.best_frame_id else None,
        })

    counts = defaultdict(int)
    for e in entities:
        counts[CATEGORY_NAMES_AR.get(e.category, e.category)] += 1

    media_ctx = []
    for m in media:
        exif = m.exif_json or {}
        annotated = sorted(
            f"derived/annotated/{run_id}/frames/{fid}.jpg"
            for fid, f in frames.items()
            if f.media_file_id == m.id
            and (settings.data_dir / f"derived/annotated/{run_id}/frames/{fid}.jpg").exists()
        )[:4]
        media_ctx.append({
            "id": m.id,
            "label": label[m.id],
            "filename": m.original_filename,
            "kind_ar": "فيديو" if m.kind == "video" else "صورة",
            "source_type_ar": SOURCE_TYPE_AR.get(m.source_type, m.source_type),
            "sha256": m.content_sha256,
            "size_ar": _size_ar(m.size_bytes),
            "duration": fmt_seconds(m.duration_s) if m.duration_s else None,
            "creation_time": (m.metadata_creation_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                              if m.metadata_creation_time else None),
            "device": f"{exif.get('Make', '')} {exif.get('Model', '')}".strip() or None,
            "gps": exif.get("gps"),
            "annotated_frames": annotated,
        })

    narratives_ctx = {}
    per_source_narratives = []
    for n in narratives:
        if n.section.startswith("per_source:"):
            mid = n.section.split(":", 1)[1]
            per_source_narratives.append({"media_id": mid,
                                          "label": label.get(mid, ""),
                                          "content": n.content_ar})
        else:
            narratives_ctx[n.section] = n.content_ar

    today = utcnow().date()
    incident = None
    if case.incident_date_gregorian:
        try:
            incident = date.fromisoformat(case.incident_date_gregorian)
        except ValueError:
            incident = None

    snapshot = run.model_snapshot_json or {}
    return {
        "case": {
            "case_number": case.case_number,
            "case_number_ar": to_arabic_indic(case.case_number),
            "title_ar": case.title_ar,
            "location_ar": case.location_ar,
            "investigator_name_ar": case.investigator_name_ar,
            "notes_ar": case.notes_ar,
            "incident_dual_date": dual_date_str(incident) if incident else None,
        },
        "run": {
            "run_number_ar": to_arabic_indic(run.run_number),
            "status": run.status,
            "model_mode": run.model_mode,
            "model_fast": snapshot.get("model_fast", ""),
            "model_thinking": snapshot.get("model_thinking", ""),
            "provider": snapshot.get("provider", run.model_mode),
            "prompt_hashes": [{"file": k, "sha_short": v[:12]}
                              for k, v in sorted((run.prompt_hashes_json or {}).items())],
            "thresholds": run.thresholds_json or {},
        },
        "generated": {
            "dual_date": dual_date_str(today),
            "time": utcnow().strftime("%H:%M UTC"),
            "by_label": user_label,
        },
        "stats": {
            "sources_ar": to_arabic_indic(len(media)),
            "frames_analyzed_ar": to_arabic_indic(frames_analyzed),
            "detections_ar": to_arabic_indic(det_count),
            "entities_ar": to_arabic_indic(len(entities)),
            "pending_review_ar": to_arabic_indic(
                sum(1 for e in entities
                    if e.needs_human_review and e.review_status == "pending")),
        },
        "counts_by_category": dict(counts),
        "entities": entities_ctx,
        "events": [{"text": e.description_ar} for e in events],
        "comparisons": [{"kind": c.kind, "detail_ar": c.detail_ar,
                         "confidence_pct": fmt_percent(c.confidence)}
                        for c in comparisons],
        "narratives": narratives_ctx,
        "per_source_narratives": per_source_narratives,
        "media": media_ctx,
        "offsets": [{"source_label": label.get(o.media_file_id, ""),
                     "offset_ar": to_arabic_indic(round(o.offset_seconds, 1)),
                     "method_ar": OFFSET_METHOD_AR.get(o.method, o.method)}
                    for o in offsets if o.media_file_id in label],
        "audit_head": audit_head,
        "audit_head_short": audit_head[:16],
        "disclaimer": DISCLAIMER,
    }


def _size_ar(size: int) -> str:
    for unit, div in (("ج.ب", 1 << 30), ("م.ب", 1 << 20), ("ك.ب", 1 << 10)):
        if size >= div:
            return to_arabic_indic(round(size / div, 1)) + " " + unit
    return to_arabic_indic(size) + " بايت"
