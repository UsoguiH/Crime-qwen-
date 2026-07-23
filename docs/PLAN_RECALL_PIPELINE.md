# Implementation Plan — Exhaustive-Recall + Verified Pipeline

Branch: `Make_Qwen_Smarter_faster` · Status: APPROVED-PENDING · v3 (2026-07-23)

Mission: the model must catch **every visible piece of evidence** on any photo,
consistently across runs, with zero tolerance for hallucinations. Strategy from
the research phase: **over-generate candidates from many independent angles →
let the proven crop classify-verify judge every candidate**. Nothing downstream
of generation can add objects today — this plan adds three new generators and
one recovery loop, and turns the verifier into the single quality gate.

---

## 0. Target architecture (one frame, photo mode)

```
┌─ Stage A: candidate generation (ALL concurrent) ───────────────┐
│ A1 full-frame thinking pass          (exists)                  │
│ A2 adaptive tiles 2×2→3×3, 18% ovl   (upgrade)     thinking    │
│ A3 category sweeps ×3, minimal JSON  (NEW)         instruct    │
└────────────────────────────────────────────────────────────────┘
→ B strict dedup (exists)
→ C ground all (exists) → dedup (exists)
→ D verify + ENRICH (upgrade): classify-verify each box; fills empty
   description fields from the zoomed crop; trace/bio never hard-deleted
→ dedup (exists)
→ E1 marker-linkage sweep (NEW): every numbered marker with no evidence
   box nearby → zoomed crop → "what does this marker flag?" → candidates
→ E2 completeness critic (NEW): annotated image → "list uncovered
   evidence regions" → candidates
→ all E-candidates: verify+enrich → dedup → done (loop E2 max ×2)
```

Wall-clock target ≤ 4 min · calls/photo ≈ 85–95 (budget 400) ·
cost/photo ≈ $0.10–0.15 (from ~$0.06).

---

## 1. Work packages (independently shippable, in order)

### PR-1 — Verifier hardening + enrich (Stage D) — foundation
Files: `grounding.py`, `model_io.py`, `97_crop_classify.md`, tests.

1. **New schema** `CropVerifyRich(CropVerify)`: adds `description_ar`,
   `forensic_significance_ar`, `handling_recommendation_ar`,
   `visible_text_ar` (all default ""). Prompt 97 gains a section: *"if
   confirmed, describe the item from the crop in forensic Arabic"*.
2. **Enrich-if-empty**: `verify_frame` writes these fields to the Detection
   row **only when the row's field is ""** (full/tile detections keep their
   scene-context prose; sweep/linkage/critic candidates get filled here).
   `location_description_ar`: generated from normalized box position via a
   small helper (`"في الجزء السفلي الأيمن من الصورة"` style) when empty —
   crops can't see scene context, don't ask the model to invent it.
3. **No-delete guard**: rejected candidates with `category ∈ {trace,
   biological, impressions}` OR box area < 1.5% of image → review-flag,
   never delete. (Hair/fiber conf sits at 0.6–0.75 — precisely what the old
   rule deleted.)
4. **Retry-on-empty**: any Stage-A pass returning 0 detections with
   `status=="repaired"` retries once (same params). Kills the silent-empty
   failure mode measured on 2026-07-21.
5. Tests: enrich-only-empty; no-delete guard; retry-on-empty (mock).

### PR-2 — Marker-linkage sweep (E1) — biggest forensic win
Files: `s3_detect.py`, `grounding.py` (geometry helper), new prompt
`26_marker_evidence.md`, `model_io.py` (`SweepResult`), tests.

1. After first verify pass: for every `scene_markers` detection with digits,
   compute nearest non-marker evidence box (center-to-center, normalized).
   **Uncovered marker** = no evidence center within `LINK_RADIUS = 0.12`
   of image diagonal.
2. Per uncovered marker (concurrent, sem 12): crop `pad = 2.5×` marker box
   (min 640px, LANCZOS upscale) → prompt 26: *"this numbered evidence
   marker flags something. Identify the evidence item(s) beside it — NOT
   the marker itself. Empty list if truly nothing."* → `SweepResult`
   (minimal items: name_ar, category, bbox_2d, confidence), non-thinking,
   1200 max tokens.
3. Map boxes crop→full (reuse tile math). New rows `local_id = mk{N}_dX`,
   `coord_space="grounded"` (zoomed-crop boxes are accurate — skip
   re-grounding). Then: verify+enrich → dedup.
4. Guard: markers already adjacent to evidence produce no calls — typical
   scenes trigger 0–4 calls. Empty result is a valid answer (prompt says
   so explicitly — some markers flag things invisible in frame).
5. Tests: geometry (covered/uncovered marker fixtures); crop mapping;
   dedup of linkage candidates against existing boxes.

### PR-3 — Category sweeps (A3)
Files: `s3_detect.py`, new prompt `25_sweep.md`, tests.

1. One prompt file, parameterized by context `sweep_focus`: three focus
   packs — (a) بيولوجية/آثار دقيقة: كل بقعة دم، شعر، ألياف، سوائل، زجاج;
   (b) أدوات وأجهزة: أسلحة، هواتف، وثائق، أوعية، ذخائر;
   (c) بنية المشهد: علامات مرقمة، آثار أقدام/أدوات، أضرار، بصمات.
   Prompt is a **checklist with counting instruction**: "sweep the image
   row by row; COUNT first, then output every instance".
