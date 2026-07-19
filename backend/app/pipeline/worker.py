"""Single in-process worker: the only long-transaction writer (SQLite-friendly).

Jobs are claimed from the DB, heartbeaten, and survive restarts: on boot any
stale `running` job is re-queued, and completed pipeline stages are skipped on
re-execution (checkpoints make stages idempotent).
"""
import asyncio
import logging
import traceback

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.core import utcnow
from app.db.models import AnalysisRun, Case, Job, ModelCall, RunStep
from app.modelclient.client import BudgetExceeded, VLMClient
from app.pipeline.ctx import Ctx
from app.pipeline.stages import (s0_verify, s1_keyframes, s2_triage, s3_detect,
                                 s4_aggregate, s5_timeline, s7_narrative,
                                 s8_annotate, s9_render)

log = logging.getLogger("athar.worker")

# stage 6 (cross-source comparison) removed per user decision 2026-07-19
PIPELINE_STAGES = [
    (0, s0_verify.run), (1, s1_keyframes.run), (2, s2_triage.run),
    (3, s3_detect.run), (4, s4_aggregate.run), (5, s5_timeline.run),
    (7, s7_narrative.run), (8, s8_annotate.run), (9, s9_render.run),
]
ACTIVE_STAGES = [stage for stage, _fn in PIPELINE_STAGES]

# photo mode: detect + decoupled grounding per single media file
# (stage 3 internally runs detect_one then ground_detections)
PHOTO_STAGES = [(0, s0_verify.run), (1, s1_keyframes.run), (3, s3_detect.run_photo)]
PHOTO_ACTIVE_STAGES = [stage for stage, _fn in PHOTO_STAGES]


async def enqueue(session, kind: str, run_id: str | None = None,
                  payload: dict | None = None) -> Job:
    job = Job(kind=kind, run_id=run_id, payload_json=payload or {})
    session.add(job)
    return job


