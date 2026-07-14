"""
A11: Auto Test Agent (自动化测试 — LLM 驱动)

Phase 5.2: 升级为真实 LLM — 调用 DeepSeek 分析代码变更并生成测试策略
触发: code_diff 或 context.ready 事件
产出: test_report → 发布 test.passed/test.failed
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)


class A11TestAgentStub(BaseAgentWorker):
    agent_id = "A11"
    agent_type = "test_agent"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)

    async def execute(self, req_id: str, context_package: dict) -> dict:
        code_diff = context_package.get("code_diff", context_package.get("payload", {}))
        changes = code_diff.get("changes", [])

        logger.info(f"[A11] Testing {len(changes)} changes for req={req_id}")

        await self.report_status(req_id, "running", "Phase 1: LLM 测试策略分析")

        # LLM-generated test strategy
        test_suites = await self._plan_tests_with_llm(req_id, changes)
        if not test_suites:
            test_suites = self._fallback_plan(changes)

        await self.report_status(req_id, "running", f"Phase 2: 执行 {len(test_suites)} 套测试")

        # Simulate test execution (production: call pytest/playwright)
        results = self._run_tests(test_suites)

        await self.report_status(req_id, "running", "Phase 3: 生成测试报告")
        report = self._build_report(results, test_suites)
        await self.report_artifact(req_id, "test_report", report)

        # Publish result
        passed = report["failed"] == 0
        event_type = "test.passed" if passed else "test.failed"
        envelope = {
            "event_id": f"test-{req_id}",
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"req_id": req_id, "report": report, "passed": passed},
            "req_id": req_id,
            "agent_id": self.agent_id,
        }
        await self.js.publish(event_type, json.dumps(envelope, ensure_ascii=False).encode(),
                              headers={"Nats-Msg-Id": f"test-result-{req_id}"})
        logger.info(f"[A11] Published {event_type} passed={passed}")

        return {"status": "completed", "total": report["total"], "passed": report["passed"],
                "failed": report["failed"], "pass_rate": report["pass_rate"]}

    async def _plan_tests_with_llm(self, req_id: str, changes: list) -> list | None:
        if not changes:
            return None

        files_info = json.dumps([{"path": c.get("path", ""), "change_type": c.get("change_type", "modified"),
                                   "lines_added": c.get("lines_added", 0), "lines_removed": c.get("lines_removed", 0)}
                                  for c in changes[:10]], ensure_ascii=False)

        prompt = f"""你是测试工程师。根据代码变更生成测试策略。

变更文件:
{files_info}

输出 JSON:
{{
  "suites": [
    {{"name": "suite名称", "type": "unit|integration|api|smoke|e2e", "target_files": ["文件路径"],
      "test_cases": [{{"name": "用例名", "input": "输入", "expected": "期望输出", "priority": "P0|P1|P2"}}],
      "estimated_count": 5 }}
  ]
}}
只输出 JSON。"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="test_execution",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.2,
            max_tokens=2000,
        )
        if not content:
            return None
        try:
            content = content.strip()
            if content.startswith("```"): content = content.split("```")[1].split("```")[0].strip()
            if content.startswith("json"): content = content[4:].strip()
            data = json.loads(content)
            return data.get("suites", [])
        except json.JSONDecodeError:
            return None

    def _fallback_plan(self, changes: list) -> list:
        suites = []
        type_map = {"src/routes": "api", "src/models": "unit", "src/services": "unit",
                     "tests": "unit", "src/main.py": "smoke", "src/db.py": "unit"}
        seen = set()
        for change in changes:
            path = change.get("path", "")
            for prefix, t in type_map.items():
                if path.startswith(prefix) and t not in seen:
                    suites.append({"name": f"{t}_suite", "type": t, "target_files": [path],
                                   "test_cases": [{"name": f"test_{t}_basic", "priority": "P1"}],
                                   "estimated_count": random.randint(3, 10)})
                    seen.add(t)
                    break
        if not suites:
            suites.append({"name": "smoke_suite", "type": "smoke", "target_files": ["all"],
                           "test_cases": [{"name": "test_smoke", "priority": "P0"}], "estimated_count": 3})
        return suites

    def _run_tests(self, suites: list) -> list:
        results = []
        for suite in suites:
            for case in suite.get("test_cases", [{"name": "auto_case"}]):
                is_fail = random.random() < 0.15  # 15% fail rate
                results.append({
                    "suite": suite["name"], "case": case.get("name", "auto"),
                    "status": "failed" if is_fail else "passed",
                    "duration_ms": random.randint(5, 500),
                    "error": f"AssertionError: {case.get('expected', 'expected')} != actual" if is_fail else None,
                })
        return results

    def _build_report(self, results: list, suites: list) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r["status"] == "passed")
        failed = total - passed
        return {
            "total": total, "passed": passed, "failed": failed,
            "pass_rate": round(passed / total * 100, 1) if total > 0 else 100.0,
            "results": results, "suites": suites,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
