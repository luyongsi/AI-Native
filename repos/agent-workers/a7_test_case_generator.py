"""
A7: Test Case Generator Agent (测试用例生成)

触发: context.ready.A7 (Orchestrator 发布)
产出: test_assets 表 + agent_results UPSERT + agent.result.A7 + test.assets_ready
支持 dag_preview 模式: dag_available=false 时独立生成基础用例
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import asyncpg
import httpx

from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A7"
AGENT_TYPE = "test_case_generator"

MC_BACKEND_URL = "http://localhost:8000"
VISAGENT_URL = "http://localhost:8080"

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "ai_native"
DB_USER = "ai_native"
DB_PASSWORD = "ai_native_dev"


class TestCaseGeneratorAgent(BaseAgentWorker):
    """A7: 根据 Spec + DAG 生成测试用例，支持 dag_preview 模式"""

    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)
        self._http: httpx.AsyncClient | None = None
        self._db_pool: asyncpg.Pool | None = None

    async def init(self):
        """Initialize and subscribe to context.ready.A7."""
        await super().init()
        # 订阅 context.ready.A7 (主入口)
        await self.js.subscribe(
            "context.ready.A7",
            cb=self._handle_context_ready,
            stream="AI_NATIVE_EVENTS",
            durable="A7_consumer",
        )
        logger.info("[A7] Subscribed to context.ready.A7 (durable=A7_consumer)")

    async def _handle_context_ready(self, msg):
        """解析 context.ready.A7 消息，调用 execute()，ack/nak 处理"""
        try:
            data = json.loads(msg.data.decode())
            payload = data.get("payload", {})
            req_id = data.get("req_id", "") or payload.get("req_id", "")
            if not req_id:
                logger.warning("[A7] context.ready.A7 missing req_id, skipping")
                await msg.ack()
                return
            logger.info(f"[A7] Received context.ready.A7 for req={req_id}")
            await self.execute(req_id, payload)
            await msg.ack()
        except Exception as e:
            logger.error(f"[A7] Error handling context.ready.A7: {e}", exc_info=True)
            try:
                await msg.nak()
            except Exception:
                pass

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._http

    async def _get_db_pool(self) -> asyncpg.Pool:
        """Get or create database connection pool."""
        if self._db_pool is None:
            self._db_pool = await asyncpg.create_pool(
                host=DB_HOST, port=DB_PORT, database=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
                min_size=1, max_size=5,
            )
        return self._db_pool

    async def close(self):
        if self._http:
            await self._http.aclose()
        if self._db_pool:
            await self._db_pool.close()
        await super().close()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        # 1. 解析 context.ready.A7 格式
        spec_package = context_package.get("spec_package", {})
        spec_doc = spec_package.get("spec_doc", {})
        openapi = spec_package.get("openapi_schema", {})
        erd = spec_package.get("erd_diagram", {})

        dag_preview = context_package.get("dag_preview", {})
        dag_available = dag_preview.get("dag_available", False)
        dag_nodes = dag_preview.get("nodes", [])

        revision_context = context_package.get("revision_context", {})
        is_revision = revision_context.get("is_revision", False)

        session_id = context_package.get("session_id", "")
        cycle = context_package.get("cycle", 0)

        logger.info(f"[A7] Generating test cases req={req_id} "
                    f"(dag_available={dag_available}, revision={is_revision})")

        await self.report_status(req_id, "running",
            f"Phase 1: 分析 Spec {'+ DAG' if dag_available else ''}, 生成测试用例")

        # 2. LLM 生成
        test_cases = await self._generate_with_llm(
            req_id, spec_doc, openapi, erd,
            dag_nodes if dag_available else None,
            revision_context, context_package
        )

        if not test_cases:
            await self.report_status(req_id, "running", "LLM 不可用, 使用规则生成")
            test_cases = self._fallback_generate(dag_nodes if dag_available else [])

        # 3. 组织测试资产
        test_assets = self._organize_test_assets(test_cases)

        # 4. 写入 test_assets 表 (version 递增)
        asset_id = await self._save_to_postgres(req_id, test_assets)

        # 5. 写入 MC Backend
        saved_count = await self._save_to_backend(req_id, test_cases)

        # 6. 推送到 VisAgent
        visagent_count = await self._push_to_visagent(req_id, test_cases)

        # 7. 计算 DAG 覆盖
        dag_coverage = self._calculate_dag_coverage(test_cases, dag_nodes, dag_available)

        # 8. UPSERT agent_results (agent_key='A7')
        artifact = {
            "test_plan": {
                "test_plan_id": f"tp-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "total_cases": len(test_cases),
                "saved_to_postgres": asset_id is not None,
                "test_asset_id": asset_id,
                "saved_to_mc": saved_count,
                "pushed_to_visagent": visagent_count,
            },
            "test_assets": test_assets,
            "dag_coverage": dag_coverage,
        }
        await self._upsert_agent_results(req_id, "A7", cycle, "completed", artifact)

        # 9. 发布 NATS 事件
        await self._publish_agent_result_a7(req_id, session_id, cycle,
                                             test_assets, dag_coverage, asset_id)
        await self._publish_test_assets_ready(req_id, test_assets, asset_id)

        await self.report_status(req_id, "completed",
            f"测试用例生成: {len(test_cases)} 条 (MC:{saved_count}, VisAgent:{visagent_count})")

        return {"status": "completed", "test_cases": len(test_cases), "asset_id": asset_id}

    # ── DAG 覆盖计算 ──────────────────────────────────────────────

    def _calculate_dag_coverage(self, test_cases: list, dag_nodes: list,
                                 dag_available: bool) -> dict:
        """计算测试用例对 DAG 节点的覆盖率"""
        if not dag_available or not dag_nodes:
            return {
                "total_dag_nodes": 0,
                "covered_nodes": 0,
                "uncovered_nodes": [],
                "dag_available": False,
            }

        all_dag_ids = {n.get("id") for n in dag_nodes if n.get("id")}
        covered_ids = set()

        for case in test_cases:
            node_id = case.get("node_id")
            if node_id and node_id in all_dag_ids:
                covered_ids.add(node_id)

        uncovered = sorted(all_dag_ids - covered_ids)

        return {
            "total_dag_nodes": len(all_dag_ids),
            "covered_nodes": len(covered_ids),
            "uncovered_nodes": uncovered,
            "dag_available": True,
        }

    # ── 组织测试资产 ──────────────────────────────────────────────

    def _organize_test_assets(self, test_cases: list) -> dict:
        """组织测试用例为结构化测试资产（按类型分组）"""
        unit_tests = []
        integration_tests = []
        e2e_tests = []
        visual_tests = []
        priority_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}

        for case in test_cases:
            test_type = case.get("type", "unit")
            priority = case.get("priority", "P2")
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

            if test_type == "unit":
                unit_tests.append(case)
            elif test_type == "integration":
                integration_tests.append(case)
            elif test_type == "e2e":
                e2e_tests.append(case)
            elif test_type == "visual":
                visual_tests.append(case)
            else:
                # api 类型归入 integration
                integration_tests.append(case)

        return {
            "unit_tests": unit_tests,
            "integration_tests": integration_tests,
            "e2e_tests": e2e_tests,
            "visual_tests": visual_tests,
            "coverage_targets": {
                "overall": 0.8,
                "branches": 0.75,
                "lines": 0.85,
            },
            "priority_distribution": priority_counts,
        }

    # ── LLM 生成 ──────────────────────────────────────────────

    async def _generate_with_llm(self, req_id: str, spec_doc: dict,
                                  openapi: dict, erd: dict,
                                  dag_nodes: list | None,
                                  revision_context: dict,
                                  context_package: dict) -> list | None:
        """LLM 生成测试用例，支持 dag_preview 和修订模式"""
        context_text = await self.prepare_llm_context(context_package, state="testing")

        # 构建修订指引
        revision_block = ""
        is_revision = revision_context.get("is_revision", False)
        if is_revision:
            rejection = revision_context.get("gate2_rejection", {})
            revision_block = f"""
