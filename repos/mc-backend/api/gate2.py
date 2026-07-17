"""
Mission Control Backend — Gate2 API (架构确认)

Gate2 专用端点，提供架构评审审批页面所需的数据聚合和操作。

Endpoints:
  GET  /api/gate2/{req_id}/context   - Gate2 审批上下文（A6 DAG + A7 测试 + A8 评审）
  POST /api/gate2/{req_id}/approve   - Gate2 通过
  POST /api/gate2/{req_id}/reject    - Gate2 拒绝（含 a6_rework/a7_rework 控制）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gate2", tags=["gate2"])


class Gate2RejectBody(BaseModel):
    """Gate2 拒绝请求体"""
    reject_reasons: list[dict] = Field(default_factory=list)
    revision_guidance: str = Field(..., description="修订指引（必填）")
    a6_rework: bool = Field(default=True, description="是否需要 A6 DAG 返工")
    a7_rework: bool = Field(default=True, description="是否需要 A7 测试用例返工")
    reviewer_user_id: str = Field(default="gate2_reviewer")
    reviewer_name: str = Field(default="Gate2 Reviewer")


class Gate2ApproveBody(BaseModel):
    """Gate2 通过请求体"""
    reviewer_user_id: str = Field(default="gate2_reviewer")
    reviewer_name: str = Field(default="Gate2 Reviewer")


# ── Helpers ──────────────────────────────────────────────────────────────


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


async def _publish_nats(subject: str, payload: dict) -> None:
    """Best-effort publish to NATS JetStream."""
    try:
        from main import NATS_CLIENT
        if NATS_CLIENT and NATS_CLIENT.is_connected:
            js = NATS_CLIENT.jetstream()
            msg_id = f"gate2-{payload.get('req_id', '?')}-{payload.get('decision', '?')}"
            await js.publish(subject, json.dumps(payload, ensure_ascii=False).encode(),
                             headers={"Nats-Msg-Id": msg_id})
            logger.info("Published NATS %s", subject)
    except Exception as e:
        logger.warning("NATS publish failed for %s: %s", subject, e)


async def _signal_temporal_gate(req_id: str, decision: str, reject_reasons=None,
                                revision_guidance="", a6_rework=True, a7_rework=True) -> None:
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
                if decision == "pass":
                    await handle.signal("approve_gate", "gate_2")
                else:
                    await handle.signal("reject_gate", "gate_2",
                                        reject_reasons=reject_reasons or [],
                                        revision_guidance=revision_guidance)
                logger.info("Signaled %s gate=2 → workflow=%s",
                            "approve_gate" if decision == "pass" else "reject_gate", wf.id)
                return

        logger.warning("No running RequirementWorkflow found for req_id prefix=%s", req_prefix)
    except Exception as e:
        logger.warning("Failed to signal Temporal workflow for Gate2: %s", e)


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/{req_id}/context")
async def get_gate2_context(req_id: str):
    """获取 Gate2 审批上下文 — 聚合 A6 DAG + A7 测试 + A8 架构评审报告."""
    conn = await get_db()
    try:
        # Requirement info
        req = await conn.fetchrow(
            """SELECT id, title, tech_prep_status, tech_prep_revision_count, phase
               FROM requirements WHERE id = $1::uuid""",
            req_id,
        )
        if not req:
            raise HTTPException(status_code=404, detail="Requirement not found")

        cycle = 0  # Fetch current cycle from latest agent_result
        cycle_row = await conn.fetchval(
            """SELECT MAX(cycle) FROM agent_results WHERE req_id = $1::uuid""",
            req_id,
        )
        if cycle_row is not None:
            cycle = cycle_row

        # A6 output
        a6_row = await conn.fetchrow(
            """SELECT artifact FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = 'A6' AND cycle = $2
               ORDER BY created_at DESC LIMIT 1""",
            req_id, cycle,
        )
        a6_missing = a6_row is None
        a6_artifact = a6_row["artifact"] if a6_row and isinstance(a6_row["artifact"], dict) else {}

        # task_dags detail
        dag_row = await conn.fetchrow(
            """SELECT id, version, dag_json, node_count, critical_path_length,
                      total_estimated_hours, human_review_nodes, source
               FROM task_dags
               WHERE req_id = $1::uuid AND cycle = $2
               ORDER BY version DESC LIMIT 1""",
            req_id, cycle,
        )
        dag_detail = None
        if dag_row:
            dag_json = dag_row["dag_json"]
            if isinstance(dag_json, str):
                try:
                    dag_json = json.loads(dag_json)
                except (json.JSONDecodeError, TypeError):
                    dag_json = {}
            dag_detail = {
                "task_dags_id": dag_row["id"],
                "version": dag_row["version"],
                "dag_json": dag_json,
                "node_count": dag_row["node_count"],
                "critical_path_length": dag_row["critical_path_length"],
                "total_estimated_hours": float(dag_row["total_estimated_hours"]) if dag_row["total_estimated_hours"] else 0,
                "human_review_nodes": dag_row["human_review_nodes"],
                "source": dag_row["source"],
            }

        # A7 output
        a7_row = await conn.fetchrow(
            """SELECT artifact FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = 'A7' AND cycle = $2
               ORDER BY created_at DESC LIMIT 1""",
            req_id, cycle,
        )
        a7_missing = a7_row is None
        a7_artifact = a7_row["artifact"] if a7_row and isinstance(a7_row["artifact"], dict) else {}

        # A8 output
        a8_row = await conn.fetchrow(
            """SELECT artifact FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = 'A8' AND cycle = $2
               ORDER BY created_at DESC LIMIT 1""",
            req_id, cycle,
        )
        a8_missing = a8_row is None
        a8_artifact = a8_row["artifact"] if a8_row and isinstance(a8_row["artifact"], dict) else {}
        a8_review = a8_artifact.get("review", {})

        return {
            "req_id": req_id,
            "cycle": cycle,
            "requirement_info": {
                "title": req["title"],
                "phase": req["phase"],
                "tech_prep_status": req["tech_prep_status"],
                "tech_prep_revision_count": req["tech_prep_revision_count"],
            },
            "a6_output": {
                "dag": a6_artifact.get("dag", {}),
                "dag_detail": dag_detail,
                "validation": a6_artifact.get("validation", {}),
                "a6_missing": a6_missing,
            },
            "a7_output": {
                "test_plan": a7_artifact.get("test_plan", {}),
                "test_assets": a7_artifact.get("test_assets", {}),
                "dag_coverage": a7_artifact.get("dag_coverage", {}),
                "a7_missing": a7_missing,
            },
            "a8_output": {
                "review": a8_review,
                "violations": a8_review.get("violations", []),
                "checks": a8_review.get("checks", {}),
                "score": a8_review.get("score", 0),
                "verdict": a8_review.get("verdict", ""),
                "suggestions": a8_review.get("suggestions", []),
                "summary": a8_review.get("summary", ""),
                "a8_missing": a8_missing,
            },
        }
    finally:
        await conn.close()


@router.post("/{req_id}/approve")
async def approve_gate2(req_id: str, body: Gate2ApproveBody):
    """Gate2 通过 — 更新审批记录 + 通知 Orchestrator."""
    conn = await get_db()
    try:
        now = datetime.now(timezone.utc)

        # Find or create pending Gate2 approval
        approval = await conn.fetchrow(
            """SELECT id, session_id, cycle FROM approvals
               WHERE req_id = $1::uuid AND gate_level = 2 AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            req_id,
        )

        if approval:
            await conn.execute(
                """UPDATE approvals
                   SET status = 'decided', decision = 'pass',
                       reviewer_user_id = $1, reviewer_name = $1,
                       reviewed_at = $2
                   WHERE id = $3::uuid""",
                body.reviewer_user_id, now, approval["id"],
            )
            session_id = str(approval["session_id"]) if approval["session_id"] else ""
            cycle = approval["cycle"]
        else:
            # Create if not exists
            session_row = await conn.fetchrow(
                """SELECT id FROM dialogue_sessions
                   WHERE req_id = $1::uuid ORDER BY last_updated DESC LIMIT 1""",
                req_id,
            )
            session_id = str(session_row["id"]) if session_row else ""
            cycle_row = await conn.fetchval(
                """SELECT MAX(cycle) FROM agent_results WHERE req_id = $1::uuid""",
                req_id,
            )
            cycle = cycle_row or 0

            row = await conn.fetchrow(
                """INSERT INTO approvals
                   (req_id, session_id, gate_level, cycle, status, decision,
                    reviewer_user_id, reviewer_name, reviewed_at, created_at)
                   VALUES ($1::uuid, $2::uuid, 2, $3, 'decided', 'pass',
                           $4, $4, $5, $5) RETURNING id""",
                req_id, session_id or None, cycle, body.reviewer_user_id, now,
            )

        # Update requirements: tech_prep_completed
        await conn.execute(
            """UPDATE requirements
               SET tech_prep_status = 'tech_prep_completed',
                   phase = 'development',
                   updated_at = NOW()
               WHERE id = $1::uuid""",
            req_id,
        )

        # Publish NATS event
        nats_payload = {
            "req_id": req_id,
            "session_id": session_id,
            "cycle": cycle,
            "gate_level": 2,
            "decision": "pass",
            "reviewer_user_id": body.reviewer_user_id,
            "reviewer_name": body.reviewer_name,
            "reviewed_at": now.isoformat(),
        }
        await _publish_nats("agent.result.gate2.pass", nats_payload)
        await _signal_temporal_gate(req_id, "pass")

        return {
            "req_id": req_id,
            "gate_level": 2,
            "decision": "pass",
            "reviewed_at": now.isoformat(),
            "message": "Gate2 通过，需求进入开发阶段",
        }
    finally:
        await conn.close()


