# Evaluation Log — Qwen3-VL detection pipeline vs COCO ground truth

**Test set (fixed for all runs):** 39 COCO val2017 images, 84 GT boxes
(knife 12, scissors 8, cell phone 11, laptop 16, bottle 11, book 26).
Selection: person-free images, box ≥0.4% of image area, ≤8 target boxes/image,
deterministic (sorted image ids). Matching: class-aware greedy, IoU ≥ 0.5.
Model: qwen/qwen3-vl-235b-a22b-instruct via OpenRouter, temperature 0.1, 2560px cap.

| run | change | prec | recall | F1 | mIoU | halluc. | miss |
|---|---|---|---|---|---|---|---|
| base-pipeline | production prompt (20_detect + 00 rules) | 1.000 | 0.012 | 0.024 | 0.984 | 0.000 | 0.988 |
| base-grounding | eval prompt (91 + 00 rules prepended) | 0.714 | 0.119 | 0.204 | 0.903 | 0.286 | 0.881 |

## Diagnosis after baselines
- Localization is NOT the problem: mean IoU 0.90–0.98 on the few matches.
- Raw outputs show the model *naming* visible target objects then declaring them
  "غير مدرج ضمن قائمة الأصناف" / "لا أدلة جنائية ضمن نطاق المهمة" — the
  always-prepended forensic persona (00_common_rules: crime-scene scope,
  "empty list is a correct answer", "ordinary objects aren't evidence")
  overrides the task instruction below it.
- Hypothesis H1: removing the forensic preamble from the eval task will unlock
  recall with little hallucination cost → proves the gate is prompt policy,
  not perception.

## Iteration 1 — 9x prompts standalone (no 00 prefix)
Change (one variable): `load_prompt` skips 00_common_rules for 9x prompt files.
Same 39 images, same matcher.
**Result: CONFIRMED H1.** recall 0.119 → **0.238** (2×), precision 0.714 → 0.800,
F1 0.204 → **0.367**, mIoU 0.859. The forensic persona was the suppressor.
Remaining failure pattern: under-enumeration — 25 preds vs 84 GT (0.64/image);
model reports the salient instance and stops; `book` still 0/26 (shelves/stacks
never enumerated), knife 2/12, laptop 6/16.

| run | change | prec | recall | F1 | mIoU | halluc. | miss |
|---|---|---|---|---|---|---|---|
| iter1-grounding-standalone | drop forensic preamble (9x standalone) | 0.800 | 0.238 | 0.367 | 0.859 | 0.200 | 0.762 |

## Iteration 2 — enumeration protocol (92_eval_grounding_v2.md)
Hypothesis H2: recall is limited by early stopping, not perception → an explicit
quadrant-scan + count-then-emit protocol (with per-class counts in the summary)
will raise recall, especially multi-instance classes (book, bottle, laptop).
Change (one variable): prompt content only (92 vs 91); harness/model/matcher identical.
**Result: REGRESSED HARD.** recall 0.238 → **0.036**, only 3 predictions.
Evidence: image 119233 returned summary «حواسيب محمولة: 1» with an EMPTY
detections array — the counting step *substituted* for emission; latencies up to
118s for 61 output tokens point at grammar-constrained decoding struggling.
H2 rejected: more protocol ≠ more recall. 92 prompt abandoned.

| run | change | prec | recall | F1 | mIoU | halluc. | miss |
|---|---|---|---|---|---|---|---|
| iter2-enumerate | count-then-emit protocol | 1.000 | 0.036 | 0.069 | 0.843 | 0.000 | 0.964 |

## Iteration 3 — strict json_schema OFF (prompt-JSON + client-side validation)
Hypothesis H3: OpenRouter strict structured-output (grammar-masked decoding on
the routed provider) suppresses/truncates detection arrays; latency anomalies
support this. Change (one variable): enforce_schema=False for the identical
iter1 prompt (91), everything else fixed.
**Result: REGRESSED (H3 rejected as stated).** recall 0.012, 1 prediction.
BUT the 25 → 3 → 1 swings across near-identical configs exposed the real
methodological flaw: **OpenRouter provider routing was an uncontrolled hidden
variable** — each request may hit a different backend (different engines &
quantizations: FP8/BF16/INT4), and dropping require_parameters in iter3 changed
the eligible pool. Served-provider was not even recorded. All prior comparisons
are confounded; production accuracy is exposed to a routing lottery.

| run | change | prec | recall | F1 | mIoU | halluc. | miss |
|---|---|---|---|---|---|---|---|
| iter3-noschema | enforce_schema off (91 prompt) | 1.000 | 0.012 | 0.024 | 0.849 | 0.000 | 0.988 |

## Iteration 4 — provider pinned (order=[alibaba], allow_fallbacks=false)
Fix the confound first, then resume prompt science. Client now records the
served backend per call (`usage.served_by`). Change (one variable vs iter1):
routing pinned to Alibaba (first-party serving); prompt 91 + schema ON identical.
**Result: clean reproducible baseline.** 39/39 calls verified `served_by: Alibaba`.
recall 0.155, precision 0.867, F1 0.263, mIoU 0.820. iter1's 0.238 recall was
partly favorable-routing luck (its providers were not recorded — unknowable now).

| run | change | prec | recall | F1 | mIoU | halluc. | miss |
|---|---|---|---|---|---|---|---|
| iter4-pinned-alibaba | provider pinned, else = iter1 | 0.867 | 0.155 | 0.263 | 0.820 | 0.133 | 0.845 |

## Iteration 5 — per-class decomposed queries (93, 6 calls/image, pinned)
Hypothesis H5: under-enumeration is query-structure-bound; targeted single-class
queries (standard open-vocab grounding practice) raise recall. Change (one
conceptual variable vs iter4): query decomposition; provider still pinned.
**Result: BEST CONTROLLED CONFIG — improvement confirmed vs iter4 on the same set.**
recall 0.155 → **0.238** (+54% rel), precision 0.867 → **0.952**, F1 0.263 →
**0.381**, hallucination 0.133 → **0.048**, mIoU 0.887. laptop 0.188 → 0.562,
knife 0.167 → 0.250, scissors 0.625. Cost: 6× calls/image (~$0.17/39 images).

| run | change | prec | recall | F1 | mIoU | halluc. | miss |
|---|---|---|---|---|---|---|---|
| iter5-perclass | per-class queries (6/img), pinned | 0.952 | 0.238 | 0.381 | 0.887 | 0.048 | 0.762 |

## The `book` invariant (0/26 in every run)
GT inspection (e.g. 000000017182.jpg): the 26 book boxes are individual ~1%-area
**book spines standing in adjacent rows** — COCO labels each spine. The model
never emits per-spine boxes under any configuration tried. Excluding the book
class: iter5 recall = 20/58 = **0.345**. Characterization: fine-grained instance
enumeration of small adjacent same-class objects is beyond this stack today;
separated/salient objects get high precision + IoU.

## Production changes adopted from this evaluation
1. 9x standalone prompts (loader no longer contaminates technical tasks).
2. `OPENROUTER_PROVIDER_ORDER=alibaba` default with fallbacks allowed
   (`OPENROUTER_ALLOW_FALLBACKS=true`); eval pins strictly with false.
3. Served backend recorded per call (`usage.served_by`) for observability.
4. NOT adopted without further evidence: per-class decomposition in the
   production pipeline (6× cost; recommend as an optional deep-scan mode),
   enumeration-protocol prompts (proven regression).
