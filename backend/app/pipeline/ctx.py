"""Shared context handed to every pipeline stage."""
import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.core import utcnow
from app.db.models import AnalysisRun, Frame, MediaFile, RunStep
from app.modelclient.client import VLMClient
from app.pipeline.progress import broadcaster
from app.services.storage import safe_resolve

STAGE_NAMES_AR = {
    0: "التحقق من سلامة الملفات",
    1: "استخراج الإطارات المفتاحية",
    2: "الفرز الأولي",
    3: "تحليل الإطارات",
    4: "توحيد الأدلة",
    5: "بناء الجدول الزمني",
    6: "مقارنة المصادر",
    7: "الصياغة التحليلية",
    8: "تعليم الصور",
    9: "إخراج التقرير",
}


class Ctx:
    def __init__(self, settings: Settings, factory: async_sessionmaker,
                 vlm: VLMClient, run: AnalysisRun):
        self.settings = settings
        self.factory = factory
        self.vlm = vlm
        self.run_id = run.id
        self.case_id = run.case_id
        self.thresholds: dict = run.thresholds_json or {}
        self.options: dict = run.options_json or {}

    # ── thresholds (frozen per run) ───────────────────────────────────────
    def thr(self, key: str, default):
        return self.thresholds.get(key, default)

    # ── events / steps ────────────────────────────────────────────────────
    def emit(self, event_type: str, **data) -> None:
        broadcaster.publish(self.run_id, {"type": event_type, "run_id": self.run_id, **data})

    async def set_step(self, stage: int, *, status: str | None = None,
                       current: int | None = None, total: int | None = None,
                       checkpoint: dict | None = None, error: str | None = None) -> None:
        values: dict = {}
        if status is not None:
            values["status"] = status
            if status == "running":
                values["started_at"] = utcnow()
            if status in ("completed", "completed_with_errors", "failed", "skipped"):
                values["finished_at"] = utcnow()
        if current is not None:
            values["progress_current"] = current
        if total is not None:
            values["progress_total"] = total
        if checkpoint is not None:
            values["checkpoint_json"] = checkpoint
        if error is not None:
            values["error"] = error[:2000]
        async with self.factory() as session:
            await session.execute(
                update(RunStep)
                .where(RunStep.run_id == self.run_id, RunStep.stage == stage)
                .values(**values))
            await session.commit()
        payload = {"stage": stage, "stage_name_ar": STAGE_NAMES_AR.get(stage, "")}
        payload.update({k: v for k, v in values.items()
                        if k in ("status", "progress_current", "progress_total", "error")})
        self.emit("step", **payload)

    async def get_checkpoint(self, stage: int) -> dict:
        async with self.factory() as session:
            row = (await session.execute(
                select(RunStep).where(RunStep.run_id == self.run_id,
                                      RunStep.stage == stage))).scalar_one_or_none()
            return dict(row.checkpoint_json or {}) if row else {}

    # ── media helpers ─────────────────────────────────────────────────────
    async def selected_media(self, kind: str | None = None) -> list[MediaFile]:
        wanted_ids = self.options.get("media_ids") or None
        async with self.factory() as session:
            stmt = select(MediaFile).where(MediaFile.case_id == self.case_id,
                                           MediaFile.excluded.is_(False))
            if kind:
                stmt = stmt.where(MediaFile.kind == kind)
            rows = (await session.execute(stmt.order_by(MediaFile.uploaded_at))).scalars().all()
        if wanted_ids:
            rows = [m for m in rows if m.id in wanted_ids]
        return rows

    def abs_path(self, rel: str) -> Path:
        return safe_resolve(self.settings, rel)

    def frame_jpeg(self, frame: Frame, max_px: int = 2560,
                   min_px: int = 960) -> bytes:
        """Frame bytes as JPEG inside the model's accurate regime (~480–2560px).

        Small images are UPSCALED to min_px on the long side — Qwen3-VL's
        localization degrades below ~480px and measurably wobbles on tiny
        screenshots (user's 390×400 case, 2026-07-19)."""
        path = self.abs_path(frame.stored_path)
        with Image.open(path) as im:
            img = im.convert("RGB")
        if max(img.size) > max_px:
            img.thumbnail((max_px, max_px))
        elif max(img.size) < min_px:
            scale = min_px / max(img.size)
            img = img.resize((round(img.width * scale), round(img.height * scale)),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        return buf.getvalue()

    @staticmethod
    def media_label(media: MediaFile) -> str:
        return media.source_label_ar or media.original_filename

    @staticmethod
    def media_stem(media: MediaFile) -> str:
        return Path(media.original_filename).stem
