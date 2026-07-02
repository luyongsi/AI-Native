"""
Temporal Workflow: Test-Driven Development Closed Loop (Task #36)

Implements the complete A7 → A9 → A11 TDD workflow:

1. A7: Generate structured test assets
2. Context Builder: Inject test assets into context
3. A9: TDD-mode code development (driven by tests)
4. A11: Execute tests, measure coverage, augment if needed
5. Publish test.tdd_complete event

State progression:
    START -> TEST_GENERATION -> TDD_DEVELOPMENT -> TEST_EXECUTION ->
    COVERAGE_CHECK -> (TEST_AUGMENTATION | COMPLETE)

Event flow:
    test.assets_ready (A7) → workflow receives → test.assets_ready_received
    → TDD_DEVELOPMENT phase → test.tdd_dev_complete (A9)
    → TEST_EXECUTION phase → test.completed/failed (A11)
    → test.tdd_complete (workflow)
"""

from __future__ import annotations

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.dispatch_agent import dispatch_agent
    from activities.context_build import build_context
    from activities.notify_mc import notify_mc
    import asyncpg
    import json

logger = logging.getLogger(__name__)

_DEFAULT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn(name="TestDrivenWorkflow")
class TestDrivenWorkflow:
    """Orchestrates the complete TDD closed-loop: test generation → TDD development → test execution."""

    def __init__(self) -> None:
        self._state: str = "START"
        self._test_assets: dict | None = None
        self._code_result: dict | None = None
        self._test_result: dict | None = None

    @workflow.run
    async def run(self, req_id: str, initial_context: dict) -> dict:
        """Run the complete TDD workflow.

        Args:
            req_id: Requirement ID
            initial_context: Initial context (may contain test_assets from event)

        Returns:
            Final TDD result with coverage and pass rate
        """
        workflow.logger.info(f"[TDD-Workflow] Started for req={req_id}")

        try:
            # ========== PHASE 1: TEST GENERATION ==========
            self._state = "TEST_GENERATION"
            workflow.logger.info(f"[TDD-Workflow] Phase 1: TEST_GENERATION for req={req_id}")

            # Dispatch A7 to generate test assets
            a7_result = await workflow.execute_activity(
                dispatch_agent,
                args=[req_id, "A7", "test_case_generator", initial_context],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=_DEFAULT_RETRY,
            )
            workflow.logger.info(f"[TDD-Workflow] A7 completed: asset_id={a7_result.get('asset_id')}")

            self._test_assets = a7_result.get("test_assets", {})

            # ========== PHASE 2: CONTEXT INJECTION ==========
            self._state = "CONTEXT_INJECTION"
            workflow.logger.info(f"[TDD-Workflow] Phase 2: CONTEXT_INJECTION for req={req_id}")

            # Build context with test assets injected
            context = await workflow.execute_activity(
                build_context,
                args=[req_id, "develop", self._test_assets],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_DEFAULT_RETRY,
            )
            workflow.logger.info(f"[TDD-Workflow] Context built with test_assets injected")

            # ========== PHASE 3: TDD DEVELOPMENT ==========
            self._state = "TDD_DEVELOPMENT"
            workflow.logger.info(f"[TDD-Workflow] Phase 3: TDD_DEVELOPMENT for req={req_id}")

            # Dispatch A9 with TDD mode enabled via context
            a9_result = await workflow.execute_activity(
                dispatch_agent,
                args=[req_id, "A9", "dev_agent", {"context": context, "test_assets": self._test_assets, "tdd_mode": True}],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=_DEFAULT_RETRY,
            )
            workflow.logger.info(f"[TDD-Workflow] A9 TDD development completed")

            self._code_result = a9_result

            # ========== PHASE 4: TEST EXECUTION ==========
            self._state = "TEST_EXECUTION"
            workflow.logger.info(f"[TDD-Workflow] Phase 4: TEST_EXECUTION for req={req_id}")

            # Dispatch A11 to execute tests and measure coverage
            a11_result = await workflow.execute_activity(
                dispatch_agent,
                args=[req_id, "A11", "auto_test", {"test_assets": self._test_assets, "code_result": a9_result}],
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=_DEFAULT_RETRY,
            )
            workflow.logger.info(f"[TDD-Workflow] A11 test execution completed: pass_rate={a11_result.get('pass_rate')}%")

            self._test_result = a11_result

            # ========== PHASE 5: COVERAGE VALIDATION ==========
            self._state = "COVERAGE_CHECK"
            coverage = a11_result.get("coverage", {})
            target_coverage = self._test_assets.get("coverage_targets", {}).get("overall", 0.8)
            current_coverage = coverage.get("overall_coverage", 0.0)
            coverage_gap = target_coverage - current_coverage

            workflow.logger.info(f"[TDD-Workflow] Coverage check: {current_coverage:.1%} / {target_coverage:.1%} (gap={coverage_gap:.1%})")

            if coverage_gap > 0 and a11_result.get("tests_augmented", 0) == 0:
                # If coverage insufficient and tests not yet augmented, re-run A11
                self._state = "TEST_AUGMENTATION"
                workflow.logger.info(f"[TDD-Workflow] Phase 5: TEST_AUGMENTATION to cover {coverage_gap:.1%}")

                # Re-dispatch A11 for augmented test round
                a11_augmented = await workflow.execute_activity(
                    dispatch_agent,
                    args=[req_id, "A11", "auto_test", {
                        "test_assets": self._test_assets,
                        "augment": True,
                        "coverage_gap": coverage_gap,
                    }],
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=_DEFAULT_RETRY,
                )
                workflow.logger.info(f"[TDD-Workflow] A11 augmentation completed")
                self._test_result = a11_augmented

            # ========== PHASE 6: COMPLETION ==========
            self._state = "COMPLETE"
            workflow.logger.info(f"[TDD-Workflow] Workflow completed for req={req_id}")

            # Notify MC of completion
            final_coverage = self._test_result.get("coverage", {}).get("overall_coverage", 0.0)
            await workflow.execute_activity(
                notify_mc,
                args=[req_id, "test_driven_workflow_completed", {
                    "test_cases": self._test_result.get("tests_total", 0),
                    "pass_rate": self._test_result.get("pass_rate", 0),
                    "coverage": final_coverage,
                    "target_coverage": target_coverage,
                    "augmented_tests": self._test_result.get("tests_augmented", 0),
                }],
                start_to_close_timeout=timedelta(seconds=30),
            )

            return {
                "status": "completed",
                "req_id": req_id,
                "test_assets_generated": len(self._test_assets.get("unit_tests", [])) +
                                        len(self._test_assets.get("integration_tests", [])) +
                                        len(self._test_assets.get("e2e_tests", [])),
                "tests_executed": self._test_result.get("tests_total", 0),
                "tests_passed": self._test_result.get("tests_passed", 0),
                "pass_rate": self._test_result.get("pass_rate", 0),
                "coverage": final_coverage,
                "target_coverage": target_coverage,
                "coverage_gap": target_coverage - final_coverage,
                "augmented_tests": self._test_result.get("tests_augmented", 0),
            }

        except Exception as e:
            workflow.logger.error(f"[TDD-Workflow] Failed at state={self._state}: {e}")
            await workflow.execute_activity(
                notify_mc,
                args=[req_id, "test_driven_workflow_failed", {
                    "state": self._state,
                    "error": str(e),
                }],
                start_to_close_timeout=timedelta(seconds=30),
            )
            return {
                "status": "failed",
                "req_id": req_id,
                "state": self._state,
                "error": str(e),
            }
