"""Transition tables for the orchestrator state machine.

TRANSITION_TABLE maps every non-terminal state to its allowed next states.
"""
from .states import RequirementState as RS

TRANSITION_TABLE: dict[RS, list[RS]] = {
    RS.DRAFT:           [RS.ANALYZING, RS.BLOCKED],
    RS.ANALYZING:       [RS.DESIGNING, RS.BLOCKED],        # Gate 0 between
    RS.DESIGNING:       [RS.REVIEWING, RS.BLOCKED],         # Gate 1 between
    RS.REVIEWING:       [RS.DECOMPOSING, RS.DESIGNING, RS.BLOCKED],  # DESIGNING for rework
    RS.DECOMPOSING:     [RS.DEVELOPING, RS.BLOCKED],         # Gate 2 between
    RS.DEVELOPING:      [RS.TESTING, RS.BLOCKED],
    RS.TESTING:         [RS.REVIEWING_CODE, RS.DEVELOPING, RS.BLOCKED],  # DEVELOPING for inner loop
    RS.REVIEWING_CODE:  [RS.RELEASING, RS.BLOCKED],         # Gate 3 between
    RS.RELEASING:       [RS.DONE, RS.BLOCKED],
    RS.DONE:            [],
    RS.BLOCKED:         [],
}

# Fast-track: skip DESIGNING/REVIEWING/DECOMPOSING/REVIEWING_CODE
FAST_TRANSITION_TABLE: dict[RS, list[RS]] = {
    RS.DRAFT:       [RS.FAST_PASS],
    RS.FAST_PASS:   [RS.DEVELOPING, RS.BLOCKED],
    RS.DEVELOPING:  [RS.TESTING, RS.BLOCKED],
    RS.TESTING:     [RS.RELEASING, RS.BLOCKED],
    RS.RELEASING:   [RS.DONE, RS.BLOCKED],
    RS.DONE:        [],
    RS.BLOCKED:     [],
}
