"""IN-APP real-dataset test for photo mode: uploads REAL COCO photos (and the
user's staged crime-scene image if present) through the actual API, runs an
independent per-photo analysis for each, and prints per-photo results.

Run inside the backend container while the server is up:
  python scripts/test_photo_mode.py
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = os.environ.get("ATHAR_API", "http://localhost:8000/api")
EVAL_GT = Path("/app/eval/data/groundtruth.json")
EVAL_IMAGES = Path("/app/eval/data/images")
PICK_CLASSES = ["knife", "scissors", "laptop", "cell phone", "bottle"]


def pick_real_images() -> list[tuple[str, Path]]:
    gt = json.loads(EVAL_GT.read_text(encoding="utf-8"))
    picked: list[tuple[str, Path]] = []
    used: set[int] = set()
    for cls in PICK_CLASSES:
        for im in gt["images"]:
            if im["id"] in used:
                continue
            if any(g["cls"] == cls for g in im["gt"]):
                picked.append((cls, EVAL_IMAGES / im["file"]))
                used.add(im["id"])
                break
    return picked


def main() -> int:
    if not EVAL_GT.exists():
        print("real dataset missing (eval/data) — run eval/dataset.py first")
        return 2
    c = httpx.Client(base_url=BASE, timeout=120)
    users = c.get("/auth/users").raise_for_status().json()
    inv = next(u for u in users if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]}).raise_for_status()

    cases = c.get("/cases").raise_for_status().json()
    case = next((x for x in cases if x["case_number"] == "PHOTO-REAL-01"), None)
    if case is None:
        case = c.post("/cases", json={
            "case_number": "PHOTO-REAL-01",
            "title_ar": "اختبار التحليل الفردي — صور حقيقية (COCO)",
            "notes_ar": "صور حقيقية من مجموعة اختبار معيارية لغرض التحقق الوظيفي.",
        }).raise_for_status().json()
        print(f"case created: {case['case_number']}")

    existing = {m["original_filename"]: m for m in
                c.get(f"/cases/{case['id']}/media").raise_for_status().json()}
    targets: list[dict] = []
    for cls, path in pick_real_images():
        if path.name in existing:
            media = existing[path.name]
        else:
            with open(path, "rb") as fp:
                media = c.post(f"/cases/{case['id']}/media",
                               files={"file": (path.name, fp, "image/jpeg")},
                               data={"source_type": "photo",
                                     "source_label_ar": f"REAL-{cls}"},
                               ).raise_for_status().json()
            print(f"uploaded {path.name} ({cls}) sha={media['content_sha256'][:12]}")
        targets.append({"cls": cls, "media": media})

    # per-photo independent analyses (thinking ON)
    runs = {}
    for t in targets:
        mid = t["media"]["id"]
        analyses = c.get(f"/media/{mid}/analyses").raise_for_status().json()
        active = next((a for a in analyses
                       if a["status"] in ("queued", "running")), None)
        if active:
            runs[mid] = active["id"]
            continue
        r = c.post(f"/media/{mid}/analyze", json={"thinking": True})
        if r.status_code == 409:
            runs[mid] = None
            continue
        runs[mid] = r.raise_for_status().json()["id"]
        print(f"analysis started for {t['media']['original_filename']}")

    print("waiting for per-photo analyses…")
    deadline = time.time() + 600
    results = {}
    while time.time() < deadline and len(results) < len(targets):
        for t in targets:
            mid = t["media"]["id"]
            if mid in results:
                continue
            analyses = c.get(f"/media/{mid}/analyses").raise_for_status().json()
            latest = analyses[0] if analyses else None
            if latest and latest["status"] not in ("queued", "running"):
                results[mid] = latest
        time.sleep(3)

    print("\n=== per-photo results (REAL images, in-app) ===")
    ok = 0
    for t in targets:
        mid = t["media"]["id"]
        latest = results.get(mid)
        name = t["media"]["original_filename"]
        if latest is None:
            print(f"[TIMEOUT] {name}")
            continue
        dets = c.get(f"/runs/{latest['id']}/detections?media_id={mid}"
                     ).raise_for_status().json()
        status = latest["status"]
        good = status == "completed"
        ok += good
        print(f"[{status}] {name} (expected class: {t['cls']}) "
              f"→ {len(dets)} detections")
        for d in dets[:6]:
            print(f"    - {d['name_ar']} [{d['category']}] conf={d['confidence']}")
    print(f"\n{ok}/{len(targets)} photo analyses completed successfully")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
