"""Stage 9 — exports: PDF/A (always), DOCX + court ZIP bundle on demand."""
import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func, select

from app.db.models import Report, User
from app.pipeline.ctx import Ctx
from app.reporting.context import build_report_context
from app.reporting.docx import render_docx
from app.reporting.pdf import render_pdf
from app.services import audit
from app.services.bundle import build_bundle
from app.services.hashing import sha256_file

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def jinja_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)),
                       autoescape=select_autoescape(default=True, default_for_string=True))


async def render_html(settings, factory, run_id: str,
                      generated_by: str | None = None,
                      asset_base: str = "") -> str:
    context = await build_report_context(settings, factory, run_id, generated_by)
    template = jinja_env().get_template("report/report.html.j2")
    return template.render(asset_base=asset_base, **context)


async def run(ctx: Ctx) -> None:
    await ctx.set_step(9, total=1, current=0)
    await generate_exports(ctx, kinds=["pdf"], user_id=None)
    await ctx.set_step(9, current=1)


async def generate_exports(ctx: Ctx, kinds: list[str], user_id: str | None) -> list[str]:
    settings = ctx.settings
    produced: list[str] = []
    context = await build_report_context(settings, ctx.factory, ctx.run_id, user_id)
    actor_label = context["generated"]["by_label"]

    async def next_version(kind: str) -> int:
        async with ctx.factory() as session:
            v = (await session.execute(
                select(func.max(Report.version)).where(
                    Report.run_id == ctx.run_id, Report.kind == kind))).scalar_one()
            return (v or 0) + 1

    async def register(kind: str, path: Path, variant: str | None,
                       manifest: dict | None = None) -> Report:
        version = await next_version(kind)
        digest = await asyncio.to_thread(sha256_file, path)
        async with ctx.factory() as session:
            head = await audit.head(session)
        row = Report(run_id=ctx.run_id, version=version, kind=kind,
                     file_path=str(path.relative_to(settings.data_dir).as_posix()),
                     file_sha256=digest, size_bytes=path.stat().st_size,
                     audit_head_hash=head, manifest_json=manifest,
                     pdf_variant=variant, generated_by=user_id)
        async with ctx.factory() as session:
            session.add(row)
            await session.commit()
        await audit.append(
            ctx.factory, action="report.generate", actor_user_id=user_id,
            actor_label=actor_label, object_type="report", object_id=row.id,
            detail={"kind": kind, "version": version, "sha256": digest,
                    "run_id": ctx.run_id})
        ctx.emit("report", kind=kind, version=version, report_id=row.id)
        return row

    reports_dir = settings.reports_dir / ctx.run_id
    pdf_path = reports_dir / "report.pdf"
    docx_path = reports_dir / "report.docx"

    if "pdf" in kinds or ("bundle" in kinds and not pdf_path.exists()):
        html = await render_html(settings, ctx.factory, ctx.run_id, user_id)
        # trailing slash matters: WeasyPrint resolves relative asset URLs
        # against base_url with urljoin semantics
        base_url = settings.data_dir.resolve().as_posix() + "/"
        variant = await asyncio.to_thread(
            render_pdf, html, pdf_path, base_url,
            settings.report_pdf_variant)
        await register("pdf_a", pdf_path, variant)
        produced.append("pdf")

    if "docx" in kinds or ("bundle" in kinds and not docx_path.exists()):
        template_path = TEMPLATES_DIR / "docx" / "report_ar.docx"
        await asyncio.to_thread(render_docx, template_path, context, docx_path)
        await register("docx", docx_path, None)
        produced.append("docx")

    if "bundle" in kinds:
        bundle_path = reports_dir / "court_bundle.zip"
        files: list[tuple[Path, str]] = [
            (pdf_path, "report.pdf"), (docx_path, "report.docx")]
        for e in context["entities"]:
            for key, suffix in (("crop", ""), ("before", "_before"), ("after", "_after")):
                rel = e.get(key)
                if rel:
                    files.append((settings.data_dir / rel,
                                  f"evidence/{e['code']}{suffix}.jpg"))
        for m in context["media"]:
            for rel in m["annotated_frames"]:
                files.append((settings.data_dir / rel,
                              f"annotated_frames/{Path(rel).name}"))
        docs = {
            "data/entities.json": context["entities"],
            "data/timeline.json": context["events"],
            "data/media_custody.json": [
                {"label": m["label"], "filename": m["filename"],
                 "sha256": m["sha256"], "size": m["size_ar"]}
                for m in context["media"]],
            "data/run_snapshot.json": context["run"],
        }
        manifest = await asyncio.to_thread(build_bundle, bundle_path, files, docs)
        await register("bundle_zip", bundle_path, None, manifest)
        produced.append("bundle")

    return produced
