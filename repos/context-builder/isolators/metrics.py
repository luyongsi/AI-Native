"""Prometheus metrics for isolation decisions."""

from collections import defaultdict
from typing import Dict, Any


class IsolationMetrics:
    """Prometheus-style metrics for isolation decisions."""

    def __init__(self):
        """Initialize metrics."""
        # Counter: isolation_decisions_total
        self._decisions_by_mode_and_risk = defaultdict(int)

        # Histogram: isolation_decision_duration_seconds
        self._duration_buckets = defaultdict(list)
        self._duration_sum = 0.0
        self._duration_count = 0

    def record_decision(self, isolation_mode: str, risk_level: str,
                       duration_seconds: float):
        """Record an isolation decision.

        Args:
            isolation_mode: 'NONE', 'WORKTREE', or 'CONTAINER'
            risk_level: 'low', 'medium', or 'high'
            duration_seconds: Decision duration in seconds
        """
        key = f"{isolation_mode}:{risk_level}"
        self._decisions_by_mode_and_risk[key] += 1

        # Record histogram
        self._duration_buckets[key].append(duration_seconds)
        self._duration_sum += duration_seconds
        self._duration_count += 1

    def get_counter_value(self, isolation_mode: str, risk_level: str) -> int:
        """Get counter value for a mode/risk combination.

        Args:
            isolation_mode: 'NONE', 'WORKTREE', or 'CONTAINER'
            risk_level: 'low', 'medium', or 'high'

        Returns:
            Number of decisions with this mode/risk combination
        """
        key = f"{isolation_mode}:{risk_level}"
        return self._decisions_by_mode_and_risk[key]

    def get_counter_total(self) -> int:
        """Get total number of decisions."""
        return self._duration_count

    def get_counter_by_mode(self) -> Dict[str, int]:
        """Get decision counts by mode."""
        counts = defaultdict(int)
        for key, count in self._decisions_by_mode_and_risk.items():
            mode, _ = key.split(':')
            counts[mode] += count
        return dict(counts)

    def get_histogram_stats(self, isolation_mode: str = None,
                            risk_level: str = None) -> Dict[str, Any]:
        """Get histogram statistics for durations.

        Args:
            isolation_mode: Optional filter by mode
            risk_level: Optional filter by risk level

        Returns:
            Dict with count, sum, and percentiles
        """
        if isolation_mode and risk_level:
            key = f"{isolation_mode}:{risk_level}"
            durations = self._duration_buckets[key]
        else:
            durations = []
            for bucket_durations in self._duration_buckets.values():
                durations.extend(bucket_durations)

        if not durations:
            return {
                'count': 0,
                'sum': 0.0,
                'mean': 0.0,
                'p50': 0.0,
                'p95': 0.0,
                'p99': 0.0,
            }

        durations_sorted = sorted(durations)
        count = len(durations_sorted)
        total = sum(durations_sorted)

        def percentile(p):
            if not durations_sorted:
                return 0.0
            idx = int(count * (p / 100.0))
            return durations_sorted[min(idx, count - 1)]

        return {
            'count': count,
            'sum': total,
            'mean': total / count if count > 0 else 0.0,
            'p50': percentile(50),
            'p95': percentile(95),
            'p99': percentile(99),
        }

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []

        # Counter: isolation_decisions_total
        lines.append('# HELP isolation_decisions_total Total isolation decisions')
        lines.append('# TYPE isolation_decisions_total counter')

        for (mode, risk), count in sorted(self._decisions_by_mode_and_risk.items()):
            mode_val = mode.split(':')[0]
            risk_val = mode.split(':')[1]
            lines.append(
                f'isolation_decisions_total{{mode="{mode_val}",risk_level="{risk_val}"}} {count}'
            )

        lines.append('')

        # Histogram: isolation_decision_duration_seconds
        lines.append('# HELP isolation_decision_duration_seconds Duration of isolation decisions')
        lines.append('# TYPE isolation_decision_duration_seconds histogram')

        # Buckets in seconds: 0.001, 0.005, 0.01, 0.05, 0.1
        buckets = [0.001, 0.005, 0.01, 0.05, 0.1]

        # Count observations in each bucket
        bucket_counts = defaultdict(int)
        for duration_list in self._duration_buckets.values():
            for duration in duration_list:
                for bucket in buckets:
                    if duration <= bucket:
                        bucket_counts[bucket] += 1

        for bucket in buckets:
            lines.append(
                f'isolation_decision_duration_seconds_bucket{{le="{bucket}"}} {bucket_counts[bucket]}'
            )

        lines.append(f'isolation_decision_duration_seconds_bucket{{le="+Inf"}} {self._duration_count}')
        lines.append(f'isolation_decision_duration_seconds_sum {self._duration_sum}')
        lines.append(f'isolation_decision_duration_seconds_count {self._duration_count}')

        return '\n'.join(lines)

    def reset(self):
        """Reset all metrics."""
        self._decisions_by_mode_and_risk.clear()
        self._duration_buckets.clear()
        self._duration_sum = 0.0
        self._duration_count = 0


# Global metrics instance
_metrics_instance = None


def get_metrics() -> IsolationMetrics:
    """Get or create global metrics instance."""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = IsolationMetrics()
    return _metrics_instance


def reset_metrics():
    """Reset global metrics."""
    global _metrics_instance
    _metrics_instance = None