class Worker:
    def __init__(self, settings: Settings, factory: async_sessionmaker, vlm: VLMClient):
        self.settings = settings
        self.factory = factory
        self.vlm = vlm
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    def notify(self) -> None:
        self._wake.set()

    async def start(self) -> None:
        await self._requeue_stale()
        self._task = asyncio.create_task(self._loop(), name="athar-worker")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _requeue_stale(self) -> None:
        async with self.factory() as session:
            await session.execute(
                update(Job).where(Job.status == "running").values(status="queued"))
            await session.commit()

    async def _loop(self) -> None:
        while not self._stopping:
            job = await self._claim()
            if job is None:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                self._wake.clear()
                continue
            hb = asyncio.create_task(self._heartbeat(job.id))
            try:
                await self._dispatch(job)
                await self._finish(job.id, "done", None)
            except asyncio.CancelledError:
                raise
            except BudgetExceeded as exc:
                log.warning("budget exceeded: %s", exc)
                await self._finish(job.id, "done", f"paused: {exc}")
            except Exception as exc:
                log.error("job %s failed: %s\n%s", job.id, exc, traceback.format_exc())
                await self._finish(job.id, "failed", f"{type(exc).__name__}: {exc}")
            finally:
                hb.cancel()

    async def _claim(self) -> Job | None:
        async with self.factory() as session:
            job = (await session.execute(
                select(Job).where(Job.status == "queued")
                .order_by(Job.created_at.asc()).limit(1))).scalar_one_or_none()
            if job is None:
                return None
            job.status = "running"
            job.claimed_at = utcnow()
            job.heartbeat_at = utcnow()
            await session.commit()
            return job

    async def _heartbeat(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(10)
            async with self.factory() as session:
                await session.execute(
                    update(Job).where(Job.id == job_id).values(heartbeat_at=utcnow()))
                await session.commit()

    async def _finish(self, job_id: str, status: str, error: str | None) -> None:
        async with self.factory() as session:
            await session.execute(
                update(Job).where(Job.id == job_id)
                .values(status=status, finished_at=utcnow(), error=error))
            await session.commit()

    # ── handlers ──────────────────────────────────────────────
    async def _dispatch(self, job: Job) -> None:
        if job.kind == "run_pipeline":
            await self._run_pipeline(job)
        elif job.kind == "render_report":
            await self._render_report(job)
        elif job.kind == "rebuild_timeline":
            await self._rebuild_timeline(job)
        else:
            raise ValueError(f"unknown job kind {job.kind}")

    async def _load_run(self, run_id: str) -> AnalysisRun:
        async with self.factory() as session:
            run = (await session.execute(
                select(AnalysisRun).where(AnalysisRun.id == run_id))).scalar_one()
            return run

    async def _set_run(self, run_id: str, **values) -> None:
        async with self.factory() as session:
            await session.execute(
                update(AnalysisRun).where(AnalysisRun.id == run_id).values(**values))
            await session.commit()

    async def _run_pipeline(self, job: Job) -> None:
        run = await self._load_run(job.run_id)
        if run.status == "cancelled":
            return
        ctx = Ctx(self.settings, self.factory, self.vlm, run)
        photo_mode = (run.options_json or {}).get("mode") == "photo"
        stages = PHOTO_STAGES if photo_mode else PIPELINE_STAGES

        # resume support: budget counter restored from persisted model_calls
        async with self.factory() as session:
            count = (await session.execute(
                select(func.count(ModelCall.id)).where(ModelCall.run_id == run.id)
            )).scalar_one()
        self.vlm.set_run_count(run.id, count)

        await self._set_run(run.id, status="running", error=None)
        if not photo_mode:
            await self._set_case_status(run.case_id, "analyzing")
        ctx.emit("run_status", status="running")

        had_errors = False
        try:
            for stage, fn in stages:
                status = await self._step_status(run.id, stage)
                if status in ("completed", "skipped"):
                    continue
                if await self._is_cancelled(run.id):
                    ctx.emit("run_status", status="cancelled")
                    return
                await ctx.set_step(stage, status="running")
                try:
                    await fn(ctx)
                except BudgetExceeded:
                    await ctx.set_step(stage, status="failed",
                                       error="توقف مؤقت: بلغ التشغيل حد استدعاءات النموذج")
                    await self._set_run(run.id, status="paused")
                    ctx.emit("run_status", status="paused",
                             reason="budget")
                    raise
                except Exception as exc:
                    await ctx.set_step(stage, status="failed",
                                       error=f"{type(exc).__name__}: {exc}")
                    await self._set_run(run.id, status="failed",
                                        error=f"stage {stage}: {exc}", finished_at=utcnow())
                    ctx.emit("run_status", status="failed", stage=stage)
                    raise
                status = await self._step_status(run.id, stage)
                if status == "running":  # stage didn't set a terminal status itself
                    await ctx.set_step(stage, status="completed")
                elif status == "completed_with_errors":
                    had_errors = True
        except BudgetExceeded:
            return  # job ends cleanly; run stays paused/resumable

        final = "completed_with_errors" if had_errors else "completed"
        await self._set_run(run.id, status=final, finished_at=utcnow())
        if not photo_mode:
            await self._set_case_status(run.case_id, "complete")
        ctx.emit("run_status", status=final)

    async def _render_report(self, job: Job) -> None:
        payload = job.payload_json or {}
        run = await self._load_run(job.run_id)
        ctx = Ctx(self.settings, self.factory, self.vlm, run)
        await s9_render.generate_exports(
            ctx, kinds=payload.get("kinds") or ["pdf"],
            user_id=payload.get("user_id"))

    async def _rebuild_timeline(self, job: Job) -> None:
        run = await self._load_run(job.run_id)
        ctx = Ctx(self.settings, self.factory, self.vlm, run)
        for stage, fn in PIPELINE_STAGES:
            if stage not in (5, 7):  # timeline + narratives depend on offsets
                continue
            await ctx.set_step(stage, status="running")
            await fn(ctx)
            if await self._step_status(run.id, stage) == "running":
                await ctx.set_step(stage, status="completed")
        ctx.emit("run_status", status=run.status)

    # ── small queries ─────────────────────────────────────────
    async def _step_status(self, run_id: str, stage: int) -> str:
        async with self.factory() as session:
            row = (await session.execute(
                select(RunStep.status).where(RunStep.run_id == run_id,
                                             RunStep.stage == stage))).scalar_one_or_none()
            return row or "pending"

    async def _is_cancelled(self, run_id: str) -> bool:
        async with self.factory() as session:
            status = (await session.execute(
                select(AnalysisRun.status).where(AnalysisRun.id == run_id))).scalar_one()
            return status == "cancelled"

    async def _set_case_status(self, case_id: str, status: str) -> None:
        async with self.factory() as session:
            await session.execute(
                update(Case).where(Case.id == case_id).values(status=status))
            await session.commit()
