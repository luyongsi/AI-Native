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
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A7"
AGENT_TYPE = "test_case_generator"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")
MC_BACKEND_URL = os.environ.get("MC_BACKEND_URL", "http://localhost:8000")
VISAGENT_URL = os.environ.get("VISAGENT_URL", "http://localhost:8080")


class TestCaseGeneratorAgent(BaseAgentWorker):
    """A7: 根据 Spec + DAG 生成测试用例，集成本地 LLM + VisAgent"""

    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._http

    async def close(self):
        if self._http:
            await self._http.aclose()
        await super().close()

    async def _call_llm(self, messages: list, temperature: float = 0.2) -> str | None:
        if not DEEPSEEK_API_KEY:
            return None
        try:
            http = await self._get_http()
            resp = await http.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={"model": DEEPSEEK_MODEL, "messages": messages, "temperature": temperature, "max_tokens": 4000},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"[A7] LLM call failed: {e}")
            return None

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

        test_cases = await self._generate_with_llm(req_id, spec_text, dag_text, nodes)

        if not test_cases:
            await self.report_status(req_id, "running", "LLM 不可用, 使用规则生成")
            test_cases = self._fallback_generate(nodes)

        await self.report_status(req_id, "running",
                                 f"Phase 2: 保存 {len(test_cases)} 条用例到 MC Backend")

        # Save to MC Backend test_cases table
        saved_count = await self._save_to_backend(req_id, test_cases)

        # Push visual test cases to VisAgent
        visagent_count = await self._push_to_visagent(req_id, test_cases)

        # Publish test.ready event
        test_plan = {
            "test_plan_id": f"tp-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "total_cases": len(test_cases),
            "saved_to_mc": saved_count,
            "pushed_to_visagent": visagent_count,
            "cases": test_cases,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.report_artifact(req_id, "test_plan", test_plan)

        envelope = {
            "event_id": f"test-ready-{req_id}",
            "event_type": "test.ready",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": test_plan,
            "req_id": req_id,
            "agent_id": AGENT_ID,
        }
        await self.nc.publish("test.ready", json.dumps(envelope, ensure_ascii=False).encode())
        logger.info(f"[A7] Published test.ready: {len(test_cases)} cases")

        await self.report_status(req_id, "completed",
                                 f"测试用例生成: {len(test_cases)} 条 (MC:{saved_count}, VisAgent:{visagent_count})")
        return {"status": "completed", "test_cases": len(test_cases), "saved": saved_count}

    async def _fetch_spec_sections(self, req_id: str) -> list:
        try:
            http = await self._get_http()
            resp = await http.get(f"{MC_BACKEND_URL}/api/chat/{req_id}/spec")
            if resp.status_code == 200:
                return resp.json().get("sections", [])
        except Exception as e:
            logger.warning(f"[A7] Failed to fetch spec: {e}")
        return []

    async def _generate_with_llm(self, req_id: str, spec_text: str, dag_text: str, nodes: list) -> list | None:
        prompt = f"""你是测试工程师。根据以下 Spec 和 DAG 任务，生成完整的测试用例。

## 需求 Spec
{spec_text[:3000]}

## DAG 任务节点
{dag_text[:2000]}

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

        content = await self._call_llm([{"role": "user", "content": prompt}], temperature=0.2)
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
