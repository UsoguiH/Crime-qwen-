"""Full in-process journey in mock mode: login → case → upload → analyze →
timeline → review → PDF report → audit chain. Requires WeasyPrint system deps
(runs inside the Docker image; skipped where Pango is unavailable)."""
import asyncio
import io
import sys
from pathlib import Path

import pytest

pytest.importorskip("weasyprint")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from make_samples import kitchen_knife_table  # noqa: E402


@pytest.fixture(scope="session")
def knife_jpg(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("media") / "kitchen_knife_table.jpg"
    kitchen_knife_table(path)
    return path.read_bytes()


async def _wait_run(client, run_id, timeout_s=120):
    for _ in range(timeout_s * 2):
        run = (await client.get(f"/runs/{run_id}")).json()
        if run["status"] in ("completed", "completed_with_errors", "failed",
                             "paused", "cancelled"):
            return run
        await asyncio.sleep(0.5)
    raise TimeoutError(f"run stuck: {run['status']}")


async def test_full_pipeline(client, logged_in, knife_jpg, settings):
    resp = await client.post("/cases", json={
        "case_number": "T-100", "title_ar": "قضية اختبار متكاملة",
        "location_ar": "مختبر الاختبارات",
        "incident_date_gregorian": "2026-07-19"})
    assert resp.status_code == 201, resp.text
    case = resp.json()
    assert case["incident_date_hijri"]  # dual date computed

    resp = await client.post(
        f"/cases/{case['id']}/media",
        files={"file": ("kitchen_knife_table.jpg", io.BytesIO(knife_jpg), "image/jpeg")},
        data={"source_type": "photo", "source_label_ar": "صورة المطبخ"})
    assert resp.status_code == 201, resp.text
    media = resp.json()
    assert len(media["content_sha256"]) == 64

    # duplicate upload dedupes
    resp = await client.post(
        f"/cases/{case['id']}/media",
        files={"file": ("kitchen_knife_table.jpg", io.BytesIO(knife_jpg), "image/jpeg")})
    assert resp.json().get("duplicate") is True

    resp = await client.post(f"/cases/{case['id']}/runs",
                             json={"thinking_policy": "auto"})
    assert resp.status_code == 201, resp.text
    run = await _wait_run(client, resp.json()["id"])
    assert run["status"] == "completed", run

    entities = (await client.get(f"/runs/{run['id']}/entities")).json()
    assert len(entities) == 1
    knife = entities[0]
    assert knife["category"] == "weapons"
    assert knife["label_ar"] == "دليل ٠٠١"
    assert knife["has_crop"] is True

    timeline = (await client.get(f"/runs/{run['id']}/timeline")).json()
    assert any(ev["event_type"] == "first_seen" for ev in timeline)

    annotated = settings.data_dir / f"derived/annotated/{run['id']}/frames"
    assert any(annotated.glob("*.jpg"))

    reports = (await client.get(f"/runs/{run['id']}/reports")).json()
    assert any(r["kind"] == "pdf_a" for r in reports)
    pdf = next(r for r in reports if r["kind"] == "pdf_a")
    assert (settings.data_dir / f"reports/{run['id']}/report.pdf").exists()
    assert pdf["audit_head_hash"]

    dl = await client.get(f"/reports/{next(r['id'] for r in reports if r['kind']=='pdf_a')}/download")
    assert dl.status_code == 200
    assert dl.content[:5] == b"%PDF-"

    verify = (await client.get("/audit/verify")).json()
    assert verify["valid"] is True and verify["length"] >= 5


async def test_review_flow_and_roles(client, logged_in):
    cases = (await client.get("/cases")).json()
    case = next(c for c in cases if c["case_number"] == "T-100")
    runs = (await client.get(f"/cases/{case['id']}/runs")).json()
    run_id = runs[0]["id"]

    # investigator cannot review
    entities = (await client.get(f"/runs/{run_id}/entities")).json()
    entity_id = entities[0]["id"]
    resp = await client.post(f"/entities/{entity_id}/review",
                             json={"action": "confirm"})
    assert resp.status_code == 403

    # switch to reviewer
    await client.post("/auth/login", json={"user_id": logged_in["reviewer"]["id"]})
    resp = await client.post(f"/entities/{entity_id}/review",
                             json={"action": "confirm", "note_ar": "مطابق للصورة"})
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "confirmed"

    # docx + bundle need investigator role → switch back and request
    await client.post("/auth/login", json={"user_id": logged_in["investigator"]["id"]})
    resp = await client.post(f"/runs/{run_id}/reports",
                             json={"kinds": ["docx", "bundle"]})
    assert resp.status_code == 202
    for _ in range(120):
        reports = (await client.get(f"/runs/{run_id}/reports")).json()
        kinds = {r["kind"] for r in reports}
        if {"docx", "bundle_zip"} <= kinds:
            break
        await asyncio.sleep(0.5)
    assert {"docx", "bundle_zip"} <= {r["kind"] for r in reports}


async def test_report_preview_and_arabic(client, logged_in):
    cases = (await client.get("/cases")).json()
    case = next(c for c in cases if c["case_number"] == "T-100")
    runs = (await client.get(f"/cases/{case['id']}/runs")).json()
    preview = await client.get(f"/runs/{runs[0]['id']}/report-preview")
    assert preview.status_code == 200
    html = preview.text
    assert 'dir="rtl"' in html
    assert "تقرير تحليلي لمسرح الجريمة" in html
    assert "سري" in html
    assert "دليل ٠٠١" in html


async def test_photo_mode(client, logged_in, knife_jpg):
    resp = await client.post("/cases", json={
        "case_number": "T-200", "title_ar": "قضية اختبار التحليل الفردي"})
    assert resp.status_code == 201, resp.text
    case = resp.json()

    resp = await client.post(
        f"/cases/{case['id']}/media",
        files={"file": ("kitchen_knife_table.jpg", io.BytesIO(knife_jpg), "image/jpeg")})
    media = resp.json()

    resp = await client.post(f"/media/{media['id']}/analyze", json={"thinking": True})
    assert resp.status_code == 201, resp.text
    run = await _wait_run(client, resp.json()["id"])
    assert run["status"] == "completed", run
    assert {s["stage"] for s in run["steps"]} == {0, 1, 3}  # detect-only path

    analyses = (await client.get(f"/media/{media['id']}/analyses")).json()
    assert len(analyses) == 1 and analyses[0]["detections_count"] == 1

    dets = (await client.get(
        f"/runs/{run['id']}/detections?media_id={media['id']}")).json()
    assert dets[0]["category"] == "weapons"

    # photo mode produces NO entities/report and never flips case status
    assert (await client.get(f"/runs/{run['id']}/entities")).json() == []
    assert (await client.get(f"/runs/{run['id']}/reports")).json() == []
    assert (await client.get(f"/cases/{case['id']}")).json()["status"] == "new"
    # and it is hidden from the case's full-run list
    assert (await client.get(f"/cases/{case['id']}/runs")).json() == []

    # a second photo analysis creates its own independent run
    resp = await client.post(f"/media/{media['id']}/analyze", json={"thinking": False})
    run2 = await _wait_run(client, resp.json()["id"])
    assert run2["status"] == "completed"
    analyses = (await client.get(f"/media/{media['id']}/analyses")).json()
    assert len(analyses) == 2

    # ask-a-question endpoint (mock answers honestly that it cannot determine)
    resp = await client.post(f"/media/{media['id']}/ask",
                             json={"question_ar": "كم عدد السكاكين؟"})
    assert resp.status_code == 201, resp.text
    answer = resp.json()
    assert answer["cannot_determine"] is True
    history = (await client.get(f"/media/{media['id']}/questions")).json()
    assert len(history) == 1 and history[0]["question_ar"] == "كم عدد السكاكين؟"


async def test_unauthenticated_blocked(app):
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test/api") as anon:
        assert (await anon.get("/cases")).status_code == 401
        assert (await anon.get("/audit/verify")).status_code == 401
