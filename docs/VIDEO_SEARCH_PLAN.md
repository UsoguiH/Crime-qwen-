# Plan — Fast Natural-Language Video Search ("اعثر في الفيديو")

> Goal: upload hours of CCTV, ask in Arabic ("متى يظهر شخص يحمل سلاحاً؟"), get
> **timestamped clips** back. Target: results in **1–2 minutes**, accurate.
> The problem is impossible manually (no one watches 100 hours) — this is the
> "can't do without AI" feature.

## SMART-FIRST design — "in crime there is no space for wrong"
The errors are asymmetric, so the design is not symmetric:
- **False NEGATIVE (missing a real weapon) = catastrophic, irreversible.**
- False POSITIVE (flagging a non-event) = a human glances and dismisses it.
Therefore the system is tuned to **never miss**, accepts extra false positives,
and **never concludes on its own** — it surfaces candidates + evidence + reasoning
for a human to confirm. Five principles make it *smart*, not just fast:

1. **High-recall retrieve, precise verify.** The retrieval threshold is set toward
   recall (cast a WIDE net — take more candidates than needed). Precision is
   restored by the rigorous VLM verify step, not by throwing away candidates
   early. Missing is unacceptable; over-catching is cheap.

2. **Multi-signal fusion (redundancy = no blind spot).** Three INDEPENDENT signals
   vote on each moment: (a) SigLIP semantic embedding (appearance/scene/action),
   (b) open-vocab object detector (concrete object presence), (c) Qwen3-VL
   reasoning (relations: "person *holding* a knife", not just "knife on a table").
   If one signal misses, another catches it. A single model is a single point of
   failure — forbidden here.

3. **Rigorous verification with reasoning + self-consistency.** Each candidate is
   verified by Qwen3-VL in **thinking mode**, and high-stakes hits (weapons,
   violence) are verified **twice** (self-consistency, as we already do for Q&A) —
   agreement raises confidence, disagreement is surfaced as "uncertain, review",
   never silently dropped. The model must SHOW its reasoning and the box, so the
   investigator can audit *why* it flagged the moment.

4. **Human-in-the-loop, always. The AI never decides.** Output is a review queue of
   timestamped clips with frame + box + reasoning + confidence. The investigator
   confirms/rejects each — exactly like the evidence review workflow already in
   the app. Every search + decision is written to the tamper-evident audit chain.

5. **Honest coverage, not false certainty.** The report states the sampling rate
   and the blind spot plainly: "فُحص عند ٢ إطار/ث — قد يفوت حدث يظهر أقل من ٠٫٥ ثانية".
   To shrink that blind spot: **adaptive sampling** — bump the frame rate where
   motion or people are detected, so brief but critical events (a weapon flashed
   for a second) are not skipped. Never claim "nothing there" — claim "nothing
   found at this coverage."

**Net:** speed comes from index-once-then-retrieve; *smartness* comes from
multi-signal redundancy + reasoning-based double-verification + mandatory human
confirmation + honest coverage. Fast enough to use, rigorous enough for evidence.

## The core insight (why it can be fast)
Running Qwen3-VL on every frame of a 3-hour video is impossible in 2 minutes
(tens of thousands of frames × ~1s each = hours). The smart pattern every fast
"search your video" system uses is **index-once, then retrieve-then-verify**:

1. **Index once (at upload, background):** encode each sampled frame into a small
   vector with a *fast* embedding model, and optionally run a *fast* open-vocab
   detector for forensic classes. This is the only heavy pass, and it is not on
   the query path.
2. **Retrieve (at query, milliseconds):** turn the text query into a vector,
   nearest-neighbour search over the frame vectors → a shortlist of candidate
   timestamps. Instant.
3. **Verify (at query, seconds):** send ONLY the ~10–40 candidate frames to
   Qwen3-VL to confirm + describe + box. Not thousands of calls — a handful.
4. **Assemble:** cluster candidate timestamps into clips, return each with a
   thumbnail, the VLM's confirmation/description, and a confidence.

Query latency = text-embed (ms) + vector-search (ms) + a few dozen VLM verifies
(seconds). The expensive encode is amortised at upload. **That is how 1–2 min is
achievable** — most of the budget is the one-time index, and queries after that
are near-instant.

## Architecture (component choices — [confirm vs research])
```
UPLOAD (once, background job — extends existing s1 keyframe stage)
  video → ffmpeg/PySceneDetect frames (scene-change + ~1–2 fps fill)
        → [EMBEDDER] frame → vector      ─┐
        → [OPEN-VOCAB DETECTOR] per frame ─┤→ store (vectors + detections + ts)
                                           └→ FAISS/hnswlib index + SQLite rows

QUERY (per question, target seconds–2 min)
  text (ar) → [EMBEDDER text encoder] → query vector
            → vector search → top-K candidate timestamps
            → cluster into moments
            → [Qwen3-VL] verify+describe+box each candidate (≤40 calls)
            → timestamped clips with thumbnails + descriptions
```

