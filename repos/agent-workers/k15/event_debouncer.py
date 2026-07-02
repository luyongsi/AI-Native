"""
k15/event_debouncer.py — K15 sub-module: Event Debouncing

Groups incoming events of the same type within a configurable time window,
then releases them as a batch for downstream processing.  Used by K15 to
avoid firing propagation.triggered for every single spec.changed event.

Phase 2 uses an in-memory dict-based queue.
Phase 3 would persist queues in Redis for durability across restarts.

Usage:
    debouncer = EventDebouncer()
    result = await debouncer.debounce("spec.changed", event_data, window_seconds=30)
    flushed = await debouncer.flush("spec.changed")
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_WINDOW_SECONDS = 30.0


class EventDebouncer:
    """Groups events within a time window and emits them as batches.

    Internal queue structure::

        {
            "spec.changed": {
                "batch-uuid-1": {
                    "events":   [ {...}, {...} ],
                    "first_at": datetime,
                    "last_at":  datetime,
                },
            },
        }

    Phase 3: Replace the dict with Redis hashes + sorted sets for persistence.

    Attributes:
        _queue:   In-memory event queue keyed by event_type then batch_id.
        _lock:    Async lock guarding queue mutations.
        _timers:  Per-event-type debounce timers (asyncio.Task).
    """

    def __init__(self) -> None:
        # Queue shape: {event_type: {batch_id: {"events": [...], "first_at": dt, "last_at": dt}}}
        self._queue: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._timers: Dict[str, asyncio.Task] = {}
        self._flushed_count: int = 0
        logger.info("EventDebouncer initialized (Phase 2 in-memory mode)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def debounce(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> Dict[str, Any]:
        """Add an event to the debounce queue for *event_type*.

        If this is the first event of its type within the current window,
        a timer is started.  Subsequent events land in the same batch until
        the timer fires (at which point the batch is "ready" for processing).
        The caller is responsible for actually processing the batch — this
        method only manages queue state.

        Args:
            event_type:     The event subject (e.g. "spec.changed").
            event_data:     The event payload dict.
            window_seconds: Debounce window in seconds (default 30.0).

        Returns:
            Dict with keys:
                should_process (bool):  Whether this event triggered batch
                                        completion (True when timer fires).
                batch_id (str):         UUID of the batch this event belongs to.
                queued_count (int):     Number of events currently in the batch.
                first_event_at (str):   ISO timestamp of first event in batch.
                last_event_at (str):    ISO timestamp of this event.
        """
        if not event_type:
            logger.warning("debounce called with empty event_type")
            return {
                "should_process": False,
                "batch_id": "",
                "queued_count": 0,
                "first_event_at": "",
                "last_event_at": "",
            }

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        async with self._lock:
            # Ensure event_type bucket exists
            if event_type not in self._queue:
                self._queue[event_type] = {}

            bucket = self._queue[event_type]

            # Find or create the active batch
            batch_id = self._find_active_batch(event_type)
            is_new_batch = batch_id is None

            if is_new_batch:
                # Phase 3: Replace with Redis HSET + EXPIRE
                #   batch_id = str(uuid.uuid4())
                #   await redis.hset(f"debounce:{event_type}:{batch_id}", mapping={...})
                #   await redis.expire(f"debounce:{event_type}:{batch_id}", window_seconds)
                batch_id = str(uuid.uuid4())
                bucket[batch_id] = {
                    "events": [event_data],
                    "first_at": now,
                    "last_at": now,
                }
                # Start a timer that will "complete" this batch
                self._timers[event_type] = asyncio.create_task(
                    self._on_window_expire(event_type, batch_id, window_seconds)
                )
                logger.info(
                    "debounce: new batch %s for %s (window=%.1fs)",
                    batch_id,
                    event_type,
                    window_seconds,
                )
            else:
                # Append to existing batch
                bucket[batch_id]["events"].append(event_data)
                bucket[batch_id]["last_at"] = now
                logger.debug(
                    "debounce: appended to batch %s for %s (total=%d events)",
                    batch_id,
                    event_type,
                    len(bucket[batch_id]["events"]),
                )

            queued_count = len(bucket[batch_id]["events"])
            first_at = bucket[batch_id]["first_at"].isoformat()

        return {
            "should_process": is_new_batch,  # Phase 2: new batch means "should start processing"
            "batch_id": batch_id,
            "queued_count": queued_count,
            "first_event_at": first_at,
            "last_event_at": now_iso,
        }

    async def flush(self, event_type: Optional[str] = None) -> Dict[str, Any]:
        """Force-flush all queued batches, optionally filtered by *event_type*.

        This immediately completes all pending batches so their events can be
        processed without waiting for the debounce window to expire.

        Args:
            event_type: If provided, only flush batches for this event type.
                        If None, flush all event types.

        Returns:
            Dict with keys:
                flushed_batches (int):  Number of batches flushed.
                events_processed (int): Total events across flushed batches.
        """
        async with self._lock:
            types_to_flush = (
                [event_type] if event_type else list(self._queue.keys())
            )

            total_batches = 0
            total_events = 0

            for etype in types_to_flush:
                if etype not in self._queue:
                    continue

                bucket = self._queue[etype]
                for batch_id, batch_data in bucket.items():
                    event_count = len(batch_data.get("events", []))
                    total_events += event_count
                    total_batches += 1
                    logger.info(
                        "flush: batch %s (%s) — %d events released",
                        batch_id,
                        etype,
                        event_count,
                    )

                # Cancel any pending timer for this event type
                timer = self._timers.pop(etype, None)
                if timer and not timer.done():
                    timer.cancel()

                # Clear the bucket
                self._queue.pop(etype, None)

            self._flushed_count += total_batches

            logger.info(
                "flush complete: %d batch(es), %d event(s), types=%s",
                total_batches,
                total_events,
                types_to_flush,
            )

        return {
            "flushed_batches": total_batches,
            "events_processed": total_events,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_active_batch(self, event_type: str) -> Optional[str]:
        """Return the batch_id of the currently active batch for *event_type*,
        or None if no active batch exists (i.e. timer already fired or none started).

        Phase 3: Query Redis for batch key existence.
        """
        bucket = self._queue.get(event_type, {})
        # In Phase 2 we consider the first (and only) batch in the bucket as active
        if bucket:
            return next(iter(bucket))
        return None

    async def _on_window_expire(
        self, event_type: str, batch_id: str, window_seconds: float
    ) -> None:
        """Timer callback: fires after *window_seconds*, marking the batch as
        ready for processing by removing it from the active queue.

        Phase 3: Redis keys auto-expire, so this becomes a simple notification
        publish rather than a state mutation.
        """
        await asyncio.sleep(window_seconds)

        async with self._lock:
            bucket = self._queue.get(event_type, {})
            batch_data = bucket.pop(batch_id, None)
            if batch_data is None:
                return  # already flushed

            event_count = len(batch_data.get("events", []))
            logger.info(
                "debounce window expired for %s batch=%s (%d events) — batch ready",
                event_type,
                batch_id,
                event_count,
            )

            # Clean up empty buckets
            if not bucket:
                self._queue.pop(event_type, None)
            self._timers.pop(event_type, None)