2. Minimal schema `SweepResult` (shared with PR-2) — no prose fields, so
   nothing discourages enumeration. Non-thinking, temp 0.1, 3000 tokens,
   full frame at 2560px. Runs inside Stage-A `asyncio.gather` (3 extra
   concurrent calls, ~20–40s each, hidden behind the thinking passes).
3. Rows `local_id = sw{a|b|c}_dX`, empty descriptions (PR-1 enriches).
4. Tests: sweep rows land with empty prose; dedup merges sweep duplicates
   of full-pass detections (existing rules already category-aware).

### PR-4 — Completeness critic (E2) + adaptive tiling (A2)
Files: `s3_detect.py`, `grounding.py`, new prompt `27_critic.md`, tests.

1. **Critic**: render the frame with current boxes burned in (PIL, thin
   2px outlines + index chips — set-of-mark style) → thinking call,
   prompt 27: *"every drawn box is already recorded. List up to 8 regions
   showing visible potential evidence NOT covered by any box. Empty list
   is a correct answer."* → `SweepResult`. Candidates IoU-checked against
   existing boxes (reject if IoU > 0.3 or containment > 0.5 with any
   existing box — the critic must only ADD) → verify+enrich → dedup.
   Loop: repeat once if ≥1 candidate survived verification (max 2 rounds).
2. **Adaptive tiles**: `detect_tiles(grid = 3 if max(W,H) ≥ 2000px else 2,
   overlap = 0.18)`. 3×3 keeps thinking mode (recall eval showed 2×
   recall from thinking); 9 concurrent calls fit sem 12, wall-clock
   unchanged (= slowest single call).
3. Tests: critic-candidate IoU rejection; loop terminates; grid selection.

### PR-5 — Timing/telemetry + eval gate (closes the loop)
1. Extend the phase log line: per-stage counts (candidates by source:
   full/tiles/sweeps/linkage/critic; verified/dropped/enriched) — one
   greppable INFO line per frame. This is how future "he missed X" reports
   get diagnosed in seconds.
2. **Regression eval script** `backend/eval/recall_check.py`: runs N=2
   analyses on the 3 reference photos (markers scene, corpse scene, axe+
   hair scene) and asserts the checklist below. Run before merging to main.

---

## 2. Ordering & sequencing rationale

PR-1 first because every later stage depends on verify-enrich (their
candidates carry empty prose) and on the no-delete guard (sweeps surface
fragile trace items that the old rule would delete). PR-2 before PR-3:
highest value-per-call (0–4 calls/photo) and unique to our domain. PR-4
last: the critic is most useful once the cheap generators exist (it then
catches only true stragglers); it's also the most expensive per call.

## 3. Acceptance criteria (the definition of "smarter")

Run the eval gate (PR-5) — all must hold on 2/2 consecutive runs:
- [ ] Axe+hair scene: hair tuft detected (both runs) — the reported miss
- [ ] Every numbered marker is either adjacent to an evidence box or has a
      logged linkage query answering "nothing visible"
- [ ] Corpse scene: جثة (ظاهرياً) + blood on clothes present (both runs)
- [ ] Markers scene: all 6 markers with correct digits + knife + phone +
      both footprint trails + ≥3 blood items (both runs)
- [ ] Zero hallucinated objects surviving verify (manual spot-check)
- [ ] Detection-count spread between the two runs ≤ 15%
- [ ] Wall-clock ≤ 4 min/photo at concurrency 12
- [ ] All existing 26 backend tests still pass; new tests green

## 4. Risks & mitigations

| Risk | Mitigation |
|---|---|
| More candidates → more false positives | Every new candidate passes crop classify-verify (benchmarked stronger than 235B); dedup runs after every stage |
| Cost/photo ↑ to ~$0.10–0.15 | Accepted for POC; `recall:"fast"` skips A2-3/E1-2 entirely (single knob, already plumbed) |
| Critic hallucinating "missed" regions | Candidates must survive verify; IoU-reject anything overlapping existing boxes; hard cap 8/round, 2 rounds |
| Slow-provider stalls (no deadline by user decision) | Unchanged behavior; concurrency hides all but the slowest call; noted, not mitigated |
| Marker linkage on markerless scenes | Zero extra calls by construction |
| Mock mode / video path | All new stages gated behind `model_mode != "mock"` and photo-mode only; `detect_one` signature untouched |
| Checkpoint/resume mid-frame | Unchanged: frame-level checkpointing; a resumed frame reruns all stages (idempotent — dedup absorbs repeats) |

## 5. Explicit non-goals (this branch)
- No GPU/open-vocab detector hybrid (MQADet pattern) — future, needs infra
- No cross-run union of detections (product-semantics change)
- No per-call deadline (explicitly reverted by owner 2026-07-23)

---

## Iteration log (how this plan reached v3)
- **v1→v2**: moved marker-linkage AFTER verify (it needs final marker boxes
  + digit corrections, not raw ones); moved descriptions out of sweep
  schema after realizing prose-per-item is itself a recall suppressor —
  enrichment relocated to the verify crop, which also writes better prose
  (zoomed view). Location text can't come from a crop → positional helper.
- **v2→v3**: reordered PRs (verify hardening first — later stages depend on
  it); added retry-on-empty to PR-1 (diagnosis #5 was otherwise
  unaddressed); critic gained the IoU-reject rule + "empty list is
  correct" phrasing (self-correction-mirage research: critics without a
  strong verifier and a no-overlap rule mostly re-find existing objects);
  added the eval gate as its own PR — "smarter" must be measurable or it
  regresses silently; capped critic rounds at 2; linkage boxes marked
  grounded to skip a wasted re-ground call.