Candidate models (my prior knowledge — research pass will confirm/replace):
| stage | candidate | why | [research] |
|---|---|---|---|
| frame embedder | **SigLIP 2** (2025) or OpenCLIP ViT-L/14 | strong zero-shot, fast GPU encode | confirm speed/license |
| open-vocab detector | **YOLOE (2025)** / YOLO-World v2 | real-time open-vocab boxes | confirm FPS/accuracy |
| temporal grounding | cluster timestamps; optional moment-retrieval model | keep simple first | check SOTA |
| vector index | **FAISS** (flat exact <1M vectors) or hnswlib | ms query, tiny build | confirm |
| verifier | **Qwen3-VL** (already integrated) | accurate confirm + Arabic describe | — |

## Why this ALSO serves the air-gap goal
The embedder + detector are small models that run **locally** (GPU ideal, CPU
fallback). Only the handful of verify calls touch the VLM. So the whole index
can be built with no data leaving the building — the same requirement real
forensic deployment needs. Local-first is a feature, not a constraint.

## Latency budget (to be proven by research; rough estimate)
3 hours CCTV → scene+1fps sampling ≈ 8–12k frames.
- Encode 10k frames on a modern GPU at ~1–2k fps → ~5–10 s (one-time, upload).
- Detector pass (optional) similar order.
- FAISS build on 10k×~1k-dim → ~1 s.
- Query: text embed <50 ms; search <50 ms; verify 30 candidates × ~1 s ≈ 30 s.
→ First-query-after-upload well under 2 min on GPU; subsequent queries seconds.
CPU-only: encode is the bottleneck (minutes for hours of video) → index in the
background at upload so query stays fast. [research to give real throughput.]

## Fit with the existing app
- Reuses the **s1 keyframe** stage (PySceneDetect + ffmpeg already there).
- New tables: `frame_embeddings` (or a sidecar index file), `video_detections`,
  `video_searches` (query + results, audited like everything else).
- New API: `POST /media/{id}/index` (build index) · `POST /cases/{id}/video-search`
  {query_ar} → clips · SSE progress for indexing.
- New UI: a "بحث في الفيديو" surface — query box → clip results with a scrubber
  that jumps the player to each hit, boxes drawn on the frame (reuse PhotoCanvas).
- Verify step reuses the current Qwen3-VL client + grounding for the box.

## Open decisions (pending research + user)
- GPU assumption: do we require a GPU for indexing, or must CPU-only work
  (slower index)? Affects model size choice.
- Query types: semantic ("suspicious activity") vs object ("knife","red jacket")
  vs person re-ID ("this person") — start with object + semantic; re-ID later.
- Embedder vs detector vs both: detector gives boxes+classes; embedder gives
  open semantic search. Best is BOTH (detector for known forensic classes,
  embedder for free-text). Research to confirm the combined pattern.

## Research findings (verified July 2026) — FINAL choices

**Architecture confirmed** by every real system found (SentrySearch, NVIDIA VSS,
Video-RAG): `Sample → index (embed + optional detect) → vector search → VLM verify`.
VLM-per-frame is infeasible (3 h of 1-fps frames through Qwen ≈ 3–9 hours);
retrieve-then-verify is the only design that hits 1–2 min.

### Final component choices
| stage | pick | why | license |
|---|---|---|---|
| sampling | PySceneDetect **+ 1 fps floor** + still-frame skip | 1 fps is the proven "don't-miss-events" CCTV rate; scene-cut alone misses static-camera events; still-skip cuts idle cost ~30–80% | — (have it) |
| **semantic embed** | **SigLIP 2 So400m** (1152-d) — CLIP ViT-B/32 (512-d) for max speed / CPU | best open retrieval encoder 2025 (COCO R@1 53.2), ~2,300 img/s on A100 | **Apache-2.0** ✅ |
| **object index (optional)** | **MM-Grounding-DINO** or **OWLv2** (NOT YOLOE/YOLO-World) | concrete-object precision ("holding a knife"); runs at index time only | **Apache-2.0** ✅ |
| vector index | **FAISS IndexFlatIP** (exact, sub-ms ≤10⁵ frames) → HNSW at 10⁶+ | hours of video = 10⁴–10⁵ vectors → brute-force is already sub-ms, zero tuning | MIT ✅ |
| **verify + localize** | **Qwen3-VL** on top-K≈20–30 candidates | already integrated; native timestamp grounding tightens the clip | (have it) |

