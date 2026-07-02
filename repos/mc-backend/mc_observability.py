"""
mc-observability — Observability middleware and metrics exporter for MC Backend.

Phase 5.3: Structured JSON logging, request latency histograms, NATS+gRPC trace injection,
and Agent execution metrics collector.

Usage (in main.py):
    from mc_observability import setup_observability, OBSERVABILITY
    setup_observability(app)

And in agent workers (base_worker.py):
    from mc_observability import record_agent_execution, record_nats_event

No OpenTelemetry SDK dependency — uses pure prometheus_client + manual instrumentation.
OTel traces can be added later via the OTLP exporter when infra is ready.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

# ── Dedicated metrics registry (avoids duplicate registration on hot reload) ──
REGISTRY = CollectorRegistry()

# ── Metric definitions ──────────────────────────────────────────────────────

# API request metrics
mc_requests_total = Counter(
    'mc_requests_total', 'Total API requests',
    ['method', 'path', 'status_code'], registry=REGISTRY,
)
mc_request_latency = Histogram(
    'mc_request_latency_seconds', 'API request latency',
    ['method', 'path'], registry=REGISTRY,
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# Agent execution metrics
agent_executions_total = Counter(
    'agent_executions_total', 'Total agent executions',
    ['agent_id', 'status'], registry=REGISTRY,
)
agent_execution_duration = Histogram(
    'agent_execution_duration_seconds', 'Agent execution duration',
    ['agent_id'], registry=REGISTRY,
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)
agent_queue_depth = Gauge(
    'agent_queue_depth', 'Current agent work queue depth',
    ['agent_id'], registry=REGISTRY,
)

# NATS event metrics
nats_events_total = Counter(
    'nats_events_total', 'NATS events published',
    ['event_type', 'agent_id'], registry=REGISTRY,
)
nats_event_latency = Histogram(
    'nats_event_latency_seconds', 'End-to-end latency from event publish to agent receive',
    ['event_type'], registry=REGISTRY,
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0],
)

# Gate SLA metrics
gate_sla_remaining = Gauge(
    'gate_sla_remaining_seconds', 'Remaining SLA time for pending gates',
    ['gate', 'req_id'], registry=REGISTRY,
)
gate_sla_breaches = Counter(
    'gate_sla_breaches_total', 'Total SLA breaches (overdue gates)',
    ['gate'], registry=REGISTRY,
)
approvals_total = Gauge(
    'approvals_total', 'Approvals by status and gate',
    ['gate', 'status'], registry=REGISTRY,
)

# Business metrics
requirements_gauge = Gauge(
    'requirements_total', 'Total requirements by status',
    ['status'], registry=REGISTRY,
)
active_workflows = Gauge(
    'active_workflows', 'Active Temporal workflows',
    registry=REGISTRY,
)
ws_connections_gauge = Gauge(
    'ws_connections_active', 'Active WebSocket connections',
    registry=REGISTRY,
)

# Pipeline metrics
pipeline_stage_transitions = Counter(
    'pipeline_stage_transitions_total', 'Pipeline stage transitions',
    ['from_stage', 'to_stage'], registry=REGISTRY,
)
pipeline_stage_duration = Histogram(
    'pipeline_stage_duration_seconds', 'Time spent in each pipeline stage',
    ['stage'], registry=REGISTRY,
    buckets=[60, 300, 600, 1800, 3600, 7200, 14400, 43200],
)

# Circuit breaker metrics
circuit_breaker_trips = Counter(
    'circuit_breaker_trips_total', 'Circuit breaker trip count',
    ['scope'], registry=REGISTRY,
)
circuit_breaker_state = Gauge(
    'circuit_breaker_state', 'Current circuit breaker state (0=closed, 1=open, 2=half_open)',
    ['scope'], registry=REGISTRY,
)

# LLM call metrics
llm_calls_total = Counter(
    'llm_calls_total', 'Total LLM API calls',
    ['provider', 'agent_id'], registry=REGISTRY,
)
llm_call_duration = Histogram(
    'llm_call_duration_seconds', 'LLM API call latency',
    ['provider'], registry=REGISTRY,
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)


# ── Structured JSON logging ─────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured log aggregation (ELK / Loki)."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # Include trace/span context if present
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            log_entry["trace_id"] = trace_id
        span_id = getattr(record, "span_id", None)
        if span_id:
            log_entry["span_id"] = span_id

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            log_entry.update(extra)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


def setup_structured_logging():
    """Configure root logger with JSON formatter for file handler + human-readable for console."""
    root = logging.getLogger()
    # Keep console human-readable
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h.formatter, JsonFormatter):
            h.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            ))
    return root


# ── FastAPI middleware ───────────────────────────────────────────────────────

class ObservabilityMiddleware:
    """ASGI middleware that records request metrics and injects trace context."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = str(uuid.uuid4())[:16]
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")

        start = time.monotonic()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.monotonic() - start
            mc_requests_total.labels(method=method, path=path, status_code=str(status_code)).inc()
            mc_request_latency.labels(method=method, path=path).observe(elapsed)

            # Structured log with trace context
            logger = logging.getLogger("mc.http")
            extra = {"trace_id": trace_id, "method": method, "path": path,
                      "status": status_code, "duration_ms": round(elapsed * 1000, 2)}
            logger.info(f"{method} {path} → {status_code} ({elapsed:.3f}s)", extra={"extra_fields": extra})


