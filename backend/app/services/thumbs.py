import asyncio
from pathlib import Path

from PIL import Image


def make_image_thumb(src: Path, dst: Path, max_px: int = 480) -> None:
    with Image.open(src) as im:
        img = im.convert("RGB")
    img.thumbnail((max_px, max_px))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=82)


async def make_video_thumb(src: Path, dst: Path, at_s: float = 1.0) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-v", "quiet", "-ss", str(at_s), "-i", str(src),
        "-frames:v", "1", "-vf", "scale=480:-2", str(dst),
    )
    await proc.wait()
    return dst.exists()
