"""Cleanup module — safely removes test data from DB, filesystem, and Temporal.

Design:
  - Only removes data with external_id LIKE 'TEST-%'
  - Delayed cleanup (300s) to allow NATS ack window to close
  - Agent-side defense: if req_id not in DB, silently skip (handled in base_worker)
  - Orphan cleanup on server startup for crash recovery
"""

import asyncio
import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

TEST_EXTERNAL_ID_PREFIX = "TEST-"


# ══════════════════════════════════════════════════════════════════════
# Database cleanup
# ══════════════════════════════════════════════════════════════════════

async def cleanup_test_requirement(db_pool: asyncpg.Pool, req_id: str) -> dict:
    """Clean a single test requirement and all its related records. Returns stats."""
    stats: dict[str, int] = {}

    async with db_pool.acquire() as conn:
        # Safety check: verify this is test data
        row = await conn.fetchrow(
            "SELECT external_id FROM requirements WHERE id=$1::uuid", req_id
        )
        if not row:
            return {"error": f"req_id {req_id} not found"}
        if not (row["external_id"] or "").startswith(TEST_EXTERNAL_ID_PREFIX):
            return {"error": f"req_id {req_id} is not test data (external_id={row['external_id']}), refusing to delete"}

        # Delete in FK dependency order
        tables = [
            "test_executions",
            "gate_approvals",
            "agent_activities",
            "api_schemas",
            "erd_designs",
        ]

        for table in tables:
            result = await conn.execute(
                f"DELETE FROM {table} WHERE req_id=$1::uuid", req_id
            )
            count = _parse_delete_count(result)
            if count > 0:
                stats[table] = count

        # Main record last
        result = await conn.execute(
            "DELETE FROM requirements WHERE id=$1::uuid", req_id
        )
        stats["requirements"] = _parse_delete_count(result)

    logger.info(f"Cleaned test data: req_id={req_id}, tables={stats}")
    return {"req_id": req_id, "cleaned": True, "tables": stats}


async def cleanup_all_test_data(db_pool: asyncpg.Pool) -> dict:
    """Remove all TEST- requirements and their related records."""
    stats: dict[str, int] = {}

    async with db_pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM requirements WHERE external_id LIKE $1",
            f"{TEST_EXTERNAL_ID_PREFIX}%",
        )
        if total == 0:
            return {"cleaned": False, "message": "no test data found", "total_found": 0}

        # Get all test req_ids
        rows = await conn.fetch(
            "SELECT id FROM requirements WHERE external_id LIKE $1",
            f"{TEST_EXTERNAL_ID_PREFIX}%",
        )
        test_ids = [r["id"] for r in rows]

        tables = [
            "test_executions",
            "gate_approvals",
            "agent_activities",
            "api_schemas",
            "erd_designs",
        ]

        for table in tables:
            for tid in test_ids:
                result = await conn.execute(
                    f"DELETE FROM {table} WHERE req_id=$1::uuid", tid
                )
                stats[table] = stats.get(table, 0) + _parse_delete_count(result)

        result = await conn.execute(
            "DELETE FROM requirements WHERE external_id LIKE $1",
            f"{TEST_EXTERNAL_ID_PREFIX}%",
        )
        stats["requirements"] = _parse_delete_count(result)

    logger.info(f"Batch cleanup: {total} requirements removed, tables={stats}")
    return {"cleaned": True, "total_requirements": total, "tables": stats}


