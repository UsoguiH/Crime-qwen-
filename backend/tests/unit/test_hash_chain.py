import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services import audit


@pytest.fixture
async def isolated_factory():
    tmp = Path(tempfile.mkdtemp(prefix="athar-chain-")) / "chain.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_chain_appends_and_verifies(isolated_factory):
    for i in range(5):
        await audit.append(isolated_factory, action=f"test.action{i}",
                           actor_label="فاحص الاختبار",
                           detail={"i": i, "نص": "قيمة عربية"})
    async with isolated_factory() as session:
        result = await audit.verify(session)
    assert result["valid"] is True
    assert result["length"] == 5
    assert len(result["head_hash"]) == 64


async def test_tamper_detected(isolated_factory):
    for i in range(4):
        await audit.append(isolated_factory, action=f"test.action{i}",
                           actor_label="فاحص")
    async with isolated_factory() as session:
        await session.execute(
            text("UPDATE audit_log SET action = 'evil.tamper' WHERE id = 2"))
        await session.commit()
        result = await audit.verify(session)
    assert result["valid"] is False
    assert result["first_broken_id"] == 2


async def test_deletion_detected(isolated_factory):
    for i in range(4):
        await audit.append(isolated_factory, action=f"test.action{i}",
                           actor_label="فاحص")
    async with isolated_factory() as session:
        await session.execute(text("DELETE FROM audit_log WHERE id = 3"))
        await session.commit()
        result = await audit.verify(session)
    assert result["valid"] is False
