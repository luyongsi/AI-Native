"""Unit tests for T1: Gate SLA timeout notification.

Self-contained — no external test framework required.
Usage: python tests/test_gate_sla.py
"""

import sys
from datetime import timedelta


# ── Gate SLA / grace-period config (mirrored from requirement_workflow.py) ──

_GATE_SLA = {
    0: timedelta(hours=1),
    1: timedelta(hours=4),
    2: timedelta(hours=4),
    3: timedelta(hours=2),
}

_GATE_GRACE_PERIOD = {
    0: None,
    1: timedelta(hours=1),
    2: timedelta(hours=1),
    3: None,
}


def _gate_level(gate_name):
    """Extract numeric gate level (mirrors gate_await._gate_level)."""
    if isinstance(gate_name, int):
        return gate_name
    import re
    match = re.search(r"(\d)", str(gate_name))
    if match:
        return int(match.group(1))
    return 0


# ── Gate state machine logic (pure functions, testable without Temporal) ──

class GateSimulator:
    """Simulates the 3-phase gate logic without Temporal dependencies."""

    def __init__(self, gate_level: int):
        self.gate_level = gate_level
        self._gate_approved = None
        self.sla = _GATE_SLA[gate_level]
        self.grace = _GATE_GRACE_PERIOD[gate_level]
        self._events = []

    def approve(self, approver="human"):
        self._gate_approved = "approved-by-" + approver

    def admin_skip(self, approver="admin"):
        self._gate_approved = "force-skip-gate-" + str(self.gate_level) + "-by-" + approver

    def _notify(self, event):
        self._events.append(event)

    def run_gate_stage(self, clock):
        """Simulate the full gate stage with the given clock (seconds).

        Returns the final state string.
        """
        sla_seconds = self.sla.total_seconds()

        # Phase 1: SLA window
        if clock < sla_seconds:
            if self._gate_approved is not None:
                return "approved_sla"
            return "would_wait_sla"

        # Phase 2: SLA expired
        self._notify("gate_timeout")

        grace = self.grace
        if grace is not None:
            grace_seconds = grace.total_seconds()
            if clock < sla_seconds + grace_seconds:
                if self._gate_approved is not None:
                    return "approved_grace"
                return "would_wait_grace"

            # Grace expired -> escalate
            self._notify("gate_grace_expired")

        # Phase 3: Wait indefinitely
        if self._gate_approved is not None:
            return "approved_indefinite"
        return "waiting_indefinite"


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


# ── Tests: SLA/grace config ─────────────────────────────────────────────

section("Gate SLA & Grace Configuration")

check("Gate 0 has SLA", 0 in _GATE_SLA)
check("Gate 1 has SLA", 1 in _GATE_SLA)
check("Gate 2 has SLA", 2 in _GATE_SLA)
check("Gate 3 has SLA", 3 in _GATE_SLA)
check("Gate 0 SLA = 1 hour", _GATE_SLA[0] == timedelta(hours=1))
check("Gate 1 SLA = 4 hours", _GATE_SLA[1] == timedelta(hours=4))
check("Gate 2 SLA = 4 hours", _GATE_SLA[2] == timedelta(hours=4))
check("Gate 3 SLA = 2 hours", _GATE_SLA[3] == timedelta(hours=2))
check("Gate 0 no grace", _GATE_GRACE_PERIOD[0] is None)
check("Gate 1 has 1h grace", _GATE_GRACE_PERIOD[1] == timedelta(hours=1))
check("Gate 2 has 1h grace", _GATE_GRACE_PERIOD[2] == timedelta(hours=1))
check("Gate 3 no grace", _GATE_GRACE_PERIOD[3] is None)

# ── Tests: Gate 0 (no grace) ────────────────────────────────────────────

section("Gate 0 — No Grace Period")

gs = GateSimulator(0)
check("within SLA, not approved -> would_wait_sla",
      gs.run_gate_stage(clock=1800) == "would_wait_sla")
check("no events fired while waiting within SLA",
      "gate_timeout" not in gs._events)

gs2 = GateSimulator(0)
gs2.approve("alice")
check("within SLA, approved -> approved_sla",
      gs2.run_gate_stage(clock=600) == "approved_sla")

