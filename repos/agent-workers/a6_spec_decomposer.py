"""
A6: Spec Decomposer Agent (Spec 拆解 + DAG 生成)

触发: context.ready.A6 (Orchestrator 发布)
产出: task_dags 表 + agent_results UPSERT + agent.result.A6 + dag.created
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg

from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A6"
AGENT_TYPE = "spec_decomposer"

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "ai_native"
DB_USER = "ai_native"
DB_PASSWORD = "ai_native_dev"


class SpecDecomposerAgent(BaseAgentWorker):
    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)
        self._db_pool: asyncpg.Pool | None = None

    async def init(self):
        await super().init()
        # 订阅 context.ready.A6
        await self.js.subscribe(
            "context.ready.A6",
            cb=self._handle_context_ready,
            stream="AI_NATIVE_EVENTS",
            durable="A6_consumer",
        )
        logger.info("[A6] Subscribed to context.ready.A6 (durable=A6_consumer)")

    async def _handle_context_ready(self, msg):
        """解析 context.ready.A6 消息，调用 execute()，ack/nak 处理"""
        try:
            data = json.loads(msg.data.decode())
            payload = data.get("payload", {})
            req_id = data.get("req_id", "") or payload.get("req_id", "")
            if not req_id:
                logger.warning("[A6] context.ready.A6 missing req_id, skipping")
                await msg.ack()
                return
            logger.info(f"[A6] Received context.ready.A6 for req={req_id}")
            await self.execute(req_id, payload)
            await msg.ack()
        except Exception as e:
            logger.error(f"[A6] Error handling context.ready.A6: {e}", exc_info=True)
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

    async def execute(self, req_id: str, context_package: dict) -> dict:
        # 1. 解析 context.ready.A6 格式
        spec_package = context_package.get("spec_package", {})
        spec_doc = spec_package.get("spec_doc", {})
        openapi = spec_package.get("openapi_schema", {})
        erd = spec_package.get("erd_diagram", {})
        ddl = spec_package.get("ddl_statements", "")

        revision_context = context_package.get("revision_context", {})
        is_revision = revision_context.get("is_revision", False)

        session_id = context_package.get("session_id", "")
        cycle = context_package.get("cycle", 0)

        logger.info(f"[A6] Decomposing spec for req={req_id} (revision={is_revision})")

        await self.report_status(req_id, "running", "Phase 1: LLM 拆解任务")

        # 2. LLM 拆解
        dag = await self._llm_decompose(spec_doc, openapi, erd, ddl,
                                         req_id, revision_context, context_package)

        if dag is None:
            await self.report_status(req_id, "running", "Fallback: 规则拆解")
            dag = self._fallback_decompose(spec_doc, openapi, erd)

        # 3. 验证 DAG
        validation = self._validate_dag(dag)
        if not validation["valid"]:
            logger.warning(f"[A6] DAG validation errors: {validation['errors']}")
            # Fallback 到规则模式
            dag = self._fallback_decompose(spec_doc, openapi, erd)
            dag["source"] = "fallback"
        else:
            dag["source"] = "llm"

        # 4. 补充元数据
        dag["dag_id"] = f"dag-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        dag["created_at"] = datetime.now(timezone.utc).isoformat()

        metadata = {
            "node_count": len(dag.get("nodes", [])),
            "human_review_nodes": sum(1 for n in dag.get("nodes", []) if n.get("needs_human_review")),
            "high_complexity_nodes": sum(1 for n in dag.get("nodes", []) if n.get("complexity") == "high"),
            "source": dag["source"],
        }

        # 5. 持久化到 task_dags
        task_dags_id = await self._save_task_dags(req_id, cycle, dag, metadata)

        # 6. UPSERT agent_results
        artifact = {
            "dag": dag,
            "task_dags_id": task_dags_id,
            "validation": validation,
        }
        await self._upsert_agent_results(req_id, "A6", cycle, "completed", artifact)

        # 7. 发布 NATS 事件
        await self._publish_agent_result_a6(req_id, session_id, cycle, dag, validation)
        await self._publish_dag_created(req_id, cycle, dag, metadata)

        await self.report_status(req_id, "completed",
            f"DAG 生成完成: {metadata['node_count']} 节点, {metadata['human_review_nodes']} 人工审核")

        return {"status": "completed", "dag": dag}

    # ── LLM 拆解 ──────────────────────────────────────────────────────

    async def _llm_decompose(self, spec_doc: dict, openapi: dict, erd: dict,
                             ddl: str, req_id: str, revision_context: dict,
                             context_package: dict) -> dict | None:
        context_text = await self.prepare_llm_context(context_package, state="decomposing")

        # 构建修订指引
        revision_block = ""
        is_revision = revision_context.get("is_revision", False)
        if is_revision:
            rejection = revision_context.get("gate2_rejection", {})
            prev_a8 = revision_context.get("previous_a8_report", {})
            revision_block = f"""
修正指引:
- 上一轮 Gate2 拒绝原因: {json.dumps(rejection.get('reject_reasons', []), ensure_ascii=False)}
- A8 架构评审报告: {json.dumps(prev_a8, ensure_ascii=False)[:500]}
"""

        prompt = f"""你是一个技术项目经理。将以下需求拆解为开发任务 DAG。

