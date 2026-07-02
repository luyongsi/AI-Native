"""
Mission Control Backend - Requirements API
GET  /api/requirements       - List all requirements
POST /api/requirements       - Create a new requirement
GET  /api/requirements/{id}  - Get requirement detail with timeline

Phase 4A (SPEC-40): Extended fields — stages, spec_sections, assignees, pm,
description, sla_deadline, related_ids.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime, timezone
import asyncpg
import uuid
import json

router = APIRouter(prefix="/api/requirements", tags=["requirements"])

# ── Default pipeline stages inserted into spec on create ──────────────────
DEFAULT_STAGES = [
    {"key": "pool", "label": "需求池", "status": "done", "order": 0},
    {"key": "designing", "label": "设计中", "status": "active", "order": 1},
    {"key": "reviewing", "label": "评审中", "status": "pending", "order": 2},
    {"key": "developing", "label": "开发中", "status": "pending", "order": 3},
    {"key": "testing", "label": "测试中", "status": "pending", "order": 4},
    {"key": "code_review", "label": "代码审查", "status": "pending", "order": 5},
    {"key": "releasing", "label": "发布中", "status": "pending", "order": 6},
    {"key": "done", "label": "已完成", "status": "pending", "order": 7},
]

DEFAULT_SPEC_SECTIONS = [
    {"key": "overview", "label": "概述", "content": ""},
    {"key": "acceptance", "label": "验收标准", "content": ""},
    {"key": "tech_notes", "label": "技术备注", "content": ""},
]


class RequirementCreate(BaseModel):
    title: str
    priority: str = "medium"
    source_type: str = "manual"
    source_payload: Optional[dict] = None
    description: Optional[str] = None


def _build_item(row, include_spec: bool = False) -> dict:
    """Build a requirement response dict from a database row.

    *include_spec* controls whether the full spec JSONB is attached
    (used by the detail endpoint but excluded from list responses for
    bandwidth reasons).
    """
    spec = row["spec"] if isinstance(row.get("spec"), dict) else {}

    # ── Pipeline stages: map backend format → frontend format ─────
    raw_stages = spec.get("stages") or DEFAULT_STAGES
    stages = []
    for s in raw_stages:
        stages.append({
            "name": s.get("label", s.get("name", "")),
            "status": "done" if s.get("status") in ("done", "active") else ("in_progress" if s.get("status") == "active" else s.get("status", "pending")),
            "duration": s.get("duration", "-"),
            "baseline": s.get("baseline", "1h"),
            "assignee": s.get("assignee", "-"),
        })

    # ── Spec sections: include from spec JSONB ──────────────────────
    raw_sections = spec.get("spec_sections", spec.get("sections", DEFAULT_SPEC_SECTIONS))
    spec_sections = []
    for s in raw_sections:
        spec_sections.append({
            "id": s.get("key", s.get("id", "")),
            "title": s.get("label", s.get("title", "")),
            "status": s.get("status", "pending"),
            "content": s.get("content", ""),
            "history": s.get("history", []),
        })

    item: dict = {
        "id": str(row["id"]),
        "external_id": row.get("external_id"),
        "title": row["title"],
        "status": row["status"],
        "priority": row["priority"],
        "current_gate": row.get("current_gate"),
        "ai_completion": row.get("ai_completion"),
        "human_interventions": row.get("human_interventions"),
        "blocked": row.get("blocked"),
        "source_type": row.get("source_type"),
        # ── New fields (SPEC-40) ──────────────────────────────────────
        "stages": stages,
        "specSections": spec_sections,          # camelCase for frontend
        "spec_sections": spec_sections,          # snake_case for backward compat
        "assignees": row.get("assignees") if isinstance(row.get("assignees"), list) else [],
        "pm": row.get("pm") or "",
        "description": row.get("description") or "",
        "sla_deadline": row["sla_deadline"].isoformat() if row.get("sla_deadline") else None,
        "related_ids": row.get("related_ids") if isinstance(row.get("related_ids"), list) else [],
        # ── End new fields ────────────────────────────────────────────
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }
    if include_spec:
        item["spec"] = spec
        item["tasks"] = row.get("tasks") if isinstance(row.get("tasks"), list) else []
        item["block_reason"] = row.get("block_reason")
        item["version"] = row.get("version")
        item["source_payload"] = (
            row.get("source_payload") if isinstance(row.get("source_payload"), dict) else {}
        )
    return item


async def get_db() -> asyncpg.Connection:
    from main import DB_POOL
    return await DB_POOL.acquire()


# ── Columns selected by list / detail queries ─────────────────────────────
_BASE_COLS = """
    id, external_id, title, status, priority, current_gate,
    ai_completion, human_interventions, blocked, source_type,
    spec, description, pm, assignees, sla_deadline, related_ids,
    created_at, updated_at
