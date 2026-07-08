"""Source ↔ Truth Spec consistency check (optional, warning-only)."""

import logging
import os
import sys

logger = logging.getLogger(__name__)


async def check_source_truth_consistency(truth_spec: dict, repo_root: str) -> list[dict]:
    """Compare transitions.py with Truth Spec. Divergences are WARNINGs, not errors."""
    warnings = []

    orchestrator_path = os.path.join(repo_root, "repos", "orchestrator")
    if not os.path.isdir(orchestrator_path):
        return [{"rule": "SOURCE_NOT_FOUND", "severity": "warning",
                 "message": f"orchestrator source not found at {orchestrator_path}"}]

    # Only import if the path exists
    if orchestrator_path not in sys.path:
        sys.path.insert(0, orchestrator_path)

    try:
        from state_machine.transitions import TRANSITION_TABLE  # type: ignore
    except ImportError as e:
        return [{"rule": "IMPORT_FAILED", "severity": "warning",
                 "message": f"Failed to import TRANSITION_TABLE: {e}"}]

    # Compare
    source_transitions = {}
    for k, vs in TRANSITION_TABLE.items():
        key = k.value if hasattr(k, "value") else str(k)
        vals = [v.value if hasattr(v, "value") else str(v) for v in vs]
        source_transitions[key] = vals

    truth_transitions = truth_spec.get("state_machine", {}).get("normal_flow", {})

    for state, next_states in source_transitions.items():
        truth_next = truth_transitions.get(state, [])
        if set(next_states) != set(truth_next):
            warnings.append({
                "rule": "TRUTH_SPEC_SOURCE_DIVERGED",
                "severity": "warning",
                "message": (
                    f"State {state}: source={sorted(next_states)}, "
                    f"truth_spec={sorted(truth_next)}. "
                    "Update whichever is stale."
                ),
            })

    # Also check for states in truth spec not in source
    for state in truth_transitions:
        if state not in source_transitions:
            warnings.append({
                "rule": "TRUTH_SPEC_SOURCE_DIVERGED",
                "severity": "warning",
                "message": f"State {state}: only in truth_spec, not in source code",
            })

    return warnings
