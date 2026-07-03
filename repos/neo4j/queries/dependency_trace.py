"""Dependency tracing queries for the Neo4j knowledge graph.

Traces upstream (who depends on me?) and downstream (what do I depend on?)
dependency chains, and detects circular dependencies.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DependencyTracer:
    """Traces dependency relationships through the knowledge graph.

    Uses the async Neo4j Python driver.  When the driver is ``None`` the
    tracer returns realistic stub data for integration testing.
    """

    # Cypher templates — populated at init or overridden for testing.
    UPSTREAM_QUERY = """
        MATCH path = (entity)-[:DEPENDS_ON*1..{max_depth}]->(upstream)
        WHERE entity.id = $entity_id
        RETURN upstream, relationships(path) as rels, length(path) as depth,
               [node in nodes(path) | node.id] as dependency_path
        ORDER BY depth
    """

    DOWNSTREAM_QUERY = """
        MATCH path = (downstream)-[:DEPENDS_ON*1..{max_depth}]->(entity)
        WHERE entity.id = $entity_id
        RETURN downstream, relationships(path) as rels, length(path) as depth,
               [node in nodes(path) | node.id] as dependency_path
        ORDER BY depth
    """

    CYCLE_QUERY = """
        MATCH (n)
        WHERE n:Task OR n:Codebase OR n:Spec
        MATCH path = (n)-[:DEPENDS_ON*2..10]->(n)
        RETURN [node in nodes(path) | node.id] as cycle_path,
               length(path) as cycle_length
        ORDER BY cycle_length
    """

    def __init__(self, driver=None) -> None:
        """Initialise with an optional async Neo4j driver.

        Args:
            driver: An instance of ``neo4j.async_.driver``.
        """
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def trace_upstream(
        self, entity_id: str, max_depth: int = 5
    ) -> dict:
        """Return everything that *entity_id* depends on (upstream).

        Args:
            entity_id: Node ``id`` of the starting entity.
            max_depth: Maximum traversal depth (default 5).

        Returns a dict of::

            {
                "entity": <str>,
                "dependencies": [
                    {
                        "entity": {"id": <str>, "type": <str>},
                        "relationship": <str>,
                        "depth": <int>,
                        "path": [<str>, ...],
                    },
                    ...
                ],
                "total_deps": <int>,
            }
        """
        logger.info(
            "DependencyTracer.trace_upstream(entity_id=%r, max_depth=%d)",
            entity_id, max_depth,
        )

        if self._driver is not None:
            # Real execution path
            params = {"entity_id": entity_id, "max_depth": max_depth}
            query = self.UPSTREAM_QUERY.format(max_depth=max_depth)
            async with self._driver.session() as session:
                result = await session.run(query, **params)
                records = await result.data()
            return self._format_result(entity_id, records)
        else:
            # Stub: realistic mock data
            return self._stub_upstream(entity_id, max_depth)

    async def trace_downstream(
        self, entity_id: str, max_depth: int = 5
    ) -> dict:
        """Return everything that depends on *entity_id* (downstream).

        Args:
            entity_id: Node ``id`` of the starting entity.
            max_depth: Maximum traversal depth (default 5).

        Returns a dict with the same shape as ``trace_upstream``.
        """
        logger.info(
            "DependencyTracer.trace_downstream(entity_id=%r, max_depth=%d)",
            entity_id, max_depth,
        )

        if self._driver is not None:
            params = {"entity_id": entity_id, "max_depth": max_depth}
            query = self.DOWNSTREAM_QUERY.format(max_depth=max_depth)
            async with self._driver.session() as session:
                result = await session.run(query, **params)
                records = await result.data()
            return self._format_result(entity_id, records)
        else:
            return self._stub_downstream(entity_id, max_depth)

    async def find_cycles(self) -> list:
        """Detect circular dependency chains in the graph.

        Searches for ``:DEPENDS_ON`` paths of length 2–10 that start and
        end at the same node.  Only checks :Task, :Codebase, and :Spec
        labels to keep scans bounded.

        Returns a list of dicts::

            [
                {"cycle": [<str>, ...], "length": <int>},
                ...
            ]
        """
        logger.info("DependencyTracer.find_cycles()")

        if self._driver is not None:
            async with self._driver.session() as session:
                result = await session.run(self.CYCLE_QUERY)
                records = await result.data()
            return [{"cycle": r["cycle_path"], "length": r["cycle_length"]} for r in records]
        else:
            return self._stub_cycles()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_result(entity_id: str, records: List[dict]) -> dict:
        """Convert raw Neo4j records into the standard response shape."""
        deps = []
        for rec in records:
            deps.append({
                "entity": {"id": rec.get("id"), "type": rec.get("type")},
                "relationship": "DEPENDS_ON",
                "depth": rec.get("depth", 0),
                "path": rec.get("dependency_path", []),
            })
        return {
            "entity": entity_id,
            "dependencies": deps,
            "total_deps": len(deps),
        }

    # ------------------------------------------------------------------
    # Stub data generators
    # ------------------------------------------------------------------

    @staticmethod
    def _stub_upstream(entity_id: str, max_depth: int) -> dict:
        """Generate realistic upstream dependency data for testing."""
        # Simulate a chain: entity → dep-1 → dep-2 → dep-root
        deps: List[Dict[str, Any]] = []
        if max_depth >= 1:
            deps.append({
                "entity": {"id": "spec:auth-v2", "type": "Spec"},
                "relationship": "DEPENDS_ON",
                "depth": 1,
                "path": [entity_id, "spec:auth-v2"],
            })
        if max_depth >= 2:
            deps.append({
                "entity": {"id": "req:REQ-042", "type": "Requirement"},
                "relationship": "DEPENDS_ON",
                "depth": 2,
                "path": [entity_id, "spec:auth-v2", "req:REQ-042"],
            })
        return {"entity": entity_id, "dependencies": deps, "total_deps": len(deps)}

    @staticmethod
    def _stub_downstream(entity_id: str, max_depth: int) -> dict:
        """Generate realistic downstream dependency data for testing."""
        deps: List[Dict[str, Any]] = []
        if max_depth >= 1:
            deps.append({
                "entity": {"id": "task:build-login", "type": "Task"},
                "relationship": "DEPENDS_ON",
                "depth": 1,
                "path": ["task:build-login", entity_id],
            })
        if max_depth >= 2:
            deps.append({
                "entity": {"id": "test:TC-099", "type": "TestCase"},
                "relationship": "DEPENDS_ON",
                "depth": 2,
                "path": ["test:TC-099", "task:build-login", entity_id],
            })
        return {"entity": entity_id, "dependencies": deps, "total_deps": len(deps)}

    @staticmethod
    def _stub_cycles() -> list:
        """Generate realistic cycle detection data for testing."""
        return [
            {
                "cycle": [
                    "task:export-csv",
                    "task:parse-csv",
                    "task:export-csv",
                ],
                "length": 2,
            },
            {
                "cycle": [
                    "cb:core/utils.py",
                    "cb:core/config.py",
                    "cb:core/helpers.py",
                    "cb:core/utils.py",
                ],
                "length": 3,
            },
        ]
