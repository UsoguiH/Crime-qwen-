"""Builds the ground-truth test set from COCO val2017 (real labeled data).

Selects images containing target classes (knife, scissors, cell phone, laptop,
bottle, book), excludes images with people, filters tiny boxes, downloads the
images, and writes data/groundtruth.json with pixel + rel-1000 boxes.

Run: python eval/dataset.py   (network required; annotations zip ~241MB, cached)
"""
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).resolve().parent / "data"
ANN_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
IMG_URL = "http://images.cocodataset.org/val2017/{file_name}"

TARGET_CLASSES = ["knife", "scissors", "cell phone", "laptop", "bottle", "book"]
PER_CLASS = 18              # more images → tighter accuracy estimates for the iteration
MIN_AREA_RATIO = 0.004      # box ≥0.4% of image — excludes unfairly tiny objects
MAX_TARGET_BOXES = 8        # keep matching tractable per image


def _download_annotations() -> Path:
    out = DATA_DIR / "instances_val2017.json"
    if out.exists():
        return out
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / "annotations_trainval2017.zip"
    if not zip_path.exists():
        print(f"downloading {ANN_URL} (~241MB)…", flush=True)
        with httpx.stream("GET", ANN_URL, timeout=None,
                          follow_redirects=True) as resp:
            resp.raise_for_status()
            done = 0
            with open(zip_path, "wb") as fp:
                for chunk in resp.iter_bytes(1 << 20):
                    fp.write(chunk)
                    done += len(chunk)
                    if done % (40 << 20) < (1 << 20):
                        print(f"  …{done >> 20} MB", flush=True)
    print("extracting instances_val2017.json…", flush=True)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("annotations/instances_val2017.json") as src:
            out.write_bytes(src.read())
    return out


def build() -> dict:
    ann_path = _download_annotations()
    print("indexing annotations…", flush=True)
    coco = json.loads(ann_path.read_text(encoding="utf-8"))
    cat_by_name = {c["name"]: c["id"] for c in coco["categories"]}
    cat_name = {c["id"]: c["name"] for c in coco["categories"]}
    person_id = cat_by_name["person"]
    target_ids = {cat_by_name[n] for n in TARGET_CLASSES}

    anns_by_img: dict[int, list] = defaultdict(list)
    for a in coco["annotations"]:
        if a.get("iscrowd"):
            continue
        anns_by_img[a["image_id"]].append(a)
    images = {im["id"]: im for im in coco["images"]}

    selected: dict[int, dict] = {}
    counts = {n: 0 for n in TARGET_CLASSES}
    for img_id in sorted(anns_by_img):
        anns = anns_by_img[img_id]
        if any(a["category_id"] == person_id for a in anns):
            continue
        im = images[img_id]
        area = im["width"] * im["height"]
        target = [a for a in anns if a["category_id"] in target_ids
                  and a["bbox"][2] * a["bbox"][3] / area >= MIN_AREA_RATIO]
        if not target or len(target) > MAX_TARGET_BOXES:
            continue
        classes_here = {cat_name[a["category_id"]] for a in target}
        needed = [c for c in classes_here if counts[c] < PER_CLASS]
        if not needed:
            continue
        for c in classes_here:
            counts[c] += 1
        selected[img_id] = {"im": im, "target": target}
        if all(v >= PER_CLASS for v in counts.values()):
            break

    print(f"selected {len(selected)} images; per-class image counts: {counts}",
          flush=True)

    img_dir = DATA_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    gt_images = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for img_id, spec in selected.items():
            im = spec["im"]
            dst = img_dir / im["file_name"]
            if not dst.exists():
                resp = client.get(IMG_URL.format(file_name=im["file_name"]))
                resp.raise_for_status()
                dst.write_bytes(resp.content)
            W, H = im["width"], im["height"]
            gt = []
            for a in spec["target"]:
                x, y, w, h = a["bbox"]
                gt.append({
                    "cls": cat_name[a["category_id"]],
                    "bbox_px": [round(x, 1), round(y, 1),
                                round(x + w, 1), round(y + h, 1)],
                    "rel1000": [round(x / W * 1000), round(y / H * 1000),
                                round((x + w) / W * 1000), round((y + h) / H * 1000)],
                    "area_ratio": round(w * h / (W * H), 4),
                })
            gt_images.append({"id": img_id, "file": im["file_name"],
                              "width": W, "height": H, "gt": gt})

    total_boxes = sum(len(x["gt"]) for x in gt_images)
    box_counts: dict[str, int] = defaultdict(int)
    for x in gt_images:
        for g in x["gt"]:
            box_counts[g["cls"]] += 1
    payload = {"classes": TARGET_CLASSES, "images": gt_images,
               "total_boxes": total_boxes, "boxes_per_class": dict(box_counts),
               "params": {"per_class": PER_CLASS, "min_area_ratio": MIN_AREA_RATIO,
                          "max_target_boxes": MAX_TARGET_BOXES,
                          "person_excluded": True}}
    (DATA_DIR / "groundtruth.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"groundtruth ready: {len(gt_images)} images, {total_boxes} boxes "
          f"→ {dict(box_counts)}", flush=True)
    return payload


if __name__ == "__main__":
    build()
