"""Stage 1 — keyframes: PySceneDetect scene changes + uniform fill + phash dedup."""
import asyncio
import logging

import imagehash
from PIL import Image
from sqlalchemy import select

from app.db.models import Frame, MediaFile
from app.pipeline.ctx import Ctx
from app.services.storage import derived_path, rel_to_data

log = logging.getLogger("athar.s1")


async def run(ctx: Ctx) -> None:
    media = await ctx.selected_media()
    checkpoint = await ctx.get_checkpoint(1)
    done: list[str] = checkpoint.get("done_media", [])
    await ctx.set_step(1, total=len(media), current=len(done))

    errors = []
    for m in media:
        if m.id in done:
            continue
        try:
            if m.kind == "video":
                await _extract_video(ctx, m)
            else:
                await _passthrough_image(ctx, m)
        except Exception as exc:
            log.warning("keyframes failed for %s: %s", m.original_filename, exc)
            errors.append(f"{m.original_filename}: {exc}")
        done.append(m.id)
        await ctx.set_step(1, current=len(done), checkpoint={"done_media": done})

    if errors:
        await ctx.set_step(1, status="completed_with_errors",
                           error=" | ".join(errors)[:1500])


async def _passthrough_image(ctx: Ctx, m: MediaFile) -> None:
    async with ctx.factory() as session:
        existing = (await session.execute(
            select(Frame).where(Frame.media_file_id == m.id))).scalars().first()
        if existing:
            return
        path = ctx.abs_path(m.stored_path)
        phash = await asyncio.to_thread(_phash, path)
        session.add(Frame(media_file_id=m.id, frame_index=0, timestamp_s=None,
                          stored_path=m.stored_path, phash=phash,
                          selection_reason="image",
                          width=m.width, height=m.height))
        await session.commit()


async def _extract_video(ctx: Ctx, m: MediaFile) -> None:
    async with ctx.factory() as session:
        existing = (await session.execute(
            select(Frame).where(Frame.media_file_id == m.id))).scalars().first()
        if existing:
            return

    src = ctx.abs_path(m.stored_path)
    duration = m.duration_s or 0.0
    interval = float(ctx.thr("keyframe_min_interval_s", ctx.settings.keyframe_min_interval_s))
    max_frames = int(ctx.thr("max_frames_per_video", 240))

    scene_times = await asyncio.to_thread(_scene_starts, str(src))
    times = _plan_timestamps(scene_times, duration, interval, max_frames)

    dedup_dist = int(ctx.thr("phash_dedup_distance", ctx.settings.phash_dedup_distance))
    prev_hash = None
    rows = []
    for idx, t in enumerate(times):
        dst = derived_path(ctx.settings, "frames", m.id, f"t{int(t * 1000):09d}.jpg")
        ok = await _ffmpeg_frame(src, dst, t)
        if not ok:
            continue
        phash_str = await asyncio.to_thread(_phash, dst)
        dropped = False
        if prev_hash is not None and phash_str:
            if _hamming(prev_hash, phash_str) <= dedup_dist:
                dropped = True
        if not dropped and phash_str:
            prev_hash = phash_str
        with Image.open(dst) as im:
            w, h = im.size
        reason = "scene_change" if t in scene_times else "uniform"
        rows.append(Frame(media_file_id=m.id, frame_index=idx, timestamp_s=round(t, 3),
                          stored_path=rel_to_data(ctx.settings, dst), phash=phash_str,
                          selection_reason=reason, dropped_dedup=dropped,
                          width=w, height=h))
    if not rows:
        raise RuntimeError("تعذر استخراج أي إطار من الفيديو")
    async with ctx.factory() as session:
        session.add_all(rows)
        await session.commit()


def _scene_starts(path: str) -> list[float]:
    try:
        from scenedetect import ContentDetector, detect
        scenes = detect(path, ContentDetector(threshold=27.0), show_progress=False)
        return sorted({round(start.seconds, 3) for start, _end in scenes})
    except Exception as exc:
        log.warning("scenedetect failed (%s), falling back to uniform only", exc)
        return []


def _plan_timestamps(scene_times: list[float], duration: float,
                     interval: float, max_frames: int) -> list[float]:
    times = set(scene_times)
    times.add(min(0.2, max(duration - 0.05, 0.0)))
    if duration > 0:
        anchors = sorted(times | {duration})
        filled = set(times)
        for a, b in zip(anchors, anchors[1:]):
            gap = b - a
            if gap > interval:
                n = int(gap // interval)
                for k in range(1, n + 1):
                    filled.add(round(a + k * gap / (n + 1), 3))
        times = filled
    ordered = sorted(t for t in times if 0 <= t < max(duration, 0.4) or duration == 0)
    if len(ordered) > max_frames:
        step = len(ordered) / max_frames
        ordered = [ordered[int(i * step)] for i in range(max_frames)]
    return ordered


async def _ffmpeg_frame(src, dst, t: float) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src),
        "-frames:v", "1", "-q:v", "2", str(dst),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return dst.exists() and dst.stat().st_size > 0


def _phash(path) -> str:
    try:
        with Image.open(path) as im:
            return str(imagehash.phash(im))
    except Exception:
        return ""


def _hamming(a: str, b: str) -> int:
    try:
        return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)
    except Exception:
        return 999
