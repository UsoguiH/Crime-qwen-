"""Annotated copies: category-colored boxes + Arabic-Indic numbered badges.

Rules (from the design system + Unicode facts):
- Originals are never touched — we always draw on copies.
- No shaped Arabic words are rasterized. Badges carry only Arabic-Indic digits
  (non-joining glyphs — render correctly without a shaping engine).
- Human-presence regions are Gaussian-blurred by default before boxes are drawn.
"""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.services.numerals import to_arabic_indic

CATEGORY_COLORS = {
    "weapons": "#c25e4c",
    "biological": "#a94464",
    "impressions": "#7b6fa8",
    "documents_devices": "#4e7fa5",
    "scene_markers": "#8a7b3c",
    "trace": "#5e8f6c",
    "human_presence": "#6b6b6b",
}
FALLBACK_COLOR = "#26251e"

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/ibmplexsansarabic/IBMPlexSansArabic-SemiBold.ttf",
    "/usr/share/fonts/truetype/ibmplexsansarabic/IBMPlexSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@dataclass
class BoxSpec:
    x1: float  # normalized 0..1
    y1: float
    x2: float
    y2: float
    entity_seq: int
    category: str = ""
    blur: bool = False


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def annotate_image(src: Path, dst: Path, boxes: list[BoxSpec]) -> None:
    with Image.open(src) as im:
        img = im.convert("RGB")
    w, h = img.size

    # blur passes first, so boxes/badges stay crisp on top
    for box in boxes:
        if not box.blur:
            continue
        px = _pixels(box, w, h)
        region = img.crop(px)
        radius = max(10, (px[2] - px[0]) // 8)
        img.paste(region.filter(ImageFilter.GaussianBlur(radius)), px)

    draw = ImageDraw.Draw(img)
    stroke = max(3, min(w, h) // 300)
    badge_d = max(30, min(w, h) // 18)
    font = _font(int(badge_d * 0.62))

    for box in boxes:
        color = CATEGORY_COLORS.get(box.category, FALLBACK_COLOR)
        x1, y1, x2, y2 = _pixels(box, w, h)
        draw.rectangle((x1, y1, x2, y2), outline=color, width=stroke)
        # badge hugs the top-right box corner (RTL reading direction)
        cx = min(w - badge_d // 2 - 2, max(badge_d // 2 + 2, x2))
        cy = max(badge_d // 2 + 2, y1)
        draw.ellipse((cx - badge_d // 2, cy - badge_d // 2,
                      cx + badge_d // 2, cy + badge_d // 2),
                     fill=color, outline="#ffffff", width=max(2, stroke // 2))
        label = to_arabic_indic(box.entity_seq)
        draw.text((cx, cy), label, font=font, fill="#ffffff", anchor="mm")

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=90)


def crop_entity(src: Path, dst: Path, box: BoxSpec, pad: float = 0.18) -> None:
    with Image.open(src) as im:
        img = im.convert("RGB")
    w, h = img.size
    x1, y1, x2, y2 = _pixels(box, w, h)
    dx = int((x2 - x1) * pad) + 8
    dy = int((y2 - y1) * pad) + 8
    region = img.crop((max(0, x1 - dx), max(0, y1 - dy),
                       min(w, x2 + dx), min(h, y2 + dy)))
    if box.blur:
        region = region.filter(ImageFilter.GaussianBlur(max(10, region.width // 8)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    region.save(dst, "JPEG", quality=90)


def _pixels(box: BoxSpec, w: int, h: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(w - 2, int(box.x1 * w)))
    y1 = max(0, min(h - 2, int(box.y1 * h)))
    x2 = max(x1 + 1, min(w - 1, int(box.x2 * w)))
    y2 = max(y1 + 1, min(h - 1, int(box.y2 * h)))
    return x1, y1, x2, y2
