"""
gate_state.py - Gate State Machine

Manages the lifecycle of a gate approval: pending -> approved/rejected/overdue.
Persists state to PostgreSQL gate_approvals table.

Usage:
    python3 gate_state.py   # runs self-test using mock data
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

import asyncpg

logger = logging.getLogger(__name__)


class GateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERDUE = "overdue"


_TRANSITIONS: dict[GateStatus, set[GateStatus]] = {
    GateStatus.PENDING:  {GateStatus.APPROVED, GateStatus.REJECTED, GateStatus.OVERDUE},
    GateStatus.APPROVED: set(),
    GateStatus.REJECTED: set(),
    GateStatus.OVERDUE:  set(),
}


class InvalidTransitionError(Exception):
    """Raised when a gate transition is not allowed."""


class GateRecord:
    """In-memory representation of a gate_approvals row."""

    def __init__(
        self,
        gate_id: str,
        req_id: str,
        gate: int,
        status: GateStatus = GateStatus.PENDING,
        approver: Optional[str] = None,
        sla_deadline: Optional[datetime] = None,
        agent_reviews: Optional[dict] = None,
        reject_reasons: Optional[list] = None,
        created_at: Optional[datetime] = None,
        resolved_at: Optional[datetime] = None,
    ):
        self.gate_id = gate_id
        self.req_id = req_id
        self.gate = gate
        self.status = status
        self.approver = approver
        self.sla_deadline = sla_deadline or (datetime.now(timezone.utc) + timedelta(hours=4))
        self.agent_reviews = agent_reviews or {}
        self.reject_reasons = reject_reasons or []
        self.created_at = created_at or datetime.now(timezone.utc)
        self.resolved_at = resolved_at


class GateStateMachine:
    """Manages gate approval lifecycle with PostgreSQL persistence."""

    def __init__(self, db_dsn: str = "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"):
        self._db_dsn = db_dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(dsn=self._db_dsn, min_size=1, max_size=5)
        logger.info("GateStateMachine connected to PostgreSQL")

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("GateStateMachine disconnected")

    def _guard_transition(self, current: GateStatus, target: GateStatus):
        allowed = _TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {current.value} to {target.value}"
            )

    async def create_gate(
        self,
        req_id: str,
        gate_level: int,
        sla_hours: float = 4.0,
    ) -> GateRecord:
        assert self._pool is not None, "Not connected - call connect() first"
        gate_id = str(uuid4())
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=sla_hours)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO gate_approvals (id, req_id, gate, status, sla_deadline, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                gate_id,
                req_id,
                gate_level,
                GateStatus.PENDING.value,
                deadline,
                now,
            )

        logger.info("Gate %s created for req=%s level=%d deadline=%s", gate_id, req_id, gate_level, deadline)
        return GateRecord(
            gate_id=gate_id,
            req_id=req_id,
            gate=gate_level,
            status=GateStatus.PENDING,
            sla_deadline=deadline,
            created_at=now,
        )

    async def approve(self, gate_id: str, approver: str, reviews: Optional[dict] = None) -> GateRecord:
        return await self._transition(gate_id, GateStatus.APPROVED, approver=approver, reviews=reviews)

    async def reject(self, gate_id: str, approver: str, reasons: Optional[list] = None,
                     reviews: Optional[dict] = None) -> GateRecord:
        return await self._transition(gate_id, GateStatus.REJECTED, approver=approver,
                                      reasons=reasons, reviews=reviews)

    async def mark_overdue(self, gate_id: str) -> GateRecord:
        return await self._transition(gate_id, GateStatus.OVERDUE)

    async def _transition(
        self,
        gate_id: str,
        target: GateStatus,
        approver: Optional[str] = None,
        reasons: Optional[list] = None,
        reviews: Optional[dict] = None,
    ) -> GateRecord:
        assert self._pool is not None, "Not connected - call connect() first"
        current = await self.get_gate(gate_id)
        if current is None:
            raise ValueError(f"Gate not found: {gate_id}")
        self._guard_transition(current.status, target)

        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            reasons_json = _json.dumps(reasons) if reasons else None
            reviews_json = _json.dumps(reviews) if reviews else None
            await conn.execute(
                """
                UPDATE gate_approvals
                   SET status = $1,
                       approver = COALESCE($3, approver),
                       resolved_at = $2,
                       reject_reasons = CASE WHEN $4::jsonb IS NOT NULL
                                             THEN $4::jsonb
                                             ELSE reject_reasons END,
                       agent_reviews = CASE WHEN $5::jsonb IS NOT NULL
                                            THEN $5::jsonb
                                            ELSE agent_reviews END
                 WHERE id = $6
                """,
                target.value,
                now,
                approver,
                reasons_json,
                reviews_json,
                gate_id,
            )

        current.status = target
        current.approver = approver or current.approver
        current.resolved_at = now
        if reasons:
            current.reject_reasons = reasons
        if reviews:
            current.agent_reviews = reviews

        logger.info("Gate %s -> %s (approver=%s)", gate_id, target.value, approver)
        return current

    async def get_gate(self, gate_id: str) -> Optional[GateRecord]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, req_id, gate, status, approver, sla_deadline,
                       agent_reviews, reject_reasons, created_at, resolved_at
                  FROM gate_approvals
                 WHERE id = $1
                """,
                gate_id,
            )
        if row is None:
            return None
        return GateRecord(
            gate_id=row["id"],
            req_id=row["req_id"],
            gate=row["gate"],
            status=GateStatus(row["status"]),
            approver=row["approver"],
            sla_deadline=row["sla_deadline"],
            agent_reviews=_json.loads(row["agent_reviews"]) if row["agent_reviews"] else {},
            reject_reasons=_json.loads(row["reject_reasons"]) if row["reject_reasons"] else [],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    async def get_overdue_gates(self) -> list[GateRecord]:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, req_id, gate, status, approver, sla_deadline,
                       agent_reviews, reject_reasons, created_at, resolved_at
                  FROM gate_approvals
                 WHERE status = 'pending'
                   AND sla_deadline < NOW()
                """
            )
        records = []
        for row in rows:
            records.append(GateRecord(
                gate_id=row["id"],
                req_id=row["req_id"],
                gate=row["gate"],
                status=GateStatus(row["status"]),
                approver=row["approver"],
                sla_deadline=row["sla_deadline"],
                agent_reviews=_json.loads(row["agent_reviews"]) if row["agent_reviews"] else {},
                reject_reasons=_json.loads(row["reject_reasons"]) if row["reject_reasons"] else [],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
            ))
        return records

    async def run_overdue_check(self) -> int:
        overdue = await self.get_overdue_gates()
        count = 0
        for gate in overdue:
            await self.mark_overdue(gate.gate_id)
            count += 1
        if count:
            logger.warning("Marked %d overdue gate(s)", count)
        return count


async def _self_test():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    gsm = GateStateMachine()
    try:
        await gsm.connect()
        logger.info("=== Gate State Machine Self-Test ===")

        # Seed a requirement row first (FK constraint)
        async with gsm._pool.acquire() as conn:
            test_req_id = str(uuid4())
            await conn.execute(
                "INSERT INTO requirements (id, title, status) VALUES ($1, $2, $3) "
                "ON CONFLICT (id) DO NOTHING",
                test_req_id, "Gate test requirement", "draft"
            )

        gate = await gsm.create_gate(req_id=test_req_id, gate_level=1, sla_hours=0.1)
        logger.info("Created gate: %s (status=%s)", gate.gate_id, gate.status.value)

        gate = await gsm.approve(gate.gate_id, approver="test-user")
        assert gate.status == GateStatus.APPROVED, f"Expected APPROVED, got {gate.status}"
        logger.info("Approved gate: %s", gate.gate_id)

        try:
            await gsm.approve(gate.gate_id, approver="test-user")
            assert False, "Should have raised"
        except InvalidTransitionError:
            logger.info("Invalid transition correctly rejected")

        gate2 = await gsm.create_gate(req_id=test_req_id, gate_level=2, sla_hours=0.1)
        gate2 = await gsm.reject(gate2.gate_id, approver="test-user", reasons=["Quality check failed"])
        assert gate2.status == GateStatus.REJECTED
        logger.info("Rejected gate: %s", gate2.gate_id)

        logger.info("=== All self-tests passed ===")
    except Exception as exc:
        logger.error("Self-test failed: %s", exc, exc_info=True)
        raise
    finally:
        await gsm.close()


if __name__ == "__main__":
    asyncio.run(_self_test())
