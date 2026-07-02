"""
Mission Control Backend - Insights / Efficiency Dashboard API
GET /api/insights - Returns efficiency dashboard metrics.

Phase 4A (SPEC-43): Extended with trends (12-week cycle_time history),
ai_vs_human comparison, total_requirements, active_agents, avg_loop_rounds.
When historical data is empty, falls back to sample values.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/insights", tags=["insights"])


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


@router.get("")
async def get_insights():
    conn = await get_db()
    try:
        req_count = await conn.fetchrow("SELECT COUNT(*) as cnt FROM requirements")
        act_count = await conn.fetchrow("SELECT COUNT(*) as cnt FROM agent_activities")
        has_data = (req_count["cnt"] > 0 if req_count else False) or (act_count["cnt"] > 0 if act_count else False)

        if not has_data:
            # Return sample values consistent with spec-03 doc
            return {
                "cycle_time_days": 2.3,
                "throughput": {"weekly": 6, "monthly": 22},
                "ai_contribution_pct": 68,
                "code_quality_score": 92,
                "bug_escape_rate_pct": 3.2,
                "bottleneck_distribution": {
                    "pool": 15,
                    "designing": 30,
                    "developing": 35,
                    "testing": 15,
                    "releasing": 5,
                },
                # ── SPEC-43 new fields (sample fallback) ─────────────
                "total_requirements": 0,
                "active_agents": 0,
                "avg_loop_rounds": 0,
                "ai_vs_human": {"ai_driven": 0, "human_driven": 0},
                "trends": [],
                # ── End new fields ───────────────────────────────────
                "source": "sample",
            }

        # ── Cycle time ─────────────────────────────────────────────────
        cycle_row = await conn.fetchrow(
            """
            SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 86400) AS cycle_days
            FROM requirements
            WHERE status = 'releasing'
            """
        )
        cycle_time = round(float(cycle_row["cycle_days"]), 1) if cycle_row and cycle_row["cycle_days"] else 2.3

        # ── Throughput ─────────────────────────────────────────────────
        wk = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM requirements WHERE created_at >= NOW() - INTERVAL '7 days'"
        )
        mo = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM requirements WHERE created_at >= NOW() - INTERVAL '30 days'"
        )
        throughput = {
            "weekly": wk["cnt"] if wk else 0,
            "monthly": mo["cnt"] if mo else 0,
        }

        # ── AI contribution ─────────────────────────────────────────────
        ai_row = await conn.fetchrow("SELECT AVG(ai_completion) as avg_ai FROM requirements")
        ai_contribution = round(float(ai_row["avg_ai"]), 1) if ai_row and ai_row["avg_ai"] else 68.0

        # ── Code quality ────────────────────────────────────────────────
        cov_row = await conn.fetchrow(
            "SELECT AVG(coverage) as avg_coverage FROM test_executions"
        )
        quality = round(float(cov_row["avg_coverage"]), 1) if cov_row and cov_row["avg_coverage"] else 92.0

        # ── Bug escape ──────────────────────────────────────────────────
        bug_row = await conn.fetchrow(
            """
            SELECT CASE WHEN SUM(total_cases) > 0
                THEN ROUND(SUM(failed)::decimal / SUM(total_cases)::decimal * 100, 1)
                ELSE 0 END AS bug_rate
            FROM test_executions
            """
        )
        bug_rate = float(bug_row["bug_rate"]) if bug_row else 3.2

        # ── Bottleneck distribution ─────────────────────────────────────
        status_rows = await conn.fetch(
            "SELECT status, COUNT(*)::int as cnt FROM requirements GROUP BY status"
        )
        status_map = {r["status"]: r["cnt"] for r in status_rows}
        bottleneck = {
            "pool": status_map.get("pool", 0),
            "designing": status_map.get("designing", 0),
            "developing": status_map.get("developing", 0),
            "testing": status_map.get("testing", 0),
            "releasing": status_map.get("releasing", 0),
        }

        # ── SPEC-43: Total requirements ─────────────────────────────────
        total_req = req_count["cnt"] if req_count else 0

        # ── SPEC-43: Active agents ─────────────────────────────────────
        active_row = await conn.fetchrow(
            "SELECT COUNT(DISTINCT agent_id)::int as cnt FROM agent_activities"
        )
        active_agents = active_row["cnt"] if active_row else 0

        # ── SPEC-43: Avg loop rounds ───────────────────────────────────
        loop_row = await conn.fetchrow(
            "SELECT COALESCE(AVG(round), 0) as avg_rounds FROM loop_events"
        )
        avg_loop_rounds = round(float(loop_row["avg_rounds"]), 2) if loop_row else 0

        # ── SPEC-43: AI vs Human comparison ────────────────────────────
        ai_count = await conn.fetchrow(
            "SELECT COUNT(*)::int as cnt FROM requirements WHERE ai_completion > 50"
        )
        human_count = await conn.fetchrow(
            "SELECT COUNT(*)::int as cnt FROM requirements WHERE ai_completion <= 50"
        )
        ai_vs_human = {
            "ai_driven": ai_count["cnt"] if ai_count else 0,
            "human_driven": human_count["cnt"] if human_count else 0,
        }

        # ── SPEC-43: 12-week cycle_time trends ─────────────────────────
        trend_rows = await conn.fetch(
            """
            SELECT
                DATE_TRUNC('week', created_at) AS week_start,
                AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 86400) AS avg_cycle_days,
                COUNT(*)::int AS req_count
            FROM requirements
            WHERE status IN ('releasing', 'done', 'testing')
              AND created_at >= NOW() - INTERVAL '84 days'
            GROUP BY week_start
            ORDER BY week_start
            """
        )
        trends = []
        for tr in trend_rows:
            trends.append({
                "week": tr["week_start"].isoformat() if tr["week_start"] else None,
                "cycle_time_days": round(float(tr["avg_cycle_days"]), 2) if tr["avg_cycle_days"] is not None else 0,
                "count": tr["req_count"],
            })

        return {
            "cycle_time_days": cycle_time,
            "throughput": throughput,
            "ai_contribution_pct": ai_contribution,
            "code_quality_score": quality,
            "bug_escape_rate_pct": bug_rate,
            "bottleneck_distribution": bottleneck,
            # ── SPEC-43 new fields ─────────────────────────────────────
            "total_requirements": total_req,
            "active_agents": active_agents,
            "avg_loop_rounds": avg_loop_rounds,
            "ai_vs_human": ai_vs_human,
            "trends": trends,
            # ── End new fields ─────────────────────────────────────────
            "source": "live",
        }
    finally:
        await conn.close()