修正指引:
- 上一轮 Gate2 拒绝原因: {json.dumps(rejection.get('reject_reasons', []), ensure_ascii=False)}
- 修订指导: {rejection.get('revision_guidance', '无特定指导')}
"""

        # DAG 上下文块
        dag_block = ""
        if dag_nodes:
            dag_block = f"""
DAG 任务节点（测试用例必须覆盖这些节点）:
{json.dumps(dag_nodes, ensure_ascii=False)[:3000]}

规则:
- 每个 DAG 节点至少 2 条测试用例
- node_id 字段填写对应的 DAG 节点 ID
"""
        else:
            dag_block = """
注意: DAG 尚未生成（dag_available=false），请基于 Spec 独立生成基础用例。
- 不需要填写 node_id 字段
- 生成覆盖核心功能的基础用例集
"""

        spec_text = json.dumps(spec_doc, ensure_ascii=False)[:3000]
        openapi_text = json.dumps(openapi, ensure_ascii=False)[:2000]
        erd_text = json.dumps(erd, ensure_ascii=False)[:2000]

        prompt = f"""你是测试工程师。根据以下需求生成完整的测试用例。

需求 Spec:
{spec_text}

API 端点:
{openapi_text}

数据实体:
{erd_text}

{dag_block}

{revision_block}

