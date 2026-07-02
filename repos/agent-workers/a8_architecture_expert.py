"""A8: Architecture Expert Agent (架构评审)

触发: dag.created (与 A7 并行)
真实 LLM: 调用 DeepSeek API 进行架构评审、红线检查、循环依赖检测
评分 >= 70 通过，<70 → Gate 2 人工裁决
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A8"
AGENT_TYPE = "architecture_expert"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")


class ArchitectureExpertAgent(BaseAgentWorker):
    """A8: 架构评审 + 红线检查 + LLM 分析"""

    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)

    async def _call_llm(self, messages: list, temperature: float = 0.2) -> str | None:
        if not DEEPSEEK_API_KEY:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                    json={"model": DEEPSEEK_MODEL, "messages": messages, "temperature": temperature, "max_tokens": 3000},
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"[A8] LLM call failed: {e}")
            return None

    async def execute(self, req_id: str, context_package: dict) -> dict:
        dag = context_package.get("dag", context_package.get("payload", {}))
        nodes = dag.get("nodes", context_package.get("nodes", []))
        edges = dag.get("edges", context_package.get("edges", []))

        logger.info(f"[A8] Architecture review req={req_id}, nodes={len(nodes)}, edges={len(edges)}")

        await self.report_status(req_id, "running", "Phase 1: 静态分析 (循环/跨层/DB)")

        # Static checks
        cycle_detected, cycle_path = self._check_cycles(nodes, edges)
        layer_violations = self._check_layer_violations(nodes, edges)
        db_issues = self._check_db_rollback(nodes)

        await self.report_status(req_id, "running", "Phase 2: LLM 架构评审")

        # LLM review
        dag_summary = {
            "nodes": nodes,
            "edges": edges,
            "cycle_detected": cycle_detected,
            "cycle_path": cycle_path if cycle_detected else None,
            "layer_violations": len(layer_violations),
            "db_issues": len(db_issues),
        }
        review = await self._llm_review(req_id, json.dumps(dag_summary, ensure_ascii=False))

        if review is None:
            review = self._fallback_review(nodes, edges, cycle_detected, cycle_path, layer_violations, db_issues)

        # Merge static check findings
        violations = review.get("violations", [])
        for lv in layer_violations:
            violations.append(lv)
        for di in db_issues:
            violations.append(di)
        if cycle_detected:
            violations.append({
                "rule": "DAG-CYCLE-001", "severity": "critical",
                "title": "检测到循环依赖",
                "detail": f"DAG 中存在依赖环: {' -> '.join(cycle_path)}" if cycle_path else "DAG 中存在循环依赖",
                "suggestion": "重新审视依赖关系, 移除循环引用或合并为单个节点",
            })

        review_id = f"rev-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        score = review.get("score", 80)
        if cycle_detected:
            score = max(score - 30, 0)

        verdict = "pass" if score >= 70 else "fail"
        if cycle_detected:
            verdict = "fail"

        summary = {
            "review_id": review_id,
            "verdict": verdict,
            "score": score,
            "gate2_required": verdict != "pass",
            "checks": {
                "cycle_dependency": {"passed": not cycle_detected},
                "layer_violation": {"passed": len(layer_violations) == 0, "count": len(layer_violations)},
                "db_rollback": {"passed": len(db_issues) == 0, "count": len(db_issues)},
            },
            "violations": violations,
            "suggestions": review.get("suggestions", []),
            "summary": review.get("summary", ""),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.report_artifact(req_id, "architecture_review", summary)

        envelope = {
            "event_id": f"review-arch-{req_id}",
            "event_type": "review.completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": summary,
            "req_id": req_id,
            "agent_id": AGENT_ID,
        }
        await self.nc.publish("review.completed", json.dumps(envelope, ensure_ascii=False).encode())
        logger.info(f"[A8] Published review.completed verdict={verdict} score={score}")

        await self.report_status(req_id, "completed",
                                 f"架构评审: {verdict} (score={score}, violations={len(violations)})")
        return {"status": "completed", "review": summary}

    async def _llm_review(self, req_id: str, dag_text: str) -> dict | None:
        prompt = f"""你是资深架构师。对以下 DAG 进行架构评审。

## DAG 数据
{dag_text[:3000]}

输出 JSON:
{{
  "score": 0-100,
  "violations": [
    {{"rule": "规则ID", "severity": "critical|warning", "title": "标题", "detail": "详情", "suggestion": "建议", "affected_nodes": ["节点ID"]}}
  ],
  "suggestions": ["建议1", "建议2"],
  "summary": "评审总结（100字以内）"
}}

检查要点: 架构分层合理性、循环依赖、DB变更回滚、安全漏洞、性能风险、模块耦合度
只输出 JSON"""

        content = await self._call_llm([{"role": "user", "content": prompt}], temperature=0.1)
        if not content:
            return None
        try:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()
            if content.startswith("json"):
                content = content[4:].strip()
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _fallback_review(self, nodes, edges, cycle, cpath, lv, db) -> dict:
        violations = []
        score = 85
        if cycle:
            violations.append({"rule": "DAG-CYCLE-001", "severity": "critical", "title": "循环依赖", "detail": str(cpath)})
            score -= 40
        if lv:
            violations.extend(lv)
            score -= len(lv) * 10
        if db:
            violations.extend(db)
            score -= len(db) * 5
        return {
            "score": max(score, 0),
            "violations": violations,
            "suggestions": ["建议前后端通过 API 契约解耦", "DB 变更建议采用 Expand-Contract 模式"],
            "summary": "[Fallback] 基于规则的架构评审",
        }

    def _check_cycles(self, nodes: list, edges: list) -> tuple:
        for e in edges:
            if e.get("from") == e.get("to"):
                return True, [e["from"], e["to"]]
        edge_set = set((e.get("from"), e.get("to")) for e in edges)
        for a, b in edge_set:
            if (b, a) in edge_set:
                return True, [a, b, a]
        return False, []

    def _check_layer_violations(self, nodes: list, edges: list) -> list:
        violations = []
        node_map = {n["id"]: n for n in nodes}
        for e in edges:
            f = node_map.get(e.get("from"))
            t = node_map.get(e.get("to"))
            if f and t and f.get("type") == "frontend" and t.get("type") == "db":
                violations.append({
                    "rule": "LAYER-VIO-001", "severity": "critical",
                    "title": f"跨层调用: {f['id']} -> {t['id']}",
                    "detail": "前端直接依赖 DB, 应通过 API 层",
                })
        return violations

    def _check_db_rollback(self, nodes: list) -> list:
        issues = []
        for n in nodes:
            if n.get("type") == "db":
                tasks = n.get("tasks", [])
                has_rollback = any("rollback" in str(t).lower() or "回滚" in str(t) for t in tasks)
                if not has_rollback:
                    issues.append({
                        "rule": "DB-ROLLBACK-001", "severity": "warning",
                        "title": f"DB 节点 {n['id']} 缺少回滚方案",
                        "detail": f"{n.get('title','')} 未包含回滚方案",
                        "suggestion": "为每个 migration 补充 down 方向",
                    })
        return issues
