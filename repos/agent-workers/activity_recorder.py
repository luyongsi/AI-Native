"""
activity_recorder.py — Activity event recorder for agent execution tracking.

Publishes progress, status, and artifact events via NATS JetStream.
Integrates with BaseAgentWorker to track real-time agent activity.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Any
from enum import Enum

import nats
from nats.js.client import JetStreamContext

logger = logging.getLogger(__name__)


class ActivityEventType(str, Enum):
    """Activity event types for streaming."""
    PROGRESS = "agent.progress"
    STATUS = "agent.status"
    ARTIFACT = "agent.artifact"


class ActivityRecorder:
    """Publishes agent activity events to NATS for real-time streaming."""

    def __init__(self, nc: nats.NATS, js: JetStreamContext, agent_id: str):
        """
        Initialize activity recorder.

        Args:
            nc: NATS connection
            js: JetStream context
            agent_id: Identifier for the agent publishing events
        """
        self.nc = nc
        self.js = js
        self.agent_id = agent_id

    async def record_progress(
        self,
        req_id: str,
        step: str,
        details: Optional[str] = None,
        progress_percent: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Record a progress update for an agent activity.

        Args:
            req_id: Request ID for tracking
            step: Current step/stage name
            details: Human-readable progress description
            progress_percent: Optional progress percentage (0-100)
            metadata: Optional additional metadata

        Returns:
            Event ID
        """
        event_data = {
            "agent_id": self.agent_id,
            "req_id": req_id,
            "event_type": ActivityEventType.PROGRESS.value,
            "step": step,
            "details": details or "",
            "progress_percent": progress_percent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            event_data["metadata"] = metadata

        subject = f"agent.{self.agent_id}.progress"
        body = json.dumps(event_data, ensure_ascii=False).encode("utf-8")

        ack = await self.js.publish(subject, body,
                                     headers={"Nats-Msg-Id": f"progress-{self.agent_id}-{req_id}-{step}"})
        logger.debug(
            f"[{self.agent_id}] Progress recorded: req={req_id}, step={step}, seq={ack.seq}"
        )
        return str(ack.seq)

    async def record_status(
        self,
        req_id: str,
        status: str,
        message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Record a status change for an agent activity.

        Args:
            req_id: Request ID for tracking
            status: Status value (e.g., "pending", "running", "completed", "failed")
            message: Optional status message
            metadata: Optional additional metadata

        Returns:
            Event ID
        """
        event_data = {
            "agent_id": self.agent_id,
            "req_id": req_id,
            "event_type": ActivityEventType.STATUS.value,
            "status": status,
            "message": message or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            event_data["metadata"] = metadata

        subject = f"agent.{self.agent_id}.status"
        body = json.dumps(event_data, ensure_ascii=False).encode("utf-8")

        ack = await self.js.publish(subject, body,
                                     headers={"Nats-Msg-Id": f"status-{self.agent_id}-{req_id}-{status}"})
        logger.debug(
            f"[{self.agent_id}] Status recorded: req={req_id}, status={status}, seq={ack.seq}"
        )
        return str(ack.seq)

    async def record_artifact(
        self,
        req_id: str,
        artifact_type: str,
        artifact_data: dict,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Record an artifact produced by the agent.

        Args:
            req_id: Request ID for tracking
            artifact_type: Type of artifact (e.g., "requirement_draft", "code_diff")
            artifact_data: Artifact content/data
            metadata: Optional additional metadata

        Returns:
            Event ID
        """
        event_data = {
            "agent_id": self.agent_id,
            "req_id": req_id,
            "event_type": ActivityEventType.ARTIFACT.value,
            "artifact_type": artifact_type,
            "artifact": artifact_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            event_data["metadata"] = metadata

        subject = f"agent.{self.agent_id}.artifact"
        body = json.dumps(event_data, ensure_ascii=False).encode("utf-8")

        ack = await self.js.publish(subject, body,
                                     headers={"Nats-Msg-Id": f"artifact-{self.agent_id}-{req_id}-{artifact_type}"})
        logger.debug(
            f"[{self.agent_id}] Artifact recorded: req={req_id}, type={artifact_type}, seq={ack.seq}"
        )
        return str(ack.seq)
