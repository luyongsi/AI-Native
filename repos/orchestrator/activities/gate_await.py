"""create_gate_approval Activity — create Gate record in DB and return immediately.

Replaces the old gate_await which blocked and polled. Gate waiting is now
done in Workflow via approve_gate Signal + wait_condition.
"""
import logging
from datetime import datetime, timezone

from temporalio import activity

logger = logging.getLogger(__name__)


def _gate_level(gate_name: str | int) -> int:
    """Extract the numeric gate level from a gate name or int."""
    if isinstance(gate_name, int):
        return gate_name
    import re
    match = re.search(r"(\d)", str(gate_name))
    if match:
        return int(match.group(1))
    return 0


@activity.defn(name="create_gate_approval")
async def create_gate_approval(req_id: str, gate_level: str | int, sla_seconds: float = 14400.0) -> dict:
    """Create a gate_approvals record and return immediately.

    The Workflow then waits for approve_gate Signal instead of polling.

    Args:
        req_id: Requirement UUID.
        gate_level: Gate level number (0-3) or name string.
        sla_seconds: SLA timeout in seconds (informational, Workflow handles enforcement).

    Returns:
        dict with gate_id, created, gate_level.
    """
    gate_num = _gate_level(gate_level)
    sla_hours = sla_seconds / 3600.0

    activity.logger.info(
        "create_gate_approval req=%s gate=%d sla=%.1fh", req_id, gate_num, sla_hours,
    )

    try:
        from gate_state import GateStateMachine

        gsm = GateStateMachine()
        await gsm.connect()

        try:
            # SLA is informational only — Workflow handles the real wait
            gate_record = await gsm.create_gate(
                req_id=req_id,
                gate_level=gate_num,
                sla_hours=sla_hours,
            )
            activity.logger.info(
                "Gate created: %s req=%s level=%d",
                gate_record.gate_id, req_id, gate_num,
            )
            return {
                "gate_id": gate_record.gate_id,
                "gate_level": gate_num,
                "created": True,
                "note": f"Gate {gate_num} created, awaiting approval via Temporal Signal",
            }
        finally:
            await gsm.close()

    except Exception:
        activity.logger.exception(
            "Gate Engine unavailable — stub for req=%s gate=%d",
            req_id, gate_num,
        )

    # Fallback stub
    return {
        "gate_id": f"stub-gate-{req_id[:8]}-{gate_num}",
        "gate_level": gate_num,
        "created": True,
        "note": f"[stub] Gate {gate_num} created (Gate Engine unavailable)",
    }
