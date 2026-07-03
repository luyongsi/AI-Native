"""build_context Activity — build agent context from DB (spec, artifacts, rules).

Reads requirements.spec JSONB and related data to build a context package
tailored for the target agent at the current state.
"""

import json
import logging
import os
from datetime import datetime, timezone

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


@activity.defn(name="build_context")
async def build_context(req_id: str, state: str) -> dict:
    """Build context for *req_id* at the given *state*."""
    activity.logger.info("build_context req=%s state=%s", req_id, state)

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, spec, status FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not row:
            return {
                "req_id": req_id,
                "state": state,
                "error": "Requirement not found",
            }

        title = row["title"] or "未命名需求"
        spec_raw = row["spec"]
        if isinstance(spec_raw, str):
            try:
                spec_raw = json.loads(spec_raw)
            except (json.JSONDecodeError, TypeError):
                spec_raw = {}
        if not isinstance(spec_raw, dict):
            spec_raw = {}

        sections = spec_raw.get("sections", spec_raw.get("spec_sections", []))
        openapi = spec_raw.get("openapi", {})
        erd = spec_raw.get("erd", {})

        # Build context tailored to state
        context = {
            "req_id": req_id,
            "state": state,
            "title": title,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "spec_sections": [],
            "openapi_hint": {},
            "erd_hint": {},
            "dag_hint": {},
            "constraints": [],
            "note": "",
        }

        # Always include spec section summaries
        for s in sections[:8]:
            context["spec_sections"].append({
                "id": s.get("id", ""),
                "title": s.get("title", ""),
                "summary": s.get("content", "")[:300],
            })

        # State-specific context
        if state in ("designing", "reviewing"):
            context["openapi_hint"] = {
                "endpoints": openapi.get("endpoints", [])[:5],
                "info": openapi.get("info", {}),
            }
            context["erd_hint"] = {
                "tables": erd.get("tables", [])[:5],
            }

        if state in ("decomposing", "developing"):
            dag = spec_raw.get("dag", {})
            context["dag_hint"] = {
                "nodes": dag.get("nodes", [])[:10],
                "edges": dag.get("edges", [])[:10],
            }

        if state == "developing":
            context["constraints"] = [
                "遵循现有代码规范和项目 CLAUDE.md",
                "不要修改数据库迁移文件",
                "修改前先运行现有测试确保不引入回归",
            ]
            context["note"] = "开发 Agent 需要基于 DAG 任务节点逐个实现"

        if state in ("testing",):
            context["note"] = "测试 Agent 需要读取 Staging URL 和测试资产包"

        if state == "releasing":
            context["note"] = "发布 Agent 需要金丝雀策略和监控指标阈值"

        activity.logger.info(
            "build_context completed req=%s sections=%d endpoints=%d tables=%d",
            req_id, len(context["spec_sections"]),
            len(context["openapi_hint"].get("endpoints", [])),
            len(context["erd_hint"].get("tables", [])),
        )

    return context
