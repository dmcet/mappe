"""Semantic similarity between the CV and job listings, with a local embedding model.

No API calls: the ONNX model (fastembed) is baked into the Docker image and loaded from
disk. Vectors are stored per listing, so a listing is embedded once, not once per search.
If the model can't be loaded, ranking falls back to keywords only.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np

from mappe.config import SearchConfig
from mappe.domain.models import ParsedCV
from mappe.search.models import JobHit

log = logging.getLogger(__name__)

# Typical cosine similarities CV <-> listing for each model, measured on live listings:
# unrelated jobs sit near the low end, close matches near the high end.
CALIBRATION = {
    "jinaai/jina-embeddings-v2-base-de": (0.40, 0.70),
    "minishlab/potion-multilingual-128M": (0.15, 0.60),
}
BATCH = 16


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class FastEmbedder:
    def __init__(self, name: str, cache_dir: str | None) -> None:
        from fastembed import TextEmbedding

        self.name = name
        # Never download at runtime: the image ships the model (see Dockerfile).
        self._model = TextEmbedding(name, cache_dir=cache_dir, local_files_only=True)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return np.array(list(self._model.embed(list(texts), batch_size=BATCH)), dtype=np.float32)


_lock = threading.Lock()
_loaded: dict[str, Embedder | None] = {}
_errors: dict[str, str] = {}


def model_cache_dir() -> str | None:
    return os.environ.get("FASTEMBED_CACHE_PATH")


def get_embedder(cfg: SearchConfig) -> Embedder | None:
    """The configured model, loaded once; None when disabled or unavailable."""
    if not cfg.semantic:
        return None
    with _lock:
        if cfg.semantic_model not in _loaded:
            try:
                _loaded[cfg.semantic_model] = FastEmbedder(cfg.semantic_model, model_cache_dir())
            except Exception as exc:  # missing model, broken install: keywords still work
                log.warning("Semantic ranking unavailable (%s): %s", cfg.semantic_model, exc)
                _loaded[cfg.semantic_model] = None
                _errors[cfg.semantic_model] = f"{type(exc).__name__}: {exc}"[:200]
        return _loaded[cfg.semantic_model]


def unavailable_reason(cfg: SearchConfig) -> str | None:
    if not cfg.semantic:
        return "turned off in config.toml"
    return _errors.get(cfg.semantic_model)


def cv_text(cv: ParsedCV) -> str:
    """What the CV is about: headline, roles with their bullets and technologies, skills."""
    parts = [cv.headline or ""]
    for p in cv.positions[:4]:
        bullets = "; ".join(f.text for f in p.responsibilities + p.achievements)
        tech = ", ".join(p.technologies)
        parts.append(f"{p.role} ({p.company}): {bullets}" + (f" [{tech}]" if tech else ""))
    if cv.skills:
        parts.append("Skills: " + ", ".join(s.name for s in cv.skills))
    return "\n".join(x for x in parts if x)


def hit_text(hit: JobHit, chars: int) -> str:
    # Title-only hits (Bundesagentur) still carry their occupations as context.
    body = hit.description[:chars] if hit.description else ", ".join(hit.tags)
    return f"{hit.title}\n{hit.company or ''}\n{body}".strip()


def text_key(model: str, text: str) -> str:
    return f"{model}:{hashlib.sha1(text.encode()).hexdigest()[:16]}"


def to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float16).tobytes()


def from_bytes(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float16).astype(np.float32)


def _unit(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(norm == 0, 1, norm)


def fit(similarity: float, model: str) -> float:
    """Cosine similarity -> 0..1 with the model's calibration."""
    low, high = CALIBRATION.get(model, (0.3, 0.7))
    return float(min(1.0, max(0.0, (similarity - low) / (high - low))))


def similarities(
    embedder: Embedder,
    cv: ParsedCV,
    hits: list[JobHit],
    cached: dict[str, tuple[str, bytes]],
    chars: int,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, float], dict[str, tuple[str, bytes]]]:
    """Fit (0..1) per hit key, plus the vectors computed now (key -> (text key, bytes)).

    ``cached`` maps hit keys to stored (text key, vector); a vector is reused only when the
    text key matches, i.e. same model and same listing text.
    """
    query = _unit(embedder.embed([cv_text(cv)])[0])
    keys = {h.key: text_key(embedder.name, hit_text(h, chars)) for h in hits}
    vectors: dict[str, np.ndarray] = {}
    missing = []
    for h in hits:
        stored = cached.get(h.key)
        if stored and stored[0] == keys[h.key]:
            vectors[h.key] = from_bytes(stored[1])
        else:
            missing.append(h)

    fresh: dict[str, tuple[str, bytes]] = {}
    for start in range(0, len(missing), BATCH):
        batch = missing[start : start + BATCH]
        for h, v in zip(batch, embedder.embed([hit_text(h, chars) for h in batch]), strict=True):
            vectors[h.key] = v
            fresh[h.key] = (keys[h.key], to_bytes(v))
        if progress:
            progress(min(start + BATCH, len(missing)), len(missing))

    sims = {k: fit(float(_unit(v) @ query), embedder.name) for k, v in vectors.items()}
    return sims, fresh
