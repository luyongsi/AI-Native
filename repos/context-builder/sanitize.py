"""ContextSanitizer: clear contaminated context history on external loop failures.

When an external loop (agent chain, multi-step reasoning) experiences
consecutive failures, previously collected context may be tainted.
This sanitizer detects such conditions and clears the pollution.
"""

import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SanitizeState:
    """Tracks failure history for sanitation decisions."""
    agent_id: str
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    failure_window_start: float = 0.0
    total_failures: int = 0


class ContextSanitizer:
    """Detect and remediate context pollution from external loop failures.

    Rules:
      - Track consecutive failures per agent
      - After N consecutive failures (default 3), flush contamination history
        for that agent
      - After a success, reset the counter
      - Stale failure records (older than window_seconds) are cleaned up
    """

    def __init__(self,
                 max_consecutive_failures: int = 3,
                 window_seconds: float = 300.0):
        """
        Args:
            max_consecutive_failures: Consecutive failures before triggering flush
            window_seconds: Failure window for staleness cleanup
        """
        self.max_consecutive_failures = max_consecutive_failures
        self.window_seconds = window_seconds
        self._states: Dict[str, SanitizeState] = {}

    def record_failure(self, agent_id: str) -> bool:
        """Record a failure for an agent. Returns True if flush is needed."""
        now = time.time()
        state = self._ensure_state(agent_id)

        # Check if this is a new failure streak
        if state.consecutive_failures == 0:
            state.failure_window_start = now

        state.consecutive_failures += 1
        state.last_failure_time = now
        state.total_failures += 1

        if state.consecutive_failures >= self.max_consecutive_failures:
            logger.warning(
                f"ContextSanitizer: Agent {agent_id} has {state.consecutive_failures} "
                f"consecutive failures. Triggering context flush."
            )
            return True

        logger.info(
            f"ContextSanitizer: Agent {agent_id} failure {state.consecutive_failures}/"
            f"{self.max_consecutive_failures}"
        )
        return False

    def record_success(self, agent_id: str):
        """Record a success, resetting the failure counter."""
        state = self._ensure_state(agent_id)
        old_count = state.consecutive_failures
        state.consecutive_failures = 0
        state.failure_window_start = 0.0

        if old_count > 0:
            logger.info(
                f"ContextSanitizer: Agent {agent_id} recovered after "
                f"{old_count} failures."
            )

    def is_contaminated(self, agent_id: str) -> bool:
        """Check if an agent's context history is suspected contaminated."""
        state = self._states.get(agent_id)
        if state is None:
            return False
        return state.consecutive_failures >= self.max_consecutive_failures

    def flush_agent(self, agent_id: str) -> List[str]:
        """Clear contamination state for an agent. Returns list of flushed keys."""
        flushed = []
        if agent_id in self._states:
            state = self._states.pop(agent_id)
            flushed.append(agent_id)
            logger.info(
                f"ContextSanitizer: Flushed contamination history for agent "
                f"{agent_id} ({state.total_failures} total failures)."
            )
        return flushed

    def cleanup_stale(self):
        """Remove stale failure records outside the window."""
        now = time.time()
        stale_keys = []
        for agent_id, state in self._states.items():
            if now - state.last_failure_time > self.window_seconds:
                stale_keys.append(agent_id)

        for key in stale_keys:
            logger.info(f"ContextSanitizer: Removing stale record for agent {key}")
            del self._states[key]

    def _ensure_state(self, agent_id: str) -> SanitizeState:
        if agent_id not in self._states:
            self._states[agent_id] = SanitizeState(agent_id=agent_id)
        return self._states[agent_id]

    @property
    def tracked_agents(self) -> List[str]:
        return list(self._states.keys())
