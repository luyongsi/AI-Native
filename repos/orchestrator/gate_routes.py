"""
gate_routes.py - Gate Approval HTTP API Router

FastAPI router providing REST endpoints for Mission Control frontend
to list, inspect, approve, and reject gates.

Mounted by mc-backend at /api/approvals or used standalone.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    approver: str
    reviews: Optional[dict] = None


class RejectRequest(BaseModel):
    approver: str
    reason: Optional[str] = None


class GateDetail(BaseModel):
    gate_id: str
    req_id: str
    gate: int
    status: str
    approver: Optional[str] = None
    sla_deadline: Optional[str] = None
    agent_reviews: Optional[dict] = None
    reject_reasons: Optional[list] = None
    created_at: Optional[str] = None
    resolved_at: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_gsm():
    """Lazy-init a GateStateMachine connected to the shared DB pool.

    Tries to reuse mc-backend's DB_POOL; falls back to a standalone
    GateStateMachine with its own pool.
    """
    from gate_state import GateStateMachine

    try:
        from main import DB_POOL  # type: ignore[import-not-found]
    except ImportError:
        DB_POOL = None  # noqa: N806

    if DB_POOL is not None:
        # Reuse the existing pool — wrap in a lightweight GSM
        gsm = GateStateMachine.__new__(GateStateMachine)
        gsm._pool = DB_POOL
        gsm._db_dsn = ""
        return gsm

    # Standalone: create and connect a fresh GSM
    gsm = GateStateMachine()
    await gsm.connect()
    return gsm


def _record_to_detail(record) -> dict:
    """Convert a GateRecord to a JSON-safe dict."""
    return {
        "gate_id": record.gate_id,
        "req_id": record.req_id,
        "gate": record.gate,
        "status": record.status.value,
        "approver": record.approver,
        "sla_deadline": record.sla_deadline.isoformat() if record.sla_deadline else None,
        "agent_reviews": record.agent_reviews or {},
        "reject_reasons": record.reject_reasons or [],
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "resolved_at": record.resolved_at.isoformat() if record.resolved_at else None,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_approvals(
    status: Optional[str] = Query(None, description="Filter by status: pending|approved|rejected|overdue"),
    gate: Optional[int] = Query(None, description="Filter by gate level (0-3)"),
    limit: int = Query(50, ge=1, le=200),
):
    """List all gate approvals with optional status/gate filters.

    When connected to the DB pool this queries gate_approvals directly.
    Falls back to an empty list when no pool is available.
    """
    try:
        from main import DB_POOL  # type: ignore[import-not-found]
    except ImportError:
        DB_POOL = None  # noqa: N806
        logger.warning("DB_POOL not available — returning empty gate list")

    if DB_POOL is None:
        return {"items": [], "total": 0}

    conditions = []
    params = []
    idx = 1

    if status is not None:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    if gate is not None:
        conditions.append(f"gate = ${idx}")
        params.append(gate)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, req_id, gate, status, approver, sla_deadline,
                   agent_reviews, reject_reasons, created_at, resolved_at
              FROM gate_approvals
              {where}
             ORDER BY created_at DESC
             LIMIT ${idx}
            """,
            *params,
        )

    items = []
    for row in rows:
        items.append({
            "id": str(row["id"]),
            "req_id": str(row["req_id"]) if row["req_id"] else None,
            "gate": row["gate"],
            "status": row["status"],
            "approver": row["approver"],
            "sla_deadline": row["sla_deadline"].isoformat() if row["sla_deadline"] else None,
            "agent_reviews": row["agent_reviews"] if isinstance(row["agent_reviews"], dict) else {},
            "reject_reasons": row["reject_reasons"] if isinstance(row["reject_reasons"], list) else [],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        })

    return {"items": items, "total": len(items)}


@router.get("/{gate_id}")
async def get_gate_detail(gate_id: str):
    """Get a single gate with its agent reviews summary."""
    gsm = await _get_gsm()
    try:
        record = await gsm.get_gate(gate_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Gate not found")

        from review_aggregator import ReviewAggregator
        ra = ReviewAggregator.__new__(ReviewAggregator)
        ra._pool = gsm._pool
        ra._db_dsn = gsm._db_dsn

        summary = await ra.summarize(gate_id)
        detail = _record_to_detail(record)
        detail["review_summary"] = {
            "total_reviews": summary.total_reviews,
            "approve_count": summary.approve_count,
            "reject_count": summary.reject_count,
            "abstain_count": summary.abstain_count,
            "consensus": summary.consensus.value if summary.consensus else None,
            "avg_confidence": summary.avg_confidence,
            "approval_ratio": summary.approval_ratio,
            "recommendation": summary.recommendation,
            "conflicts": summary.conflicts,
        }
        return detail
    finally:
        if gsm._db_dsn:  # standalone pool was created — clean it up
            await gsm.close()


@router.post("/{gate_id}/approve")
async def approve_gate(gate_id: str, body: ApproveRequest):
    """Approve a pending gate."""
    gsm = await _get_gsm()
    try:
        from gate_state import InvalidTransitionError

        try:
            record = await gsm.approve(
                gate_id=gate_id,
                approver=body.approver,
                reviews=body.reviews,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Gate not found")
        except InvalidTransitionError:
            raise HTTPException(
                status_code=409,
                detail="Cannot approve: gate is not in pending state",
            )

        return _record_to_detail(record)
    finally:
        if gsm._db_dsn:
            await gsm.close()


@router.post("/{gate_id}/reject")
async def reject_gate(gate_id: str, body: RejectRequest):
    """Reject a pending gate."""
    gsm = await _get_gsm()
    try:
        from gate_state import InvalidTransitionError

        reasons = [body.reason] if body.reason else None
        try:
            record = await gsm.reject(
                gate_id=gate_id,
                approver=body.approver,
                reasons=reasons,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Gate not found")
        except InvalidTransitionError:
            raise HTTPException(
                status_code=409,
                detail="Cannot reject: gate is not in pending state",
            )

        return _record_to_detail(record)
    finally:
        if gsm._db_dsn:
            await gsm.close()
