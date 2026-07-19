"""WeasyPrint PDF/A rendering with graceful variant fallback.

Target pdf/a-3u; if generation under that variant fails (WeasyPrint #2841
territory), fall back to pdf/a-3b, then to a plain PDF — the report must never
fail to export. The variant actually used is recorded on the report row.
"""
import logging
from pathlib import Path

log = logging.getLogger("athar.pdf")


def render_pdf(html: str, dst: Path, base_url: str, preferred_variant: str) -> str:
    from weasyprint import HTML

    dst.parent.mkdir(parents=True, exist_ok=True)
    variants = [preferred_variant]
    if preferred_variant != "pdf/a-3b":
        variants.append("pdf/a-3b")
    variants.append(None)  # plain PDF as last resort

    last_error: Exception | None = None
    for variant in variants:
        try:
            doc = HTML(string=html, base_url=base_url)
            if variant:
                doc.write_pdf(str(dst), pdf_variant=variant)
            else:
                doc.write_pdf(str(dst))
            return variant or "pdf"
        except Exception as exc:  # try the next variant
            last_error = exc
            log.warning("PDF render with variant %s failed: %s", variant, exc)
    raise RuntimeError(f"PDF rendering failed for all variants: {last_error}")
