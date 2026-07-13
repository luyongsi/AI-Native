"""
E2E Test Framework for Phase 6 - End-to-end integration testing.

Provides a complete framework for testing the entire system flow from
Feishu input through GitHub PR generation.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

import nats
import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result of a single test scenario."""
    scenario_id: str
    scenario_name: str
    req_id: str
    status: str  # 'passed', 'failed', 'timeout'
    duration_seconds: float
    start_time: datetime
    end_time: datetime
    outputs: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


class E2ETestFramework:
    """
    End-to-end test framework for the entire requirement pipeline.

    Manages:
    - NATS event bus connections
    - PostgreSQL database connections
    - Redis cache connections (optional)
    - Event tracking and verification
    - Requirement submission and status polling
    """

    def __init__(
        self,
        nats_url: str = "nats://localhost:4222",
        db_url: str = "postgresql://localhost:5432/ai_native",
        redis_url: Optional[str] = None,
        timeout: int = 3600,
    ):
        self.nats_url = nats_url
        self.db_url = db_url
        self.redis_url = redis_url
        self.timeout = timeout

        self.nats_client: Optional[nats.NATS] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.event_subscriptions: Dict[str, asyncio.Task] = {}
        self.captured_events: List[Dict[str, Any]] = []
        self._running = False

    async def setup(self) -> None:
        """Initialize all connections."""
        logger.info("Setting up E2E test framework...")

        try:
            self.nats_client = await nats.connect(self.nats_url)
            logger.info(f"Connected to NATS at {self.nats_url}")
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise

        try:
            self.db_pool = await asyncpg.create_pool(
                self.db_url,
                min_size=5,
                max_size=20,
            )
            logger.info(f"Connected to database at {self.db_url}")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

        self._running = True
        logger.info("E2E test framework setup complete")

    async def teardown(self) -> None:
        """Clean up all connections."""
        logger.info("Tearing down E2E test framework...")
        self._running = False

        for task in self.event_subscriptions.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self.db_pool:
            await self.db_pool.close()
            logger.info("Database pool closed")

        if self.nats_client:
            await self.nats_client.drain()
            logger.info("NATS connection closed")

    async def submit_requirement(
        self,
        title: str,
        description: str,
        priority: str = "P2",
        source_type: str = "feishu",
    ) -> str:
        """
        Submit a requirement to the system (simulating Feishu input).

        Returns the requirement ID.
        """
        if not self.db_pool:
            raise RuntimeError("Framework not initialized")

        req_id = str(uuid.uuid4())
        external_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO requirements
                (id, external_id, title, status, priority, source_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                """,
                req_id,
                external_id,
                title,
                "draft",
                priority,
                source_type,
            )

        logger.info(f"Submitted requirement {req_id} ({external_id})")

        # Publish event to trigger pipeline
        if self.nats_client:
            try:
                js = self.nats_client.jetstream()
                await js.publish(
                    "requirement.intake",
                    json.dumps({
                        "req_id": req_id,
                        "external_id": external_id,
                        "title": title,
                        "description": description,
                        "priority": priority,
                        "source_type": source_type,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }).encode(),
                )
            except Exception as e:
                logger.warning(f"Failed to publish requirement.intake event: {e}")

        return req_id

    async def wait_for_completion(
        self,
        req_id: str,
        target_gate: int = 7,
        timeout: Optional[int] = None,
    ) -> bool:
        """
        Wait for requirement to reach target gate (default: Gate 7 = complete).

        Returns True if completed, False if timeout.
        """
        if not self.db_pool:
            raise RuntimeError("Framework not initialized")

        timeout = timeout or self.timeout
        start_time = datetime.now(timezone.utc)

        while True:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT status, current_gate FROM requirements WHERE id = $1",
                    req_id,
                )

            if not row:
                logger.error(f"Requirement {req_id} not found")
                return False

            status = row["status"]
            current_gate = row["current_gate"]

            logger.debug(f"Requirement {req_id}: status={status}, gate={current_gate}")

            if current_gate and current_gate >= target_gate:
                logger.info(f"Requirement {req_id} reached target gate {target_gate}")
                return True

            if status == "blocked":
                logger.error(f"Requirement {req_id} is blocked")
                return False

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if elapsed > timeout:
                logger.error(f"Requirement {req_id} timed out after {elapsed}s")
                return False

            await asyncio.sleep(5)  # Poll every 5 seconds

    async def subscribe_events(self, req_id: str) -> None:
        """
        Subscribe to all events for a specific requirement.

        Events are captured in self.captured_events.
        """
        if not self.nats_client:
            raise RuntimeError("Framework not initialized")

        subjects = [
            "requirement.intake",
            "knowledge.analyzed",
            "spec.api_schema_ready",
            "spec.erd_ready",
            "architecture.dag_built",
            "code.generated",
            "test.executed",
            "test.passed",
            "test.failed",
            "gate.approved",
            "gate.rejected",
            "pr.created",
            "requirement.completed",
            "requirement.failed",
        ]

        async def event_handler(msg):
            try:
                data = json.loads(msg.data.decode())
                if data.get("req_id") == req_id:
                    self.captured_events.append({
                        "subject": msg.subject,
                        "data": data,
                        "timestamp": datetime.now(timezone.utc),
                    })
                    logger.debug(f"Captured event: {msg.subject}")
            except Exception as e:
                logger.warning(f"Failed to process event: {e}")

        for subject in subjects:
            try:
                sub = await self.nats_client.subscribe(subject)
                self.event_subscriptions[subject] = asyncio.create_task(
                    self._consume_events(sub, event_handler)
                )
            except Exception as e:
                logger.warning(f"Failed to subscribe to {subject}: {e}")

    async def _consume_events(self, sub, handler):
        """Consume events from subscription."""
        try:
            async for msg in sub.messages:
                await handler(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error consuming events: {e}")

    async def verify_outputs(self, req_id: str) -> Dict[str, Any]:
        """
        Verify all outputs have been generated for a requirement.

        Returns a dict with verification results:
        - api_schema: bool
        - erd: bool
        - dag: bool
        - code: dict with files_changed count
        - tests: dict with pass_rate and metrics
        """
        if not self.db_pool:
            raise RuntimeError("Framework not initialized")

        results = {
            "api_schema": False,
            "erd": False,
            "dag": False,
            "code": {"files_changed": 0},
            "tests": {"pass_rate": 0.0, "passed": 0, "failed": 0},
        }

        try:
            async with self.db_pool.acquire() as conn:
                # Check requirement spec
                req = await conn.fetchrow(
                    "SELECT spec FROM requirements WHERE id = $1",
                    req_id,
                )

                if req and req["spec"]:
                    spec = req["spec"]
                    results["api_schema"] = bool(spec.get("api_schema"))
                    results["erd"] = bool(spec.get("erd"))
                    results["dag"] = bool(spec.get("dag"))

                # Check test results
                test_result = await conn.fetchrow(
                    """
                    SELECT passed, failed, coverage FROM test_executions
                    WHERE req_id = $1
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    req_id,
                )

                if test_result:
                    passed = test_result["passed"] or 0
                    failed = test_result["failed"] or 0
                    total = passed + failed

                    results["tests"]["passed"] = passed
                    results["tests"]["failed"] = failed
                    results["tests"]["pass_rate"] = (
                        passed / total if total > 0 else 0
                    )

        except Exception as e:
            logger.error(f"Error verifying outputs: {e}")

        return results

    async def get_duration(self, req_id: str) -> float:
        """Get the total duration from requirement creation to completion."""
        if not self.db_pool:
            raise RuntimeError("Framework not initialized")

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT created_at, updated_at FROM requirements WHERE id = $1
                """,
                req_id,
            )

        if not row:
            return 0.0

        duration = (row["updated_at"] - row["created_at"]).total_seconds()
        return duration

    async def get_requirement_status(self, req_id: str) -> Dict[str, Any]:
        """Get current status of a requirement."""
        if not self.db_pool:
            raise RuntimeError("Framework not initialized")

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id, external_id, title, status, current_gate, priority,
                    ai_completion, human_interventions, blocked, created_at, updated_at
                FROM requirements WHERE id = $1
                """,
                req_id,
            )

        if not row:
            return {}

        return dict(row)

    def get_timeline(self, req_id: str) -> List[Dict[str, Any]]:
        """Get event timeline for a requirement."""
        return [
            e for e in self.captured_events
            if e["data"].get("req_id") == req_id
        ]

    async def cleanup_test_data(self, req_id: str) -> None:
        """Clean up test data after test completion."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                # Delete related records
                await conn.execute(
                    "DELETE FROM test_executions WHERE req_id = $1",
                    req_id,
                )
                await conn.execute(
                    "DELETE FROM gate_approvals WHERE req_id = $1",
                    req_id,
                )
                await conn.execute(
                    "DELETE FROM agent_activities WHERE req_id = $1",
                    req_id,
                )
                await conn.execute(
                    "DELETE FROM requirements WHERE id = $1",
                    req_id,
                )

            logger.info(f"Cleaned up test data for requirement {req_id}")
        except Exception as e:
            logger.warning(f"Error cleaning up test data: {e}")
