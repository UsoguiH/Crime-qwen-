from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import COOKIE_NAME, decode_session
from app.config import Settings, get_settings
from app.db import engine as db_engine
from app.db.models import User


@dataclass
class CurrentUser:
    id: str
    username: str
    display_name_ar: str
    role: str


async def get_session():
    factory = db_engine.session_factory()
    async with factory() as session:
        yield session


def settings_dep() -> Settings:
    return get_settings()


async def get_current_user(request: Request,
                           session: AsyncSession = Depends(get_session),
                           settings: Settings = Depends(settings_dep)) -> CurrentUser:
    token = request.cookies.get(COOKIE_NAME)
    uid = decode_session(settings.secret_key, token) if token else None
    if not uid:
        raise HTTPException(status_code=401, detail="غير مسجل الدخول")
    user = (await session.execute(
        select(User).where(User.id == uid, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="جلسة غير صالحة")
    return CurrentUser(id=user.id, username=user.username,
                       display_name_ar=user.display_name_ar, role=user.role)


def require_role(*roles: str):
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
        return user
    return _check


def get_worker(request: Request):
    return request.app.state.worker


def get_vlm(request: Request):
    return request.app.state.vlm


def get_factory(request: Request):
    return db_engine.session_factory()
