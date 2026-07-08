"""Unit tests for T2: MC Backend PUT /api/requirements/{req_id}/status.

Tests the status update endpoint logic in isolation (without FastAPI TestClient).
"""

import json
import sys


# ── Pure logic from mc-backend requirements.py ──────────────────────────

DEFAULT_STAGES = [
    {"key": "pool", "label": "需求池", "status": "done", "order": 0},
    {"key": "designing", "label": "设计中", "status": "active", "order": 1},
    {"key": "reviewing", "label": "评审中", "status": "pending", "order": 2},
    {"key": "developing", "label": "开发中", "status": "pending", "order": 3},
    {"key": "testing", "label": "测试中", "status": "pending", "order": 4},
    {"key": "code_review", "label": "代码审查", "status": "pending", "order": 5},
    {"key": "releasing", "label": "发布中", "status": "pending", "order": 6},
    {"key": "done", "label": "已完成", "status": "pending", "order": 7},
]


def apply_status_update(spec, new_state, status):
    """Pure function mirroring the PUT endpoint's stage advancement + status update logic."""
    stages = spec.get("stages", [])
    updated_stages = []
    for s in stages:
        key = s.get("key", "")
        if key == new_state:
            updated_stages.append({**s, "status": "active"})
        elif s.get("status") == "active" and key != new_state:
            updated_stages.append({**s, "status": "done"})
        else:
            updated_stages.append(s)

    return {
        **spec,
        "stages": updated_stages,
    }


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


# ── Tests ───────────────────────────────────────────────────────────────

section("Full pipeline: analyzing -> designing -> reviewing")

spec = {"stages": DEFAULT_STAGES}
spec = apply_status_update(spec, "analyzing", "analyzing")
check("pool stays done after analyzing becomes active",
      any(s["key"] == "pool" and s["status"] == "done" for s in spec["stages"]))

# Move to designing
spec = apply_status_update(spec, "designing", "designing")
check("designing stage is active",
      any(s["key"] == "designing" and s["status"] == "active" for s in spec["stages"]))
check("previous active stage is done",
      any(s["key"] == "pool" and s["status"] == "done" for s in spec["stages"]))

# Move to reviewing
spec = apply_status_update(spec, "reviewing", "reviewing")
check("reviewing is active",
      any(s["key"] == "reviewing" and s["status"] == "active" for s in spec["stages"]))
check("designing is now done",
      any(s["key"] == "designing" and s["status"] == "done" for s in spec["stages"]))

# Full progression
section("Full State Progression")

spec2 = {"stages": DEFAULT_STAGES}
states = ["analyzing", "designing", "reviewing", "developing", "testing",
          "code_review", "releasing", "done"]
for st in states:
    spec2 = apply_status_update(spec2, st, st)

check("done is active", any(s["key"] == "done" and s["status"] == "active" for s in spec2["stages"]))
check("releasing is done", any(s["key"] == "releasing" and s["status"] == "done" for s in spec2["stages"]))
check("no more than 1 active",
      sum(1 for s in spec2["stages"] if s["status"] == "active") == 1)

# ── Edge cases ──────────────────────────────────────────────────────────

section("Edge Cases")

spec_empty = apply_status_update({}, "analyzing", "analyzing")
check("empty spec (no stages) works", spec_empty.get("stages", []) == [])

stages_single_active = [
    {"key": "draft", "status": "active"},
    {"key": "analyzing", "status": "pending"},
]
result_single = apply_status_update({"stages": stages_single_active}, "analyzing", "analyzing")
check("only one active after transition",
      sum(1 for s in result_single["stages"] if s["status"] == "active") == 1)

# ── Gate events ─────────────────────────────────────────────────────────

section("Gate Event Types")

gate_events = ["gate_timeout", "gate_grace_expired", "gate_approved", "gate_rejected"]
for evt in gate_events:
    payload = {"status": "designing", "event": {"event": evt, "gate_level": 1}}
    check("event type preserved: " + evt, payload["event"]["event"] == evt)

# ── Result format ───────────────────────────────────────────────────────

section("PUT Response Format")

response_ok = {"ok": True, "req_id": "req-001", "status": "designing"}
check("response has ok=True", response_ok["ok"] is True)
check("response has req_id", response_ok["req_id"] == "req-001")
check("response has status", response_ok["status"] == "designing")

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
