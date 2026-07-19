# أثر / Athar — Crime Scene AI Analysis System

> **"Every contact leaves a trace" — Locard's exchange principle · «كل تماسٍ يترك أثراً»**

Court-oriented crime-scene evidence analysis for Saudi Arabia. Investigators upload photos and videos; **Qwen3-VL** analyzes them; the system produces an evidence **timeline**, an **annotated evidence gallery**, and a full analytical report in **legal Modern Standard Arabic**, exported as **PDF/A** and **DOCX**, with a SHA-256 **chain of custody** and a tamper-evident, hash-chained **audit log**. The entire UI is Arabic, RTL.

**العربية: [README.ar.md](README.ar.md)**

---

## ⚠️ Legal & ethical boundaries

Every output is stamped: **"تحليل بمساعدة الذكاء الاصطناعي — يتطلب تحقيق خبير مؤهل قبل أي استخدام قانوني"** (AI-assisted analysis — requires a qualified expert investigation before any legal use). The system never issues legal judgments — no guilt, no cause of death, no intent. Detections below the confidence threshold (default 75%) are force-flagged **«يتطلب مراجعة بشرية»** and enter a mandatory human review queue. Human-presence detections are observation-only (no identification) and are blurred by default in annotated outputs.

## One-command run

```bash
docker compose up --build
```

Then open **http://localhost:8090**. With no `.env` file the system boots in **mock mode**: no API key, no GPU — the full pipeline (upload → analysis → timeline → review → PDF/A report) works against recorded fixtures and the bundled staged samples.

To use the real model, `cp .env.example .env` and set:

| Variable | Meaning |
|---|---|
| `MODEL_MODE` | `api` (OpenRouter/DashScope) · `local` (vLLM, `--profile gpu`) · `mock` |
| `OPENAI_API_KEY` | OpenRouter key (default provider) |
| `MODEL_NAME_FAST` / `MODEL_NAME_THINKING` | instruct slug for triage/detection · thinking slug for aggregation/comparison/narratives |
| `OPENROUTER_DATA_COLLECTION` / `OPENROUTER_ZDR` | privacy routing — crime-scene imagery should not be retained by inference providers |

> **Data sovereignty:** `MODEL_MODE=api` sends scene imagery to a cloud provider. For real casework use `MODEL_MODE=local` (fully air-gapped vLLM) — that is what the GPU compose profile is for.

## Architecture (short)

```
frontend/  React 19 + Vite + TS + Tailwind v4 — Arabic RTL, design tokens from DesignMD (see frontend/DESIGN.md)
backend/   FastAPI + SQLAlchemy 2 (async) + SQLite(WAL)|Postgres — single asyncio worker owns the pipeline
           s0 verify hashes → s1 keyframes (PySceneDetect+ffmpeg+phash) → s2 triage → s3 detect (Qwen3-VL,
           bbox_2d 0–1000) → s4 aggregate entities → s5 timeline (pure code) → s6 cross-source compare →
           s7 narratives (citation-validated) → s8 annotate (badges, face blur) → s9 render (WeasyPrint
           PDF/A-3u + docxtpl DOCX + court ZIP bundle)
```

One OpenAI-SDK client covers all model modes (OpenRouter · DashScope · vLLM · mock). Model calls are logged (tokens/latency/cost), retried with exponential backoff, JSON-schema-validated, and repaired on failure. Prompts live in `backend/app/prompts/` — versioned, their SHA-256 recorded per analysis run and printed in the report appendix.

## Verification

```bash
# in-container test suite (unit + integration in mock mode + report/PDF-A checks)
docker compose exec backend pytest -q
# PDF/A conformance (veraPDF)
docker run --rm -v athar_athar-data:/data verapdf/cli -f 3u /data/reports/<file>.pdf
```

Seed a demo case: `docker compose exec backend python scripts/seed_demo.py`

## Repository map

| Path | Purpose |
|---|---|
| `backend/app/prompts/` | Arabic system prompts (anti-fabrication, injection defense, category definitions) |
| `backend/app/pipeline/stages/` | the 10 pipeline stages |
| `backend/app/modelclient/` | unified Qwen3-VL client (api/local/mock) + JSON repair + budget |
| `frontend/DESIGN.md` | UI design system — adapted from `DesignMD.txt` for Arabic RTL |
| `samples/` | staged, innocuous sample media + mock fixtures + bbox calibration grid |
| `Prompt.txt` / `DesignMD.txt` | original source specifications |
