"""Database utilities for the testing tool."""

import os
import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"
)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def fetch_requirement(req_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, external_id, title, status, spec, source_payload, "
            "created_at, updated_at FROM requirements WHERE id=$1::uuid",
            req_id,
        )
        if not row:
            return None
        spec = row["spec"]
        if isinstance(spec, str):
            import json
            try:
                spec = json.loads(spec)
            except (json.JSONDecodeError, TypeError):
                spec = {}
        return {
            "id": str(row["id"]),
            "external_id": row["external_id"],
            "title": row["title"],
            "status": row["status"],
            "spec": spec if isinstance(spec, dict) else {},
            "source_payload": row["source_payload"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


async def insert_requirement(req_id: str, external_id: str, title: str,
                             description: str = "", priority: str = "medium",
                             source_type: str = "manual") -> None:
    pool = await get_pool()
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    spec_payload = {
        "source": source_type,
        "stages": [],
        "spec_sections": [],
    }
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO requirements
               (id, external_id, title, status, priority, current_gate,
                spec, tasks, ai_completion, human_interventions, blocked,
                version, source_type, source_payload, description,
                created_at, updated_at)
               VALUES ($1, $2, $3, 'draft', $4, 0,
                       $5::jsonb, '[]'::jsonb, 0, 0, false,
                       '1.0', $6, $7::jsonb, $8, $9, $9)""",
            req_id, external_id, title, priority,
            json.dumps(spec_payload), source_type,
            json.dumps({}), description, now,
        )


def flatten_spec(spec_raw) -> dict:
    """Normalize spec for snapshot use."""
    import json
    if spec_raw is None:
        return {}
    if isinstance(spec_raw, str):
        try:
            return json.loads(spec_raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return spec_raw if isinstance(spec_raw, dict) else {}
