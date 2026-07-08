"""store_agent_result Activity — persist agent output to requirements.spec.artifacts.

Writes agent output to requirements.spec.artifacts.{agent_id} JSONB.
A4 is excluded (it writes its own output directly to requirements.spec).
"""

import json
import logging
import os

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
    """Persist agent output into requirements.spec.artifacts JSONB.

    Uses jsonb_set with create_missing=true so the artifacts key is
    auto-created if it doesn't exist yet. COALESCE handles NULL spec.

    Args:
        req_id: Requirement UUID.
        agent_id: Agent ID string (e.g. "A1", "A6", "A12").
        result: The agent's output dict to persist.

    Returns:
        dict with ok, req_id, agent_id.
    """
    activity.logger.info(
        "store_agent_result req=%s agent=%s", req_id, agent_id,
    )

    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Read current spec, merge artifacts in Python, write back.
        row = await conn.fetchrow(
            "SELECT COALESCE(spec::text, '{}') AS spec_text FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        spec = {}
        if row and row["spec_text"]:
            try:
                spec = json.loads(row["spec_text"])
            except (json.JSONDecodeError, TypeError):
                spec = {}
        if not isinstance(spec, dict):
            spec = {}

        artifacts = spec.get("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts = {}

        # For large results (>100KB), store to a file and keep a pointer in DB
        result_json = json.dumps(result, ensure_ascii=False)
        if len(result_json) > 100_000:
            _write_artifact_file(req_id, agent_id, result)
            artifacts[agent_id] = {
                "_file_ref": f"/opt/ai-native/data/artifacts/{req_id}/{agent_id}.json",
                "size": len(result_json),
            }
        else:
            artifacts[agent_id] = result
        spec["artifacts"] = artifacts

        await conn.execute(
            "UPDATE requirements SET spec = $2::jsonb, updated_at = NOW() WHERE id = $1::uuid",
            req_id,
            json.dumps(spec),
        )
        activity.logger.info(
            "store_agent_result: persisted req=%s agent=%s", req_id, agent_id,
        )

    return {"ok": True, "req_id": req_id, "agent_id": agent_id}


def _write_artifact_file(req_id: str, agent_id: str, result: dict):
    """Write a large artifact to a JSON file on disk."""
    from pathlib import Path
    base = Path(os.environ.get("AI_NATIVE_DATA_DIR", "/opt/ai-native/data"))
    dir_path = base / "artifacts" / req_id
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{agent_id}.json"
    file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("store_agent_result: wrote large artifact to %s", file_path)
