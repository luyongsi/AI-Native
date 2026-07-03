"""RequirementState enum - all 12 states per spec-12."""

from enum import StrEnum


class RequirementState(StrEnum):
    """12-state machine for requirement processing.

    Main pipeline:
        DRAFT -> ANALYZING -> DESIGNING -> REVIEWING -> DECOMPOSING
        -> DEVELOPING -> TESTING -> REVIEWING_CODE -> RELEASING -> DONE

    Terminal/altered: BLOCKED
    Fast track:      FAST_PASS (skips DESIGNING/REVIEWING/DECOMPOSING/REVIEWING_CODE)
    """

    DRAFT = "draft"
    ANALYZING = "analyzing"
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
