"""Generates the staged, innocuous sample media (deterministic drawings whose
object positions match the bundled mock fixtures). No real evidence, no persons.

Run: python scripts/make_samples.py   (ffmpeg required for the videos)
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples" / "media"

WOOD = "#a97c50"
WOOD_LINE = "#8a6540"


def _wood_bg(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), WOOD)
    d = ImageDraw.Draw(img)
    for y in range(0, h, 80):
        d.line((0, y, w, y), fill=WOOD_LINE, width=3)
    return img


def _knife(d: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int) -> None:
    """Chef-knife silhouette inside the pixel box: pointed curved blade with a
    bright spine + darker edge bevel, bolster, riveted dark handle, soft shadow."""
    h = y2 - y1
    split = x1 + int((x2 - x1) * 0.66)      # blade | handle boundary
    cy = (y1 + y2) // 2
    # soft contact shadow
    d.ellipse((x1 + 6, y2 - h // 4, x2, y2 + h // 3), fill="#8a6540")
    # blade body: pointed tip, gently curved cutting edge
    blade = [(x1, cy - h // 8), (x1 + (split - x1) // 3, y1 + 2),
             (split, y1), (split, y2 - 2),
             (x1 + (split - x1) // 3, y2 - h // 6)]
    d.polygon(blade, fill="#c9ccd1", outline="#8f9399")
    # spine highlight + edge bevel
    d.line([(x1 + (split - x1) // 3, y1 + 4), (split, y1 + 3)], fill="#eef0f2", width=3)
    d.polygon([(x1, cy - h // 8), (x1 + (split - x1) // 3, y2 - h // 6),
               (split, y2 - 2), (split, y2 - h // 5)], fill="#aeb2b8")
    # bolster
    d.rectangle((split - 6, y1 + 1, split + 8, y2 - 1), fill="#6d7075")
    # handle with rivets
    d.rounded_rectangle((split + 8, y1 + 3, x2, y2 - 3), radius=h // 3, fill="#2e2620")
    d.rounded_rectangle((split + 8, y1 + 3, x2, cy), radius=h // 3, fill="#3a2f27")
    for rx in (split + (x2 - split) // 3, split + 2 * (x2 - split) // 3):
        d.ellipse((rx - 4, cy - 4, rx + 4, cy + 4), fill="#8f9399")


def rel_box(rel, w, h):
    x1, y1, x2, y2 = rel
    return int(x1 / 1000 * w), int(y1 / 1000 * h), int(x2 / 1000 * w), int(y2 / 1000 * h)


def kitchen_knife_table(dst: Path) -> None:
    w, h = 1200, 800
    img = _wood_bg(w, h)
    d = ImageDraw.Draw(img)
    _knife(d, *rel_box([417, 419, 717, 469], w, h))
    img.save(dst, "JPEG", quality=90)


def desk_documents(dst: Path) -> None:
    w, h = 1000, 800
    img = Image.new("RGB", (w, h), "#8a6f52")
    d = ImageDraw.Draw(img)
    for i, (dx, dy, ang_off) in enumerate([(0, 0, 0), (40, 60, 12), (90, 130, -8)]):
        x1, y1, x2, y2 = rel_box([140, 300, 480, 620], w, h)
        d.rectangle((x1 + dx, y1 + dy, x1 + dx + 220, y1 + dy + 160),
                    fill="#f4f1e8", outline="#d9d4c4", width=2)
        for line in range(4):
            d.line((x1 + dx + 18, y1 + dy + 30 + line * 28,
                    x1 + dx + 200, y1 + dy + 30 + line * 28), fill="#8f8a78", width=3)
    x1, y1, x2, y2 = rel_box([610, 380, 790, 560], w, h)
    d.rounded_rectangle((x1, y1, x2, y2), radius=18, fill="#1d1d22", outline="#404048", width=3)
    img.save(dst, "JPEG", quality=90)


def juice_spill(dst: Path) -> None:
    w = h = 1000
    img = Image.new("RGB", (w, h), "#e8e4da")
    d = ImageDraw.Draw(img)
    for x in range(0, w, 200):
        d.line((x, 0, x, h), fill="#cfcabc", width=4)
    for y in range(0, h, 200):
        d.line((0, y, w, y), fill="#cfcabc", width=4)
    x1, y1, x2, y2 = rel_box([340, 430, 700, 760], w, h)
    d.ellipse((x1, y1, x2, y2), fill="#8f1d24")
    d.ellipse((x1 + 60, y2 - 70, x1 + 160, y2 + 40), fill="#8f1d24")
    d.ellipse((x2 - 90, y1 - 30, x2 + 10, y1 + 60), fill="#a3323a")
    img.save(dst, "JPEG", quality=90)


def shoeprint_sand(dst: Path) -> None:
    w = h = 1000
    img = Image.new("RGB", (w, h), "#d9c39a")
    d = ImageDraw.Draw(img)
    for y in range(0, h, 26):
        d.line((0, y, w, y), fill="#d1ba8f", width=2)
    x1, y1, x2, y2 = rel_box([330, 260, 660, 740], w, h)
    d.ellipse((x1, y1, x2, y1 + int((y2 - y1) * 0.62)), fill="#b39468")
    d.ellipse((x1 + 30, y2 - 140, x2 - 30, y2), fill="#b39468")
    for i in range(6):
        ty = y1 + 30 + i * 44
        d.rectangle((x1 + 24, ty, x2 - 24, ty + 18), fill="#8f744e")
    img.save(dst, "JPEG", quality=90)


def broken_glass(dst: Path) -> None:
    w = h = 1000
    img = Image.new("RGB", (w, h), "#b9b9b3")
    d = ImageDraw.Draw(img)
    x1, y1, x2, y2 = rel_box([220, 480, 780, 830], w, h)
    shards = [
        [(x1, y2 - 40), (x1 + 90, y1 + 30), (x1 + 150, y2 - 80)],
        [(x1 + 200, y1), (x1 + 300, y1 + 90), (x1 + 180, y1 + 140)],
        [(x2 - 220, y1 + 60), (x2 - 90, y1 + 10), (x2 - 120, y1 + 170)],
        [(x2 - 60, y2 - 120), (x2, y2 - 30), (x2 - 160, y2)],
        [((x1 + x2) // 2, y2 - 150), ((x1 + x2) // 2 + 110, y2 - 60),
         ((x1 + x2) // 2 - 40, y2 - 20)],
    ]
    for s in shards:
        d.polygon(s, fill="#dfe9ec", outline="#aebfc4")
    img.save(dst, "JPEG", quality=90)


def markers_ruler(dst: Path) -> None:
    w = h = 1000
    img = Image.new("RGB", (w, h), "#9d9a90")
    d = ImageDraw.Draw(img)
    x1, y1, x2, y2 = rel_box([250, 350, 520, 560], w, h)
    for i, off in enumerate((0, 150)):
        bx = x1 + off
        d.polygon([(bx, y2), (bx + 110, y2), (bx + 55, y1)], fill="#e8c31c",
                  outline="#a98d0d")
        d.text((bx + 44, (y1 + y2) // 2 + 20), str(i + 1), fill="#26251e")
    rx1, ry1, rx2, ry2 = rel_box([560, 600, 860, 660], w, h)
    d.rectangle((rx1, ry1, rx2, ry2), fill="#f2efe6", outline="#26251e", width=3)
    for i in range(0, rx2 - rx1, 30):
        d.line((rx1 + i, ry1, rx1 + i, ry1 + 18), fill="#26251e", width=3)
    img.save(dst, "JPEG", quality=90)


def _video(dst: Path, creation_time: str, pos_a, pos_b, shift: int = 0) -> None:
    w, h = 960, 720
    tmp = dst.parent / f"_frames_{dst.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        img = _wood_bg(w, h)
        d = ImageDraw.Draw(img)
        rel = pos_a if i < 5 else pos_b
        x1, y1, x2, y2 = rel_box(rel, w, h)
        _knife(d, x1 + shift, y1, x2 + shift, y2)
        img.save(tmp / f"frame_{i:02d}.png")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-framerate", "1",
        "-i", str(tmp / "frame_%02d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25",
        "-metadata", f"creation_time={creation_time}",
        str(dst)], check=True)
    for f in tmp.glob("*.png"):
        f.unlink()
    tmp.rmdir()


def calibration_grid(dst: Path) -> None:
    w = h = 1000
    img = Image.new("RGB", (w, h), "#ffffff")
    d = ImageDraw.Draw(img)
    boxes = {"#d62828": [100, 100, 300, 300], "#2a9d4a": [700, 100, 900, 250],
             "#1d6fb8": [150, 650, 350, 900], "#c08532": [600, 600, 900, 900]}
    for color, rel in boxes.items():
        d.rectangle(rel_box(rel, w, h), fill=color)
    img.save(dst, "PNG")


ALL = {
    "kitchen_knife_table.jpg": kitchen_knife_table,
    "desk_documents.jpg": desk_documents,
    "juice_spill.jpg": juice_spill,
    "shoeprint_sand.jpg": shoeprint_sand,
    "broken_glass.jpg": broken_glass,
    "markers_ruler.jpg": markers_ruler,
}

KNIFE_A = [180, 420, 470, 480]
KNIFE_B = [560, 620, 850, 680]


def ensure_samples(with_videos: bool = True) -> Path:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for name, fn in ALL.items():
        path = SAMPLES_DIR / name
        if not path.exists():
            fn(path)
    calib = SAMPLES_DIR.parent / "calibration"
    calib.mkdir(parents=True, exist_ok=True)
    if not (calib / "grid.png").exists():
        calibration_grid(calib / "grid.png")
    if with_videos:
        vids = {
            "kitchen_knife_move.mp4": ("2026-07-19T10:00:00Z", 0),
            "two_angle_a.mp4": ("2026-07-19T10:00:00Z", 0),
            "two_angle_b.mp4": ("2026-07-19T10:00:30Z", 25),
        }
        for name, (created, shift) in vids.items():
            path = SAMPLES_DIR / name
            if not path.exists():
                try:
                    _video(path, created, KNIFE_A, KNIFE_B, shift)
                except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                    print(f"skip video {name}: {exc}", file=sys.stderr)
    return SAMPLES_DIR


if __name__ == "__main__":
    out = ensure_samples()
    print(f"samples ready in {out}")
