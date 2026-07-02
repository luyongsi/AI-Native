"""Prometheus metrics for circuit breaker monitoring.

Tracks escalation events, model switches, and human escalation requests.
"""

import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerMetrics:
    """In-memory metrics collection for circuit breaker.

    In production, these would be exposed via Prometheus endpoints.
    """
    # Counter: total escalations by (agent_id, level)
    escalations_total: Dict[tuple[str, str], int]
    # Counter: total human escalation requests by agent_id
    human_requests_total: Dict[str, int]
    # Counter: total model switches by (from_model, to_model)
    model_switches_total: Dict[tuple[str, str], int]
    # Gauge: current failure count by (req_id, agent_id)
    current_failures: Dict[tuple[str, str], int]

    def __init__(self):
        """Initialize empty metrics."""
        self.escalations_total = {}
        self.human_requests_total = {}
        self.model_switches_total = {}
        self.current_failures = {}

    def increment_escalation(self, agent_id: str, level: str) -> None:
        """Increment escalation counter.

        Args:
            agent_id: Agent identifier
            level: Escalation level name
        """
        key = (agent_id, level)
        self.escalations_total[key] = self.escalations_total.get(key, 0) + 1
        logger.debug(f"Metric: escalation agent_id={agent_id} level={level}")

    def increment_human_request(self, agent_id: str) -> None:
        """Increment human escalation request counter.

        Args:
            agent_id: Agent identifier
        """
        self.human_requests_total[agent_id] = self.human_requests_total.get(agent_id, 0) + 1
        logger.debug(f"Metric: human_request agent_id={agent_id}")

    def increment_model_switch(self, from_model: str, to_model: str) -> None:
        """Increment model switch counter.

        Args:
            from_model: Source model name
            to_model: Target model name
        """
        key = (from_model, to_model)
        self.model_switches_total[key] = self.model_switches_total.get(key, 0) + 1
        logger.debug(f"Metric: model_switch {from_model}→{to_model}")

    def set_failure_count(self, req_id: str, agent_id: str, count: int) -> None:
        """Set current failure count gauge.

        Args:
            req_id: Requirement ID
            agent_id: Agent identifier
            count: Current failure count
        """
        key = (req_id, agent_id)
        self.current_failures[key] = count
        logger.debug(f"Metric: failure_count req_id={req_id} agent_id={agent_id} count={count}")

    def get_escalation_count(self, agent_id: str = None, level: str = None) -> int:
        """Get escalation count with optional filtering.

        Args:
            agent_id: Filter by agent (optional)
            level: Filter by level (optional)

        Returns:
            Total count matching filters
        """
        total = 0
        for (aid, lvl), count in self.escalations_total.items():
            if (agent_id is None or aid == agent_id) and (level is None or lvl == level):
                total += count
        return total

    def get_human_request_count(self, agent_id: str = None) -> int:
        """Get human request count with optional filtering.

        Args:
            agent_id: Filter by agent (optional)

        Returns:
            Total count matching filter
        """
        if agent_id is None:
            return sum(self.human_requests_total.values())
        return self.human_requests_total.get(agent_id, 0)

    def get_model_switch_count(self, from_model: str = None, to_model: str = None) -> int:
        """Get model switch count with optional filtering.

        Args:
            from_model: Filter by source model (optional)
            to_model: Filter by target model (optional)

        Returns:
            Total count matching filters
        """
        total = 0
        for (fm, tm), count in self.model_switches_total.items():
            if (from_model is None or fm == from_model) and (to_model is None or tm == to_model):
                total += count
        return total

    def to_dict(self) -> dict:
        """Export metrics as dictionary.

        Returns:
            Dict with all metrics
        """
        return {
            "escalations_total": dict(self.escalations_total),
            "human_requests_total": dict(self.human_requests_total),
            "model_switches_total": dict(self.model_switches_total),
            "current_failures": dict(self.current_failures),
        }

    def reset(self) -> None:
        """Reset all metrics (useful for testing)."""
        self.escalations_total.clear()
        self.human_requests_total.clear()
        self.model_switches_total.clear()
        self.current_failures.clear()
        logger.info("Circuit breaker metrics reset")


# Module-level singleton
_metrics: CircuitBreakerMetrics | None = None


def get_metrics() -> CircuitBreakerMetrics:
    """Get or create the module-level metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = CircuitBreakerMetrics()
    return _metrics
