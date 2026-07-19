import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.admin import get_setting_overrides
from app.config import Settings
from app.deps import (CurrentUser, get_current_user, get_factory, get_session,
                      get_vlm, get_worker, require_role, settings_dep)
from app.db.models import AnalysisRun, Case, Job, ModelCall, RunStep
from app.modelclient.client import prompt_hashes
from app.pipeline import worker as worker_mod
from app.pipeline.ctx import STAGE_NAMES_AR
from app.pipeline.progress import broadcaster
from app.services import audit

router = APIRouter(tags=["runs"])


class RunCreate(BaseModel):
    media_ids: list[str] | None = None
    thinking_policy: str = "auto"  # auto | always | never


def _step_dict(s: RunStep) -> dict:
    return {"stage": s.stage, "stage_name_ar": STAGE_NAMES_AR.get(s.stage, ""),
            "status": s.status, "progress_current": s.progress_current,
            "progress_total": s.progress_total, "error": s.error}


def _run_dict(r: AnalysisRun, steps: list[RunStep] | None = None) -> dict:
    d = {"id": r.id, "case_id": r.case_id, "run_number": r.run_number,
         "status": r.status, "model_mode": r.model_mode,
         "model_snapshot": r.model_snapshot_json,
         "thresholds": r.thresholds_json,
         "options": r.options_json,
         "started_at": r.started_at.isoformat(),
         "finished_at": r.finished_at.isoformat() if r.finished_at else None,
         "error": r.error}
    if steps is not None:
        d["steps"] = [_step_dict(s) for s in sorted(steps, key=lambda x: x.stage)]
    return d


@router.post("/cases/{case_id}/runs", status_code=201)
async def start_run(case_id: str, body: RunCreate,
                    session: AsyncSession = Depends(get_session),
                    settings: Settings = Depends(settings_dep),
                    user: CurrentUser = Depends(require_role("investigator")),
                    factory=Depends(get_factory), worker=Depends(get_worker)):
    case = (await session.execute(
        select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="قضية غير موجودة")

    active_runs = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.case_id == case_id,
                                  AnalysisRun.status.in_(["queued", "running"])))
    ).scalars().all()
    if any((r.options_json or {}).get("mode") != "photo" for r in active_runs):
        raise HTTPException(status_code=409, detail="يوجد تحليل قيد التنفيذ لهذه القضية")

    overrides = await get_setting_overrides(session)
    run_number = ((await session.execute(
        select(func.max(AnalysisRun.run_number))
        .where(AnalysisRun.case_id == case_id))).scalar_one() or 0) + 1

    thresholds = {
        "confidence_review_threshold": float(overrides.get(
            "confidence_review_threshold", settings.confidence_review_threshold)),
        "triage_relevance_threshold": settings.triage_relevance_threshold,
        "keyframe_min_interval_s": settings.keyframe_min_interval_s,
        "phash_dedup_distance": settings.phash_dedup_distance,
        "iou_merge_threshold": settings.iou_merge_threshold,
        "move_centroid_threshold": settings.move_centroid_threshold,
        "max_frames_per_video": int(overrides.get("max_frames_per_video", 240)),
    }
    policy = overrides.get("thinking_policy", body.thinking_policy)
    run = AnalysisRun(
        case_id=case_id, run_number=run_number, status="queued",
        model_mode=settings.model_mode,
        model_snapshot_json={
            "provider": ("vllm" if settings.model_mode == "local"
                         else settings.model_provider if settings.model_mode == "api"
                         else "mock"),
            "base_url": settings.resolved_base_url if settings.model_mode != "mock" else "",
            "model_fast": (settings.vllm_model if settings.model_mode == "local"
                           else settings.model_name_fast if settings.model_mode == "api"
                           else "mock"),
            "model_thinking": (settings.vllm_model if settings.model_mode == "local"
                               else settings.model_name_thinking if settings.model_mode == "api"
                               else "mock"),
        },
        prompt_hashes_json=prompt_hashes(settings),
        thresholds_json=thresholds,
        options_json={"media_ids": body.media_ids, "thinking_policy": policy},
        started_by=user.id)
    session.add(run)
    await session.flush()
    for stage in worker_mod.ACTIVE_STAGES:
        session.add(RunStep(run_id=run.id, stage=stage))
    await worker_mod.enqueue(session, "run_pipeline", run.id)
    await session.commit()
    worker.notify()
    await audit.append(factory, action="run.start", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="run",
                       object_id=run.id,
                       detail={"case_id": case_id, "run_number": run_number,
                               "model_mode": settings.model_mode,
                               "thinking_policy": policy})
    return _run_dict(run)


