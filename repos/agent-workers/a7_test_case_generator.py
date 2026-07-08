"""
A7: Test Case Generator Agent (测试用例生成)

Real LLM: 调用 DeepSeek API 根据 Spec + DAG 生成测试用例
集成 VisAgent: 将生成的视觉测试用例推送到 VisAgent 执行平台
持久化: 保存到 MC Backend test_cases 表

触发: dag.created (A6 完成后自动触发)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx
import asyncpg
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A7"
AGENT_TYPE = "test_case_generator"

MC_BACKEND_URL = os.environ.get("MC_BACKEND_URL", "http://localhost:8000")
VISAGENT_URL = os.environ.get("VISAGENT_URL", "http://localhost:8080")

# Database connection
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "ai_native")
DB_USER = os.environ.get("DB_USER", "ai_native")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "ai_native_dev")


class TestCaseGeneratorAgent(BaseAgentWorker):
    """A7: 根据 Spec + DAG 生成测试用例，集成本地 LLM + VisAgent"""

    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)
        self._http: httpx.AsyncClient | None = None
        self._db_pool: asyncpg.Pool | None = None

    async def init(self):
        """Initialize and subscribe to validation events."""
        await super().init()
        # Subscribe to test.validate events
        try:
            await self.nc.subscribe("test.validate", cb=self._handle_validate_event)
            logger.info(f"[A7] Subscribed to test.validate events")
        except Exception as e:
            logger.warning(f"[A7] Failed to subscribe to test.validate: {e}")

    async def _handle_validate_event(self, msg):
        """Handle incoming test.validate events from NATS."""
        try:
            data = json.loads(msg.data.decode())
            req_id = data.get("req_id")
            case_id = data.get("case_id")
            logger.info(f"[A7] Received validation request: req_id={req_id}, case_id={case_id}")

            # Fetch test case from DB
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM test_cases WHERE id = $1::uuid AND req_id = $2::uuid",
                    case_id,
                    req_id,
                )
                if not row:
                    logger.warning(f"[A7] Test case not found: {case_id}")
                    return

                # Convert row to dict
                test_case = dict(row)
                # Validate the test case
                await self.validate_test_case(req_id, case_id, test_case)
        except Exception as e:
            logger.error(f"[A7] Error handling validation event: {e}")

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._http

    async def _get_db_pool(self) -> asyncpg.Pool:
        """Get or create database connection pool."""
        if self._db_pool is None:
            self._db_pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                min_size=1,
                max_size=5,
            )
        return self._db_pool

    async def close(self):
        if self._http:
            await self._http.aclose()
        if self._db_pool:
            await self._db_pool.close()
        await super().close()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        dag = context_package.get("dag", context_package.get("payload", {}))
        nodes = dag.get("nodes", context_package.get("nodes", []))

        logger.info(f"[A7] Generating test cases for req={req_id}, nodes={len(nodes)}")
        await self.report_status(req_id, "running", f"Phase 1: 分析 DAG + Spec, 生成测试用例")

        # Read spec from DB for context
        try:
            spec_sections = await self._fetch_spec_sections(req_id)
        except Exception:
            spec_sections = []

        # Use LLM to generate test cases
        spec_text = "\n".join(
            f"{s.get('title','')}: {s.get('content','')[:300]}"
            for s in spec_sections[:5]
        ) if spec_sections else json.dumps(dag, ensure_ascii=False)[:2000]

        dag_text = json.dumps(nodes, ensure_ascii=False, indent=2)[:2000]

        test_cases = await self._generate_with_llm(req_id, spec_text, dag_text, nodes, context_package)

        if not test_cases:
            await self.report_status(req_id, "running", "LLM 不可用, 使用规则生成")
            test_cases = self._fallback_generate(nodes)

        await self.report_status(req_id, "running",
                                 f"Phase 2: 保存 {len(test_cases)} 条用例到 MC Backend + PostgreSQL")

        # Organize test cases by type
        test_assets = self._organize_test_assets(test_cases)

        # Save to PostgreSQL test_assets table
        asset_id = await self._save_to_postgres(req_id, test_assets)

        # Save to MC Backend test_cases table
        saved_count = await self._save_to_backend(req_id, test_cases)

        # Push visual test cases to VisAgent
        visagent_count = await self._push_to_visagent(req_id, test_cases)

        # Publish test.assets_ready event with structured test assets
        test_plan = {
            "test_asset_id": asset_id,
            "test_plan_id": f"tp-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "total_cases": len(test_cases),
            "saved_to_postgres": asset_id is not None,
            "saved_to_mc": saved_count,
            "pushed_to_visagent": visagent_count,
            "test_assets": test_assets,  # Structured assets for injection
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.report_artifact(req_id, "test_plan", test_plan)

        envelope = {
            "event_id": f"test-assets-ready-{req_id}",
            "event_type": "test.assets_ready",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": test_plan,
            "req_id": req_id,
            "agent_id": AGENT_ID,
        }
        await self.nc.publish("test.assets_ready", json.dumps(envelope, ensure_ascii=False).encode())
        logger.info(f"[A7] Published test.assets_ready: {len(test_cases)} cases, asset_id={asset_id}")

        await self.report_status(req_id, "completed",
                                 f"测试用例生成: {len(test_cases)} 条 (MC:{saved_count}, VisAgent:{visagent_count}, PG:{asset_id})")
        return {"status": "completed", "test_cases": len(test_cases), "saved": saved_count, "asset_id": asset_id}

    def _organize_test_assets(self, test_cases: list) -> dict:
        """Organize test cases into structured test assets by type.

        Returns:
            {
                'unit_tests': [...],
                'integration_tests': [...],
                'e2e_tests': [...],
                'visual_tests': [...],
                'coverage_targets': {...},
                'priority_distribution': {...}
            }
        """
        unit_tests = []
        integration_tests = []
        e2e_tests = []
        visual_tests = []
        priority_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}

        for case in test_cases:
            test_type = case.get("type", "unit")
            priority = case.get("priority", "P2")
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

            # Organize by type
            if test_type == "unit":
                unit_tests.append(case)
            elif test_type == "integration":
                integration_tests.append(case)
            elif test_type == "e2e":
                e2e_tests.append(case)
            elif test_type == "visual":
                visual_tests.append(case)
            else:
                # Default to unit if type not recognized
                unit_tests.append(case)

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

    async def _save_to_postgres(self, req_id: str, test_assets: dict) -> int | None:
        """Save structured test assets to PostgreSQL test_assets table.

        Returns:
            test_asset_id if successful, None otherwise
        """
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                # Insert into test_assets table
                result = await conn.fetchval("""
                    INSERT INTO test_assets (
                        req_id,
                        unit_tests,
                        integration_tests,
                        e2e_tests,
                        visual_tests,
                        coverage_targets,
                        total_cases,
                        priority_distribution,
                        source,
                        version
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
                1,
                )
                logger.info(f"[A7] Saved test assets to PostgreSQL: id={result}")
                return result
        except Exception as e:
            logger.warning(f"[A7] Failed to save test assets to PostgreSQL: {e}")
            return None

    async def _fetch_spec_sections(self, req_id: str) -> list:
        try:
            http = await self._get_http()
            resp = await http.get(f"{MC_BACKEND_URL}/api/chat/{req_id}/spec")
            if resp.status_code == 200:
                return resp.json().get("sections", [])
        except Exception as e:
            logger.warning(f"[A7] Failed to fetch spec: {e}")
        return []

    async def _generate_with_llm(self, req_id: str, spec_text: str, dag_text: str, nodes: list, context_package: dict) -> list | None:
        context_text = await self.prepare_llm_context(context_package, state="testing")
        prompt = f"""你是测试工程师。根据以下 Spec 和 DAG 任务，生成完整的测试用例。

{context_text}

输出 JSON 数组（只输出 JSON, 不要 markdown）：
[
  {{
    "title": "测试用例标题（描述清楚测试什么）",
    "type": "unit|integration|e2e|visual|api",
    "priority": "P0|P1|P2",
    "description": "简要说明",
    "preconditions": "前置条件",
    "steps": [
      {{"step_number": 1, "action": "操作步骤", "expected": "预期结果"}}
    ],
    "tags": ["标签1"],
    "node_id": "对应的 DAG 节点 ID"
  }}
]

规则:
- 为每个 DAG 节点生成至少 2 条用例
- type 按节点类型: backend→api/unit, frontend→e2e/visual, db→unit
- 必须覆盖正常流程 + 异常/边界条件
- 优先考虑安全相关: 鉴权、输入校验、SQL注入、XSS"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="test_case_gen",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.2,
            max_tokens=2000,
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

    def _fallback_generate(self, nodes: list) -> list:
        cases = []
        for node in nodes:
            ntype = node.get("type", "unknown")
            ntitle = node.get("title", "Task")
            nid = node.get("id", "unknown")
            if ntype == "backend":
                cases.append({"title": f"[API] {ntitle} - 正常请求", "type": "api", "priority": "P0", "steps": [{"step_number": 1, "action": "发送正常请求", "expected": "返回 200 + 正确数据"}]})
                cases.append({"title": f"[API] {ntitle} - 参数校验", "type": "api", "priority": "P0", "steps": [{"step_number": 1, "action": "发送无效参数", "expected": "返回 400 + 错误信息"}]})
            elif ntype == "frontend":
                cases.append({"title": f"[UI] {ntitle} - 页面渲染", "type": "visual", "priority": "P0", "steps": [{"step_number": 1, "action": "打开页面", "expected": "组件正常渲染"}]})
                cases.append({"title": f"[UI] {ntitle} - 用户交互", "type": "e2e", "priority": "P1", "steps": [{"step_number": 1, "action": "执行核心操作流程", "expected": "流程完整无报错"}]})
            elif ntype == "db":
                cases.append({"title": f"[DB] {ntitle} - Migration up", "type": "unit", "priority": "P0", "steps": [{"step_number": 1, "action": "执行 up migration", "expected": "无报错"}]})
        return cases

    async def _save_to_backend(self, req_id: str, cases: list) -> int:
        """Save test cases to MC Backend via its REST API."""
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

    # ── Test Case Validation Methods ─────────────────────────────────────────

    async def validate_test_case(self, req_id: str, case_id: str, test_case: dict) -> dict:
        """Validate a test case for syntax and logic correctness.

        Returns:
            {
                "case_id": str,
                "req_id": str,
                "validation_status": "passed" | "failed",
                "errors": [...],
                "warnings": [...]
            }
        """
        logger.info(f"[A7] Validating test case: req_id={req_id}, case_id={case_id}")

        errors = []
        warnings = []

        # Check syntax
        syntax_errors = await self._check_syntax(test_case)
        errors.extend(syntax_errors)

        # Check logic
        logic_issues = await self._check_logic(test_case)
        errors.extend(logic_issues.get("errors", []))
        warnings.extend(logic_issues.get("warnings", []))

        validation_status = "passed" if not errors else "failed"

        # Update database with validation results
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE test_cases
                    SET validation_status = $1,
                        validation_errors = $2,
                        updated_at = NOW()
                    WHERE id = $3::uuid AND req_id = $4::uuid
                    """,
                    validation_status,
                    json.dumps({"errors": errors, "warnings": warnings}),
                    case_id,
                    req_id,
                )
        except Exception as e:
            logger.error(f"[A7] Failed to update validation status: {e}")

        # Publish validation result event
        result = {
            "case_id": case_id,
            "req_id": req_id,
            "validation_status": validation_status,
            "errors": errors,
            "warnings": warnings,
        }

        event_envelope = {
            "event_id": f"test-validated-{case_id}",
            "event_type": "test.validated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": result,
            "req_id": req_id,
            "agent_id": AGENT_ID,
        }
        await self.nc.publish("test.validated", json.dumps(event_envelope, ensure_ascii=False).encode())
        logger.info(f"[A7] Published test.validated: {case_id}, status={validation_status}")

        return result

    async def _check_syntax(self, test_case: dict) -> list:
        """Check test case syntax.

        Returns:
            List of error messages
        """
        errors = []

        # Check required fields
        if not test_case.get("title"):
            errors.append("Missing required field: title")
        if not test_case.get("steps") or not isinstance(test_case.get("steps"), list):
            errors.append("Steps must be a non-empty list")

        # Check steps structure
        steps = test_case.get("steps", [])
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"Step {i} is not a dictionary")
                continue
            if not step.get("action"):
                errors.append(f"Step {i} missing action")
            if not step.get("expected"):
                errors.append(f"Step {i} missing expected result")
            if "step_number" in step and not isinstance(step["step_number"], int):
                errors.append(f"Step {i} number is not an integer")

        # Check priority is valid
        valid_priorities = ["P0", "P1", "P2", "P3"]
        if test_case.get("priority") and test_case.get("priority") not in valid_priorities:
            errors.append(f"Invalid priority: {test_case.get('priority')}")

        return errors

    async def _check_logic(self, test_case: dict) -> dict:
        """Check test case logic consistency.

        Returns:
            {
                "errors": [...],
                "warnings": [...]
            }
        """
        errors = []
        warnings = []

        title = test_case.get("title", "")
        steps = test_case.get("steps", [])
        preconditions = test_case.get("preconditions", "")

        # Check for empty preconditions with DB-related test
        if not preconditions and ("database" in title.lower() or "db" in title.lower()):
            warnings.append("Database test missing preconditions")

        # Check for unreasonable step count
        if len(steps) > 20:
            warnings.append("Test case has unusually many steps (>20)")
        elif len(steps) < 1:
            errors.append("Test case must have at least one step")

        # Check for suspicious patterns in expected results
        for i, step in enumerate(steps):
            expected = step.get("expected", "").lower()
            if "todo" in expected or "fix" in expected or "pending" in expected:
                warnings.append(f"Step {i} has incomplete expected result: {step.get('expected')}")

        # Check for test case title clarity
        if len(title) < 5:
            warnings.append("Test case title is too short, consider being more descriptive")
        if len(title) > 200:
            errors.append("Test case title exceeds 200 characters")

        return {"errors": errors, "warnings": warnings}
