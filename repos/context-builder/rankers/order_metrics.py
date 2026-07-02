"""Prometheus metrics for context ordering."""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class OrderMetrics:
    """Prometheus-style metrics for ordering stage."""

    def __init__(self):
        """Initialize ordering metrics."""
        self.order_top_k_size = 0  # Gauge: Top-K candidates selected
        self.order_duration_ms = 0.0  # Histogram: ordering duration
        self.order_candidates_total = 0  # Counter: total candidates processed
        self.order_discarded_total = 0  # Counter: candidates discarded
        self.order_errors_total = 0  # Counter: ordering errors

        # Agent-specific metrics
        self.agent_order_counts = {}  # Dict[agent_id -> count]
        self.agent_top_k_sizes = {}  # Dict[agent_id -> top_k_size]

        # Histograms (simplified as lists)
        self.duration_samples = []  # List of duration samples in ms
        self.top_k_size_samples = []  # List of top-k sizes

    def record_order(
        self,
        candidates_count: int,
        top_k_size: int,
        duration_ms: float,
        agent_id: str = "unknown",
    ):
        """Record an ordering operation.

        Args:
            candidates_count: Total candidates processed
            top_k_size: Candidates selected in top-K
            duration_ms: Ordering duration in milliseconds
            agent_id: Target agent ID
        """
        self.order_top_k_size = top_k_size
        self.order_candidates_total += candidates_count
        self.order_discarded_total += (candidates_count - top_k_size)
        self.order_duration_ms = duration_ms

        self.duration_samples.append(duration_ms)
        self.top_k_size_samples.append(top_k_size)

        # Track per-agent metrics
        if agent_id not in self.agent_order_counts:
            self.agent_order_counts[agent_id] = 0
            self.agent_top_k_sizes[agent_id] = 0

        self.agent_order_counts[agent_id] += 1
        self.agent_top_k_sizes[agent_id] = top_k_size

        logger.debug(
            f"Order recorded: {candidates_count} candidates -> {top_k_size} top-K "
            f"(discarded: {candidates_count - top_k_size}), "
            f"duration: {duration_ms:.1f}ms, agent: {agent_id}"
        )

    def record_error(self, error: str, agent_id: str = "unknown"):
        """Record an ordering error.

        Args:
            error: Error description
            agent_id: Target agent ID
        """
        self.order_errors_total += 1
        logger.error(f"Order error recorded: {error} (agent: {agent_id})")

    def get_percentile(self, samples: list, percentile: float) -> float:
        """Calculate percentile from samples.

        Args:
            samples: List of samples
            percentile: Percentile (0.0-1.0)

        Returns:
            Percentile value
        """
        if not samples:
            return 0.0
        sorted_samples = sorted(samples)
        index = int(len(sorted_samples) * percentile)
        return sorted_samples[min(index, len(sorted_samples) - 1)]

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary (Prometheus format).

        Returns:
            Dictionary with all metrics
        """
        metrics = {
            'context_builder_order_top_k_size': self.order_top_k_size,
            'context_builder_order_duration_seconds': self.order_duration_ms / 1000.0,
            'context_builder_order_duration_ms': self.order_duration_ms,
            'context_builder_order_candidates_total': self.order_candidates_total,
            'context_builder_order_discarded_total': self.order_discarded_total,
            'context_builder_order_errors_total': self.order_errors_total,
            'context_builder_order_duration_p50_ms': (
                self.get_percentile(self.duration_samples, 0.50)
                if self.duration_samples
                else 0.0
            ),
            'context_builder_order_duration_p95_ms': (
                self.get_percentile(self.duration_samples, 0.95)
                if self.duration_samples
                else 0.0
            ),
            'context_builder_order_duration_p99_ms': (
                self.get_percentile(self.duration_samples, 0.99)
                if self.duration_samples
                else 0.0
            ),
            'context_builder_order_top_k_size_avg': (
                sum(self.top_k_size_samples) / len(self.top_k_size_samples)
                if self.top_k_size_samples
                else 0.0
            ),
        }

        # Add agent-specific metrics
        for agent_id, count in self.agent_order_counts.items():
            metrics[f'context_builder_order_agent_{agent_id}_total'] = count
            metrics[f'context_builder_order_agent_{agent_id}_top_k_size'] = (
                self.agent_top_k_sizes.get(agent_id, 0)
            )

        return metrics

    def reset(self):
        """Reset all metrics."""
        self.order_top_k_size = 0
        self.order_duration_ms = 0.0
        self.order_candidates_total = 0
        self.order_discarded_total = 0
        self.order_errors_total = 0
        self.agent_order_counts = {}
        self.agent_top_k_sizes = {}
        self.duration_samples = []
        self.top_k_size_samples = []
        logger.debug("Order metrics reset")
