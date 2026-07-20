"""Video-search core math: embedder determinism, sidecar round-trip,
top-k retrieval, moment clustering, sensitivity fallback."""
import numpy as np
from PIL import Image

from app.videosearch.embedder import MockEmbedder
from app.videosearch.indexer import sidecar_load, sidecar_save
from app.videosearch.search import (cluster_moments, fallback_sensitive,
                                     select_candidates, topk_frames)


def test_mock_embedder_deterministic_and_normalized():
    e = MockEmbedder()
    img = Image.new("RGB", (64, 48), (200, 30, 30))
    img.paste((0, 0, 0), (0, 0, 32, 48))
    a = e.embed_images([img, img])
    b = e.embed_images([img])
    assert a.shape == (2, e.dim)
    assert np.allclose(a[0], a[1]) and np.allclose(a[0], b[0])
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)

    t1 = e.embed_texts(["knife on the table"])
    t2 = e.embed_texts(["knife on the table"])
    t3 = e.embed_texts(["a running person"])
    assert np.allclose(t1, t2)
    assert not np.allclose(t1, t3)
    assert np.allclose(np.linalg.norm(t1, axis=1), 1.0, atol=1e-5)


def test_sidecar_roundtrip(tmp_path):
    rng = np.random.default_rng(7)
    vecs = rng.standard_normal((10, 16)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    ts = [i * 0.5 for i in range(10)]
    path = tmp_path / "x.npz"
    sidecar_save(path, vecs, ts, {"embedder": "test", "dim": 16})
    v2, t2, meta = sidecar_load(path)
    assert v2.shape == (10, 16)
    assert np.allclose(v2, vecs, atol=2e-3)          # float16 quantization
    assert np.allclose(np.linalg.norm(v2, axis=1), 1.0, atol=1e-5)
    assert list(t2) == ts
    assert meta["embedder"] == "test"


def test_topk_frames_ranks_planted_target():
    rng = np.random.default_rng(3)
    vectors = rng.standard_normal((100, 32)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    target = vectors[42]
    ts = np.arange(100, dtype=np.float32)
    hits = topk_frames(vectors, ts, target[None, :], k=5)
    assert hits[0][0] == 42.0
    assert hits[0][1] > 0.99
    # score is max over variants: adding an orthogonal-ish variant keeps the hit
    variants = np.stack([target, vectors[7]])
    hits2 = topk_frames(vectors, ts, variants, k=5)
    top_ts = {h[0] for h in hits2}
    assert {42.0, 7.0} <= top_ts
    assert topk_frames(np.zeros((0, 32), np.float32), ts[:0], target[None, :], 5) == []


def test_cluster_moments_merges_and_caps():
    cands = [(1.0, 0.5), (2.0, 0.9), (3.5, 0.4),      # one moment (gaps ≤ 2s)
             (10.0, 0.7),                              # separate moment
             (20.0, 0.3), (21.0, 0.2)]                # third moment
    moments = cluster_moments(cands, gap_s=2.0, budget=10)
    assert len(moments) == 3
    best = moments[0]
    assert (best["ts_start"], best["ts_end"], best["ts_best"]) == (1.0, 3.5, 2.0)
    assert best["score"] == 0.9
    assert [m["score"] for m in moments] == [0.9, 0.7, 0.3]
    assert len(cluster_moments(cands, gap_s=2.0, budget=2)) == 2
    assert cluster_moments([], 2.0, 5) == []


def test_select_candidates_spreads_across_time():
    # dense candidates 0.5s apart across 10s; must pick spread ≥2s apart, top-score
    cands = [(t / 2.0, 1.0 - t * 0.01) for t in range(20)]  # ts 0..9.5s
    picked = select_candidates(cands, min_gap_s=2.0, budget=24)
    ts = [p[0] for p in picked]
    assert ts == sorted(ts)                      # chronological
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    assert all(g >= 2.0 for g in gaps)           # spacing enforced
    assert len(ts) >= 4                          # ~5 points across 10s, not 1
    # budget caps the count
    assert len(select_candidates(cands, 0.1, 3)) == 3
    # highest score always kept
    assert picked[0][0] == 0.0
    assert select_candidates([], 2.0, 5) == []


def test_fallback_sensitive_keywords():
    assert fallback_sensitive("أين يظهر السكين؟")
    assert fallback_sensitive("person holding a gun")
    assert not fallback_sensitive("سيارة حمراء في الموقف")