@router.get("/cases/{case_id}/runs")
async def list_runs(case_id: str, session: AsyncSession = Depends(get_session),
                    user: CurrentUser = Depends(get_current_user)):
    runs = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.case_id == case_id)
        .order_by(AnalysisRun.run_number.desc()))).scalars().all()
    return [_run_dict(r) for r in runs
            if (r.options_json or {}).get("mode") != "photo"]


class PhotoAnalyzeBody(BaseModel):
    thinking: bool = True


@router.post("/media/{media_id}/analyze", status_code=201)
async def analyze_photo(media_id: str, body: PhotoAnalyzeBody,
                        session: AsyncSession = Depends(get_session),
                        settings: Settings = Depends(settings_dep),
                        user: CurrentUser = Depends(require_role("investigator")),
                        factory=Depends(get_factory), worker=Depends(get_worker)):
    from app.db.models import MediaFile
    media = (await session.execute(
        select(MediaFile).where(MediaFile.id == media_id))).scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    if media.kind != "image":
        raise HTTPException(status_code=400,
                            detail="التحليل الفردي متاح للصور فقط")

    existing = (await session.execute(
        select(AnalysisRun).where(
            AnalysisRun.case_id == media.case_id,
            AnalysisRun.status.in_(["queued", "running"])))).scalars().all()
    for r in existing:
        opts = r.options_json or {}
        if opts.get("mode") == "photo" and media_id in (opts.get("media_ids") or []):
            raise HTTPException(status_code=409,
                                detail="يوجد تحليل قيد التنفيذ لهذه الصورة")

    run_number = ((await session.execute(
        select(func.max(AnalysisRun.run_number))
        .where(AnalysisRun.case_id == media.case_id))).scalar_one() or 0) + 1
    run = AnalysisRun(
        case_id=media.case_id, run_number=run_number, status="queued",
        model_mode=settings.model_mode,
        model_snapshot_json={
            "provider": ("vllm" if settings.model_mode == "local"
                         else settings.model_provider if settings.model_mode == "api"
                         else "mock"),
            "model_fast": (settings.vllm_model if settings.model_mode == "local"
                           else settings.model_name_fast if settings.model_mode == "api"
                           else "mock"),
            "model_thinking": (settings.vllm_model if settings.model_mode == "local"
                               else settings.model_name_thinking if settings.model_mode == "api"
                               else "mock"),
        },
        prompt_hashes_json=prompt_hashes(settings),
        thresholds_json={
            "confidence_review_threshold": settings.confidence_review_threshold,
        },
        options_json={"mode": "photo", "media_ids": [media_id],
                      "thinking_policy": "always" if body.thinking else "never"},
        started_by=user.id)
    session.add(run)
    await session.flush()
    for stage in worker_mod.PHOTO_ACTIVE_STAGES:
        session.add(RunStep(run_id=run.id, stage=stage))
    await worker_mod.enqueue(session, "run_pipeline", run.id)
    await session.commit()
    worker.notify()
    await audit.append(factory, action="run.start", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="run",
                       object_id=run.id,
                       detail={"case_id": media.case_id, "mode": "photo",
                               "media_id": media_id,
                               "thinking": body.thinking})
    return _run_dict(run)


@router.get("/media/{media_id}/analyses")
async def photo_analyses(media_id: str,
                         session: AsyncSession = Depends(get_session),
                         user: CurrentUser = Depends(get_current_user)):
    from app.db.models import Detection, MediaFile
    media = (await session.execute(
        select(MediaFile).where(MediaFile.id == media_id))).scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    runs = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.case_id == media.case_id)
        .order_by(AnalysisRun.started_at.desc()))).scalars().all()
    photo_runs = [r for r in runs
                  if (r.options_json or {}).get("mode") == "photo"
                  and media_id in ((r.options_json or {}).get("media_ids") or [])]
    counts = dict((await session.execute(
        select(Detection.run_id, func.count(Detection.id))
        .where(Detection.run_id.in_([r.id for r in photo_runs] or [""]))
        .group_by(Detection.run_id))).all())
    out = []
    for r in photo_runs:
        steps = (await session.execute(
            select(RunStep).where(RunStep.run_id == r.id))).scalars().all()
        d = _run_dict(r, steps)
        d["detections_count"] = counts.get(r.id, 0)
        out.append(d)
    return out


