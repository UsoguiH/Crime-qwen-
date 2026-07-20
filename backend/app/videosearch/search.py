"""Natural-language video search: translate → retrieve → cluster → verify.

SMART-first (docs/VIDEO_SEARCH_PLAN.md): the retrieval net is cast wide (no
score floor, misses are the catastrophic error), precision is restored by the
Qwen3-VL verify pass, weapon/violence queries are verified twice
(self-consistency — disagreement is surfaced as «uncertain», never dropped),
and the result always states its coverage honestly.
"""
import asyncio
import io
import logging
import time
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import select, update

from app.config import Settings
from app.core import utcnow
from app.db.models import MediaFile, VideoIndex, VideoSearch
from app.modelclient.client import FrameImage, VLMClient
from app.pipeline.grounding import refine_answer_boxes
from app.schemas.model_io import QueryTranslation, VideoVerify
from app.services import audit
from app.services.storage import derived_path, rel_to_data, safe_resolve
from app.videosearch.embedder import get_embedder
from app.videosearch.indexer import sidecar_load

log = logging.getLogger("athar.videosearch")

VERIFY_MIN_PX = 1280   # same accurate-regime upscale as photo Q&A grounding

# fallback only (translation normally decides): treat as sensitive → double verify
SENSITIVE_TERMS = (
    "سلاح", "سكين", "مسدس", "بندقية", "رصاص", "دم", "دماء", "عنف", "اعتداء",
    "ضرب", "طعن", "جثة", "خطف",
    "weapon", "knife", "gun", "pistol", "rifle", "blood", "violence", "assault",
    "fight", "stab", "shoot", "body", "kidnap",
)


def fallback_sensitive(query: str) -> bool:
    q = query.lower()
    return any(term in q for term in SENSITIVE_TERMS)


def topk_frames(vectors: np.ndarray, timestamps: np.ndarray,
                query_vecs: np.ndarray, k: int) -> list[tuple[float, float]]:
    """Top-k (timestamp, score) by cosine; score = max over query variants.
    Exact brute force — at ≤10⁵ frames this is sub-millisecond (plan: FAISS
    IndexFlatIP equivalent, no extra dependency)."""
    if len(vectors) == 0:
        return []
    sims = (vectors @ query_vecs.T).max(axis=1)
    k = min(k, len(sims))
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    return [(float(timestamps[i]), float(sims[i])) for i in idx]


def cluster_moments(candidates: list[tuple[float, float]], gap_s: float,
                    budget: int) -> list[dict]:
    """Merge candidate timestamps within gap_s into moments; a moment carries
    its span, its best timestamp and its best score. Top `budget` by score."""
    moments: list[dict] = []
    for ts, score in sorted(candidates):
        if moments and ts - moments[-1]["ts_end"] <= gap_s:
            m = moments[-1]
            m["ts_end"] = ts
            if score > m["score"]:
                m["score"], m["ts_best"] = score, ts
        else:
            moments.append({"ts_start": ts, "ts_end": ts, "ts_best": ts,
                            "score": score})
    moments.sort(key=lambda m: -m["score"])
    return moments[:budget]


async def run_search(settings: Settings, factory, vlm: VLMClient,
                     search_id: str) -> None:
    started = time.monotonic()
    async with factory() as session:
        search = (await session.execute(
            select(VideoSearch).where(VideoSearch.id == search_id))).scalar_one()
    try:
        await _run(settings, factory, vlm, search, started)
    except Exception as exc:
        await _set(factory, search_id, status="failed",
                   error=f"{type(exc).__name__}: {exc}"[:1500],
                   finished_at=utcnow(),
                   latency_ms=int((time.monotonic() - started) * 1000))
        raise


