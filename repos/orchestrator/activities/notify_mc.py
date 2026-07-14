"""notify_mc Activity — publish state change to NATS + sync to MC Backend."""

import json
import logging
import os
from datetime import datetime, timezone

import nats
from temporalio import activity

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")
MC_BACKEND_URL = os.environ.get("MC_BACKEND_URL", "http://localhost:8000")

_nc: nats.NATS | None = None


async def _get_nats() -> nats.NATS:
    global _nc
    if _nc is None or not _nc.is_connected:
        _nc = await nats.connect(NATS_URL)
        logger.info("notify_mc: connected to NATS at %s", NATS_URL)
    return _nc


async def _sync_to_mc_backend(req_id: str, new_state: str, old_state: str, extra: dict) -> bool:
    """Best-effort HTTP PUT to MC Backend. Returns True if synced, False on failure."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(
                f"{MC_BACKEND_URL}/api/requirements/{req_id}/status",
                json={
                    "status": new_state,
                    "old_state": old_state,
                    "new_state": new_state,
                    "event": extra,
                    "agent_id": "orchestrator",
                },
            )
            resp.raise_for_status()
            return True
    except Exception:
        logger.warning("notify_mc: MC Backend sync failed for req=%s (non-fatal)", req_id)
        return False


@activity.defn(name="notify_mc")
async def notify_mc(
    req_id: str,
    old_state: str,
    new_state: str,
    extra: dict | None = None,
) -> dict:
    """Publish a state-change notification to NATS and sync to MC Backend.

    Subject: `orchestrator.state.<req_id>`
    Also publishes to `agent.status.changed` for MC live view.
    HTTP PUT to MC Backend is best-effort — failure does not block.
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
        "mc_synced": False,
        "note": "",
    }

    try:
        nc = await _get_nats()
        js = nc.jetstream()
        subject = f"orchestrator.state.{req_id}"
        await js.publish(subject, json.dumps(envelope, ensure_ascii=False).encode(),
                         headers={"Nats-Msg-Id": envelope["event_id"]})
        # Also publish to agent.status.changed for MC live view
        status_envelope = {
            "agent_id": "orchestrator",
            "req_id": req_id,
            "status": new_state,
            "message": f"State: {old_state} -> {new_state}",
            "timestamp": now_ts,
        }
        await js.publish("agent.status.changed", json.dumps(status_envelope, ensure_ascii=False).encode(),
                         headers={"Nats-Msg-Id": f"state-change-{req_id}-{new_state}"})
        result["note"] = f"Published to NATS subject '{subject}'"
        activity.logger.info("notify_mc: published %s -> %s for req=%s", old_state, new_state, req_id)
    except Exception as e:
        result["ok"] = False
        result["note"] = f"NATS publish failed: {e}"
        activity.logger.error("notify_mc: NATS publish failed: %s", e)

    # Best-effort sync to MC Backend
    result["mc_synced"] = await _sync_to_mc_backend(req_id, new_state, old_state, extra)

    return result
