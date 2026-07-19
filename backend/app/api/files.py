"""Auth-gated file serving. Clients pass IDs, never paths; every resolved path
is jailed inside DATA_DIR. Videos stream with manual HTTP Range support."""
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import CurrentUser, get_current_user, get_session, settings_dep
from app.db.models import EvidenceEntity, Frame, MediaFile
from app.services.storage import safe_resolve

router = APIRouter(prefix="/files", tags=["files"])

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _ranged(path: Path, request: Request, media_type: str):
    size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type)
    match = RANGE_RE.match(range_header)
    if not match:
        return FileResponse(path, media_type=media_type)
    start_s, end_s = match.groups()
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return Response(status_code=416,
                        headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1

    def iterator(chunk=1024 * 512):
        with open(path, "rb") as fp:
            fp.seek(start)
            remaining = length
            while remaining > 0:
                data = fp.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iterator(), status_code=206, media_type=media_type,
        headers={"Content-Range": f"bytes {start}-{end}/{size}",
                 "Accept-Ranges": "bytes", "Content-Length": str(length)})


async def _media(session: AsyncSession, media_id: str) -> MediaFile:
    m = (await session.execute(
        select(MediaFile).where(MediaFile.id == media_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    return m


@router.get("/original/{media_id}")
async def original(media_id: str, request: Request,
                   session: AsyncSession = Depends(get_session),
                   settings: Settings = Depends(settings_dep),
                   user: CurrentUser = Depends(get_current_user)):
    m = await _media(session, media_id)
    path = safe_resolve(settings, m.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="الملف الأصلي غير متاح")
    return _ranged(path, request, m.mime)


@router.get("/thumb/{media_id}")
async def thumb(media_id: str, session: AsyncSession = Depends(get_session),
                settings: Settings = Depends(settings_dep),
                user: CurrentUser = Depends(get_current_user)):
    await _media(session, media_id)
    path = settings.derived_dir / "thumbs" / f"{media_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="لا توجد مصغرة")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/frame/{frame_id}")
async def frame(frame_id: str, session: AsyncSession = Depends(get_session),
                settings: Settings = Depends(settings_dep),
                user: CurrentUser = Depends(get_current_user)):
    f = (await session.execute(
        select(Frame).where(Frame.id == frame_id))).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="إطار غير موجود")
    path = safe_resolve(settings, f.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/annotated/frame/{frame_id}")
async def annotated_frame(frame_id: str, run_id: str,
                          settings: Settings = Depends(settings_dep),
                          user: CurrentUser = Depends(get_current_user)):
    path = safe_resolve(settings, f"derived/annotated/{run_id}/frames/{frame_id}.jpg")
    if not path.exists():
        raise HTTPException(status_code=404, detail="لا توجد نسخة معلمة")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/annotated/entity/{entity_id}")
async def annotated_entity(entity_id: str, variant: str = "crop",
                           session: AsyncSession = Depends(get_session),
                           settings: Settings = Depends(settings_dep),
                           user: CurrentUser = Depends(get_current_user)):
    e = (await session.execute(
        select(EvidenceEntity).where(EvidenceEntity.id == entity_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="دليل غير موجود")
    suffix = {"crop": "", "before": "_before", "after": "_after"}.get(variant)
    if suffix is None:
        raise HTTPException(status_code=400, detail="متغير غير صالح")
    path = safe_resolve(
        settings, f"derived/annotated/{e.run_id}/entities/{entity_id}{suffix}.jpg")
    if not path.exists():
        raise HTTPException(status_code=404, detail="الصورة غير متاحة")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/data/{rel_path:path}")
async def data_asset(rel_path: str, settings: Settings = Depends(settings_dep),
                     user: CurrentUser = Depends(get_current_user)):
    # report-preview assets only: derived artifacts, never originals
    if not rel_path.startswith("derived/"):
        raise HTTPException(status_code=403, detail="غير مسموح")
    try:
        path = safe_resolve(settings, rel_path)
    except PermissionError:
        raise HTTPException(status_code=404)
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)
