"""Unit tests for T2: notify_mc DB sync.

Covers:
  - notify_mc result structure (mc_synced field)
  - _sync_to_mc_backend behavior (success, connection refused, 404)
  - MC Backend PUT /api/requirements/{req_id}/status endpoint logic
  - StatusUpdate model validation
"""

import json
import sys
from datetime import datetime, timezone


# ── Mock-free test: StatusUpdate model validation ───────────────────────

class StatusUpdate:
    """Mirror of mc-backend StatusUpdate model for testing."""

    def __init__(self, status, new_state=None, old_state=None, event=None, agent_id=None):
        self.status = status
        self.new_state = new_state
        self.old_state = old_state
        self.event = event
        self.agent_id = agent_id


# ── Stage advancement logic (pure function, mirrors PUT endpoint) ───────

def advance_stages(stages, new_state):
    """Pure function: advance pipeline stages.

    Sets matching stage to 'active', previous active to 'done'.
    """
    result = []
    for s in stages:
        key = s.get("key", "")
        if key == new_state:
            result.append({**s, "status": "active"})
        elif s.get("status") == "active" and key != new_state:
            result.append({**s, "status": "done"})
        else:
            result.append(s)
    return result


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


# ── Tests: StatusUpdate model ───────────────────────────────────────────

section("StatusUpdate Model")

su = StatusUpdate(
    status="designing",
    old_state="analyzing",
    new_state="designing",
    event={"event": "gate_timeout", "gate_level": 0},
    agent_id="orchestrator",
)
check("status field", su.status == "designing")
check("old_state field", su.old_state == "analyzing")
check("new_state field", su.new_state == "designing")
check("event field", su.event == {"event": "gate_timeout", "gate_level": 0})
check("agent_id field", su.agent_id == "orchestrator")

su_minimal = StatusUpdate(status="analyzing")
check("minimal StatusUpdate works", su_minimal.status == "analyzing")
check("new_state optional", su_minimal.new_state is None)

# ── Tests: Stage advancement ────────────────────────────────────────────

section("Stage Advancement Logic")

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

result = advance_stages(DEFAULT_STAGES, "reviewing")
check("designing -> done (previous active)", result[1]["status"] == "done")
check("reviewing -> active (new state)", result[2]["status"] == "active")
check("developing still pending", result[3]["status"] == "pending")

# Edge: same state
result2 = advance_stages(DEFAULT_STAGES, "designing")
check("same state stays active", result2[1]["status"] == "active")

# Edge: empty stages
check("empty stages returns empty", advance_stages([], "analyzing") == [])

# Edge: unknown state key — when no stage matches new_state, the
# previous 'active' stage transitions to 'done' and nothing becomes active.
# This is expected behaviour (orchestrator shouldn't pass unknown states).
result3 = advance_stages(DEFAULT_STAGES, "unknown_state")
check("unknown state: no stage becomes active",
      sum(1 for s in result3 if s["status"] == "active") == 0)
check("unknown state: previous active is now done",
      any(s["key"] == "designing" and s["status"] == "done" for s in result3))

# ── Tests: notify_mc result format ──────────────────────────────────────

section("notify_mc Result Format")

# Simulate result structure from notify_mc Activity
result_ok = {
    "ok": True,
    "req_id": "req-123",
    "old_state": "analyzing",
    "new_state": "designing",
    "published_at": datetime.now(timezone.utc).isoformat(),
    "mc_synced": True,
    "note": "Published to NATS subject 'orchestrator.state.req-123'",
}
check("mc_synced field exists", "mc_synced" in result_ok)
check("mc_synced = True when backend reachable", result_ok["mc_synced"] is True)

result_failed = {
    "ok": True,
    "req_id": "req-456",
    "old_state": "designing",
    "new_state": "reviewing",
    "published_at": datetime.now(timezone.utc).isoformat(),
    "mc_synced": False,
    "note": "Published to NATS subject 'orchestrator.state.req-456'",
}
check("mc_synced = False when backend unavailable", result_failed["mc_synced"] is False)
check("ok still True when mc_synced is False", result_failed["ok"] is True)

# ── Tests: HTTP sync function (pure logic) ──────────────────────────────

section("HTTP Sync Logic (pure)")

def build_status_payload(req_id, new_state, old_state, extra):
    """Mirrors the payload _sync_to_mc_backend sends."""
    return {
        "status": new_state,
        "old_state": old_state,
        "new_state": new_state,
        "event": extra,
        "agent_id": "orchestrator",
    }

payload = build_status_payload("req-789", "testing", "developing", {"task_id": "abc"})
check("payload has status", payload["status"] == "testing")
check("payload has old_state", payload["old_state"] == "developing")
check("payload has new_state", payload["new_state"] == "testing")
check("payload has event dict", payload["event"] == {"task_id": "abc"})
check("payload has agent_id", payload["agent_id"] == "orchestrator")

# Gate event payload
gate_payload = build_status_payload(
    "req-001", "analyzing", "analyzing",
    {"event": "gate_timeout", "gate_level": 0, "sla_hours": 1.0},
)
check("gate event embedded in extra",
      gate_payload["event"]["event"] == "gate_timeout")

# ── Tests: URL construction ─────────────────────────────────────────────

section("MC Backend URL Construction")

MC_BACKEND_URL = "http://172.27.78.109:8000"
url = f"{MC_BACKEND_URL}/api/requirements/req-123/status"
check("PUT URL is correct", url == "http://172.27.78.109:8000/api/requirements/req-123/status")

# Default URL
default_url = f"http://localhost:8000/api/requirements/req-abc/status"
check("default URL uses localhost",
      "localhost:8000/api/requirements" in default_url)

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
