"""
a13/auto_rollback.py — Auto Rollbacker

Evaluates canary health metrics against thresholds and triggers rollback
when violations are detected. Thresholds are configurable.

Real implementation pattern:
  - Evaluate Prometheus results against SLO thresholds
  - Call `kubectl argo rollouts undo <rollout>` or abort the canary step
  - Re-route traffic back to the stable ReplicaSet
  - Record the incident for post-mortem analysis
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Default rollback thresholds — tuned to typical SLOs
DEFAULT_ROLLBACK_THRESHOLDS = {
    "error_rate": 0.05,            # 5% — anything above triggers rollback
    "latency_p99_multiplier": 2.0,  # 2x baseline
    "cpu_pct": 90,                  # 90%
    "memory_pct": 90,               # 90%
}


class AutoRollbacker:
    """Automated rollback decider and executor.

    Consumes health metrics from MetricsMonitor and decides whether to
    roll back a canary deployment. In production this interacts with Argo
    Rollouts or the underlying Kubernetes Deployment controller.
    """

    def __init__(self, thresholds: dict | None = None,
                 baseline_latency_p99_ms: float = 200.0):
        self.thresholds = thresholds or DEFAULT_ROLLBACK_THRESHOLDS
        self.baseline_latency_p99_ms = baseline_latency_p99_ms

    async def should_rollback(self, metrics: dict) -> dict:
        """Evaluate metrics against thresholds and decide whether to rollback.

        Args:
            metrics: A metrics dict as returned by MetricsMonitor.check_health().
                     Expected keys: error_rate, latency_p99, cpu_pct, memory_pct, checks[].

        Returns:
            dict with should_rollback, reason, violated_thresholds[]
        """
        logger.info("Evaluating rollback decision...")

        # Simulate evaluation time
        await asyncio.sleep(0.1)

        violated: list[dict] = []

        error_rate = metrics.get("error_rate", 0)
        latency_p99 = metrics.get("latency_p99", 0)
        cpu_pct = metrics.get("cpu_pct", 0)
        memory_pct = metrics.get("memory_pct", 0)

        # Check error rate
        if error_rate > self.thresholds["error_rate"]:
            violated.append({
                "metric": "error_rate",
                "value": error_rate,
                "threshold": self.thresholds["error_rate"],
                "description": (
                    f"Error rate {error_rate:.4f} exceeds threshold "
                    f"{self.thresholds['error_rate']}"
                ),
            })

        # Check latency P99 vs baseline * multiplier
        latency_limit = self.baseline_latency_p99_ms * self.thresholds["latency_p99_multiplier"]
        if latency_p99 > latency_limit:
            violated.append({
                "metric": "latency_p99",
                "value": latency_p99,
                "threshold": latency_limit,
                "baseline": self.baseline_latency_p99_ms,
                "multiplier": self.thresholds["latency_p99_multiplier"],
                "description": (
                    f"P99 latency {latency_p99:.1f}ms exceeds "
                    f"{latency_limit:.1f}ms ({self.thresholds['latency_p99_multiplier']}x baseline)"
                ),
            })

        # Check CPU
        if cpu_pct > self.thresholds["cpu_pct"]:
            violated.append({
                "metric": "cpu_pct",
                "value": cpu_pct,
                "threshold": self.thresholds["cpu_pct"],
                "description": (
                    f"CPU usage {cpu_pct:.1f}% exceeds threshold "
                    f"{self.thresholds['cpu_pct']}%"
                ),
            })

        # Check memory
        if memory_pct > self.thresholds["memory_pct"]:
            violated.append({
                "metric": "memory_pct",
                "value": memory_pct,
                "threshold": self.thresholds["memory_pct"],
                "description": (
                    f"Memory usage {memory_pct:.1f}% exceeds threshold "
                    f"{self.thresholds['memory_pct']}%"
                ),
            })

        should_rollback = len(violated) > 0
        reason = (
            f"{len(violated)} threshold(s) violated: "
            + ", ".join(v["metric"] for v in violated)
            if violated
            else "All metrics within thresholds"
        )

        result = {
            "should_rollback": should_rollback,
            "reason": reason,
            "violated_thresholds": violated,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

        if should_rollback:
            logger.warning("ROLLBACK RECOMMENDED: %s", reason)
        else:
            logger.info("No rollback needed: %s", reason)

        return result

    async def rollback(self, deploy_id: str, previous_version: str) -> dict:
        """Execute a rollback to the previous stable version.

        In production this would:
          - Call `kubectl argo rollouts undo <rollout> --to-revision=<n>`
          - Or patch the Rollout's `.spec.template` back to previous image
          - Wait for the stable ReplicaSet to become ready

        Args:
            deploy_id: The canary deploy ID to rollback
            previous_version: Previous stable version tag (e.g. "myapp:v1.2.2")

        Returns:
            dict with rolled_back, rollback_id, new_version, duration_seconds
        """
        rollback_id = f"rollback-{uuid.uuid4().hex[:8]}"
        logger.warning(
            "ROLLBACK STARTED: deploy=%s -> %s (rollback_id=%s)",
            deploy_id, previous_version, rollback_id,
        )

        # Simulate rollback time (scaled down for stubs)
        rollback_duration = 5  # seconds, would be 30-60s in production
        await asyncio.sleep(min(rollback_duration / 5, 1))

        result = {
            "rolled_back": True,
            "rollback_id": rollback_id,
            "deploy_id": deploy_id,
            "previous_version": previous_version,
            "new_version": previous_version,  # reverted to previous
            "duration_seconds": rollback_duration,
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("Rollback complete: %s -> %s", deploy_id, previous_version)
        return result
