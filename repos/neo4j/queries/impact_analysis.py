"""Impact analysis queries for the Neo4j knowledge graph.

Answers "if I change X, what breaks?" and identifies architectural
hotspots (entities with unusually many incoming dependencies).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Impact classification heuristics
# ---------------------------------------------------------------------------
IMPACT_LEVELS: Dict[str, Tuple[str, str]] = {
    "breaking": ("critical", "may break downstream consumers"),
    "additive": ("low", "backward-compatible addition"),
    "deprecation": ("medium", "consumers should migrate"),
    "refactor": ("medium", "internal restructure, verify contracts"),
    "config": ("low", "configuration-only change"),
}


class ImpactAnalyzer:
    """Analyses the blast radius of a change and identifies hotspots.

    Uses the async Neo4j Python driver for real graph traversal; returns
    realistic stub data when no driver is provided.
    """

    IMPACT_QUERY = """
        MATCH (source {id: $entity_id})-[r:IMPACTS|DEPENDS_ON|TESTED_BY|CONTAINS*1..5]->(target)
        RETURN target, labels(target) as target_labels,
               [rel in relationships(path) | type(rel)] as impact_chain,
               length(path) as distance
        ORDER BY distance
    """

    HOTSPOT_QUERY = """
        MATCH (n)<-[r:DEPENDS_ON|IMPACTS|TESTED_BY]-(m)
        WHERE n:Task OR n:Codebase OR n:Spec
        WITH n, count(DISTINCT m) as incoming_deps
        WHERE incoming_deps >= $min_dependencies
        RETURN n.id as id, labels(n) as labels, incoming_deps
        ORDER BY incoming_deps DESC
        LIMIT 50
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

    async def analyze_change(
        self, entity_id: str, change_type: str
    ) -> dict:
        """Analyse the blast radius of changing *entity_id*.

        Args:
            entity_id: Node ``id`` of the changed entity.
            change_type: One of ``breaking``, ``additive``, ``deprecation``,
                ``refactor``, or ``config``.

        Returns a dict of::

            {
                "impacted_entities": [
                    {
                        "id": <str>,
                        "type": <str>,
                        "impact_level": <str>,
                        "reason": <str>,
                        "path": [<str>, ...],
                    },
                    ...
                ],
                "total_impacted": <int>,
                "risk_score": <float>,       # 0.0 – 1.0
                "recommendation": <str>,
            }
        """
        logger.info(
            "ImpactAnalyzer.analyze_change(entity_id=%r, change_type=%r)",
            entity_id, change_type,
        )

        impact_level, reason = IMPACT_LEVELS.get(
            change_type, ("medium", "unknown change type")
        )

        if self._driver is not None:
            # Real execution path
            async with self._driver.session() as session:
                result = await session.run(
                    self.IMPACT_QUERY, {"entity_id": entity_id}
                )
                records = await result.data()
            impacted = self._format_impact(records, impact_level)
            risk = self._compute_risk(len(impacted), change_type)
            return {
                "impacted_entities": impacted,
                "total_impacted": len(impacted),
                "risk_score": risk,
                "recommendation": self._recommendation(
                    len(impacted), change_type
                ),
            }
        else:
            return self._stub_analyze(entity_id, change_type)

    async def get_hotspots(self, min_dependencies: int = 5) -> list:
        """Find entities with unusually many incoming dependencies.

        Args:
            min_dependencies: Minimum incoming dependency count (default 5).

        Returns a list of dicts::

            [
                {"id": <str>, "type": <str>, "incoming_dependencies": <int>},
                ...
            ]
        """
        logger.info(
            "ImpactAnalyzer.get_hotspots(min_dependencies=%d)", min_dependencies
        )

        if self._driver is not None:
            async with self._driver.session() as session:
                result = await session.run(
                    self.HOTSPOT_QUERY,
                    {"min_dependencies": min_dependencies},
                )
                records = await result.data()
            return [
                {
                    "id": r["id"],
                    "type": r["labels"][0] if r["labels"] else "Unknown",
                    "incoming_dependencies": r["incoming_deps"],
                }
                for r in records
            ]
        else:
            return self._stub_hotspots(min_dependencies)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_impact(records: List[dict], impact_level: str) -> list:
        """Convert Neo4j records to the standard impacted-entities shape."""
        return [
            {
                "id": r.get("id", ""),
                "type": r["target_labels"][0] if r.get("target_labels") else "Unknown",
                "impact_level": impact_level,
                "reason": f"connected via {r.get('distance', '?')} hops",
                "path": r.get("impact_chain", []),
            }
            for r in records
        ]

    @staticmethod
    def _compute_risk(count: int, change_type: str) -> float:
        """Simple risk heuristic: count + change severity."""
        weight = {
            "breaking": 0.4, "deprecation": 0.3,
            "refactor": 0.25, "additive": 0.15, "config": 0.1,
        }.get(change_type, 0.2)
        raw = min(count * weight * 0.1, 1.0)
        return round(raw, 2)

    @staticmethod
    def _recommendation(count: int, change_type: str) -> str:
        """Generate a plain-English recommendation based on impact size."""
        if count == 0:
            return "No downstream dependencies detected. Safe to proceed."
        if change_type == "breaking" and count > 3:
            return (
                f"Breaking change impacts {count} downstream entities. "
                "Schedule a migration window and notify owning teams."
            )
        if count > 10:
            return (
                f"Large blast radius ({count} entities). "
                "Consider a phased rollout with feature flags."
            )
        return (
            f"{count} downstream entities affected. "
            "Review impacted paths and add regression tests before merging."
        )

    # ------------------------------------------------------------------
    # Stub data generators
    # ------------------------------------------------------------------

    @staticmethod
    def _stub_analyze(entity_id: str, change_type: str) -> dict:
        """Generate realistic impact analysis data for testing."""
        impacted = [
            {
                "id": "task:export-orders",
                "type": "Task",
                "impact_level": "high",
                "reason": "directly calls the changed endpoint",
                "path": [entity_id, "task:export-orders"],
            },
            {
                "id": "tc:order-export-integration",
                "type": "TestCase",
                "impact_level": "high",
                "reason": "integration test for the changed endpoint",
                "path": [entity_id, "task:export-orders", "tc:order-export-integration"],
            },
            {
                "id": "comp:OrderDetailPage",
                "type": "Codebase",
                "impact_level": "medium",
                "reason": "renders export button that triggers the endpoint",
                "path": [entity_id, "comp:OrderDetailPage"],
            },
        ]
        total = len(impacted)
        return {
            "impacted_entities": impacted,
            "total_impacted": total,
            "risk_score": 0.35 if change_type == "breaking" else 0.12,
            "recommendation": (
                f"Change type '{change_type}' affects {total} downstream "
                "entities. Run full test suite before merging."
            ),
        }

    @staticmethod
    def _stub_hotspots(min_dependencies: int) -> list:
        """Generate realistic hotspot data for testing."""
        return [
            {"id": "cb:shared/auth.py", "type": "Codebase", "incoming_dependencies": 23},
            {"id": "spec:order-api-v2", "type": "Spec", "incoming_dependencies": 18},
            {"id": "task:notification-dispatcher", "type": "Task", "incoming_dependencies": 14},
            {"id": "cb:core/database.py", "type": "Codebase", "incoming_dependencies": 11},
            {"id": "tc:login-flow", "type": "TestCase", "incoming_dependencies": 7},
        ]
