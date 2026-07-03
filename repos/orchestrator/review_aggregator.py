"""
review_aggregator.py - Agent Review Aggregator

Aggregates review opinions from multiple agents for a given gate.
Reads from the gate_approvals.agent_reviews JSONB column and provides
consensus calculation, summary generation, and conflict detection.

Usage:
    python3 review_aggregator.py   # runs self-test using mock data
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)


class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


@dataclass
class AgentReview:
    """A single agent's review opinion."""
    agent_id: str
    verdict: ReviewVerdict
    confidence: float = 1.0
    comment: str = ""
    checks: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "comment": self.comment,
            "checks": self.checks,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentReview":
        return cls(
            agent_id=data.get("agent_id", ""),
            verdict=ReviewVerdict(data.get("verdict", "abstain")),
            confidence=float(data.get("confidence", 1.0)),
            comment=data.get("comment", ""),
            checks=data.get("checks", []),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class ReviewSummary:
    """Aggregated summary of all agent reviews for a gate."""
    gate_id: str
    total_reviews: int = 0
    approve_count: int = 0
    reject_count: int = 0
    abstain_count: int = 0
    consensus: Optional[ReviewVerdict] = None
    avg_confidence: float = 0.0
    conflicts: list[dict] = field(default_factory=list)
    reviews: list[AgentReview] = field(default_factory=list)
    recommendation: str = ""

    @property
    def has_consensus(self) -> bool:
        return self.consensus is not None

    @property
    def approval_ratio(self) -> float:
        total = self.approve_count + self.reject_count
        if total == 0:
            return 0.0
        return self.approve_count / total


class ReviewAggregator:
    """Aggregates agent reviews for gate approvals.

    Consensus rules:
      - 100% approve -> APPROVE
      - >= 75% approve -> APPROVE (weak consensus)
      - 100% reject -> REJECT
      - Mixed < 75% -> no consensus (requires human intervention)
    """

    CONSENSUS_THRESHOLD = 0.75

    def __init__(self, db_dsn: str = "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"):
        self._db_dsn = db_dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(dsn=self._db_dsn, min_size=1, max_size=5)
        logger.info("ReviewAggregator connected to PostgreSQL")

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("ReviewAggregator disconnected")

    async def add_review(self, gate_id: str, review: AgentReview) -> None:
        assert self._pool is not None
        existing = await self._load_reviews(gate_id)
        existing[review.agent_id] = review
        await self._save_reviews(gate_id, existing)
        logger.info("Review added for gate=%s agent=%s verdict=%s", gate_id, review.agent_id, review.verdict.value)

    async def remove_review(self, gate_id: str, agent_id: str) -> bool:
        assert self._pool is not None
        existing = await self._load_reviews(gate_id)
        if agent_id in existing:
            del existing[agent_id]
            await self._save_reviews(gate_id, existing)
            logger.info("Review removed for gate=%s agent=%s", gate_id, agent_id)
            return True
        return False

    async def get_reviews(self, gate_id: str) -> list[AgentReview]:
        reviews_map = await self._load_reviews(gate_id)
        return list(reviews_map.values())

    async def summarize(self, gate_id: str) -> ReviewSummary:
        reviews = await self.get_reviews(gate_id)
        summary = self._compute_summary(gate_id, reviews)
        logger.info("Review summary for gate=%s: consensus=%s approval_ratio=%.2f",
                    gate_id, summary.consensus, summary.approval_ratio)
        return summary

    def _compute_summary(self, gate_id: str, reviews: list[AgentReview]) -> ReviewSummary:
        total = len(reviews)
        if total == 0:
            return ReviewSummary(
                gate_id=gate_id,
                recommendation="No agent reviews submitted yet."
            )

        counter = Counter(r.verdict for r in reviews)
        approve = counter.get(ReviewVerdict.APPROVE, 0)
        reject = counter.get(ReviewVerdict.REJECT, 0)
        abstain = counter.get(ReviewVerdict.ABSTAIN, 0)
        voted = approve + reject

        if total > 0:
            avg_confidence = sum(r.confidence for r in reviews) / total
        else:
            avg_confidence = 0.0

        consensus = None
        recommendation = ""
        conflicts = []

        if voted == 0:
            recommendation = "All agents abstained - requires human decision."
        elif approve == voted:
            consensus = ReviewVerdict.APPROVE
            recommendation = f"Unanimous approval ({approve}/{voted} agents)."
        elif reject == voted:
            consensus = ReviewVerdict.REJECT
            recommendation = f"Unanimous rejection ({reject}/{voted} agents)."
        elif voted > 0 and approve / voted >= self.CONSENSUS_THRESHOLD:
            consensus = ReviewVerdict.APPROVE
            ratio_pct = int(approve / voted * 100)
            recommendation = (
                f"Consensus to approve ({approve}/{voted} agents, "
                f"{ratio_pct}%). Confidence: {avg_confidence:.2f}"
            )
            for r in reviews:
                if r.verdict == ReviewVerdict.REJECT:
                    conflicts.append({
                        "agent": r.agent_id,
                        "concern": r.comment,
                        "verdict": "reject",
                    })
        else:
            recommendation = (
                f"No consensus - {approve} approve vs {reject} reject "
                f"({voted} voted). Requires human intervention."
            )
            for r in reviews:
                if r.verdict in (ReviewVerdict.APPROVE, ReviewVerdict.REJECT):
                    conflicts.append({
                        "agent": r.agent_id,
                        "verdict": r.verdict.value,
                        "concern": r.comment,
                    })

        return ReviewSummary(
            gate_id=gate_id,
            total_reviews=total,
            approve_count=approve,
            reject_count=reject,
            abstain_count=abstain,
            consensus=consensus,
            avg_confidence=round(avg_confidence, 3),
            conflicts=conflicts,
            reviews=reviews,
            recommendation=recommendation,
        )

    async def _load_reviews(self, gate_id: str) -> dict[str, AgentReview]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT agent_reviews FROM gate_approvals WHERE id = $1", gate_id
            )
        if row is None or row["agent_reviews"] is None:
            return {}
        raw = _json.loads(row["agent_reviews"]) if isinstance(row["agent_reviews"], str) else row["agent_reviews"]
        return {agent_id: AgentReview.from_dict(data) for agent_id, data in raw.items()}

    async def _save_reviews(self, gate_id: str, reviews: dict[str, AgentReview]) -> None:
        assert self._pool is not None
        blob = _json.dumps({aid: r.to_dict() for aid, r in reviews.items()}, ensure_ascii=False)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE gate_approvals SET agent_reviews = $1::jsonb WHERE id = $2",
                blob, gate_id,
            )


