"""Transition tables for the orchestrator state machine.

TRANSITION_TABLE maps every non-terminal state to its allowed next states.
"""
from .states import RequirementState as RS

TRANSITION_TABLE: dict[RS, list[RS]] = {
    RS.DRAFT:               [RS.ANALYZING, RS.BLOCKED],
    RS.ANALYZING:           [RS.KNOWLEDGE_ANALYSIS, RS.BLOCKED],   # A1 -> A2
    RS.KNOWLEDGE_ANALYSIS:  [RS.DESIGNING, RS.ANALYZING, RS.BLOCKED],  # Gate 0: pass->DESIGNING, reject->ANALYZING
    RS.DESIGNING:           [RS.SPEC_WRITING, RS.BLOCKED],         # A3 confirm -> A4 spec writing
    RS.SPEC_WRITING:        [RS.REVIEWING, RS.BLOCKED],            # A4 done -> A5 review
    RS.REVIEWING:           [RS.DECOMPOSING, RS.SPEC_WRITING, RS.BLOCKED],  # Gate 1: pass->DECOMPOSING, reject->SPEC_WRITING
    RS.DECOMPOSING:         [RS.DEVELOPING, RS.BLOCKED],           # Gate 2 between
    RS.DEVELOPING:          [RS.TESTING, RS.BLOCKED],
    RS.TESTING:             [RS.REVIEWING_CODE, RS.DEVELOPING, RS.BLOCKED],  # DEVELOPING for inner loop
    RS.REVIEWING_CODE:      [RS.RELEASING, RS.BLOCKED],            # Gate 3 between
    RS.RELEASING:           [RS.DONE, RS.BLOCKED],
    RS.DONE:                [],
    RS.BLOCKED:             [],
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
