"""
a13/feature_flag.py — Feature Flag Manager

Manages feature flags for progressive delivery and dark launches.
Flags control who sees a new feature (percentage rollout, user targeting).

Real implementation pattern:
  - Use LaunchDarkly / Split.io / Flagsmith SDK
  - Or a custom flag service backed by Redis/PostgreSQL
  - Evaluate flags client-side with rule engine (targeting, split, etc.)
  - Cache flag state locally with periodic refresh

Typical flag evaluation flow:
  1. App calls is_enabled("new-checkout", user_id="u123")
  2. SDK checks local cache -> if stale, fetch from flag service
  3. Evaluate rules: user in target segment? rollout % bucket match?
  4. Return boolean
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class FeatureFlagManager:
    """Stub feature flag manager.

    In production this would be backed by a distributed flag service.
    For now it maintains an in-memory store of flags and simulates
    the full lifecycle: create, enable, disable, and evaluate.
    """

    def __init__(self):
        # In-memory flag store — production would use Redis / DB
        self._flags: dict[str, dict] = {}

    async def create_flag(
        self,
        name: str,
        description: str,
        rollout_pct: int = 0,
    ) -> dict:
        """Create a new feature flag.

        Args:
            name: Unique flag key (e.g. "new-checkout-flow")
            description: Human-readable description
            rollout_pct: Initial rollout percentage (0-100)

        Returns:
            dict with flag_id, name, description, rollout_pct, enabled, created_at
        """
        flag_id = f"flag-{uuid.uuid4().hex[:8]}"
        flag = {
            "flag_id": flag_id,
            "name": name,
            "description": description,
            "rollout_pct": rollout_pct,
            "enabled": rollout_pct > 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._flags[flag_id] = flag
        logger.info(
            "Feature flag created: id=%s name=%s rollout=%d%%",
            flag_id, name, rollout_pct,
        )
        return flag

    async def enable_flag(self, flag_id: str, rollout_pct: int) -> dict:
        """Enable (or update rollout percentage of) a feature flag.

        Args:
            flag_id: The flag to enable
            rollout_pct: Percentage of users who should see the feature (0-100)

        Returns:
            Updated flag dict
        """
        await asyncio.sleep(0.05)  # simulate I/O

        if flag_id not in self._flags:
            logger.warning("Flag not found: %s", flag_id)
            return {"error": f"Flag {flag_id} not found", "flag_id": flag_id}

        self._flags[flag_id]["enabled"] = rollout_pct > 0
        self._flags[flag_id]["rollout_pct"] = rollout_pct
        self._flags[flag_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("Flag %s enabled at %d%% rollout", flag_id, rollout_pct)
        return self._flags[flag_id]

    async def disable_flag(self, flag_id: str) -> dict:
        """Disable a feature flag (set rollout to 0%).

        Returns:
            Updated flag dict
        """
        await asyncio.sleep(0.05)  # simulate I/O

        if flag_id not in self._flags:
            logger.warning("Flag not found: %s", flag_id)
            return {"error": f"Flag {flag_id} not found", "flag_id": flag_id}

        self._flags[flag_id]["enabled"] = False
        self._flags[flag_id]["rollout_pct"] = 0
        self._flags[flag_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("Flag %s disabled", flag_id)
        return self._flags[flag_id]

    async def is_enabled(self, flag_id: str, user_id: str | None = None) -> bool:
        """Check whether a flag is enabled for a given user.

        Implements consistent percentage rollout using hash-based bucketing.
        A given user_id will always get the same result for a given rollout_pct
        (deterministic hash), ensuring a stable experience.

        Args:
            flag_id: The flag to evaluate
            user_id: Optional user identifier for percentage-based targeting.
                     If None, returns the global enabled state.

        Returns:
            bool — True if the feature should be shown to this user
        """
        await asyncio.sleep(0.02)  # simulate I/O

        if flag_id not in self._flags:
            logger.warning("Flag not found: %s", flag_id)
            return False

        flag = self._flags[flag_id]

        # Globally disabled
        if not flag["enabled"]:
            return False

        # 100% rollout — everyone gets it
        rollout_pct = flag["rollout_pct"]
        if rollout_pct >= 100:
            return True

        # No user_id provided — return global state
        if user_id is None:
            return flag["enabled"]

        # Consistent hash bucketing:
        # hash(user_id + flag_id) % 100 < rollout_pct
        bucket = hash(f"{user_id}:{flag_id}") % 100
        is_in_rollout = bucket < rollout_pct

        logger.debug(
            "Flag %s eval: user=%s bucket=%d rollout=%d%% => %s",
            flag_id, user_id, bucket, rollout_pct, is_in_rollout,
        )
        return is_in_rollout
