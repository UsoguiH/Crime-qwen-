"""Stage 0 — chain-of-custody gate: re-hash every original before analysis."""
import asyncio

from sqlalchemy import update

from app.db.models import AnalysisRun
from app.pipeline.ctx import Ctx
from app.services.hashing import sha256_file


class IntegrityError(Exception):
    pass


async def run(ctx: Ctx) -> None:
    media = await ctx.selected_media()
    await ctx.set_step(0, total=len(media), current=0)
    results = {}
    mismatched = []
    for i, m in enumerate(media, start=1):
        path = ctx.abs_path(m.stored_path)
        if not path.exists():
            results[m.id] = {"ok": False, "reason": "missing"}
            mismatched.append(m.original_filename)
        else:
            digest = await asyncio.to_thread(sha256_file, path)
            ok = digest == m.content_sha256
            results[m.id] = {"ok": ok, "sha256": digest}
            if not ok:
                mismatched.append(m.original_filename)
        await ctx.set_step(0, current=i)

    async with ctx.factory() as session:
        await session.execute(
            update(AnalysisRun).where(AnalysisRun.id == ctx.run_id)
            .values(integrity_check_json={"results": results,
                                          "mismatched": mismatched}))
        await session.commit()

    if mismatched:
        raise IntegrityError(
            "فشل التحقق من سلامة الملفات الأصلية: " + "، ".join(mismatched))
