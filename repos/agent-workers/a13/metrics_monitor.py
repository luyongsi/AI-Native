"""
a13/metrics_monitor.py — Metrics Monitor

Simulates Prometheus query results for canary health checks.
Checks error rate, P99 latency, CPU, and memory against thresholds.

Real implementation pattern:
  - Query Prometheus API: GET /api/v1/query?query=<promql>
  - Common queries:
      sum(rate(http_requests_total{target="x",status=~"5.."}[5m]))
        /
      sum(rate(http_requests_total{target="x"}[5m]))
      histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
      container_cpu_usage_seconds_total{pod=~"x-.*"}
  - Evaluate against SLO thresholds defined in a config map
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Default health check thresholds
DEFAULT_THRESHOLDS = {
    "error_rate": 0.05,        # 5%
    "latency_p99_ms": 500,     # 500ms
    "cpu_pct": 90,             # 90%
    "memory_pct": 85,          # 85%
}


class MetricsMonitor:
    """Prometheus-backed health checker for canary deployments.

    In production, each method would issue HTTP GET to a Prometheus-compatible
    endpoint (Prometheus, VictoriaMetrics, Cortex) and parse the JSON response.
    """

    def __init__(self, prometheus_url: str = "http://prometheus:9090",
                 thresholds: dict | None = None):
        self.prometheus_url = prometheus_url
        self.thresholds = thresholds or DEFAULT_THRESHOLDS

    async def check_health(self, deploy_id: str, target: str) -> dict:
        """Run health checks against a canary deployment target.

        Returns a dict with healthy (bool), raw metrics, and per-check pass/fail.
        """
        logger.info("Checking health for deploy=%s target=%s", deploy_id, target)

        # Simulate a short query round-trip
        await asyncio.sleep(0.5)

        # Generate realistic stub metric values
        error_rate = round(random.uniform(0.001, 0.08), 4)
        latency_p99 = round(random.uniform(50, 800), 1)
        cpu_pct = round(random.uniform(10, 95), 1)
        memory_pct = round(random.uniform(20, 92), 1)

        checks = [
            {
                "name": "error_rate",
                "passed": error_rate <= self.thresholds["error_rate"],
                "value": error_rate,
                "threshold": self.thresholds["error_rate"],
                "unit": "ratio",
            },
            {
                "name": "latency_p99",
                "passed": latency_p99 <= self.thresholds["latency_p99_ms"],
                "value": latency_p99,
                "threshold": self.thresholds["latency_p99_ms"],
                "unit": "ms",
            },
            {
                "name": "cpu_pct",
                "passed": cpu_pct <= self.thresholds["cpu_pct"],
                "value": cpu_pct,
                "threshold": self.thresholds["cpu_pct"],
                "unit": "%",
            },
            {
                "name": "memory_pct",
                "passed": memory_pct <= self.thresholds["memory_pct"],
                "value": memory_pct,
                "threshold": self.thresholds["memory_pct"],
                "unit": "%",
            },
        ]

        all_healthy = all(c["passed"] for c in checks)

        result = {
            "healthy": all_healthy,
            "error_rate": error_rate,
            "latency_p99": latency_p99,
            "cpu_pct": cpu_pct,
            "memory_pct": memory_pct,
            "checks": checks,
            "deploy_id": deploy_id,
            "target": target,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "Health check result for %s: healthy=%s err=%.4f p99=%.1fms cpu=%.1f%% mem=%.1f%%",
            target, all_healthy, error_rate, latency_p99, cpu_pct, memory_pct,
        )
        return result

    async def get_metrics(self, target: str, duration_minutes: int = 5) -> dict:
        """Fetch recent metrics for a target.

        Simulates a Prometheus range query over the given duration.
        """
        logger.info(
            "Fetching metrics for target=%s window=%dmin", target, duration_minutes,
        )

        # Simulate query latency
        await asyncio.sleep(0.3)

        # Build a realistic time-series stub
        datapoints = []
        now = datetime.now(timezone.utc)
        for i in range(duration_minutes):
            ts = now.replace(second=0, microsecond=0)
            datapoints.append({
                "timestamp": ts.isoformat(),
                "error_rate": round(random.uniform(0.0, 0.06), 4),
                "latency_p99_ms": round(random.uniform(40, 600), 1),
                "cpu_pct": round(random.uniform(8, 88), 1),
                "memory_pct": round(random.uniform(18, 85), 1),
                "request_count": random.randint(100, 5000),
            })

        # Aggregate
        avg_error = round(sum(d["error_rate"] for d in datapoints) / len(datapoints), 4)
        avg_latency = round(sum(d["latency_p99_ms"] for d in datapoints) / len(datapoints), 1)
        avg_cpu = round(sum(d["cpu_pct"] for d in datapoints) / len(datapoints), 1)
        avg_memory = round(sum(d["memory_pct"] for d in datapoints) / len(datapoints), 1)
        total_requests = sum(d["request_count"] for d in datapoints)

        return {
            "target": target,
            "duration_minutes": duration_minutes,
            "datapoints": datapoints,
            "aggregates": {
                "avg_error_rate": avg_error,
                "avg_latency_p99_ms": avg_latency,
                "avg_cpu_pct": avg_cpu,
                "avg_memory_pct": avg_memory,
                "total_requests": total_requests,
            },
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
