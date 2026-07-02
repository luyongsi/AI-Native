"""
VisAgent Event Handler — Processes NATS events from the VisAgent ecosystem.

Listens for test.completed, agent.status.changed events and updates
internal state for downstream consumers.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class VisAgentEventHandler:
    """Handles NATS events emitted by the VisAgent service and bridge."""

    def __init__(self):
        self._state: dict[str, Any] = {
            "last_test_completed": None,
            "agent_statuses": {},
            "total_tests_completed": 0,
            "total_tests_passed": 0,
            "total_tests_failed": 0,
        }

    async def handle_test_completed(self, event: dict) -> None:
        """
        Process a NATS `test.completed` event.

        Args:
            event: Event dict with: event_type, timestamp, payload
                   payload contains: test_case_id, passed, duration_ms, issues[], screenshots[]
        """
        event_type = event.get("event_type", "test.completed")
        timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())
        payload = event.get("payload", {})

        test_case_id = payload.get("test_case_id", "unknown")
        passed = payload.get("passed", False)

        logger.info(
            f"VisAgentEventHandler: test.completed — "
            f"test_case={test_case_id} passed={passed}"
        )

        self._state["last_test_completed"] = {
            "test_case_id": test_case_id,
            "passed": passed,
            "timestamp": timestamp,
        }
        self._state["total_tests_completed"] += 1

        if passed:
            self._state["total_tests_passed"] += 1
        else:
            self._state["total_tests_failed"] += 1
            issues = payload.get("issues", [])
            if issues:
                logger.warning(f"VisAgentEventHandler: {len(issues)} issues in {test_case_id}")

    async def handle_agent_status(self, event: dict) -> None:
        """
        Process a NATS `agent.status.changed` event.

        Args:
            event: Event dict with: event_type, timestamp, payload
                   payload contains: agent_id, old_status, new_status, metadata
        """
        payload = event.get("payload", {})
        agent_id = payload.get("agent_id", "unknown")
        old_status = payload.get("old_status", "unknown")
        new_status = payload.get("new_status", "unknown")

        logger.info(
            f"VisAgentEventHandler: agent.status.changed — "
            f"agent={agent_id} {old_status} -> {new_status}"
        )

        self._state["agent_statuses"][agent_id] = {
            "status": new_status,
            "previous_status": old_status,
            "last_updated": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }

    @property
    def state(self) -> dict:
        """Return a copy of the current internal state."""
        return dict(self._state)

    def get_agent_status(self, agent_id: str) -> str | None:
        """Get the last known status for a specific agent."""
        entry = self._state["agent_statuses"].get(agent_id)
        return entry["status"] if entry else None

    def reset(self) -> None:
        """Reset all internal state."""
        logger.info("VisAgentEventHandler: resetting state")
        self._state = {
            "last_test_completed": None,
            "agent_statuses": {},
            "total_tests_completed": 0,
            "total_tests_passed": 0,
            "total_tests_failed": 0,
        }
