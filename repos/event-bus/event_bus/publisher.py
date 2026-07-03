"""
EventPublisher — typed async publisher for NATS JetStream.

Uses JetStream publish with Nats-Msg-Id header for idempotent delivery.
Every publish auto-generates event_id (uuid4) and timestamp (ISO 8601).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

import nats
from nats.js.client import JetStreamContext

logger = logging.getLogger(__name__)

STREAM_NAME = "AI_NATIVE_EVENTS"


class EventPublisher:
    """Async publisher that writes idempotent, typed events to JetStream."""

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._nats_url = nats_url
        self._nc: Optional[nats.NATS] = None
        self._js: Optional[JetStreamContext] = None
        self._validator: Optional[Any] = None  # lazily-initialized SchemaValidator

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> "EventPublisher":
        """Connect to NATS. Safe to call multiple times."""
        if self._nc is None:
            self._nc = await nats.connect(self._nats_url)
            logger.info("Publisher connected to NATS at %s", self._nats_url)
        if self._js is None:
            self._js = self._nc.jetstream()
        return self

    async def disconnect(self) -> None:
        """Drain and close."""
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None
            self._js = None
            logger.info("Publisher disconnected")

    # ------------------------------------------------------------------
    # Core publish
    # ------------------------------------------------------------------

    async def publish(
        self,
        event_type: str,
        payload: Any,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        validate: bool = True,
    ) -> str:
        """
        Publish a typed event to JetStream.

        Returns the generated ``event_id`` (uuid4).

        Uses ``Nats-Msg-Id`` header keyed on ``event_id`` so that duplicate
        publishes within the stream's duplicate window are ignored.

        When *validate* is True (the default), the flattened envelope is
        validated against any matching JSON schema before publishing.  If
        validation fails, a ``ValidationError`` is raised and the event is
        NOT published.
        """
        if self._js is None:
            await self.connect()

        event_id = str(uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "payload": payload,
        }
        if req_id is not None:
            envelope["req_id"] = req_id
        if agent_id is not None:
            envelope["agent_id"] = agent_id
        if context is not None:
            envelope["context"] = context

        # ---- schema validation ----
        if validate:
            self._ensure_validator()
            assert self._validator is not None
            try:
                # Flatten: merge payload fields into envelope at top level
                # so the object matches the schema's flat field layout.
                flat = {
                    k: v for k, v in envelope.items() if k != "payload"
                }
                if isinstance(payload, dict):
                    flat.update(payload)
                self._validator.validate(event_type, flat)
            except Exception:
                logger.exception(
                    "Schema validation failed for event_type=%r event_id=%s",
                    event_type,
                    event_id,
                )
                raise

        body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")

        ack = await self._js.publish(
            subject=event_type,
            payload=body,
            headers={"Nats-Msg-Id": event_id},
            stream=STREAM_NAME,
        )
        logger.debug(
            "Published %s seq=%s event_id=%s", event_type, ack.seq, event_id
        )
        return event_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_validator(self) -> None:
        """Create the ``SchemaValidator`` on first use (lazy init)."""
        if self._validator is None:
            from event_bus.schema_validator import SchemaValidator  # noqa: E402

            self._validator = SchemaValidator()

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def gate_approved(
        self,
        gate_level: int,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish gate.{level}.approved"""
        return await self.publish(
            f"gate.{gate_level}.approved",
            payload={"gate_level": gate_level, "action": "approved"},
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )

    async def gate_rejected(
        self,
        gate_level: int,
        reason: str,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish gate.{level}.rejected"""
        return await self.publish(
            f"gate.{gate_level}.rejected",
            payload={"gate_level": gate_level, "action": "rejected"},
            req_id=req_id,
            agent_id=agent_id,
            context={"reason": reason, **context},
        )

    async def gate_resubmitted(
        self,
        gate_level: int,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish gate.{level}.resubmitted"""
        return await self.publish(
            f"gate.{gate_level}.resubmitted",
            payload={"gate_level": gate_level, "action": "resubmitted"},
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )

    async def agent_status_changed(
        self,
        agent_id: str,
        new_status: str,
        previous_status: Optional[str] = None,
        message: Optional[str] = None,
        req_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish agent.status.changed"""
        ctx = {
            "previous_status": previous_status,
            "message": message,
            **context,
        }
        return await self.publish(
            "agent.status.changed",
            payload={"agent_id": agent_id, "status": new_status},
            req_id=req_id,
            agent_id=agent_id,
            context=ctx,
        )

    async def requirement_drafted(
        self,
        req_id: str,
        **context: Any,
    ) -> str:
        """Publish requirement.drafted"""
        return await self.publish(
            "requirement.drafted",
            payload={"req_id": req_id},
            req_id=req_id,
            context=context,
        )

    async def artifact_produced(
        self,
        artifact_id: str,
        artifact_type: str,
        location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish artifact.produced"""
        return await self.publish(
            "artifact.produced",
            payload={
                "artifact": {
                    "id": artifact_id,
                    "type": artifact_type,
                    "location": location,
                    "metadata": metadata,
                }
            },
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )

    async def test_completed(
        self,
        test_name: str,
        passed: bool,
        duration_ms: Optional[float] = None,
        details: Optional[str] = None,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish test.completed or test.failed based on *passed*."""
        event_type = "test.completed" if passed else "test.failed"
        return await self.publish(
            event_type,
            payload={
                "test_result": {
                    "test_name": test_name,
                    "passed": passed,
                    "duration_ms": duration_ms,
                    "details": details,
                }
            },
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )

    async def test_failed(
        self,
        test_name: str,
        duration_ms: Optional[float] = None,
        details: Optional[str] = None,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish test.failed (convenience alias)."""
        return await self.test_completed(
            test_name=test_name,
            passed=False,
            duration_ms=duration_ms,
            details=details,
            req_id=req_id,
            agent_id=agent_id,
            **context,
        )

    async def loop_tripped(
        self,
        loop_id: str,
        trigger: Optional[str] = None,
        iteration: Optional[int] = None,
        reason: Optional[str] = None,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish loop.tripped"""
        return await self.publish(
            "loop.tripped",
            payload={"loop_id": loop_id, "trigger": trigger},
            req_id=req_id,
            agent_id=agent_id,
            context={"iteration": iteration, "reason": reason, **context},
        )

    async def code_pushed(
        self,
        source: Optional[str] = None,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish code.pushed"""
        return await self.publish(
            "code.pushed",
            payload={"source": source},
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )

    async def pipeline_passed(
        self,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish pipeline.passed"""
        return await self.publish(
            "pipeline.passed",
            payload={},
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )

    async def pipeline_failed(
        self,
        reason: Optional[str] = None,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish pipeline.failed"""
        return await self.publish(
            "pipeline.failed",
            payload={},
            req_id=req_id,
            agent_id=agent_id,
            context={"reason": reason, **context},
        )

    async def context_ready(
        self,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish context.ready"""
        return await self.publish(
            "context.ready",
            payload={},
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )

    async def propagation_triggered(
        self,
        source_gate: Optional[int] = None,
        affected_agents: Optional[list] = None,
        req_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        **context: Any,
    ) -> str:
        """Publish propagation.triggered"""
        return await self.publish(
            "propagation.triggered",
            payload={"source_gate": source_gate, "affected_agents": affected_agents},
            req_id=req_id,
            agent_id=agent_id,
            context=context,
        )
