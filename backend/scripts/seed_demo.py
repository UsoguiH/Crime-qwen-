"""Seeds a demo case through the real API (server must be running).

Usage (inside the backend container):  python scripts/seed_demo.py
"""
import sys
import time
from pathlib import Path

import httpx

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
from make_samples import ensure_samples  # noqa: E402

BASE = "http://localhost:8000/api"

SOURCES = {
    "kitchen_knife_table.jpg": ("photo", "صورة ميدانية — المطبخ"),
    "kitchen_knife_move.mp4": ("cctv", "كاميرا المطبخ العلوية"),
    "desk_documents.jpg": ("photo", "صورة ميدانية — المكتب"),
    "juice_spill.jpg": ("photo", "صورة ميدانية — الممر"),
    "shoeprint_sand.jpg": ("photo", "صورة ميدانية — الفناء الخارجي"),
    "broken_glass.jpg": ("photo", "صورة ميدانية — الصالة"),
    "markers_ruler.jpg": ("photo", "صورة توثيق العلامات"),
}


def main() -> None:
    samples = ensure_samples()
    client = httpx.Client(base_url=BASE, timeout=120)

    users = client.get("/auth/users").raise_for_status().json()
    investigator = next(u for u in users if u["role"] == "investigator")
    client.post("/auth/login", json={"user_id": investigator["id"]}).raise_for_status()

    cases = client.get("/cases").raise_for_status().json()
    case = next((c for c in cases if c["case_number"] == "DEMO-0001"), None)
    if case is None:
        case = client.post("/cases", json={
            "case_number": "DEMO-0001",
            "title_ar": "القضية التجريبية — عرض قدرات النظام",
            "location_ar": "موقع افتراضي — عينات مُعدّة",
            "investigator_name_ar": investigator["display_name_ar"],
            "notes_ar": "قضية توضيحية على عينات مصطنعة بريئة؛ لا تمثل واقعة حقيقية.",
            "incident_date_gregorian": "2026-07-19",
        }).raise_for_status().json()
        print(f"case created: {case['id']}")

    existing = {m["original_filename"] for m in
                client.get(f"/cases/{case['id']}/media").raise_for_status().json()}
    for name, (source_type, label) in SOURCES.items():
        path = samples / name
        if not path.exists() or name in existing:
            continue
        with open(path, "rb") as fp:
            resp = client.post(
                f"/cases/{case['id']}/media",
                files={"file": (name, fp)},
                data={"source_type": source_type, "source_label_ar": label})
        resp.raise_for_status()
        print(f"uploaded {name}: sha256={resp.json()['content_sha256'][:16]}…")

    run = client.post(f"/cases/{case['id']}/runs",
                      json={"thinking_policy": "auto"}).raise_for_status().json()
    print(f"analysis started: run {run['id']}")

    for _ in range(240):
        status = client.get(f"/runs/{run['id']}").raise_for_status().json()["status"]
        if status in ("completed", "completed_with_errors", "failed", "paused"):
            print(f"run finished: {status}")
            break
        time.sleep(1)
    reports = client.get(f"/runs/{run['id']}/reports").raise_for_status().json()
    for r in reports:
        print(f"report {r['kind']} v{r['version']} sha256={r['file_sha256'][:16]}…")
    print("demo ready → http://localhost:8090")


if __name__ == "__main__":
    main()
