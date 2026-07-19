import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.auth.seed import seed_users
from app.config import get_settings
from app.db import engine as db_engine
from app.db.models import Base
from app.modelclient.client import VLMClient
from app.pipeline.worker import Worker


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_dirs()
        engine = db_engine.init_engine(settings)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = db_engine.session_factory()
        async with factory() as session:
            await seed_users(session)
        vlm = VLMClient(settings, factory)
        worker = Worker(settings, factory, vlm)
        app.state.vlm = vlm
        app.state.worker = worker
        await worker.start()
        yield
        await worker.stop()
        await db_engine.dispose_engine()

    app = FastAPI(title="أثر — Athar Crime Scene Analysis", lifespan=lifespan)

    from app.api import (admin, audit_api, auth, cases, files, media, photo_qa,
                         reports, results, review, runs)
    for router in (auth.router, cases.router, media.router, runs.router,
                   results.router, review.router, reports.router, files.router,
                   audit_api.router, admin.router, photo_qa.router):
        app.include_router(router, prefix="/api")

    @app.get("/api/health")
    async def health():
        worker_alive = (getattr(app.state, "worker", None) is not None
                        and app.state.worker._task is not None
                        and not app.state.worker._task.done())
        return {"status": "ok", "model_mode": settings.model_mode,
                "worker": worker_alive}

    @app.exception_handler(PermissionError)
    async def permission_handler(_request, _exc):
        return JSONResponse(status_code=404, content={"detail": "غير موجود"})

    return app


app = create_app()
