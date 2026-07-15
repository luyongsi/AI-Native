"""
Mission Control Backend — Approvals API (Gate 0-3)

Aligned with data dictionary §6 and migration 008 (new approvals table).

Endpoints:
  GET  /api/approvals                  - List approvals
  POST /api/approvals                  - Pre-create approval record
  GET  /api/approvals/{id}/context     - Gate0 approval context (A1+A2 outputs)
  POST /api/approvals/{id}/decide      - Submit pass/reject decision
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

# Gate SLA in hours (per design doc §7): Gate0=1h
GATE_SLA_HOURS = {0: 1, 1: 24, 2: 12, 3: 4}

GATE_META = {
    0: {"label": "业务确认", "icon": "clipboard", "description": "A1+A2 分析完成后，业务方确认需求理解正确"},
    1: {"label": "Spec 确认", "icon": "file-text", "description": "A4 生成 Spec/OpenAPI/ERD 后确认设计方案"},
    2: {"label": "架构确认", "icon": "layers", "description": "A8 架构评审通过后确认技术方案"},
    3: {"label": "发布确认", "icon": "rocket", "description": "A12 Code Review 通过后确认发布上线"},
}

# Reject reason enum → Chinese label
REJECT_REASON_LABELS: dict[str, str] = {
    # Gate 0
    "requirement_unclear": "需求不清晰",
    "requirement_incomplete": "需求不完整",
    "acceptance_criteria_insufficient": "验收标准不足",
    "business_not_feasible": "业务不可行",
    "risk_unacceptable": "风险过高",
    "conflict_unresolved": "存在冲突",
    # Gate 1 (stage two)
    "prototype_not_aligned": "原型与需求不符",
    "spec_incomplete": "Spec 不完整",
    "api_design_issue": "API 设计问题",
    "erd_incomplete": "ERD 不完整",
    "acceptance_criteria_mismatch": "验收标准遗漏",
    "prototype_change_needed": "需要原型修改",
    "other": "其他",
}

# ── Pydantic models ────────────────────────────────────────────────────────


class ApprovalCreateBody(BaseModel):
    req_id: str
    session_id: str = ""
    cycle: int = 0
    gate_level: int = 0


class RejectReason(BaseModel):
    category: str
    description: str


class DecideBody(BaseModel):
    decision: str = Field(..., description="pass or reject")
    reject_reasons: list[RejectReason] = Field(default_factory=list)
    revision_guidance: str = ""
    a3_rework: bool = Field(default=False, description="Gate1 only: require A3 prototype rework")
    a6_rework: bool = Field(default=True, description="Gate2 only: require A6 DAG rework")
    a7_rework: bool = Field(default=True, description="Gate2 only: require A7 test case rework")


# ── Helpers ────────────────────────────────────────────────────────────────


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


async def _publish_nats(subject: str, payload: dict) -> None:
    """Best-effort publish to NATS JetStream."""
    try:
        from main import NATS_CLIENT
        if NATS_CLIENT and NATS_CLIENT.is_connected:
            js = NATS_CLIENT.jetstream()
            msg_id = f"approval-{payload.get('req_id', '?')}-{payload.get('gate_level', 0)}-{payload.get('decision', '?')}"
            await js.publish(subject, json.dumps(payload, ensure_ascii=False).encode(),
                             headers={"Nats-Msg-Id": msg_id})
            logger.info("Published NATS %s", subject)
    except Exception as e:
        logger.warning("NATS publish failed for %s: %s", subject, e)


async def _signal_temporal_gate(req_id: str, gate: int, decision: str) -> None:
    """Send approve_gate or reject_gate signal to the Temporal workflow."""
    try:
        from temporalio.client import Client
        client = await Client.connect("localhost:7233", namespace="ai-native")

        req_prefix = req_id[:8]
        async for wf in client.list_workflows(
            'WorkflowType="RequirementWorkflow" and ExecutionStatus="Running"'
        ):
            if wf.id.startswith(f"req-{req_prefix}"):
                handle = client.get_workflow_handle(wf.id)
                signal_name = "approve_gate" if decision == "pass" else "reject_gate"
                await handle.signal(signal_name, f"gate_{gate}")
                logger.info("Signaled %s gate=%d → workflow=%s", signal_name, gate, wf.id)
                return

        logger.warning("No running RequirementWorkflow found for req_id prefix=%s", req_prefix)
    except Exception as e:
        logger.warning("Failed to signal Temporal workflow for gate %d: %s", gate, e)


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("")
async def list_approvals(
    gate_level: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List approvals, filtering by gate_level and/or status."""
    conn = await get_db()
    try:
        conditions = []
        params = []
        idx = 1
        if gate_level is not None:
            conditions.append(f"a.gate_level = ${idx}")
            params.append(gate_level)
            idx += 1
        if status:
            conditions.append(f"a.status = ${idx}")
            params.append(status)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        rows = await conn.fetch(
            f"""
            SELECT a.*, r.title as req_title
            FROM approvals a
            LEFT JOIN requirements r ON r.id = a.req_id
            {where}
            ORDER BY a.created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )

        items = []
        for row in rows:
            items.append({
                "id": str(row["id"]),
                "req_id": str(row["req_id"]) if row["req_id"] else None,
                "req_title": row["req_title"] or "",
                "session_id": str(row["session_id"]) if row["session_id"] else None,
                "gate_level": row["gate_level"],
                "cycle": row["cycle"],
                "status": row["status"],
                "decision": row["decision"],
                "reject_reasons": (
                    row["reject_reasons"]
                    if isinstance(row["reject_reasons"], list)
                    else []
                ),
                "revision_guidance": row["revision_guidance"],
                "reviewer_user_id": row["reviewer_user_id"],
                "reviewer_name": row["reviewer_name"],
                "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "gate_meta": GATE_META.get(row["gate_level"]),
            })
        return {"items": items, "total": len(items)}
    finally:
        await conn.close()


@router.get("/{approval_id}")
async def get_approval(approval_id: str):
    """Get a single approval record by ID."""
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            """SELECT a.*, r.title as req_title
               FROM approvals a
               LEFT JOIN requirements r ON r.id = a.req_id
               WHERE a.id = $1::uuid""",
            approval_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")

        return {
            "id": str(row["id"]),
            "req_id": str(row["req_id"]) if row["req_id"] else None,
            "req_title": row["req_title"] or "",
            "session_id": str(row["session_id"]) if row["session_id"] else None,
            "gate_level": row["gate_level"],
            "cycle": row["cycle"],
            "status": row["status"],
            "decision": row["decision"],
            "reject_reasons": (
                row["reject_reasons"]
                if isinstance(row["reject_reasons"], list)
                else []
            ),
            "revision_guidance": row["revision_guidance"],
            "reviewer_user_id": row["reviewer_user_id"],
            "reviewer_name": row["reviewer_name"],
            "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "gate_meta": GATE_META.get(row["gate_level"]),
        }
    finally:
        await conn.close()


@router.post("")
async def create_approval(body: ApprovalCreateBody):
    """Pre-create an approval record (idempotent)."""
    conn = await get_db()
    try:
        # Check requirement exists
        req = await conn.fetchrow(
            "SELECT id FROM requirements WHERE id = $1::uuid", body.req_id
        )
        if not req:
            raise HTTPException(status_code=404, detail="Requirement not found")

        # Idempotency
        existing = await conn.fetchrow(
            """SELECT id FROM approvals
               WHERE req_id = $1::uuid AND gate_level = $2 AND cycle = $3 AND status = 'pending'""",
            body.req_id, body.gate_level, body.cycle,
        )
        if existing:
            return {
                "id": str(existing["id"]),
                "status": "pending",
                "message": "Approval already exists",
            }

        now = datetime.now(timezone.utc)
        row = await conn.fetchrow(
            """INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, created_at)
               VALUES ($1::uuid, $2::uuid, $3, $4, 'pending', $5) RETURNING id""",
            body.req_id, body.session_id or None, body.gate_level, body.cycle, now,
        )
        return {
            "id": str(row["id"]),
            "gate_level": body.gate_level,
            "cycle": body.cycle,
            "status": "pending",
            "gate_meta": GATE_META.get(body.gate_level),
        }
    finally:
        await conn.close()


@router.get("/{approval_id}/context")
async def get_approval_context(approval_id: str):
    """Assemble Gate approval context.

    Gate 0: A1 draft + A2 analysis.
    Gate 1: A3 prototype + A4 spec + A5 design review report.
    """
    conn = await get_db()
    try:
        approval = await conn.fetchrow(
            "SELECT * FROM approvals WHERE id = $1::uuid", approval_id
        )
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")

        req_id = str(approval["req_id"])
        cycle = approval["cycle"]
        gate_level = approval["gate_level"]

        if gate_level == 1:
            return await _build_gate1_context(conn, req_id, cycle, approval)
        elif gate_level == 2:
            return await _build_gate2_context(conn, req_id, cycle, approval)
        return await _build_gate0_context(conn, req_id, cycle, approval)
    finally:
        await conn.close()


async def _build_gate0_context(conn, req_id: str, cycle: int, approval) -> dict:
    """Build Gate0 context: A1 draft + A2 analysis."""
    req = await conn.fetchrow(
        "SELECT requirement_draft, confidence_score FROM requirements WHERE id = $1::uuid",
        req_id,
    )
    requirement_draft = None
    confidence_score = None
    if req:
        requirement_draft = req["requirement_draft"] if isinstance(req["requirement_draft"], dict) else {}
        confidence_score = req["confidence_score"]

    a1_row = await conn.fetchrow(
        """SELECT artifact FROM agent_results
           WHERE req_id = $1::uuid AND agent_key = 'A1' AND cycle = $2
           ORDER BY created_at DESC LIMIT 1""",
        req_id, cycle,
    )

    wireframe_url = None
    if a1_row and isinstance(a1_row["artifact"], dict):
        wireframe_url = a1_row["artifact"].get("wireframe_url")

    a2_row = await conn.fetchrow(
        """SELECT artifact, status FROM agent_results
           WHERE req_id = $1::uuid AND agent_key = 'A2' AND cycle = $2
           ORDER BY created_at DESC LIMIT 1""",
        req_id, cycle,
    )

    a2_missing = True
    a2_artifact: dict = {}
    if a2_row:
        a2_missing = False
        a2_artifact = a2_row["artifact"] if isinstance(a2_row["artifact"], dict) else {}

    return {
        "req_id": req_id,
        "session_id": str(approval["session_id"]) if approval["session_id"] else None,
        "cycle": cycle,
        "gate_level": approval["gate_level"],
        "a1_output": {
            "requirement_draft": requirement_draft,
            "wireframe_url": wireframe_url,
            "confidence_score": confidence_score,
        },
        "a2_output": {
            "feasibility_assessment": a2_artifact.get("feasibility_assessment"),
            "confirmation_checklist": a2_artifact.get("confirmation_checklist", []),
            "conflicts": a2_artifact.get("conflicts", []),
            "quality_score": a2_artifact.get("quality_score"),
            "a2_missing": a2_missing,
        },
        "gate_meta": GATE_META.get(approval["gate_level"]),
    }


async def _build_gate1_context(conn, req_id: str, cycle: int, approval) -> dict:
    """Build Gate1 context: A3 prototype + A4 spec + A5 design review."""
    # A3 output
    a3_proto = await conn.fetchrow(
        """SELECT prototype_url, screens, version, status
           FROM prototype_artifacts
           WHERE req_id = $1::uuid AND status = 'confirmed'
           ORDER BY version DESC LIMIT 1""",
        req_id,
    )
    a3_output = {
        "prototype_url": a3_proto["prototype_url"] if a3_proto else None,
        "screens": a3_proto["screens"] if a3_proto and isinstance(a3_proto["screens"], list) else [],
        "version": a3_proto["version"] if a3_proto else 0,
        "confirmed": a3_proto is not None,
    }

    # A4 output
    a4_ds = await conn.fetchrow(
        """SELECT spec_doc, openapi_schema, erd_diagram, quality_score
           FROM design_specs
           WHERE req_id = $1::uuid
           ORDER BY version DESC LIMIT 1""",
        req_id,
    )
    a4_missing = a4_ds is None
    a4_output = {
        "spec_doc": a4_ds["spec_doc"] if a4_ds and isinstance(a4_ds["spec_doc"], dict) else {},
        "openapi_schema": a4_ds["openapi_schema"] if a4_ds and isinstance(a4_ds["openapi_schema"], dict) else {},
        "erd_diagram": a4_ds["erd_diagram"] if a4_ds and isinstance(a4_ds["erd_diagram"], dict) else {},
        "quality_score": float(a4_ds["quality_score"]) if a4_ds and a4_ds["quality_score"] else 0.0,
        "a4_missing": a4_missing,
    }

    # A5 output
    a5_row = await conn.fetchrow(
        """SELECT artifact FROM agent_results
           WHERE req_id = $1::uuid AND agent_key = 'A5'
           ORDER BY cycle DESC, created_at DESC LIMIT 1""",
        req_id,
    )
    a5_missing = a5_row is None
    a5_output: dict = {"check_report": None, "a5_missing": a5_missing}
    if a5_row and isinstance(a5_row["artifact"], dict):
        a5_output["check_report"] = a5_row["artifact"].get("check_report")

    return {
        "req_id": req_id,
        "session_id": str(approval["session_id"]) if approval["session_id"] else None,
        "cycle": cycle,
        "gate_level": approval["gate_level"],
        "a3_output": a3_output,
        "a4_output": a4_output,
        "a5_output": a5_output,
        "gate_meta": GATE_META.get(approval["gate_level"]),
    }


async def _build_gate2_context(conn, req_id: str, cycle: int, approval) -> dict:
    """Build Gate2 context: A6 DAG + A7 test assets + A8 architecture review."""
    # Requirement info
    req = await conn.fetchrow(
        "SELECT title, tech_prep_status, tech_prep_revision_count FROM requirements WHERE id = $1::uuid",
        req_id,
    )
    req_info = {
        "title": req["title"] if req else "",
        "tech_prep_status": req["tech_prep_status"] if req else None,
        "tech_prep_revision_count": req["tech_prep_revision_count"] if req else 0,
    }

    # A6 output (DAG)
    a6_row = await conn.fetchrow(
        """SELECT artifact FROM agent_results
           WHERE req_id = $1::uuid AND agent_key = 'A6' AND cycle = $2
           ORDER BY created_at DESC LIMIT 1""",
        req_id, cycle,
    )
    a6_missing = a6_row is None
    a6_artifact = a6_row["artifact"] if a6_row and isinstance(a6_row["artifact"], dict) else {}
    a6_output = {
        "dag": a6_artifact.get("dag", {}),
        "validation": a6_artifact.get("validation", {}),
        "task_dags_id": a6_artifact.get("task_dags_id"),
        "a6_missing": a6_missing,
    }

    # Also fetch from task_dags for full DAG detail
    dag_row = await conn.fetchrow(
        """SELECT dag_json, node_count, critical_path_length,
                  total_estimated_hours, human_review_nodes, source
           FROM task_dags
           WHERE req_id = $1::uuid AND cycle = $2
           ORDER BY version DESC LIMIT 1""",
        req_id, cycle,
    )
    if dag_row:
        a6_output["dag_detail"] = {
            "dag_json": dag_row["dag_json"] if isinstance(dag_row["dag_json"], dict) else {},
            "node_count": dag_row["node_count"],
            "critical_path_length": dag_row["critical_path_length"],
            "total_estimated_hours": float(dag_row["total_estimated_hours"]) if dag_row["total_estimated_hours"] else 0,
            "human_review_nodes": dag_row["human_review_nodes"],
            "source": dag_row["source"],
        }

    # A7 output (test assets)
    a7_row = await conn.fetchrow(
        """SELECT artifact FROM agent_results
           WHERE req_id = $1::uuid AND agent_key = 'A7' AND cycle = $2
           ORDER BY created_at DESC LIMIT 1""",
        req_id, cycle,
    )
    a7_missing = a7_row is None
    a7_artifact = a7_row["artifact"] if a7_row and isinstance(a7_row["artifact"], dict) else {}
    a7_output = {
        "test_plan": a7_artifact.get("test_plan", {}),
        "test_assets": a7_artifact.get("test_assets", {}),
        "dag_coverage": a7_artifact.get("dag_coverage", {}),
        "a7_missing": a7_missing,
    }

    # Also fetch latest test_assets record
    ta_row = await conn.fetchrow(
        """SELECT id, total_cases, priority_distribution, source, version, created_at
           FROM test_assets
           WHERE req_id = $1::uuid
           ORDER BY created_at DESC LIMIT 1""",
        req_id,
    )
    if ta_row:
        a7_output["test_asset_record"] = {
            "test_asset_id": ta_row["id"],
            "total_cases": ta_row["total_cases"],
            "priority_distribution": ta_row["priority_distribution"] if isinstance(ta_row["priority_distribution"], dict) else {},
            "version": ta_row["version"],
            "created_at": ta_row["created_at"].isoformat() if ta_row["created_at"] else None,
        }

    # A8 output (architecture review)
    a8_row = await conn.fetchrow(
        """SELECT artifact FROM agent_results
           WHERE req_id = $1::uuid AND agent_key = 'A8' AND cycle = $2
           ORDER BY created_at DESC LIMIT 1""",
        req_id, cycle,
    )
    a8_missing = a8_row is None
    a8_artifact = a8_row["artifact"] if a8_row and isinstance(a8_row["artifact"], dict) else {}
    a8_review = a8_artifact.get("review", {})
    a8_output = {
        "review": a8_review,
        "a8_missing": a8_missing,
    }

    return {
        "req_id": req_id,
        "session_id": str(approval["session_id"]) if approval["session_id"] else None,
        "cycle": cycle,
        "gate_level": approval["gate_level"],
        "requirement_info": req_info,
        "a6_output": a6_output,
        "a7_output": a7_output,
        "a8_output": a8_output,
        "gate_meta": GATE_META.get(approval["gate_level"]),
    }


@router.post("/{approval_id}/decide")
async def decide_approval(approval_id: str, body: DecideBody):
    """Submit a pass/reject decision for an approval."""
    if body.decision not in ("pass", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'pass' or 'reject'")

    conn = await get_db()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM approvals WHERE id = $1::uuid", approval_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Approval not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Already decided: status={row['status']}")

        req_id = str(row["req_id"])
        gate = row["gate_level"]
        cycle = row["cycle"]
        session_id = str(row["session_id"]) if row["session_id"] else ""
        now = datetime.now(timezone.utc)

        if body.decision == "reject":
            if not body.reject_reasons:
                raise HTTPException(status_code=400, detail="reject_reasons required for rejection")
            if not body.revision_guidance:
                raise HTTPException(status_code=400, detail="revision_guidance required for rejection")

            reviewer_name = f"gate{gate}_reviewer"

            await conn.execute(
                """UPDATE approvals
                   SET status = 'decided', decision = 'reject',
                       reject_reasons = $1::jsonb, revision_guidance = $2,
                       a3_rework = $3,
                       a6_rework = $4, a7_rework = $5,
                       reviewer_user_id = $6, reviewer_name = $6,
                       reviewed_at = $7
                   WHERE id = $8::uuid""",
                json.dumps([r.model_dump() for r in body.reject_reasons], ensure_ascii=False),
                body.revision_guidance,
                body.a3_rework if gate == 1 else False,
                body.a6_rework if gate == 2 else False,
                body.a7_rework if gate == 2 else False,
                reviewer_name,
                now,
                approval_id,
            )

            nats_subject = f"agent.result.gate{gate}.reject"
            nats_payload = {
                "req_id": req_id,
                "session_id": session_id,
                "cycle": cycle,
                "gate_level": gate,
                "decision": "reject",
                "reject_reasons": [r.model_dump() for r in body.reject_reasons],
                "revision_guidance": body.revision_guidance,
                "a3_rework": body.a3_rework if gate == 1 else False,
                "a6_rework": body.a6_rework if gate == 2 else False,
                "a7_rework": body.a7_rework if gate == 2 else False,
                "reviewer_user_id": reviewer_name,
                "reviewer_name": reviewer_name,
                "reviewed_at": now.isoformat(),
            }
            await _publish_nats(nats_subject, nats_payload)
            await _signal_temporal_gate(req_id, gate, "reject")

            return {"id": approval_id, "status": "decided", "decision": "reject",
                    "reviewed_at": now.isoformat(), "gate_meta": GATE_META.get(gate)}

        # pass
        reviewer_name = f"gate{gate}_reviewer"
        await conn.execute(
            """UPDATE approvals
               SET status = 'decided', decision = 'pass',
                   reviewer_user_id = $1, reviewer_name = $1,
                   reviewed_at = $2
               WHERE id = $3::uuid""",
            reviewer_name,
            now,
            approval_id,
        )

        nats_subject = f"agent.result.gate{gate}.pass"
        nats_payload = {
            "req_id": req_id,
            "session_id": session_id,
            "cycle": cycle,
            "gate_level": gate,
            "decision": "pass",
            "reviewer_user_id": f"gate{gate}_reviewer",
            "reviewer_name": f"gate{gate}_reviewer",
            "reviewed_at": now.isoformat(),
        }
        await _publish_nats(nats_subject, nats_payload)
        await _signal_temporal_gate(req_id, gate, "pass")

        # NOTE: requirements.status update (to 'approved') is the Orchestrator's
        #       responsibility per data dictionary §1.1. We do NOT write it here —
        #       the Orchestrator handles it on receiving agent.result.gate0.pass.

        return {"id": approval_id, "status": "decided", "decision": "pass",
                "reviewed_at": now.isoformat(), "gate_meta": GATE_META.get(gate)}
    finally:
        await conn.close()
