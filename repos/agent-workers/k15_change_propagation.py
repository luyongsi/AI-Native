"""
k15_change_propagation.py — K15 Change Propagation Agent Worker

Subscribes to spec.changed and api.changed events.
Implements a 30-second debounce window before publishing propagation.triggered
to notify downstream agents of changes.

Usage:
    python3 k15_change_propagation.py       # run standalone
    # Or register in worker_launcher.py     # run alongside the rest of the platform
"""

import asyncio
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Set

from event_bus import EventPublisher, EventSubscriber
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AGENT_ID = "K15"
AGENT_TYPE = "change_propagation"

DEBOUNCE_SECONDS = 30  # Debounce window before propagating


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class ChangePropagationAgent(BaseAgentWorker):
    """
    K15 Change Propagation Agent.

    Debounces spec.changed and api.changed events for 30 seconds,
    then publishes propagation.triggered with the aggregated change set.
    """

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(agent_id=AGENT_ID, agent_type=AGENT_TYPE, nats_url=nats_url)
        self._publisher: Optional[EventPublisher] = None
        # Per-req_id tracking: pending timer and collected change types
        self._pending: dict = {}  # req_id -> { "timer": asyncio.Task, "changes": set }
        self._lock = asyncio.Lock()

    async def init(self):
        await super().init()
        self._publisher = EventPublisher(self.nats_url)
        await self._publisher.connect()
        logger.info("[K15] Change Propagation Agent initialized")

    async def close(self):
        # Cancel any pending debounce timers
        async with self._lock:
            for entry in self._pending.values():
                if entry.get("timer"):
                    entry["timer"].cancel()
            self._pending.clear()
        if self._publisher:
            await self._publisher.disconnect()
        await super().close()

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """
        Handle a change event with debouncing.
        Called each time spec.changed or api.changed fires.
        """
        event_type = context_package.get("event_type", "unknown")
        logger.info("[K15] Received %s for req=%s", event_type, req_id)

        await self._debounced_handle(req_id, event_type)
        return {"status": "debouncing", "req_id": req_id, "event_type": event_type}

    async def _debounced_handle(self, req_id: str, event_type: str):
        """
        Implement the 30s debounce:
          - On first event for a req_id, start a 30s timer.
          - Subsequent events within the window extend/reset the timer.
          - When timer fires, publish propagation.triggered.
        """
        async with self._lock:
            entry = self._pending.get(req_id)
            if entry is None:
                # First event for this req_id — create entry and start timer
                changes: Set[str] = {event_type}
                timer = asyncio.create_task(self._fire_propagation(req_id))
                self._pending[req_id] = {"timer": timer, "changes": changes}
                logger.info("[K15] Debounce timer started for req=%s (%ds)", req_id, DEBOUNCE_SECONDS)
            else:
                # Add to existing change set
                entry["changes"].add(event_type)
                logger.info("[K15] Added %s to pending changes for req=%s (total: %d)",
                            event_type, req_id, len(entry["changes"]))

    async def _fire_propagation(self, req_id: str):
        """Wait for the debounce window, then fire propagation.triggered."""
        await asyncio.sleep(DEBOUNCE_SECONDS)

        async with self._lock:
            entry = self._pending.pop(req_id, None)

        if entry is None:
            return  # already consumed

        changes = entry["changes"]
        change_list = sorted(changes)

        logger.info("[K15] Debounce window expired for req=%s — propagating changes: %s", req_id, change_list)

        await self._publisher.propagation_triggered(
            req_id=req_id,
            agent_id=AGENT_ID,
            source_gate=None,
            affected_agents=list(change_list),
            change_types=change_list,
            debounce_seconds=DEBOUNCE_SECONDS,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self.report_status(req_id, "completed", f"Propagation triggered for: {change_list}")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

async def main():
    """Run Change Propagation Agent directly for development/testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    agent = ChangePropagationAgent()
    await agent.init()

    subscriber = EventSubscriber()

    @subscriber.on("spec.changed")
    async def on_spec_changed(event: dict):
        req_id = event.get("req_id", "unknown")
        logger.info("[K15] spec.changed for req=%s", req_id)
        await agent.execute(req_id, event)

    @subscriber.on("api.changed")
    async def on_api_changed(event: dict):
        req_id = event.get("req_id", "unknown")
        logger.info("[K15] api.changed for req=%s", req_id)
        await agent.execute(req_id, event)

    await subscriber.start()
    logger.info("[K15] Change Propagation Agent listening on spec.changed, api.changed — Ctrl+C to stop")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("[K15] Shutting down...")
    finally:
        await subscriber.stop()
        await agent.close()

if __name__ == "__main__":
    asyncio.run(main())
