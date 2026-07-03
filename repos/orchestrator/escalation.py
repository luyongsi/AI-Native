"""
escalation.py - Escalation Manager

Handles escalation when a gate exceeds its SLA deadline.
Determines severity level and logs/publishes escalation events.

Usage:
    mgr = EscalationManager()
    result = await mgr.escalate(gate_record, reason="SLA deadline exceeded")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gate_state import GateRecord

logger = logging.getLogger(__name__)


class EscalationManager:
    """Handles escalation when gates go overdue.

    In production this would publish to a NATS event bus and insert
    escalation records into a dedicated table.  For now it logs and
    returns structured data so callers can act on the result.
    """

    async def escalate(self, gate_record: GateRecord, reason: str = "SLA deadline exceeded") -> dict:
        """Escalate an overdue gate.

        Args:
            gate_record: The gate that has become overdue.
            reason: Human-readable reason for escalation.

        Returns:
            A dict with escalation details.
        """
        hours_overdue = 0.0
        if gate_record.sla_deadline is not None:
            delta = datetime.now(timezone.utc) - gate_record.sla_deadline
            hours_overdue = delta.total_seconds() / 3600.0

        level = self.determine_level(gate_record.gate, hours_overdue)

        message = (
            f"Gate {gate_record.gate_id} (level {gate_record.gate}) is overdue "
            f"by {hours_overdue:.1f}h — escalation level: {level}"
        )

        logger.warning("ESCALATION [%s] gate=%s req=%s hours_overdue=%.1f reason=%s",
                       level.upper(), gate_record.gate_id, gate_record.req_id,
                       hours_overdue, reason)

        # TODO: Production would publish to NATS event bus here:
        #   await nats.publish("orchestrator.escalation", ...)
        # TODO: Production would insert into escalation_log table here.

        return {
            "escalated": True,
            "gate_id": gate_record.gate_id,
            "req_id": gate_record.req_id,
            "gate_level": gate_record.gate,
            "level": level,
            "hours_overdue": round(hours_overdue, 2),
            "message": message,
        }

    @staticmethod
    def determine_level(gate_level: int, hours_overdue: float) -> str:
        """Determine the escalation severity level.

        Rules:
            - Gate 0 overdue  -> "warning"
            - Gate 1-2 overdue -> "warning" if under 2 h, "critical" if over 2 h
            - Gate 3 overdue  -> "critical"
        """
        if gate_level == 0:
            return "warning"
        if gate_level in (1, 2):
            if hours_overdue > 2.0:
                return "critical"
            return "warning"
        # Gate 3
        return "critical"
