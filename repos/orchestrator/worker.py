"""Temporal Worker entry point for the Orchestrator (spec-12).

Usage:
    python3 worker.py

Starts a Temporal worker listening on the orchestrator task queue.
Includes OpenTelemetry tracing initialization.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

# Ensure the orchestrator package is importable.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

# Initialize OpenTelemetry tracing
try:
    from infra.observability.otel_config import init_tracer
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False
    def init_tracer(name, **kwargs):
        return None

# -- Import workflow and activity definitions for registration ---------
from workflows.requirement_workflow import RequirementWorkflow
from workflows.fast_channel_workflow import FastChannelWorkflow
from workflows.dag_dispatcher import DispatchParallelWorkflow

from activities.dispatch_agent import dispatch_agent
from activities.gate_await import create_gate_approval
from activities.context_build import build_context
from activities.notify_mc import notify_mc
from activities.complexity_classifier import complexity_classifier

# ── Config ────────────────────────────────────────────────────────────
TASK_QUEUE = os.environ.get("TEMPORAL_TASK_QUEUE", "orchestrator-task-queue")
TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "ai-native")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")


async def main() -> None:
    """Connect to Temporal and start the worker."""
    logger.info("Connecting to Temporal at %s (ns=%s)", TEMPORAL_HOST, TEMPORAL_NAMESPACE)

    # Initialize OpenTelemetry tracing
    if _HAS_OTEL:
        try:
            init_tracer("orchestrator", environment=os.environ.get("ENVIRONMENT", "dev"))
            logger.info("OpenTelemetry tracer initialized for orchestrator")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenTelemetry: {e}")

    client = await Client.connect(
        TEMPORAL_HOST,
        namespace=TEMPORAL_NAMESPACE,
    )

    _workflows = [
        RequirementWorkflow,
        FastChannelWorkflow,
        DispatchParallelWorkflow,
    ]
    _activities = [
        dispatch_agent,
        create_gate_approval,
        build_context,
        notify_mc,
        complexity_classifier,
    ]

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=_workflows,
        activities=_activities,
    )

    print(f"Temporal Worker started on task queue: {TASK_QUEUE}")
    print(f"  Namespace : {TEMPORAL_NAMESPACE}")
    print(f"  Host      : {TEMPORAL_HOST}")
    print(f"  Workflows : {len(_workflows)} registered")
    for wf in _workflows:
        print(f"    - {getattr(wf, '__temporal_workflow_name', wf.__name__)}")
    print(f"  Activities: {len(_activities)} registered")
    for act in _activities:
        print(f"    - {getattr(act, '__temporal_activity_definition', act.__name__)}")
    print()
    logger.info("Worker running. Press Ctrl+C to stop.")

    try:
        await worker.run()
    except asyncio.CancelledError:
        logger.info("Worker cancelled.")
    finally:
        logger.info("Worker shut down.")


if __name__ == "__main__":
    asyncio.run(main())
