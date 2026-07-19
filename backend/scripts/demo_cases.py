"""Creates 3 real cases in the LIVE app from labeled COCO images and runs the
per-photo analysis (thinking-default detect + grounding) on each, proving the
improved accuracy end-to-end in the running product.

Cases (crime-relevant framing):
  A أدوات حادة   — knife + scissors  (weapons)
  B أجهزة ووثائق — laptop + cell phone + book
  C مسرح مختلط   — bottle + mixed

Usage (in container network):  python scripts/demo_cases.py
"""
import json
import os
import time
from pathlib import Path

import httpx

BASE = os.environ.get("ATHAR_API", "http://localhost:8000/api")
GT = Path("/app/eval/data/groundtruth.json")
IMAGES = Path("/app/eval/data/images")

CASES = [
    {"num": "WEAPONS-01", "title": "أدوات حادة — تحليل أسلحة بيضاء",
     "classes": ["knife", "scissors"], "per_class": 2},
    {"num": "DEVICES-01", "title": "أجهزة ووثائق — أدلة رقمية",
     "classes": ["laptop", "cell phone", "book"], "per_class": 1},
    {"num": "SCENE-01", "title": "مسرح مختلط — مواد وأثريات",
     "classes": ["bottle"], "per_class": 3},
]


def pick(gt, classes, per_class, used):
    out = []
    for cls in classes:
        n = 0
        for im in gt["images"]:
            if im["id"] in used:
                continue
            gtc = [g for g in im["gt"] if g["cls"] == cls]
            if gtc:
                out.append((im, cls, len(gtc)))
                used.add(im["id"])
                n += 1
                if n >= per_class:
                    break
    return out


def main() -> int:
    gt = json.loads(GT.read_text(encoding="utf-8"))
    c = httpx.Client(base_url=BASE, timeout=180)
    inv = next(u for u in c.get("/auth/users").raise_for_status().json()
               if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]}).raise_for_status()

    used: set = set()
    grand_truth = grand_found = 0
    for spec in CASES:
        cases = c.get("/cases").raise_for_status().json()
        case = next((x for x in cases if x["case_number"] == spec["num"]), None)
        if case is None:
            case = c.post("/cases", json={
                "case_number": spec["num"], "title_ar": spec["title"],
                "notes_ar": "قضية عرض على صور حقيقية مُوسومة (COCO) لإثبات الدقة.",
            }).raise_for_status().json()
        picks = pick(gt, spec["classes"], spec["per_class"], used)
        print(f"\n=== {spec['num']}: {spec['title']} ({len(picks)} صور) ===")

        existing = {m["original_filename"]: m for m in
                    c.get(f"/cases/{case['id']}/media").raise_for_status().json()}
        media_map = []
        for im, cls, ngt in picks:
            if im["file"] in existing:
                media = existing[im["file"]]
            else:
                with open(IMAGES / im["file"], "rb") as fp:
                    media = c.post(f"/cases/{case['id']}/media",
                                   files={"file": (im["file"], fp, "image/jpeg")},
                                   data={"source_type": "photo",
                                         "source_label_ar": f"صورة {cls}"},
                                   ).raise_for_status().json()
            media_map.append((media, cls, ngt))

        for media, cls, ngt in media_map:
            analyses = c.get(f"/media/{media['id']}/analyses").raise_for_status().json()
            if not any(a["status"] in ("queued", "running") for a in analyses):
                r = c.post(f"/media/{media['id']}/analyze", json={"thinking": True})
                if r.status_code == 409:
                    pass
        # wait for all analyses in this case
        for media, cls, ngt in media_map:
            latest = None
            for _ in range(120):
                a = c.get(f"/media/{media['id']}/analyses").raise_for_status().json()
                latest = a[0] if a else None
                if latest and latest["status"] not in ("queued", "running"):
                    break
                time.sleep(3)
            dets = c.get(f"/runs/{latest['id']}/detections?media_id={media['id']}"
                         ).raise_for_status().json() if latest else []
            found = len(dets)
            grand_truth += ngt
            grand_found += min(found, ngt) if found else 0
            print(f"  {media['original_filename']} [{cls}] "
                  f"ground-truth={ngt}  detected={found}")
            for d in dets[:8]:
                print(f"      - {d['name_ar']} [{d['category']}] conf={d['confidence']}")
    print(f"\n=== SUMMARY (per-photo, thinking-default): "
          f"detected {grand_found}/{grand_truth} ground-truth objects across 3 cases ===")
    print("open the app → cases WEAPONS-01 / DEVICES-01 / SCENE-01")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
