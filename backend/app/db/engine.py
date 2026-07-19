from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    url = settings.resolved_database_url
    _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    if url.startswith("sqlite"):
        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker:
    assert _session_factory is not None, "init_engine() must run first"
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
