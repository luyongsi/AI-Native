"""Guard conditions for state transitions.

Enforces:
- can_advance_to_gate: whether a state may pass through a gate
  (gates are located between certain pipeline stages per 04 §3.0).
- is_loop_exhausted: circuit-breaker exhaustion counters
  (inner <= 2, outer <= 3, debate <= 3).
"""

from .states import RequirementState as RS

# ── Gate map: which states must pass through a gate before advancing ────
# Gates are placed after certain stages; the gate name is the key.
GATE_MAP: dict[str, RS] = {
    "analyze":         RS.KNOWLEDGE_ANALYSIS,   # Gate 0 after A2
    "knowledge":       RS.KNOWLEDGE_ANALYSIS,   # alias
    "design":          RS.DESIGNING,            # Gate 1
    "review":          RS.REVIEWING,
    "decompose":       RS.DECOMPOSING,          # Gate 2
    "develop":         RS.DEVELOPING,
    "test":            RS.TESTING,
    "code_review":     RS.REVIEWING_CODE,       # Gate 3
    "release":         RS.RELEASING,
}

# States that require gate approval before transitioning to the next stage.
_GATED_STATES: set[RS] = {
    RS.KNOWLEDGE_ANALYSIS,   # Gate 0 — after A2, before DESIGNING
    RS.DESIGNING,            # Gate 1
    RS.DECOMPOSING,          # Gate 2
    RS.REVIEWING_CODE,       # Gate 3
}


def can_advance_to_gate(state: RS, gate: str) -> bool:
    """Return True if *state* may proceed through *gate*.

    A state matches a gate when the gate name maps to that state
    and the state is one that requires gate approval.
    """
    expected_state = GATE_MAP.get(gate)
    if expected_state is None:
        return False
    return state == expected_state and state in _GATED_STATES


# ── Loop exhaustion ────────────────────────────────────────────────────

# Max round limits per loop type (per 04 §3.0).
MAX_ROUNDS: dict[str, int] = {
    "inner": 2,
    "outer": 3,
    "debate": 3,
}

# Loop-context map: which loop types apply to which states.
LOOP_CONTEXT: dict[RS, str] = {
    RS.KNOWLEDGE_ANALYSIS: "inner",  # A2 self-loop (retry once on timeout)
    RS.DESIGNING:       "debate",    # debate rounds: DESIGNING <-> REVIEWING
    RS.REVIEWING:       "debate",
    RS.DEVELOPING:      "inner",     # inner dev loop: DEVELOPING <-> TESTING
    RS.TESTING:         "inner",
    RS.REVIEWING_CODE:  "outer",     # outer loop: back to DEVELOPING
}


def is_loop_exhausted(scope: str, round_count: int) -> bool:
    """Return True when *round_count* has reached the max for *scope*."""
    max_round = MAX_ROUNDS.get(scope)
    if max_round is None:
        raise ValueError(f"Unknown loop scope: {scope}")
    return round_count >= max_round


def loop_scope_for_state(state: RS) -> str | None:
    """Return the loop scope name for *state*, or None if not in a loop."""
    return LOOP_CONTEXT.get(state)
