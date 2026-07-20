"""Ask a natural-language question about a case's videos.

Retrieve the moment most relevant to the question (SigLIP over the index), then
answer it with the existing photo-QA path — self-consistency double-ask, honest
«cannot_determine», grounded boxes — on the retrieved frame. Returns the answer
with a bounding box AND the timestamp it was found at.
"""
import asyncio
import time
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.core import make_id
from app.db.models import MediaFile, VideoIndex
from app.modelclient.client import FrameImage, VLMClient
from app.pipeline.grounding import refine_answer_boxes
from app.schemas.model_io import PhotoAnswer, QueryTranslation
from app.services.storage import safe_resolve
from app.videosearch.embedder import get_embedder
from app.videosearch.indexer import sidecar_load
from app.videosearch.search import _extract_frame, topk_frames


def _similar(a: str, b: str) -> bool:
    ta = set(a.replace("،", " ").replace(".", " ").split())
    tb = set(b.replace("،", " ").replace(".", " ").split())
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.5


async def _ready_media(settings, factory, case_id, media_ids, embedder_name):
    wanted = set(media_ids or [])
    async with factory() as s:
        media = (await s.execute(
            select(MediaFile).where(MediaFile.case_id == case_id,
                                    MediaFile.kind == "video",
                                    MediaFile.excluded.is_(False)))).scalars().all()
        indexes = {i.media_file_id: i for i in (await s.execute(
            select(VideoIndex).where(VideoIndex.case_id == case_id))).scalars().all()}
    out = []
    for m in media:
        if wanted and m.id not in wanted:
            continue
        idx = indexes.get(m.id)
        if idx and idx.status == "ready" and idx.embedder_name == embedder_name:
            out.append((m, idx))
    return out


async def video_ask(settings: Settings, factory, vlm: VLMClient, case_id: str,
                    question_ar: str, media_ids: list[str] | None) -> dict:
    started = time.monotonic()
    embedder = await asyncio.to_thread(get_embedder, settings)

    # question → retrieval variants (English aids the CLIP-family text tower)
    try:
        tr = await vlm.complete_json(
            prompt_files=("95_query_translate.md",), schema=QueryTranslation,
            purpose="translate", context={"query_ar": question_ar},
            max_output_tokens=400)
        variants = [v.strip() for v in tr.value.english_variants if v.strip()][:4] \
            or [question_ar]
    except Exception:
        variants = [question_ar]
    query_vecs = await asyncio.to_thread(embedder.embed_texts, variants)

    ready = await _ready_media(settings, factory, case_id, media_ids, embedder.name)
    scored = []
    for media, idx in ready:
        vectors, timestamps, _ = await asyncio.to_thread(
            sidecar_load, safe_resolve(settings, idx.sidecar_path))
        for ts, sc in topk_frames(vectors, timestamps, query_vecs, 8):
            scored.append((sc, media, ts))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return {"answer_ar": "لا توجد فهارس فيديو جاهزة في هذه القضية لطرح سؤال عليها.",
                "confidence": 0.0, "cannot_determine": True, "boxes": [],
                "timestamp_s": None, "media_file_id": None, "media_label": "",
                "thumb_path": None, "retrieval_score": 0.0, "considered": []}

    best_score, media, ts = scored[0]
    img_bytes, thumb_rel = await _extract_frame(
        settings, safe_resolve(settings, media.stored_path), ts, f"ask-{make_id()}", 0)
    context = {"question_ar": question_ar,
               "media_label": media.source_label_ar or media.original_filename}

    async def one() -> PhotoAnswer | None:
        try:
            r = await vlm.complete_json(
                prompt_files=("70_photo_qa.md",), schema=PhotoAnswer, purpose="qa",
                thinking=True, images=[FrameImage(data=img_bytes,
                                                  ref=f"{media.id}@{ts:.1f}s")],
                context=context, media_file_id=media.id, max_output_tokens=2500)
            return r.value
        except Exception:
            return None

    a, b = await asyncio.gather(one(), one())   # self-consistency
    answers = [x for x in (a, b) if x is not None]
    if not answers:
        return {"answer_ar": "تعذّر الحصول على إجابة من النموذج.", "confidence": 0.0,
                "cannot_determine": True, "boxes": [], "timestamp_s": round(ts, 2),
                "media_file_id": media.id,
                "media_label": media.source_label_ar or media.original_filename,
                "thumb_path": thumb_rel, "retrieval_score": round(best_score, 4),
                "considered": []}
    if len(answers) == 2:
        primary = a if a.confidence >= b.confidence else b
        both = not a.cannot_determine and not b.cannot_determine
        agree = both and _similar(a.answer_ar, b.answer_ar)
        confidence = min(1.0, primary.confidence + 0.15) if agree \
            else max(a.confidence, b.confidence) * (0.7 if both else 1.0)
        cannot = a.cannot_determine and b.cannot_determine
    else:
        primary = answers[0]
        confidence = primary.confidence * 0.85
        cannot = primary.cannot_determine

    boxes = [{"label_ar": g.label_ar,
              "bbox": [g.bbox_2d[0] / 1000, g.bbox_2d[1] / 1000,
                       g.bbox_2d[2] / 1000, g.bbox_2d[3] / 1000]}
             for g in primary.grounded_boxes if len(g.bbox_2d) == 4]
    if boxes and not cannot:
        boxes = await refine_answer_boxes(vlm, img_bytes, boxes)

    return {
        "answer_ar": primary.answer_ar, "confidence": round(confidence, 3),
        "cannot_determine": cannot, "boxes": boxes,
        "timestamp_s": round(ts, 2), "media_file_id": media.id,
        "media_label": media.source_label_ar or media.original_filename,
        "thumb_path": thumb_rel, "retrieval_score": round(best_score, 4),
        "considered": [round(t, 1) for _, _, t in scored[:5]],
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
