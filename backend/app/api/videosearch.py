"""Video search API: build the per-video retrieval index (background job) and
run natural-language searches over a case's indexed videos (background job,
polled — up to ~24 verify calls is too long for a synchronous request)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Case, MediaFile, VideoIndex, VideoSearch
from app.deps import (CurrentUser, get_current_user, get_factory,
                      get_index_worker, get_session, get_worker, require_role,
                      settings_dep)
from app.pipeline.worker import enqueue
from app.services import audit
from app.videosearch.search import index_dict, search_dict

router = APIRouter(tags=["video-search"])


class SearchBody(BaseModel):
    query_ar: str
    media_ids: list[str] | None = None


class AskBody(BaseModel):
    question_ar: str
    media_ids: list[str] | None = None


@router.post("/media/{media_id}/video-index", status_code=201)
async def build_video_index(media_id: str,
                            session: AsyncSession = Depends(get_session),
                            settings: Settings = Depends(settings_dep),
                            user: CurrentUser = Depends(require_role("investigator")),
                            index_worker=Depends(get_index_worker)):
    if not settings.video_search_enabled:
        raise HTTPException(status_code=400, detail="البحث في الفيديو معطّل")
    media = (await session.execute(
        select(MediaFile).where(MediaFile.id == media_id))).scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=404, detail="ملف غير موجود")
    if media.kind != "video":
        raise HTTPException(status_code=400, detail="الفهرسة متاحة للفيديو فقط")

    row = (await session.execute(
        select(VideoIndex).where(VideoIndex.media_file_id == media_id)
    )).scalar_one_or_none()
    if row is not None and row.status in ("queued", "building", "ready"):
        return index_dict(row)  # idempotent: already queued/built
    if row is None:
        row = VideoIndex(media_file_id=media_id, case_id=media.case_id)
        session.add(row)
    else:  # failed → retry
        row.status = "queued"
        row.error = None
    await enqueue(session, "index_video", payload={"media_id": media_id})
    await session.commit()
    index_worker.notify()
    return index_dict(row)


@router.get("/media/{media_id}/video-index")
async def get_video_index(media_id: str,
                          session: AsyncSession = Depends(get_session),
                          user: CurrentUser = Depends(get_current_user)):
    row = (await session.execute(
        select(VideoIndex).where(VideoIndex.media_file_id == media_id)
    )).scalar_one_or_none()
    return index_dict(row)


@router.post("/cases/{case_id}/video-search", status_code=201)
async def create_video_search(case_id: str, body: SearchBody,
                              session: AsyncSession = Depends(get_session),
                              settings: Settings = Depends(settings_dep),
                              user: CurrentUser = Depends(
                                  require_role("investigator", "reviewer")),
                              worker=Depends(get_worker),
                              factory=Depends(get_factory)):
    if not settings.video_search_enabled:
        raise HTTPException(status_code=400, detail="البحث في الفيديو معطّل")
    query = body.query_ar.strip()
    if not query:
        raise HTTPException(status_code=400, detail="نص البحث فارغ")
    if len(query) > 500:
        raise HTTPException(status_code=400, detail="نص البحث طويل جداً")
    case = (await session.execute(
        select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="قضية غير موجودة")
    has_video = (await session.execute(
        select(MediaFile.id).where(MediaFile.case_id == case_id,
                                   MediaFile.kind == "video",
                                   MediaFile.excluded.is_(False)).limit(1)
    )).scalar_one_or_none()
    if has_video is None:
        raise HTTPException(status_code=400, detail="لا توجد مقاطع فيديو في القضية")

    search = VideoSearch(case_id=case_id, query_ar=query,
                         media_ids_json=body.media_ids, created_by=user.id)
    session.add(search)
    await session.flush()  # assign search.id before it goes into the payload
    await enqueue(session, "video_search", payload={"search_id": search.id})
    await session.commit()
    worker.notify()
    await audit.append(factory, action="video.search", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="video_search",
                       object_id=search.id,
                       detail={"case_id": case_id, "query": query[:200]})
    return search_dict(search)


@router.post("/cases/{case_id}/video-ask", status_code=201)
async def video_ask_endpoint(case_id: str, body: AskBody,
                             session: AsyncSession = Depends(get_session),
                             settings: Settings = Depends(settings_dep),
                             user: CurrentUser = Depends(
                                 require_role("investigator", "reviewer")),
                             worker=Depends(get_worker),
                             factory=Depends(get_factory)):
    if not settings.video_search_enabled:
        raise HTTPException(status_code=400, detail="البحث في الفيديو معطّل")
    q = body.question_ar.strip()
    if not q:
        raise HTTPException(status_code=400, detail="السؤال فارغ")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="السؤال طويل جداً")
    case = (await session.execute(
        select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="قضية غير موجودة")

    from app.videosearch.qa import video_ask
    result = await video_ask(settings, factory, worker.vlm, case_id, q, body.media_ids)
    await audit.append(factory, action="video.ask", actor_user_id=user.id,
                       actor_label=user.display_name_ar, object_type="case",
                       object_id=case_id,
                       detail={"question": q[:200],
                               "timestamp_s": result.get("timestamp_s"),
                               "cannot_determine": result.get("cannot_determine")})
    return result


@router.get("/video-searches/{search_id}")
async def get_video_search(search_id: str,
                           session: AsyncSession = Depends(get_session),
                           user: CurrentUser = Depends(get_current_user)):
    row = (await session.execute(
        select(VideoSearch).where(VideoSearch.id == search_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="بحث غير موجود")
    return search_dict(row)


@router.get("/cases/{case_id}/video-searches")
async def list_video_searches(case_id: str,
                              session: AsyncSession = Depends(get_session),
                              user: CurrentUser = Depends(get_current_user)):
    rows = (await session.execute(
        select(VideoSearch).where(VideoSearch.case_id == case_id)
        .order_by(VideoSearch.created_at.desc()))).scalars().all()
    return [search_dict(r) for r in rows]
