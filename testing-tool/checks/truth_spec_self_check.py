"""Truth Spec self-consistency validation."""


def validate_truth_spec(spec: dict) -> list[dict]:
    """Validate that truth-spec.yaml is internally consistent."""
    issues = []

    agents = spec.get("agents", {})
    state_agents = agents.get("state_agent_map", {})
    parallel = agents.get("parallel_states", {})
    transitions = spec.get("state_machine", {}).get("normal_flow", {})
    gates = spec.get("gates", [])
    upstream = spec.get("data_flow", {}).get("upstream_artifacts", {})
    context_map = spec.get("data_flow", {}).get("context_key_mapping", {})
    stubs = set(agents.get("stubs", []))
    all_states = set(state_agents.keys()) | set(parallel.keys())

    # 1. Gate runs_in_state must be in agents
    for g in gates:
        runs_in = g.get("runs_in_state", "")
        next_s = g.get("next_state", "")
        if runs_in and runs_in not in all_states:
            issues.append({
                "rule": "GATE_RUNS_IN_UNKNOWN",
                "severity": "error",
                "message": f"Gate {g['level']}: runs_in_state={runs_in} not in agents",
            })
        if next_s and next_s not in transitions:
            issues.append({
                "rule": "GATE_NEXT_STATE_UNKNOWN",
                "severity": "error",
                "message": f"Gate {g['level']}: next_state={next_s} not in transitions",
            })
        elif next_s and runs_in and next_s not in transitions.get(runs_in, []):
            issues.append({
                "rule": "GATE_NEXT_STATE_UNREACHABLE",
                "severity": "error",
                "message": f"Gate {g['level']}: {runs_in} -> {next_s} is not a valid transition",
            })

    # 2. upstream_artifacts agents must be in context_key_mapping
    all_upstream = set()
    for lst in upstream.values():
        all_upstream.update(lst)
    for a in all_upstream:
        if a not in context_map:
            issues.append({
                "rule": "UPSTREAM_NO_MAPPING",
                "severity": "error",
                "message": f"upstream agent {a} has no context_key_mapping",
            })

    # 3. Transition target states must exist
    for state, next_states in transitions.items():
        for ns in next_states:
            if ns not in transitions:
                issues.append({
                    "rule": "UNDEFINED_STATE",
                    "severity": "error",
                    "message": f"{state} -> {ns}, but {ns} is not defined",
                })

    # 4. Parallel state must not also be in single state map
    for s in parallel:
        if s in state_agents:
            issues.append({
                "rule": "STATE_DUPLICATE",
                "severity": "error",
                "message": f"{s} is in both state_agent_map and parallel_states",
            })

    # 5. Stub in state map = warning
    for stub in stubs:
        for s, a in state_agents.items():
            if a == stub:
                issues.append({
                    "rule": "STUB_IN_STATE_MAP",
                    "severity": "warning",
                    "message": f"{stub} is a stub but executes state {s}",
                })

    # 6. Gate SLA + grace < 24h
    for g in gates:
        total = g.get("sla_hours", 0) + (g.get("grace_hours") or 0)
        if total > 24:
            issues.append({
                "rule": "GATE_WAIT_LONG",
                "severity": "warning",
                "message": f"Gate {g['level']} total wait {total}h may be too long",
            })

    # 7. Persistence contract targets reasonable
    pcontracts = spec.get("data_flow", {}).get("persistence_contracts", {})
    valid_targets = {"spec.openapi", "spec.erd", "api_schemas", "erd_designs"}
    for agent, contracts in pcontracts.items():
        if agent == "default":
            continue
        for c in contracts:
            t = c.get("target", "")
            if t.startswith("spec.") and t not in valid_targets:
                # Dynamically accept spec.artifacts.X patterns
                if not t.startswith("spec.artifacts."):
                    issues.append({
                        "rule": "UNKNOWN_PERSISTENCE_TARGET",
                        "severity": "warning",
                        "message": f"{agent}: unknown persistence target '{t}'",
                    })

    return issues
