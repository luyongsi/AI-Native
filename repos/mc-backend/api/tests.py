"""
Mission Control Backend - Tests API
GET /api/tests/{req_id} - Test insight panel: summary of test executions for a requirement.
"""
from fastapi import APIRouter, HTTPException
from typing import Any

router = APIRouter(prefix="/api/tests", tags=["tests"])


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


@router.get("/{req_id}")
async def get_test_insights(req_id: str):
    conn = await get_db()
    try:
        # Verify requirement exists
        req = await conn.fetchrow(
            "SELECT id, title FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not req:
            raise HTTPException(status_code=404, detail="Requirement not found")

        # Latest test execution summary
        latest = await conn.fetchrow(
            """
            SELECT * FROM test_executions
            WHERE req_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT 1
            """,
            req_id,
        )

        # Round-by-round history
        rounds = await conn.fetch(
            """
            SELECT round, total_cases, passed, failed, skipped, coverage,
                   ai_generated_ratio, quality_score, created_at
            FROM test_executions
            WHERE req_id = $1::uuid
            ORDER BY round ASC
            """,
            req_id,
        )

        rounds_data = []
        for r in rounds:
            rounds_data.append({
                "round": r["round"],
                "total_cases": r["total_cases"],
                "passed": r["passed"],
                "failed": r["failed"],
                "skipped": r["skipped"],
                "coverage": float(r["coverage"]) if r["coverage"] else 0.0,
                "ai_generated_ratio": float(r["ai_generated_ratio"]) if r["ai_generated_ratio"] else 0.0,
                "quality_score": r["quality_score"] if isinstance(r["quality_score"], dict) else {},
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })

        return {
            "req_id": req_id,
            "req_title": req["title"],
            "latest": {
                "id": str(latest["id"]) if latest else None,
                "round": latest["round"] if latest else None,
                "total_cases": latest["total_cases"] if latest else 0,
                "passed": latest["passed"] if latest else 0,
                "failed": latest["failed"] if latest else 0,
                "skipped": latest["skipped"] if latest else 0,
                "coverage": float(latest["coverage"]) if latest and latest["coverage"] else 0.0,
                "ai_generated_ratio": float(latest["ai_generated_ratio"]) if latest and latest["ai_generated_ratio"] else 0.0,
                "quality_score": latest["quality_score"] if latest and isinstance(latest["quality_score"], dict) else {},
                "failed_cases": latest["failed_cases"] if latest and isinstance(latest["failed_cases"], list) else [],
                "traces": latest["traces"] if latest and isinstance(latest["traces"], list) else [],
                "visual_diffs": latest["visual_diffs"] if latest and isinstance(latest["visual_diffs"], list) else [],
                "created_at": latest["created_at"].isoformat() if latest and latest["created_at"] else None,
            } if latest else None,
            "rounds": rounds_data,
        }
    finally:
        await conn.close()
