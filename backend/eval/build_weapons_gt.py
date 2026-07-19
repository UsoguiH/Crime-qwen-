"""Parse Pascal-VOC weapon annotations (UGR OD-WeaponDetection / WeaponS) into
the same groundtruth.json format the scorer uses. Real photos, expert boxes.

Usage: python eval/build_weapons_gt.py <images_dir> <xmls_dir> [--limit 60] [--out realdata/weapons_gt.json]
"""
import argparse
import json
import random
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# map raw VOC class names → our canonical weapon label
CLASS_MAP = {"pistol": "handgun", "handgun": "handgun", "gun": "handgun",
             "weapon": "handgun", "knife": "knife", "cuchillo": "knife"}


def _find(images_dir: Path, stem: str) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
        p = images_dir / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def collect(images_dir: Path, xmls_dir: Path, limit: int, seed: int) -> list[dict]:
    xmls = sorted(xmls_dir.glob("*.xml"))
    random.Random(seed).shuffle(xmls)
    out_images: list[dict] = []
    for xf in xmls:
        try:
            root = ET.parse(xf).getroot()
        except ET.ParseError:
            continue
        size = root.find("size")
        if size is None:
            continue
        W = int(float(size.findtext("width", "0")))
        H = int(float(size.findtext("height", "0")))
        if W < 10 or H < 10:
            continue
        img = _find(images_dir, xf.stem) or (
            _find(images_dir, root.findtext("filename", "").rsplit(".", 1)[0]))
        if img is None:
            continue
        gt = []
        for obj in root.findall("object"):
            raw = (obj.findtext("name", "") or "").strip().lower()
            cls = CLASS_MAP.get(raw)
            if cls is None:
                continue
            bb = obj.find("bndbox")
            if bb is None:
                continue
            x1 = float(bb.findtext("xmin", "0")); y1 = float(bb.findtext("ymin", "0"))
            x2 = float(bb.findtext("xmax", "0")); y2 = float(bb.findtext("ymax", "0"))
            if x2 <= x1 or y2 <= y1:
                continue
            gt.append({"cls": cls,
                       "bbox_px": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                       "rel1000": [round(x1 / W * 1000), round(y1 / H * 1000),
                                   round(x2 / W * 1000), round(y2 / H * 1000)],
                       "area_ratio": round((x2 - x1) * (y2 - y1) / (W * H), 4)})
        if not gt:
            continue
        out_images.append({"id": f"{images_dir.parent.name[:3]}-{xf.stem}",
                           "file": img.name, "src": str(img),
                           "width": W, "height": H, "gt": gt})
        if len(out_images) >= limit:
            break
    return out_images


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=["ugr"], default="ugr")
    ap.add_argument("--root", default=str(_HERE / "realdata" / "OD-WeaponDetection"))
    ap.add_argument("--per-class", type=int, default=35)
    ap.add_argument("--out", default=str(_HERE / "realdata" / "weapons_gt.json"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    root = Path(args.root)
    sources = [
        (root / "Pistol detection" / "Weapons", root / "Pistol detection" / "xmls"),
        (root / "Knife_detection" / "Images", root / "Knife_detection" / "annotations"),
    ]
    images: list[dict] = []
    for images_dir, xmls_dir in sources:
        if images_dir.exists() and xmls_dir.exists():
            images += collect(images_dir, xmls_dir, args.per_class, args.seed)

    boxes_per_class: dict[str, int] = {}
    for x in images:
        for g in x["gt"]:
            boxes_per_class[g["cls"]] = boxes_per_class.get(g["cls"], 0) + 1
    total = sum(len(x["gt"]) for x in images)
    payload = {"classes": sorted(boxes_per_class), "images": images,
               "total_boxes": total, "boxes_per_class": boxes_per_class,
               "source": "UGR OD-WeaponDetection (real photos, Pascal-VOC)"}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"weapons GT: {len(images)} real images, {total} boxes → {boxes_per_class}")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
