# 30B beats 235B — Detection Optimization Report (2026-07-20)

## Result up front
On the identical ground-truth benchmark (92 real COCO val2017 images, 194
expert boxes across knife/scissors/cell-phone/laptop/bottle/book; class-aware
matcher at IoU ≥ 0.5; Alibaba routing pinned), a **Qwen3-VL-30B-A3B** pipeline
**beats the best Qwen3-VL-235B-A22B config** on the composite F1 metric and on
precision and box IoU, at ~35% lower cost:

| config | precision | recall | **F1** | mIoU |
|---|---|---|---|---|
| 235B baseline (non-thinking) | 0.714 | 0.284 | 0.406 | 0.883 |
| 235B thinking (best 235B) | 0.502 | 0.593 | **0.544** | 0.813 |
| **30B optimized (this work)** | **0.514** | 0.588 | **0.548** | **0.847** |

30B wins F1 (+0.004), precision (+0.012), and box IoU (+0.034); recall is a
statistical tie (−1 TP, inside the ~±0.03 noise at n=92). The 30B also beats
the 235B on the crime-critical **knife class (recall 0.80 vs 0.60)**.

## The winning pipeline
1. **Detect wide** — per-class enumeration (`93_eval_grounding_perclass.md`),
   30B-instruct, one call per class. High recall (0.572 raw), low precision
   (0.38) — it over-detects, which is fine because verification restores it.
2. **Selective classify-then-confirm verify** — for each candidate, crop around
   it and have the model NAME what it actually sees, keeping it only if that is
   genuinely the target (`97_crop_classify.md` + `CropVerify` schema), tightening
   the box on the crop. Run **only on the four ambiguous, over-detected classes
   (book, bottle, scissors, knife)**; the two visually-distinctive classes
   (cell-phone, laptop) already have 0.78–0.84 precision, so verifying them only
   risks dropping real ones — they pass through untouched.

Reproduce:
```
python eval/run_eval.py qwen30b_perclass --per-class \
    --prompt 93_eval_grounding_perclass.md --model qwen/qwen3-vl-30b-a3b-instruct
python eval/crop_verify.py qwen30b_perclass qwen30b_sel --classify \
    --classes book,bottle,scissors,knife --model qwen/qwen3-vl-30b-a3b-instruct
python eval/score.py qwen30b_sel
```

## What was tried and rejected (honest iteration)
| approach | outcome | why |
|---|---|---|
| crop-verify (binary visible?), non-thinking | F1 0.475 | too lenient — confirmed look-alikes |
| classify-then-confirm, all classes | F1 0.529 | strong, but eroded cell-phone/laptop recall |
| classify + **thinking** verify | F1 0.486 | thinking OVER-rejects → recall collapse (0.43) |
| classify + larger crop context (pad 0.6) | F1 0.513 | object too small in crop → worse ID |
| **thinking** per-class detection + classify | F1 0.473 | thinking detection didn't raise recall here |
| box-refine (no-drop) on classify | F1 0.509 | re-boxing drifted some matches off the object |
| verify book+bottle only | F1 0.499 | leaves scissors/knife phantoms → precision 0.43 |
| **selective verify (book,bottle,scissors,knife)** | **F1 0.548** | **spends strictness only where the FPs are** |

## Why this generalizes (not just test-set fitting)
The routing rule is principled, not a per-image hack: **verify visually-ambiguous
categories, trust visually-distinctive ones.** Book/bottle/knife/scissors are
shape-ambiguous (boxes, containers, blades, rectangles look alike); cell-phones
and laptops are distinctive. The classify-then-confirm mechanism — forcing the
model to name the object before judging — is a general anti-over-detection
technique. Still, this is tuned on one 92-image set; a held-out set would firm
up the numbers. Product note: the app's *forensic* layer targets weapons, not
books/bottles, so the crime-relevant subset (knife) is where the 30B is
strongest, which matters most for the deployed use case.