需求 Spec:
{json.dumps(spec_doc, ensure_ascii=False)[:3000]}

API 端点:
{json.dumps(openapi, ensure_ascii=False)[:2000]}

数据实体:
{json.dumps(erd, ensure_ascii=False)[:2000]}

DDL:
{ddl[:1000]}

{revision_block}

{context_text}

输出严格 JSON（不要 markdown 包裹）:
{{
  "nodes": [
    {{
      "id": "task-01",
      "type": "planning|backend|frontend|db|testing|deployment",
      "title": "任务标题（简明扼要，含动词）",
      "description": "任务详细描述（30-100字）",
      "complexity": "low|medium|high",
      "estimated_hours": 4,
      "agent": "A9|A10|A11|A12",
      "steps": ["步骤1", "步骤2"],
      "needs_human_review": false,
      "human_review_reason": null
    }}
  ],
  "edges": [
    {{'from': "task-01", "to": "task-02", "type": "sequential|parallel"}}
  ],
  "critical_path": ["task-01", "task-03"],
  "parallel_groups": [
    {{'name': "前后端并行开发", "tasks": ["task-02", "task-04"]}}
  ],
  "total_estimated_hours": 48
}}

规则:
1. 节点数 5-20 个，过多请合并，过少请细分
2. type 按任务性质: planning=方案设计, backend=后端开发, frontend=前端开发,
   db=数据库变更, testing=测试编写, deployment=部署
3. complexity=high 的节点自动标记 needs_human_review=true
4. agent 映射: backend/frontend/db/planning→A9, deployment→A10, testing→A11
5. 每个数据实体至少对应一个 db 类型节点（DDL 迁移）
6. 每个 API 端点至少对应一个 backend 类型节点
7. edges 必须形成无环图，标注并行关系
8. critical_path 取依赖最长链路
9. parallel_groups 标注互不依赖的节点组
10. Gate2 打回时优先修正拒绝原因指出的问题

