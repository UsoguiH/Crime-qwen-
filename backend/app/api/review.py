from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import utcnow
from app.deps import (CurrentUser, get_factory, get_session, require_role,
                      settings_dep)
from app.api.results import _entity_dict
from app.db.models import EvidenceEntity
from app.services import audit

router = APIRouter(tags=["review"])

EDITABLE = {"canonical_name_ar", "category", "description_ar",
            "forensic_significance_ar", "handling_recommendation_ar"}


class ReviewBody(BaseModel):
    action: str  # confirm | reject | edit
    edits: dict | None = None
    note_ar: str = ""


@router.get("/runs/{run_id}/review-queue")
async def review_queue(run_id: str, session: AsyncSession = Depends(get_session),
                       settings: Settings = Depends(settings_dep),
                       user: CurrentUser = Depends(require_role("reviewer"))):
    rows = (await session.execute(
        select(EvidenceEntity).where(
            EvidenceEntity.run_id == run_id,
            EvidenceEntity.needs_human_review.is_(True),
            EvidenceEntity.review_status == "pending")
        .order_by(EvidenceEntity.confidence_max.asc()))).scalars().all()
    return [_entity_dict(e, settings) for e in rows]


@router.post("/entities/{entity_id}/review")
async def review_entity(entity_id: str, body: ReviewBody,
                        session: AsyncSession = Depends(get_session),
                        settings: Settings = Depends(settings_dep),
                        user: CurrentUser = Depends(require_role("reviewer")),
                        factory=Depends(get_factory)):
    e = (await session.execute(
        select(EvidenceEntity).where(EvidenceEntity.id == entity_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="دليل غير موجود")
    if body.action not in ("confirm", "reject", "edit"):
        raise HTTPException(status_code=400, detail="إجراء غير معروف")

    if body.action == "confirm":
        e.review_status = "confirmed"
    elif body.action == "reject":
        e.review_status = "rejected"
    else:
        edits = {k: v for k, v in (body.edits or {}).items() if k in EDITABLE}
        if not edits:
            raise HTTPException(status_code=400, detail="لا تعديلات صالحة")
        originals = {k: getattr(e, k) for k in edits}
        for k, v in edits.items():
            setattr(e, k, v)
        e.review_edits_json = {"originals": originals, "edits": edits}
        e.review_status = "edited"

    e.review_note_ar = body.note_ar
    e.reviewed_by = user.id
    e.reviewed_at = utcnow()
    await session.commit()
    await audit.append(factory, action=f"entity.review.{body.action}",
                       actor_user_id=user.id, actor_label=user.display_name_ar,
                       object_type="entity", object_id=entity_id,
                       detail={"note_ar": body.note_ar,
                               **({"edits": body.edits} if body.action == "edit" else {})})
    return _entity_dict(e, settings)
