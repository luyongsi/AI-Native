"""
k14/knowledge_graph_updater.py — K14 sub-module: Knowledge Graph Updater

Maintains a knowledge graph of artifact relationships.  In Phase 2 this uses
hardcoded mock relationships instead of a real graph database.  Phase 3
replaces the mock logic with Neo4j (or equivalent) queries.

Usage:
    kg = KnowledgeGraphUpdater()
    result = await kg.update_from_artifact(artifact)
    related = await kg.query_related("REQ-001", max_depth=2)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded relationship map (Phase 2 placeholder)
#
# Phase 3: Replace with Neo4j queries, e.g.:
#   MATCH (a:Artifact {id: $id})-[r:DEPENDS_ON*1..$depth]-(b) RETURN a, r, b
# ---------------------------------------------------------------------------
_MOCK_RELATIONSHIPS: Dict[str, List[str]] = {
    "REQ-001": ["SPEC-001", "SPEC-002", "DESIGN-001"],
    "SPEC-001": ["API-001", "API-002", "COMP-A"],
    "SPEC-002": ["API-003", "COMP-B", "COMP-C"],
    "API-001":  ["CODE-001", "TEST-001"],
    "API-002":  ["CODE-002", "CODE-003"],
    "API-003":  ["CODE-004", "TEST-002"],
    "COMP-A":   ["CODE-005", "CONFIG-A"],
    "COMP-B":   ["CODE-006"],
    "COMP-C":   ["CODE-007", "CODE-008", "TEST-003"],
}


class KnowledgeGraphUpdater:
    """Manages artifact relationships via a knowledge graph.

    Phase 2 (current): Hardcoded relationship lookups — no external graph DB.
    Phase 3 (planned):  Neo4j integration with Cypher queries.

    Attributes:
        _node_count:  Running count of nodes created this session.
        _edge_count:  Running count of edges created this session.
    """

    def __init__(self) -> None:
        self._node_count: int = 0
        self._edge_count: int = 0
        logger.info("KnowledgeGraphUpdater initialized (Phase 2 hardcoded-graph mode)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def update_from_artifact(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest an artifact and create/update graph nodes + edges.

        In Phase 2 this uses the hardcoded ``_MOCK_RELATIONSHIPS`` map.
        Phase 3 would run Cypher MERGE statements against Neo4j.

        Args:
            artifact: Dict with ``id``, ``type``, and optionally ``dependencies``.

        Returns:
            Dict with keys:
                nodes_created (int): Number of new nodes.
                edges_created (int): Number of new edges.
                query (str):        The (simulated) graph query that ran.
        """
        artifact_id = artifact.get("id", f"artifact:{uuid.uuid4().hex[:8]}")
        artifact_type = artifact.get("type", "unknown")
        dependencies: List[str] = artifact.get("dependencies", [])

        # Phase 3: Real Cypher would look like:
        #   query = (
        #       "MERGE (a:Artifact {id: $id, type: $type}) "
        #       "WITH a "
        #       "UNWIND $deps AS dep_id "
        #       "MERGE (d:Artifact {id: dep_id}) "
        #       "MERGE (a)-[:DEPENDS_ON]->(d) "
        #       "RETURN count(a) AS nodes, count(d) AS edges"
        #   )
        query = (
            f"--[Phase 2 stub]--\n"
            f"MERGE (a:Artifact {{id: '{artifact_id}', type: '{artifact_type}'}})\n"
            + "\n".join(
                f"MERGE (d:Artifact {{id: '{dep}'}})\n"
                f"MERGE (a)-[:DEPENDS_ON]->(d)"
                for dep in dependencies
            )
            if dependencies
            else f"-- no dependencies declared for {artifact_id}"
        )

        # Determine nodes/edges created from mock data
        if not dependencies and artifact_id in _MOCK_RELATIONSHIPS:
            dependencies = _MOCK_RELATIONSHIPS[artifact_id]

        nodes_created = 1  # the artifact itself
        if dependencies:
            nodes_created += len(dependencies)
            self._edge_count += len(dependencies)

        self._node_count += nodes_created

        logger.info(
            "Graph update for %s: +%d nodes, +%d edges",
            artifact_id,
            nodes_created,
            len(dependencies),
        )

        return {
            "nodes_created": nodes_created,
            "edges_created": len(dependencies),
            "query": query,
        }

    async def query_related(
        self, req_id: str, max_depth: int = 2
    ) -> Dict[str, Any]:
        """Find artifacts related to a given requirement/spec ID.

        Phase 2: Walks the hardcoded ``_MOCK_RELATIONSHIPS`` map (BFS).
        Phase 3: Runs a Neo4j Cypher traversal, e.g.:
            MATCH (a:Artifact {id: $req_id})-[r:DEPENDS_ON*1..$max_depth]->(b)
            RETURN a, r, b

        Args:
            req_id:    The starting artifact/requirement ID.
            max_depth: Maximum graph traversal depth (default 2).

        Returns:
            Dict with keys:
                nodes (list):  Visited node dicts with ``id`` and ``depth``.
                edges (list):  Traversed edge dicts with ``from``, ``to``, ``depth``.
                query (str):   The (simulated) Cypher query.
        """
        # Phase 3 Cypher:
        #   cypher = (
        #       "MATCH p=(start:Artifact {id: $req_id})"
        #       "-[:DEPENDS_ON*1..$max_depth]->(related) "
        #       "RETURN nodes(p), relationships(p)"
        #   )
        cypher = (
            f"--[Phase 2 stub - BFS on hardcoded map]--\n"
            f"MATCH p=(start:Artifact {{id: '{req_id}'}})"
            f"-[:DEPENDS_ON*1..{max_depth}]->(related)\n"
            f"RETURN nodes(p), relationships(p)"
        )

        # BFS traversal over the mock graph
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        visited: set = set()
        queue: List[tuple] = [(req_id, 0)]  # (node_id, depth)

        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            nodes.append({"id": current, "depth": depth})

            neighbors = _MOCK_RELATIONSHIPS.get(current, [])
            for neighbor in neighbors:
                if neighbor not in visited and depth < max_depth:
                    edges.append({"from": current, "to": neighbor, "depth": depth + 1})
                    queue.append((neighbor, depth + 1))

        logger.info(
            "query_related(%s, depth=%d) → %d nodes, %d edges (stub)",
            req_id,
            max_depth,
            len(nodes),
            len(edges),
        )

        return {
            "nodes": nodes,
            "edges": edges,
            "query": cypher,
        }
