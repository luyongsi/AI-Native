"""
k15/dependency_traverser.py — K15 sub-module: Dependency Graph Traversal

Given a ``spec.changed`` (or similar) event, walks the agent dependency graph
to determine which downstream agents and requirements are affected.  Phase 2
uses a hardcoded adjacency map; Phase 3 replaces it with Neo4j Cypher queries.

Usage:
    traverser = DependencyTraverser()
    result = traverser.traverse(change_event)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded agent dependency graph (Phase 2)
#
# A1 (Requirement Intake)       → A2, A3, A4
# A2 (Knowledge Analyst)        → A4
# A4 (Spec Writer)              → A5, A6, A8
# A6 (Spec Decomposer)          → A7, A9
# A9 (Claude Code Bridge)       → A10, A12
# A10 (Dev Agent Stub)          → A11, A13
# A12 (Code Review / Impact)    → A11
# A3 (UI Generator)             → A5, A6
# A5 (Design Review)            → A6
# A8 (Architecture Expert)      → A6, A9
# A7 (Test Case Generator)      → A11
# A11 (Test Agent Stub)         → (terminal)
# A13 (Release Agent)           → (terminal)
#
# Phase 3: Replace with Neo4j traversal:
#   MATCH (a:Agent {id: $source})-[r:DEPENDS_ON*1..$max_depth]->(b:Agent)
#   RETURN a.id, type(r), b.id, length(r) AS depth
# ---------------------------------------------------------------------------
_AGENT_DEPENDENCY_GRAPH: Dict[str, List[str]] = {
    "A1":  ["A2", "A3", "A4"],
    "A2":  ["A4"],
    "A3":  ["A5", "A6"],
    "A4":  ["A5", "A6", "A8"],
    "A5":  ["A6"],
    "A6":  ["A7", "A9"],
    "A7":  ["A11"],
    "A8":  ["A6", "A9"],
    "A9":  ["A10", "A12"],
    "A10": ["A11", "A13"],
    "A12": ["A11"],
    "A11": [],   # terminal
    "A13": [],   # terminal
}

# ---------------------------------------------------------------------------
# Requirement → agent mapping (Phase 2 placeholder)
# ---------------------------------------------------------------------------
_REQ_TO_AGENTS: Dict[str, List[str]] = {
    "REQ-001": ["A1", "A2", "A4", "A6", "A9"],
    "REQ-002": ["A1", "A3", "A5", "A6", "A7"],
    "REQ-003": ["A1", "A4", "A8", "A9", "A10", "A11"],
}


class DependencyTraverser:
    """Walks the agent dependency graph to find affected downstream agents.

    Phase 2 (current): Hardcoded adjacency map with BFS traversal.
    Phase 3 (planned):  Neo4j Cypher queries for live dependency resolution.

    Attributes:
        _max_depth:  Maximum graph traversal depth to prevent runaway walks.
    """

    def __init__(self, max_depth: int = 10) -> None:
        self._max_depth = max_depth
        logger.info(
            "DependencyTraverser initialized (Phase 2 hardcoded-graph mode, max_depth=%d)",
            max_depth,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def traverse(self, change_event: Dict[str, Any]) -> Dict[str, Any]:
        """Traverse the dependency graph from the source agent in the change event.

        Args:
            change_event: Dict with expected keys:
                - ``source_agent`` (str):  The agent that triggered the change
                                           (e.g. "A4" for spec.changed).
                - ``req_id`` (str):        The originating requirement ID.
                - ``change_type`` (str):   E.g. "spec.changed", "api.changed".
                - ``changed_files`` (list): Optional list of changed file paths.

        Returns:
            Dict with keys:
                affected_agents (list):      Dicts with agent_id, reason,
                                             impact_type ("direct"|"indirect").
                affected_requirements (list): Requirement IDs that may need
                                             re-validation.
                propagation_depth (int):     Furthest depth reached.
                total_affected (int):        Total count of affected agents.
        """
        source_agent = change_event.get("source_agent", "")
        req_id = change_event.get("req_id", "unknown")
        change_type = change_event.get("change_type", "unknown")

        if not source_agent:
            logger.warning("traverse called without source_agent in change_event")
            return {
                "affected_agents": [],
                "affected_requirements": [],
                "propagation_depth": 0,
                "total_affected": 0,
            }

        logger.info(
            "Traversing dependencies from %s (req=%s, type=%s)",
            source_agent,
            req_id,
            change_type,
        )

        # BFS over the hardcoded graph
        affected: List[Dict[str, Any]] = []
        visited: set = set()
        queue: List[tuple] = [(source_agent, 0, "direct")]  # (agent_id, depth, impact_type)
        max_depth_reached = 0

        while queue:
            current, depth, impact = queue.pop(0)
            if current in visited or depth > self._max_depth:
                continue
            visited.add(current)
            max_depth_reached = max(max_depth_reached, depth)

            # The source agent itself is not "affected" — it is the origin
            if depth > 0:
                reason = self._build_reason(current, source_agent, depth, change_type)
                affected.append({
                    "agent_id": current,
                    "reason": reason,
                    "impact_type": impact,
                })

            # Enqueue downstream dependencies
            downstream = _AGENT_DEPENDENCY_GRAPH.get(current, [])
            for neighbor in downstream:
                if neighbor not in visited:
                    next_impact = "indirect" if depth > 0 else "direct"
                    queue.append((neighbor, depth + 1, next_impact))

        # Determine affected requirements from the mock mapping
        affected_requirements = [
            rid for rid, agents in _REQ_TO_AGENTS.items()
            if any(a in visited for a in agents)
        ]

        logger.info(
            "Traversal complete: %d affected agents, depth=%d, %d affected reqs",
            len(affected),
            max_depth_reached,
            len(affected_requirements),
        )

        return {
            "affected_agents": affected,
            "affected_requirements": affected_requirements,
            "propagation_depth": max_depth_reached,
            "total_affected": len(affected),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_reason(
        agent_id: str, source_agent: str, depth: int, change_type: str
    ) -> str:
        """Build a human-readable reason string for why an agent is affected.

        Phase 3: Could pull descriptions from the agent metadata table.
        """
        if depth == 1:
            return (
                f"Agent {agent_id} is a direct downstream dependency of "
                f"{source_agent} — {change_type} event requires re-processing"
            )
        else:
            return (
                f"Agent {agent_id} is indirectly affected via {depth}-hop "
                f"propagation from {source_agent} ({change_type})"
            )
