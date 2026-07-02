"""
Mission Control Backend - Topology + Agent Graph API (SPEC-41b)
GET /api/topology - Returns the agent topology graph (nodes + edges).

Nodes are derived from agent_activities (distinct agent_id) plus a hardcoded
orchestrator. Edges are a static map of 13 inter-agent relationships.
When the database is empty all agents are shown as "idle".
"""
from fastapi import APIRouter
from typing import Optional, List

router = APIRouter(prefix="/api/topology", tags=["topology"])

# ── All known agent identities and their human-readable labels ────────────
_AGENT_LABELS: dict = {
    "A1": "需求标准化 Agent",
    "A2": "UI/UX 原型 Agent",
    "A3": "技术方案 Agent",
    "A4": "技术方案评审 Agent",
    "A5": "视觉还原 Agent",
    "A6": "前后端代码生成 Agent",
    "A7": "后端开发 Agent",
    "A8": "前端开发 Agent",
    "A9": "测试 Agent",
    "A10": "Review Agent",
    "A11": "E2E 测试 Agent",
    "A12": "联调优化 Agent",
    "A13": "代码变更影响 Agent",
}

# ── Hardcoded edges from the spec ─────────────────────────────────────────
_EDGES: list = [
    {"from": "orchestrator", "to": "A1"},
    {"from": "A1", "to": "A2"},
    {"from": "A1", "to": "A3"},
    {"from": "A1", "to": "A4"},
    {"from": "A2", "to": "A4"},
    {"from": "A4", "to": "A5"},
    {"from": "A4", "to": "A6"},
    {"from": "A4", "to": "A8"},
    {"from": "A6", "to": "A7"},
    {"from": "A6", "to": "A9"},
    {"from": "A9", "to": "A10"},
    {"from": "A9", "to": "A12"},
    {"from": "A10", "to": "A13"},
    {"from": "A10", "to": "A11"},
]


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


@router.get("")
async def get_topology():
    """Return the agent topology graph."""
    conn = await get_db()
    try:
        # Fetch latest status per agent from agent_activities
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (agent_id) agent_id, status
            FROM agent_activities
            ORDER BY agent_id, created_at DESC
            """
        )
        db_status: dict = {}
        for row in rows:
            db_status[row["agent_id"]] = row["status"]

        # Build node list
        nodes: list = [
            {
                "id": "orchestrator",
                "label": "Orchestrator",
                "type": "orchestrator",
                "status": "running",
            }
        ]
        for agent_id, label in sorted(_AGENT_LABELS.items()):
            status = db_status.get(agent_id, "idle")
            nodes.append({
                "id": agent_id,
                "label": label,
                "type": "agent",
                "status": status,
            })

        return {"nodes": nodes, "edges": _EDGES}
    finally:
        await conn.close()
