"""build_context Activity — build 5-layer agent context package.

Reads requirements + artifacts from DB, environment config from YAML,
and knowledge from context-builder service (or direct DB fallback).

Five-layer context model:
  1. requirement_context  — title, description, acceptance_criteria, A1 analysis
  2. artifact_context     — upstream agent outputs from spec.artifacts JSONB
  3. knowledge_context    — similar requirements, relevant code, best practices, known issues
  4. environment_context  — project config, deployment URLs, tech stack, conventions
  5. rework_context       — round number, previous feedback/issues (supplied by Workflow)
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from temporalio import activity

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"
)
CONTEXT_BUILDER_URL = os.environ.get("CONTEXT_BUILDER_URL", "http://localhost:8300")

_pool: asyncpg.Pool | None = None
_config_dir = Path(os.environ.get("AI_NATIVE_CONFIG_DIR", ".ai-native"))


# ── Connection ──────────────────────────────────────────────────────────

async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


# ── Config loading ──────────────────────────────────────────────────────

def _load_yaml(filename: str) -> dict:
    path = _config_dir / filename
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("Failed to load %s: %s", path, e)
        return {}


def _load_project_config() -> dict:
    return _load_yaml("project-config.yaml")


def _load_budget_config() -> dict:
    return _load_yaml("context-budget.yaml")


# ── Budget helper ───────────────────────────────────────────────────────

def _token_budget_for_state(state: str) -> int:
    config = _load_budget_config()
    model_window = config.get("model_window", 200000)
    budgets = config.get("budgets", {})
    state_config = budgets.get(state, {"pct": 2.0, "max": 4000})
    pct_budget = int(model_window * state_config["pct"] / 100)
    return min(pct_budget, state_config["max"])


# ── Knowledge queries per agent ─────────────────────────────────────────

def _build_search_queries(agent_id: str, title: str, description: str) -> dict[str, str]:
    base = f"{title} {description}"[:500]
    return {
        "A1": {
            "similar_requirements": f"需求分析 历史需求 {base}",
            "known_issues": f"问题 风险 {base}",
        },
        "A2": {
            "similar_requirements": f"需求 设计 {base}",
            "relevant_code": f"代码 {base}",
            "dependency_graph": f"依赖 模块 {base}",
            "best_practices": f"最佳实践 {base}",
        },
        "A3": {
            "similar_requirements": f"UI原型 界面设计 {base}",
        },
        "A4": {
            "similar_requirements": f"API设计 数据库 ERD OpenAPI {base}",
            "relevant_code": f"API Schema SQL {base}",
        },
        "A5": {
            "best_practices": "设计评审 架构评审 安全检查清单 反模式",
        },
        "A6": {
            "relevant_code": f"模块结构 项目架构 {base}",
            "dependency_graph": f"依赖关系 模块 {base}",
        },
        "A9": {
            "relevant_code": f"代码实现 {base}",
            "best_practices": "编码规范 错误处理 日志 安全 最佳实践",
            "known_issues": f"Bug 问题 历史缺陷 {base}",
        },
        "A11": {
            "relevant_code": f"测试 测试用例 {base}",
            "known_issues": "测试失败 常见测试问题",
        },
        "A12": {
            "relevant_code": f"代码 {base}",
            "best_practices": "代码审查 代码质量 安全",
        },
        "A13": {
            "dependency_graph": f"依赖 影响范围 {base}",
        },
    }.get(agent_id, {"similar_requirements": base})


# ── Knowledge retrieval ─────────────────────────────────────────────────

async def _query_knowledge_base(
    target_agent: str, req_id: str, query_text: str, max_tokens: int,
) -> list[dict]:
    """Query knowledge base — context-builder service first, direct DB fallback."""
    # Try HTTP context-builder service
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{CONTEXT_BUILDER_URL}/context/build",
                json={
                    "target_agent": target_agent, "req_id": req_id,
                    "query_text": query_text, "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("success"):
                return result.get("context_package", {}).get("head", [])
    except Exception:
        logger.warning("context-builder unavailable for agent=%s, falling back to DB", target_agent)

    # Direct DB fallback
    return await _query_knowledge_chunks_direct(query_text)


async def _query_knowledge_chunks_direct(query_text: str) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """SELECT title, content, doc_type, file_path,
                         ts_rank(search_vector, plainto_tsquery('english', $1)) AS rank
                  FROM knowledge_chunks
                  WHERE search_vector @@ plainto_tsquery('english', $1)
                  ORDER BY rank DESC LIMIT 20""",
                query_text,
            )
        except Exception:
            return []

        items = []
        for row in rows:
            items.append({
                "type": row["doc_type"] or "unknown",
                "content": row["content"] or "",
                "relevance": float(row["rank"]) if row["rank"] else 0.0,
                "file": row["file_path"] or "",
            })
        return items


async def _build_knowledge_section(
    target_agent: str, req_id: str, title: str, description: str, token_budget: int,
) -> dict:
    """Query knowledge base for the given agent and return categorized items."""
    queries = _build_search_queries(target_agent, title, description)
    all_items = []
    for category_name, query in queries.items():
        items = await _query_knowledge_base(target_agent, req_id, query, token_budget)
        for item in items:
            item["category"] = category_name
        all_items.extend(items)

    # Sort by relevance, deduplicate by content prefix
    all_items.sort(key=lambda x: x.get("relevance", 0), reverse=True)
    seen = set()
    unique = []
    for item in all_items:
        prefix = item.get("content", "")[:80]
        if prefix not in seen:
            seen.add(prefix)
            unique.append(item)

    # Split into head/mid/tail by relevance
    head = [i for i in unique if i.get("relevance", 0) >= 0.8]
    mid = [i for i in unique if 0.5 <= i.get("relevance", 0) < 0.8]
    tail = [i for i in unique if i.get("relevance", 0) < 0.5]

    return {"head": head, "mid": mid, "tail": tail}


# ── Context extraction helpers ──────────────────────────────────────────

def _parse_json(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _extract_requirement_context(row, spec: dict) -> dict:
    source_payload = _parse_json(row.get("source_payload"))
    return {
        "title": row.get("title", ""),
        "description": row.get("description", "") or source_payload.get("description", ""),
        "acceptance_criteria": spec.get("acceptance_criteria", []),
        "analysis": (spec.get("artifacts", {}).get("A1", {}) or {}).get("analysis", {}),
        "source_type": row.get("source_type", ""),
    }


def _extract_artifact_context(spec: dict, state: str) -> dict:
    """Extract upstream artifacts relevant to the current state."""
    artifacts = spec.get("artifacts", {}) or {}

    # Per-state: which upstream agents' artifacts are relevant
    _STATE_UPSTREAM = {
        "analyzing": [],
        "designing": ["A1", "A2"],
        "reviewing": ["A1", "A2", "A3", "A4"],
        "decomposing": ["A1", "A4", "A5"],
        "developing": ["A1", "A4", "A5", "A6", "A7"],
        "testing": ["A4", "A7", "A9"],
        "reviewing_code": ["A4", "A9", "A11"],
        "releasing": ["A4", "A9", "A11", "A12"],
    }

    relevant = _STATE_UPSTREAM.get(state, [])
    result = {}
    for agent_id in relevant:
        if agent_id == "A4":
            # A4 writes to spec.openapi / spec.erd (root keys) instead of
            # spec.artifacts.A4 because it's in _AGENTS_THAT_PERSIST.
            # Read from root keys and normalize into artifact_context.
            a4_data = {}
            openapi = spec.get("openapi", {})
            erd = spec.get("erd", {})

            if openapi:
                api_schema = openapi.get("schema", openapi)
                if isinstance(api_schema, dict):
                    # Produce list of dicts (not strings) so _structured_extract
                    # can safely call .get() on each item.
                    paths = {}
                    raw_paths = api_schema.get("paths", {})
                    for path, methods in (raw_paths.items() if isinstance(raw_paths, dict) else []):
                        paths[path] = list(methods.keys()) if isinstance(methods, dict) else []
                    a4_data["openapi"] = {
                        "paths": paths,
                        "info": api_schema.get("info", {}),
                        "has_schema": bool(raw_paths),
                    }
            if erd:
                a4_data["erd"] = {
                    "tables": [e.get("name", "") for e in erd.get("entities", [])],
                    "relationships": erd.get("relationships", []),
                    "has_entities": bool(erd.get("entities", [])),
                }

            result[agent_id] = a4_data if a4_data else artifacts.get(agent_id, {})
        elif agent_id in artifacts:
            result[agent_id] = artifacts[agent_id]
        else:
            result[agent_id] = {}

    return result


def _extract_environment_context() -> dict:
    config = _load_project_config()
    project = config.get("project", {})
    deployment = config.get("deployment", {})

    # Read CLAUDE.md content if available
    claude_md_content = ""
    claude_path = project.get("claude_md_path", "CLAUDE.md")
    try:
        md_path = Path(claude_path)
        if md_path.exists():
            claude_md_content = md_path.read_text(encoding="utf-8")[:2000]
    except Exception:
        pass

    return {
        "project": {
            "name": project.get("name", ""),
            "tech_stack": project.get("tech_stack", []),
            "coding_conventions": project.get("coding_conventions", ""),
            "claude_md_content": claude_md_content,
        },
        "deployment": {
            "dev_url": deployment.get("dev_url", ""),
            "staging_url": deployment.get("staging_url", ""),
            "production_url": deployment.get("production_url", ""),
            "test_db": deployment.get("db_connections", {}).get("dev", ""),
        },
        "integration": {
            "issue_tracker": config.get("integration", {}).get("issue_tracker", ""),
            "ci_cd": config.get("integration", {}).get("ci_cd", ""),
            "monitoring": config.get("integration", {}).get("monitoring", ""),
        },
    }


# ── Decisions context ────────────────────────────────────────────────────

async def _extract_decisions_context(req_id: str, state: str, conn) -> dict:
    """Read Gate decisions from spec.decisions JSONB root key.

    For DEVELOPING state: includes Gate 1 architecture decisions.
    For TESTING/REVIEWING_CODE/RELEASING: includes all Gate decisions.
    """
    if state not in ("developing", "testing", "reviewing_code", "releasing"):
        return {}

    row = await conn.fetchrow(
        "SELECT COALESCE(spec->'decisions', '{}'::jsonb) AS decisions "
        "FROM requirements WHERE id = $1::uuid",
        req_id,
    )
    if not row:
        return {"resolved": {}, "source_gates": []}

    decisions_raw = row["decisions"]
    if isinstance(decisions_raw, str):
        try:
            decisions_raw = json.loads(decisions_raw)
        except (json.JSONDecodeError, TypeError):
            decisions_raw = {}
    if not isinstance(decisions_raw, dict):
        decisions_raw = {}
    return {
        "resolved": decisions_raw.get("resolved", {}),
        "source_gates": decisions_raw.get("source_gates", []),
        "approved_at": decisions_raw.get("approved_at", ""),
    }


# ── Agent ID mapping ────────────────────────────────────────────────────

def _agent_for_state(state: str) -> str:
    return {
        "analyzing": "A1",
        "designing": "A4",
        "reviewing": "A5",
        "decomposing": "A6",
        "developing": "A9",
        "testing": "A11",
        "reviewing_code": "A12",
        "releasing": "A13",
    }.get(state, "A1")


# ── Main Activity ───────────────────────────────────────────────────────

@activity.defn(name="build_context")
async def build_context(
    req_id: str,
    state: str,
    target_agent: str = "",
    rework_context: dict | None = None,
) -> dict:
    """Build a 5-layer context package for the target agent at the given state.

    Args:
        req_id: Requirement UUID.
        state: Current pipeline state (e.g. "analyzing", "designing").
        target_agent: Target agent ID. If empty, inferred from state.
        rework_context: Optional rework info {round, issues, suggestion, previous_result}.

    Returns:
        ContextPackage dict with five layers + metadata.
    """
    agent_id = target_agent or _agent_for_state(state)
    activity.logger.info(
        "build_context req=%s state=%s agent=%s", req_id, state, agent_id,
    )

    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, description, spec, source_payload, source_type "
            "FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not row:
            return {"req_id": req_id, "state": state, "error": "Requirement not found"}

        spec = _parse_json(row["spec"])

        # 1. Requirement context
        requirement_context = _extract_requirement_context(row, spec)

        # 2. Artifact context (from spec.artifacts JSONB)
        artifact_context = _extract_artifact_context(spec, state)

        # 3. Knowledge context
        budget = _token_budget_for_state(state)
        knowledge_context = await _build_knowledge_section(
            target_agent=agent_id,
            req_id=req_id,
            title=requirement_context["title"] or "",
            description=requirement_context["description"] or "",
            token_budget=budget,
        )

        # 4. Environment context
        environment_context = _extract_environment_context()

        # 5. Decisions context (Gate approval decisions)
        decisions_context = await _extract_decisions_context(req_id, state, conn)

    # 6. Rework context (supplied by Workflow)
    rework = rework_context or {}

    # ── Assemble full package (backward-compatible aliases) ──────────────
    context = {
        "req_id": req_id,
        "state": state,
        "agent_id": agent_id,
        "built_at": datetime.now(timezone.utc).isoformat(),

        # Six layers
        "requirement_context": requirement_context,
        "artifact_context": artifact_context,
        "knowledge_context": knowledge_context,
        "environment_context": environment_context,
        "decisions_context": decisions_context,
        "rework_context": rework if rework else None,

        # Backward-compatible keys (existing agent code reads these)
        "title": requirement_context["title"],
        "spec_sections": spec.get("spec_sections", spec.get("sections", [])),
        "openapi_hint": {
            "paths": (artifact_context.get("A4", {}).get("openapi", {}) or {}).get("paths", {}),
            "info": (artifact_context.get("A4", {}).get("openapi", {}) or {}).get("info", {}),
        },
        "erd_hint": {
            "tables": (artifact_context.get("A4", {}).get("erd", {}) or {}).get("tables", [])[:10],
        },
        "dag_hint": {
            "nodes": (artifact_context.get("A6", {}) or {}).get("nodes", [])[:10],
            "edges": (artifact_context.get("A6", {}) or {}).get("edges", [])[:10],
        },
        "constraints": _constraints_for_state(state),
        "note": _note_for_state(state),
    }
    return context


# ── Per-state hints ─────────────────────────────────────────────────────

def _constraints_for_state(state: str) -> list[str]:
    if state == "developing":
        return [
            "遵循现有代码规范和项目 CLAUDE.md",
            "不要修改数据库迁移文件",
            "修改前先运行现有测试确保不引入回归",
        ]
    return []


def _note_for_state(state: str) -> str:
    return {
        "developing": "开发 Agent 需要基于 DAG 任务节点逐个实现",
        "testing": "测试 Agent 需要读取 Staging URL 和测试资产包",
        "releasing": "发布 Agent 需要金丝雀策略和监控指标阈值",
    }.get(state, "")
