# Qwen3-VL Evidence-Detection Evaluation — Final Report (2026-07-19)

## Verdict up front (brutally honest)
On real labeled images, this stack has **excellent precision and localization
but poor recall on cluttered scenes**. Best controlled configuration: precision
**0.952**, hallucination **4.8%**, mean IoU **0.887** — but recall **0.238**
(0.345 excluding the pathological book-spine class). It finds what it reports
with near-forensic reliability; it does not report most of what is there when
many objects are present. **Demo-ready for deliberate, single-subject evidence
photographs (the typical crime-scene closeup). Not ready for exhaustive
inventory of cluttered wide shots** — that claim should not be made to
stakeholders today.

## Method
- **Ground truth:** 39 COCO val2017 images, 84 human-labeled boxes across
  knife (12), scissors (8), cell phone (11), laptop (16), bottle (11),
  book (26). Person-free images, boxes ≥0.4% of image area, deterministic
  selection. Nothing was measured against the model's own claims.
- **Matching:** class-aware greedy, IoU ≥ 0.5; FPs decomposed into
  hallucination / bad-box / class-confusion / out-of-scope.
- **Model:** `qwen/qwen3-vl-235b-a22b-instruct` via OpenRouter, temperature 0.1,
  images ≤2560px. From iteration 4 the serving backend was pinned
  (`alibaba`, `allow_fallbacks=false`) and verified per call.

## Results (same 39 images / 84 boxes throughout)

| run | one change | prec | recall | F1 | mIoU | halluc. | miss |
|---|---|---|---|---|---|---|---|
| base-pipeline | production forensic prompt | 1.000 | 0.012 | 0.024 | 0.984 | 0.000 | 0.988 |
| base-grounding | eval prompt under forensic preamble | 0.714 | 0.119 | 0.204 | 0.903 | 0.286 | 0.881 |
| iter1 | drop forensic preamble | 0.800 | 0.238 | 0.367 | 0.859 | 0.200 | 0.762 |
| iter2 | count-then-emit protocol | 1.000 | 0.036 | 0.069 | 0.843 | 0.000 | 0.964 |
| iter3 | strict json_schema off | 1.000 | 0.012 | 0.024 | 0.849 | 0.000 | 0.988 |
| iter4 | provider pinned (alibaba) | 0.867 | 0.155 | 0.263 | 0.820 | 0.133 | 0.845 |
| **iter5 (best)** | **per-class queries, pinned** | **0.952** | **0.238** | **0.381** | **0.887** | **0.048** | **0.762** |

Valid comparisons: iter4 → iter5 (+54% recall, +0.085 precision, hallucination
÷2.8) is the only pair with routing controlled on both sides. base→iter1–3 are
confounded by the then-unknown provider lottery — stated, not hidden.

Per-class (iter5): scissors R=0.625 · laptop R=0.562 · knife R=0.250 ·
bottle R=0.182 · cell phone R=0.091 · book R=0.000.

## Diagnosis — what actually fails (worst cases in `outputs/*/failures/`)
1. **Forensic persona suppression (fixed):** raw outputs literally said
   "المشهد يحتوي على حاسوب محمول … لكنه غير مدرج ضمن قائمة الأصناف" — the model
   named the object then refused it. Removing the crime-scene preamble from
   technical tasks doubled recall.
2. **Instruction interference (proven regression):** the counting protocol made
   the model satisfy the task with count summaries («حواسيب محمولة: 1») while
   returning empty detection arrays, with latencies to 118s.
3. **Provider routing lottery (fixed):** identical configs swung 25→3→1
   predictions until the backend was pinned and recorded.
4. **Under-enumeration (the remaining core weakness):** single-shot queries
   yield ~0.6 detections/image vs 2.2 GT/image; per-class queries recover part
   of it. The hard floor: adjacent small same-class instances — all 26 book GTs
   are ~1%-area spines in rows (e.g. 000000017182.jpg: six adjacent spines,
   zero predictions in every run).
5. **Not failure modes:** Arabic output (naming was consistently correct),
   coordinates (mIoU 0.82–0.98; separate calibration grid 4/4 within ~1%),
   fabrication (best-run hallucination 4.8%, mostly zero elsewhere).

## Current best configuration (adopted where safe)
- Production keeps the forensic prompt (its conservatism is a feature for
  casework closeups) with: standalone 9x technical prompts, temperature 0.1,
  strict schema ON, provider preference `alibaba` (fallbacks allowed in
  production, disabled in eval), served-backend logged per call.
- **Recommended optional mode (not yet wired into the pipeline):** per-class
  decomposed "deep scan" for wide/cluttered frames — measured +54% recall and
  ÷2.8 hallucinations at 6× call cost.

## Remaining weaknesses / next levers (unproven — would need the same harness)
- Tiled inference (quadrant crops + merge) for small-instance recall.
- English grounding-cookbook phrasing A/B.
- ShoeCase footwear-impression set (not obtainable this session — COCO used;
  no fabricated results).
- Larger set + repeated runs for variance bars (n=39 gives ±~0.05 on recall).
