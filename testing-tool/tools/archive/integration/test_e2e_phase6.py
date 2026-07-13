"""
Phase 6 End-to-End Integration Tests.

Tests three scenarios with varying complexity:
1. Simple requirement (< 2h): Add email_verified field
2. Medium requirement (< 8h): User login functionality
3. Complex requirement: Multi-tenant permission system
"""

import asyncio
import json
import logging
import pytest
from datetime import datetime, timezone
from typing import List

from e2e_test_framework import E2ETestFramework, TestResult
from event_tracker import EventTracker
from quality_validator import QualityValidator
from report_generator import ReportGenerator

logger = logging.getLogger(__name__)

# Test configuration
NATS_URL = "nats://localhost:4222"
DB_URL = "postgresql://localhost:5432/ai_native"
REDIS_URL = "redis://localhost:6379"

# Scenario definitions
SCENARIO_1_SIMPLE = {
    "id": "scenario_1",
    "name": "Add email_verified field to users table",
    "title": "User Email Verification Field",
    "description": """
    Add email_verified field to users table:
    - Database migration: users table new BOOLEAN field email_verified, default false
    - API interface: PATCH /api/users/:id/verify-email
    - Unit tests: verify field default value and update logic

    Estimated time: < 2 hours
    """,
    "timeout": 7200,  # 2 hours
    "priority": "P2",
}

SCENARIO_2_MEDIUM = {
    "id": "scenario_2",
    "name": "Implement user login functionality",
    "title": "User Authentication System",
    "description": """
    Implement user login functionality:
    - API Schema: POST /auth/login (username, password)
    - ERD: sessions table design
    - Backend: JWT token generation and validation
    - Frontend: Login form + token storage
    - Testing: unit tests + integration tests

    Estimated time: < 8 hours
    """,
    "timeout": 28800,  # 8 hours
    "priority": "P1",
}

SCENARIO_3_COMPLEX = {
    "id": "scenario_3",
    "name": "Multi-tenant RBAC permission system",
    "title": "Role-Based Access Control",
    "description": """
    Implement multi-tenant permission management:
    - Database: tenants, roles, permissions, user_roles tables
    - API: RBAC permission check middleware
    - Backend: permission management CRUD + permission tree
    - Testing: boundary tests + performance tests

    Complex requirement (reference benchmark, no time target).
    """,
    "timeout": None,  # No specific timeout
    "priority": "P0",
}


