"""
A8: Architecture Expert Agent (架构评审)

触发: context.ready.A8 (Orchestrator 发布，A6+A7 都完成后)
产出: agent_results UPSERT (agent_key='A8') + agent.result.A8
静态检查: DFS 颜色标记法多跳环检测 + 分层违规 + DB 回滚 (steps 字段)
LLM 评审: 安全/性能/耦合度
评分 >= 70 通过, < 70 → Gate2 人工裁决
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg

from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A8"
AGENT_TYPE = "architecture_expert"

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "ai_native"
DB_USER = "ai_native"
DB_PASSWORD = "ai_native_dev"

# 合法分层: frontend → backend → db（单向依赖，不可反向/跨层）
_LAYER_ORDER = {"frontend": 0, "backend": 1, "db": 2}


class ArchitectureExpertAgent(BaseAgentWorker):
    """A8: 架构评审 + 静态分析 + LLM 分析"""

    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)
        self._db_pool: asyncpg.Pool | None = None

    async def init(self):
        """Initialize and subscribe to context.ready.A8."""
        await super().init()
        # 订阅 context.ready.A8 (主入口)
        await self.js.subscribe(
            "context.ready.A8",
            cb=self._handle_context_ready,
            stream="AI_NATIVE_EVENTS",
            durable="A8_consumer",
        )
        logger.info("[A8] Subscribed to context.ready.A8 (durable=A8_consumer)")

    async def _handle_context_ready(self, msg):
        """解析 context.ready.A8 消息，调用 execute()，ack/nak 处理"""
        try:
            data = json.loads(msg.data.decode())
            payload = data.get("payload", {})
            req_id = data.get("req_id", "") or payload.get("req_id", "")
            if not req_id:
                logger.warning("[A8] context.ready.A8 missing req_id, skipping")
                await msg.ack()
                return
            logger.info(f"[A8] Received context.ready.A8 for req={req_id}")
            await self.execute(req_id, payload)
            await msg.ack()
        except Exception as e:
            logger.error(f"[A8] Error handling context.ready.A8: {e}", exc_info=True)
            try:
                await msg.nak()
            except Exception:
                pass

    async def _get_db_pool(self) -> asyncpg.Pool:
        if self._db_pool is None:
            self._db_pool = await asyncpg.create_pool(
                host=DB_HOST, port=DB_PORT, database=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
                min_size=1, max_size=5,
            )
        return self._db_pool

    async def close(self):
        if self._db_pool:
            await self._db_pool.close()
        await super().close()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        session_id = context_package.get("session_id", "")
        cycle = context_package.get("cycle", 0)

        dag = context_package.get("dag", {})
        nodes = dag.get("nodes", [])
        edges = dag.get("edges", [])

        logger.info(f"[A8] Architecture review req={req_id}, nodes={len(nodes)}, edges={len(edges)}")

        # 空 DAG 处理（A6 超时降级）
        if not nodes:
            logger.warning(f"[A8] Empty DAG for req={req_id}, skipping review")
            await self._upsert_agent_results(req_id, "A8", cycle, "skipped",
                                             {"reason": "empty_dag"})
            # 发布 skipped 的 agent.result.A8
            await self._publish_agent_result_a8(req_id, session_id, cycle,
                {"review_id": "", "verdict": "skipped", "score": 0,
                 "gate2_required": True, "checks": {},
                 "violations": [], "suggestions": [],
                 "summary": "DAG 为空，跳过评审"})
            return {"status": "skipped", "reason": "empty_dag"}

        await self.report_status(req_id, "running", "Phase 1: 静态分析 (循环/分层/DB)")

        # 阶段一：静态分析
        cycle_detected, cycle_path = self._check_cycles(nodes, edges)
        layer_violations = self._check_layer_violations(nodes, edges)
        db_issues = self._check_db_rollback(nodes)

        await self.report_status(req_id, "running", "Phase 2: LLM 架构评审 (安全/性能/耦合)")

        # 阶段二：LLM 评审
        review = await self._llm_review(req_id, dag, nodes, edges,
            cycle_detected, cycle_path, layer_violations, db_issues,
            context_package)

        # LLM 失败 → 仅静态分析
        if review is None:
            review = self._fallback_review(nodes, edges, cycle_detected, cycle_path,
                                           layer_violations, db_issues)

        # 阶段三：合并报告
        violations = review.get("violations", [])
        for lv in layer_violations:
            violations.append(lv)
        for di in db_issues:
            violations.append(di)
        if cycle_detected:
            violations.append({
                "rule": "DAG-CYCLE-001",
                "severity": "critical",
                "title": "检测到循环依赖",
                "detail": f"DAG 中存在依赖环: {' → '.join(cycle_path)}" if cycle_path else "DAG 中存在循环依赖",
                "suggestion": "重新审视依赖关系，移除循环引用或合并为单个节点",
                "affected_nodes": cycle_path if cycle_path else [],
            })

        # 评分与判定
        review_id = f"rev-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        score = review.get("score", 85)
        score = max(score - 30 if cycle_detected else score, 0)

        verdict = "pass" if (score >= 70 and not cycle_detected) else "fail"

        checks = {
            "cycle_dependency": {"passed": not cycle_detected, "count": 1 if cycle_detected else 0},
            "layer_violation": {"passed": len(layer_violations) == 0, "count": len(layer_violations)},
            "db_rollback": {"passed": len(db_issues) == 0, "count": len(db_issues)},
            "security_risk": {"passed": len([v for v in violations if v.get("rule", "").startswith("SEC-")]) == 0,
                              "count": len([v for v in violations if v.get("rule", "").startswith("SEC-")])},
            "performance_risk": {"passed": len([v for v in violations if v.get("rule", "").startswith("PERF-")]) == 0,
                                 "count": len([v for v in violations if v.get("rule", "").startswith("PERF-")])},
        }

        summary = {
            "review_id": review_id,
            "verdict": verdict,
            "score": score,
            "gate2_required": verdict != "pass",
            "checks": checks,
            "violations": violations,
            "suggestions": review.get("suggestions", []),
            "summary": review.get("summary", ""),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }

        # 持久化
        await self._upsert_agent_results(req_id, "A8", cycle, "completed",
                                         {"review": summary})

        # 发布 agent.result.A8
        await self._publish_agent_result_a8(req_id, session_id, cycle, summary)

        await self.report_status(req_id, "completed",
            f"架构评审: {verdict} (score={score}, violations={len(violations)})")

        return {"status": "completed", "review": summary}

    # ── 静态检查: DFS 颜色标记法 ──────────────────────────────────────────────

    def _check_cycles(self, nodes: list, edges: list) -> tuple[bool, list]:
        """使用 DFS 颜色标记法检测有向图中的环（支持多跳环）"""
        WHITE, GRAY, BLACK = 0, 1, 2

        graph = defaultdict(list)
        node_ids = {n.get("id") for n in nodes if n.get("id")}
        for e in edges:
            f, t = e.get("from", ""), e.get("to", "")
            if f in node_ids and t in node_ids:
                graph[f].append(t)

        color = defaultdict(lambda: WHITE)
        parent = {}

        def dfs(u):
            color[u] = GRAY
            for v in graph.get(u, []):
                if color[v] == GRAY:
                    # 找到环: 从 v 到 u 沿 parent 回溯
                    cycle = [v]
                    cur = u
                    while cur != v:
                        cycle.append(cur)
                        cur = parent.get(cur, v)
                    cycle.append(v)
                    return cycle[::-1]
                elif color[v] == WHITE:
                    parent[v] = u
                    result = dfs(v)
                    if result:
                        return result
            color[u] = BLACK
            return None

        for nid in node_ids:
            if color[nid] == WHITE:
                cycle = dfs(nid)
                if cycle:
                    return True, cycle

        return False, []

    # ── 静态检查: 分层违规 ──────────────────────────────────────────────

    def _check_layer_violations(self, nodes: list, edges: list) -> list:
        """检查分层违规（前端→DB 直接依赖 / DB→前端反向依赖）"""
        violations = []
        node_map = {n.get("id"): n for n in nodes if n.get("id")}

        for e in edges:
            f = node_map.get(e.get("from"))
            t = node_map.get(e.get("to"))
            if not f or not t:
                continue

            # 前端直接依赖 DB → critical
            if f.get("type") == "frontend" and t.get("type") == "db":
                violations.append({
                    "rule": "LAYER-VIO-001",
                    "severity": "critical",
                    "title": f"跨层调用: {f['id']}(frontend) → {t['id']}(db)",
                    "detail": "前端节点直接依赖数据库层，应通过 API 接口（backend）间接访问",
                    "suggestion": "在前端和 DB 之间插入 backend 节点，通过 REST API 或 RPC 调用",
                    "affected_nodes": [f.get("id"), t.get("id")],
                })

            # DB 依赖前端 → warning（反向依赖）
            if f.get("type") == "db" and t.get("type") == "frontend":
                violations.append({
                    "rule": "LAYER-VIO-002",
                    "severity": "warning",
                    "title": f"反向依赖: {f['id']}(db) → {t['id']}(frontend)",
                    "detail": "数据库节点不应依赖前端展示层",
                    "suggestion": "解除反向依赖，数据流向应为 frontend → backend → db",
                    "affected_nodes": [f.get("id"), t.get("id")],
                })

        return violations

    # ── 静态检查: DB 回滚（检查 steps 字段而非 tasks） ──────────────────────

    def _check_db_rollback(self, nodes: list) -> list:
        """检查 db 类型节点的 steps 中是否包含回滚/rollback 方案"""
        issues = []

        for n in nodes:
            if n.get("type") != "db":
                continue

            steps = n.get("steps", [])
            has_rollback = any(
                "rollback" in str(s).lower() or "回滚" in str(s)
                for s in steps
            )

            if not has_rollback:
                issues.append({
                    "rule": "DB-ROLLBACK-001",
                    "severity": "warning",
                    "title": f"DB 节点 {n.get('id')} 缺少回滚方案",
                    "detail": f"节点 '{n.get('title', '')}' 的 steps 中未包含数据库迁移的回滚（down migration）方案",
                    "suggestion": "为每个 DDL 变更补充反向迁移步骤（如 ALTER TABLE DROP COLUMN → 回滚: ALTER TABLE ADD COLUMN）",
                    "affected_nodes": [n.get("id")],
                })

        return issues

    # ── LLM 评审 ──────────────────────────────────────────────

    async def _llm_review(self, req_id: str, dag: dict, nodes: list, edges: list,
                          cycle_detected: bool, cycle_path: list,
                          layer_violations: list, db_issues: list,
                          context_package: dict) -> dict | None:
        """LLM 架构评审（安全/性能/耦合度）"""
        context_text = await self.prepare_llm_context(context_package, state="decomposing")

        # DAG 摘要
        nodes_summary = "\n".join(
            f"  {n.get('id')}: [{n.get('type')}] {n.get('title')} (complexity={n.get('complexity')})"
            for n in nodes[:15]
        )
        edges_summary = "\n".join(
            f"  {e.get('from')} → {e.get('to')} ({e.get('type')})"
            for e in edges[:20]
        )
        critical_path = dag.get("critical_path", [])

        prompt = f"""你是资深架构师。对以下 DAG 进行架构评审。

