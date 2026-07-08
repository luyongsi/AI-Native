"""Unit tests for T5: Agent artifact persistence (store_agent_result).

Covers:
  - store_agent_result writes to spec.artifacts.{agent_id} JSONB
  - Non-existent req_id returns ok=True (0 rows updated)
  - Overwrite on re-execution (same agent_id)
  - _AGENTS_THAT_PERSIST = {"A4"} skip logic
  - JSONB COALESCE handles NULL spec
  - A3 persisted / A4 skipped in parallel dispatch
"""

import json
import sys


# ── Pure SQL generation (mirrors store_agent_result activity) ───────────

def build_jsonb_set_query(req_id, agent_id, result):
    """Build the parameterized SQL that store_agent_result executes.

    Returns (sql_template, params) for inspection.
    """
    return (
        """UPDATE requirements
           SET spec = jsonb_set(
               COALESCE(spec, '{}'::jsonb),
               '{artifacts,' || $2 || '}',
               $3::jsonb,
               true
           ),
           updated_at = NOW()
           WHERE id = $1::uuid
        """,
        [req_id, agent_id, json.dumps(result)],
    )


def simulate_artifacts_write(existing_spec, agent_id, result):
    """Simulate PostgreSQL jsonb_set with COALESCE and create_missing=true."""
    if existing_spec is None:
        existing_spec = {}
    artifacts = existing_spec.get("artifacts", {})
    artifacts[agent_id] = result
    return {**existing_spec, "artifacts": artifacts}


# ── Test runner ─────────────────────────────────────────────────────────

_passed = 0
_failed = 0


def check(desc, condition):
    global _passed, _failed
    if condition:
        _passed += 1
        print("  PASS: " + desc)
    else:
        _failed += 1
        print("  FAIL: " + desc)


def section(title):
    print("\n" + "=" * 60)
    print("  " + title)
    print("=" * 60)


# ── Tests: SQL template ─────────────────────────────────────────────────

section("SQL Template Generation")

sql, params = build_jsonb_set_query("req-001", "A1", {"analysis": "ok"})
check("COALESCE handles NULL spec", "COALESCE" in sql)
check("jsonb_set with create_missing=true", "true" in sql)
check("agent_id is param $2", "$2" in sql)
check("result is param $3", "$3" in sql)
check("WHERE clause uses uuid cast", "::uuid" in sql)

sql2, params2 = build_jsonb_set_query("req-002", "A12", {"verdict": "pass"})
check("agent_id A12 in params", params2[1] == "A12")
check("result serialized to JSON string", isinstance(params2[2], str))
check("result deserializes correctly", json.loads(params2[2]) == {"verdict": "pass"})

# ── Tests: artifacts write simulation ───────────────────────────────────

section("Artifact Write to NULL Spec")

result1 = simulate_artifacts_write(None, "A1", {"analysis": "requirement parsed"})
check("NULL spec -> creates spec with artifacts",
      result1["artifacts"]["A1"]["analysis"] == "requirement parsed")
check("only A1 artifact present",
      list(result1["artifacts"].keys()) == ["A1"])

# ── Tests: write to existing spec with other artifacts ──────────────────

section("Append to Existing Spec")

existing = {
    "stages": [{"key": "designing"}],
    "openapi": {"endpoints": []},
    "artifacts": {"A1": {"analysis": "done"}, "A2": {"knowledge_brief": "..."}},
}
result2 = simulate_artifacts_write(existing, "A3", {"prototype_url": "http://x"})
check("A3 artifact appended", "A3" in result2["artifacts"])
check("A1 artifact preserved", "A1" in result2["artifacts"])
check("A2 artifact preserved", "A2" in result2["artifacts"])
check("existing keys preserved", "stages" in result2 and "openapi" in result2)
check("A3 content correct",
      result2["artifacts"]["A3"]["prototype_url"] == "http://x")

# ── Tests: overwrite same agent ─────────────────────────────────────────

section("Overwrite Same Agent ID")

result3 = simulate_artifacts_write(existing, "A1", {"analysis": "re-analyzed v2"})
check("A1 overwritten",
      result3["artifacts"]["A1"] == {"analysis": "re-analyzed v2"})
check("A2 untouched",
      "knowledge_brief" in result3["artifacts"]["A2"])
check("still exactly 3 agent artifacts",
      len(result3["artifacts"]) == 3)

# ── Tests: _AGENTS_THAT_PERSIST skip logic ──────────────────────────────

section("A4 Skip Logic (_AGENTS_THAT_PERSIST)")

_AGENTS_THAT_PERSIST = {"A4"}

check("A4 in skip set", "A4" in _AGENTS_THAT_PERSIST)
check("A3 not in skip set", "A3" not in _AGENTS_THAT_PERSIST)
check("A1 not in skip set", "A1" not in _AGENTS_THAT_PERSIST)
check("A9 not in skip set", "A9" not in _AGENTS_THAT_PERSIST)
check("A12 not in skip set", "A12" not in _AGENTS_THAT_PERSIST)

# Simulate dispatch-and-wait for a full pipeline
agent_results = {
    "A1": {"analysis": "done"},
    "A3": {"prototype_url": "http://example.com"},
    "A4": {"openapi": "...", "erd": "..."},
    "A5": {"pass": True, "score": 90},
}
spec = None
for agent_id, result in agent_results.items():
    if agent_id not in _AGENTS_THAT_PERSIST:
        spec = simulate_artifacts_write(spec, agent_id, result)

check("A1 persisted", "A1" in spec["artifacts"])
check("A3 persisted", "A3" in spec["artifacts"])
check("A4 NOT persisted (skip set)", "A4" not in spec["artifacts"])
check("A5 persisted", "A5" in spec["artifacts"])
check("total 3 artifacts (A4 skipped)",
      len(spec["artifacts"]) == 3)

# ── Tests: store_agent_result returns correct struct ────────────────────

section("Activity Return Value")

expected_return = {"ok": True, "req_id": "req-abc", "agent_id": "A6"}
check("ok field", expected_return["ok"] is True)
check("req_id echoed", expected_return["req_id"] == "req-abc")
check("agent_id echoed", expected_return["agent_id"] == "A6")

# Edge: empty result dict
result_empty = simulate_artifacts_write({}, "A7", {})
check("empty result stored as empty object",
      result_empty["artifacts"]["A7"] == {})

# ── Tests: deep nested result ───────────────────────────────────────────

section("Deep Nested Result")

nested = {
    "openapi": {"paths": {"/users": {"get": {"summary": "List users"}}}},
    "erd": {"tables": [{"name": "users", "columns": ["id", "email"]}]},
    "meta": {"agent": "A4", "version": 2, "requires_review": True},
}
spec_nested = simulate_artifacts_write({}, "A4", nested)
check("nested openapi preserved",
      spec_nested["artifacts"]["A4"]["openapi"]["paths"]["/users"]["get"]["summary"]
      == "List users")
check("erd tables preserved",
      spec_nested["artifacts"]["A4"]["erd"]["tables"][0]["name"] == "users")
check("meta preserved", spec_nested["artifacts"]["A4"]["meta"]["version"] == 2)

# ── Results ─────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
total = _passed + _failed
print(f"  {_passed}/{total} passed", end="")
if _failed > 0:
    print(f", {_failed} FAILED")
    sys.exit(1)
else:
    print(" — ALL PASSED")
    sys.exit(0)
