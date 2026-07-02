"""
k14/expiration_marker.py — K14 sub-module: Content Expiration & Conflict Detection

Identifies stale knowledge chunks, marks them expired/archived, and detects
conflicting entries in the knowledge base.  Phase 2 uses simulated data;
Phase 3 would query pgvector directly and integrate with an archival pipeline.

Usage:
    marker = ExpirationMarker()
    stale = await marker.check_stale_content("my-project", max_age_days=90)
    result = await marker.mark_expired([chunk_id_1, chunk_id_2])
    conflicts = await marker.detect_conflicts()
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MAX_AGE_DAYS = 90


class ExpirationMarker:
    """Detects and handles stale/conflicting knowledge chunks.

    Phase 2 (current):  Mock stale-content detection based on simulated dates.
    Phase 3 (planned):   Real pgvector queries against ``knowledge_chunks``
                         with ``updated_at`` column, plus automated archival
                         to an ``expired_chunks`` table or S3 cold storage.

    Attributes:
        _archived_count: Running total of chunks archived this session.
        _marked_count:   Running total of chunks marked expired this session.
    """

    def __init__(self) -> None:
        self._archived_count: int = 0
        self._marked_count: int = 0
        # Phase 2: canned stale data for deterministic testing
        self._mock_stale_chunks: List[Dict[str, Any]] = [
            {
                "chunk_id": "chunk:spec:REQ-001:a1b2c3d4",
                "doc_id": "spec:REQ-001:v1",
                "age_days": 120,
                "reason": "No updates since initial creation; newer version v2 exists",
            },
            {
                "chunk_id": "chunk:api:API-003:e5f6g7h8",
                "doc_id": "api:API-003:v1",
                "age_days": 95,
                "reason": "API endpoint deprecated in favour of API-004",
            },
            {
                "chunk_id": "chunk:design:DESIGN-001:i9j0k1l2",
                "doc_id": "design:DESIGN-001:v2",
                "age_days": 180,
                "reason": "Design superseded by architecture review v3",
            },
            {
                "chunk_id": "chunk:test:TEST-005:m3n4o5p6",
                "doc_id": "test:TEST-005:v1",
                "age_days": 91,
                "reason": "Test file references removed API; coverage dropped below threshold",
            },
        ]
        self._mock_conflicts: List[Dict[str, Any]] = [
            {
                "chunk_a": "chunk:spec:SPEC-001:v1:abc",
                "chunk_b": "chunk:spec:SPEC-001:v2:def",
                "overlap_score": 0.87,
                "field": "api_endpoints",
            },
            {
                "chunk_a": "chunk:code:CODE-002:v1:ghi",
                "chunk_b": "chunk:code:CODE-002-R:jkl",
                "overlap_score": 0.72,
                "field": "function_signatures",
            },
        ]
        logger.info("ExpirationMarker initialized (Phase 2 stub mode)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_stale_content(
        self, project: str, max_age_days: int = DEFAULT_MAX_AGE_DAYS
    ) -> Dict[str, Any]:
        """Scan for stale knowledge chunks older than *max_age_days*.

        Phase 2: Filters canned mock data by *max_age_days* threshold.
        Phase 3: Runs a pgvector query like:
            SELECT chunk_id, doc_id, updated_at,
                   EXTRACT(DAY FROM now() - updated_at) AS age_days
            FROM knowledge_chunks
            WHERE project = $1 AND updated_at < now() - $2::interval
            ORDER BY updated_at ASC;

        Args:
            project:      Project namespace to scope the check.
            max_age_days: Age threshold in days (default 90).

        Returns:
            Dict with keys:
                stale_chunks (list):  List of dicts with chunk_id, doc_id,
                                      age_days, reason.
                total_stale (int):    Count of stale chunks found.
        """
        if not project:
            logger.warning("check_stale_content called with empty project name")
            return {"stale_chunks": [], "total_stale": 0}

        # Phase 3: Replace with actual DB query
        #   async with self._pool.acquire() as conn:
        #       rows = await conn.fetch(STALE_QUERY, project, max_age_days)
        #       stale_chunks = [dict(row) for row in rows]

        stale_chunks = [
            chunk
            for chunk in self._mock_stale_chunks
            if chunk["age_days"] >= max_age_days
        ]

        logger.info(
            "check_stale_content(project=%s, max_age=%dd) → %d stale chunk(s)",
            project,
            max_age_days,
            len(stale_chunks),
        )

        return {
            "stale_chunks": stale_chunks,
            "total_stale": len(stale_chunks),
        }

    async def mark_expired(self, chunk_ids: List[str]) -> Dict[str, Any]:
        """Mark the given chunks as expired and optionally archive them.

        Phase 2: Simulates the mark + archive flow; increments counters.
        Phase 3: Bulk-UPDATE ``knowledge_chunks`` to set ``expired = true``,
                 then INSERT into ``expired_chunks`` archive table, e.g.:
                     WITH expired AS (
                         UPDATE knowledge_chunks
                         SET expired = true, expired_at = now()
                         WHERE chunk_id = ANY($1)
                         RETURNING *
                     )
                     INSERT INTO expired_chunks SELECT * FROM expired;

        Args:
            chunk_ids: List of chunk IDs to expire.

        Returns:
            Dict with keys:
                marked (int):   Number of chunks marked expired.
                archived (int): Number of chunks archived.
        """
        if not chunk_ids:
            logger.warning("mark_expired called with empty chunk_ids list")
            return {"marked": 0, "archived": 0}

        count = len(chunk_ids)
        self._marked_count += count
        self._archived_count += count  # Phase 2: archive everything marked

        logger.info(
            "mark_expired: %d chunk(s) marked + archived (Phase 2 stub)", count
        )

        return {
            "marked": count,
            "archived": count,
        }

    async def detect_conflicts(self) -> Dict[str, Any]:
        """Detect conflicting/duplicate entries in the knowledge base.

        Phase 2: Returns canned conflict data.
        Phase 3: Runs a similarity query via pgvector + cosine distance,
                 e.g.:
                     SELECT a.chunk_id AS chunk_a, b.chunk_id AS chunk_b,
                            1 - (a.embedding <=> b.embedding) AS overlap_score
                     FROM knowledge_chunks a
                     JOIN knowledge_chunks b
                       ON a.doc_type = b.doc_type
                      AND a.chunk_id < b.chunk_id
                     WHERE 1 - (a.embedding <=> b.embedding) > 0.7
                     ORDER BY overlap_score DESC;

        Returns:
            Dict with keys:
                conflicts (list): List of dicts with chunk_a, chunk_b,
                                  overlap_score, field.
        """
        logger.info(
            "detect_conflicts → %d conflict(s) found (Phase 2 stub)",
            len(self._mock_conflicts),
        )

        return {
            "conflicts": self._mock_conflicts,
        }
