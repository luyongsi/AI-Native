"""
Event Tracker for Phase 6 E2E tests.

Subscribes to NATS events and tracks event flow through the system.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import nats

logger = logging.getLogger(__name__)


class EventTracker:
    """Tracks events flowing through the NATS event bus."""

    def __init__(self, nats_client: nats.NATS):
        self.nats = nats_client
        self.events: List[Dict[str, Any]] = []
        self.subscriptions: Dict[str, nats.Subscription] = {}

    async def subscribe_all(self) -> None:
        """Subscribe to all relevant event subjects."""
        subjects = [
            "requirement.intake",
            "requirement.validated",
            "knowledge.analyzed",
            "spec.api_schema_ready",
            "spec.erd_ready",
            "architecture.dag_built",
            "code.generated",
            "code.reviewed",
            "test.generated",
            "test.executed",
            "test.passed",
            "test.failed",
            "test.coverage_analyzed",
            "gate.submitted",
            "gate.approved",
            "gate.rejected",
            "pr.created",
            "pr.merged",
            "requirement.completed",
            "requirement.failed",
            "requirement.blocked",
        ]

        for subject in subjects:
            try:
                sub = await self.nats.subscribe(subject)
                self.subscriptions[subject] = sub
                logger.info(f"Subscribed to {subject}")
            except Exception as e:
                logger.warning(f"Failed to subscribe to {subject}: {e}")

    async def consume_events(self) -> None:
        """Consume events from all subscriptions."""
        tasks = []
        for subject, sub in self.subscriptions.items():
            task = asyncio.create_task(self._consume_subject(subject, sub))
            tasks.append(task)

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()

    async def _consume_subject(self, subject: str, sub: nats.Subscription) -> None:
        """Consume events from a single subject."""
        try:
            async for msg in sub.messages:
                self._handle_event(subject, msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error consuming from {subject}: {e}")

    def _handle_event(self, subject: str, msg: nats.Msg) -> None:
        """Handle a single event message."""
        try:
            data = json.loads(msg.data.decode())
            event = {
                "subject": subject,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "seq": msg.metadata.sequence.stream if msg.metadata else None,
            }
            self.events.append(event)
            logger.debug(f"Captured {subject}: {data.get('event_id', 'unknown')}")
        except Exception as e:
            logger.warning(f"Failed to process event on {subject}: {e}")

    def get_timeline(self, req_id: str) -> List[Dict[str, Any]]:
        """Get timeline of events for a specific requirement."""
        return [
            e for e in self.events
            if e["data"].get("req_id") == req_id
        ]

    def get_events_by_type(self, req_id: str, event_type: str) -> List[Dict[str, Any]]:
        """Get all events of a specific type for a requirement."""
        return [
            e for e in self.events
            if e["data"].get("req_id") == req_id and e["subject"] == event_type
        ]

    def get_first_event(self, req_id: str, event_type: str) -> Optional[Dict[str, Any]]:
        """Get the first event of a specific type."""
        events = self.get_events_by_type(req_id, event_type)
        return events[0] if events else None

    def get_last_event(self, req_id: str, event_type: str) -> Optional[Dict[str, Any]]:
        """Get the last event of a specific type."""
        events = self.get_events_by_type(req_id, event_type)
        return events[-1] if events else None

    def get_time_between_events(
        self,
        req_id: str,
        from_event: str,
        to_event: str,
    ) -> Optional[float]:
        """Get time elapsed between two events (in seconds)."""
        first = self.get_first_event(req_id, from_event)
        last = self.get_last_event(req_id, to_event)

        if not first or not last:
            return None

        from datetime import datetime as dt
        t1 = dt.fromisoformat(first["timestamp"])
        t2 = dt.fromisoformat(last["timestamp"])
        return (t2 - t1).total_seconds()

    def verify_event_sequence(
        self,
        req_id: str,
        expected_sequence: List[str],
    ) -> tuple[bool, str]:
        """
        Verify events occur in expected sequence.

        Returns (success, message).
        """
        timeline = self.get_timeline(req_id)
        subjects = [e["subject"] for e in timeline]

        # Check all expected events are present
        for expected in expected_sequence:
            if expected not in subjects:
                return False, f"Missing expected event: {expected}"

        # Check order
        last_idx = -1
        for expected in expected_sequence:
            try:
                idx = subjects.index(expected, last_idx + 1)
                last_idx = idx
            except ValueError:
                return False, f"Event {expected} appears out of sequence"

        return True, "All events in correct sequence"

    def get_stats(self, req_id: str) -> Dict[str, Any]:
        """Get statistics about events for a requirement."""
        timeline = self.get_timeline(req_id)

        if not timeline:
            return {
                "total_events": 0,
                "event_types": [],
                "first_event_time": None,
                "last_event_time": None,
                "duration_seconds": 0,
            }

        subjects = [e["subject"] for e in timeline]
        unique_subjects = list(set(subjects))

        from datetime import datetime as dt
        first_time = dt.fromisoformat(timeline[0]["timestamp"])
        last_time = dt.fromisoformat(timeline[-1]["timestamp"])
        duration = (last_time - first_time).total_seconds()

        return {
            "total_events": len(timeline),
            "event_types": unique_subjects,
            "event_type_count": {
                subject: subjects.count(subject)
                for subject in unique_subjects
            },
            "first_event_time": timeline[0]["timestamp"],
            "last_event_time": timeline[-1]["timestamp"],
            "duration_seconds": duration,
        }

    async def unsubscribe_all(self) -> None:
        """Unsubscribe from all subjects."""
        for subject, sub in self.subscriptions.items():
            try:
                await sub.unsubscribe()
                logger.info(f"Unsubscribed from {subject}")
            except Exception as e:
                logger.warning(f"Error unsubscribing from {subject}: {e}")

        self.subscriptions.clear()
