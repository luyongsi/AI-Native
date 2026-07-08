"""Runtime verifier — compares observed behavior against Truth Spec expectations.

All checks:
  1. check_upstream_visibility    — DB snapshot cross-check (modified: uses DB, not NATS context string)
  2. check_agent_output_fields    — hard constraints on agent output (error)
  3. check_data_quantity_constraints — soft constraints (warning)
  4. check_persistence_contracts  — DB writes match persistence_contracts (delayed)
  5. check_gate_progression_sync  — gate approval leads to correct next state
  6. check_flow_contracts_sync    — rework/inner_loop feedback present
  7. check_duplicate_dispatch_sync — same state not dispatched twice in N seconds
  8. check_gate_sla_sync          — gate wait time within SLA
  9. check_llm_audit_completeness — LLM call records present
  10. check_worktree_cleanup_sync  — no stale A9 worktrees
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class RuntimeVerifier:
    def __init__(self, truth_spec: dict, db_pool):
        self.spec = truth_spec
        self.db_pool = db_pool

    # ═══════════════════════════════════════════════════════════════
    # Check 1: Upstream data flow (DB-only cross-check)
    #
    # NATS dispatch payload only contains a context *string*, not
    # structured openapi_hint/erd_hint fields. We verify data flow by
    # comparing what's in the DB against what the Truth Spec says
    # should be there for the current state's upstream agents.
    # ═══════════════════════════════════════════════════════════════

    async def check_upstream_visibility(
        self, state: str, _context_package: dict, db_snapshot: dict
    ) -> list[dict]:
        """Verify: for the current state, all expected upstream agent
        data exists in the DB snapshot."""
        state_lower = state.lower()
        expected_upstream = (
            self.spec.get("data_flow", {}).get("upstream_artifacts", {}).get(state_lower, [])
        )
        context_map = self.spec.get("data_flow", {}).get("context_key_mapping", {})
        findings = []

        for agent in expected_upstream:
            mappings = context_map.get(agent, [])
            if not isinstance(mappings, list):
                mappings = [mappings]
            if not mappings:
                continue

            for mapping in mappings:
                source_path = mapping.get("source", "")  # e.g. "spec.openapi"
                db_data = _get_by_path(db_snapshot, source_path)
                db_has_data = db_data is not None and db_data != {} and db_data != []

                if not db_has_data:
                    findings.append({
                        "rule": "UPSTREAM_DATA_MISSING_IN_DB",
                        "severity": "warning",
                        "state": state,
                        "agent": agent,
                        "message": (
                            f"State {state}: expected upstream {agent} data at {source_path}, "
                            f"but DB has no data. Upstream {agent} may not have produced output yet."
                        ),
                        "db_snapshot": _safe_snapshot({source_path: db_data}),
                    })

        return findings

    # ═══════════════════════════════════════════════════════════════
    # Check 2 + 3: Agent output fields + quantity constraints
    # ═══════════════════════════════════════════════════════════════

    async def check_agent_output_fields(self, agent_id: str, output: dict) -> list[dict]:
        findings = []
        stubs = self.spec.get("agents", {}).get("stubs", [])
        if agent_id in stubs:
            if output.get("status") != "completed":
                findings.append({
                    "rule": "STUB_AGENT_NOT_COMPLETED",
                    "severity": "warning",
                    "agent": agent_id,
                    "message": f"Stub agent {agent_id} returned status={output.get('status')}",
                })
            return findings

        hard = self.spec.get("constraints", {}).get("hard", {})
        field_key = f"{agent_id.lower()}_output_required_fields"
        for path in hard.get(field_key, []):
            value = _get_by_path(output, path)
            if value is None or (isinstance(value, (list, dict, str)) and not value):
                findings.append({
                    "rule": "AGENT_OUTPUT_MISSING_REQUIRED_FIELD",
                    "severity": "error",
                    "agent": agent_id,
                    "message": f"{agent_id} output missing required field: {path}",
                })
        return findings

    async def check_data_quantity_constraints(self, agent_id: str, output: dict) -> list[dict]:
        findings = []
        soft = self.spec.get("constraints", {}).get("soft", {})
        if agent_id == "A4":
            actual = output.get("erd_tables", 0)
            min_tables = soft.get("a4_min_erd_tables", 1)
            if actual < min_tables:
                findings.append({
                    "rule": "A4_ERD_TABLE_COUNT_LOW",
                    "severity": "warning",
                    "message": f"A4 generated {actual} tables, expected >= {min_tables}.",
                })
        if agent_id == "A6":
            dag = output.get("dag", {})
            actual = len(dag.get("nodes", []))
            min_nodes = soft.get("a6_min_dag_nodes", 5)
            if actual < min_nodes:
                findings.append({
                    "rule": "A6_DAG_NODE_COUNT_LOW",
                    "severity": "warning",
                    "message": f"A6 generated {actual} DAG nodes, expected >= {min_nodes}.",
                })
        return findings

    # ═══════════════════════════════════════════════════════════════
    # Check 4: Persistence contracts (delayed — only at flow end)
    # ═══════════════════════════════════════════════════════════════

    async def check_persistence_contracts(self, agent_id: str, req_id: str) -> list[dict]:
        """Verify agent data is persisted in DB.
        Only called at flow end (not per-event) to avoid timing issues
        where store_agent_result hasn't run yet."""
        findings = []
        contracts = self.spec.get("data_flow", {}).get("persistence_contracts", {})
        agent_contracts = contracts.get(agent_id, [])
        default_contract = contracts.get("default", [])

        pool = self.db_pool

        for c in agent_contracts:
            target = c["target"]
            if target.startswith("spec."):
                field = target.split(".", 1)[1]
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT spec->>$1 as val FROM requirements WHERE id=$2::uuid",
                        field, req_id,
                    )
                if not row or not row["val"]:
                    findings.append({
                        "rule": "PERSISTENCE_CONTRACT_VIOLATED",
                        "severity": "error", "agent": agent_id,
                        "message": f"{agent_id} should have written {target}, but it is empty",
                    })
            elif target == "api_schemas":
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT COUNT(*) as c FROM api_schemas WHERE req_id=$1::uuid", req_id
                    )
                if not row or row["c"] == 0:
                    findings.append({
                        "rule": "PERSISTENCE_CONTRACT_VIOLATED",
                        "severity": "error", "agent": agent_id,
                        "message": f"{agent_id}: no record in api_schemas table",
                    })
            elif target == "erd_designs":
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT COUNT(*) as c FROM erd_designs WHERE req_id=$1::uuid", req_id
                    )
                if not row or row["c"] == 0:
                    findings.append({
                        "rule": "PERSISTENCE_CONTRACT_VIOLATED",
                        "severity": "error", "agent": agent_id,
                        "message": f"{agent_id}: no record in erd_designs table",
                    })

        if not agent_contracts and default_contract:
            for dc in default_contract:
                field = dc["target"].replace("{agent_id}", agent_id).split(".", 1)[1]
                # artifacts.X is a nested JSONB path, use #>> for chained access
                parts = field.split(".")
                if len(parts) == 2:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            f"SELECT spec#>>'{{{parts[0]},{parts[1]}}}' as val FROM requirements WHERE id=$1::uuid",
                            req_id,
                        )
                    if not row or not row["val"]:
                        findings.append({
                            "rule": "PERSISTENCE_CONTRACT_VIOLATED",
                            "severity": "warning", "agent": agent_id,
                            "message": f"{agent_id}: {field} is empty in DB",
                        })
                else:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT spec->>$1 as val FROM requirements WHERE id=$2::uuid",
                            field, req_id,
                        )
                    if not row or not row["val"]:
                        findings.append({
                            "rule": "PERSISTENCE_CONTRACT_VIOLATED",
                            "severity": "warning", "agent": agent_id,
                            "message": f"{agent_id}: {field} is empty in DB",
                        })
        return findings

    # ═══════════════════════════════════════════════════════════════
    # Check 5-10: Sync checks (called at flow end)
    # ═══════════════════════════════════════════════════════════════

    def check_gate_progression_sync(self, timeline: list[dict]) -> list[dict]:
        findings = []
        for gate in self.spec.get("gates", []):
            level = gate["level"]
            expected_next = gate.get("next_state", "").lower()
            approvals = [
                e for e in timeline
                if e.get("event_type") in ("gate_approved", "gate_auto_approved")
                and e.get("gate") == level
            ]
            for approval in approvals:
                idx = timeline.index(approval)
                changes = [
                    e for e in timeline[idx + 1:idx + 6]
                    if e.get("event_type") in ("state_changed", "state_transition")
                ]
                if changes:
                    actual = (changes[0].get("new_state") or changes[0].get("state") or "").lower()
                    if actual != expected_next:
                        findings.append({
                            "rule": "GATE_PROGRESSION_MISMATCH",
                            "severity": "error",
                            "message": f"Gate {level}: expected -> {expected_next}, actual -> {actual}",
                        })
                else:
                    findings.append({
                        "rule": "GATE_APPROVAL_NO_STATE_CHANGE",
                        "severity": "error",
                        "message": f"Gate {level} approved but no state change within 5 events",
                    })
        return findings

    def check_flow_contracts_sync(self, timeline: list[dict]) -> list[dict]:
        findings = []
        contracts = self.spec.get("flow_contracts", {})

        rework = contracts.get("rework", {})
        keyword = rework.get("expect_in_context", "")
        des_ctxs = [
            e for e in timeline
            if (e.get("state") or "").lower() == "designing"
            and e.get("event_type") == "context_built"
        ]
        if len(des_ctxs) >= 2 and keyword:
            last_ctx = json.dumps(des_ctxs[-1].get("data", {}).get("context_snapshot", {}))
            if keyword not in last_ctx:
                findings.append({
                    "rule": "REWORK_FEEDBACK_MISSING",
                    "severity": "error",
                    "message": f"Rework occurred but DESIGNING context missing {keyword}",
                })

        inner = contracts.get("inner_loop", {})
        keyword = inner.get("expect_in_context", "")
        dev_ctxs = [
            e for e in timeline
            if (e.get("state") or "").lower() == "developing"
            and e.get("event_type") == "context_built"
        ]
        if len(dev_ctxs) >= 2 and keyword:
            last_ctx = json.dumps(dev_ctxs[-1].get("data", {}).get("context_snapshot", {}))
            if keyword not in last_ctx:
                findings.append({
                    "rule": "INNER_LOOP_FEEDBACK_MISSING",
                    "severity": "error",
                    "message": f"Inner loop occurred but DEVELOPING context missing {keyword}",
                })
        return findings

    def check_duplicate_dispatch_sync(self, timeline: list[dict]) -> list[dict]:
        findings = []
        window = self.spec.get("additional_checks", {}).get("duplicate_dispatch_window_seconds", 300)
        seen: dict[str, str] = {}
        for e in timeline:
            if e.get("event_type") == "context_built":
                state = (e.get("state") or "").lower()
                ts = e.get("timestamp", "")
                if state and state in seen and ts and seen[state]:
                    try:
                        d = (datetime.fromisoformat(ts) - datetime.fromisoformat(seen[state])).total_seconds()
                        if d < window:
                            findings.append({
                                "rule": "DUPLICATE_DISPATCH",
                                "severity": "warning",
                                "message": f"State {state} dispatched twice within {d:.0f}s",
                            })
                    except Exception:
                        pass
                if state and ts:
                    seen[state] = ts
        return findings

    def check_gate_sla_sync(self, timeline: list[dict]) -> list[dict]:
        findings = []
        sla_config = self.spec.get("gate_sla", {})
        now = datetime.now(timezone.utc)
        for e in timeline:
            if e.get("event_type") == "gate_created":
                gate = e.get("gate", 0)
                key = f"gate_{gate}"
                sla_h = sla_config.get(key, {}).get("sla_hours", 4)
                approved = any(
                    a for a in timeline
                    if a.get("event_type") in ("gate_approved", "gate_auto_approved")
                    and a.get("gate") == gate
                )
                if not approved:
                    try:
                        ts = datetime.fromisoformat(e.get("timestamp", ""))
                        if (now - ts).total_seconds() / 3600 > sla_h:
                            findings.append({
                                "rule": "GATE_SLA_EXCEEDED",
                                "severity": "warning",
                                "message": f"Gate {gate} waiting > SLA ({sla_h}h)",
                            })
                    except Exception:
                        pass
        return findings

    async def check_llm_audit_completeness(self, agent_id: str, req_id: str) -> list[dict]:
        enabled = self.spec.get("additional_checks", {}).get("llm_audit_completeness", False)
        if not enabled:
            return []
        log_dir = Path("/opt/ai-native/logs/llm_calls") / req_id[:8]
        if log_dir.exists():
            has_calls = any(agent_id in f.name for f in log_dir.glob("*.json"))
            if not has_calls:
                return [{
                    "rule": "NO_LLM_AUDIT_RECORD",
                    "severity": "info",
                    "agent": agent_id,
                    "message": f"{agent_id}: no LLM call records in {log_dir}",
                }]
        return []

    def check_worktree_cleanup_sync(self) -> list[dict]:
        findings = []
        cfg = self.spec.get("additional_checks", {})
        path = Path(cfg.get("worktree_path", "/tmp/a9-runtimes"))
        max_age = cfg.get("worktree_max_age_minutes", 120)
        if path.exists():
            now = time.time()
            for d in path.iterdir():
                if d.is_dir() and (now - d.stat().st_mtime) / 60 > max_age:
                    findings.append({
                        "rule": "WORKTREE_LEAK",
                        "severity": "warning",
                        "message": f"Worktree {d.name} older than {max_age}min, possible leak",
                    })
        return findings


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _get_by_path(obj: dict, path: str):
    if not path:
        return None
    current = obj
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _safe_snapshot(obj, depth=3, max_str=500):
    if depth <= 0:
        return "..."
    if isinstance(obj, dict):
        return {k: _safe_snapshot(v, depth - 1, max_str) for k, v in list(obj.items())[:20]}
    if isinstance(obj, list):
        return [_safe_snapshot(v, depth - 1, max_str) for v in obj[:10]]
    if isinstance(obj, str) and len(obj) > max_str:
        return obj[:max_str] + "..."
    return obj
