import asyncio
import hashlib
from datetime import datetime
from pathlib import Path

import filetype
from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import make_id
from app.deps import (CurrentUser, get_factory, get_current_user, get_session,
                      require_role, settings_dep)
from app.db.models import Case, Frame, MediaFile
from app.services import audit
from app.services.media_meta import image_meta, probe_video
from app.services.storage import store_original
from app.services.thumbs import make_image_thumb, make_video_thumb

router = APIRouter(tags=["media"])

CHUNK = 1024 * 1024
ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff"}
ALLOWED_VIDEO = {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm",
                 "video/x-msvideo"}


class MediaPatch(BaseModel):
    source_label_ar: str | None = None
    source_type: str | None = None
    excluded: bool | None = None


def _media_dict(m: MediaFile) -> dict:
    return {
        "id": m.id, "case_id": m.case_id, "kind": m.kind,
        "original_filename": m.original_filename,
        "content_sha256": m.content_sha256, "size_bytes": m.size_bytes,
        "mime": m.mime, "width": m.width, "height": m.height,
        "duration_s": m.duration_s, "fps": m.fps,
        "source_label_ar": m.source_label_ar, "source_type": m.source_type,
        "excluded": m.excluded,
        "metadata_creation_time": (m.metadata_creation_time.isoformat()
                                   if m.metadata_creation_time else None),
        "exif": m.exif_json or {},
        "uploaded_at": m.uploaded_at.isoformat(),
    }


@router.post("/cases/{case_id}/media", status_code=201)
async def upload_media(case_id: str, file: UploadFile = File(...),
                       source_type: str = Form("other"),
                       source_label_ar: str = Form(""),
                       session: AsyncSession = Depends(get_session),
                       settings: Settings = Depends(settings_dep),
                       user: CurrentUser = Depends(require_role("investigator")),
                       factory=Depends(get_factory)):
    case = (await session.execute(
        select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="قضية غير موجودة")

    settings.ensure_dirs()
    tmp_path = settings.tmp_dir / f"upload-{make_id()}"
    hasher = hashlib.sha256()
    size = 0
    head = b""
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413,
                                        detail="حجم الملف يتجاوز الحد المسموح")
                if len(head) < 8192:
                    head += chunk[:8192 - len(head)]
                hasher.update(chunk)
                out.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    if size == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="ملف فارغ")

    kind_guess = filetype.guess(head)
    mime = kind_guess.mime if kind_guess else (file.content_type or "")
    if mime in ALLOWED_IMAGE:
        kind = "image"
    elif mime in ALLOWED_VIDEO:
        kind = "video"
    else:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=415,
                            detail=f"نوع ملف غير مدعوم ({mime or 'غير معروف'})")

    digest = hasher.hexdigest()
    existing = (await session.execute(
        select(MediaFile).where(MediaFile.case_id == case_id,
                                MediaFile.content_sha256 == digest))
    ).scalar_one_or_none()
    if existing:
        tmp_path.unlink(missing_ok=True)
        return {**_media_dict(existing), "duplicate": True}

    ext = Path(file.filename or "").suffix or (f".{kind_guess.extension}" if kind_guess else "")
    rel = store_original(settings, tmp_path, digest, ext)
    abs_path = settings.data_dir / rel

    width = height = None
    duration = fps = None
    exif: dict = {}
    ffprobe: dict | None = None
    creation: datetime | None = None
    if kind == "image":
        meta = await asyncio.to_thread(image_meta, abs_path)
        width, height, exif = meta["width"], meta["height"], meta["exif"]
        if meta["creation_time"]:
            creation = datetime.fromisoformat(meta["creation_time"])
    else:
        meta = await probe_video(abs_path)
        width, height = meta["width"], meta["height"]
        duration, fps = meta["duration_s"], meta["fps"]
        ffprobe = meta["ffprobe"]
        if meta["creation_time"]:
            creation = datetime.fromisoformat(meta["creation_time"])

    media = MediaFile(
        case_id=case_id, kind=kind, original_filename=file.filename or "unnamed",
        content_sha256=digest, stored_path=rel, size_bytes=size, mime=mime,
        width=width, height=height, duration_s=duration, fps=fps,
        exif_json=exif or None, ffprobe_json=ffprobe,
        metadata_creation_time=creation,
        source_label_ar=source_label_ar, source_type=source_type,
        uploaded_by=user.id)
    session.add(media)
    await session.commit()

    thumb = settings.derived_dir / "thumbs" / f"{media.id}.jpg"
    try:
        if kind == "image":
            await asyncio.to_thread(make_image_thumb, abs_path, thumb)
        else:
            await make_video_thumb(abs_path, thumb)
    except Exception:
        pass

    await audit.append(factory, action="media.upload", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="media",
                       object_id=media.id,
                       detail={"filename": media.original_filename,
                               "sha256": digest, "size": size, "kind": kind})
    return _media_dict(media)


@router.get("/cases/{case_id}/media")
async def list_media(case_id: str, session: AsyncSession = Depends(get_session),
                     user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(MediaFile).where(MediaFile.case_id == case_id)
        .order_by(MediaFile.uploaded_at))).scalars().all()
    return [_media_dict(m) for m in rows]


@router.get("/media/{media_id}")
async def get_media(media_id: str, session: AsyncSession = Depends(get_session),
                    user: CurrentUser = Depends(get_current_user)):
    m = (await session.execute(
        select(MediaFile).where(MediaFile.id == media_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    return _media_dict(m)


@router.patch("/media/{media_id}")
async def patch_media(media_id: str, body: MediaPatch,
                      session: AsyncSession = Depends(get_session),
                      user: CurrentUser = Depends(require_role("investigator")),
                      factory=Depends(get_factory)):
    m = (await session.execute(
        select(MediaFile).where(MediaFile.id == media_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(m, key, value)
    await session.commit()
    await audit.append(factory, action="media.update", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="media",
                       object_id=m.id, detail=changes)
    return _media_dict(m)


@router.get("/media/{media_id}/frames")
async def media_frames(media_id: str, session: AsyncSession = Depends(get_session),
                       user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(Frame).where(Frame.media_file_id == media_id)
        .order_by(Frame.frame_index))).scalars().all()
    return [{"id": f.id, "frame_index": f.frame_index,
             "timestamp_s": f.timestamp_s, "selection_reason": f.selection_reason,
             "dropped_dedup": f.dropped_dedup, "width": f.width,
             "height": f.height} for f in rows]
