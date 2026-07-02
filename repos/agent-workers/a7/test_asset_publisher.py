"""
Test Asset Publisher — publishes test.ready events and creates VisAgent batches.

Real implementation would:
  - Connect to NATS event bus and publish typed events
  - Create VisAgent batches via the VisAgent API for trace visualization
  - Track publish state with idempotency keys
  - Support retry with exponential backoff
  - Record audit trail of published test assets
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TestAssetPublisher:
    """
    Publishes test.ready events onto the event bus and creates
    corresponding VisAgent visualization batches.

    This is a simulation stub — in production it would use the real
    EventPublisher and VisAgent HTTP client.
    """

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self._published_events: list = []

    async def publish_test_ready(
        self, req_id: str, test_assets: dict
    ) -> dict:
        """
        Publish a test.ready event and create a VisAgent batch.

        Args:
            req_id: The requirement / request ID this test plan belongs to.
            test_assets: The complete test assets dict (test plan, cases, etc.).

        Returns:
            {
                event_id: str,          # unique event ID
                published: bool,        # whether publish succeeded
                test_case_count: int,   # number of test cases published
                visagent_batch_id: str, # VisAgent batch ID for trace visualization
            }
        """
        event_id = f"evt-{req_id}-{secrets.token_hex(6)}"
        visagent_batch_id = f"vab-{req_id}-{secrets.token_hex(4)}"

        test_case_count = 0
        if isinstance(test_assets, dict):
            test_plan = test_assets.get("test_plan", test_assets)
            test_case_count = test_plan.get("total_cases", len(test_assets.get("cases", [])))

        logger.info(
            "Publishing test.ready for req=%s — %d test cases, event=%s, batch=%s",
            req_id,
            test_case_count,
            event_id,
            visagent_batch_id,
        )

        # --- Simulate event bus publish ---
        event_payload = {
            "event_id": event_id,
            "event_type": "test.ready",
            "req_id": req_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "test_case_count": test_case_count,
                "test_plan_id": test_assets.get(
                    "test_plan_id",
                    f"tp-{req_id}",
                ),
                "asset_summary": self._summarize_assets(test_assets),
            },
        }

        self._published_events.append(event_payload)
        logger.debug("Event queued: %s", event_id)

        # --- Simulate VisAgent batch creation ---
        visagent_payload = {
            "batch_id": visagent_batch_id,
            "req_id": req_id,
            "source_event": event_id,
            "test_case_count": test_case_count,
            "status": "created",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.debug("VisAgent batch created: %s", visagent_batch_id)

        return {
            "event_id": event_id,
            "published": True,
            "test_case_count": test_case_count,
            "visagent_batch_id": visagent_batch_id,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _summarize_assets(self, test_assets: dict) -> dict:
        """Build a lightweight summary of test assets for the event payload."""
        summary = {}
        plan = test_assets.get("test_plan", test_assets)
        cases = plan.get("cases", test_assets.get("cases", []))

        # Count by type
        type_counts: Dict[str, int] = {}
        for c in cases:
            t = c.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        # Count by priority
        priority_counts: Dict[str, int] = {}
        for c in cases:
            p = c.get("priority", "P9")
            priority_counts[p] = priority_counts.get(p, 0) + 1

        return {
            "total_cases": len(cases),
            "by_type": type_counts,
            "by_priority": priority_counts,
            "asset_types": list(test_assets.get("test_assets", {}).keys()),
        }
