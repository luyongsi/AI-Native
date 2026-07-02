"""Embedding interface with hash-based simulation for development."""

import hashlib
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class Embedder:
    """Unified embedding interface.

    In development mode, uses a hash-based simulation that produces
    deterministic 1024-dimensional pseudo-embeddings (no real model needed).

    Production path: replace with sentence-transformers or OpenAI-compatible API.
    """

    def __init__(self, dim: int = 1024, use_real_model: bool = False, model_name: str = ""):
        self.dim = dim
        self.use_real_model = use_real_model
        self.model_name = model_name
        self._model = None
        self._degraded = False

        if use_real_model and model_name:
            self._init_real_model(model_name)
        else:
            print(f"[Embedder] Using hash-based simulation (dim={dim})")

    def _init_real_model(self, model_name: str):
        """Initialize a real sentence-transformers model."""
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(model_name)
            print(f"[Embedder] Loaded real model: {model_name}")
        except Exception as e:
            print(f"[Embedder] Failed to load model '{model_name}': {e}")
            print("[Embedder] Falling back to hash-based simulation")
            self.use_real_model = False
            self._degraded = True

    @property
    def healthy(self) -> bool:
        """Return True if the embedder is working correctly.

        Hash-based embedder is always healthy.
        Real model embedder is healthy only if the model loaded successfully.
        """
        if not self.use_real_model:
            return True
        return self._model is not None

    @property
    def remote_healthy(self) -> bool:
        """Perform a quick health check for remote embedding.

        Hash-based embedder always returns True (no remote dependency).
        For real model, checks that the model is loaded and not degraded.
        """
        if not self.use_real_model:
            return True
        if self._degraded:
            return False
        return self._model is not None

    def _hash_embed(self, text: str) -> List[float]:
        """Generate a deterministic pseudo-embedding from text hash.

        Uses SHA-256 of the text, then expands to `dim` dimensions
        using a simple deterministic pattern. This gives consistent
        results for identical inputs — useful for development/testing.
        """
        text_bytes = text.encode('utf-8')
        digest = hashlib.sha256(text_bytes).digest()

        # Expand 32-byte digest into `dim` floats
        vec = []
        for i in range(self.dim):
            # Use different byte positions with wrapping
            base = digest[i % 32] / 255.0
            offset = digest[(i + 7) % 32] / 255.0
            val = (base * 2.0 - 1.0) + (offset * 0.1 - 0.05)  # range ~[-1.05, 1.05]
            vec.append(val)
        return vec

    def embed(self, text: str) -> List[float]:
        """Embed a single text into a vector.

        Never raises — falls back to hash-based embedding on any error.
        """
        try:
            if self.use_real_model and self._model:
                return self._model.encode(text).tolist()
            return self._hash_embed(text)
        except Exception as e:
            logger.error(f"[Embedder] embed() failed, degrading to hash-based: {e}")
            self._degraded = True
            self.use_real_model = False
            return self._hash_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts.

        Never raises — falls back to hash-based embedding on any error.
        """
        try:
            if self.use_real_model and self._model:
                return self._model.encode(texts).tolist()
            return [self._hash_embed(t) for t in texts]
        except Exception as e:
            logger.error(f"[Embedder] embed_batch() failed, degrading to hash-based: {e}")
            self._degraded = True
            self.use_real_model = False
            return [self._hash_embed(t) for t in texts]

    def embed_with_fallback(self, text: str) -> Tuple[List[float], bool]:
        """Embed text with automatic fallback to hash-based on failure.

        Returns:
            (embedding_vector, used_fallback) — used_fallback is True
            if the primary method failed and hash-based was used instead.
        """
        try:
            if self.use_real_model and self._model:
                result = self._model.encode(text).tolist()
                return (result, False)
            return (self._hash_embed(text), False)
        except Exception as e:
            logger.error(f"[Embedder] embed_with_fallback() failed, using hash fallback: {e}")
            self._degraded = True
            self.use_real_model = False
            return (self._hash_embed(text), True)

    def embed_batch_with_fallback(self, texts: List[str]) -> Tuple[List[List[float]], bool]:
        """Embed a batch of texts with automatic fallback to hash-based on failure.

        Returns:
            (embedding_vectors, used_fallback) — used_fallback is True
            if the primary method failed and hash-based was used instead.
        """
        try:
            if self.use_real_model and self._model:
                result = self._model.encode(texts).tolist()
                return (result, False)
            return ([self._hash_embed(t) for t in texts], False)
        except Exception as e:
            logger.error(f"[Embedder] embed_batch_with_fallback() failed, using hash fallback: {e}")
            self._degraded = True
            self.use_real_model = False
            return ([self._hash_embed(t) for t in texts], True)


# Singleton convenience
_default_embedder: Embedder = None


def get_embedder(dim: int = 1024, use_real_model: bool = False, model_name: str = "") -> Embedder:
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = Embedder(dim=dim, use_real_model=use_real_model, model_name=model_name)
    return _default_embedder
