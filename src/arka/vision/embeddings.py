"""Optional CLIP-style image/text embeddings for relevance scoring."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_CLIP_MODEL = "sentence-transformers/clip-ViT-B-32"


@dataclass(frozen=True)
class EmbeddingBackend:
    name: str
    model_id: str


def _model_name() -> str:
    return (os.environ.get("ARKA_IMAGE_FILTER_CLIP_MODEL") or DEFAULT_CLIP_MODEL).strip()


def _load_sentence_transformers(model_id: str) -> Any | None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    try:
        return SentenceTransformer(model_id)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("sentence-transformers CLIP load failed: %s", exc)
        return None


def _load_transformers_clip(model_id: str) -> tuple[Any, Any, Any] | None:
    try:
        from transformers import CLIPModel, CLIPProcessor
    except ImportError:
        return None
    try:
        model = CLIPModel.from_pretrained(model_id)
        processor = CLIPProcessor.from_pretrained(model_id)
        return model, processor, None
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("transformers CLIP load failed: %s", exc)
        return None


class ClipEmbedder:
    """Lazy CLIP embedder with sentence-transformers or transformers fallback."""

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or _model_name()
        self._st_model: Any | None = None
        self._tf_bundle: tuple[Any, Any, Any] | None = None
        self.backend: EmbeddingBackend | None = None

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    def _ensure_loaded(self) -> bool:
        if self.backend is not None:
            return True
        st = _load_sentence_transformers(self.model_id)
        if st is not None:
            self._st_model = st
            self.backend = EmbeddingBackend("sentence-transformers", self.model_id)
            return True
        tf = _load_transformers_clip(self.model_id)
        if tf is not None:
            self._tf_bundle = tf
            self.backend = EmbeddingBackend("transformers", self.model_id)
            return True
        return False

    def embed_text(self, text: str) -> np.ndarray:
        if not self._ensure_loaded():
            raise RuntimeError(
                "CLIP unavailable. Install optional deps: "
                "pip install 'arka-agent[image-filter]' or sentence-transformers"
            )
        text = text.strip()
        if self._st_model is not None:
            vec = self._st_model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            return np.asarray(vec, dtype=np.float32)
        model, processor, _ = self._tf_bundle  # type: ignore[misc]
        import torch

        inputs = processor(text=[text], return_tensors="pt", padding=True)
        with torch.no_grad():
            vec = model.get_text_features(**inputs)
        vec = vec / vec.norm(dim=-1, keepdim=True)
        return vec.squeeze(0).cpu().numpy().astype(np.float32)

    def embed_image_path(self, path: str | Path) -> np.ndarray:
        if not self._ensure_loaded():
            raise RuntimeError("CLIP unavailable")
        path = Path(path)
        if self._st_model is not None:
            from PIL import Image

            img = Image.open(path).convert("RGB")
            vec = self._st_model.encode(img, convert_to_numpy=True, normalize_embeddings=True)
            return np.asarray(vec, dtype=np.float32)
        model, processor, _ = self._tf_bundle  # type: ignore[misc]
        import torch
        from PIL import Image

        img = Image.open(path).convert("RGB")
        inputs = processor(images=img, return_tensors="pt")
        with torch.no_grad():
            vec = model.get_image_features(**inputs)
        vec = vec / vec.norm(dim=-1, keepdim=True)
        return vec.squeeze(0).cpu().numpy().astype(np.float32)

    def embed_image_paths(self, paths: list[str | Path]) -> list[np.ndarray]:
        return [self.embed_image_path(p) for p in paths]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def batch_centroid(embeddings: list[np.ndarray]) -> np.ndarray:
    if not embeddings:
        raise ValueError("embeddings must not be empty")
    stack = np.stack([np.asarray(e, dtype=np.float32).ravel() for e in embeddings], axis=0)
    centroid = stack.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm > 0:
        centroid = centroid / norm
    return centroid.astype(np.float32)


def z_scores(values: list[float]) -> list[float]:
    if len(values) < 2:
        return [0.0] * len(values)
    arr = np.asarray(values, dtype=np.float64)
    std = float(arr.std())
    if std <= 1e-9:
        return [0.0] * len(values)
    mean = float(arr.mean())
    return [float((v - mean) / std) for v in values]


def isolation_outliers(embeddings: list[np.ndarray], *, contamination: float = 0.1) -> list[bool]:
    """Flag outliers via IsolationForest when sklearn is available, else z-score on norms."""
    if len(embeddings) < 3:
        return [False] * len(embeddings)
    matrix = np.stack([np.asarray(e, dtype=np.float32).ravel() for e in embeddings], axis=0)
    try:
        from sklearn.ensemble import IsolationForest

        clf = IsolationForest(contamination=min(max(contamination, 0.01), 0.5), random_state=42)
        preds = clf.fit_predict(matrix)
        return [p == -1 for p in preds]
    except ImportError:
        centroid = batch_centroid(embeddings)
        dists = [1.0 - cosine_similarity(e, centroid) for e in embeddings]
        zs = z_scores(dists)
        return [abs(z) >= 2.0 for z in zs]


def average_hash(path: str | Path, *, hash_size: int = 8) -> str:
    """Simple perceptual hash fallback when CLIP is unavailable."""
    from PIL import Image

    img = Image.open(path).convert("L").resize((hash_size, hash_size))
    pixels = list(img.get_flattened_data())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return format(int(bits, 2), f"0{hash_size * hash_size // 4}x")


def hamming_distance_hex(a: str, b: str) -> int:
    ia, ib = int(a, 16), int(b, 16)
    return (ia ^ ib).bit_count()
