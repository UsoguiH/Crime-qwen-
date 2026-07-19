"""Mock-auth seed users (locked decision: no passwords in v1).

Real authentication swaps in behind the same User rows + session cookie —
nothing else in the system knows the difference.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

SEED_USERS = [
    {"username": "investigator", "display_name_ar": "المحقق الجنائي", "role": "investigator"},
    {"username": "reviewer", "display_name_ar": "المراجع الفني", "role": "reviewer"},
    {"username": "admin", "display_name_ar": "مشرف النظام", "role": "admin"},
]


async def seed_users(session: AsyncSession) -> None:
    existing = (await session.execute(select(User.username))).scalars().all()
    for spec in SEED_USERS:
        if spec["username"] not in existing:
            session.add(User(**spec))
    await session.commit()