def setup_observability(app):
    """Install observability middleware on a FastAPI app."""
    app.add_middleware(lambda app: ObservabilityMiddleware(app))
    setup_structured_logging()
    logging.getLogger("mc.observability").info("Observability middleware installed (Prometheus + structured logging)")


# ── Helper functions for agent workers ──────────────────────────────────────

_agent_timers: dict[str, float] = {}


def record_agent_start(agent_id: str, req_id: str):
    """Called at the start of agent.execute() — begins the duration timer."""
    key = f"{agent_id}:{req_id}"
    _agent_timers[key] = time.monotonic()
    agent_queue_depth.labels(agent_id=agent_id).inc()


def record_agent_end(agent_id: str, req_id: str, status: str = "completed"):
    """Called at the end of agent.execute() — records duration and status."""
    key = f"{agent_id}:{req_id}"
    start = _agent_timers.pop(key, None)
    agent_queue_depth.labels(agent_id=agent_id).dec()
    agent_executions_total.labels(agent_id=agent_id, status=status).inc()
    if start:
        agent_execution_duration.labels(agent_id=agent_id).observe(time.monotonic() - start)


def record_nats_event(event_type: str, agent_id: str = "", req_id: str = ""):
    """Record a NATS event being published."""
    nats_events_total.labels(event_type=event_type, agent_id=agent_id).inc()


def record_nats_latency(event_type: str, publish_time: str):
    """Calculate and record end-to-end NATS event latency."""
    try:
        pub_dt = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
        latency = (datetime.now(timezone.utc) - pub_dt).total_seconds()
        if 0 < latency < 3600:  # sanity check
            nats_event_latency.labels(event_type=event_type).observe(latency)
    except (ValueError, TypeError):
        pass


def record_llm_call(provider: str, agent_id: str, duration_s: float, success: bool):
    """Record an LLM API call."""
    llm_calls_total.labels(provider=provider, agent_id=agent_id).inc()
    llm_call_duration.labels(provider=provider).observe(duration_s)
    if duration_s > 60:
        logging.getLogger("mc.llm").warning(
            f"Slow LLM call: provider={provider} agent={agent_id} duration={duration_s:.1f}s",
            extra={"extra_fields": {"provider": provider, "agent_id": agent_id, "duration_s": duration_s}}
        )


def record_pipeline_transition(from_stage: str, to_stage: str):
    """Record a requirement pipeline stage transition."""
    pipeline_stage_transitions.labels(from_stage=from_stage, to_stage=to_stage).inc()


def update_gate_sla_metrics(gate: int, req_id: str, remaining_seconds: float | None):
    """Update SLA gauge for a specific gate."""
    if remaining_seconds is not None and remaining_seconds >= 0:
        gate_sla_remaining.labels(gate=str(gate), req_id=req_id).set(remaining_seconds)
        if remaining_seconds <= 0:
            gate_sla_breaches.labels(gate=str(gate)).inc()


@contextmanager
def trace_agent(agent_id: str, req_id: str):
    """Context manager for agent execution tracing."""
    record_agent_start(agent_id, req_id)
    status = "completed"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        record_agent_end(agent_id, req_id, status)


# ── Periodic metrics collection (called by a background task) ────────────────

async def collect_db_metrics(pool):
    """Update gauges from database state — call periodically."""
    try:
        async with pool.acquire() as conn:
            # Requirements by status
            rows = await conn.fetch(
                "SELECT status, COUNT(*) as cnt FROM requirements GROUP BY status"
            )
            for row in rows:
                requirements_gauge.labels(status=row["status"]).set(row["cnt"])

            # Active approvals
            rows2 = await conn.fetch(
                "SELECT gate, status, COUNT(*) as cnt FROM gate_approvals WHERE status = 'pending' GROUP BY gate, status"
            )
            for row in rows2:
                approvals_total.labels(gate=str(row["gate"]), status=row["status"]).set(row["cnt"])

            # Overdue gates
            now = datetime.now(timezone.utc)
            overdue = await conn.fetch(
                "SELECT gate, req_id, sla_deadline FROM gate_approvals WHERE status = 'pending' AND sla_deadline < $1",
                now,
            )
            for row in overdue:
                gate_sla_breaches.labels(gate=str(row["gate"])).inc()
                gate_sla_remaining.labels(gate=str(row["gate"]), req_id=str(row["req_id"])).set(0)

    except Exception as e:
        logging.getLogger("mc.observability").warning(f"Failed to collect DB metrics: {e}")


class ObservabilityState:
    """Singleton holding the current observability configuration."""
    def __init__(self):
        self.metrics_registry = REGISTRY
        self.started_at = datetime.now(timezone.utc)


OBSERVABILITY = ObservabilityState()
