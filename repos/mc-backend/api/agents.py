"""
Mission Control Backend - Agents API
GET /api/agents                - Returns recent 50 agent activities
GET /api/agents/{agent_id}/diffs - Code diffs for an agent (SPEC-41b)

Phase 4A (SPEC-41): Computed fields — tool_calls_count, tool_calls_success,
tool_calls_failed, last_activity, runtime_seconds.
Phase 4A (SPEC-41b): Code-diff endpoint per agent.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime
import uuid
import json

router = APIRouter(prefix="/api/agents", tags=["agents"])


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


# ── Helpers ───────────────────────────────────────────────────────────────

def _count_tool_calls(tool_calls_json) -> int:
    """Return the length of tool_calls_json if it is a dict, else 0."""
    if isinstance(tool_calls_json, dict):
        return len(tool_calls_json)
    return 0


def _language_from_filename(filename: str) -> str:
    """Guess a programming language from a file extension."""
    ext_map = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".sql": "sql",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".css": "css",
        ".html": "html",
        ".md": "markdown",
    }
    for ext, lang in ext_map.items():
        if filename.endswith(ext):
            return lang
    return "text"


# ── Mock diffs for dev mode (when no real code-gen data exists) ───────────

_MOCK_DIFFS: dict = {
    "A1": [
        {
            "file": "repos/mc-backend/api/requirements.py",
            "addedLines": 45,
            "removedLines": 12,
            "hunks": [
                {
                    "oldStart": 70, "oldLines": 7, "newStart": 70, "newLines": 14,
                    "content": " @@ -70,7 +70,14 @@\n     ...\n+    # New extended fields\n+    \"stages\": stages,\n+    \"spec_sections\": spec_sections,\n+    \"assignees\": row.get(\"assignees\") or [],"
                }
            ]
        },
        {
            "file": "repos/infra/alembic/versions/002_requirements_extended.py",
            "addedLines": 38,
            "removedLines": 0,
            "hunks": [
                {
                    "oldStart": 0, "oldLines": 0, "newStart": 1, "newLines": 38,
                    "content": " @@ -0,0 +1,38 @@\n+ \"\"\"002_requirements_extended ...\n+ ..."
                }
            ]
        }
    ],
    "A2": [
        {
            "file": "repos/mc-backend/api/agents.py",
            "addedLines": 28,
            "removedLines": 5,
            "hunks": [
                {
                    "oldStart": 44, "oldLines": 10, "newStart": 44, "newLines": 18,
                    "content": " @@ -44,10 +44,18 @@\n     ...\n+    \"tool_calls_count\": tc_count,\n+    \"tool_calls_success\": 0,\n+    \"last_activity\": created_at"
                }
            ]
        }
    ],
    "A3": [
        {
            "file": "repos/mc-backend/api/insights.py",
            "addedLines": 52,
            "removedLines": 3,
            "hunks": [
                {
                    "oldStart": 95, "oldLines": 8, "newStart": 95, "newLines": 55,
                    "content": " @@ -95,8 +95,55 @@\n     ...\n+    # Trends: 12-week cycle_time history\n+    trend_rows = await conn.fetch(...)"
                }
            ]
        }
    ],
}

# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("")
async def list_agent_activities(
    agent_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    conn = await get_db()
    try:
        params = []
        conditions = []
        idx = 1
        if agent_type:
            conditions.append(f"agent_type = ${idx}")
            params.append(agent_type)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params.append(limit)
        rows = await conn.fetch(
            f"""
            SELECT id, agent_id, agent_type, req_id, task_id, status,
                   current_action, tool_calls_json, code_added, code_removed,
                   anomaly, session_id, cost_usd, created_at
            FROM agent_activities
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        items = []
        for row in rows:
            tc_json = row["tool_calls_json"] if isinstance(row["tool_calls_json"], dict) else {}
            tc_count = _count_tool_calls(tc_json)
            items.append({
                "id": str(row["id"]),
                "agent_id": row["agent_id"],
                "agent_type": row["agent_type"],
                "req_id": str(row["req_id"]) if row["req_id"] else None,
                "task_id": row["task_id"],
                "status": row["status"],
                "current_action": row["current_action"],
                "tool_calls_json": tc_json if tc_json else {},
                "code_added": row["code_added"],
                "code_removed": row["code_removed"],
                "anomaly": row["anomaly"],
                "session_id": row["session_id"],
                "cost_usd": float(row["cost_usd"]) if row["cost_usd"] else 0.0,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                # ── SPEC-41: Computed fields ──────────────────────────
                "tool_calls_count": tc_count,
                "tool_calls_success": 0,   # placeholder; computed from tool_calls_json in future
                "tool_calls_failed": 0,    # placeholder
                "last_activity": row["created_at"].isoformat() if row["created_at"] else None,
                "runtime_seconds": None,   # placeholder; computed from session duration in future
                # ── End computed fields ───────────────────────────────
            })
        return {"items": items, "total": len(items)}
    finally:
        await conn.close()


@router.get("/{agent_id}/diffs")
async def get_agent_diffs(agent_id: str):
    """Return code diffs for an agent.

    In dev mode (no real data), returns mock diffs. When real data exists,
    extracts diffs from tool_calls_json for actions matching 'code_gen'.
    """
    conn = await get_db()
    try:
        # Try to find real diffs from agent_activities
        rows = await conn.fetch(
            """
            SELECT id, tool_calls_json, current_action, created_at
            FROM agent_activities
            WHERE agent_id = $1
              AND current_action = 'code_gen'
            ORDER BY created_at DESC
            LIMIT 10
            """,
            agent_id,
        )

        diffs = []
        if rows:
            for row in rows:
                tc_json = row["tool_calls_json"] if isinstance(row["tool_calls_json"], dict) else {}
                if not tc_json:
                    continue
                # Walk through tool calls looking for file-editing results
                for call_key, call_val in tc_json.items():
                    if not isinstance(call_val, dict):
                        continue
                    path = call_val.get("path") or call_val.get("file") or ""
                    if not path:
                        continue
                    added = call_val.get("addedLines") or call_val.get("lines_added") or 0
                    removed = call_val.get("removedLines") or call_val.get("lines_removed") or 0
                    hunks = call_val.get("hunks") or call_val.get("diff_hunks") or []
                    diffs.append({
                        "id": str(row["id"]),
                        "agentId": agent_id,
                        "file": path,
                        "language": _language_from_filename(path),
                        "addedLines": int(added),
                        "removedLines": int(removed),
                        "hunks": hunks if isinstance(hunks, list) else [],
                    })
                if diffs:
                    break  # take the most recent activity with diffs

        # Fall back to mock data in dev mode
        if not diffs and agent_id in _MOCK_DIFFS:
            for mock_diff in _MOCK_DIFFS[agent_id]:
                diffs.append({
                    "id": str(uuid.uuid4()),
                    "agentId": agent_id,
                    "file": mock_diff["file"],
                    "language": _language_from_filename(mock_diff["file"]),
                    "addedLines": mock_diff["addedLines"],
                    "removedLines": mock_diff["removedLines"],
                    "hunks": mock_diff["hunks"],
                })

        return {"agent_id": agent_id, "diffs": diffs}
    finally:
        await conn.close()
