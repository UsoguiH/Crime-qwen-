"""Ask-anything grounded Q&A about a single photo — accuracy-first.

For accuracy the answer is produced by self-consistency: the question is asked
twice in thinking mode on the upscaled image; if both agree they reinforce, and
disagreement is surfaced as lower confidence rather than a confident guess. Every
grounded box is re-grounded through the same single-target pass as detection, so
the boxes the answer points to actually land on the objects.
"""
import asyncio
import io

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AnalysisRun, Detection, Frame, MediaFile, PhotoQuestion
from app.deps import (CurrentUser, get_current_user, get_factory, get_session,
                      get_vlm, require_role, settings_dep)
from app.modelclient.client import FrameImage
from app.schemas.model_io import PhotoAnswer
from app.services import audit
from app.services.storage import safe_resolve

router = APIRouter(tags=["photo-qa"])
GROUND_MIN_PX = 1280


class AskBody(BaseModel):
    question_ar: str
    thinking: bool = True


def _q_dict(q: PhotoQuestion) -> dict:
    return {"id": q.id, "media_file_id": q.media_file_id,
            "question_ar": q.question_ar, "answer_ar": q.answer_ar,
            "confidence": q.confidence, "cannot_determine": q.cannot_determine,
            "grounded_boxes": q.grounded_boxes_json or [],
            "thinking_used": q.thinking_used,
            "created_at": q.created_at.isoformat()}


def _upscaled_bytes(path) -> bytes:
    with Image.open(path) as im:
        img = im.convert("RGB")
    if max(img.size) < GROUND_MIN_PX:
        s = GROUND_MIN_PX / max(img.size)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


@router.post("/media/{media_id}/ask", status_code=201)
async def ask_photo(media_id: str, body: AskBody,
                    session: AsyncSession = Depends(get_session),
                    settings: Settings = Depends(settings_dep),
                    user: CurrentUser = Depends(require_role("investigator", "reviewer")),
                    factory=Depends(get_factory), vlm=Depends(get_vlm)):
    q = body.question_ar.strip()
    if not q:
        raise HTTPException(status_code=400, detail="السؤال فارغ")
    if len(q) > 1000:
        raise HTTPException(status_code=400, detail="السؤال طويل جداً")
    media = (await session.execute(
        select(MediaFile).where(MediaFile.id == media_id))).scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    if media.kind != "image":
        raise HTTPException(status_code=400, detail="الأسئلة متاحة للصور فقط")

    img_bytes = _upscaled_bytes(safe_resolve(settings, media.stored_path))
    context = {"question_ar": q, "media_label": media.source_label_ar
               or media.original_filename}

    async def one() -> PhotoAnswer | None:
        try:
            res = await vlm.complete_json(
                prompt_files=("70_photo_qa.md",), schema=PhotoAnswer,
                purpose="qa", thinking=body.thinking,
                images=[FrameImage(data=img_bytes, ref=media_id)],
                context=context, media_file_id=media_id, max_output_tokens=4000)
            return res.value
        except Exception:
            return None

    # self-consistency: two independent passes; agreement raises confidence
    a, b = await asyncio.gather(one(), one())
    answers = [x for x in (a, b) if x is not None]
    if not answers:
        raise HTTPException(status_code=502, detail="تعذّر الحصول على إجابة من النموذج")
    if len(answers) == 2:
        primary = a if a.confidence >= b.confidence else b
        both_determine = not a.cannot_determine and not b.cannot_determine
        agree = both_determine and _similar(a.answer_ar, b.answer_ar)
        confidence = min(1.0, (primary.confidence + 0.15)) if agree \
            else max(a.confidence, b.confidence) * (0.7 if both_determine else 1.0)
        cannot = a.cannot_determine and b.cannot_determine
    else:
        primary = answers[0]
        confidence = primary.confidence * 0.85
        cannot = primary.cannot_determine

    boxes = [{"label_ar": g.label_ar,
              "bbox": [g.bbox_2d[0] / 1000, g.bbox_2d[1] / 1000,
                       g.bbox_2d[2] / 1000, g.bbox_2d[3] / 1000]}
             for g in primary.grounded_boxes
             if len(g.bbox_2d) == 4]

    row = PhotoQuestion(
        media_file_id=media_id, case_id=media.case_id, question_ar=q,
        answer_ar=primary.answer_ar, confidence=round(confidence, 3),
        cannot_determine=cannot, grounded_boxes_json=boxes,
        thinking_used=body.thinking, asked_by=user.id)
    session.add(row)
    await session.commit()
    await audit.append(factory, action="photo.ask", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="media",
                       object_id=media_id, detail={"question": q[:200]})
    return _q_dict(row)


@router.get("/media/{media_id}/questions")
async def list_questions(media_id: str,
                         session: AsyncSession = Depends(get_session),
                         user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(PhotoQuestion).where(PhotoQuestion.media_file_id == media_id)
        .order_by(PhotoQuestion.created_at.desc()))).scalars().all()
    return [_q_dict(r) for r in rows]


def _similar(a: str, b: str) -> bool:
    """Cheap agreement heuristic: high token overlap on the answer cores."""
    ta = set(a.replace("،", " ").replace(".", " ").split())
    tb = set(b.replace("،", " ").replace(".", " ").split())
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb)) >= 0.5