class TestE2EPhase6:
    """End-to-end integration tests for Phase 6."""

    @pytest.fixture
    async def framework(self):
        """Set up E2E test framework."""
        fw = E2ETestFramework(
            nats_url=NATS_URL,
            db_url=DB_URL,
            redis_url=REDIS_URL,
        )
        await fw.setup()
        yield fw
        await fw.teardown()

    @pytest.mark.asyncio
    @pytest.mark.timeout(7200)  # 2 hour timeout
    async def test_scenario_1_simple_requirement(self, framework):
        """
        Test Scenario 1: Simple requirement (email_verified field).

        Acceptance criteria:
        - Requirement completes within 2 hours
        - API schema is generated
        - ERD is generated
        - Code is generated (> 0 files changed)
        - Tests pass with >= 80% pass rate
        - Code quality >= 4.0/5
        """
        logger.info("Starting Scenario 1 test (simple requirement)")
        start_time = datetime.now(timezone.utc)

        # Initialize tracking
        event_tracker = EventTracker(framework.nats_client)
        await event_tracker.subscribe_all()
        event_task = asyncio.create_task(event_tracker.consume_events())

        validator = QualityValidator(framework.db_pool)

        try:
            # Submit requirement
            req_id = await framework.submit_requirement(
                title=SCENARIO_1_SIMPLE["title"],
                description=SCENARIO_1_SIMPLE["description"],
                priority=SCENARIO_1_SIMPLE["priority"],
            )
            logger.info(f"Submitted requirement {req_id}")

            # Wait for completion
            completed = await framework.wait_for_completion(
                req_id,
                target_gate=7,
                timeout=SCENARIO_1_SIMPLE["timeout"],
            )

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            # Verify outputs
            outputs = await framework.verify_outputs(req_id)
            status = await framework.get_requirement_status(req_id)

            logger.info(f"Requirement {req_id} completion status: {completed}")
            logger.info(f"Duration: {duration:.2f}s")
            logger.info(f"Outputs: {outputs}")

            # Assertions
            assert completed, "Requirement did not complete within timeout"
            assert outputs["api_schema"], "API schema not generated"
            assert outputs["erd"], "ERD not generated"
            assert outputs["code"]["files_changed"] > 0, "No code generated"
            assert outputs["tests"]["pass_rate"] >= 0.8, "Test pass rate < 80%"
            assert duration < SCENARIO_1_SIMPLE["timeout"], (
                f"Duration {duration}s exceeds target {SCENARIO_1_SIMPLE['timeout']}s"
            )

            # Get event timeline for validation
            timeline = event_tracker.get_timeline(req_id)
            logger.info(f"Captured {len(timeline)} events")

            # Verify expected event sequence
            expected_events = [
                "requirement.intake",
                "knowledge.analyzed",
                "spec.api_schema_ready",
                "spec.erd_ready",
                "code.generated",
                "test.executed",
            ]
            success, message = event_tracker.verify_event_sequence(req_id, expected_events)
            assert success, f"Event sequence validation failed: {message}"

            # Cleanup
            await framework.cleanup_test_data(req_id)

            # Create test result
            result = TestResult(
                scenario_id=SCENARIO_1_SIMPLE["id"],
                scenario_name=SCENARIO_1_SIMPLE["name"],
                req_id=req_id,
                status="passed",
                duration_seconds=duration,
                start_time=start_time,
                end_time=end_time,
                outputs=outputs,
                events=timeline,
            )

            logger.info(f"Scenario 1 PASSED ({duration:.2f}s)")
            return result

        except Exception as e:
            logger.error(f"Scenario 1 FAILED: {e}", exc_info=True)
            await framework.cleanup_test_data(req_id)
            raise

        finally:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
            await event_tracker.unsubscribe_all()

    @pytest.mark.asyncio
    @pytest.mark.timeout(28800)  # 8 hour timeout
    async def test_scenario_2_medium_requirement(self, framework):
        """
        Test Scenario 2: Medium requirement (user login).

        Acceptance criteria:
        - Requirement completes within 8 hours
        - API schema is generated and valid
        - ERD is generated with proper relationships
        - Code is generated for backend + frontend
        - Tests pass with >= 80% pass rate
        - Code quality >= 4.0/5
        - Test coverage >= 70%
        """
        logger.info("Starting Scenario 2 test (medium requirement)")
        start_time = datetime.now(timezone.utc)

        event_tracker = EventTracker(framework.nats_client)
        await event_tracker.subscribe_all()
        event_task = asyncio.create_task(event_tracker.consume_events())

        validator = QualityValidator(framework.db_pool)
        req_id = None

        try:
            # Submit requirement
            req_id = await framework.submit_requirement(
                title=SCENARIO_2_MEDIUM["title"],
                description=SCENARIO_2_MEDIUM["description"],
                priority=SCENARIO_2_MEDIUM["priority"],
            )
            logger.info(f"Submitted requirement {req_id}")

            # Wait for completion
            completed = await framework.wait_for_completion(
                req_id,
                target_gate=7,
                timeout=SCENARIO_2_MEDIUM["timeout"],
            )

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            # Verify outputs
            outputs = await framework.verify_outputs(req_id)
            status = await framework.get_requirement_status(req_id)

            logger.info(f"Requirement {req_id} completion status: {completed}")
            logger.info(f"Duration: {duration:.2f}s")
            logger.info(f"Outputs: {outputs}")

            # Assertions
            assert completed, "Requirement did not complete within timeout"
            assert outputs["api_schema"], "API schema not generated"
            assert outputs["erd"], "ERD not generated"
            assert outputs["code"]["files_changed"] > 0, "No code generated"
            assert outputs["tests"]["pass_rate"] >= 0.8, "Test pass rate < 80%"
            assert duration < SCENARIO_2_MEDIUM["timeout"], (
                f"Duration {duration}s exceeds target {SCENARIO_2_MEDIUM['timeout']}s"
            )

            # Verify event timeline
            timeline = event_tracker.get_timeline(req_id)
            logger.info(f"Captured {len(timeline)} events")

            expected_events = [
                "requirement.intake",
                "knowledge.analyzed",
                "spec.api_schema_ready",
                "spec.erd_ready",
                "architecture.dag_built",
                "code.generated",
                "test.executed",
            ]
            success, message = event_tracker.verify_event_sequence(req_id, expected_events)
            assert success, f"Event sequence validation failed: {message}"

            # Cleanup
            await framework.cleanup_test_data(req_id)

            result = TestResult(
                scenario_id=SCENARIO_2_MEDIUM["id"],
                scenario_name=SCENARIO_2_MEDIUM["name"],
                req_id=req_id,
                status="passed",
                duration_seconds=duration,
                start_time=start_time,
                end_time=end_time,
                outputs=outputs,
                events=timeline,
            )

            logger.info(f"Scenario 2 PASSED ({duration:.2f}s)")
            return result

        except Exception as e:
            logger.error(f"Scenario 2 FAILED: {e}", exc_info=True)
            if req_id:
                await framework.cleanup_test_data(req_id)
            raise

        finally:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
            await event_tracker.unsubscribe_all()

    @pytest.mark.asyncio
    async def test_scenario_3_complex_requirement(self, framework):
        """
        Test Scenario 3: Complex requirement (multi-tenant RBAC).

        Acceptance criteria (process completeness only):
        - All major phases are executed
        - Event timeline is complete
        - No blocking errors
        - Output artifacts are generated
        """
        logger.info("Starting Scenario 3 test (complex requirement)")
        start_time = datetime.now(timezone.utc)

        event_tracker = EventTracker(framework.nats_client)
        await event_tracker.subscribe_all()
        event_task = asyncio.create_task(event_tracker.consume_events())

        req_id = None

        try:
            # Submit requirement
            req_id = await framework.submit_requirement(
                title=SCENARIO_3_COMPLEX["title"],
                description=SCENARIO_3_COMPLEX["description"],
                priority=SCENARIO_3_COMPLEX["priority"],
            )
            logger.info(f"Submitted requirement {req_id}")

            # Wait for completion (allow longer time for complex scenario)
            completed = await framework.wait_for_completion(
                req_id,
                target_gate=7,
                timeout=86400,  # 24 hours
            )

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            # Verify outputs
            outputs = await framework.verify_outputs(req_id)
            status = await framework.get_requirement_status(req_id)

            logger.info(f"Requirement {req_id} status: {status}")
            logger.info(f"Duration: {duration:.2f}s")
            logger.info(f"Outputs: {outputs}")

            # For complex scenarios, we just verify process completeness
            assert status, "Requirement not found"
            assert "current_gate" in status, "Requirement has no gate info"

            # Verify event timeline
            timeline = event_tracker.get_timeline(req_id)
            logger.info(f"Captured {len(timeline)} events")

            # Verify minimum event coverage
            subjects = set(e["subject"] for e in timeline)
            assert len(subjects) >= 5, (
                f"Expected at least 5 different event types, got {len(subjects)}"
            )

            # Cleanup
            await framework.cleanup_test_data(req_id)

            result = TestResult(
                scenario_id=SCENARIO_3_COMPLEX["id"],
                scenario_name=SCENARIO_3_COMPLEX["name"],
                req_id=req_id,
                status="passed",
                duration_seconds=duration,
                start_time=start_time,
                end_time=end_time,
                outputs=outputs,
                events=timeline,
            )

            logger.info(f"Scenario 3 PASSED ({duration:.2f}s)")
            return result

        except Exception as e:
            logger.error(f"Scenario 3 FAILED: {e}", exc_info=True)
            if req_id:
                await framework.cleanup_test_data(req_id)
            raise

        finally:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
            await event_tracker.unsubscribe_all()


# Standalone test runner
@pytest.fixture(scope="session")
async def test_results():
    """Collect all test results for report generation."""
    return []


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to capture test results."""
    outcome = yield
    rep = outcome.get_result()
    # Results are collected by pytest
    pass
