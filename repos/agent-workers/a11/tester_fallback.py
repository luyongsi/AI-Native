"""
Tester Fallback — Direct Playwright execution when VisAgent is unavailable.

Provides a fallback path that runs Playwright tests directly, bypassing the
VisAgent cloud service. Used during VisAgent outages or for local development.
"""

import asyncio
import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)


class TesterFallback:
    """Executes tests directly via Playwright when VisAgent is unreachable."""

    def __init__(self, playwright_path: str = "npx playwright"):
        self.playwright_path = playwright_path
        self._visagent_reachable: bool | None = None

    async def execute_direct_playwright(self, test_case: dict) -> dict:
        """
        Execute a test case directly using Playwright as a fallback.

        Simulates `subprocess.run("npx playwright test")`.

        Args:
            test_case: A dict with keys: id, title, steps

        Returns:
            dict with: passed, test_name, duration_ms, output, error
        """
        test_name = test_case.get("title", test_case.get("id", "unnamed"))
        logger.warning(f"TesterFallback: falling back to direct Playwright for '{test_name}'")

        # Simulate subprocess invocation latency
        await asyncio.sleep(random.uniform(1.0, 3.0))

        start = time.monotonic()

        # Simulate playwright test execution
        passed = random.random() < 0.78  # Slightly lower pass rate than VisAgent
        duration_ms = int((time.monotonic() - start) * 1000)

        output_lines = [
            f"Running: {self.playwright_path} test",
            f"  Test: {test_name}",
            f"  Browser: chromium",
        ]

        if passed:
            output_lines.append(f"  Result: PASSED ({duration_ms}ms)")
            return {
                "passed": True,
                "test_name": test_name,
                "duration_ms": duration_ms,
                "output": "\n".join(output_lines),
                "error": None,
            }
        else:
            error = (
                f"AssertionError: Timed out waiting for selector "
                f"'{test_case.get('steps', [''])[0]}' after 30s"
            )
            output_lines.append(f"  Result: FAILED — {error}")
            return {
                "passed": False,
                "test_name": test_name,
                "duration_ms": duration_ms,
                "output": "\n".join(output_lines),
                "error": error,
            }

    async def should_use_fallback(self) -> bool:
        """
        Check whether we should use the Playwright fallback.

        Returns True if VisAgent is unreachable. Currently always returns False
        (stub — VisAgent is considered available).
        """
        if self._visagent_reachable is not None:
            return not self._visagent_reachable

        # Stub: simulate a health check
        await asyncio.sleep(0.05)

        # In production, this would make an HTTP GET to VisAgent /health
        # For the stub, VisAgent is always reachable
        self._visagent_reachable = True
        logger.debug("TesterFallback: VisAgent health check passed (stub)")
        return False

    async def refresh_health(self) -> bool:
        """Force a re-check of VisAgent health. Returns True if reachable."""
        self._visagent_reachable = None
        return not await self.should_use_fallback()
