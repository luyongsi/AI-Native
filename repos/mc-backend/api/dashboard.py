"""
Mission Control Backend - Dashboard Stats API
GET /api/dashboard/stats - Returns requirement pipeline status counts.
"""
import logging
from fastapi import APIRouter
import asyncpg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

VALID_STATUSES = ["pool", "designing", "developing", "testing", "releasing"]


async def get_db() -> asyncpg.Connection:
    from main import DB_POOL
    return await DB_POOL.acquire()


@router.get("/stats")
async def dashboard_stats():
    """Return requirement pipeline status counts, with zero fallback on errors."""
    try:
        conn = await get_db()
        try:
            rows = await conn.fetch("""
                SELECT status, COUNT(*)::int AS cnt
                FROM requirements
                GROUP BY status
            """)
            status_map = {row["status"]: row["cnt"] for row in rows}
            stats = {s: status_map.get(s, 0) for s in VALID_STATUSES}
            stats["total"] = sum(stats.values())
            return stats
        finally:
            await conn.close()
    except Exception as e:
        logger.warning(f"[dashboard] DB query failed, returning zeros: {e}")
        stats = {s: 0 for s in VALID_STATUSES}
        stats["total"] = 0
        return stats
