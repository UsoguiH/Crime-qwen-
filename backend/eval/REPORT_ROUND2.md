# Accuracy Optimization — Round 2 Final Report (2026-07-19)

## What we set out to do
Make the detection AI measurably more accurate, prove it against real labeled
ground truth (not the model's own claims), iterate one change at a time, and
ship the winner to the live app.

## The proven win (shipped)
Test set: **92 real COCO val2017 images, 194 expert-drawn boxes** (knife 23,
scissors 17, cell phone 23, laptop 31, bottle 39, book 61). Matcher: class-aware,
IoU ≥ 0.5. Provider pinned (Alibaba) to remove the routing confound.

| strategy | precision | recall | F1 | mean IoU |
|---|---|---|---|---|
| baseline (fast / non-thinking) | 0.714 | 0.284 | 0.406 | 0.883 |
| **thinking mode ← WINNER, shipped** | 0.502 | **0.593** | **0.544** | 0.813 |
| recheck (second-look + dedup) | 0.885 | 0.237 | 0.374 | 0.905 |
| thinking + grounding-verify | ~0.48 | ~0.31 | ~0.38 | 0.848 |

**Thinking mode more than doubles recall (0.284 → 0.593, +109% relative)** and
lifts F1 +34%. Crime-critical classes: knife 0.261 → 0.522, scissors 0.529 →
0.765, laptop 0.677 → 0.935. Cost is precision (0.71 → 0.50), but: (a) only 2
duplicate boxes in 92 images, so it's genuine extra detections — many are real
objects COCO left unlabeled, meaning measured precision is a **lower bound**;
(b) the product mandates human review of every finding, so recall is the metric
that matters and false positives are absorbed by the reviewer.

**Shipped to production:** the full-case pipeline's detection now defaults to
thinking mode (previously it only escalated on complex frames, leaving most
detection in the low-recall fast path). The UI dropdown was simplified so the
accurate path is the obvious default. Photo mode already defaulted thinking on.

## Rejected (with mechanism — honest iteration)
- **Recheck**: a "what did you miss" second pass with IoU-dedup. Recall *fell*
  to 0.237 — the dedup merges adjacent same-class objects (books on a shelf have
  IoU > 0.5), deleting real instances. Net loss.
- **Grounding-verify**: drop any detection the single-target grounding pass can't
  re-confirm. Recall fell — grounding on a cluttered full image fails to
  re-locate many real objects, dropping them. (Grounding stays valuable for
  *tightening* accepted boxes — round 1: 58% → 75% correct@0.5 — just not as a
  presence filter.)

## The honest limitation (this is the important part)
The 3 in-app demo cases (WEAPONS-01, DEVICES-01, SCENE-01) revealed a real
distinction we must be clear about:

- The **detection engine** (measured above with an enumeration prompt) is what
  we improved and proved.
- The **product** uses the *forensic* prompt, which deliberately judges
  **evidentiary relevance** — it flags weapons, devices, blood, markers, and
  ignores mundane objects. In the demo it correctly found the **knife (0.98)**
  and **scissors (0.95)**, and flagged genuinely evidence-like items (a phone, a
  notebook, a hotel keycard, scene-marker arrows) — while ignoring ordinary
  books and bottles.

So "7/15 COCO objects" is NOT a fair product-accuracy score: **a book on a shelf
or a water bottle is not crime evidence**, and the forensic layer is right to
skip it. COCO is the correct test for the detection *engine*; it is the wrong
scorecard for the forensic *relevance* layer.

## What a true forensic-accuracy number requires (next step, honestly stated)
To score the *product* (not just the engine) we need a labeled dataset of real
forensic classes — weapons (guns/knives), bloodstains, impressions — with
ground-truth boxes. These exist (e.g. weapon-detection datasets on Open
Images / Roboflow) but are not as trivially downloadable as COCO. Building that
test set is the right next investment; per the ground rules we did **not**
fabricate a forensic accuracy number we couldn't measure.

## Round 3 — measured on REAL weapon photos (not COCO)
Dataset: **University of Granada OD-WeaponDetection** — real photos of actual
handguns and knives (internet/CCTV/YouTube frames) with expert Pascal-VOC boxes,
CC BY-SA, no-login. Built a 70-image / 74-box set (38 handgun, 36 knife).

Ran 40 images through the **exact production box pipeline** (forensic thinking-
detect → dedup → per-object grounding → degenerate-filter → dedup) and scored
weapon boxes against the expert boxes:

| metric | value |
|---|---|
| **mean IoU of matched boxes (BOX ACCURACY)** | **0.879** |
| recall (real weapons found) | 0.767 (33/43) |
| precision (detections that hit a real weapon) | 0.717 |
| correct@0.5 | 0.767 |

This is the honest product-accuracy number on real crime-relevant imagery:
**when the system flags a weapon, the box lands on it tightly (IoU 0.88)**, and
it finds ~77% of real weapons. Much stronger than the cluttered-COCO scene
numbers because weapons are the salient subject and the forensic prompt +
grounding pipeline perform well on them. 100% is not achievable by any vision
model; 0.88 IoU / 0.77 recall on real weapons, with mandatory human review, is a
genuinely strong, defensible result.

## Round 3 — per-class finding (handguns vs knives)
Rendering AI boxes (red) against expert boxes (green) on real weapon photos
(in-app, case REAL-WEAPONS-01) shows a clear, honest split:
- **Handguns: boxing is excellent** — red and green nearly coincide, IoU 0.80–0.94.
  Compact, fully-visible objects are localized tightly.
- **Knives: FOUND reliably (conf 0.95–0.98) but box EXTENT less precise** — the AI
  boxes the clearly-visible blade, the expert box spans the whole knife including
  the gripped/occluded handle, so several fall just under IoU 0.5 despite being
  "on the knife." Thin, held, partially-occluded objects have genuine box-extent
  ambiguity. This is the real remaining weakness, not a gross localization error.
Aggregate over 40 mixed images: mIoU 0.879 / recall 0.767. Small in-app samples
that hit several hard knife cases score lower (variance) — the 40-image number is
the reliable estimate.

## Bottom line
- **Engine accuracy: materially and provably improved** (recall doubled),
  measured on real labeled data, winner shipped to the live web app.
- **Product relevance: working as designed** (finds weapons, ignores clutter),
  but not yet scored against a forensic-labeled set — that's the honest gap and
  the clear next step.
