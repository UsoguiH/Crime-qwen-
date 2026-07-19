"""Runs the new in-app photo mode on the user's uploaded crime-scene screenshot."""
import os
import time

import httpx

BASE = os.environ.get("ATHAR_API", "http://localhost:8000/api")


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=120)
    users = c.get("/auth/users").raise_for_status().json()
    inv = next(u for u in users if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]}).raise_for_status()

    cases = c.get("/cases").raise_for_status().json()
    case = next(x for x in cases if x["case_number"] == "1212")
    media = c.get(f"/cases/{case['id']}/media").raise_for_status().json()
    target = next(m for m in media if m["kind"] == "image")
    print(f"target: {target['original_filename']} ({target['width']}x{target['height']})")

    analyses = c.get(f"/media/{target['id']}/analyses").raise_for_status().json()
    if not any(a["status"] in ("queued", "running") for a in analyses):
        c.post(f"/media/{target['id']}/analyze",
               json={"thinking": True}).raise_for_status()
        print("photo analysis started (thinking ON)")

    for _ in range(120):
        analyses = c.get(f"/media/{target['id']}/analyses").raise_for_status().json()
        latest = analyses[0]
        if latest["status"] not in ("queued", "running"):
            break
        time.sleep(3)
    print(f"status: {latest['status']}  detections: {latest['detections_count']}")
    dets = c.get(f"/runs/{latest['id']}/detections?media_id={target['id']}"
                 ).raise_for_status().json()
    for d in dets:
        flag = " [NEEDS HUMAN REVIEW]" if d["needs_human_review"] else ""
        print(f"  - {d['name_ar']} [{d['category']}] conf={d['confidence']}{flag}")
    print(f"open in app: /cases/{case['id']}/photos/{target['id']}")


if __name__ == "__main__":
    main()
