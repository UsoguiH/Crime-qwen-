import os
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="athar-test-"))
os.environ.update({
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_URL": f"sqlite+aiosqlite:///{(TMP / 'test.db').as_posix()}",
    "MODEL_MODE": "mock",
    "SECRET_KEY": "test-secret",
    "LOG_LEVEL": "warning",
})

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
async def app():
    from app.main import create_app
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(scope="session")
async def client(app):
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test/api") as c:
        yield c


@pytest.fixture(scope="session")
async def logged_in(client):
    users = (await client.get("/auth/users")).json()
    by_role = {u["role"]: u for u in users}
    resp = await client.post("/auth/login", json={"user_id": by_role["investigator"]["id"]})
    assert resp.status_code == 200
    return by_role
