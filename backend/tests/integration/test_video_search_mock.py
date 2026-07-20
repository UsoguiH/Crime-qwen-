"""Video search end-to-end in mock mode: upload a generated video → index is
auto-built (mock embedder) → Arabic search → verify (fixture-confirmed) →
clips with thumbs + honest coverage + audit trail. Needs ffmpeg (in-container)."""
import asyncio
import io
import shutil
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                reason="ffmpeg required")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))


@pytest.fixture(scope="module")
def knife_video(tmp_path_factory) -> bytes:
    from make_samples import KNIFE_A, KNIFE_B, _video
    path = tmp_path_factory.mktemp("vid") / "kitchen_knife_move.mp4"
    _video(path, "2026-07-19T10:00:00Z", KNIFE_A, KNIFE_B)
    return path.read_bytes()


async def _poll(fn, accept, timeout_s=90):
    for _ in range(timeout_s * 2):
        state = await fn()
        if state in accept:
            return state
        await asyncio.sleep(0.5)
    raise TimeoutError(f"stuck at {state}")


async def test_video_search_flow(client, logged_in, knife_video):
    resp = await client.post("/cases", json={
        "case_number": "T-VS-1", "title_ar": "قضية بحث الفيديو",
        "incident_date_gregorian": "2026-07-20"})
    assert resp.status_code == 201, resp.text
    case = resp.json()

    resp = await client.post(
        f"/cases/{case['id']}/media",
        files={"file": ("kitchen_knife_move.mp4", io.BytesIO(knife_video),
                        "video/mp4")},
        data={"source_type": "cctv", "source_label_ar": "كاميرا المطبخ"})
    assert resp.status_code == 201, resp.text
    media = resp.json()

    # index auto-queued on upload → becomes ready with vectors
    async def index_status():
        return (await client.get(f"/media/{media['id']}/video-index")).json()["status"]
    assert await _poll(index_status, {"ready", "failed"}) == "ready"
    index = (await client.get(f"/media/{media['id']}/video-index")).json()
    assert index["frames_indexed"] >= 1
    assert index["embedder_name"] == "mock-embedder"
    assert index["dim"] == 64

    # re-request is idempotent (no rebuild of a ready index)
    resp = await client.post(f"/media/{media['id']}/video-index")
    assert resp.status_code == 201
    assert resp.json()["status"] == "ready"

    # search: mock translate marks sensitive → double verify; fixture confirms
    resp = await client.post(f"/cases/{case['id']}/video-search",
                             json={"query_ar": "أين يظهر السكين في التسجيل؟"})
    assert resp.status_code == 201, resp.text
    search_id = resp.json()["id"]

    async def search_status():
        return (await client.get(f"/video-searches/{search_id}")).json()["status"]
    assert await _poll(search_status, {"done", "failed"}) == "done"

    search = (await client.get(f"/video-searches/{search_id}")).json()
    assert search["sensitive"] is True
    results = search["results"]
    assert results["stats"]["candidates"] >= 1
    assert len(results["clips"]) >= 1

    clip = results["clips"][0]
    assert clip["status"] == "confirmed"          # both mock verifies match
    assert clip["confidence"] == 1.0              # 0.9 + self-consistency bonus
    assert clip["media_file_id"] == media["id"]
    assert clip["ts_in"] < clip["ts_out"]
    assert clip["label_ar"]
    assert clip["frames_matched"] >= 1            # one or more frames clustered
    # sensitive query ⇒ two verify calls per frame; ≥1 frame in the clip
    assert len(clip["model_call_ids"]) >= 2
    b = clip["bbox"]
    assert b and len(b) == 4 and all(0 <= v <= 1 for v in b)

    # honest coverage statement + thumb served from the derived jail
    assert "فُحص" in results["coverage"]["statement_ar"]
    assert results["coverage"]["media_searched"] == 1
    assert clip["thumb_path"].startswith("derived/videosearch/")
    resp = await client.get(f"/files/data/{clip['thumb_path']}")
    assert resp.status_code == 200

    # history + audit chain
    listing = (await client.get(f"/cases/{case['id']}/video-searches")).json()
    assert [s["id"] for s in listing] == [search_id]
    audit_rows = (await client.get("/audit", params={"limit": 50})).json()
    actions = [r["action"] for r in audit_rows]
    assert "video.search" in actions and "video.search.done" in actions


async def test_search_requires_video(client, logged_in):
    resp = await client.post("/cases", json={
        "case_number": "T-VS-2", "title_ar": "قضية بلا فيديو"})
    case = resp.json()
    resp = await client.post(f"/cases/{case['id']}/video-search",
                             json={"query_ar": "أي شيء"})
    assert resp.status_code == 400