def _test_pure_logic():
    """Test the aggregation logic without a database connection."""
    logger.info("=== Review Aggregator Pure Logic Test ===")

    agg = ReviewAggregator()

    # Unanimous approval
    reviews = [
        AgentReview(agent_id="A1", verdict=ReviewVerdict.APPROVE, confidence=0.95, timestamp="2026-01-01T00:00:00Z"),
        AgentReview(agent_id="A2", verdict=ReviewVerdict.APPROVE, confidence=0.88, timestamp="2026-01-01T00:00:00Z"),
        AgentReview(agent_id="A3", verdict=ReviewVerdict.APPROVE, confidence=0.92, timestamp="2026-01-01T00:00:00Z"),
    ]
    summary = agg._compute_summary("gate-1", reviews)
    assert summary.consensus == ReviewVerdict.APPROVE, f"Expected APPROVE, got {summary.consensus}"
    assert summary.has_consensus
    logger.info("Unanimous approval: %s", summary.recommendation)

    # Mixed - no consensus
    reviews2 = [
        AgentReview(agent_id="A1", verdict=ReviewVerdict.APPROVE, confidence=0.95),
        AgentReview(agent_id="A2", verdict=ReviewVerdict.REJECT, confidence=0.9, comment="Security risk"),
        AgentReview(agent_id="A3", verdict=ReviewVerdict.REJECT, confidence=0.7),
    ]
    summary2 = agg._compute_summary("gate-2", reviews2)
    assert summary2.consensus is None, f"Expected no consensus, got {summary2.consensus}"
    assert len(summary2.conflicts) > 0
    logger.info("No consensus: %s", summary2.recommendation)

    # Weak consensus (80% approve)
    reviews3 = [
        AgentReview(agent_id="A1", verdict=ReviewVerdict.APPROVE, confidence=0.9),
        AgentReview(agent_id="A2", verdict=ReviewVerdict.APPROVE, confidence=0.8),
        AgentReview(agent_id="A3", verdict=ReviewVerdict.APPROVE, confidence=0.7),
        AgentReview(agent_id="A4", verdict=ReviewVerdict.APPROVE, confidence=0.6),
        AgentReview(agent_id="A5", verdict=ReviewVerdict.REJECT, confidence=0.3, comment="Minor nit"),
    ]
    summary3 = agg._compute_summary("gate-3", reviews3)
    assert summary3.consensus == ReviewVerdict.APPROVE, f"Expected APPROVE, got {summary3.consensus}"
    assert len(summary3.conflicts) == 1
    logger.info("Weak consensus: %s", summary3.recommendation)

    # All abstain
    reviews4 = [
        AgentReview(agent_id="A1", verdict=ReviewVerdict.ABSTAIN),
        AgentReview(agent_id="A2", verdict=ReviewVerdict.ABSTAIN),
    ]
    summary4 = agg._compute_summary("gate-4", reviews4)
    assert summary4.consensus is None
    assert summary4.approve_count == 0 and summary4.reject_count == 0
    logger.info("All abstain: %s", summary4.recommendation)

    # Edge case: no reviews
    summary5 = agg._compute_summary("gate-5", [])
    assert summary5.total_reviews == 0
    logger.info("No reviews: %s", summary5.recommendation)

    logger.info("=== All pure logic tests passed ===")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    _test_pure_logic()
