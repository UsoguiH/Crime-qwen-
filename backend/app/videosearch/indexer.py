"""Build the retrieval index for one video (the one-time heavy pass, off the
query path): decode at a fixed frame rate → phash still-skip → embed kept
frames → float16 vectors + timestamps in an .npz sidecar under derived/.
"""
import asyncio
import json
import logging
import shutil
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image
from sqlalchemy import select, update

from app.config import Settings
from app.core import utcnow
from app.db.models import MediaFile, VideoIndex
from app.services.storage import derived_path, rel_to_data, safe_resolve
from app.videosearch.embedder import get_embedder

log = logging.getLogger("athar.videosearch")

EMBED_BATCH = 32


def sidecar_save(path: Path, vectors: np.ndarray, timestamps: list[float],
                 meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path, vectors=vectors.astype(np.float16),
        timestamps=np.asarray(timestamps, dtype=np.float32),
        meta=np.array([json.dumps(meta, ensure_ascii=False)]))


def sidecar_load(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    with np.load(path, allow_pickle=False) as z:
        vectors = z["vectors"].astype(np.float32)
        timestamps = z["timestamps"].astype(np.float32)
        meta = json.loads(str(z["meta"][0]))
    # renormalize: float16 quantization nudges norms off 1.0
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-8), timestamps, meta


async def build_index(settings: Settings, factory, media_id: str) -> None:
    async with factory() as session:
        media = (await session.execute(
            select(MediaFile).where(MediaFile.id == media_id))).scalar_one()
        row = (await session.execute(
            select(VideoIndex).where(VideoIndex.media_file_id == media_id)
        )).scalar_one_or_none()
        if row is None:
            row = VideoIndex(media_file_id=media_id, case_id=media.case_id)
            session.add(row)
        row.status = "building"
        row.error = None
        row.fps = settings.video_index_fps
        await session.commit()
        index_id = row.id

    tmp = settings.tmp_dir / f"vidx-{media_id}"
    try:
        src = safe_resolve(settings, media.stored_path)
        frames = await _decode_frames(settings, src, tmp)
        if not frames:
            raise RuntimeError("ffmpeg produced no frames for this video")
        await _set(factory, index_id, frames_seen=len(frames),
                   progress_total=len(frames))

        # load OFF the event loop: first use downloads/loads ~1GB of weights,
        # which would otherwise freeze the whole backend (every request hangs)
        embedder = await asyncio.to_thread(get_embedder, settings)
        skip_dist = settings.video_index_still_skip_distance
        vectors: list[np.ndarray] = []
        timestamps: list[float] = []
        batch_imgs: list[Image.Image] = []
        batch_ts: list[float] = []
        prev_hash = None
        done = 0

        async def flush() -> None:
            nonlocal batch_imgs, batch_ts
            if not batch_imgs:
                return
            vecs = await asyncio.to_thread(embedder.embed_images, batch_imgs)
            vectors.append(vecs)
            timestamps.extend(batch_ts)
            for im in batch_imgs:
                im.close()
            batch_imgs, batch_ts = [], []
            await _set(factory, index_id, progress_current=done,
                       frames_indexed=len(timestamps))

        for ts, path in frames:
            done += 1
            phash = await asyncio.to_thread(_phash, path)
            if (prev_hash is not None and phash is not None
                    and prev_hash - phash <= skip_dist):
                continue  # near-identical still — the previous frame covers it
            if phash is not None:
                prev_hash = phash
            batch_imgs.append(Image.open(path).convert("RGB"))
            batch_ts.append(ts)
            if len(batch_imgs) >= EMBED_BATCH:
                await flush()
        await flush()

        if not timestamps:
            raise RuntimeError("no frames survived still-skip")
        matrix = np.concatenate(vectors, axis=0)
        sidecar = derived_path(settings, "videoindex", f"{media_id}.npz")
        meta = {"media_file_id": media_id, "embedder": embedder.name,
                "dim": int(matrix.shape[1]), "fps": settings.video_index_fps,
                "frames_seen": len(frames), "frames_indexed": len(timestamps)}
        await asyncio.to_thread(sidecar_save, sidecar, matrix, timestamps, meta)

        await _set(factory, index_id, status="ready", built_at=utcnow(),
                   embedder_name=embedder.name, dim=int(matrix.shape[1]),
                   frames_indexed=len(timestamps), progress_current=len(frames),
                   sidecar_path=rel_to_data(settings, sidecar),
                   duration_s=media.duration_s,
                   params_json={"still_skip_distance": skip_dist,
                                "max_side": settings.video_index_max_side})
        log.info("index ready for %s: %d/%d frames kept",
                 media.original_filename, len(timestamps), len(frames))
    except Exception as exc:
        await _set(factory, index_id, status="failed",
                   error=f"{type(exc).__name__}: {exc}"[:1500])
        raise
    finally:
        await asyncio.to_thread(shutil.rmtree, tmp, True)


async def _decode_frames(settings: Settings, src: Path,
                         tmp: Path) -> list[tuple[float, Path]]:
    """One ffmpeg pass: sample at the index rate, downscale (the embedder's
    processor resizes further anyway). Frame k of the fps filter sits at k/fps."""
    tmp.mkdir(parents=True, exist_ok=True)
    fps = settings.video_index_fps
    vf = f"fps={fps},scale={settings.video_index_max_side}:-2"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf,
        "-q:v", "5", str(tmp / "f%08d.jpg"),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode(errors='replace')[:500]}")
    files = sorted(tmp.glob("f*.jpg"))
    return [(k / fps, p) for k, p in enumerate(files)]


def _phash(path: Path):
    try:
        with Image.open(path) as im:
            return imagehash.phash(im)
    except Exception:
        return None


async def _set(factory, index_id: str, **values) -> None:
    async with factory() as session:
        await session.execute(
            update(VideoIndex).where(VideoIndex.id == index_id).values(**values))
        await session.commit()