{context_text}

输出严格 JSON 数组（不要 markdown 包裹）:
[
  {{
    "title": "测试用例标题（描述清楚测试什么）",
    "type": "unit|integration|e2e|visual|api",
    "priority": "P0|P1|P2",
    "description": "简要说明",
    "preconditions": "前置条件",
    "steps": [
      {{'step_number': 1, "action": "操作步骤", "expected": "预期结果"}}
    ],
    "tags": ["标签1"],
    "node_id": "对应的 DAG 节点 ID（dag_available=false时不填）"
  }}
]

规则:
1. 必须覆盖正常流程 + 异常/边界条件
2. type 按功能类型: 后端→api/unit, 前端→e2e/visual, 数据库→unit
3. 优先考虑安全相关: 鉴权、输入校验、SQL注入、XSS
4. P0: 核心流程/安全相关, P1: 重要功能, P2: 边界/异常
5. Gate2 打回时优先修正拒绝原因指出的问题

只输出 JSON"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="test_case_gen",
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
            cases = json.loads(content)
            return cases if isinstance(cases, list) else []
        except json.JSONDecodeError as e:
            logger.warning(f"[A7] LLM JSON parse failed: {e}")
            return None

    # ── Fallback ──────────────────────────────────────────────

    def _fallback_generate(self, nodes: list) -> list:
        """规则模式生成测试用例"""
        cases = []
        # 有 DAG 节点时按节点生成
        if nodes:
            for node in nodes:
                ntype = node.get("type", "unknown")
                ntitle = node.get("title", "Task")
                nid = node.get("id", "unknown")
                if ntype == "backend":
                    cases.append({"title": f"[API] {ntitle} - 正常请求", "type": "api", "priority": "P0", "node_id": nid, "steps": [{"step_number": 1, "action": "发送正常请求", "expected": "返回 200 + 正确数据"}]})
                    cases.append({"title": f"[API] {ntitle} - 参数校验", "type": "api", "priority": "P0", "node_id": nid, "steps": [{"step_number": 1, "action": "发送无效参数", "expected": "返回 400 + 错误信息"}]})
                elif ntype == "frontend":
                    cases.append({"title": f"[UI] {ntitle} - 页面渲染", "type": "visual", "priority": "P0", "node_id": nid, "steps": [{"step_number": 1, "action": "打开页面", "expected": "组件正常渲染"}]})
                    cases.append({"title": f"[UI] {ntitle} - 用户交互", "type": "e2e", "priority": "P1", "node_id": nid, "steps": [{"step_number": 1, "action": "执行核心操作流程", "expected": "流程完整无报错"}]})
                elif ntype == "db":
                    cases.append({"title": f"[DB] {ntitle} - Migration up", "type": "unit", "priority": "P0", "node_id": nid, "steps": [{"step_number": 1, "action": "执行 up migration", "expected": "无报错"}]})
                elif ntype == "testing":
                    cases.append({"title": f"[Test] {ntitle} - 测试执行", "type": "unit", "priority": "P1", "node_id": nid, "steps": [{"step_number": 1, "action": "运行测试套件", "expected": "测试通过"}]})
                elif ntype == "deployment":
                    cases.append({"title": f"[Deploy] {ntitle} - 部署验证", "type": "integration", "priority": "P1", "node_id": nid, "steps": [{"step_number": 1, "action": "部署到测试环境", "expected": "服务正常运行"}]})
                else:
                    cases.append({"title": f"[Unit] {ntitle} - 基础验证", "type": "unit", "priority": "P1", "node_id": nid, "steps": [{"step_number": 1, "action": "执行基础功能验证", "expected": "功能正常运行"}]})
        else:
            # dag_available=false 时独立生成基础用例
            cases = [
                {"title": "核心功能 - 正常流程", "type": "integration", "priority": "P0", "steps": [{"step_number": 1, "action": "执行核心业务流程", "expected": "流程完整无报错"}]},
                {"title": "核心功能 - 异常输入", "type": "unit", "priority": "P0", "steps": [{"step_number": 1, "action": "输入非法数据", "expected": "返回错误信息"}]},
                {"title": "鉴权 - 未授权访问", "type": "api", "priority": "P0", "steps": [{"step_number": 1, "action": "无 token 访问受保护接口", "expected": "返回 401"}]},
                {"title": "鉴权 - 无权限操作", "type": "api", "priority": "P1", "steps": [{"step_number": 1, "action": "低权限用户执行高权限操作", "expected": "返回 403"}]},
                {"title": "页面渲染 - 基础展示", "type": "e2e", "priority": "P0", "steps": [{"step_number": 1, "action": "打开核心页面", "expected": "页面正常渲染"}]},
                {"title": "数据存储 - CRUD", "type": "unit", "priority": "P0", "steps": [{"step_number": 1, "action": "创建/读取/更新/删除数据", "expected": "CRUD 操作全部成功"}]},
            ]
        return cases

    # ── 持久化 ──────────────────────────────────────────────

    async def _save_to_postgres(self, req_id: str, test_assets: dict) -> int | None:
        """写入 test_assets 表，version 递增 (COALESCE(MAX(version), 0) + 1)"""
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                # 获取下一个版本号
                version = await conn.fetchval(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM test_assets WHERE req_id = $1::uuid",
                    req_id,
                )

                result = await conn.fetchval("""
                    INSERT INTO test_assets (
                        req_id, unit_tests, integration_tests, e2e_tests,
                        visual_tests, coverage_targets, total_cases,
                        priority_distribution, source, version
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING id
                """,
                    req_id,
                    json.dumps(test_assets.get("unit_tests", []), ensure_ascii=False),
                    json.dumps(test_assets.get("integration_tests", []), ensure_ascii=False),
                    json.dumps(test_assets.get("e2e_tests", []), ensure_ascii=False),
                    json.dumps(test_assets.get("visual_tests", []), ensure_ascii=False),
                    json.dumps(test_assets.get("coverage_targets", {}), ensure_ascii=False),
                    sum(len(test_assets.get(k, [])) for k in ["unit_tests", "integration_tests", "e2e_tests", "visual_tests"]),
                    json.dumps(test_assets.get("priority_distribution", {}), ensure_ascii=False),
                    "a7_generator",
                    version,
                )
                logger.info(f"[A7] Saved test assets to PostgreSQL: id={result} version={version}")
                return result
        except Exception as e:
            logger.warning(f"[A7] Failed to save test assets to PostgreSQL: {e}")
            return None

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
            logger.info(f"[A7] UPSERT agent_results: agent_key={agent_key} status={status}")

    # ── MC Backend & VisAgent ──────────────────────────────────────

    async def _save_to_backend(self, req_id: str, cases: list) -> int:
        """Save test cases to MC Backend via REST API."""
        saved = 0
        try:
            http = await self._get_http()
            for case in cases:
                payload = {
                    "title": case.get("title", "Untitled")[:200],
                    "description": case.get("description", ""),
                    "steps": case.get("steps", []),
                    "preconditions": case.get("preconditions", ""),
                    "priority": case.get("priority", "P2"),
                    "tags": case.get("tags", ["ai_generated"]),
                }
                resp = await http.post(
                    f"{MC_BACKEND_URL}/api/tests/{req_id}/cases",
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    saved += 1
        except Exception as e:
            logger.warning(f"[A7] Failed to save test cases to backend: {e}")
        return saved

    async def _push_to_visagent(self, req_id: str, cases: list) -> int:
        """Push visual test cases to VisAgent platform."""
        count = 0
        visual_cases = [c for c in cases if c.get("type") in ("visual", "e2e")]
        if not visual_cases:
            return 0
        try:
            http = await self._get_http()
            for case in visual_cases[:10]:
                priority_map = {"P0": 1, "P1": 2, "P2": 3, "P3": 4}
                steps_text = "\n".join(
                    f"{s.get('action','')} -> {s.get('expected','')}"
                    for s in case.get("steps", [])
                )
                payload = {
                    "title": case.get("title", "")[:200],
                    "description": case.get("description", ""),
                    "natural_language_steps": steps_text or case.get("title", ""),
                    "preconditions": case.get("preconditions", ""),
                    "tags": case.get("tags", []),
                    "priority": priority_map.get(case.get("priority", "P2"), 3),
                }
                resp = await http.post(f"{VISAGENT_URL}/api/v1/testcases", json=payload)
                if resp.status_code in (200, 201):
                    count += 1
        except Exception as e:
            logger.warning(f"[A7] Failed to push test cases to VisAgent: {e}")
        return count

    # ── NATS 事件发布 ──────────────────────────────────────────────

    async def _publish_agent_result_a7(self, req_id: str, session_id: str,
                                        cycle: int, test_assets: dict,
                                        dag_coverage: dict, asset_id: int | None):
        """发布 agent.result.A7 事件（符合数据字典 §5.4 格式）"""
        total_cases = sum(len(test_assets.get(k, []))
                         for k in ["unit_tests", "integration_tests", "e2e_tests", "visual_tests"])

        payload = {
            "req_id": req_id,
            "session_id": session_id,
            "cycle": cycle,
            "test_assets": {
                "test_asset_id": asset_id,
                "test_plan_id": f"tp-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "total_cases": total_cases,
                "unit_tests": test_assets.get("unit_tests", []),
                "integration_tests": test_assets.get("integration_tests", []),
                "e2e_tests": test_assets.get("e2e_tests", []),
                "visual_tests": test_assets.get("visual_tests", []),
                "coverage_targets": test_assets.get("coverage_targets", {}),
                "priority_distribution": test_assets.get("priority_distribution", {}),
            },
            "dag_coverage": dag_coverage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        msg_id = f"{req_id}-agent.result.A7-{cycle}"

        await self.js.publish(
            "agent.result.A7",
            json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Nats-Msg-Id": msg_id},
        )
        logger.info(f"[A7] Published agent.result.A7 for req={req_id}")

    async def _publish_test_assets_ready(self, req_id: str, test_assets: dict,
                                          asset_id: int | None):
        """发布 test.assets_ready 事件（供 A11 订阅）"""
        total_cases = sum(len(test_assets.get(k, []))
                         for k in ["unit_tests", "integration_tests", "e2e_tests", "visual_tests"])

        payload = {
            "test_asset_id": asset_id,
            "test_plan_id": f"tp-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "total_cases": total_cases,
            "saved_to_postgres": asset_id is not None,
            "test_assets": test_assets,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        envelope = {
            "event_id": f"test-assets-ready-{req_id}",
            "event_type": "test.assets_ready",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "req_id": req_id,
            "agent_id": AGENT_ID,
        }

        msg_id = f"test-assets-{req_id}-{asset_id}"

        await self.js.publish(
            "test.assets_ready",
            json.dumps(envelope, ensure_ascii=False).encode(),
            headers={"Nats-Msg-Id": msg_id},
        )
        logger.info(f"[A7] Published test.assets_ready: {total_cases} cases, asset_id={asset_id}")