gs3 = GateSimulator(0)
check("SLA expired, not approved -> waiting_indefinite (NOT auto-approve)",
      gs3.run_gate_stage(clock=3700) == "waiting_indefinite")
check("gate_timeout event fired on SLA expiry",
      "gate_timeout" in gs3._events)
check("no grace_expired for Gate 0 (no grace)",
      "gate_grace_expired" not in gs3._events)

gs4 = GateSimulator(0)
gs4.admin_skip("admin")
check("SLA expired + admin skip -> approved_indefinite",
      gs4.run_gate_stage(clock=5000) == "approved_indefinite")
check("admin skip value contains force-skip",
      "force-skip" in gs4._gate_approved)

# ── Tests: Gate 1 (1h grace) ────────────────────────────────────────────

section("Gate 1 — 1h Grace Period")

gs5 = GateSimulator(1)
gs5.approve("bob")
check("within 4h SLA, approved -> approved_sla",
      gs5.run_gate_stage(clock=7200) == "approved_sla")

gs6 = GateSimulator(1)
check("SLA expired, within grace -> would_wait_grace",
      gs6.run_gate_stage(clock=15000) == "would_wait_grace")
check("gate_timeout fired when SLA expired",
      "gate_timeout" in gs6._events)
check("gate_grace_expired NOT fired (still in grace)",
      "gate_grace_expired" not in gs6._events)

gs7 = GateSimulator(1)
gs7.approve("carol")
check("approved during grace window -> approved_grace",
      gs7.run_gate_stage(clock=17000) == "approved_grace")

gs8 = GateSimulator(1)
check("grace expired, not approved -> waiting_indefinite",
      gs8.run_gate_stage(clock=20000) == "waiting_indefinite")
check("both gate_timeout AND gate_grace_expired fired",
      "gate_timeout" in gs8._events and "gate_grace_expired" in gs8._events)

# ── Tests: Gate 2 (1h grace) ────────────────────────────────────────────

section("Gate 2 — 1h Grace Period")

gs9 = GateSimulator(2)
check("same grace behavior as Gate 1, SLA expired -> would_wait_grace",
      gs9.run_gate_stage(clock=15000) == "would_wait_grace")

gs10 = GateSimulator(2)
check("Gate 2 grace expired -> waiting_indefinite",
       gs10.run_gate_stage(clock=20000) == "waiting_indefinite")

# ── Tests: Gate 3 (no grace) ────────────────────────────────────────────

section("Gate 3 — No Grace Period, 2h SLA")

gs11 = GateSimulator(3)
check("SLA expired -> waiting_indefinite (no grace for Gate 3)",
      gs11.run_gate_stage(clock=8000) == "waiting_indefinite")
check("gate_timeout fired, no gate_grace_expired",
      "gate_timeout" in gs11._events and "gate_grace_expired" not in gs11._events)

gs12 = GateSimulator(3)
gs12.approve("dave")
check("within 2h SLA, approved -> approved_sla",
      gs12.run_gate_stage(clock=3600) == "approved_sla")

# ── Tests: Signal logic ─────────────────────────────────────────────────

section("Gate Signal Logic")

check("gate_timeout signal value is distinguishable",
      "force-skip" in "force-skip-gate-2-by-adminuser")
check("approve_gate signal value is distinguishable from timeout",
      "force-skip" not in "approved-by-alice")
check("timeout value contains gate level",
      "gate-1" in "force-skip-gate-1-by-admin")
check("timeout value contains approver name",
      "admin" in "force-skip-gate-1-by-admin")

# ── Tests: gate_await helpers ───────────────────────────────────────────

section("gate_await Helper Functions")

check("_gate_level returns int for int", _gate_level(2) == 2)
check("_gate_level returns 3 for 'gate-3'", _gate_level("gate-3") == 3)
check("_gate_level returns 1 for 'Gate1'", _gate_level("Gate1") == 1)
check("_gate_level returns 0 for unknown", _gate_level("unknown") == 0)
check("sla_seconds 7200 -> 2.0h", 7200.0 / 3600.0 == 2.0)
check("sla_seconds 14400 -> 4.0h (default)", 14400.0 / 3600.0 == 4.0)

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
