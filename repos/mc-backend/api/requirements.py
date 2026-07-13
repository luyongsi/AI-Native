"""
Mission Control Backend - Requirements API
  GET  /api/requirements       - List all requirements
  POST /api/requirements       - Create a new requirement (pre-dialogue req_id)
  GET  /api/requirements/{id}  - Get requirement detail

Aligned with data dictionary v1.3 §3.1 — new requirements table schema.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


# ── Models ──────────────────────────────────────────────────────────────

class RequirementCreate(BaseModel):
    title: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────────────

async def _get_conn() -> asyncpg.Connection:
    from main import DB_POOL
    return await DB_POOL.acquire()


def _jwt_claims(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[7:]
    try:
        import jwt as pyjwt
        claims = pyjwt.decode(token, options={"verify_signature": False})
        return {"sub": claims.get("sub", "dev-user"), "name": claims.get("name", "Dev User")}
    except Exception:
        return {"sub": token[:50], "name": "Dev User"}


def _row_to_dict(row) -> dict:
    """Convert a new-schema requirements row to API response dict."""
    if row is None:
        return {}
    draft = row.get("requirement_draft")
    if isinstance(draft, str):
        try:
            draft = json.loads(draft)
        except (json.JSONDecodeError, TypeError):
            draft = None
    title = row.get("title") or (draft.get("title") if isinstance(draft, dict) else None)
    return {
        "id": str(row["id"]),
        "title": title,
        "status": row["status"],
        "confidence_score": float(row["confidence_score"]) if row.get("confidence_score") else None,
        "requirement_draft": draft,
        "creator_user_id": row.get("creator_user_id"),
        "creator_name": row.get("creator_name"),
        "analyzer_agent": row.get("analyzer_agent"),
        "analyzed_at": row["analyzed_at"].isoformat() if row.get("analyzed_at") else None,
        "gate_rejection_count": row.get("gate_rejection_count", 0),
        "revision_count": row.get("revision_count", 0),
        "last_revised_at": row["last_revised_at"].isoformat() if row.get("last_revised_at") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


# ══════════════════════════════════════════════════════════════════════════

@router.post("")
async def create_requirement(body: RequirementCreate, claims: dict = Depends(_jwt_claims)):
    """Create a requirement record, returning req_id for subsequent dialogue.

    Per data dictionary §1.2: user clicks "创建需求" → creates requirements row (status='draft').
    Dialogue begins via POST /api/dialogue/chat which creates dialogue_sessions.
    """
    conn = await _get_conn()
    try:
        new_id = uuid.uuid4()
        creator_id = claims.get("sub", "dev-user")
        creator_name = claims.get("name", "Dev User")

        title = body.title or None
        draft = {"title": title} if title else {}

        await conn.execute(
            """INSERT INTO requirements
               (id, title, status, requirement_draft, creator_user_id, creator_name)
               VALUES ($1::uuid, $2, 'draft', $3::jsonb, $4, $5)""",
            new_id,
            title,
            json.dumps(draft, ensure_ascii=False),
            creator_id,
            creator_name,
        )
        row = await conn.fetchrow(
            "SELECT * FROM requirements WHERE id = $1::uuid", new_id,
        )
        result = _row_to_dict(row)
        # Return with req_id alias for frontend compatibility
        result["req_id"] = result["id"]
        result["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
        return result
    finally:
        await conn.close()


@router.get("")
async def list_requirements(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    claims: dict = Depends(_jwt_claims),
):
    """List requirements with optional status filter."""
    conn = await _get_conn()
    try:
        conditions = []
        params: list = []
        idx = 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""SELECT * FROM requirements
               {where}
               ORDER BY created_at DESC
               LIMIT ${idx} OFFSET ${idx + 1}""",
            *params,
        )
        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) as cnt FROM requirements {where}",
            *params[: idx - 1 if conditions else 0],
        )
        total = total_row["cnt"] if total_row else 0

        return {
            "items": [_row_to_dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        await conn.close()


@router.get("/{req_id}")
async def get_requirement_detail(req_id: str, claims: dict = Depends(_jwt_claims)):
    """Get requirement detail with associated data."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM requirements WHERE id = $1::uuid", req_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Requirement not found")

        result = _row_to_dict(row)

        # Load agent_results
        ar_rows = await conn.fetch(
            "SELECT agent_key, cycle, status, artifact FROM agent_results "
            "WHERE req_id = $1::uuid ORDER BY cycle, agent_key",
            req_id,
        )
        result["agent_results"] = [
            {
                "agent_key": r["agent_key"],
                "cycle": r["cycle"],
                "status": r["status"],
                "artifact": r["artifact"] if isinstance(r["artifact"], dict) else {},
            }
            for r in ar_rows
        ]

        # Load approvals
        ap_rows = await conn.fetch(
            "SELECT * FROM approvals WHERE req_id = $1::uuid ORDER BY cycle, created_at",
            req_id,
        )
        result["approvals"] = [
            {
                "id": str(r["id"]),
                "gate_level": r["gate_level"],
                "cycle": r["cycle"],
                "status": r["status"],
                "decision": r["decision"],
                "reject_reasons": r["reject_reasons"] if isinstance(r.get("reject_reasons"), list) else [],
                "revision_guidance": r.get("revision_guidance"),
                "reviewer_name": r.get("reviewer_name"),
                "reviewed_at": r["reviewed_at"].isoformat() if r.get("reviewed_at") else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in ap_rows
        ]

        # Load event_log entries for activity timeline
        el_rows = await conn.fetch(
            "SELECT id, event_name, direction, created_at FROM event_log "
            "WHERE req_id = $1::uuid ORDER BY created_at DESC LIMIT 50",
            req_id,
        )
        result["activities"] = [
            {
                "id": r["id"],
                "event": r["event_name"],
                "direction": r["direction"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in el_rows
        ]

        return result
    finally:
        await conn.close()
