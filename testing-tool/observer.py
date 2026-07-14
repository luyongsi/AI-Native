"""PipelineObserver — three-channel observation engine.

Channels:
  1. NATS subscription  — context.ready.> and agent.result.>
  2. DB polling          — requirements table every 3s
  3. Temporal queries    — get_progress every 5s

Also handles auto gate approval and delayed cleanup on completion.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
import nats

from checks.runtime_verifier import RuntimeVerifier
from cleanup import full_test_cleanup

logger = logging.getLogger(__name__)


class PipelineObserver:
    def __init__(
        self,
        req_id: str,
        workflow_id: str,
        gate_strategy: str,  # "auto" | "manual"
        truth_spec: dict,
        db_pool,
        temporal_client,
        keep_data: bool = False,
        event_callback=None,  # async callable for SSE push
    ):
        self.req_id = req_id
        self.workflow_id = workflow_id
        self.gate_strategy = gate_strategy
        self.spec = truth_spec
        self.db_pool = db_pool
        self.temporal_client = temporal_client
        self._keep_data = keep_data
        self._event_callback = event_callback

        self.verifier = RuntimeVerifier(truth_spec, db_pool)
        self.timeline: list[dict] = []
        self.findings: list[dict] = []
        self._current_state = "DRAFT"
        self._stop = asyncio.Event()
        self._started_at: datetime | None = None

    async def run(self) -> dict:
        self._started_at = datetime.now(timezone.utc)
        self._append_event("workflow_started", state="DRAFT",
                           data={"workflow_id": self.workflow_id, "req_id": self.req_id})
        await self._emit("run-start", {"run_id": self._run_id, "req_id": self.req_id,
                                       "workflow_id": self.workflow_id})

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._listen_nats())
                tg.create_task(self._poll_db())
                tg.create_task(self._poll_temporal())
                if self.gate_strategy == "auto":
                    tg.create_task(self._auto_approve_gates())
                tg.create_task(self._watchdog())
        except* Exception as eg:
            logger.error(f"Observer task group error: {eg}")

        finally:
            # Delayed cleanup: wait for NATS ack window to close
            try:
                if not self._keep_data:
                    logger.info("Waiting 300s for NATS ack window before DB cleanup...")
                    for _ in range(60):  # 60 * 5s = 300s
                        if self._stop.is_set():
                            break
                        await asyncio.sleep(5)
                    logger.info("Delay complete, starting cleanup...")

                cleanup_report = await full_test_cleanup(
                    db_pool=self.db_pool,
                    temporal_client=self.temporal_client,
                    req_id=self.req_id,
                    workflow_id=self.workflow_id,
                    keep_data=self._keep_data,
                )
                self._append_event("cleanup_completed", data=cleanup_report)
                await self._emit("cleanup", cleanup_report)
            except Exception as e:
                logger.error(f"Cleanup failed: {e}", exc_info=True)

        result = self._build_result()
        await self._emit("run-complete", {
            "run_id": self._run_id,
            "final_state": self._current_state,
            "total_duration_s": result["total_duration_s"],
            "findings_count": len(self.findings),
        })
        return result

    @property
    def _run_id(self) -> str:
        if self._started_at:
            return f"run-{self._started_at.strftime('%Y%m%d-%H%M%S')}"
        return f"run-{uuid.uuid4().hex[:8]}"

    # ── Channel 1: NATS ──

    async def _listen_nats(self):
        try:
            nc = await nats.connect("nats://localhost:4222")
            js = nc.jetstream()

            async def on_context_ready(msg):
                try:
                    data = json.loads(msg.data.decode())
                    payload = data.get("payload", {})
                    if payload.get("req_id") != self.req_id:
                        return
                    state = payload.get("state", "")
                    agent = payload.get("agent_id", "")

                    # Extract raw context string — agents receive it as "context" field
                    raw_context = payload.get("context", "")
                    # Parse structured sections from the context string
                    structured = _parse_context_string(raw_context)
                    # Store both raw and structured for frontend display
                    context_snapshot = {
                        "req_id": payload.get("req_id", ""),
                        "state": payload.get("state", ""),
                        "agent_id": payload.get("agent_id", ""),
                        "workflow_id": payload.get("workflow_id", ""),
                        "title": payload.get("title", ""),
                        "raw_context": raw_context,
                        "structured": structured,
                        "rework_context": payload.get("rework_context", {}),
                        "requirement_draft": payload.get("requirement_draft", {}),
                    }
                    db_snap = await self._snapshot_db()
                    self._append_event("context_built", state=state, agent=agent,
                                       data={"context_snapshot": context_snapshot, "db_snapshot": db_snap})

                    # Verify upstream visibility against DB snapshot
                    f1 = await self.verifier.check_upstream_visibility(state, {}, db_snap)
                    self._add_findings(f1)

                    logger.info(f"Captured context_built: state={state} agent={agent}")
                    await self._emit("checkpoint", {
                        "event_type": "context_built", "state": state, "agent": agent,
                        "context_snapshot": context_snapshot,
                    })
                except Exception as e:
                    logger.error(f"Error in context_ready handler: {e}", exc_info=True)
                finally:
                    try:
                        await msg.ack()
                    except Exception:
                        pass

            async def on_agent_result(msg):
                try:
                    data = json.loads(msg.data.decode())
                    if data.get("req_id") != self.req_id:
                        return
                    agent = data.get("agent_id", "")
                    result = data.get("result", {})

                    self._append_event("agent_completed", state=self._current_state,
                                       agent=agent, data={"result": result})

                    f2 = await self.verifier.check_agent_output_fields(agent, result)
                    f3 = await self.verifier.check_data_quantity_constraints(agent, result)
                    f4 = await self.verifier.check_persistence_contracts(agent, self.req_id)
                    f5 = await self.verifier.check_llm_audit_completeness(agent, self.req_id)
                    self._add_findings(f2 + f3 + f4 + f5)

                    await self._emit("checkpoint", {
                        "event_type": "agent_completed", "state": self._current_state,
                        "agent": agent,
                    })
                except Exception as e:
                    logger.error(f"Error in agent_result handler: {e}")
                finally:
                    try:
                        await msg.ack()
                    except Exception:
                        pass

            await js.subscribe("context.ready.>", cb=on_context_ready,
                               stream="AI_NATIVE_EVENTS", durable="observer_context_ready")
            await js.subscribe("agent.result.>", cb=on_agent_result,
                               stream="AI_NATIVE_EVENTS", durable="observer_agent_result")
            logger.info("NATS listeners active on context.ready.> and agent.result.>")
            await self._stop.wait()
            await nc.close()
        except Exception as e:
            logger.error(f"NATS listener failed: {e}")

    # ── Channel 2: DB polling ──

    async def _poll_db(self):
        while not self._stop.is_set():
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT status, spec, current_gate FROM requirements WHERE id=$1::uuid",
                        self.req_id,
                    )
                if row:
                    new_state = row["status"]
                    if new_state and new_state != self._current_state:
                        old = self._current_state
                        self._current_state = new_state
                        spec = row["spec"]
                        if isinstance(spec, str):
                            try:
                                spec = json.loads(spec)
                            except Exception:
                                spec = {}
                        self._append_event("state_transition", state=new_state,
                                           data={"from": old, "to": new_state,
                                                 "db_snapshot": _flatten_spec(spec)})
                        await self._emit("state-change", {"from": old, "to": new_state})
            except Exception as e:
                logger.debug(f"DB poll error (non-fatal): {e}")
            await asyncio.sleep(3)

    # ── Channel 3: Temporal ──

    async def _poll_temporal(self):
        if not self.temporal_client:
            return
        while not self._stop.is_set():
            try:
                handle = self.temporal_client.get_workflow_handle(self.workflow_id)
                progress = await handle.query("get_progress")
                self._append_event("temporal_heartbeat", data=progress)
                wf_state = progress.get("state", "")
                if wf_state in ("done", "blocked"):
                    if wf_state != self._current_state:
                        self._current_state = wf_state
                    self._stop.set()
            except Exception:
                pass
            await asyncio.sleep(5)

    # ── Gate auto-approval ──

    async def _auto_approve_gates(self):
        while not self._stop.is_set():
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT id, gate FROM gate_approvals "
                        "WHERE req_id=$1::uuid AND status='pending' ORDER BY gate LIMIT 1",
                        self.req_id,
                    )
                if row:
                    async with httpx.AsyncClient(timeout=15) as http:
                        resp = await http.post(
                            f"http://localhost:8000/api/approvals/{row['id']}/approve"
                        )
                    if resp.status_code < 400:
                        self._append_event("gate_auto_approved", gate=row["gate"],
                                           data={"gate_id": str(row["id"])})
                        await self._emit("gate-approved", {"gate": row["gate"]})
                        logger.info(f"Auto-approved Gate {row['gate']}")
            except Exception:
                pass
            await asyncio.sleep(5)

    # ── Watchdog ──

    async def _watchdog(self):
        # Default 2h timeout, overridden by spec if available
        timeout_config = self.spec.get("timeout_expectations", {})
        total = sum(
            c.get("max_seconds", 3600)
            for c in timeout_config.values()
            if isinstance(c, dict)
        )
        limit = min(total, 18000)  # cap at 5h
        if limit < 3600:
            limit = 3600
        logger.info(f"Watchdog set to {limit}s")
        for _ in range(limit // 5):
            if self._stop.is_set():
                return
            await asyncio.sleep(5)
        if not self._stop.is_set():
            self._append_event("workflow_timeout", data={"limit_s": limit})
            self._stop.set()

    # ── Helpers ──

    def _append_event(self, event_type: str, **kwargs):
        event = {
            "seq": len(self.timeline) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **kwargs,
        }
        self.timeline.append(event)

    def _add_findings(self, findings: list[dict]):
        for f in findings:
            self.findings.append(f)
            asyncio.create_task(self._emit("finding", f))

    async def _snapshot_db(self) -> dict:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT title, status, spec->'openapi' as openapi, "
                    "spec->'erd' as erd, spec->'artifacts' as artifacts "
                    "FROM requirements WHERE id=$1::uuid", self.req_id
                )
            if row:
                return {
                    "title": row["title"],
                    "status": row["status"],
                    "spec": {
                        "openapi": _parse_json(row["openapi"]),
                        "erd": _parse_json(row["erd"]),
                        "artifacts": _parse_json(row["artifacts"]),
                    },
                }
        except Exception:
            pass
        return {}

    async def _emit(self, event: str, data: dict):
        if self._event_callback:
            try:
                await self._event_callback(event, data)
            except Exception:
                pass

    def _build_result(self) -> dict:
        # Final checks
        self._add_findings(self.verifier.check_gate_progression_sync(self.timeline))
        self._add_findings(self.verifier.check_flow_contracts_sync(self.timeline))
        self._add_findings(self.verifier.check_duplicate_dispatch_sync(self.timeline))
        self._add_findings(self.verifier.check_gate_sla_sync(self.timeline))
        self._add_findings(self.verifier.check_worktree_cleanup_sync())

        finished = datetime.now(timezone.utc)
        return {
            "run_id": self._run_id,
            "req_id": self.req_id,
            "workflow_id": self.workflow_id,
            "title": "",
            "started_at": self._started_at.isoformat() if self._started_at else "",
            "finished_at": finished.isoformat(),
            "final_state": self._current_state,
            "total_duration_s": (
                (finished - self._started_at).total_seconds()
                if self._started_at else 0
            ),
            "gate_strategy": self.gate_strategy,
            "timeline": self.timeline,
            "findings": self.findings,
        }


def _flatten_spec(spec) -> dict:
    if spec is None:
        return {}
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except Exception:
            return {}
    if not isinstance(spec, dict):
        return {}
    return {
        "openapi": spec.get("openapi", {}),
        "erd": spec.get("erd", {}),
        "artifacts": spec.get("artifacts", {}),
    }


def _parse_context_string(raw: str) -> dict:
    """Parse the build_context output string into structured sections.
    The context is a YAML-like text with section markers like:
      [REQUIREMENT] ... [/REQUIREMENT]
      [ARTIFACT_CONTEXT] ... [/ARTIFACT_CONTEXT]
    """
    import re
    result = {}
    if not raw:
        return result

    # Try to extract sections delimited by headings or markers
    # build_context builds 6 layers with keys like:
    # requirement_context, artifact_context, knowledge_context, etc.
    sections = re.split(r'\n(?=(?:[A-Z_ ]{3,}:|\[|#{1,3} )|\n(?:requirement_context|artifact_context|knowledge_context|environment_context|decisions_context|rework_context|title|spec_sections|openapi_hint|erd_hint|dag_hint|constraints|note)\s*[:=])', raw)
    current_key = "_preamble"
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Extract key if present
        m = re.match(r'^([a-z_]+)\s*[:\n]', section)
        if m:
            current_key = m.group(1)
            result[current_key] = section[len(m.group(0)):].strip()
        else:
            result[current_key] = (result.get(current_key, "") + "\n" + section).strip()

    return result


def _parse_json(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}
