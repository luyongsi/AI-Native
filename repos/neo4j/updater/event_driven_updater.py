"""Event-driven Neo4j knowledge graph updater.

Subscribes to NATS subjects and reacts to platform events by creating,
updating, or linking nodes and relationships in the Neo4j graph.

Stub implementation that logs every inbound event and maintains an
in-memory state dict for smoke-test validation.  A production
deployment would:

1. Connect to NATS with JetStream for at-least-once delivery.
2. Use ``neo4j.async_.driver`` session-per-event or batched writes.
3. Deduplicate via event ID / timestamp to avoid double-upsert.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class EventDrivenUpdater:
    """Listens for platform events and updates the Neo4j knowledge graph.

    Connects to NATS and the async Neo4j driver.  When either is ``None``
    the updater runs in stub / dry-run mode — useful for integration tests.

    Typical usage::

        updater = EventDrivenUpdater(driver=neo4j_driver)
        await updater.start("nats://localhost:4222")
        # ... platform runs ...
        await updater.stop()
    """

    # NATS subjects the updater subscribes to.
    SUBJECTS: tuple[str, ...] = (
        "artifact.produced",
        "requirement.drafted",
        "requirement.approved",
        "gate.passed",
        "gate.failed",
        "test.completed",
    )

    def __init__(
        self,
        driver=None,
    ) -> None:
        """Initialise the updater with an optional async Neo4j driver.

        Args:
            driver: An instance of ``neo4j.async_.driver`` or ``None``
                for stub mode.
        """
        self._driver = driver
        self._nats_connection: Any = None
        self._subscriptions: list = []
        self._running = False

        # In-memory state for stub-mode validation.
        self._state: Dict[str, list[dict]] = {
            subject: [] for subject in self.SUBJECTS
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, nats_url: str) -> None:
        """Subscribe to NATS subjects and begin processing events.

        In stub mode (no real NATS connection) this records that the
        updater is running so that ``handle_*`` methods can be tested
        directly.

        Args:
            nats_url: NATS server URL, e.g. ``"nats://localhost:4222"``.
        """
        logger.info("EventDrivenUpdater.start(nats_url=%r)", nats_url)
        self._running = True

        # Production path:
        #   import nats
        #   self._nats_connection = await nats.connect(nats_url)
        #   for subject in self.SUBJECTS:
        #       sub = await self._nats_connection.subscribe(subject, cb=self._dispatch)
        #       self._subscriptions.append(sub)
        #
        # Stub: log the intent
        for subject in self.SUBJECTS:
            logger.info("  subscribed to %s (stub)", subject)

    async def stop(self) -> None:
        """Gracefully unsubscribe and close the NATS / Neo4j connections."""
        logger.info("EventDrivenUpdater.stop() — draining subscriptions")
        self._running = False

        # Production path:
        #   for sub in self._subscriptions:
        #       await sub.unsubscribe()
        #   self._subscriptions.clear()
        #   if self._nats_connection:
        #       await self._nats_connection.close()
        #       self._nats_connection = None
        #   if self._driver:
        #       await self._driver.close()

        logger.info(
            "EventDrivenUpdater stopped. Events buffered: %s",
            {k: len(v) for k, v in self._state.items()},
        )

    # ------------------------------------------------------------------
    # Event dispatcher
    # ------------------------------------------------------------------

    async def _dispatch(self, msg) -> None:
        """Route an inbound NATS message to the correct handler.

        Production: called by the NATS client as a callback.
        Stub mode: call directly with a mock message.
        """
        subject = msg.subject if hasattr(msg, "subject") else msg.get("subject", "")
        data = msg.data if hasattr(msg, "data") else msg.get("data", {})
        logger.debug("_dispatch(subject=%r)", subject)

        handler_map = {
            "artifact.produced": self.handle_artifact_produced,
            "requirement.drafted": self.handle_requirement_created,
            "gate.passed": self.handle_gate_event,
            "gate.failed": self.handle_gate_event,
            "test.completed": self.handle_test_completed,
        }
        handler = handler_map.get(subject)
        if handler:
            await handler(data)
        else:
            logger.warning("No handler for subject %r", subject)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def handle_artifact_produced(self, event: dict) -> None:
        """Handle ``artifact.produced`` events.

        Updates the Neo4j graph:
        1. MERGE the producing :Agent node.
        2. MERGE the :Artifact node (Spec / Task / TestCase).
        3. CREATE the ``:GENERATES`` relationship.

        Args:
            event: Expected keys — ``agent_id``, ``agent_name``,
                ``agent_type``, ``artifact_id``, ``artifact_type``,
                ``artifact_title``, ``timestamp``.
        """
        agent_id = event.get("agent_id", "unknown")
        artifact_id = event.get("artifact_id", "unknown")
        artifact_type = event.get("artifact_type", "Artifact")
        logger.info(
            "handle_artifact_produced: agent=%s artifact=%s type=%s",
            agent_id, artifact_id, artifact_type,
        )
        self._state["artifact.produced"].append(event)

        # Production Cypher:
        #   MERGE (a:Agent {id: $agent_id})
        #     ON CREATE SET a.name=$agent_name, a.type=$agent_type
        #   CREATE (art:Artifact {id: $artifact_id, type: $artifact_type, title: $artifact_title})
        #   CREATE (a)-[:GENERATES {timestamp: $timestamp}]->(art)
        #
        # Stub: event is already buffered in self._state.

    async def handle_requirement_created(self, event: dict) -> None:
        """Handle ``requirement.drafted`` events.

        Creates/updates a :Requirement node in the knowledge graph.

        Args:
            event: Expected keys — ``id``, ``title``, ``status``,
                ``priority``, ``version``.
        """
        req_id = event.get("id", "unknown")
        logger.info("handle_requirement_created: id=%s title=%r", req_id, event.get("title"))
        self._state["requirement.drafted"].append(event)

        # Production Cypher:
        #   MERGE (r:Requirement {id: $id})
        #     SET r.title=$title, r.status=$status, r.priority=$priority, r.version=$version

    async def handle_gate_event(self, event: dict) -> None:
        """Handle ``gate.passed`` and ``gate.failed`` events.

        Creates/updates a :GateApproval node and the ``:GATED_BY``
        relationship from the associated :Requirement.

        Args:
            event: Expected keys — ``gate_approval_id``, ``gate_level``,
                ``status`` (passed/failed), ``requirement_id``,
                ``reviewer_agent_id``, ``timestamp``.
        """
        approval_id = event.get("gate_approval_id", "unknown")
        status = event.get("status", "unknown")
        logger.info("handle_gate_event: approval=%s status=%s", approval_id, status)

        subject = f"gate.{status}"
        if subject in self._state:
            self._state[subject].append(event)

        # Production Cypher:
        #   MERGE (g:GateApproval {id: $gate_approval_id})
        #     SET g.gate_level=$gate_level, g.status=$status
        #   WITH g
        #   MATCH (r:Requirement {id: $requirement_id})
        #   MERGE (r)-[:GATED_BY]->(g)
        #   WITH g
        #   MATCH (a:Agent {id: $reviewer_agent_id})
        #   MERGE (a)-[:REVIEWS {timestamp: $timestamp, verdict: $status}]->(g)

    async def handle_test_completed(self, event: dict) -> None:
        """Handle ``test.completed`` events.

        Links the test result to its parent requirement and updates the
        :TestCase node status.

        Args:
            event: Expected keys — ``test_case_id``, ``status``,
                ``requirement_id``, ``task_id``, ``timestamp``.
        """
        test_id = event.get("test_case_id", "unknown")
        status = event.get("status", "unknown")
        logger.info("handle_test_completed: test=%s status=%s", test_id, status)
        self._state["test.completed"].append(event)

        # Production Cypher:
        #   MERGE (tc:TestCase {id: $test_case_id})
        #     SET tc.status=$status, tc.last_run=$timestamp
        #   WITH tc
        #   MATCH (t:Task {id: $task_id})
        #   MERGE (t)-[:TESTED_BY]->(tc)
        #   WITH tc
        #   MATCH (r:Requirement {id: $requirement_id})
        #   MERGE (tc)-[:VALIDATES]->(r)

    # ------------------------------------------------------------------
    # Inspection (for tests / stub validation)
    # ------------------------------------------------------------------

    def event_count(self, subject: str) -> int:
        """Return the number of events received for *subject*.

        Useful for asserting in tests that the updater saw the expected
        number of events.

        Args:
            subject: NATS subject, e.g. ``"artifact.produced"``.

        Returns:
            Number of buffered events.
        """
        return len(self._state.get(subject, []))

    def all_events(self) -> Dict[str, int]:
        """Return a summary of all received event counts."""
        return {k: len(v) for k, v in self._state.items()}

    def clear_state(self) -> None:
        """Reset in-memory event buffers (for test isolation)."""
        for key in self._state:
            self._state[key] = []
