from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import CurrentUser, get_current_user, get_session
from app.db.models import AuditLog
from app.services import audit as audit_svc

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(action: str | None = None, object_id: str | None = None,
                     actor_user_id: str | None = None,
                     limit: int = 100, offset: int = 0,
                     session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(get_current_user)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if object_id:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    rows = (await session.execute(
        stmt.offset(offset).limit(min(limit, 500)))).scalars().all()
    return [{"id": r.id, "ts": r.ts.isoformat(), "actor_label": r.actor_label,
             "action": r.action, "object_type": r.object_type,
             "object_id": r.object_id, "detail": r.detail_json,
             "entry_hash": r.entry_hash} for r in rows]


@router.get("/verify")
async def verify(session: AsyncSession = Depends(get_session),
                 user: CurrentUser = Depends(get_current_user)):
    return await audit_svc.verify(session)


@router.get("/head")
async def head(session: AsyncSession = Depends(get_session),
               user: CurrentUser = Depends(get_current_user)):
    return {"head": await audit_svc.head(session)}
