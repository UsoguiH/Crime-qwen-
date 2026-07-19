from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import (CurrentUser, get_current_user, get_factory, get_session,
                      get_worker, require_role, settings_dep)
from app.db.models import AnalysisRun, Case, Report
from app.pipeline import worker as worker_mod
from app.pipeline.stages.s9_render import render_html
from app.services.storage import safe_resolve

router = APIRouter(tags=["reports"])

EXT = {"pdf_a": "pdf", "docx": "docx", "bundle_zip": "zip"}


class ReportRequest(BaseModel):
    kinds: list[str] = ["pdf"]  # pdf | docx | bundle


@router.post("/runs/{run_id}/reports", status_code=202)
async def request_reports(run_id: str, body: ReportRequest,
                          session: AsyncSession = Depends(get_session),
                          user: CurrentUser = Depends(require_role("investigator")),
                          worker=Depends(get_worker)):
    run = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="تحليل غير موجود")
    kinds = [k for k in body.kinds if k in ("pdf", "docx", "bundle")]
    if not kinds:
        raise HTTPException(status_code=400, detail="أنواع تصدير غير صالحة")
    job = await worker_mod.enqueue(session, "render_report", run_id,
                                   {"kinds": kinds, "user_id": user.id})
    await session.commit()
    worker.notify()
    return {"job_id": job.id, "kinds": kinds}


@router.get("/runs/{run_id}/reports")
async def list_reports(run_id: str, session: AsyncSession = Depends(get_session),
                       user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(Report).where(Report.run_id == run_id)
        .order_by(Report.generated_at.desc()))).scalars().all()
    return [{"id": r.id, "kind": r.kind, "version": r.version,
             "file_sha256": r.file_sha256, "size_bytes": r.size_bytes,
             "pdf_variant": r.pdf_variant,
             "audit_head_hash": r.audit_head_hash,
             "generated_at": r.generated_at.isoformat()} for r in rows]


@router.get("/reports/{report_id}/download")
async def download(report_id: str, session: AsyncSession = Depends(get_session),
                   settings: Settings = Depends(settings_dep),
                   user: CurrentUser = Depends(get_current_user)):
    r = (await session.execute(
        select(Report).where(Report.id == report_id))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="تقرير غير موجود")
    run = (await session.execute(
        select(AnalysisRun).where(AnalysisRun.id == r.run_id))).scalar_one()
    case = (await session.execute(
        select(Case).where(Case.id == run.case_id))).scalar_one()
    path = safe_resolve(settings, r.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="ملف التقرير غير متاح")
    filename = f"athar-{case.case_number}-run{run.run_number}-v{r.version}.{EXT[r.kind]}"
    return FileResponse(path, filename=filename)


@router.get("/runs/{run_id}/report-preview")
async def report_preview(run_id: str,
                         settings: Settings = Depends(settings_dep),
                         user: CurrentUser = Depends(get_current_user),
                         factory=Depends(get_factory)):
    html = await render_html(settings, factory, run_id, user.id,
                             asset_base="/api/files/data/")
    return HTMLResponse(html)
