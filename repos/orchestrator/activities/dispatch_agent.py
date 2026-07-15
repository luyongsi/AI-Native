"""dispatch_agent Activity — publish context.ready to NATS Event Bus.

Dispatches to a specific agent_id with workflow_id for precise routing.
State-to-agent mapping is validated before dispatch.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import nats
from temporalio import activity

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")
_CONTEXT_MAX_CHARS = int(os.environ.get("DISPATCH_CONTEXT_MAX_CHARS", "65536"))

_nc: nats.NATS | None = None
_connect_lock = asyncio.Lock()

# State → expected agent mapping (for validation)
_STATE_AGENT_MAP: dict[str, str | None] = {
    "analyzing": "A1",
    "designing": None,       # A3 + A4 in parallel
    "reviewing": "A5",
    "decomposing": "A6",
    "developing": "A9",
    "testing": "A11",
    "code_review": "A12",
    "releasing": "A13",
    "draft": "A1",
}


async def _get_nats() -> nats.NATS:
    global _nc
    if _nc is None or not _nc.is_connected:
        async with _connect_lock:
            if _nc is None or not _nc.is_connected:
                _nc = await nats.connect(NATS_URL)
                logger.info(f"dispatch_agent: connected to NATS at {NATS_URL}")
    return _nc


def _truncate_context(context: str, max_chars: int = 65536) -> str:
    """Truncate context at max_chars, breaking at the nearest paragraph boundary."""
    if len(context) <= max_chars:
        return context
    search_start = int(max_chars * 0.9)
    break_pos = context.rfind("\n\n", search_start, max_chars)
    if break_pos > search_start:
        return context[:break_pos] + "\n\n[truncated — remaining items in _refs]"
    return context[:max_chars] + "\n[truncated]"


@activity.defn(name="dispatch_agent")
async def dispatch_agent(
    req_id: str,
    state: str,
    agent_id: str,
    workflow_id: str,
    context: str = "",
    rework_context: dict | None = None,
    ctx_meta: dict | None = None,
) -> dict:
    """Publish a dispatch message to NATS, targeting a specific agent.

    Args:
        req_id: Requirement UUID.
        state: Current pipeline state (e.g. "analyzing", "designing").
        agent_id: Target agent ID (e.g. "A1", "A3", "A4").
        workflow_id: Temporal workflow ID for Bridge routing.
        context: Serialized context string from build_context.
        rework_context: Rework feedback dict (injected into payload for Agents).
        ctx_meta: Context metadata from build_context (requirement_context, spec_sections, etc.).

    Returns:
        dict with ok, dispatched_at, agent_id, nats_subject.
    """
    ctx_meta = ctx_meta or {}
    activity.logger.info(
        "dispatch_agent req=%s state=%s agent=%s wf=%s",
        req_id, state, agent_id, workflow_id,
    )

    # Validate state → agent mapping
    expected = _STATE_AGENT_MAP.get(state)
    if expected is not None and agent_id != expected:
        activity.logger.warning(
            "dispatch_agent: state '%s' expected agent '%s', got '%s' — continuing anyway",
            state, expected, agent_id,
        )

    # Map agent_id to NATS subject suffix (must match agent_type in each agent class)
    # Phase3 agents (A6/A7/A8) use agent_id as subject suffix (context.ready.A6/A7/A8)
    _AGENT_TYPE_MAP = {
        "A1": "requirement_intake",
        "A2": "knowledge_analyst",
        "A3": "ui_generator",
        "A4": "spec_writer",
        "A5": "design_review",
        "A6": "A6",           # Phase3: context.ready.A6
        "A7": "A7",           # Phase3: context.ready.A7
        "A8": "A8",           # Phase3: context.ready.A8
        "A9": "dev_agent",
        "A10": "ci_cd",
        "A11": "test_agent",
        "A12": "code_review",
        "A13": "release",
        "K14": "knowledge_keeper",
        "K15": "change_propagation",
        "FC": "fast_channel",
    }
    agent_type = _AGENT_TYPE_MAP.get(agent_id, agent_id.lower())
    event_type = f"context.ready.{agent_type}"

    # Extract requirement fields for Agent direct access
    req_ctx = ctx_meta.get("requirement_context", {})

    # Build payload based on agent_id — Phase3 agents get structured context
    if agent_id in ("A6", "A7", "A8"):
        # Phase3 structured context package (per data dictionary)
        payload_data = _build_phase3_payload(req_id, agent_id, ctx_meta, rework_context)
    else:
        payload_data = {
            "req_id": req_id,
            "state": state,
            "agent_id": agent_id,
            "context": _truncate_context(context, _CONTEXT_MAX_CHARS),
            "workflow_id": workflow_id,
            "rework_context": rework_context or {},
            "requirement_draft": req_ctx,
            "title": req_ctx.get("title", ""),
            "description": req_ctx.get("description", ""),
            "spec_sections": ctx_meta.get("spec_sections", []),
        }

    envelope = {
        "event_id": f"dispatch-{req_id}-{state}-{agent_id}",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload_data,
        "req_id": req_id,
    }

    result: dict = {
        "ok": True,
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "state": state,
        "workflow_id": workflow_id,
    }

    try:
        nc = await _get_nats()
        js = nc.jetstream()
        await js.publish(
            event_type,
            json.dumps(envelope, ensure_ascii=False).encode(),
            headers={"Nats-Msg-Id": envelope["event_id"]},
        )
        result["note"] = f"Published to NATS subject '{event_type}'"
        result["nats_subject"] = event_type
        activity.logger.info(
            "dispatch_agent: published to '%s' req=%s agent=%s",
            event_type, req_id, agent_id,
        )
    except Exception as e:
        activity.logger.error("dispatch_agent: NATS publish failed: %s", e)
        result["ok"] = False
        result["note"] = f"NATS publish failed: {e}"

    return result


def _build_phase3_payload(req_id: str, agent_id: str,
                          ctx_meta: dict, rework_context: dict | None) -> dict:
    """Build structured context payload for Phase3 agents (A6/A7/A8).

    Each agent gets a tailored context package per data dictionary.
    """
    rework = rework_context or {}
    artifact_ctx = ctx_meta.get("artifact_context", {})
    spec_sections = ctx_meta.get("spec_sections", [])

    # Common spec_package extraction
    a4 = artifact_ctx.get("A4", {})
    spec_package = {
        "spec_doc": {
            "modules": a4.get("modules", []),
            "states": a4.get("states", []),
            "sections": spec_sections,
        },
        "openapi_schema": a4.get("openapi", {}),
        "erd_diagram": a4.get("erd", {}),
        "ddl_statements": a4.get("ddl", ""),
    }

    # Common fields
    base = {
        "req_id": req_id,
        "session_id": ctx_meta.get("session_id", ""),
        "cycle": ctx_meta.get("cycle", 0),
        "spec_package": spec_package,
        "revision_context": {
            "is_revision": rework.get("is_revision", False),
            "tech_prep_revision_count": rework.get("tech_prep_revision_count", 0),
            "gate2_rejection": rework.get("gate2_rejection"),
            "previous_a8_report": rework.get("previous_a8_report"),
        },
    }

    if agent_id == "A6":
        # A6 context: spec_package + revision_context
        return base

    elif agent_id == "A7":
        # A7 context: spec_package + dag_preview + revision_context
        a6_artifact = artifact_ctx.get("A6", {})
        dag_nodes = (a6_artifact.get("dag", {}) or {}).get("nodes", [])
        dag_available = bool(dag_nodes) and rework.get("is_revision", False) is not True

        return {
            **base,
            "dag_preview": {
                "nodes": dag_nodes,
                "node_count": len(dag_nodes),
                "dag_available": dag_available,
            },
        }

    elif agent_id == "A8":
        # A8 context: dag + spec_package (for LLM review)
        a6_artifact = artifact_ctx.get("A6", {})
        dag = a6_artifact.get("dag", {})

        return {
            **base,
            "dag": dag,
        }

    return base
