from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import (CurrentUser, get_current_user, get_factory, get_session,
                      require_role)
from app.db.models import AnalysisRun, Case, EvidenceEntity, MediaFile
from app.services import audit
from app.services.hijri import hijri_str

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseCreate(BaseModel):
    case_number: str
    title_ar: str
    location_ar: str = ""
    investigator_name_ar: str = ""
    notes_ar: str = ""
    incident_date_gregorian: str | None = None  # YYYY-MM-DD


class CasePatch(BaseModel):
    title_ar: str | None = None
    location_ar: str | None = None
    investigator_name_ar: str | None = None
    notes_ar: str | None = None
    incident_date_gregorian: str | None = None
    status: str | None = None
    face_blur_enabled: bool | None = None


def _case_dict(c: Case, extra: dict | None = None) -> dict:
    d = {
        "id": c.id, "case_number": c.case_number, "title_ar": c.title_ar,
        "location_ar": c.location_ar, "investigator_name_ar": c.investigator_name_ar,
        "notes_ar": c.notes_ar,
        "incident_date_gregorian": c.incident_date_gregorian,
        "incident_date_hijri": c.incident_date_hijri,
        "status": c.status, "face_blur_enabled": c.face_blur_enabled,
        "created_at": c.created_at.isoformat(),
    }
    if extra:
        d.update(extra)
    return d


def _hijri_for(gregorian: str | None) -> str | None:
    if not gregorian:
        return None
    try:
        return hijri_str(date.fromisoformat(gregorian))
    except ValueError:
        return None


@router.get("")
async def list_cases(status: str | None = None, q: str | None = None,
                     session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(get_current_user)):
    stmt = select(Case).order_by(Case.created_at.desc())
    if status:
        stmt = stmt.where(Case.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Case.title_ar.like(like) | Case.case_number.like(like))
    cases = (await session.execute(stmt)).scalars().all()
    ids = [c.id for c in cases] or [""]
    media_counts = dict((await session.execute(
        select(MediaFile.case_id, func.count(MediaFile.id))
        .where(MediaFile.case_id.in_(ids), MediaFile.excluded.is_(False))
        .group_by(MediaFile.case_id))).all())
    runs = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.case_id.in_(ids))
        .order_by(AnalysisRun.started_at))).scalars().all()
    last_run: dict[str, AnalysisRun] = {}
    for r in runs:
        last_run[r.case_id] = r
    pending = dict((await session.execute(
        select(AnalysisRun.case_id, func.count(EvidenceEntity.id))
        .join(EvidenceEntity, EvidenceEntity.run_id == AnalysisRun.id)
        .where(AnalysisRun.case_id.in_(ids),
               EvidenceEntity.needs_human_review.is_(True),
               EvidenceEntity.review_status == "pending")
        .group_by(AnalysisRun.case_id))).all())
    return [
        _case_dict(c, {
            "media_count": media_counts.get(c.id, 0),
            "last_run": ({"id": last_run[c.id].id,
                          "status": last_run[c.id].status,
                          "run_number": last_run[c.id].run_number}
                         if c.id in last_run else None),
            "pending_review": pending.get(c.id, 0),
        }) for c in cases
    ]


@router.post("", status_code=201)
async def create_case(body: CaseCreate,
                      session: AsyncSession = Depends(get_session),
                      user: CurrentUser = Depends(require_role("investigator")),
                      factory=Depends(get_factory)):
    exists = (await session.execute(
        select(Case).where(Case.case_number == body.case_number))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="رقم القضية مستخدم من قبل")
    case = Case(**body.model_dump(),
                incident_date_hijri=_hijri_for(body.incident_date_gregorian),
                created_by=user.id)
    session.add(case)
    await session.commit()
    await audit.append(factory, action="case.create", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="case",
                       object_id=case.id,
                       detail={"case_number": case.case_number})
    return _case_dict(case)


@router.get("/{case_id}")
async def get_case(case_id: str, session: AsyncSession = Depends(get_session),
                   user: CurrentUser = Depends(get_current_user)):
    case = (await session.execute(
        select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="قضية غير موجودة")
    runs = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.case_id == case_id)
        .order_by(AnalysisRun.run_number.desc()))).scalars().all()
    return _case_dict(case, {
        "runs": [{"id": r.id, "run_number": r.run_number, "status": r.status,
                  "model_mode": r.model_mode,
                  "started_at": r.started_at.isoformat(),
                  "finished_at": r.finished_at.isoformat() if r.finished_at else None}
                 for r in runs],
    })


@router.patch("/{case_id}")
async def patch_case(case_id: str, body: CasePatch,
                     session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(require_role("investigator")),
                     factory=Depends(get_factory)):
    case = (await session.execute(
        select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="قضية غير موجودة")
    changes = body.model_dump(exclude_none=True)
    if "face_blur_enabled" in changes and user.role != "admin":
        raise HTTPException(status_code=403,
                            detail="تعديل التمويه من صلاحية المشرف فقط")
    for key, value in changes.items():
        setattr(case, key, value)
    if "incident_date_gregorian" in changes:
        case.incident_date_hijri = _hijri_for(case.incident_date_gregorian)
    await session.commit()
    await audit.append(factory, action="case.update", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="case",
                       object_id=case.id, detail=changes)
    return _case_dict(case)
