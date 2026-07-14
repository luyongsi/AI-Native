"""
Mission Control Backend — Agent Results API

POST /api/agent_results — Persist agent output (UPSERT by req_id + agent_key + cycle).
Aligned with data dictionary §3.2 agent_results table.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent_results", tags=["agent_results"])


class AgentResultBody(BaseModel):
    req_id: str
    agent_key: str = Field(..., description="e.g. A1, A2, A3")
    cycle: int = 0
    status: str = Field(..., description="completed | empty | skipped")
    artifact: dict = Field(default_factory=dict)


class AgentResultResponse(BaseModel):
    ok: bool
    req_id: str
    agent_key: str
    cycle: int
    status: str
    created: bool  # True = INSERT, False = UPDATE


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


@router.post("", response_model=AgentResultResponse)
async def upsert_agent_result(body: AgentResultBody):
    """Insert or update an agent result.

    Idempotent: same (req_id, agent_key, cycle) updates existing row.
    """
    if body.status not in ("completed", "empty", "skipped"):
        raise HTTPException(status_code=400, detail="status must be one of: completed, empty, skipped")

    conn = await get_db()
    try:
        now = datetime.now(timezone.utc)

        existing = await conn.fetchrow(
            """SELECT id FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = $2 AND cycle = $3""",
            body.req_id, body.agent_key, body.cycle,
        )

        if existing:
            await conn.execute(
                """UPDATE agent_results
                   SET status = $1, artifact = $2::jsonb, created_at = $3
                   WHERE req_id = $4::uuid AND agent_key = $5 AND cycle = $6""",
                body.status, body.artifact, now,
                body.req_id, body.agent_key, body.cycle,
            )
            return AgentResultResponse(
                ok=True,
                req_id=body.req_id,
                agent_key=body.agent_key,
                cycle=body.cycle,
                status=body.status,
                created=False,
            )

        await conn.execute(
            """INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact, created_at)
               VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6)""",
            body.req_id, body.agent_key, body.cycle,
            body.status, body.artifact, now,
        )
        return AgentResultResponse(
            ok=True,
            req_id=body.req_id,
            agent_key=body.agent_key,
            cycle=body.cycle,
            status=body.status,
            created=True,
        )
    finally:
        await conn.close()
