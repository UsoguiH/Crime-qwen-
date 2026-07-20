"""Measure video search on real footage: index time, query latency, recall.

Usage (app running, MODEL_MODE=api for real verification):
  python scripts/video_search_eval.py --video path/to/cctv.mp4 \
      --queries queries.json [--case-number VS-EVAL-1] [--api http://localhost:8000/api]

queries.json format — expected_ts lists the ground-truth event times (seconds)
you hand-labelled in the footage; omit it to measure latency only:
  [
    {"query_ar": "شخص يحمل سكيناً", "expected_ts": [125.0, 1440.5]},
    {"query_ar": "حقيبة متروكة"}
  ]

A hit = any returned clip [ts_in - tol, ts_out + tol] covering an expected ts.
Output is English-only (console safety); queries themselves stay Arabic.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

TOL_S = 5.0
POLL_S = 2.0


def wait(fn, accept, timeout_s, label):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        state = fn()
        if state in accept:
            return state, time.time() - t0
        time.sleep(POLL_S)
    print(f"TIMEOUT waiting for {label} (last state: {state})")
    sys.exit(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--api", default="http://localhost:8000/api")
    ap.add_argument("--case-number", default=f"VS-EVAL-{int(time.time())}")
    ap.add_argument("--index-timeout", type=int, default=3600)
    ap.add_argument("--query-timeout", type=int, default=600)
    args = ap.parse_args()

    video = Path(args.video)
    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    c = httpx.Client(base_url=args.api, timeout=120)

    inv = next(u for u in c.get("/auth/users").json()
               if u["role"] == "investigator")
    c.post("/auth/login", json={"user_id": inv["id"]})

    case = c.post("/cases", json={"case_number": args.case_number,
                                  "title_ar": "تقييم البحث في الفيديو"}).json()
    print(f"case {case['case_number']} ({case['id']})")

    print(f"uploading {video.name} ({video.stat().st_size / 1e6:.1f} MB)...")
    t0 = time.time()
    with open(video, "rb") as fp:
        media = c.post(f"/cases/{case['id']}/media",
                       files={"file": (video.name, fp, "video/mp4")},
                       data={"source_type": "cctv"}).json()
    print(f"  upload: {time.time() - t0:.1f}s  duration={media.get('duration_s')}s")

    state, dt = wait(
        lambda: c.get(f"/media/{media['id']}/video-index").json()["status"],
        {"ready", "failed"}, args.index_timeout, "index")
    idx = c.get(f"/media/{media['id']}/video-index").json()
    if state != "ready":
        print(f"INDEX FAILED: {idx.get('error')}")
        sys.exit(1)
    print(f"  index: {dt:.1f}s  frames {idx['frames_indexed']}/{idx['frames_seen']} "
          f"kept  embedder={idx['embedder_name']}")

    total_expected = total_hit = 0
    for q in queries:
        sid = c.post(f"/cases/{case['id']}/video-search",
                     json={"query_ar": q["query_ar"]}).json()["id"]
        state, dt = wait(
            lambda: c.get(f"/video-searches/{sid}").json()["status"],
            {"done", "failed"}, args.query_timeout, "search")
        s = c.get(f"/video-searches/{sid}").json()
        if state != "done":
            print(f"SEARCH FAILED: {s.get('error')}")
            continue
        r = s["results"]
        st = r["stats"]
        print(f"\nquery: {q['query_ar']!r}")
        print(f"  wall {dt:.1f}s (translate {st.get('translate_ms', 0)}ms, "
              f"retrieve {st.get('retrieve_ms', 0)}ms, verify {st.get('verify_ms', 0)}ms)"
              f"  sensitive={s['sensitive']}")
        print(f"  candidates {st['candidates']} -> confirmed {st['confirmed']}, "
              f"uncertain {st['uncertain']}, rejected {st['rejected']}")
        for clip in r["clips"]:
            print(f"    [{clip['status']:9}] {clip['ts_in']:8.1f}-{clip['ts_out']:8.1f}s "
                  f"conf={clip['confidence']:.2f} score={clip['retrieval_score']:.3f}")
        expected = q.get("expected_ts") or []
        if expected:
            spans = [(cl["ts_in"] - TOL_S, cl["ts_out"] + TOL_S) for cl in r["clips"]]
            hits = [ts for ts in expected
                    if any(a <= ts <= b for a, b in spans)]
            missed = [ts for ts in expected if ts not in hits]
            total_expected += len(expected)
            total_hit += len(hits)
            print(f"  recall {len(hits)}/{len(expected)}"
                  + (f"  MISSED at {missed}" if missed else ""))

    if total_expected:
        print(f"\nTOTAL RECALL: {total_hit}/{total_expected} "
              f"({total_hit / total_expected:.0%}) at ±{TOL_S}s tolerance")


if __name__ == "__main__":
    main()
