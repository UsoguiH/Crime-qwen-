# Video-Search Method Ladder — iterate until no rung beats the previous
> Rank each method on **SMART** (recall / never-miss, temporal + relational
> understanding, auditability — the forensic priority) and **SPEED** (query
> latency; index cost noted separately since it's a one-time background job).
> A rung is kept only if it beats the rung below on at least one axis without
> collapsing the other. We stop when the next rung can't strictly improve the
> Pareto frontier. Scores /10; "index" = one-time build, "query" = per-search.

## The ladder (draft v1 — from established methods; frontier research pending)

### v1 — VLM on every frame (naive "maximum smart")
Run Qwen3-VL on every sampled frame, ask "is X here?".
- SMART 8 · SPEED **1** (query = hours). Single-frame reasoning, no temporal.
- Verdict: correct-but-unusable. The thing every later rung must beat on speed.

### v2 — Retrieve-then-verify (CLIP/SigLIP embed + FAISS + VLM verify)
Index frames as vectors once; query → vector search → VLM verifies ~30 candidates.
- SMART 6 · SPEED 8. **Beats v1 on speed massively.** Weakness: single-frame CLIP
  retrieval can MISS fine-grained/relational cases ("holding" vs "knife present"),
  and the retrieval gate is a single point of failure → misses = forensic no-no.

### v3 — Multi-signal fusion (embed + open-vocab detector + VLM verify)
Add an independent open-vocab detector as a 2nd recall path; union the candidates.
- SMART 7.5 · SPEED 7.5. **Beats v2 on smart** (two independent recall paths →
  fewer misses; detector nails concrete objects CLIP is weak on) at small index cost.
- The forensic "no single point of failure" principle starts here.

### v4 — Video-native embeddings (clip embeddings + detector + VLM verify)
Replace/augment frame-CLIP with CLIP-embeddings that encode short clips
(motion/action), so "person swinging a knife" is retrievable, not just "knife".
- SMART 8.5 · SPEED 7. **Beats v3 on smart** (temporal/action understanding —
  catches events a single frame can't) at a modest encode cost.

### v5 — Object tracking + re-ID tracklets (+ video embed + detector + verify)
Track every object/person across frames (modern MOT + re-ID). An object seen once
is followed through occlusion; a 1-second appearance becomes a tracked span;
"find THIS weapon/person everywhere" becomes a tracklet lookup.
- SMART 9 · SPEED 6.5 (index heavier; near real-time on GPU). **Beats v4 on smart**
  (occlusion recovery + re-ID + brief events extended → materially fewer misses).

### v6 — Structured event graph (caption+detect+track → spatio-temporal graph)
Build ONE exhaustive structured index: every object/person/action/relation with
timestamps → a graph/DB. Queries become exhaustive lookups that structurally
**cannot miss an indexed event**, support relational queries ("person hands
object to another"), and are fully auditable (why each hit exists).
- SMART 9.5 · SPEED query **9** / index 4. **Beats v5**: exhaustive + relational +
  auditable, and QUERY is instant (graph lookup). Cost is a heavy one-time index
  — but that runs in the background at upload, off the query path.

### v7 — Agentic search over the structured index (LLM plans + zooms + self-checks)
An agent orchestrates graph + embeddings + detector + VLM, decomposing complex
queries ("who entered before the alarm and left with a bag"), zooming into
candidates, and self-verifying.
- SMART 9.5–10 (complex multi-hop reasoning, self-correction) · SPEED 6 (several
  planning rounds). **Beats v6 only for COMPLEX queries**; overkill for simple ones.

## Current reading of the frontier (Pareto)
Smart↔Speed trade off, so the "winner" is the Pareto-optimal HYBRID, not one rung:
**structured event-graph index (v6, exhaustive = never-miss) built in the
background, with fast graph+vector retrieval + VLM verify, and the agentic layer
(v7) invoked only for complex queries.** Simple object/action queries take the
fast v3–v5 path; hard relational/multi-hop queries escalate to v7. This looks
like the convergence point (fast query + exhaustive smart + auditable), but the
frontier-research pass may surface a rung I'm missing → will extend/replace.

### v8 — Multimodal exhaustive index (vision + AUDIO + text/OCR + identity)
Add the modalities vision alone misses: audio event detection (gunshot, scream,
breaking glass), speech→text (Whisper), on-screen OCR (plates, IDs, timestamps
burned into CCTV). Fuse with the visual event graph.
- SMART 9.7 · SPEED query 9 / index 4. **Beats v7 on smart** — catches events
  outside the visual frame (an off-camera gunshot, a spoken threat, a plate) that
  NO vision-only method can. For forensics this closes real blind spots.

### v9 — Streaming index built DURING ingest (online VLM + streaming memory)
Instead of "upload, then index," build the index in a single online pass AS the
video ingests (streaming VLM + rolling memory). The index is ready the instant
upload finishes — the one-time build stops being a separate wait.
- SMART 9.7 · SPEED index **7** (folded into ingest) / query 9. **Beats v8 on
  effective speed** — removes the post-upload index wait; same smartness.

### v10 — Learned coarse-to-fine gating (cheap model decides what deserves deep analysis)
A tiny always-on model scores every frame's "forensic salience"; only salient
spans get the expensive embed/detect/track/graph treatment, the rest get a light
footprint. Recall is preserved by tuning the gate toward over-inclusion.
- SMART 9.7 · SPEED index **9** / query 9. **Beats v9 on index speed** at equal
  smart — the exhaustive treatment runs only where it matters, so hours of idle
  CCTV cost almost nothing. This is how you index massive archives cheaply.

### v11 — Systems/hardware optimum (quantized encoders, GPU-batched, FAISS-GPU, KV reuse)
Not a new idea — pure engineering: TensorRT/INT8 encoders, batched multi-stream
decode (DeepStream), FAISS-GPU/cuVS, VLM KV-cache reuse across candidate verifies.
- SMART 9.7 (unchanged) · SPEED index 9.5 / query 9.5. **Beats v10 on raw speed**
  with no smartness loss — squeezes the constant factors to the metal.

### v12 — THE FRONTIER: exhaustive streaming multimodal event-graph, hybrid-retrieved,
### self-consistently verified, agentically escalated, honestly bounded
Everything above, unified:
- **Index (one streaming pass during ingest, learned-gated, GPU-optimized):**
  vision event graph (objects/actions/relations/tracklets/re-ID) + audio events +
  speech + OCR + multimodal clip embeddings → structured + vector + sparse index.
- **Query (instant):** hybrid dense (embeddings) + sparse (tags/graph) + structured
  (relations/time) retrieval → O(log n) lookup, cast wide for recall.
- **Verify:** best reasoning VLM, self-consistent (double-check), shows reasoning + box.
- **Escalate:** agentic multi-hop reasoning only for complex relational queries.
- **Bound:** honest coverage statement + confidence + mandatory human confirmation
  + full audit chain. Never concludes; never claims "nothing there," only "nothing
  found at this coverage."
- SMART **10** · SPEED index 9.5 / query 9.5.

## Why v12 is the ceiling — no technique on Earth beats it (the convergence proof)
Both axes are at their theoretical floor; remaining gains are *base-model* quality,
which is exogenous to the METHOD and plugs into this same architecture unchanged.

**SPEED is at the complexity floor.**
- Index: you must read each frame's information **at least once** to represent it —
  that's a lower bound of one pass. v12 does exactly one streaming pass (learned
  gating only lightens it). You cannot index in less than one pass.
- Query: answering an *arbitrary* natural-language query requires consulting the
  index; a prebuilt hybrid index answers in **O(log n)** (vector/graph lookup).
  The only way to be faster is to precompute the answer — impossible for an
  open/unbounded query set (you'd need to pre-answer every possible question).
  So query is at its information-theoretic floor too.

**SMART is at the representational floor.**
- A method can only find what its index can *represent*. v12 indexes **every
  modality** (vision + audio + speech + text + identity + relation + time) — there
  is no further modality a camera+mic capture to add. Nothing observable is
  un-representable, so recall is bounded only by the base models' perception, not
  by the architecture.
- Reasoning uses the **best available model with self-verification**; you cannot
  reason "more correctly" than best-model + cross-check + honest-uncertainty
  without a *better model*.
- The forensic safety ceiling (never-miss bias + human-in-loop + audit + honest
  coverage) is already maximal — you cannot be *more* careful than "surface every
  candidate, decide nothing, record everything, state your blind spot."

**Therefore:** any "faster" technique would have to break the one-pass-index or
O(log n)-query floor (impossible), and any "smarter" technique would need a
modality that doesn't exist or a base model better than the best one — which,
when it arrives, drops into v12 unchanged. **v12 is Pareto-optimal at the physical
frontier; the architecture converges here.** Further improvement = better base
models, not a better method.

## Practical takeaway (what to actually build first)
The frontier (v12) is the *target architecture*, but you don't build it all at
once. The Pareto-smart *starting* point that already beats everything simple:
**v3 (embed + detector + VLM-verify)** for a shippable prototype, on the path to
**v6 (event-graph index)** as the durable core, adding audio/OCR (v8) and learned
gating (v10) for scale. Each is a real rung you can ship and measure.

═══════════════════════════════════════════════════════════════════════
## ⚠ CORRECTED BY FRONTIER RESEARCH (July 2026) — supersedes v1–v12 above
═══════════════════════════════════════════════════════════════════════
The research overturned the key assumption in my v6/v12 reasoning. I was **wrong**
that a "structured event-graph = can't miss." Honest correction, with evidence:

**THE reframing insight: a miss happens at the PERCEPTION / sampling front-end —
never at the index or the query stage.** "Exhaustive DB lookup" only guarantees
completeness *given a perfect index*, and the index is NEVER perfect because the
model that built it sampled sparsely or summarized lossily. Proof: video
scene-graph generation recovers only **~26% of relations (74% missed)** on Action
Genome and its vocabulary has **no weapon/violence class at all**. So the
event-graph is LOSSIER, not safer.

**Consequence — my baseline was underrated:** a per-frame open-vocab detector
*prompted specifically for "knife/gun" at high frame-rate* has **denser temporal
coverage than any chunk-sampled captioner or 8-frame clip encoder**. For raw
object recall it is the **strongest design in the field** — caption/graph
pipelines are downstream of it and lose information. So the ladder is NOT
"replace the baseline with something smarter"; it is **"keep the baseline as the
recall net and ADD layers that cover its specific blind spots."**

Also sobering: **no system in the entire survey publishes recall on weapons or
violent acts in real footage.** That evaluation gap is itself the finding — which
is exactly why our UGR-weapon-style measured eval matters.

### The corrected ladder — ADDITIVE layers (stack, don't swap), with real models
Each layer closes a *proven* blind spot of the baseline. Scores: SMART = never-miss
+ temporal/relational; SPEED = query/index. License matters (commercial forensic).

**L0 — Baseline (KEEP): per-frame open-vocab detector + SigLIP/FAISS + Qwen3-VL verify.**
Recall champion for OBJECTS; blind to actions-over-time, missed re-appearances,
relational queries, and slow to verify at hours-scale. Clean licenses.

**L1 — Video-native clip encoder (+ short windows).** Closes the **action/motion**
gap ("swinging a knife", "running") — benchmarked (cross-frame X-CLIP 0.470 vs
frame SigLIP 0.325; SSv2 77–88%). *Cheapest SMART upgrade, drop-in to FAISS.*
Pick: **PE-Core-L (Apache-2.0)** or **Cosmos-Embed1 (NVIDIA-open, has a
surveillance anomaly fine-tune)**; InternVideo2-6B if compute allows; Marengo only
if footage may leave (API-only — chain-of-custody risk). SMART ★★★ · SPEED moderate.

**L2 — Open-vocab ACTION + ANOMALY channel (parallel).** Makes events first-class,
not inferred from objects — the highest-value forensic add ("a fight" is an action,
not an object). Open-vocab TAL is still weak (~34 novel mAP), so lean on
**anomaly detectors: π-VAD (UCF-Crime AUC 90.33, XD-Violence 85.37, ~30 FPS RGB),
OVVAD (names unseen anomaly types), VadCLIP**. SMART ★★★★ · SPEED near-real-time.

**L3 — Tracking + re-ID + prompt-propagation.** An object seen ONCE is propagated
across occlusions/gaps (ByteTrack 2nd-association, OC-SORT re-linking, StrongSORT
GSI gap-fill) and "find THIS weapon/person everywhere" becomes a concept/tracklet
query. Pick: **MASA (Apache-2.0)** bolt-on to our detector NOW; **SAMURAI
(Apache-2.0)** for single-instance propagation; **SAM3 concept-prompt** is the
ideal "segment+track ALL instances of a phrase" fit but its **custom SAM License
needs legal review**. Caveat: interpolation can HALLUCINATE an object into a frame
→ **every recovered frame must pass Qwen3-VL verify.** SMART ★★★★ · SPEED real-time-ish.
(Avoid StrongSORT=GPL, BoxMOT=AGPL for a proprietary product.)

**L4 — Streaming single-pass indexer (SPEED at hours-scale).** One 8–17 FPS pass
builds a dense searchable trace of the whole video at bounded cost. Pick:
**StreamingVLM (MIT, >2h stable, 8 FPS/H100)** or **Flash-VStream (Apache-2.0,
constant memory)**. The lossless ideal **ReKV is license-blocked (no LICENSE
file)**. Caveat: lossy memory can evict a brief event → this is a FAST COARSE
layer, **never the safety net**. SMART ★★ (coarse) · SPEED ★★★★★.

**L5 — Agentic verifier / self-verifying temporal search (SELECTIVE).** Catches
misses a single pass leaves and answers **relational/multi-hop** queries ("who
held the weapon *before* the fight"). Pick: **VideoMind (BSD-3) Planner→Grounder→
Verifier→Answerer** pattern; **TimeSearch-R** RL search with a *Completeness
Self-Verification* reward (the most "reduce-misses"-shaped 2025 method, +4.1
LongVideoBench); **VideoChat-R1** for pinpoint localization (Charades mIoU 60.8 vs
29.0). Cost: 2–10+ model calls/query, high latency (rarely benchmarked) → reserve
for high-stakes queries + candidate re-checks, NOT the first-pass scan.
SMART ★★★★★ · SPEED slow.

**Orthogonal — event/knowledge-graph (VSS / HKU-VideoRAG).** Buys **relational
query expressiveness + cheap summaries** over the corpus, NOT never-miss. Feed it
the OUTPUTS of L0–L3 (detections, tracklets, actions), so the graph inherits the
detector's higher recall instead of a lossy caption. Never the miss-proof layer.

## The REAL convergence — where no technique can be smarter or faster (corrected)
The ceiling is **NOT a perfect exhaustive index** (impossible — perception is
lossy). The true frontier is:
- **SMART ceiling = maximize PERCEPTION coverage**: dense sampling (adaptive fps,
  bumped on motion) × the best detectors across **every modality** (objects,
  actions/anomaly, audio-gunshot/speech, OCR, identity/tracklets), each an
  independent recall path, unioned wide, then verified by the best reasoning VLM
  with self-consistency + honest coverage bounds + mandatory human confirmation.
  You cannot find what no sensor+model perceives — recall is bounded by
  perception, and perception is bounded by the **base models**, which are
  exogenous. When a better detector/VLM ships, it drops into this same stack.
- **SPEED ceiling = one streaming index pass (you must observe each moment ≥once)
  + O(log n) hybrid retrieval at query.** Both at their complexity floor; faster
  is impossible for open-vocabulary queries.

So the architecture converges to **"L0 recall-net + L1 actions + L2 anomaly +
L3 tracklets, indexed in one streaming pass (L4) with adaptive sampling, hybrid-
retrieved, selectively agent-verified (L5), graph-organized for relational
queries, human-confirmed, audited."** No *method* beats this — only better
**base models** do, and they plug in unchanged. **That is the honest ceiling:
perception-bound, not index-bound.** My earlier "perfect graph = never-miss"
(v6/v12) was wrong; this corrects it.

## Clean-license buildable set (commercial forensic)
Apache/MIT/BSD: PE-Core, Cosmos-Embed1, MASA, SAMURAI, ByteTrack, OC-SORT,
Deep-OC-SORT, StreamingVLM, Flash-VStream, VideoMind, STTran, CLIP-ReID, Whisper,
FAISS, π-VAD (verify repo). Legal-review/avoid: SAM3 (custom license), StrongSORT
(GPL), BoxMOT (AGPL), ImageBind/Dispider (NC), ReKV (no license), Marengo (API
egress). → A fully clean-license, air-gappable stack is achievable.

## Build order (unchanged, now evidence-backed)
Ship **L0** (already 80% built) → add **L1** (biggest cheap SMART win: catch
actions) → **L2** anomaly channel → **L3** MASA tracklets → **L4** streaming for
scale → **L5** agentic verify selectively. Measure recall on real weapon footage
at each step (the eval gap the whole field has).