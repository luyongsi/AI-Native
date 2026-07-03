"""
nats_temporal_bridge.py — Bridges NATS agent events to Temporal Signals.

Subscribes to agent.result.> and agent.status.changed.> via JetStream durable
consumer. Parses workflow_id from each message and signals the corresponding
Temporal Workflow.
"""
import asyncio
import json
import logging
import os
from typing import Optional

import nats

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")
TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "ai-native")

STREAM_NAME = "AI_NATIVE_EVENTS"
CONSUMER_NAME = "BRIDGE_CONSUMER"

_temporal_client = None


async def _get_temporal_client():
    global _temporal_client
    if _temporal_client is None:
        from temporalio.client import Client
        _temporal_client = await Client.connect(
            TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE
        )
        logger.info(f"Bridge connected to Temporal at {TEMPORAL_HOST} (ns={TEMPORAL_NAMESPACE})")
    return _temporal_client


async def start_nats_temporal_bridge(nc: nats.NATS):
    """Start the bridge: subscribe to agent result/status events via JetStream."""
    logger.info("=== NATS-Temporal Bridge starting ===")

    js = nc.jetstream()

    # Ensure stream exists
    try:
        await js.stream_info(STREAM_NAME)
    except Exception:
        logger.warning(f"Stream {STREAM_NAME} not found, creating...")
        await js.add_stream(
            name=STREAM_NAME,
            subjects=[
                "context.ready.>",
                "agent.result.>",
                "agent.status.changed.>",
                "orchestrator.>",
            ],
            retention="interest",
            storage="file",
        )

    try:
        await _get_temporal_client()
    except Exception as e:
        logger.warning(f"Temporal not available, bridge will retry: {e}")

    async def _handle_agent_result(msg):
        try:
            data = json.loads(msg.data.decode())
            agent_id = data.get("agent_id", "?")
            req_id = data.get("req_id", "")
            workflow_id = data.get("workflow_id", "")
            result = data.get("result", {})

            if not workflow_id and not req_id:
                logger.error("Bridge: message has no workflow_id or req_id, discarding")
                await msg.ack()
                return

            await _signal_workflow(agent_id, req_id, workflow_id, result, msg)
        except Exception as e:
            logger.error(f"Bridge: error handling agent.result: {e}", exc_info=True)
            await msg.nak()

    async def _handle_agent_status(msg):
        try:
            data = json.loads(msg.data.decode())
            agent_id = data.get("agent_id", "?")
            req_id = data.get("req_id", "")
            status = data.get("status", "")
            message = data.get("message", "")
            await _signal_workflow_status(agent_id, req_id, status, message, msg)
        except Exception as e:
            logger.error(f"Bridge: error handling agent.status: {e}", exc_info=True)
            await msg.ack()

    async def _signal_workflow(agent_id, req_id, workflow_id, result, msg):
        client = await _get_temporal_client()
        if client is None:
            await msg.nak()
            return

        try:
            if workflow_id:
                handle = client.get_workflow_handle(workflow_id)
                await handle.signal("agent_completed", args=[agent_id, result])
                logger.info(f"Bridge: signaled agent_completed({agent_id}) -> workflow={workflow_id}")
            else:
                logger.warning(f"Bridge: no workflow_id, searching by req_id={req_id[:20]}")
                found = False
                async for wf in client.list_workflows(
                    'WorkflowType="RequirementWorkflow" and ExecutionStatus="Running"'
                ):
                    if wf.id.startswith(f"req-{req_id[:8]}"):
                        handle = client.get_workflow_handle(wf.id)
                        await handle.signal("agent_completed", args=[agent_id, result])
                        logger.info(f"Bridge: signaled agent_completed({agent_id}) -> workflow={wf.id}")
                        found = True
                        break
                if not found:
                    logger.warning(f"Bridge: no running workflow found for req_id={req_id[:20]}")
            await msg.ack()
        except Exception as e:
            err = str(e)
            if "not found" in err.lower():
                logger.info(f"Bridge: workflow {workflow_id} not found (completed), discarding")
                await msg.ack()
            else:
                logger.error(f"Bridge: signal failed: {e}")
                await msg.nak()

    async def _signal_workflow_status(agent_id, req_id, status, message, msg):
        client = await _get_temporal_client()
        if client is None:
            await msg.ack()
            return

        try:
            async for wf in client.list_workflows(
                'WorkflowType="RequirementWorkflow" and ExecutionStatus="Running"'
            ):
                if req_id and req_id[:8] in wf.id:
                    handle = client.get_workflow_handle(wf.id)
                    await handle.signal("agent_status", args=[agent_id, status, message])
                    break
            await msg.ack()
        except Exception as e:
            await msg.ack()

    # Subscribe via JetStream durable consumer
    try:
        await js.subscribe(
            "agent.result.>",
            cb=_handle_agent_result,
            stream=STREAM_NAME,
            durable=CONSUMER_NAME,
        )
        logger.info("Bridge subscribed: agent.result.>")
    except Exception as e:
        logger.error(f"Bridge: failed to subscribe agent.result.>: {e}")

    try:
        await js.subscribe(
            "agent.status.changed.>",
            cb=_handle_agent_status,
            stream=STREAM_NAME,
            durable=f"{CONSUMER_NAME}_STATUS",
        )
        logger.info("Bridge subscribed: agent.status.changed.>")
    except Exception as e:
        logger.error(f"Bridge: failed to subscribe agent.status.changed.>: {e}")

    logger.info("=== NATS-Temporal Bridge running ===")
