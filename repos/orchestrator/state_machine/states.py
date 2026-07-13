"""RequirementState enum - all 12 states per spec-12."""

from enum import StrEnum


class RequirementState(StrEnum):
    """14-state machine for requirement processing.

    Main pipeline:
        DRAFT -> ANALYZING (A1 via HTTP+SSE) -> KNOWLEDGE_ANALYSIS (A2)
        -> Gate 0 -> DESIGNING (A3+A4) -> REVIEWING (A5) -> DECOMPOSING (A6)
        -> DEVELOPING (A9) -> TESTING (A11) -> REVIEWING_CODE (A12)
        -> RELEASING (A13) -> DONE

    Gate0 reject: KNOWLEDGE_ANALYSIS -> ANALYZING (A1 revision, cycle++)

    Terminal/altered: BLOCKED
    Fast track:      FAST_PASS (skips DESIGNING/REVIEWING/DECOMPOSING/REVIEWING_CODE)
    """

    DRAFT = "draft"
    ANALYZING = "analyzing"
    KNOWLEDGE_ANALYSIS = "knowledge_analysis"  # A2 stage (new)
    DESIGNING = "designing"
    REVIEWING = "reviewing"
    DECOMPOSING = "decomposing"
    DEVELOPING = "developing"
    TESTING = "testing"
    REVIEWING_CODE = "reviewing_code"
    RELEASING = "releasing"
    DONE = "done"
    BLOCKED = "blocked"
    FAST_PASS = "fast_pass"
