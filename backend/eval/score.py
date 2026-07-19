"""Scores an eval run against COCO ground truth. No self-reported accuracy —
class-aware greedy IoU matching, per-class metrics, FP taxonomy, failure renders.

  python eval/score.py <tag> [--match name|category] [--iou 0.5]
  python eval/score.py --compare tagA,tagB,...
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DATA_DIR = _HERE / "data"
OUT_DIR = _HERE / "outputs"

CLASS_KEYWORDS = {
    "laptop": ["حاسوب", "لابتوب", "حاسب"],
    "cell phone": ["هاتف", "جوال", "موبايل"],
    "knife": ["سكين", "سكاكين", "خنجر", "نصل", "شفرة", "مدية"],
    "scissors": ["مقص"],
    "bottle": ["زجاجة", "قارورة", "قنينة", "عبوة"],
    "book": ["كتاب", "كتب", "دفتر", "مجلد"],
}
PRIORITY = list(CLASS_KEYWORDS)  # laptop before cell phone («حاسوب محمول»)
CATEGORY_OF = {"knife": "weapons", "scissors": "weapons",
               "cell phone": "documents_devices", "laptop": "documents_devices",
               "book": "documents_devices", "bottle": "trace"}


def iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua


def resolve_class(name_ar: str, category: str, match_mode: str):
    for cls in PRIORITY:
        if any(k in name_ar for k in CLASS_KEYWORDS[cls]):
            return [cls]
    if match_mode == "category":
        cands = [c for c, cat in CATEGORY_OF.items() if cat == category]
        return cands or None
    return None


def score(tag: str, match_mode: str, iou_thr: float) -> dict:
    gt_data = json.loads((DATA_DIR / "groundtruth.json").read_text(encoding="utf-8"))
    out = OUT_DIR / tag
    per_class = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "ious": []})
    fp_kinds = {"hallucination": 0, "bad_box": 0, "class_confusion": 0,
                "out_of_scope": 0}
    image_rows = []
    errored_images = 0

    for im in gt_data["images"]:
        path = out / f"{im['id']}.json"
        gts = [{"cls": g["cls"], "box": g["rel1000"], "matched": False}
               for g in im["gt"]]
        preds = []
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "error" in payload:
                errored_images += 1
            else:
                for d in payload["pred"]["detections"]:
                    preds.append({"name": d["name_ar"], "cat": d["category"],
                                  "box": d["bbox_2d"], "conf": d["confidence"]})
        else:
            errored_images += 1

        row = {"id": im["id"], "file": im["file"], "tp": 0, "fp": 0, "fn": 0,
               "events": []}
        for p in sorted(preds, key=lambda x: -x["conf"]):
            cands = resolve_class(p["name"], p["cat"], match_mode)
            if cands is None:
                fp_kinds["out_of_scope"] += 1
                row["fp"] += 1
                row["events"].append(f"FP خارج النطاق: «{p['name']}»")
                continue
            best, best_iou = None, 0.0
            for g in gts:
                if g["matched"] or g["cls"] not in cands:
                    continue
                v = iou(p["box"], g["box"])
                if v > best_iou:
                    best, best_iou = g, v
            if best is not None and best_iou >= iou_thr:
                best["matched"] = True
                per_class[best["cls"]]["tp"] += 1
                per_class[best["cls"]]["ious"].append(best_iou)
                row["tp"] += 1
            else:
                cls = cands[0]
                per_class[cls]["fp"] += 1
                row["fp"] += 1
                any_gt_iou = max((iou(p["box"], g["box"]) for g in gts
                                  if not g["matched"]), default=0.0)
                if any_gt_iou >= iou_thr:
                    fp_kinds["class_confusion"] += 1
                    row["events"].append(
                        f"FP خلط صنف: «{p['name']}» فوق عنصر من صنف آخر")
                elif best_iou > 0.1:
                    fp_kinds["bad_box"] += 1
                    row["events"].append(
                        f"FP صندوق منحرف: «{p['name']}» IoU={best_iou:.2f}")
                else:
                    fp_kinds["hallucination"] += 1
                    row["events"].append(f"FP اختلاق: «{p['name']}»")
        for g in gts:
            if not g["matched"]:
                per_class[g["cls"]]["fn"] += 1
                row["fn"] += 1
                row["events"].append(f"MISS: {g['cls']}")
        image_rows.append(row)

    tp = sum(v["tp"] for v in per_class.values())
    fp = sum(v["fp"] for v in per_class.values()) + fp_kinds["out_of_scope"]
    fn = sum(v["fn"] for v in per_class.values())
    all_ious = [x for v in per_class.values() for x in v["ious"]]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    metrics = {
        "tag": tag, "match_mode": match_mode, "iou_thr": iou_thr,
        "images": len(gt_data["images"]), "errored_images": errored_images,
        "gt_boxes": gt_data["total_boxes"],
        "predictions": tp + fp,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 3), "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3)
        if precision + recall else 0.0,
        "mean_iou": round(sum(all_ious) / len(all_ious), 3) if all_ious else 0.0,
        "hallucination_rate": round(fp / (tp + fp), 3) if tp + fp else 0.0,
        "miss_rate": round(fn / (tp + fn), 3) if tp + fn else 0.0,
        "fp_kinds": fp_kinds,
        "per_class": {
            cls: {
                "gt": v["tp"] + v["fn"], "tp": v["tp"], "fp": v["fp"],
                "fn": v["fn"],
                "precision": round(v["tp"] / (v["tp"] + v["fp"]), 3)
                if v["tp"] + v["fp"] else 0.0,
                "recall": round(v["tp"] / (v["tp"] + v["fn"]), 3)
                if v["tp"] + v["fn"] else 0.0,
                "mean_iou": round(sum(v["ious"]) / len(v["ious"]), 3)
                if v["ious"] else 0.0,
            } for cls, v in sorted(per_class.items())
        },
    }
    (out / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    _render_failures(tag, gt_data, image_rows)
    _print(metrics)
    return metrics


def _render_failures(tag: str, gt_data: dict, rows: list, top: int = 5) -> None:
    from PIL import Image, ImageDraw
    out = OUT_DIR / tag / "failures"
    out.mkdir(parents=True, exist_ok=True)
    worst = sorted(rows, key=lambda r: -(r["fn"] + r["fp"]))[:top]
    lines = [f"# أسوأ {len(worst)} إخفاقات — {tag}", ""]
    by_id = {im["id"]: im for im in gt_data["images"]}
    for r in worst:
        im = by_id[r["id"]]
        src = DATA_DIR / "images" / im["file"]
        preds_path = OUT_DIR / tag / f"{r['id']}.json"
        pred_boxes = []
        if preds_path.exists():
            payload = json.loads(preds_path.read_text(encoding="utf-8"))
            for d in payload.get("pred", {}).get("detections", []):
                pred_boxes.append((d["bbox_2d"], d["name_ar"]))
        try:
            with Image.open(src) as img0:
                img = img0.convert("RGB")
            W, H = img.size
            draw = ImageDraw.Draw(img)
            for g in im["gt"]:
                b = g["rel1000"]
                draw.rectangle([b[0] / 1000 * W, b[1] / 1000 * H,
                                b[2] / 1000 * W, b[3] / 1000 * H],
                               outline="#1f8a65", width=5)
            for b, _name in pred_boxes:
                draw.rectangle([b[0] / 1000 * W, b[1] / 1000 * H,
                                b[2] / 1000 * W, b[3] / 1000 * H],
                               outline="#cf2d56", width=3)
            img.save(out / f"{r['id']}.jpg", "JPEG", quality=88)
        except OSError:
            pass
        lines += [f"## {im['file']} (tp={r['tp']} fp={r['fp']} fn={r['fn']})",
                  "الحقيقة: " + "، ".join(g["cls"] for g in im["gt"]),
                  "الأحداث:"]
        lines += [f"- {e}" for e in r["events"]]
        lines.append("")
    (out.parent / "failures.md").write_text("\n".join(lines), encoding="utf-8")


def _print(m: dict) -> None:
    print(f"\n== {m['tag']} (match={m['match_mode']}, IoU≥{m['iou_thr']}) ==")
    print(f"images={m['images']} (errors={m['errored_images']}) "
          f"gt={m['gt_boxes']} preds={m['predictions']}")
    print(f"precision={m['precision']}  recall={m['recall']}  f1={m['f1']}  "
          f"meanIoU={m['mean_iou']}")
    print(f"hallucination_rate={m['hallucination_rate']}  "
          f"miss_rate={m['miss_rate']}  fp_kinds={m['fp_kinds']}")
    print(f"{'class':<12}{'gt':>4}{'tp':>4}{'fp':>4}{'fn':>4}"
          f"{'prec':>7}{'rec':>7}{'mIoU':>7}")
    for cls, v in m["per_class"].items():
        print(f"{cls:<12}{v['gt']:>4}{v['tp']:>4}{v['fp']:>4}{v['fn']:>4}"
              f"{v['precision']:>7}{v['recall']:>7}{v['mean_iou']:>7}")


def compare(tags: list[str]) -> None:
    rows = []
    for t in tags:
        p = OUT_DIR / t / "metrics.json"
        if not p.exists():
            print(f"no metrics for {t}")
            continue
        rows.append(json.loads(p.read_text(encoding="utf-8")))
    keys = ["precision", "recall", "f1", "mean_iou", "hallucination_rate",
            "miss_rate"]
    print(f"{'metric':<20}" + "".join(f"{r['tag']:>18}" for r in rows))
    for k in keys:
        print(f"{k:<20}" + "".join(f"{r[k]:>18}" for r in rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--match", choices=["name", "category"], default="name")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--compare")
    args = ap.parse_args()
    if args.compare:
        compare(args.compare.split(","))
    elif args.tag:
        score(args.tag, args.match, args.iou)
    else:
        ap.print_help()
        sys.exit(2)
