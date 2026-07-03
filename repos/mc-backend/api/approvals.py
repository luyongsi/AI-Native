"""
Mission Control Backend - Approvals API (Phase 5.2: Complete Gate 0-3 + SLA)
GET  /api/approvals                  - List approvals, filter by gate/status
POST /api/approvals                  - Create approval record (human or agent-auto)
POST /api/approvals/{id}/approve    - Approve a gate approval
POST /api/approvals/{id}/reject     - Reject a gate approval

Orchestrator Refactor: Gate approval now signals Temporal Workflow directly.
Agent dispatch is handled by the Workflow, not by this API.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

# Gate SLA in hours (per design doc 3.0)
GATE_SLA_HOURS = {0: 48, 1: 24, 2: 12, 3: 4}

# Gate metadata for frontend differentiation
GATE_META = {
    0: {"label": "业务确认", "icon": "clipboard", "description": "A1+A2 分析完成后，业务方确认需求理解正确"},
    1: {"label": "Spec 确认", "icon": "file-text", "description": "A4 生成 Spec/OpenAPI/ERD 后确认设计方案"},
    2: {"label": "架构确认", "icon": "layers", "description": "A8 架构评审通过后确认技术方案"},
    3: {"label": "发布确认", "icon": "rocket", "description": "A12 Code Review 通过后确认发布上线"},
}


class AutoCreateRequest(BaseModel):
    req_id: str
    gate: int
    agent_id: str = ""
    review_data: Optional[dict] = None


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


def _compute_review_summary(agent_reviews) -> dict:
    """Parse agent_reviews JSONB into a summary of approve/reject/abstain counts."""
    if not isinstance(agent_reviews, dict):
        return {"approve": 0, "reject": 0, "abstain": 0, "total": 0}
    approve = 0; reject = 0; abstain = 0
    for _agent, review in agent_reviews.items():
        if not isinstance(review, dict):
            continue
        verdict = review.get("verdict") or review.get("status") or review.get("decision") or ""
        verdict = verdict.lower()
        if verdict in ("approve", "approved", "pass", "passed"):
            approve += 1
        elif verdict in ("reject", "rejected", "fail", "failed"):
            reject += 1
        else:
            abstain += 1
    return {"approve": approve, "reject": reject, "abstain": abstain, "total": approve + reject + abstain}


@router.get("")
async def list_approvals(
    gate: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    conn = await get_db()
    try:
        conditions = []
        params = []
        idx = 1
        if gate is not None:
            conditions.append(f"ga.gate = ${idx}"); params.append(gate); idx += 1
        if status:
            conditions.append(f"ga.status = ${idx}"); params.append(status); idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await conn.fetch(
            f"""
            SELECT ga.*, r.title as req_title
            FROM gate_approvals ga
            LEFT JOIN requirements r ON r.id = ga.req_id
            {where}
            ORDER BY ga.created_at DESC
            LIMIT ${idx}
            """, *params)
        items = []
        for row in rows:
            agent_reviews = row["agent_reviews"] if isinstance(row["agent_reviews"], dict) else {}
            sla_deadline = row["sla_deadline"]
            sla_remaining = None
            if sla_deadline and row["status"] == "pending":
                remaining = (sla_deadline - datetime.now(timezone.utc)).total_seconds()
                sla_remaining = max(0, int(remaining))
            items.append({
                "id": str(row["id"]),
                "req_id": str(row["req_id"]) if row["req_id"] else None,
                "req_title": row["req_title"] or "",
                "gate": row["gate"],
                "status": row["status"],
                "approver": row["approver"],
                "sla_deadline": sla_deadline.isoformat() if sla_deadline else None,
                "sla_remaining_seconds": sla_remaining,
                "agent_reviews": agent_reviews,
                "review_summary": _compute_review_summary(agent_reviews),
                "reject_reasons": row["reject_reasons"] if isinstance(row["reject_reasons"], list) else [],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
                "gate_meta": GATE_META.get(row["gate"]),
            })
        return {"items": items, "total": len(items)}
    finally:
        await conn.close()


@router.post("")
async def create_approval(
    req_id: str = Query(""),
    gate: int = Query(0),
    body: Optional[AutoCreateRequest] = None,
):
    """Create approval (human via query params, or agent-auto via JSON body)."""
    if body and body.req_id:
        req_id = body.req_id
        gate = body.gate
    if not req_id:
        raise HTTPException(status_code=400, detail="req_id is required")

    conn = await get_db()
    try:
        req = await conn.fetchrow("SELECT id FROM requirements WHERE id = $1::uuid", req_id)
        if not req:
            raise HTTPException(status_code=404, detail="Requirement not found")

        # Check for existing pending
        existing = await conn.fetchrow(
            "SELECT id FROM gate_approvals WHERE req_id = $1::uuid AND gate = $2 AND status = 'pending'",
            req_id, gate)
        if existing:
            return {"id": str(existing["id"]), "status": "pending", "message": "Approval already submitted"}

        sla_hours = GATE_SLA_HOURS.get(gate, 24)
        now = datetime.now(timezone.utc)
        sla = now + timedelta(hours=sla_hours)

        # Attach agent review data if provided
        agent_reviews = {}
        if body and body.review_data and body.agent_id:
            agent_reviews[body.agent_id] = body.review_data

        row = await conn.fetchrow(
            """INSERT INTO gate_approvals (req_id, gate, status, sla_deadline, agent_reviews, created_at)
               VALUES ($1::uuid, $2, 'pending', $3, $4::jsonb, $5) RETURNING id""",
            req_id, gate, sla, agent_reviews, now)
        return {
            "id": str(row["id"]), "gate": gate, "status": "pending",
            "sla_deadline": sla.isoformat(), "gate_meta": GATE_META.get(gate),
        }
    finally:
        await conn.close()


@router.get("/check-overdue")
async def check_overdue():
    """List all pending approvals past their SLA deadline."""
    conn = await get_db()
    try:
        now = datetime.now(timezone.utc)
        rows = await conn.fetch(
            "SELECT * FROM gate_approvals WHERE status = 'pending' AND sla_deadline < $1", now)
        return {"overdue": len(rows), "items": [
            {"id": str(r["id"]), "req_id": str(r["req_id"]) if r["req_id"] else None,
             "gate": r["gate"], "sla_deadline": r["sla_deadline"].isoformat()}
            for r in rows
        ]}
    finally:
        await conn.close()


@router.post("/{approval_id}/approve")
async def approve(approval_id: str):
    conn = await get_db()
    try:
        row = await conn.fetchrow("SELECT * FROM gate_approvals WHERE id = $1::uuid", approval_id)
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")
        if row["status"] not in ("pending", "overdue"):
            raise HTTPException(status_code=409, detail=f"Cannot approve: current status is {row['status']}")

        req_id = str(row["req_id"])
        gate = row["gate"]
        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE gate_approvals SET status = 'approved', resolved_at = $1 WHERE id = $2::uuid",
            now, approval_id)

        result: dict = {"id": str(row["id"]), "status": "approved", "resolved_at": now.isoformat(),
                        "gate": gate, "gate_meta": GATE_META.get(gate)}

        # Signal Temporal workflow
        await _signal_temporal_gate(req_id, gate, result)

        await _advance_requirement(conn, req_id, gate)

        return result
    finally:
        await conn.close()


async def _advance_requirement(conn, req_id: str, gate: int):
    """Update requirement status based on gate approval."""
    gate_status_map = {
        0: "analyzing",
        1: "designing",
        2: "developing",
        3: "releasing",
    }
    new_status = gate_status_map.get(gate)
    if new_status:
        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE requirements SET status = $1, updated_at = $2 WHERE id = $3::uuid",
            new_status, now, req_id)
        logger.info(f"Requirement {req_id} advanced to {new_status} (gate {gate} approved)")


async def _signal_temporal_gate(req_id: str, gate: int, result: dict):
    """Send approve_gate Signal to the Temporal Workflow."""
    try:
        from temporalio.client import Client
        client = await Client.connect("localhost:7233", namespace="ai-native")

        req_prefix = req_id[:8]
        async for wf in client.list_workflows(
            f'WorkflowType="RequirementWorkflow" and ExecutionStatus="Running"'
        ):
            if wf.id.startswith(f"req-{req_prefix}"):
                handle = client.get_workflow_handle(wf.id)
                await handle.signal("approve_gate", f"gate_{gate}")
                result["temporal_signaled"] = True
                result["workflow_id"] = wf.id
                logger.info("Signaled approve_gate gate=%d -> workflow=%s", gate, wf.id)
                return

        logger.warning("No running RequirementWorkflow found for req_id prefix=%s", req_prefix)
    except Exception as e:
        logger.warning(f"Failed to signal Temporal workflow for gate {gate}: {e}")


@router.post("/{approval_id}/reject")
async def reject(approval_id: str, reason: Optional[str] = None):
    conn = await get_db()
    try:
        row = await conn.fetchrow("SELECT * FROM gate_approvals WHERE id = $1::uuid", approval_id)
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")
        if row["status"] not in ("pending",):
            raise HTTPException(status_code=409, detail=f"Cannot reject: current status is {row['status']}")

        now = datetime.now(timezone.utc)
        reject_reasons = list(row["reject_reasons"]) if isinstance(row["reject_reasons"], list) else []
        if reason:
            reject_reasons.append({"reason": reason, "at": now.isoformat()})

        await conn.execute(
            "UPDATE gate_approvals SET status = 'rejected', resolved_at = $1, reject_reasons = $2::jsonb WHERE id = $3::uuid",
            now, reject_reasons, approval_id)
        return {"id": str(row["id"]), "status": "rejected", "resolved_at": now.isoformat(),
                "reject_reasons": reject_reasons, "gate_meta": GATE_META.get(row["gate"])}
    finally:
        await conn.close()
