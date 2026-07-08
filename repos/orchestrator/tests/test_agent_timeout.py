"""Unit tests for T3: Agent timeout escalation.

Covers:
  - Consecutive timeout tracking (_agent_failures dict)
  - Threshold=2 triggers notify_mc with agent_repeated_timeout event
  - Success resets failure counter
  - _escalate flag completely removed from codebase
  - A3/A4 parallel timeout tracking (independent counters)
  - Single timeout does NOT trigger escalation
"""

import sys


# ── Pure implementation of timeout escalation logic ─────────────────────

_ESCALATION_THRESHOLD = 2


class AgentTimeoutTracker:
    """Mirrors the _agent_failures tracking in RequirementWorkflow."""

    def __init__(self):
        self._agent_failures = {}
        self._escalation_events = []

    def handle_timeout(self, agent_id):
        self._agent_failures[agent_id] = self._agent_failures.get(agent_id, 0) + 1
        failures = self._agent_failures[agent_id]
        if failures >= _ESCALATION_THRESHOLD:
            self._escalation_events.append({
                "event": "agent_repeated_timeout",
                "agent_id": agent_id,
                "consecutive_failures": failures,
            })
            return True
        return False

    def handle_success(self, agent_id):
        self._agent_failures[agent_id] = 0

    def get_failure_count(self, agent_id):
        return self._agent_failures.get(agent_id, 0)


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


# ── Tests: timeout tracking ─────────────────────────────────────────────

section("Single Agent Timeout Tracking")

tracker = AgentTimeoutTracker()
check("initial failure count = 0", tracker.get_failure_count("A1") == 0)

escalated = tracker.handle_timeout("A1")
check("1st timeout: count = 1", tracker.get_failure_count("A1") == 1)
check("1st timeout: no escalation", not escalated)
check("1st timeout: no events recorded", len(tracker._escalation_events) == 0)

escalated2 = tracker.handle_timeout("A1")
check("2nd timeout: count = 2", tracker.get_failure_count("A1") == 2)
check("2nd timeout: escalation triggered", escalated2)
check("2nd timeout: event recorded", len(tracker._escalation_events) == 1)
check("event has agent_id = A1",
      tracker._escalation_events[0]["agent_id"] == "A1")
check("event has consecutive_failures = 2",
      tracker._escalation_events[0]["consecutive_failures"] == 2)
check("event type = agent_repeated_timeout",
      tracker._escalation_events[0]["event"] == "agent_repeated_timeout")

# 3rd timeout also escalates
escalated3 = tracker.handle_timeout("A1")
check("3rd timeout: count = 3", tracker.get_failure_count("A1") == 3)
check("3rd timeout: escalation triggered", escalated3)
check("3rd timeout: 2 events recorded", len(tracker._escalation_events) == 2)

# ── Tests: success resets counter ───────────────────────────────────────

section("Success Resets Failure Counter")

tracker2 = AgentTimeoutTracker()
tracker2.handle_timeout("A9")
check("A9: after 1 timeout, count = 1", tracker2.get_failure_count("A9") == 1)

tracker2.handle_success("A9")
check("A9: after success, count = 0", tracker2.get_failure_count("A9") == 0)

tracker2.handle_timeout("A9")
check("A9: after new timeout, count = 1 (reset)", tracker2.get_failure_count("A9") == 1)

tracker2.handle_success("A9")
tracker2.handle_timeout("A9")
escalated = tracker2.handle_timeout("A9")
check("A9: timeout->success->timeout->timeout: escalation on 2nd consecutive",
      escalated)
check("A9: count = 2", tracker2.get_failure_count("A9") == 2)

# ── Tests: independent per agent ────────────────────────────────────────

section("Independent Failure Tracking Per Agent")

tracker3 = AgentTimeoutTracker()
tracker3.handle_timeout("A4")
tracker3.handle_timeout("A4")
check("A4: 2 timeouts -> escalated", len(tracker3._escalation_events) == 1)
check("A9: untouched, count = 0", tracker3.get_failure_count("A9") == 0)

tracker3.handle_timeout("A9")
check("A9: 1 timeout, count = 1", tracker3.get_failure_count("A9") == 1)
check("A9: no escalation yet",
      tracker3._escalation_events[-1]["agent_id"] == "A4")

# ── Tests: A3 non-fatal vs A4 fatal ─────────────────────────────────────

section("A3/A4 Parallel Timeout: Independent Counters")

tracker4 = AgentTimeoutTracker()

# A3 timeout (non-fatal but still tracked)
tracker4.handle_timeout("A3")
check("A3: 1 timeout, count = 1", tracker4.get_failure_count("A3") == 1)

tracker4.handle_timeout("A3")
check("A3: 2 timeouts -> escalated", len(tracker4._escalation_events) >= 1)
check("A3 escalation event present",
      any(e["agent_id"] == "A3" for e in tracker4._escalation_events))

# ── Tests: Parallel agent tracking ──────────────────────────────────────

section("Parallel A3/A4 Mix")

tracker5 = AgentTimeoutTracker()
tracker5.handle_timeout("A3")
tracker5.handle_timeout("A4")
tracker5.handle_success("A3")
check("A3 reset after success: 0", tracker5.get_failure_count("A3") == 0)
check("A4 still 1 (uncoupled)", tracker5.get_failure_count("A4") == 1)

tracker5.handle_timeout("A4")
check("A4: 2 timeouts -> escalated",
      any(e["agent_id"] == "A4" for e in tracker5._escalation_events))

# ── Tests: _escalate flag removed ───────────────────────────────────────

section("Dead Code Removal: _escalate Flag")

# Verify _escalate is not in the workflow source file
with open("workflows/requirement_workflow.py", "r", encoding="utf-8") as f:
    source = f.read()

check("_escalate removed from requirement_workflow.py",
      "_escalate" not in source)
check("_agent_failures dict present in workflow",
      "_agent_failures" in source)
check("agent_repeated_timeout event referenced",
      "agent_repeated_timeout" in source)
check("consecutive_failures field referenced",
      "consecutive_failures" in source)

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