DAG 摘要:
- 节点 ({len(nodes)}):
{nodes_summary}
- 依赖边 ({len(edges)}):
{edges_summary}
- 关键路径: {json.dumps(critical_path)}

静态分析结果:
- 循环依赖: {"detected, path: " + " → ".join(cycle_path) if cycle_detected else "未检测到"}
- 分层违规: {len(layer_violations)} 项
- DB 回滚缺失: {len(db_issues)} 项

{context_text}

输出严格 JSON（不要 markdown 包裹）:
{{
  "score": 0-100,
  "violations": [
    {{
      "rule": "SEC-AUTH-001|SEC-SQL-001|SEC-DATA-001|SEC-KEY-001|PERF-N1-001|PERF-CACHE-001|PERF-PAGE-001",
      "severity": "critical|warning",
      "title": "标题（10字内）",
      "detail": "详细说明",
      "suggestion": "修复建议（可操作的具体方案）",
      "affected_nodes": ["node-id"]
    }}
  ],
  "suggestions": ["全局建议1", "全局建议2"],
  "summary": "评审总结（50-100字，含最关键的发现和建议）"
}}

检查要点:
1. 安全红线（必查）:
   - 认证/授权是否覆盖所有 API？
   - DAG 中是否有 SQL 拼接/注入风险节点？
   - 是否有敏感数据（密码/Token/PII）明文传输/存储？
   - 是否有硬编码密钥/AK/SK？
