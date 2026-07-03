"""notify_mc Activity — publish state change to NATS Event Bus."""

import json
import logging
import os
from datetime import datetime, timezone

import nats
from temporalio import activity

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")

_nc: nats.NATS | None = None


async def _get_nats() -> nats.NATS:
    global _nc
    if _nc is None or not _nc.is_connected:
        _nc = await nats.connect(NATS_URL)
        logger.info("notify_mc: connected to NATS at %s", NATS_URL)
    return _nc


@activity.defn(name="notify_mc")
async def notify_mc(
    req_id: str,
    old_state: str,
    new_state: str,
    extra: dict | None = None,
) -> dict:
    """Publish a state-change notification to NATS.

    Subject: `orchestrator.state.<req_id>`
    Also publishes to `agent.status.changed` for MC live view.
    """
    extra = extra or {}
    now = datetime.now(timezone.utc)
    now_ts = now.isoformat()

    envelope = {
        "event_id": f"state-change-{req_id}-{old_state}-{new_state}",
        "event_type": "orchestrator.state.changed",
        "timestamp": now_ts,
        "payload": {
            "req_id": req_id,
            "old_state": old_state,
            "new_state": new_state,
            "extra": extra,
        },
        "req_id": req_id,
    }

    result = {
        "ok": True,
        "req_id": req_id,
        "old_state": old_state,
        "new_state": new_state,
        "published_at": now_ts,
        "note": "",
    }

    try:
        nc = await _get_nats()
        subject = f"orchestrator.state.{req_id}"
        await nc.publish(subject, json.dumps(envelope, ensure_ascii=False).encode())
        # Also publish to agent.status.changed for MC live view
        status_envelope = {
            "agent_id": "orchestrator",
            "req_id": req_id,
            "status": new_state,
            "message": f"State: {old_state} -> {new_state}",
            "timestamp": now_ts,
        }
        await nc.publish("agent.status.changed", json.dumps(status_envelope, ensure_ascii=False).encode())
        result["note"] = f"Published to NATS subject '{subject}'"
        activity.logger.info("notify_mc: published %s -> %s for req=%s", old_state, new_state, req_id)
    except Exception as e:
        result["ok"] = False
        result["note"] = f"NATS publish failed: {e}"
        activity.logger.error("notify_mc: NATS publish failed: %s", e)

    return result