async def _run(settings: Settings, factory, vlm: VLMClient,
               search: VideoSearch, started: float) -> None:
    timings: dict[str, int] = {}

    # ── translate (Arabic → English retrieval variants + sensitivity) ─────
    await _set(factory, search.id, status="translating")
    t0 = time.monotonic()
    try:
        res = await vlm.complete_json(
            prompt_files=("95_query_translate.md",), schema=QueryTranslation,
            purpose="translate", context={"query_ar": search.query_ar},
            max_output_tokens=500)
        variants = [v.strip() for v in res.value.english_variants if v.strip()][:4]
        sensitive = res.value.sensitive
    except Exception as exc:
        log.warning("query translation failed (%s) — searching raw query", exc)
        variants, sensitive = [], True   # recall-first fallback
    if not variants:
        variants = [search.query_ar]
    sensitive = sensitive or fallback_sensitive(search.query_ar)
    timings["translate_ms"] = int((time.monotonic() - t0) * 1000)
    await _set(factory, search.id, sensitive=sensitive,
               query_variants_json={"english_variants": variants,
                                    "sensitive": sensitive})

    # ── retrieve (vector search over ready indexes) ───────────────────────
    await _set(factory, search.id, status="retrieving")
    t0 = time.monotonic()
    # load OFF the event loop (see indexer): first-use weight load must not
    # block the async loop, or every concurrent HTTP request stalls
    embedder = await asyncio.to_thread(get_embedder, settings)
    media_rows, skipped = await _target_media(settings, factory, search, embedder.name)
    query_vecs = await asyncio.to_thread(embedder.embed_texts, variants)

    moments: list[dict] = []
    frames_indexed = frames_seen = 0
    for media, index in media_rows:
        vectors, timestamps, _meta = await asyncio.to_thread(
            sidecar_load, safe_resolve(settings, index.sidecar_path))
        frames_indexed += len(timestamps)
        frames_seen += index.frames_seen
        cands = topk_frames(vectors, timestamps, query_vecs,
                            settings.video_search_top_k)
        for m in cluster_moments(cands, settings.video_search_cluster_gap_s,
                                 settings.video_search_verify_budget):
            m["media"] = media
            moments.append(m)
    moments.sort(key=lambda m: -m["score"])
    moments = moments[:settings.video_search_verify_budget]
    timings["retrieve_ms"] = int((time.monotonic() - t0) * 1000)

    # ── verify (Qwen3-VL, thinking; sensitive ⇒ two independent passes) ───
    await _set(factory, search.id, status="verifying", progress_current=0,
               progress_total=len(moments))
    t0 = time.monotonic()
    done = 0
    # bound frame extraction + model fan-out (the VLM client has its own cap)
    sem = asyncio.Semaphore(max(4, settings.model_max_concurrency))

    async def verify(i: int, m: dict) -> dict | None:
        nonlocal done
        async with sem:
            return await _verify_one(i, m)

    async def _verify_one(i: int, m: dict) -> dict | None:
        nonlocal done
        media: MediaFile = m["media"]
        try:
            frame_png = await _extract_frame(
                settings, safe_resolve(settings, media.stored_path),
                m["ts_best"], search.id, i)
        except Exception as exc:
            log.warning("frame extract failed @%ss: %s", m["ts_best"], exc)
            return None
        img_bytes, thumb_rel = frame_png
        context = {"query_ar": search.query_ar, "english_variants": variants,
                   "timestamp_s": round(m["ts_best"], 1),
                   "media_label": media.source_label_ar or media.original_filename}

        async def one() -> tuple | None:
            try:
                r = await vlm.complete_json(
                    prompt_files=("71_video_verify.md",), schema=VideoVerify,
                    purpose="video_verify", thinking=True,
                    images=[FrameImage(data=img_bytes,
                                       ref=f"{media.id}@{m['ts_best']:.1f}s",
                                       name_hint=Path(media.original_filename).stem)],
                    context=context, media_file_id=media.id,
                    max_output_tokens=2500)
                return r.value, r.model_call_id
            except Exception:
                return None

        calls = await asyncio.gather(one(), one()) if sensitive else [await one()]
        answers = [c for c in calls if c is not None]
        done += 1
        await _set(factory, search.id, progress_current=done)
        if not answers:
            return None
        verdicts = [a for a, _ in answers]
        call_ids = [cid for _, cid in answers]
        primary = max(verdicts, key=lambda v: v.confidence)
        matches = [v.match for v in verdicts]
        if all(matches):
            status = "confirmed"
            confidence = min(1.0, primary.confidence + (0.1 if len(verdicts) == 2 else 0.0))
        elif not any(matches):
            status = "rejected"
            confidence = 1.0 - max(v.confidence for v in verdicts)
        else:  # disagreement is surfaced, never silently dropped
            status = "uncertain"
            confidence = round(sum(v.confidence for v in verdicts) / len(verdicts) * 0.6, 3)

        box = None
        if status != "rejected" and primary.bbox_2d and len(primary.bbox_2d) == 4:
            raw = [{"label_ar": primary.label_ar or "الهدف",
                    "bbox": [min(max(v, 0), 1000) / 1000 for v in primary.bbox_2d]}]
            refined = await refine_answer_boxes(vlm, img_bytes, raw)
            if refined:
                box = refined[0]["bbox"]

        duration = media.duration_s or m["ts_end"] + settings.video_search_clip_pad_s
        return {
            "media_file_id": media.id,
            "media_label": media.source_label_ar or media.original_filename,
            "ts_in": round(max(0.0, m["ts_start"] - settings.video_search_clip_pad_s), 2),
            "ts_out": round(min(duration, m["ts_end"] + settings.video_search_clip_pad_s), 2),
            "ts_best": round(m["ts_best"], 2),
            "retrieval_score": round(m["score"], 4),
            "status": status,
            "confidence": round(confidence, 3),
            "label_ar": primary.label_ar,
            "description_ar": primary.description_ar,
            "bbox": box,
            "thumb_path": thumb_rel,
            "model_call_ids": call_ids,
        }

    results = [r for r in await asyncio.gather(
        *[verify(i, m) for i, m in enumerate(moments)]) if r is not None]
    timings["verify_ms"] = int((time.monotonic() - t0) * 1000)

    order = {"confirmed": 0, "uncertain": 1}
    clips = sorted((r for r in results if r["status"] != "rejected"),
                   key=lambda r: (order[r["status"]], -r["confidence"]))
    rejected = sorted((r for r in results if r["status"] == "rejected"),
                      key=lambda r: -r["retrieval_score"])

    fps = settings.video_index_fps
    coverage = {
        "fps": fps,
        "frames_seen": frames_seen,
        "frames_indexed": frames_indexed,
        "media_searched": len(media_rows),
        "skipped_media": skipped,
        # honest bound, never "nothing there" (plan principle 5)
        "statement_ar": (
            f"فُحص الفيديو بمعدل {fps:g} إطار/ثانية؛ قد لا يُرصد حدث يظهر "
            f"لأقل من {1 / fps:g} ثانية. عدم العثور على نتيجة يعني عدم "
            "العثور عند هذه التغطية، لا الجزم بعدم الوجود. كل النتائج "
            "تتطلب تأكيداً بشرياً."),
    }
    stats = {"candidates": len(moments), "confirmed":
             sum(1 for c in clips if c["status"] == "confirmed"),
             "uncertain": sum(1 for c in clips if c["status"] == "uncertain"),
             "rejected": len(rejected), **timings}

    await _set(factory, search.id, status="done", finished_at=utcnow(),
               latency_ms=int((time.monotonic() - started) * 1000),
               results_json={"clips": clips, "rejected": rejected,
                             "coverage": coverage, "stats": stats})
    await audit.append(
        factory, action="video.search.done", actor_label="النظام",
        object_type="video_search", object_id=search.id,
        detail={"case_id": search.case_id, "query": search.query_ar[:200],
                "sensitive": sensitive, **{k: stats[k] for k in
                                           ("candidates", "confirmed",
                                            "uncertain", "rejected")}})


