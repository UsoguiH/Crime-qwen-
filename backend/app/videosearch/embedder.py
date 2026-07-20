"""Frame/text embedding for video retrieval.

Real mode: SigLIP2 (Apache-2.0) on CPU — the plan's clean-license pick; torch +
transformers are imported lazily so mock mode and the test suite never need
them. Mock mode: a deterministic hash-based embedder with the same interface so
the whole index→search path runs offline.
"""
import hashlib
import logging
import threading

import numpy as np
from PIL import Image

from app.config import Settings

log = logging.getLogger("athar.videosearch")

_lock = threading.Lock()
_cache: dict[tuple, object] = {}


class MockEmbedder:
    """Deterministic stand-in: images → 8×8 grayscale vector, texts → summed
    per-word hash vectors. No semantic alignment — tests assert mechanics
    (index build, retrieval math, persistence), never ranking quality."""
    name = "mock-embedder"
    dim = 64

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        out = np.zeros((len(images), self.dim), dtype=np.float32)
        for i, im in enumerate(images):
            small = im.convert("L").resize((8, 8), Image.BILINEAR)
            v = np.asarray(small, dtype=np.float32).reshape(-1)
            v -= v.mean()
            out[i] = v
        return _l2(out)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in text.split():
                seed = int.from_bytes(
                    hashlib.sha256(word.lower().encode()).digest()[:8], "big")
                rng = np.random.default_rng(seed)
                out[i] += rng.standard_normal(self.dim).astype(np.float32)
        return _l2(out)


class SiglipEmbedder:
    """SigLIP2 via transformers, CPU inference. Loaded once per process."""

    def __init__(self, model_id: str):
        import torch  # lazy: only real mode needs the heavy deps
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        log.info("loading embedder %s (first use downloads weights)", model_id)
        self.model = AutoModel.from_pretrained(model_id)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.name = model_id
        self.dim = int(self.model.config.text_config.hidden_size)

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        torch = self._torch
        inputs = self.processor(images=[im.convert("RGB") for im in images],
                                return_tensors="pt")
        with torch.no_grad():
            feats = self.model.get_image_features(**inputs)
        return _l2(feats.float().cpu().numpy())

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        torch = self._torch
        # SigLIP text towers are trained on max_length-padded sequences
        inputs = self.processor(text=texts, padding="max_length", max_length=64,
                                truncation=True, return_tensors="pt")
        with torch.no_grad():
            feats = self.model.get_text_features(**inputs)
        return _l2(feats.float().cpu().numpy())


def _l2(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.maximum(norms, 1e-8)


def get_embedder(settings: Settings):
    mode = settings.embedder_mode
    if mode == "auto":
        mode = "mock" if settings.model_mode == "mock" else "real"
    key = (mode, settings.embedder_model)
    with _lock:
        if key not in _cache:
            _cache[key] = (MockEmbedder() if mode == "mock"
                           else SiglipEmbedder(settings.embedder_model))
        return _cache[key]