"""


@router.get("")
async def list_requirements(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = await get_db()
    try:
        conditions = []
        params = []
        idx = 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if priority:
            conditions.append(f"priority = ${idx}")
            params.append(priority)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT {_BASE_COLS}
            FROM requirements
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )
        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) as cnt FROM requirements {where}",
            *params[: idx - 1 if conditions else 0],
        )
        total = total_row["cnt"] if total_row else 0

        items = [_build_item(row) for row in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        await conn.close()


@router.post("")
async def create_requirement(body: RequirementCreate):
    conn = await get_db()
    try:
        new_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Build the spec JSONB with default stages and spec_sections
        spec_payload = {
            "source": body.source_type,
            "stages": DEFAULT_STAGES,
            "spec_sections": DEFAULT_SPEC_SECTIONS,
        }
        if body.source_payload:
            spec_payload["source_payload"] = body.source_payload

        row = await conn.fetchrow(
            """
            INSERT INTO requirements (id, title, status, priority, current_gate,
                spec, tasks, ai_completion, human_interventions, blocked, version,
                source_type, source_payload, description, created_at, updated_at)
            VALUES ($1, $2, 'pool', $3, 0, $4::jsonb, '[]'::jsonb, 0, 0, false, '1.0',
                    $5, $6::jsonb, $7, $8, $8)
            RETURNING id, external_id, title, status, priority, current_gate,
                      ai_completion, human_interventions, blocked, source_type,
                      spec, description, pm, assignees, sla_deadline, related_ids,
                      created_at, updated_at
            """,
            new_id,
            body.title,
            body.priority,
            json.dumps(spec_payload),
            body.source_type,
            json.dumps(body.source_payload) if body.source_payload else None,
            body.description,
            now,
        )
        return _build_item(row)
    finally:
        await conn.close()


@router.get("/{req_id}")
async def get_requirement_detail(req_id: str):
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            f"""
            SELECT r.*
            FROM requirements r
            WHERE r.id = $1::uuid
            """,
            req_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Requirement not found")

        req = _build_item(row, include_spec=True)

        # Approvals timeline
        ga_rows = await conn.fetch(
            """
            SELECT * FROM gate_approvals
            WHERE req_id = $1::uuid
            ORDER BY created_at DESC
            """,
            req_id,
        )
        approvals = []
        for ga in ga_rows:
            approvals.append({
                "id": str(ga["id"]),
                "gate": ga["gate"],
                "status": ga["status"],
                "approver": ga["approver"],
                "sla_deadline": ga["sla_deadline"].isoformat() if ga["sla_deadline"] else None,
                "agent_reviews": ga["agent_reviews"] if isinstance(ga["agent_reviews"], dict) else {},
                "reject_reasons": ga["reject_reasons"] if isinstance(ga["reject_reasons"], list) else [],
                "created_at": ga["created_at"].isoformat() if ga["created_at"] else None,
                "resolved_at": ga["resolved_at"].isoformat() if ga["resolved_at"] else None,
            })

        # Activity timeline
        act_rows = await conn.fetch(
            """
            SELECT * FROM agent_activities
            WHERE req_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT 50
            """,
            req_id,
        )
        activities = []
        for a in act_rows:
            activities.append({
                "id": str(a["id"]),
                "agent_id": a["agent_id"],
                "agent_type": a["agent_type"],
                "action": a["current_action"],
                "status": a["status"],
                "created_at": a["created_at"].isoformat() if a["created_at"] else None,
            })

        req["approvals"] = approvals
        req["activities"] = activities
        return req
    finally:
        await conn.close()
