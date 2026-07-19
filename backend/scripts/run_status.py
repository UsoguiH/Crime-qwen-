"""Prints a run's status/steps/model-call totals (latest run if no arg).

Usage: python scripts/run_status.py [run_id]
"""
import json
import sys

import httpx

BASE = "http://localhost:8000/api"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=30)
    users = c.get("/auth/users").raise_for_status().json()
    inv = next(u for u in users if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]}).raise_for_status()

    run_id = sys.argv[1] if len(sys.argv) > 1 else None
    if run_id is None:
        cases = c.get("/cases").raise_for_status().json()
        case = next(x for x in cases if x["case_number"] == "DEMO-0001")
        runs = c.get(f"/cases/{case['id']}/runs").raise_for_status().json()
        run_id = runs[0]["id"]

    run = c.get(f"/runs/{run_id}").raise_for_status().json()
    print("run:", run_id, "status:", run["status"], "error:", run.get("error"))
    for s in run.get("steps", []):
        line = (f"  s{s['stage']} {s['stage_name_ar']}: {s['status']} "
                f"{s['progress_current']}/{s['progress_total']}")
        if s.get("error"):
            line += f"  !! {s['error'][:160]}"
        print(line)
    calls = c.get(f"/runs/{run_id}/model-calls").raise_for_status().json()
    print("model calls:", json.dumps(calls["totals"]))
    print("by purpose:", json.dumps(calls["by_purpose"], ensure_ascii=False))
    entities = c.get(f"/runs/{run_id}/entities").raise_for_status().json()
    print(f"entities: {len(entities)}")
    for e in entities:
        print(f"  {e['code']} {e['canonical_name_ar']} [{e['category']}] "
              f"conf={e['confidence_max']:.2f} review={e['review_status']}"
              f"{' NEEDS-REVIEW' if e['needs_human_review'] else ''}")
    reports = c.get(f"/runs/{run_id}/reports").raise_for_status().json()
    for r in reports:
        print(f"report: {r['kind']} v{r['version']} variant={r.get('pdf_variant')} "
              f"sha={r['file_sha256'][:16]}…")


if __name__ == "__main__":
    main()