async def cleanup_orphan_test_data(db_pool: asyncpg.Pool,
                                   max_age_hours: int = 24) -> dict:
    """Remove stale test data (crashed / kill -9 residue). Call on server startup."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, external_id FROM requirements "
            "WHERE external_id LIKE $1 AND created_at < $2",
            f"{TEST_EXTERNAL_ID_PREFIX}%", cutoff,
        )

        if not rows:
            return {"cleaned": False, "message": f"no orphan data older than {max_age_hours}h"}

        cleaned = 0
        for row in rows:
            result = await cleanup_test_requirement(db_pool, row["id"])
            if result.get("cleaned"):
                cleaned += 1

        return {
            "cleaned": True,
            "orphans_found": len(rows),
            "orphans_cleaned": cleaned,
            "max_age_hours": max_age_hours,
        }


# ══════════════════════════════════════════════════════════════════════
# Filesystem cleanup
# ══════════════════════════════════════════════════════════════════════

def cleanup_worktrees(worktree_base: str = "/tmp/a9-runtimes",
                      max_age_minutes: int = 120) -> dict:
    """Remove stale A9 git worktree directories."""
    path = Path(worktree_base)
    if not path.exists():
        return {"cleaned": False, "message": f"directory not found: {worktree_base}"}

    now = datetime.now().timestamp()
    cleaned = []
    errors = []
    total_size_freed = 0

    for wt_dir in path.iterdir():
        if not wt_dir.is_dir():
            continue
        if not (wt_dir.name.startswith("wt-") or wt_dir.name.startswith("wt-a9rt-")):
            continue

        age_min = (now - wt_dir.stat().st_mtime) / 60
        if age_min > max_age_minutes:
            try:
                dir_size = sum(f.stat().st_size for f in wt_dir.rglob("*") if f.is_file())
                shutil.rmtree(wt_dir)
                cleaned.append({"name": wt_dir.name, "age_minutes": round(age_min)})
                total_size_freed += dir_size
                logger.info(f"Cleaned worktree: {wt_dir.name} (age={age_min:.0f}m, size={dir_size / 1024:.0f}KB)")
            except Exception as e:
                errors.append({"name": wt_dir.name, "error": str(e)})

    return {
        "cleaned": len(cleaned) > 0,
        "removed_count": len(cleaned),
        "errors": errors,
        "total_size_freed_kb": round(total_size_freed / 1024),
        "details": cleaned,
    }


def cleanup_llm_call_logs(req_id: str, log_base: str = "/opt/ai-native/logs/llm_calls") -> dict:
    """Remove LLM call audit log files for a specific req_id."""
    req_dir = Path(log_base) / req_id[:8]
    if not req_dir.exists():
        return {"cleaned": False, "message": f"directory not found: {req_dir}"}

    deleted = 0
    prefix = req_id[:8]
    for f in req_dir.glob(f"*{prefix}*.json"):
        f.unlink()
        deleted += 1

    if not any(req_dir.iterdir()):
        req_dir.rmdir()

    return {"cleaned": deleted > 0, "files_deleted": deleted, "path": str(req_dir)}


# ══════════════════════════════════════════════════════════════════════
# Full cleanup
# ══════════════════════════════════════════════════════════════════════

async def full_test_cleanup(
    db_pool: asyncpg.Pool,
    temporal_client,
    req_id: str,
    workflow_id: str | None = None,
    keep_data: bool = False,
) -> dict:
    """Comprehensive cleanup entry point. Called by Observer.finally."""
    if keep_data:
        logger.info(f"keep_data=True, preserving test data: req_id={req_id}")
        return {"skipped": True, "reason": "keep_data", "req_id": req_id}

    report: dict = {"req_id": req_id, "workflow_id": workflow_id}

    # 1. Terminate Temporal workflow
    if workflow_id and temporal_client:
        from utils.temporal_client import terminate_workflow
        report["temporal"] = await terminate_workflow(temporal_client, workflow_id)

    # 2. Clean database
    report["database"] = await cleanup_test_requirement(db_pool, req_id)

    # 3. Clean LLM audit logs
    report["llm_logs"] = cleanup_llm_call_logs(req_id)

    # 4. Clean stale worktrees
    report["worktrees"] = cleanup_worktrees()

    logger.info(
        "Full cleanup complete: req_id=%s db_cleaned=%s llm_files=%s",
        req_id,
        report["database"].get("cleaned"),
        report["llm_logs"].get("files_deleted", 0),
    )
    return report


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _parse_delete_count(result: str) -> int:
    """asyncpg DELETE returns 'DELETE N', parse N."""
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
