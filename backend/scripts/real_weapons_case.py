"""Creates a REAL-WEAPONS case in the live app from the UGR weapon photos,
analyzes each (production thinking+ground+dedup), reports detected-vs-truth,
and renders boxes on a few for visual proof.
"""
import io
import json
import os
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

BASE = os.environ.get("ATHAR_API", "http://localhost:8000/api")
GT = Path("/app/eval/realdata/weapons_gt.json")
OUTDIR = Path("/app/eval/realdata/proof")


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2-ix1) * max(0, iy2-iy1)
    if inter <= 0:
        return 0.0
    return inter / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)


def main():
    gt = json.loads(GT.read_text(encoding="utf-8"))
    # 4 handgun + 4 knife
    hg = [x for x in gt["images"] if any(g["cls"] == "handgun" for g in x["gt"])][:4]
    kn = [x for x in gt["images"] if any(g["cls"] == "knife" for g in x["gt"])][:4]
    picks = hg + kn
    OUTDIR.mkdir(parents=True, exist_ok=True)

    c = httpx.Client(base_url=BASE, timeout=180)
    inv = next(u for u in c.get("/auth/users").raise_for_status().json()
               if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]}).raise_for_status()
    cases = c.get("/cases").raise_for_status().json()
    case = next((x for x in cases if x["case_number"] == "REAL-WEAPONS-01"), None)
    if case is None:
        case = c.post("/cases", json={
            "case_number": "REAL-WEAPONS-01",
            "title_ar": "أسلحة حقيقية — تقييم دقة على صور فعلية",
            "notes_ar": "صور أسلحة حقيقية (جامعة غرناطة) بمربعات مرجعية خبيرة.",
        }).raise_for_status().json()

    existing = {m["original_filename"]: m for m in
                c.get(f"/cases/{case['id']}/media").raise_for_status().json()}
    items = []
    for im in picks:
        if im["file"] in existing:
            media = existing[im["file"]]
        else:
            with open(im["src"], "rb") as fp:
                media = c.post(f"/cases/{case['id']}/media",
                               files={"file": (im["file"], fp, "image/jpeg")},
                               data={"source_type": "photo",
                                     "source_label_ar": "صورة سلاح"},
                               ).raise_for_status().json()
        items.append((im, media))

    for im, media in items:
        a = c.get(f"/media/{media['id']}/analyses").raise_for_status().json()
        if not any(x["status"] in ("queued", "running") for x in a):
            c.post(f"/media/{media['id']}/analyze", json={"thinking": True})

    print("=== REAL WEAPON analyses (in-app) ===")
    matched_total = gt_total = 0
    for idx, (im, media) in enumerate(items):
        latest = None
        for _ in range(120):
            a = c.get(f"/media/{media['id']}/analyses").raise_for_status().json()
            latest = a[0] if a else None
            if latest and latest["status"] not in ("queued", "running"):
                break
            time.sleep(3)
        dets = c.get(f"/runs/{latest['id']}/detections?media_id={media['id']}"
                     ).raise_for_status().json() if latest else []
        gt_boxes = [[v/1000 for v in g["rel1000"]] for g in im["gt"]]
        weap = [d for d in dets if d["category"] == "weapons"]
        used, best_ious = set(), []
        for d in weap:
            best, bi = 0.0, -1
            for i, g in enumerate(gt_boxes):
                if i in used:
                    continue
                v = iou(d["bbox"], g)
                if v > best:
                    best, bi = v, i
            if bi >= 0 and best >= 0.5:
                used.add(bi); best_ious.append(best)
        matched_total += len(used); gt_total += len(gt_boxes)
        cls = im["gt"][0]["cls"]
        print(f"  {im['file']} [{cls}] GT={len(gt_boxes)} weapon-dets={len(weap)} "
              f"matched={len(used)} "
              f"IoU={'/'.join(f'{x:.2f}' for x in best_ious) or '-'}")
        for d in dets[:5]:
            print(f"      - {d['name_ar']} [{d['category']}] conf={d['confidence']}")

        # render proof for the first 3
        if idx < 3:
            img = Image.open(io.BytesIO(
                c.get(f"/files/original/{media['id']}").content)).convert("RGB")
            sc = 700/max(img.size)
            img = img.resize((round(img.width*sc), round(img.height*sc)))
            W, H = img.size
            d = ImageDraw.Draw(img)
            for g in gt_boxes:
                d.rectangle((g[0]*W, g[1]*H, g[2]*W, g[3]*H), outline="#1f8a65", width=4)
            for det in weap:
                b = det["bbox"]
                d.rectangle((b[0]*W, b[1]*H, b[2]*W, b[3]*H), outline="#cf2d56", width=2)
            img.save(OUTDIR / f"proof_{idx}_{cls}.jpg", "JPEG", quality=88)

    print(f"\n=== in-app: matched {matched_total}/{gt_total} real weapon boxes "
          f"(green=truth, red=AI in /app/eval/realdata/proof) ===")
    print("open app → case REAL-WEAPONS-01")


if __name__ == "__main__":
    main()
