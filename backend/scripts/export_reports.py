"""Requests fresh PDF/DOCX/bundle exports for the demo run and waits for them.

Usage: python scripts/export_reports.py [run_id]
"""
import sys
import time

import httpx

BASE = "http://localhost:8000/api"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=60)
    users = c.get("/auth/users").raise_for_status().json()
    inv = next(u for u in users if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]}).raise_for_status()

    run_id = sys.argv[1] if len(sys.argv) > 1 else None
    if run_id is None:
        cases = c.get("/cases").raise_for_status().json()
        case = next(x for x in cases if x["case_number"] == "DEMO-0001")
        run_id = c.get(f"/cases/{case['id']}/runs").raise_for_status().json()[0]["id"]

    before = {(r["kind"], r["version"]) for r in
              c.get(f"/runs/{run_id}/reports").raise_for_status().json()}
    c.post(f"/runs/{run_id}/reports",
           json={"kinds": ["pdf", "docx", "bundle"]}).raise_for_status()
    for _ in range(180):
        reports = c.get(f"/runs/{run_id}/reports").raise_for_status().json()
        fresh = [r for r in reports if (r["kind"], r["version"]) not in before]
        if {"pdf_a", "docx", "bundle_zip"} <= {r["kind"] for r in fresh}:
            for r in sorted(fresh, key=lambda x: x["kind"]):
                print(f"{r['kind']} v{r['version']} variant={r.get('pdf_variant')} "
                      f"size={r['size_bytes']} sha={r['file_sha256'][:16]}…")
            print("run_id:", run_id)
            return
        time.sleep(1)
    raise SystemExit("timed out waiting for exports")


if __name__ == "__main__":
    main()
