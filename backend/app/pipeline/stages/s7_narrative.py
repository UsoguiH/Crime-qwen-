"""Stage 7 — narrative sections (thinking), generated ONLY from curated JSON.

Anti-fabrication contract: the validator rejects any section that cites an
evidence code/label not present in this run; one corrective re-ask, then the
section renders a safe placeholder instead of unverified prose.
"""
import logging
import re
from collections import defaultdict

from sqlalchemy import func, select

from app.db.models import (Case, ComparisonFinding, Detection, EntityObservation,
                           EvidenceEntity, Frame, MediaFile, Narrative,
                           SourceOffset, TimelineEvent, TriageResult)
from app.pipeline.ctx import Ctx
from app.schemas.model_io import NarrativeSection
from app.services.numerals import (entity_code, entity_label_ar, fmt_percent,
                                   fmt_seconds, to_arabic_indic)

log = logging.getLogger("athar.s7")

CODE_RE = re.compile(r"E-(\d{3})")
LABEL_RE = re.compile(r"دليل\s+([٠-٩]{1,4})")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

REVIEW_STATUS_AR = {"pending": "بانتظار المراجعة", "confirmed": "مؤكد",
                    "rejected": "مرفوض", "edited": "معدّل ومعتمد"}

FALLBACK = ("تعذّر توليد هذا القسم آلياً وفق ضوابط التحقق من الإسناد؛ "
            "تُعرض البيانات المهيكلة الموثقة في جداول هذا التقرير، "
            "وتبقى المراجعة البشرية المتخصصة واجبة.")


async def run(ctx: Ctx) -> None:
    data = await _collect(ctx)
    sections: list[tuple[str, str, dict]] = [
        ("exec_summary", "50_narrative_exec.md", data["base"]),
        ("timeline", "51_narrative_timeline.md",
         {**data["base"], "timeline_events": data["events"]}),
        ("spatial", "52_narrative_spatial.md",
         {**data["base"], "locations": data["locations"]}),
        ("review_needed", "53_narrative_review.md",
         {**data["base"], "review_items": data["review_items"]}),
        ("recommendations", "54_narrative_recommendations.md", data["base"]),
    ]
    for m in data["media_summaries"]:
        sections.append((f"per_source:{m['media_id']}", "55_narrative_per_source.md",
                         {**data["base"], "source": m}))

    async with ctx.factory() as session:
        version = ((await session.execute(
            select(func.max(Narrative.version)).where(Narrative.run_id == ctx.run_id)
        )).scalar_one() or 0) + 1

    await ctx.set_step(7, total=len(sections), current=0)
    known_codes = data["known_codes"]

    for i, (section, prompt_file, context) in enumerate(sections, start=1):
        content, cited, report, call_id = await _generate(
            ctx, section, prompt_file, context, known_codes)
        async with ctx.factory() as session:
            session.add(Narrative(
                run_id=ctx.run_id, section=section, content_ar=content,
                cited_entity_ids_json=cited, validator_report_json=report,
                model_call_id=call_id, version=version))
            await session.commit()
        await ctx.set_step(7, current=i)


async def _generate(ctx: Ctx, section: str, prompt_file: str, context: dict,
                    known_codes: set[str]):
    feedback = None
    call_id = None
    for attempt in range(2):
        payload = dict(context, section=section)
        if feedback:
            payload["validator_feedback"] = feedback
        try:
            result = await ctx.vlm.complete_json(
                prompt_files=(prompt_file,), schema=NarrativeSection,
                purpose="narrative", thinking=True, context=payload,
                run_id=ctx.run_id, stage=7, max_output_tokens=4000)
        except Exception as exc:
            log.warning("narrative %s failed: %s", section, exc)
            return FALLBACK, [], {"error": str(exc)[:500]}, call_id
        call_id = result.model_call_id
        value: NarrativeSection = result.value
        bad = _validate_citations(value, known_codes)
        if not bad:
            return (value.content_ar,
                    sorted(set(value.cited_entity_codes) & known_codes),
                    {"ok": True, "attempt": attempt + 1}, call_id)
        feedback = ("رُصدت إشارات إلى أدلة غير موجودة في بيانات المهمة: "
                    f"{', '.join(sorted(bad))}. "
                    "أعد الصياغة مستخدماً فقط الأدلة المذكورة في البيانات.")
    return FALLBACK, [], {"ok": False, "invalid_citations": sorted(bad)}, call_id


def _validate_citations(value: NarrativeSection, known_codes: set[str]) -> set[str]:
    bad = {c for c in value.cited_entity_codes if c not in known_codes}
    for match in CODE_RE.finditer(value.content_ar):
        code = f"E-{match.group(1)}"
        if code not in known_codes:
            bad.add(code)
    for match in LABEL_RE.finditer(value.content_ar):
        seq = int(match.group(1).translate(_AR_DIGITS))
        code = f"E-{seq:03d}"
        if code not in known_codes:
            bad.add(f"دليل {match.group(1)}")
    return bad


