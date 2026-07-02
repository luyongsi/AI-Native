"""Circuit breaker with escalation strategy (few-shot → strong model → human).

Tracks failure counts per (req_id, agent_id) and escalates through:
  1. FEW_SHOT: Inject few-shot examples
  2. STRONG_MODEL: Switch to stronger model (Claude Sonnet)
  3. HUMAN: Request human intervention (send Feishu notification)
"""

from enum import Enum
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class EscalationLevel(Enum):
    """Escalation levels for circuit breaker."""
    NORMAL = 0
    FEW_SHOT = 1
    STRONG_MODEL = 2
    HUMAN = 3


@dataclass
class FailureRecord:
    """Track failures for a single (req_id, agent_id) pair."""
    req_id: str
    agent_id: str
    failure_count: int = 0
    current_level: EscalationLevel = field(default=EscalationLevel.NORMAL)

    def escalate(self) -> EscalationLevel:
        """Record a failure and return the new escalation level."""
        self.failure_count += 1

        if self.failure_count == 1:
            self.current_level = EscalationLevel.FEW_SHOT
        elif self.failure_count == 2:
            self.current_level = EscalationLevel.STRONG_MODEL
        else:
            self.current_level = EscalationLevel.HUMAN

        return self.current_level

    def reset(self) -> None:
        """Reset on success."""
        self.failure_count = 0
        self.current_level = EscalationLevel.NORMAL


class CircuitBreaker:
    """Manages escalation strategy based on failure patterns.

    Per-requirement, per-agent tracking of failures and escalation levels.
    """

    def __init__(self):
        """Initialize circuit breaker with empty state store."""
        self._state: dict[tuple[str, str], FailureRecord] = {}

    def get_level(self, req_id: str, agent_id: str) -> EscalationLevel:
        """Get current escalation level for (req_id, agent_id)."""
        key = (req_id, agent_id)
        if key not in self._state:
            self._state[key] = FailureRecord(req_id, agent_id)
        return self._state[key].current_level

    def record_failure(self, req_id: str, agent_id: str) -> EscalationLevel:
        """Record a failure and return the new escalation level.

        Increments failure count and determines next escalation strategy:
          1st failure → FEW_SHOT
          2nd failure → STRONG_MODEL
          3rd+ failure → HUMAN
        """
        key = (req_id, agent_id)
        if key not in self._state:
            self._state[key] = FailureRecord(req_id, agent_id)

        record = self._state[key]
        new_level = record.escalate()

        logger.info(
            "Circuit breaker escalated [req=%s agent=%s] "
            "failure_count=%d new_level=%s",
            req_id, agent_id, record.failure_count, new_level.name
        )
        return new_level

    def reset(self, req_id: str, agent_id: str) -> None:
        """Reset escalation state on success."""
        key = (req_id, agent_id)
        if key in self._state:
            self._state[key].reset()
            logger.debug(
                "Circuit breaker reset [req=%s agent=%s]",
                req_id, agent_id
            )

    def cleanup(self, req_id: str) -> None:
        """Clean up all states for a given req_id (e.g., on requirement completion)."""
        keys_to_remove = [k for k in self._state if k[0] == req_id]
        for key in keys_to_remove:
            del self._state[key]
        if keys_to_remove:
            logger.debug(
                "Circuit breaker cleaned up %d records for req=%s",
                len(keys_to_remove), req_id
            )


# Module-level singleton
_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    """Get or create the module-level circuit breaker instance."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