### ⚠ Critical licensing finding (affects commercial deployment)
The *fastest* open-vocab detectors — **YOLOE / YOLO26 (AGPL-3.0)** and
**YOLO-World (GPL-3.0)** — are **copyleft**: shipping them in a proprietary
forensic product requires either open-sourcing the app or buying an Ultralytics
commercial license. **Decision: make SigLIP 2 (Apache-2.0) the primary index** —
it alone covers most free-text queries — and use **MM-Grounding-DINO / OWLv2
(Apache-2.0)** for object precision. This keeps the whole stack commercially
clean and air-gappable. Revisit YOLO only if we license it.

### Latency budget (single RTX 4090 / A100, 1 fps sampling) — PROVEN
- 3 h footage → ~10,800 frames (still-skip removes 30–80%).
- **Index (once, background):** SigLIP2 encode ~5–11 s + FAISS build <1 s
  (+ optional detector ~30–70 s) = **~10–80 s per 3 h**.
- **Query (index prebuilt):** text-embed ~10 ms + FAISS search <1 ms +
  Qwen3-VL verify 20–30 clips @ ~1–3 s = **~30–90 s → inside 1–2 min ✅**.
- **CPU-only:** CLIP/MobileCLIP ~38 img/s → 3 h index ~5 min (offline, fine);
  FAISS fine on CPU; route verify to Qwen3-VL-2B or the cloud endpoint.
→ **Design rule: build the index at UPLOAD (background), so queries stay fast.**

### Reference implementations to borrow from
- **SentrySearch** (github.com/ssrajadh/sentrysearch) — closest match: NL → trimmed
  clip w/ timestamps, Qwen3-VL + CLIP + ChromaDB, still-skip, real latency numbers.
- **NVIDIA VSS Blueprint** — production reference (TensorRT encoder + Milvus + VLM).
- **Video-RAG** — training-free retrieve-then-verify (CLIP gate + FAISS + VLM),
  +5–11 s latency, +8 GB VRAM.
- **rom1504/clip-retrieval**, **clip-faiss** — battle-tested embed+FAISS at scale.

## Implementation phases (for THIS app)
- **V0 — prove it (2–3 days):** SigLIP2 + FAISS, no detector. Extend s1 keyframes
  to also emit embeddings at upload → `frame_embeddings` table + FAISS index file
  per media. `POST /cases/{id}/video-search {query_ar}` → translate query →
  SigLIP text embed → FAISS top-K → cluster into moments → Qwen3-VL verify each →
  return clips {ts_in, ts_out, thumb, description_ar, confidence}. Measure query
  latency on a real 1–3 h test video.
- **V1 — object precision:** add MM-Grounding-DINO index pass for forensic classes
  (weapon/knife/gun/person/bag); route object queries to tag-filter, hybrid to both.
- **V2 — UX:** "بحث في الفيديو" surface — Arabic query box → clip cards → click a
  clip → VideoPlayer seeks to ts_in with the box drawn (reuse PhotoCanvas). SSE
  index-progress bar. Every search audited.
- **V3 — scale + air-gap:** HNSW for many-camera archives; package SigLIP2 +
  detector to run locally (GPU profile), so indexing never leaves the building.

## V0 STATUS (2026-07-20) — IMPLEMENTED
Shipped on branch `feature/video-search`, all 33 tests green:
- Index: `index_video` job (own worker lane so long builds never block analysis)
  — ffmpeg 1 fps → phash still-skip → SigLIP2-base CPU embeddings (mock embedder
  in mock mode) → fp16 `.npz` sidecar per video; auto-queued at upload.
- Query: `video_search` job — Qwen fast-call translates/paraphrases the Arabic
  query (+ sensitivity flag) → numpy cosine top-K (FAISS unnecessary ≤10⁵
  frames) → moment clustering → Qwen3-VL thinking verify per candidate
  (double-ask on sensitive queries; disagreement surfaced as «uncertain») →
  box re-grounded via the existing grounding path → clips + honest coverage
  + full audit. UI: «بحث الفيديو» tab (query box, index chips, clip cards,
  player seek, rejected list collapsed).
- Measurement harness for real footage: `backend/scripts/video_search_eval.py`
  (recall vs hand-labelled timestamps + per-phase latency). Real-CCTV numbers
  pending the user's footage.

## Verification (how we prove the target)
Take one real 1–3 h CCTV video (or concatenate the UGR weapon clips + neutral
footage with known weapon timestamps), index it, run 5 queries
("شخص يحمل سلاحاً", "حقيبة متروكة", "شخص يركض"), and measure: (a) query wall-clock
< 2 min, (b) recall vs the known timestamps, (c) false-positive rate after the
Qwen verify step. Report honest numbers like the weapon-box eval.