async def _collect(ctx: Ctx) -> dict:
    media = await ctx.selected_media()
    label = {m.id: ctx.media_label(m) for m in media}
    async with ctx.factory() as session:
        case = (await session.execute(
            select(Case).where(Case.id == ctx.case_id))).scalar_one()
        entities = (await session.execute(
            select(EvidenceEntity).where(EvidenceEntity.run_id == ctx.run_id)
            .order_by(EvidenceEntity.entity_seq))).scalars().all()
        obs = (await session.execute(
            select(EntityObservation).where(
                EntityObservation.entity_id.in_([e.id for e in entities] or [""])
            ))).scalars().all()
        events = (await session.execute(
            select(TimelineEvent).where(TimelineEvent.run_id == ctx.run_id)
            .order_by(TimelineEvent.timestamp_global_s))).scalars().all()
        comparisons = (await session.execute(
            select(ComparisonFinding).where(ComparisonFinding.run_id == ctx.run_id)
        )).scalars().all()
        offsets = (await session.execute(
            select(SourceOffset).where(SourceOffset.run_id == ctx.run_id)
        )).scalars().all()
        frames_analyzed = (await session.execute(
            select(func.count(TriageResult.id)).where(
                TriageResult.run_id == ctx.run_id,
                TriageResult.selected_for_detection.is_(True)))).scalar_one()
        det_count = (await session.execute(
            select(func.count(Detection.id)).where(Detection.run_id == ctx.run_id)
        )).scalar_one()
        frame_media = {f.id: f.media_file_id for f in (await session.execute(
            select(Frame).where(Frame.media_file_id.in_(list(label) or [""])))
        ).scalars().all()}

    from app.db.models import CATEGORY_NAMES_AR
    obs_by_entity = defaultdict(list)
    for o in obs:
        obs_by_entity[o.entity_id].append(o)

    entities_ctx = []
    for e in entities:
        e_obs = obs_by_entity[e.id]
        stamps = [o.timestamp_source_s for o in e_obs if o.timestamp_source_s is not None]
        entities_ctx.append({
            "code": entity_code(e.entity_seq),
            "label_ar": entity_label_ar(e.entity_seq),
            "name_ar": e.canonical_name_ar,
            "category_ar": CATEGORY_NAMES_AR.get(e.category, e.category),
            "confidence": fmt_percent(e.confidence_max),
            "needs_human_review": e.needs_human_review,
            "review_status_ar": REVIEW_STATUS_AR.get(e.review_status, e.review_status),
            "forensic_significance_ar": e.forensic_significance_ar,
            "sources": sorted({label.get(o.media_file_id, "") for o in e_obs}),
            "first_ts": fmt_seconds(min(stamps)) if stamps else None,
            "last_ts": fmt_seconds(max(stamps)) if stamps else None,
        })

    counts = defaultdict(int)
    for e in entities:
        counts[CATEGORY_NAMES_AR.get(e.category, e.category)] += 1

    media_summaries = []
    for m in media:
        m_entities = [entity_label_ar(e.entity_seq) for e in entities
                      if any(o.media_file_id == m.id for o in obs_by_entity[e.id])]
        meta_bits = {}
        if m.metadata_creation_time:
            meta_bits["creation_time"] = m.metadata_creation_time.isoformat()
        exif = m.exif_json or {}
        if exif.get("gps"):
            meta_bits["gps"] = exif["gps"]
        if exif.get("Model"):
            meta_bits["device"] = f"{exif.get('Make', '')} {exif.get('Model', '')}".strip()
        media_summaries.append({
            "media_id": m.id,
            "source_label": label[m.id],
            "kind": m.kind,
            "duration_s": m.duration_s,
            "frames_analyzed": sum(1 for fid, mid in frame_media.items()
                                   if mid == m.id),
            "entities": m_entities,
            "metadata": meta_bits,
        })

    base = {
        "case": {"case_number": case.case_number, "title_ar": case.title_ar,
                 "location_ar": case.location_ar},
        "stats": {
            "sources": len(media),
            "frames_analyzed": frames_analyzed,
            "detections": det_count,
            "entities_total": len(entities),
            "entities_by_category": dict(counts),
            "pending_review": sum(1 for e in entities
                                  if e.needs_human_review and e.review_status == "pending"),
        },
        "entities": entities_ctx,
        "comparisons": [{"kind": c.kind, "detail_ar": c.detail_ar,
                         "confidence": c.confidence} for c in comparisons],
        "offsets": [{"source_label": label.get(o.media_file_id, ""),
                     "offset_seconds": o.offset_seconds, "method": o.method}
                    for o in offsets if o.media_file_id in label],
    }
    return {
        "base": base,
        "events": [e.description_ar for e in events],
        "locations": [{"label_ar": entity_label_ar(e.entity_seq),
                       "name_ar": e.canonical_name_ar,
                       "location_ar": next(
                           (d for d in [e.description_ar] if d), "")}
                      for e in entities],
        "review_items": [ec for ec in entities_ctx if ec["needs_human_review"]],
        "media_summaries": media_summaries,
        "known_codes": {entity_code(e.entity_seq) for e in entities},
    }
