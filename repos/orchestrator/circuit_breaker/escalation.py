"""Strategy escalation when a gate is blocked or a loop is exhausted.

Implements three escalation levels per spec-12:
  stronger_model   - promote the next agent call to a stronger model
  compromise_prompt - inject a compromise/fallback prompt
  forced_cot        - force chain-of-thought reasoning
"""

from dataclasses import dataclass, field
from enum import StrEnum


class EscalationLevel(StrEnum):
    STRONGER_MODEL = "stronger_model"
    COMPROMISE_PROMPT = "compromise_prompt"
    FORCED_COT = "forced_cot"


@dataclass
class EscalationState:
    level: EscalationLevel = EscalationLevel.STRONGER_MODEL
    attempts: dict[EscalationLevel, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attempts:
            self.attempts = {lvl: 0 for lvl in EscalationLevel}


# Per-requirement escalation store.
_store: dict[str, EscalationState] = {}


def escalate(req_id: str) -> EscalationLevel | None:
    """Advance the escalation level for *req_id* and return the new level.

    Returns None when all levels are exhausted.
    """
    es = _store.setdefault(req_id, EscalationState())
    current = es.level
    es.attempts[current] = es.attempts.get(current, 0) + 1

    # Cycle through levels
    _order = list(EscalationLevel)
    idx = _order.index(current)
    if idx + 1 < len(_order):
        es.level = _order[idx + 1]
    else:
        # All levels exhausted
        return None
    return es.level


def reset_escalation(req_id: str) -> None:
    """Clear the escalation state for *req_id*."""
    _store.pop(req_id, None)