只输出 JSON"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="task_decomposition",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.2,
            max_tokens=4000,
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
            logger.warning(f"[A6] LLM JSON parse failed: {e}")
            return None

    # ── DAG 验证 ──────────────────────────────────────────────────────

    def _validate_dag(self, dag: dict) -> dict:
        nodes = dag.get("nodes", [])
        edges = dag.get("edges", [])
        node_ids = {n.get("id") for n in nodes}

        errors = []
        warnings = []

        # 节点数检查
        if len(nodes) < 5:
            errors.append("节点数 < 5")
        elif len(nodes) > 25:
            errors.append("节点数 > 25，拒绝写入")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # 边有效性检查
        for e in edges:
            f = e.get("from", "")
            t = e.get("to", "")
            if f not in node_ids:
                warnings.append(f"边 {f}→{t}: from 引用无效节点")
            if t not in node_ids:
                warnings.append(f"边 {f}→{t}: to 引用无效节点")
            if f == t:
                errors.append(f"自环边: {f}→{t}")

        # 孤岛节点检查
        connected = set()
        for e in edges:
            connected.add(e.get("from", ""))
            connected.add(e.get("to", ""))
        isolated = node_ids - connected
        if isolated:
            warnings.append(f"孤岛节点（无边连接）: {sorted(isolated)}")

        # critical_path 有效性检查
        cp = dag.get("critical_path", [])
        for nid in cp:
            if nid not in node_ids:
                warnings.append(f"critical_path 引用无效节点: {nid}")

        # 类型枚举检查
        valid_types = {"planning", "backend", "frontend", "db", "testing", "deployment"}
        valid_agents = {"A9", "A10", "A11", "A12"}
        for n in nodes:
            if n.get("type") not in valid_types:
                errors.append(f"节点 {n.get('id')}: 无效 type={n.get('type')}")
            if n.get("agent") not in valid_agents:
                errors.append(f"节点 {n.get('id')}: 无效 agent={n.get('agent')}")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    # ── Fallback ──────────────────────────────────────────────────────

    def _fallback_decompose(self, spec_doc: dict, openapi: dict, erd: dict) -> dict:
        """增强的 fallback: 基于 Spec 模块 + ERD 实体 + OpenAPI 端点推导任务"""
        nodes = []
        node_id = 1

        # 1. 规划阶段
        nodes.append({
            "id": f"task-{node_id:02d}", "type": "planning",
            "title": "技术方案设计", "complexity": "low",
            "estimated_hours": 2, "agent": "A9",
            "steps": ["确认技术栈", "设计模块架构", "评审技术方案"],
            "needs_human_review": False, "human_review_reason": None,
        })
        node_id += 1

        # 2. 从 ERD 推导 DB 任务
        entities = erd.get("entities", [])
        if entities:
            entity_names = [e.get("name", "Unknown") for e in entities[:5]]
            nodes.append({
                "id": f"task-{node_id:02d}", "type": "db",
                "title": f"数据库设计与迁移 ({', '.join(entity_names)})",
                "complexity": "medium", "estimated_hours": max(2, len(entities)),
                "agent": "A9",
                "steps": [
                    "编写 DDL migration",
                    "编写回滚 migration",
                    "本地验证 migration up/down",
                ],
                "needs_human_review": False, "human_review_reason": None,
            })
            node_id += 1

        # 3. 从 Spec 模块推导后端任务
        modules = spec_doc.get("modules", [])
        for module in modules[:5]:
            nodes.append({
                "id": f"task-{node_id:02d}", "type": "backend",
                "title": f"{module.get('name', 'API')} 接口开发",
                "complexity": "medium", "estimated_hours": 4,
                "agent": "A9",
                "steps": [
                    "定义 API 接口契约",
                    "实现业务逻辑层",
                    "编写输入校验",
                ],
                "needs_human_review": False, "human_review_reason": None,
            })
            node_id += 1

        # 4. 前端任务
        has_states = any(m.get("states") for m in modules)
        if has_states:
            nodes.append({
                "id": f"task-{node_id:02d}", "type": "frontend",
                "title": "前端页面开发", "complexity": "medium",
                "estimated_hours": 8, "agent": "A9",
                "steps": [
                    "实现核心页面组件",
                    "接入后端 API",
                    "处理加载态/空态/错误态",
                ],
                "needs_human_review": False, "human_review_reason": None,
            })
            node_id += 1

        # 5. 测试任务
        nodes.append({
            "id": f"task-{node_id:02d}", "type": "testing",
            "title": "功能验证与测试", "complexity": "medium",
            "estimated_hours": 4, "agent": "A11",
            "steps": ["执行 A7 生成的测试用例", "修复测试失败"],
            "needs_human_review": False, "human_review_reason": None,
        })
        node_id += 1

        # 6. 部署任务
        nodes.append({
            "id": f"task-{node_id:02d}", "type": "deployment",
            "title": "部署上线", "complexity": "low",
            "estimated_hours": 2, "agent": "A10",
            "steps": ["构建 Docker 镜像", "部署到测试环境", "验证部署"],
            "needs_human_review": False, "human_review_reason": None,
        })

        # 构建 edges
        edges = [
            {"from": nodes[i]["id"], "to": nodes[i+1]["id"], "type": "sequential"}
            for i in range(len(nodes)-1)
        ]

        return {
            "nodes": nodes,
            "edges": edges,
            "critical_path": [n["id"] for n in nodes],
            "parallel_groups": [],
            "total_estimated_hours": sum(n.get("estimated_hours", 0) for n in nodes),
            "source": "fallback",
        }

    # ── 持久化 ──────────────────────────────────────────────────────

    async def _save_task_dags(self, req_id: str, cycle: int, dag: dict,
                              metadata: dict) -> int:
        """写入 task_dags 表，返回 id"""
        pool = await self._get_db_pool()
        async with pool.acquire() as conn:
            # 计算版本号: MAX(version) + 1
            version = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM task_dags "
                "WHERE req_id = $1::uuid AND cycle = $2",
                req_id, cycle,
            )

            task_dags_id = await conn.fetchval("""
                INSERT INTO task_dags (
                    req_id, cycle, version, dag_json,
                    node_count, critical_path_length,
                    total_estimated_hours, human_review_nodes, source
                ) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9)
                RETURNING id
            """,
                req_id, cycle, version,
                json.dumps(dag, ensure_ascii=False),
                metadata["node_count"],
                len(dag.get("critical_path", [])),
                dag.get("total_estimated_hours", 0),
                metadata["human_review_nodes"],
                metadata["source"],
            )
            logger.info(f"[A6] Saved DAG to task_dags id={task_dags_id} version={version}")
            return task_dags_id

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
            logger.info(f"[A6] UPSERT agent_results: agent_key={agent_key} status={status}")

    # ── NATS 事件发布 ──────────────────────────────────────────────

    async def _publish_agent_result_a6(self, req_id: str, session_id: str,
                                        cycle: int, dag: dict, validation: dict):
        """发布 agent.result.A6 事件"""
        payload = {
            "req_id": req_id,
            "session_id": session_id,
            "cycle": cycle,
            "dag": dag,
            "validation": validation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        msg_id = f"{req_id}-agent.result.A6-{cycle}"

        await self.js.publish(
            "agent.result.A6",
            json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Nats-Msg-Id": msg_id},
        )
        logger.info(f"[A6] Published agent.result.A6 for req={req_id}")

    async def _publish_dag_created(self, req_id: str, cycle: int, dag: dict, metadata: dict):
        """发布 dag.created 事件"""
        payload = {
            "req_id": req_id,
            "cycle": cycle,
            "dag_id": dag["dag_id"],
            "node_count": metadata["node_count"],
            "critical_path_length": len(dag.get("critical_path", [])),
            "total_estimated_hours": dag.get("total_estimated_hours", 0),
            "source": metadata["source"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        msg_id = f"{req_id}-dag.created-{cycle}"

        await self.js.publish(
            "dag.created",
            json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Nats-Msg-Id": msg_id},
        )
        logger.info(f"[A6] Published dag.created for req={req_id}")