async def _target_media(settings: Settings, factory, search: VideoSearch,
                        embedder_name: str):
    """Case videos paired with their READY index; everything else is reported
    in coverage.skipped_media rather than silently ignored."""
    wanted = set(search.media_ids_json or [])
    async with factory() as session:
        media = (await session.execute(
            select(MediaFile).where(MediaFile.case_id == search.case_id,
                                    MediaFile.kind == "video",
                                    MediaFile.excluded.is_(False))
            .order_by(MediaFile.uploaded_at))).scalars().all()
        indexes = {i.media_file_id: i for i in (await session.execute(
            select(VideoIndex).where(VideoIndex.case_id == search.case_id)
        )).scalars().all()}
    if wanted:
        media = [m for m in media if m.id in wanted]
    ready, skipped = [], []
    for m in media:
        idx = indexes.get(m.id)
        label = m.source_label_ar or m.original_filename
        if idx is None:
            skipped.append({"media_file_id": m.id, "label": label,
                            "reason": "no_index"})
        elif idx.status != "ready":
            skipped.append({"media_file_id": m.id, "label": label,
                            "reason": idx.status})
        elif idx.embedder_name != embedder_name:
            skipped.append({"media_file_id": m.id, "label": label,
                            "reason": "embedder_mismatch"})
        else:
            ready.append((m, idx))
    return ready, skipped


