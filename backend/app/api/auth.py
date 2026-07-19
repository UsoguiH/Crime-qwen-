from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import COOKIE_NAME, MAX_AGE_S, encode_session
from app.config import Settings
from app.deps import (CurrentUser, get_current_user, get_factory, get_session,
                      settings_dep)
from app.db.models import User
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    user_id: str


@router.get("/users")
async def list_users(session: AsyncSession = Depends(get_session)):
    users = (await session.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.username)
    )).scalars().all()
    return [{"id": u.id, "username": u.username,
             "display_name_ar": u.display_name_ar, "role": u.role} for u in users]


@router.post("/login")
async def login(body: LoginBody, response: Response,
                session: AsyncSession = Depends(get_session),
                settings: Settings = Depends(settings_dep),
                factory=Depends(get_factory)):
    user = (await session.execute(
        select(User).where(User.id == body.user_id, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="مستخدم غير موجود")
    token = encode_session(settings.secret_key, user.id)
    response.set_cookie(COOKIE_NAME, token, max_age=MAX_AGE_S, httponly=True,
                        samesite="lax", path="/")
    await audit.append(factory, action="login", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="user",
                       object_id=user.id)
    return {"id": user.id, "username": user.username,
            "display_name_ar": user.display_name_ar, "role": user.role}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "username": user.username,
            "display_name_ar": user.display_name_ar, "role": user.role}
