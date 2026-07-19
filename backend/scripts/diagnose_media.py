"""Why did the app 'do nothing' with an uploaded image? Pulls the facts:
upload → runs after it → triage verdict → detections → model calls, then
re-asks the live model about the exact stored original to capture its own
stated reasoning.

Usage: python scripts/diagnose_media.py [filename-fragment]
"""
import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine as db_engine  # noqa: E402
from app.db.models import (AnalysisRun, Base, Case, Detection, Frame,  # noqa: E402
                           MediaFile, ModelCall, RunStep, TriageResult)
from app.modelclient.client import FrameImage, VLMClient  # noqa: E402
from app.schemas.model_io import DetectionResult  # noqa: E402
from app.services.storage import safe_resolve  # noqa: E402


async def main() -> None:
    frag = sys.argv[1] if len(sys.argv) > 1 else ""
    settings = get_settings()
    engine = db_engine.init_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = db_engine.session_factory()

    async with factory() as s:
        stmt = select(MediaFile).where(MediaFile.kind == "image")
        if frag:
            stmt = stmt.where(MediaFile.original_filename.like(f"%{frag}%"))
        media = (await s.execute(
            stmt.order_by(MediaFile.uploaded_at.desc()).limit(5))).scalars().all()
        if not media:
            print("no image uploads found")
            return
        print("=== أحدث الصور المرفوعة ===")
        for m in media:
            print(f"- {m.original_filename}  uploaded={m.uploaded_at:%H:%M:%S}  "
                  f"case={m.case_id[:8]}  {m.width}x{m.height}  "
                  f"sha={m.content_sha256[:12]}")
        target = media[0]
        print(f"\n=== تشخيص: {target.original_filename} ===")

        case = (await s.execute(
            select(Case).where(Case.id == target.case_id))).scalar_one()
        runs = (await s.execute(
            select(AnalysisRun).where(AnalysisRun.case_id == case.id)
            .order_by(AnalysisRun.started_at.desc()))).scalars().all()
        print(f"case: {case.case_number} status={case.status}")
        runs_after = [r for r in runs if r.started_at >= target.uploaded_at]
        print(f"runs total={len(runs)}; runs STARTED AFTER this upload="
              f"{len(runs_after)}")
        for r in runs[:3]:
            when = "AFTER upload" if r.started_at >= target.uploaded_at else "BEFORE upload"
            print(f"  run#{r.run_number} {r.status} started={r.started_at:%H:%M:%S} ({when})")

        frames = (await s.execute(
            select(Frame).where(Frame.media_file_id == target.id))).scalars().all()
        print(f"frames extracted for this image: {len(frames)}")
        for f in frames:
            triage = (await s.execute(
                select(TriageResult).where(TriageResult.frame_id == f.id))
            ).scalars().all()
            dets = (await s.execute(
                select(Detection).where(Detection.frame_id == f.id))).scalars().all()
            for t in triage:
                print(f"  triage(run {t.run_id[:8]}): relevance={t.relevance} "
                      f"evidence={t.contains_evidence} complexity={t.complexity} "
                      f"human={t.human_presence_suspected} selected={t.selected_for_detection}")
            print(f"  detections stored: {len(dets)}")
            for d in dets[:10]:
                print(f"    - {d.name_ar} [{d.category}] conf={d.confidence}")
            calls = (await s.execute(
                select(ModelCall).where(ModelCall.frame_id == f.id))).scalars().all()
            for c in calls:
                print(f"  model_call: {c.purpose} status={c.status} thinking={c.thinking} "
                      f"in={c.input_tokens} out={c.output_tokens} err={c.error}")

    # live probe: what does the model say about THIS image right now?
    if settings.model_mode == "api":
        print("\n=== إعادة سؤال النموذج الآن عن الصورة نفسها (فحص مباشر) ===")
        vlm = VLMClient(settings, factory)
        path = safe_resolve(settings, target.stored_path)
        result = await vlm.complete_json(
            prompt_files=("20_detect.md", "21_detect_human_addendum.md"),
            schema=DetectionResult, purpose="detect", thinking=True,
            images=[FrameImage(data=path.read_bytes(), ref="diagnose",
                               mime=target.mime)],
            context={"frame_ref": "diagnose", "media_label": "صورة مرفوعة",
                     "timestamp_s": None, "case_notes": case.notes_ar[:300]},
            max_output_tokens=6000)
        v = result.value
        print(f"detections now: {len(v.detections)}")
        for d in v.detections:
            print(f"  - {d.name_ar} [{d.category}] conf={d.confidence} bbox={d.bbox_2d}")
            if d.uncertainty_notes_ar:
                print(f"    uncertainty: {d.uncertainty_notes_ar}")
        print(f"scene_summary: {v.scene_summary_ar}")
        print(f"usage: {result.usage}")


if __name__ == "__main__":
    asyncio.run(main())