@router.post("/{req_id}/reject")
async def reject_gate2(req_id: str, body: Gate2RejectBody):
    """Gate2 拒绝 — 更新审批记录 + 通知 Orchestrator 重新调度 A6+A7."""
    if not body.reject_reasons:
        raise HTTPException(status_code=400, detail="reject_reasons 必填")
    if not body.revision_guidance:
        raise HTTPException(status_code=400, detail="revision_guidance 必填")

    conn = await get_db()
    try:
        now = datetime.now(timezone.utc)

        # Find or create pending Gate2 approval
        approval = await conn.fetchrow(
            """SELECT id, session_id, cycle FROM approvals
               WHERE req_id = $1::uuid AND gate_level = 2 AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            req_id,
        )

        if approval:
            await conn.execute(
                """UPDATE approvals
                   SET status = 'decided', decision = 'reject',
                       reject_reasons = $1::jsonb, revision_guidance = $2,
                       a6_rework = $3, a7_rework = $4,
                       reviewer_user_id = $5, reviewer_name = $5,
                       reviewed_at = $6
                   WHERE id = $7::uuid""",
                json.dumps(body.reject_reasons, ensure_ascii=False),
                body.revision_guidance,
                body.a6_rework, body.a7_rework,
                body.reviewer_user_id, now, approval["id"],
            )
            session_id = str(approval["session_id"]) if approval["session_id"] else ""
            cycle = approval["cycle"]
        else:
            session_row = await conn.fetchrow(
                """SELECT id FROM dialogue_sessions
                   WHERE req_id = $1::uuid ORDER BY last_updated DESC LIMIT 1""",
                req_id,
            )
            session_id = str(session_row["id"]) if session_row else ""
            cycle_row = await conn.fetchval(
                """SELECT MAX(cycle) FROM agent_results WHERE req_id = $1::uuid""",
                req_id,
            )
            cycle = cycle_row or 0

            row = await conn.fetchrow(
                """INSERT INTO approvals
                   (req_id, session_id, gate_level, cycle, status, decision,
                    reject_reasons, revision_guidance, a6_rework, a7_rework,
                    reviewer_user_id, reviewer_name, reviewed_at, created_at)
                   VALUES ($1::uuid, $2::uuid, 2, $3, 'decided', 'reject',
                           $4::jsonb, $5, $6, $7,
                           $8, $8, $9, $9) RETURNING id""",
                req_id, session_id or None, cycle,
                json.dumps(body.reject_reasons, ensure_ascii=False),
                body.revision_guidance,
                body.a6_rework, body.a7_rework,
                body.reviewer_user_id, now,
            )

        # Update requirements: revising + revision_count +1
        await conn.execute(
            """UPDATE requirements
               SET tech_prep_status = 'revising',
                   tech_prep_revision_count = tech_prep_revision_count + 1,
                   updated_at = NOW()
               WHERE id = $1::uuid""",
            req_id,
        )

        # Publish NATS event
        nats_payload = {
            "req_id": req_id,
            "session_id": session_id,
            "cycle": cycle,
            "gate_level": 2,
            "decision": "reject",
            "reject_reasons": body.reject_reasons,
            "revision_guidance": body.revision_guidance,
            "a6_rework": body.a6_rework,
            "a7_rework": body.a7_rework,
            "reviewer_user_id": body.reviewer_user_id,
            "reviewer_name": body.reviewer_name,
            "reviewed_at": now.isoformat(),
        }
        await _publish_nats("agent.result.gate2.reject", nats_payload)
        await _signal_temporal_gate(req_id, "reject",
                                    reject_reasons=body.reject_reasons,
                                    revision_guidance=body.revision_guidance)

        # Fetch updated revision count
        req_row = await conn.fetchrow(
            "SELECT tech_prep_revision_count FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        revision_count = req_row["tech_prep_revision_count"] if req_row else 0

        return {
            "req_id": req_id,
            "gate_level": 2,
            "decision": "reject",
            "reject_reasons": body.reject_reasons,
            "revision_guidance": body.revision_guidance,
            "a6_rework": body.a6_rework,
            "a7_rework": body.a7_rework,
            "tech_prep_revision_count": revision_count,
            "reviewed_at": now.isoformat(),
            "message": f"Gate2 拒绝，A6+A7 将重新调度 (revision={revision_count})",
        }
    finally:
        await conn.close()
