"""Mock mode: fixture-backed responses so the FULL pipeline runs offline.

Lookup per call:
  1. fixtures/by-name/<purpose>/<name_hint>.json   (name_hint = media file stem)
     - a detect fixture may be segmented by video time:
       {"segments": [{"from_s": 0, "to_s": 4, "result": {...DetectionResult...}}, ...]}
  2. fixtures/by-name/narrative/<section>.json for narrative sections
  3. safe defaults — honest "nothing detected" output; never fabricated evidence
     for unknown media. Aggregate default deterministically groups clusters that
     share (category, name) — mirroring what the real model does for the samples.
Fixtures that no longer validate fall through to defaults (rot-proof).
"""
import json
from pathlib import Path

from pydantic import BaseModel


def resolve(fixtures_dir: Path, purpose: str, name_hints: list[str],
            context: dict | None, schema: type[BaseModel]) -> BaseModel:
    for hint in name_hints:
        if not hint:
            continue
        path = fixtures_dir / "by-name" / purpose / f"{hint}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data = _pick_segment(data, purpose, context)
                return schema.model_validate(data)
            except Exception:
                continue
    section = (context or {}).get("section", "")
    if section:
        base = section.split(":", 1)[0]
        for name in (section, base):
            path = fixtures_dir / "by-name" / purpose / f"{name}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return schema.model_validate(data)
                except Exception:
                    break
    return schema.model_validate(_default(purpose, name_hints, context))


def _pick_segment(data: dict, purpose: str, context: dict | None) -> dict:
    if purpose != "detect" or "segments" not in data:
        return data
    ts = (context or {}).get("timestamp_s")
    segments = data["segments"]
    if ts is None:
        return segments[0]["result"]
    for seg in segments:
        if seg.get("from_s", 0) <= ts < seg.get("to_s", float("inf")):
            return seg["result"]
    return segments[-1]["result"]


def _default(purpose: str, name_hints: list[str], context: dict | None) -> dict:
    if purpose == "triage":
        refs = (context or {}).get("frame_refs", []) or [h for h in name_hints if h]
        return {"items": [
            {"frame_ref": ref, "relevance": 0.62,
             "scene_type_ar": "مشهد داخلي عام",
             "contains_evidence": True, "complexity": "low",
             "human_presence_suspected": False}
            for ref in refs
        ]}
    if purpose == "detect":
        return {"detections": [],
                "scene_summary_ar": "لم يتم رصد أدلة ظاهرة في هذا الإطار."}
    if purpose == "aggregate":
        clusters = (context or {}).get("clusters", [])
        groups: dict[tuple, list[dict]] = {}
        for c in clusters:
            groups.setdefault((c.get("category", ""), c.get("name_ar", "")), []).append(c)
        entities = []
        for (category, name), members in groups.items():
            first = members[0]
            entities.append({
                "member_cluster_ids": [m["cluster_id"] for m in members],
                "canonical_name_ar": name or "عنصر غير مسمى",
                "category": category or "trace",
                "description_ar": first.get("description_ar", ""),
                "forensic_significance_ar": "تُحدد الدلالة بعد المراجعة البشرية "
                                            "والتحليل المتخصص.",
                "handling_recommendation_ar": "التوثيق التصويري قبل أي تعامل، "
                                              "والرفع الفني وفق الأصول.",
                "merge_rationale_ar": ("جُمعت المشاهدات لتطابق الاسم والفئة "
                                       "(وضع المحاكاة)." if len(members) > 1 else ""),
            })
        return {"entities": entities}
    if purpose == "compare":
        return {"findings": []}
    if purpose == "refine":
        # keep the original box: not visible ⇒ caller preserves coarse coords
        return {"bbox_2d": [0, 0, 1000, 1000], "visible": False}
    if purpose == "qa":
        return {"answer_ar": "(وضع المحاكاة) لا يمكن الإجابة بدون نموذج فعلي؛ "
                             "فعّل الوضع السحابي أو المحلي لطرح الأسئلة.",
                "confidence": 0.0, "cannot_determine": True,
                "grounded_boxes": []}
    if purpose == "narrative":
        return {"content_ar": "(وضع المحاكاة) تعذّر إنشاء السرد التحليلي بالنموذج "
                              "اللغوي؛ تُعرض البيانات المهيكلة في جداول هذا التقرير، "
                              "وتبقى المراجعة البشرية المتخصصة واجبة قبل أي استخدام "
                              "قانوني.",
                "cited_entity_codes": []}
    raise ValueError(f"unknown mock purpose: {purpose}")


def record(fixtures_dir: Path, purpose: str, name_hint: str, payload: dict) -> None:
    path = fixtures_dir / "by-name" / purpose / f"{name_hint}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
