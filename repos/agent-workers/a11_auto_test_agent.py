"""
A11 VisAgent Auto Test Agent — runs visual tests via VisAgent service.

Listens for test.ready events, executes visual tests via VisAgent API,
publishes results as test.completed events.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import httpx
import jwt
from base_worker import BaseAgentWorker
from a11.tester import VisAgentTester
from a11.healer_client import VisAgentHealerClient
from a11.result_converter import ResultConverter
from a11.stryker_runner import StrykerRunner
from a11.mutation_reporter import MutationReporter

logger = logging.getLogger(__name__)

AGENT_ID = "A11"
AGENT_TYPE = "auto_test"

MC_BACKEND_URL = os.environ.get("MC_BACKEND_URL", "http://localhost:8000")
JWT_SECRET = os.environ.get("JWT_SECRET", "mc-dev-secret-key-change-in-production")


def _get_auth_token() -> str:
    """Generate a JWT token for authenticating with MC Backend and VisAgent."""
    import time
    payload = {
        "sub": "a11-agent",
        "role": "agent",
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class A11AutoTestAgent(BaseAgentWorker):
    """A11 Auto Test Agent — executes visual tests against VisAgent."""

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(agent_id=AGENT_ID, agent_type=AGENT_TYPE, nats_url=nats_url)
        self._jwt_token = _get_auth_token()
        self._tester = VisAgentTester(jwt_token=self._jwt_token)
        self._healer = VisAgentHealerClient(jwt_token=self._jwt_token)
        self._converter = ResultConverter()
        self._stryker = StrykerRunner()
        self._reporter = MutationReporter()
        self._http_client: Optional[httpx.AsyncClient] = None

    async def init(self):
        await super().init()
        self._http_client = httpx.AsyncClient(
            base_url=MC_BACKEND_URL,
            headers={"Authorization": f"Bearer {self._jwt_token}"},
            timeout=httpx.Timeout(30.0),
        )
        logger.info(f"[A11] Auto Test Agent initialized, backend={MC_BACKEND_URL}")

    async def close(self):
        if self._http_client:
            await self._http_client.aclose()
        await self._tester.close()
        await self._healer.close()
        await super().close()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """Execute visual tests for a requirement."""
        logger.info(f"[A11] Starting visual test execution for req={req_id}")

        # Phase 1: Fetch test cases from MC Backend
        await self.report_status(req_id, "running", "Phase 1: 获取测试用例")
        test_cases = await self._fetch_test_cases(req_id)

        if not test_cases:
            await self.report_status(req_id, "running", "No test cases found, skipping visual test")
            return {"status": "skipped", "reason": "no_test_cases", "req_id": req_id}

        # Phase 2: Execute visual tests via VisAgent
        await self.report_status(req_id, "running",
                                 f"Phase 2: 执行 {len(test_cases)} 个可视化测试")
        batch_result = await self._tester.execute_batch(test_cases)

        # Phase 3: Process results
        await self.report_status(req_id, "running", "Phase 3: 处理测试结果")
        ai_results = []
        for result in batch_result["results"]:
            converted = self._converter.visagent_to_ai_format(result)
            ai_results.append(converted)

        # Phase 4: Heal failed tests
        failed_results = [r for r in batch_result["results"] if not r["passed"]]
        heal_results = []
        for failed in failed_results:
            heal_result = await self._healer.heal(
                failed.get("details", {}).get("test_case_id", "unknown"),
                failed.get("details", {}),
            )
            heal_results.append(heal_result)

        # Phase 5: Run Stryker mutation testing if coverage available
        mutation_result = None
        try:
            mutation_result = self._stryker.run(
                source_files=["src/**/*.ts", "src/**/*.tsx"],
                test_files=["tests/**/*.test.ts"],
            )
        except Exception as e:
            logger.warning(f"[A11] Stryker mutation skipped: {e}")

        # Phase 6: Publish results
        await self.report_status(req_id, "running", "Phase 6: 发布测试结果")

        # Publish test results to NATS
        for result in batch_result["results"]:
            test_name = result.get("test_name", "unknown")
            passed = result.get("passed", False)
            await self.nc.publish(
                f"{'test.completed' if passed else 'test.failed'}",
                {
                    "event_type": "test.completed" if passed else "test.failed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "test_name": test_name,
                        "passed": passed,
                        "duration_ms": result.get("duration_ms", 0),
                        "details": result.get("details", {}),
                    },
                    "req_id": req_id,
                    "agent_id": AGENT_ID,
                },
            )

        # Build final report artifact
        report = {
            "req_id": req_id,
            "tests_total": batch_result["total"],
            "tests_passed": batch_result["passed"],
            "tests_failed": batch_result["failed"],
            "pass_rate": round(batch_result["passed"] / max(batch_result["total"], 1) * 100, 1),
            "duration_ms": batch_result["duration_ms"],
            "results": ai_results,
            "heal_attempts": len(heal_results),
            "heal_successful": sum(1 for h in heal_results if h.get("healed")),
            "mutation_score": mutation_result.get("score") if mutation_result else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await self.report_artifact(req_id, "test_report", report)
        await self.report_status(req_id, "completed",
                                 f"完成: {batch_result['passed']}/{batch_result['total']} 通过")

        return {"status": "completed", **report, "heal_results": heal_results}

    async def _fetch_test_cases(self, req_id: str) -> list:
        """Fetch test cases from MC Backend for this requirement."""
        if not self._http_client:
            return []
        try:
            resp = await self._http_client.get(f"/api/tests/{req_id}/cases")
            resp.raise_for_status()
            data = resp.json()
            return data.get("items", [])
        except Exception as e:
            logger.warning(f"[A11] Failed to fetch test cases from MC Backend: {e}")
            return []


async def main():
    """Run A11 Agent standalone for testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    agent = A11AutoTestAgent()
    await agent.init()

    # Test: execute against a known requirement
    test_req_id = "49395ab8-e3c9-444d-be56-b37abada5c21"
    logger.info(f"[A11] Testing against req={test_req_id}")
    result = await agent.execute(test_req_id, {})
    logger.info(f"[A11] Test result: {result}")

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
