"""
k14/artifact_vectorizer.py — K14 sub-module: Artifact Vectorization

Simulates embedding generation and pgvector storage for artifact content.
In Phase 3 this would call a real embedding model (e.g., text-embedding-3-large
or a local SentenceTransformer) and perform actual pgvector inserts.

Usage:
    vectorizer = ArtifactVectorizer()
    result = await vectorizer.vectorize(artifact_dict)
    batch_result = await vectorizer.batch_vectorize([a1, a2, a3])
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMBEDDING_DIM = 1024  # Matches vector(1024) in knowledge_chunks schema
DEFAULT_CHUNK_SIZE = 512  # tokens per chunk (approximate)

# ---------------------------------------------------------------------------
# ArtifactVectorizer
# ---------------------------------------------------------------------------


class ArtifactVectorizer:
    """Simulates text-to-vector embedding and pgvector storage.

    In Phase 2 this is a functional stub that generates deterministic mock
    embeddings and returns storage confirmation.  Phase 3 replaces the mock
    embedding call with a real model and performs actual DB writes.

    Attributes:
        _total_vectorized: Running count of chunks vectorized this session.
        _db_available: Whether the simulated pgvector backend is reachable.
    """

    def __init__(self) -> None:
        self._total_vectorized: int = 0
        self._db_available: bool = True  # Phase 2: always "available"
        logger.info("ArtifactVectorizer initialized (Phase 2 stub mode)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def vectorize(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Vectorize a single artifact into one or more chunks.

        Args:
            artifact: Dict with keys ``id``, ``type``, ``content`` / ``metadata``.

        Returns:
            Dict with keys:
                chunk_id (str):     UUID of the created chunk.
                embedding_dim (int): Vector dimensionality (1024).
                tokens (int):       Approximate token count of the content.
                stored (bool):      Whether the chunk was persisted.
                vector_db (str):    Backend used ("pgvector").
        """
        if not artifact:
            logger.warning("vectorize called with empty artifact — returning zero-result")
            return {
                "chunk_id": "",
                "embedding_dim": EMBEDDING_DIM,
                "tokens": 0,
                "stored": False,
                "vector_db": "pgvector",
            }

        artifact_id = artifact.get("id", str(uuid.uuid4()))
        artifact_type = artifact.get("type", "unknown")
        content = self._extract_content(artifact)

        # Simulate token count (rough heuristic: 4 chars ~= 1 token)
        token_count = max(1, len(content) // 4)

        # Phase 2: generate a deterministic mock embedding via hash
        # Phase 3 would replace this with a real embedding model call.
        _embedding = self._mock_embed(content)

        # Simulate pgvector insert
        chunk_id = f"chunk:{artifact_type}:{artifact_id}:{uuid.uuid4().hex[:8]}"
        stored = self._simulate_store(chunk_id, artifact_type, content, token_count)

        if stored:
            self._total_vectorized += 1

        logger.info(
            "Vectorized artifact %s (%s) → chunk=%s tokens=%d stored=%s",
            artifact_id,
            artifact_type,
            chunk_id,
            token_count,
            stored,
        )

        return {
            "chunk_id": chunk_id,
            "embedding_dim": EMBEDDING_DIM,
            "tokens": token_count,
            "stored": stored,
            "vector_db": "pgvector",
        }

    async def batch_vectorize(self, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Vectorize multiple artifacts in a single batch.

        Args:
            artifacts: List of artifact dicts (same shape as ``vectorize()``).

        Returns:
            Dict with keys:
                chunks_created (int):  Total chunks written.
                total_tokens (int):    Sum of token counts across all chunks.
                batch_id (str):        UUID identifying this batch run.
        """
        if not artifacts:
            logger.warning("batch_vectorize called with empty list")
            return {
                "chunks_created": 0,
                "total_tokens": 0,
                "batch_id": str(uuid.uuid4()),
            }

        batch_id = str(uuid.uuid4())
        total_tokens = 0
        chunks_created = 0

        for artifact in artifacts:
            result = await self.vectorize(artifact)
            if result["stored"]:
                chunks_created += 1
                total_tokens += result["tokens"]

        logger.info(
            "Batch %s complete: %d chunks, %d tokens from %d artifacts",
            batch_id,
            chunks_created,
            total_tokens,
            len(artifacts),
        )

        return {
            "chunks_created": chunks_created,
            "total_tokens": total_tokens,
            "batch_id": batch_id,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_content(artifact: Dict[str, Any]) -> str:
        """Pull text content from an artifact dict, falling back through common keys."""
        # Try explicit content field first
        if "content" in artifact and artifact["content"]:
            return str(artifact["content"])
        # Fall back to metadata
        meta = artifact.get("metadata", {})
        if isinstance(meta, dict) and meta:
            import json

            return json.dumps(meta, ensure_ascii=False, default=str)
        if isinstance(meta, str) and meta:
            return meta
        # Last resort: stringify the whole artifact
        import json

        return json.dumps(artifact, ensure_ascii=False, default=str)

    @staticmethod
    def _mock_embed(text: str) -> List[float]:
        """Generate a deterministic mock embedding from text.

        Phase 3: Replace with a real embedding model, e.g.:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("BAAI/bge-large-en-v1.5")
            return model.encode(text).tolist()

        For now we use a SHA-256 hash expanded to 1024 dimensions so the
        same input always produces the same vector (useful for testing).
        """
        # Hash the text to get deterministic seed bytes
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand 32 bytes → 1024 floats by cycling and normalizing
        vector: List[float] = []
        for i in range(EMBEDDING_DIM):
            byte_val = h[i % len(h)]
            # Map 0-255 → roughly [-1.0, 1.0]
            vector.append((byte_val / 127.5) - 1.0)
        # L2-normalize so cosine similarity works as expected
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    def _simulate_store(
        self, chunk_id: str, artifact_type: str, content: str, token_count: int
    ) -> bool:
        """Simulate a pgvector INSERT.

        Phase 3: Replace with actual asyncpg INSERT into knowledge_chunks:
            await conn.execute(
                \"\"\"INSERT INTO knowledge_chunks (doc_id, title, content,
                   doc_type, embedding, token_count, updated_at)
                   VALUES ($1, $2, $3, $4, $5::vector, $6, $7)
                   ON CONFLICT (doc_id) DO UPDATE ...\"\"\",
                chunk_id, title, content, artifact_type, embedding, token_count, now,
            )
        """
        if not self._db_available:
            logger.error("pgvector backend unavailable — cannot store chunk %s", chunk_id)
            return False

        # In Phase 2 we just log and claim success
        logger.debug(
            "pgvector SIMULATED STORE: chunk_id=%s type=%s tokens=%d content_len=%d",
            chunk_id,
            artifact_type,
            token_count,
            len(content),
        )
        return True
