"""store_agent_result Activity — persist Agent result to agent_results table."""

import json
import logging
import os
from pathlib import Path

import asyncpg
from temporalio import activity

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"
)

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


@activity.defn(name="store_agent_result")
async def store_agent_result(req_id: str, agent_id: str, result: dict) -> dict:
    """Persist an Agent's output to agent_results table.

    Uses (req_id, agent_key, cycle) unique constraint — ON CONFLICT
    upserts to handle retries idempotently.
    """
    activity.logger.info(
        "store_agent_result req=%s agent=%s", req_id, agent_id,
    )

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Determine current cycle from agent_results (MAX cycle for this agent)
        cycle = await conn.fetchval(
            "SELECT COALESCE(MAX(cycle), 0) FROM agent_results "
            "WHERE req_id = $1::uuid AND agent_key = $2",
            req_id, agent_id,
        )
        cycle = cycle or 0

        await conn.execute(
            """INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
               VALUES ($1::uuid, $2, $3, 'completed', $4::jsonb)
               ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
               SET artifact = $4::jsonb, status = 'completed', created_at = NOW()""",
            req_id, agent_id, cycle, json.dumps(result, ensure_ascii=False),
        )

    return {"ok": True, "req_id": req_id, "agent_id": agent_id, "cycle": cycle}
