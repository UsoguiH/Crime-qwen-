"""Hash-chained, append-only audit log.

entry_hash = SHA256(prev_hash ‖ canonical_json(payload)) — any later edit or
deletion of a row breaks every hash after it, so `verify()` proves integrity.
Appends run on their own short session under a single lock (strict ordering),
and are written only after the audited action has committed.
"""
import asyncio
import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import utcnow
from app.db.models import AuditLog
from app.services.hashing import canonical_json

GENESIS = "0" * 64
_lock = asyncio.Lock()


def _entry_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(payload)).encode("utf-8")).hexdigest()


def _iso(dt) -> str:
    """tz-normalized timestamp for hashing: SQLite round-trips datetimes as
    naive strings, so hash the naive UTC wall time both at append and verify."""
    return dt.replace(tzinfo=None).isoformat()


def _payload(row_ts, actor_user_id, actor_label, action, object_type, object_id, detail) -> dict:
    return {
        "ts": _iso(row_ts),
        "actor_user_id": actor_user_id or "",
        "actor_label": actor_label or "",
        "action": action,
        "object_type": object_type or "",
        "object_id": object_id or "",
        "detail": detail or {},
    }


async def append(
    factory: async_sessionmaker,
    *,
    action: str,
    actor_user_id: str | None = None,
    actor_label: str = "",
    object_type: str = "",
    object_id: str = "",
    detail: dict | None = None,
) -> str:
    async with _lock:
        async with factory() as session:
            last = (await session.execute(
                select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
            )).scalar_one_or_none()
            prev = last.entry_hash if last else GENESIS
            row_ts = utcnow()
            payload = _payload(row_ts, actor_user_id, actor_label, action,
                               object_type, object_id, detail)
            entry = AuditLog(
                ts=row_ts,
                actor_user_id=actor_user_id,
                actor_label=actor_label,
                action=action,
                object_type=object_type,
                object_id=object_id,
                detail_json=detail or {},
                prev_hash=prev,
                entry_hash=_entry_hash(prev, payload),
            )
            session.add(entry)
            await session.commit()
            return entry.entry_hash


async def head(session: AsyncSession) -> str:
    last = (await session.execute(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
    )).scalar_one_or_none()
    return last.entry_hash if last else GENESIS


async def verify(session: AsyncSession) -> dict:
    total = (await session.execute(select(func.count(AuditLog.id)))).scalar_one()
    prev = GENESIS
    first_broken: int | None = None
    offset = 0
    batch = 500
    while first_broken is None:
        rows = (await session.execute(
            select(AuditLog).order_by(AuditLog.id.asc()).offset(offset).limit(batch)
        )).scalars().all()
        if not rows:
            break
        for row in rows:
            payload = _payload(row.ts, row.actor_user_id, row.actor_label, row.action,
                               row.object_type, row.object_id, row.detail_json)
            if row.prev_hash != prev or row.entry_hash != _entry_hash(prev, payload):
                first_broken = row.id
                break
            prev = row.entry_hash
        offset += batch
    return {
        "valid": first_broken is None,
        "length": total,
        "head_hash": prev if first_broken is None else "",
        "first_broken_id": first_broken,
    }