async def _extract_frame(settings: Settings, src: Path, ts: float,
                         search_id: str, i: int) -> tuple[bytes, str]:
    """Full-res frame at ts → (upscaled JPEG bytes for the model, thumb rel path)."""
    out = settings.tmp_dir / f"vsearch-{search_id}-{i}.jpg"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-v", "error", "-ss", f"{ts:.3f}", "-i", str(src),
        "-frames:v", "1", "-q:v", "2", str(out),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.wait()
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"no frame at {ts:.2f}s")

    def _prepare() -> tuple[bytes, bytes]:
        with Image.open(out) as im:
            img = im.convert("RGB")
        thumb = img.copy()
        thumb.thumbnail((640, 640))
        tbuf = io.BytesIO()
        thumb.save(tbuf, "JPEG", quality=80)
        if max(img.size) < VERIFY_MIN_PX:
            s = VERIFY_MIN_PX / max(img.size)
            img = img.resize((round(img.width * s), round(img.height * s)),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return buf.getvalue(), tbuf.getvalue()

    model_bytes, thumb_bytes = await asyncio.to_thread(_prepare)
    out.unlink(missing_ok=True)
    thumb_path = derived_path(settings, "videosearch", search_id, f"{i:03d}.jpg")
    await asyncio.to_thread(thumb_path.write_bytes, thumb_bytes)
    return model_bytes, rel_to_data(settings, thumb_path)


async def _set(factory, search_id: str, **values) -> None:
    async with factory() as session:
        await session.execute(
            update(VideoSearch).where(VideoSearch.id == search_id).values(**values))
        await session.commit()


def search_dict(s: VideoSearch) -> dict:
    return {
        "id": s.id, "case_id": s.case_id, "query_ar": s.query_ar,
        "status": s.status, "sensitive": s.sensitive,
        "progress_current": s.progress_current, "progress_total": s.progress_total,
        "query_variants": (s.query_variants_json or {}).get("english_variants", []),
        "media_ids": s.media_ids_json or [],
        "results": s.results_json,
        "latency_ms": s.latency_ms, "error": s.error,
        "created_at": s.created_at.isoformat(),
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
    }


def index_dict(i: VideoIndex | None) -> dict:
    if i is None:
        return {"status": "none"}
    return {
        "id": i.id, "media_file_id": i.media_file_id, "status": i.status,
        "embedder_name": i.embedder_name, "dim": i.dim, "fps": i.fps,
        "frames_seen": i.frames_seen, "frames_indexed": i.frames_indexed,
        "progress_current": i.progress_current, "progress_total": i.progress_total,
        "duration_s": i.duration_s, "error": i.error,
        "built_at": i.built_at.isoformat() if i.built_at else None,
    }
