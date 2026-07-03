"""await_gate_approval Activity — create Gate record then poll with SLA timeout.

DEPRECATED: replaced by create_gate_approval Activity + approve_gate Signal.
This file is kept as a compatibility shim for old workflows.
"""
import asyncio
import logging
from datetime import datetime, timezone

from temporalio import activity

logger = logging.getLogger(__name__)

GATE_SLA_SECONDS = 10


@activity.defn(name="await_gate_approval")
async def await_gate_approval(req_id, gate_name, sla_seconds=GATE_SLA_SECONDS):
    """Deprecated shim — delegates to create_gate_approval."""
    logger.warning("await_gate_approval is deprecated, use create_gate_approval")
    from activities.gate_await import create_gate_approval
    return await create_gate_approval(req_id, gate_name)
