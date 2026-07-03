"""
sla_tracker.py - SLA Tracker

Background asyncio task that periodically checks for overdue gates
by calling GateStateMachine.run_overdue_check().

Usage:
    tracker = SLATracker(check_interval=30)
    await tracker.start(gate_state_machine)
    # ... application runs ...
    stats = tracker.get_stats()
    await tracker.stop()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from gate_state import GateStateMachine

logger = logging.getLogger(__name__)


class SLATracker:
    """SLA timer that monitors gate deadlines via a background polling loop."""

    def __init__(self, check_interval: int = 30):
        self._check_interval = check_interval
        self._task: Optional[asyncio.Task] = None
        self._total_checked: int = 0
        self._overdue_marked: int = 0
        self._last_check: Optional[str] = None
        self._running: bool = False

    async def start(self, gate_state_machine: GateStateMachine) -> None:
        """Start the background SLA polling task.

        Args:
            gate_state_machine: Connected GateStateMachine instance used to
                query and mark overdue gates.
        """
        if self._running:
            logger.warning("SLATracker is already running")
            return

        self._running = True
        self._gsm = gate_state_machine
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("SLATracker started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        """Cancel the background polling task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info(
            "SLATracker stopped (checked=%d overdue=%d)",
            self._total_checked,
            self._overdue_marked,
        )

    def get_stats(self) -> dict:
        """Return current SLA tracking statistics."""
        return {
            "total_checked": self._total_checked,
            "overdue_marked": self._overdue_marked,
            "last_check": self._last_check,
        }

    async def _poll_loop(self) -> None:
        """Background loop: periodically run the overdue check."""
        while self._running:
            try:
                count = await self._gsm.run_overdue_check()
                self._total_checked += 1
                self._overdue_marked += count
                self._last_check = datetime.now(timezone.utc).isoformat()

                if count:
                    logger.warning(
                        "SLA check: %d overdue gate(s) marked (total overdue=%d)",
                        count,
                        self._overdue_marked,
                    )
                else:
                    logger.debug("SLA check: no overdue gates")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SLA check failed - will retry in %ds", self._check_interval)

            await asyncio.sleep(self._check_interval)
