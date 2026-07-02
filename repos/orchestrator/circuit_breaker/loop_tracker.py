"""Loop tracker - per-requirement round counters for circuit breaking.

Tracks {req_id: {inner, outer, debate}} counters.
Supports both standalone (process-memory) and serializable (dict-based) modes.
For Temporal workflows, use the serializable dict functions directly.
"""

from dataclasses import dataclass, field


@dataclass
class LoopCounters:
    inner: int = 0
    outer: int = 0
    debate: int = 0

    def to_dict(self) -> dict:
        return {"inner": self.inner, "outer": self.outer, "debate": self.debate}

    @classmethod
    def from_dict(cls, d: dict) -> "LoopCounters":
        return cls(inner=d.get("inner", 0), outer=d.get("outer", 0), debate=d.get("debate", 0))


class LoopTracker:
    """Thread-safe(ish) in-memory loop counter store (for non-Temporal use)."""

    def __init__(self) -> None:
        self._store: dict[str, LoopCounters] = {}

    def get(self, req_id: str) -> LoopCounters:
        if req_id not in self._store:
            self._store[req_id] = LoopCounters()
        return self._store[req_id]

    def increment(self, req_id: str, scope: str) -> int:
        counters = self.get(req_id)
        current = getattr(counters, scope, 0) + 1
        setattr(counters, scope, current)
        return current

    def reset(self, req_id: str) -> None:
        self._store.pop(req_id, None)

    def snapshot(self, req_id: str) -> dict[str, int]:
        c = self.get(req_id)
        return c.to_dict()


# Module-level singleton for worker lifetime (non-Temporal use).
loop_tracker = LoopTracker()


# ── Serializable helpers for Temporal Workflows ──

def increment_counts(counts: dict, scope: str) -> dict:
    """Return a NEW dict with *scope* incremented (safe for Temporal replay)."""
    c = dict(counts)
    c[scope] = c.get(scope, 0) + 1
    return c


def init_counts() -> dict:
    return {"inner": 0, "outer": 0, "debate": 0}


def is_exhausted(counts: dict, scope: str, max_rounds: dict | None = None) -> bool:
    """Check if *scope* counter has exceeded its max rounds."""
    if max_rounds is None:
        max_rounds = {"inner": 2, "outer": 3, "debate": 3}
    return counts.get(scope, 0) >= max_rounds.get(scope, 3)
