"""EXIF / ffprobe metadata capture — file metadata is itself evidence."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import ExifTags, Image

EXIF_DT_KEYS = (36867, 306)  # DateTimeOriginal, DateTime


def image_meta(path: Path) -> dict:
    out: dict = {"width": None, "height": None, "exif": {}, "creation_time": None}
    try:
        with Image.open(path) as img:
            out["width"], out["height"] = img.size
            exif = img.getexif()
            if exif:
                plain: dict = {}
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                    plain[tag] = _safe(value)
                gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
                if gps:
                    coords = _gps_coords(gps)
                    if coords:
                        plain["gps"] = coords
                out["exif"] = plain
                for key in EXIF_DT_KEYS:
                    raw = exif.get(key)
                    if raw:
                        try:
                            dt = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
                            out["creation_time"] = dt.replace(tzinfo=timezone.utc).isoformat()
                            break
                        except ValueError:
                            continue
    except Exception:
        pass
    return out


def _gps_coords(gps) -> dict | None:
    try:
        def to_deg(vals, ref, neg):
            d = float(vals[0]) + float(vals[1]) / 60 + float(vals[2]) / 3600
            return -d if ref in neg else d
        lat = to_deg(gps[2], gps.get(1, "N"), ("S",))
        lon = to_deg(gps[4], gps.get(3, "E"), ("W",))
        return {"lat": round(lat, 6), "lon": round(lon, 6)}
    except Exception:
        return None


def _safe(value):
    if isinstance(value, bytes):
        return value.hex()[:200]
    if isinstance(value, (int, float, str, bool)) or value is None:
        return str(value)[:500] if isinstance(value, str) else value
    return str(value)[:500]


async def probe_video(path: Path) -> dict:
    """ffprobe → {ffprobe: full json, width, height, duration_s, fps, creation_time}."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    info: dict = {}
    try:
        info = json.loads(stdout.decode("utf-8", "replace")) if stdout else {}
    except json.JSONDecodeError:
        info = {}
    out = {"ffprobe": info, "width": None, "height": None,
           "duration_s": None, "fps": None, "creation_time": None}
    fmt = info.get("format", {})
    if fmt.get("duration"):
        try:
            out["duration_s"] = float(fmt["duration"])
        except ValueError:
            pass
    created = (fmt.get("tags") or {}).get("creation_time")
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            out["width"] = stream.get("width")
            out["height"] = stream.get("height")
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
            try:
                num, den = rate.split("/")
                if float(den):
                    out["fps"] = round(float(num) / float(den), 3)
            except (ValueError, ZeroDivisionError):
                pass
            created = created or (stream.get("tags") or {}).get("creation_time")
            break
    if created:
        try:
            out["creation_time"] = datetime.fromisoformat(
                created.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return out