@router.get("/runs/{run_id}")
async def get_run(run_id: str, session: AsyncSession = Depends(get_session),
                  user: CurrentUser = Depends(get_current_user)):
    run = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="تحليل غير موجود")
    steps = (await session.execute(
        select(RunStep).where(RunStep.run_id == run_id))).scalars().all()
    return _run_dict(run, steps)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(require_role("investigator")),
                     factory=Depends(get_factory)):
    run = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="تحليل غير موجود")
    if run.status not in ("queued", "running", "paused"):
        raise HTTPException(status_code=409, detail="لا يمكن إلغاء تحليل منتهٍ")
    run.status = "cancelled"
    await session.commit()
    broadcaster.publish(run_id, {"type": "run_status", "run_id": run_id,
                                 "status": "cancelled"})
    await audit.append(factory, action="run.cancel", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="run",
                       object_id=run_id)
    return {"ok": True}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(require_role("investigator")),
                     factory=Depends(get_factory), worker=Depends(get_worker)):
    run = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="تحليل غير موجود")
    if run.status not in ("failed", "paused", "cancelled"):
        raise HTTPException(status_code=409, detail="التحليل ليس في حالة قابلة للاستئناف")
    await session.execute(
        update(RunStep).where(RunStep.run_id == run_id,
                              RunStep.status.in_(["failed", "running"]))
        .values(status="pending", error=None))
    run.status = "queued"
    run.error = None
    run.finished_at = None
    await worker_mod.enqueue(session, "run_pipeline", run_id)
    await session.commit()
    worker.notify()
    await audit.append(factory, action="run.resume", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="run",
                       object_id=run_id)
    return {"ok": True}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request,
                     session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(get_current_user)):
    run = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="تحليل غير موجود")
    steps = (await session.execute(
        select(RunStep).where(RunStep.run_id == run_id))).scalars().all()
    snapshot = _run_dict(run, steps)

    async def gen():
        q = broadcaster.subscribe(run_id)
        try:
            yield {"event": "snapshot", "data": json.dumps(snapshot, ensure_ascii=False)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"event": event.get("type", "message"),
                           "data": json.dumps(event, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            broadcaster.unsubscribe(run_id, q)

    return EventSourceResponse(gen())


@router.get("/runs/{run_id}/model-calls")
async def model_calls(run_id: str, session: AsyncSession = Depends(get_session),
                      user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(ModelCall).where(ModelCall.run_id == run_id)
        .order_by(ModelCall.created_at))).scalars().all()
    totals = {
        "calls": len(rows),
        "input_tokens": sum(r.input_tokens for r in rows),
        "output_tokens": sum(r.output_tokens for r in rows),
        "cost_usd": round(sum(r.cost_usd_estimate for r in rows), 4),
        "failed": sum(1 for r in rows if r.status == "failed"),
        "repaired": sum(1 for r in rows if r.status == "repaired"),
    }
    by_purpose: dict[str, dict] = {}
    for r in rows:
        agg = by_purpose.setdefault(r.purpose, {"calls": 0, "cost_usd": 0.0,
                                                "input_tokens": 0, "output_tokens": 0})
        agg["calls"] += 1
        agg["cost_usd"] = round(agg["cost_usd"] + r.cost_usd_estimate, 4)
        agg["input_tokens"] += r.input_tokens
        agg["output_tokens"] += r.output_tokens
    return {"totals": totals, "by_purpose": by_purpose,
            "calls": [{"id": r.id, "purpose": r.purpose, "stage": r.stage,
                       "model": r.model_name, "thinking": r.thinking,
                       "status": r.status, "attempts": r.attempts,
                       "input_tokens": r.input_tokens,
                       "output_tokens": r.output_tokens,
                       "latency_ms": r.latency_ms,
                       "cost_usd": r.cost_usd_estimate,
                       "created_at": r.created_at.isoformat()} for r in rows[-200:]]}