2. 性能风险:
   - 是否存在 N+1 查询模式？
   - 热点数据是否缺少缓存策略？
   - 列表接口是否包含分页？
3. 架构分层合理性:
   - 前端/后端/DB 分层是否清晰？
   - 是否有跨服务/跨模块的不合理直接依赖？

只输出 JSON"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="architecture_review",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.1,
            max_tokens=3000,
        )
        if not content:
            return None
        try:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()
            if content.startswith("json"):
                content = content[4:].strip()
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"[A8] LLM JSON parse failed: {e}")
            return None

    # ── Fallback ──────────────────────────────────────────────

    def _fallback_review(self, nodes, edges, cycle, cpath, lv, db) -> dict:
        """Fallback: 仅基于静态分析产出评审结果"""
        violations = []
        score = 85
        if cycle:
            violations.append({"rule": "DAG-CYCLE-001", "severity": "critical",
                               "title": "循环依赖", "detail": str(cpath)})
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
            "suggestions": [
                "建议前后端通过 API 契约解耦",
                "DB 变更建议采用 Expand-Contract 模式",
            ],
            "summary": "[Fallback] 基于静态分析的架构评审",
        }

    # ── 持久化 ──────────────────────────────────────────────

    async def _upsert_agent_results(self, req_id: str, agent_key: str,
                                     cycle: int, status: str, artifact: dict):
        """UPSERT agent_results 表"""
        pool = await self._get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact, created_at)
                VALUES ($1::uuid, $2, $3, $4, $5::jsonb, NOW())
                ON CONFLICT (req_id, agent_key, cycle)
                DO UPDATE SET artifact = EXCLUDED.artifact, status = EXCLUDED.status, created_at = NOW()
            """,
                req_id, agent_key, cycle, status,
                json.dumps(artifact, ensure_ascii=False),
            )
            logger.info(f"[A8] UPSERT agent_results: agent_key={agent_key} status={status}")

    # ── NATS 事件发布 ──────────────────────────────────────────────

    async def _publish_agent_result_a8(self, req_id: str, session_id: str,
                                        cycle: int, review: dict):
        """发布 agent.result.A8 事件（符合数据字典 §6.5 格式）"""
        payload = {
            "req_id": req_id,
            "session_id": session_id,
            "cycle": cycle,
            "review": review,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        msg_id = f"{req_id}-agent.result.A8-{cycle}"

        await self.js.publish(
            "agent.result.A8",
            json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Nats-Msg-Id": msg_id},
        )
        logger.info(f"[A8] Published agent.result.A8 for req={req_id}")
