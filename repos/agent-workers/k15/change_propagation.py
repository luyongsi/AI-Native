"""
k15/change_propagation.py — K15 Neo4j Integration: Change Impact Analysis

Analyzes the downstream impact of changes to entities in the Neo4j knowledge graph.
Traverses dependency relationships to identify affected nodes and calculate risk levels.

Phase 3 implementation: Real Neo4j queries instead of hardcoded mocks.

Usage:
    propagation = ChangePropagation(uri="neo4j://host:7687", user="neo4j", password="...")
    impact = await propagation.analyze_impact(changed_entity)
    risk = propagation.calculate_risk_level(impact['affected_count'])
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from neo4j import AsyncGraphDatabase, AsyncSession
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

logger = logging.getLogger(__name__)


class ChangePropagation:
    """Analyzes impact of changes on the Neo4j knowledge graph.

    Traverses DEPENDS_ON, DEFINES, CREATES, and QUERIES relationships to
    identify all affected entities when a change occurs.

    Attributes:
        driver: Neo4j async driver instance
        uri: Connection URI
        user: Authentication user
    """

    def __init__(self, uri: str, user: str, password: str):
        """Initialize Neo4j connection.

        Args:
            uri: Neo4j connection URI (e.g., "neo4j://localhost:7687")
            user: Username for authentication
            password: Password for authentication

        Raises:
            ImportError: If neo4j package is not available
        """
        if not NEO4J_AVAILABLE:
            raise ImportError("neo4j package required. Install with: pip install neo4j")

        self.uri = uri
        self.user = user
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"[K15] ChangePropagation initialized: uri={uri}, user={user}")

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self.driver:
            await self.driver.close()
            logger.info("[K15] Neo4j driver closed")

    # ========================================================================
    # Impact Analysis
    # ========================================================================

    async def analyze_impact(
        self,
        changed_entity: str,
        max_depth: int = 3,
        entity_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze downstream impact of a change to an entity.

        Args:
            changed_entity: Entity identifier (path, table name, req_id, etc.)
            max_depth: Maximum traversal depth for impact analysis (default 3)
            entity_type: Optional filter (APIEndpoint, Database, Module, etc.)

        Returns:
            Dict with keys:
                - changed_entity: The entity that changed
                - entity_type: Type of the changed entity
                - affected_count: Number of affected downstream entities
                - affected_nodes: List of affected nodes with type and name
                - risk_level: LOW | MEDIUM | HIGH | CRITICAL
                - impact_paths: Detailed paths showing how change propagates
                - timestamp: Analysis timestamp
        """
        logger.info(f"[K15] Analyzing impact for {changed_entity} (depth={max_depth})")

        try:
            async with self.driver.session() as session:
                # Phase 1: Find the changed entity
                changed_node = await self._find_entity(session, changed_entity, entity_type)
                if not changed_node:
                    logger.warning(f"[K15] Entity not found: {changed_entity}")
                    return {
                        "changed_entity": changed_entity,
                        "entity_type": "unknown",
                        "affected_count": 0,
                        "affected_nodes": [],
                        "risk_level": "LOW",
                        "impact_paths": [],
                        "error": "Entity not found",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                entity_type_found = self._determine_entity_type(changed_node)

                # Phase 2: Query all affected entities
                impact_paths = await self._find_affected_entities(
                    session, changed_entity, entity_type_found, max_depth
                )

                # Phase 3: Extract unique affected nodes
                affected_nodes = self._extract_unique_nodes(impact_paths)

                # Phase 4: Calculate risk level
                risk_level = self._calculate_risk_level(len(affected_nodes))

                logger.info(
                    f"[K15] Impact analysis complete: {len(affected_nodes)} affected nodes, "
                    f"risk={risk_level}"
                )

                return {
                    "changed_entity": changed_entity,
                    "entity_type": entity_type_found,
                    "affected_count": len(affected_nodes),
                    "affected_nodes": affected_nodes,
                    "risk_level": risk_level,
                    "impact_paths": impact_paths,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        except Exception as e:
            logger.error(f"[K15] Impact analysis failed: {str(e)}", exc_info=True)
            return {
                "changed_entity": changed_entity,
                "entity_type": entity_type or "unknown",
                "affected_count": 0,
                "affected_nodes": [],
                "risk_level": "UNKNOWN",
                "impact_paths": [],
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def analyze_batch_impact(
        self,
        changed_entities: List[str],
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """Analyze impact of multiple entity changes.

        Args:
            changed_entities: List of entity identifiers
            max_depth: Maximum traversal depth

        Returns:
            Dict with:
                - total_changed: Number of changed entities
                - total_affected: Total unique affected entities
                - individual_impacts: List of impact dicts for each entity
                - combined_risk_level: Overall risk level
                - timestamp: Analysis timestamp
        """
        logger.info(f"[K15] Analyzing batch impact for {len(changed_entities)} entities")

        individual_impacts = []
        all_affected_nodes = set()
        max_risk_score = 0

        risk_scores = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

        for entity in changed_entities:
            impact = await self.analyze_impact(entity, max_depth)
            individual_impacts.append(impact)

            # Track unique affected nodes
            for node in impact.get("affected_nodes", []):
                node_id = node.get("id") or node.get("name")
                all_affected_nodes.add(node_id)

            # Track max risk
            risk_score = risk_scores.get(impact.get("risk_level"), 0)
            max_risk_score = max(max_risk_score, risk_score)

        risk_score_reverse = {0: "LOW", 1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
        combined_risk = risk_score_reverse.get(max_risk_score, "UNKNOWN")

        logger.info(
            f"[K15] Batch analysis complete: {len(all_affected_nodes)} total affected nodes, "
            f"combined_risk={combined_risk}"
        )

        return {
            "total_changed": len(changed_entities),
            "total_affected": len(all_affected_nodes),
            "individual_impacts": individual_impacts,
            "combined_risk_level": combined_risk,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ========================================================================
    # Change Propagation Tracing
    # ========================================================================

    async def trace_propagation_paths(
        self,
        changed_entity: str,
        max_depth: int = 3,
        include_reverse: bool = False
    ) -> Dict[str, Any]:
        """Trace detailed propagation paths showing how change affects downstream entities.

        Args:
            changed_entity: Entity identifier
            max_depth: Maximum traversal depth
            include_reverse: Include reverse paths (entities that depend on changed entity)

        Returns:
            Dict with:
                - forward_paths: List of downstream propagation paths
                - reverse_paths: List of upstream dependency paths (if include_reverse=True)
                - path_count: Total number of paths
                - deepest_path_length: Maximum depth reached
        """
        logger.debug(f"[K15] Tracing propagation paths for {changed_entity}")

        try:
            async with self.driver.session() as session:
                # Forward paths (change propagates to these entities)
                forward_query = """
                    MATCH (changed)
                    WHERE changed.req_id = $entity OR changed.path = $entity
                       OR changed.name = $entity
                    OPTIONAL MATCH paths = (changed)-[:DEPENDS_ON|DEFINES|CREATES|QUERIES|CALLS*1..$depth]->(affected)
                    RETURN
                        [path IN collect(paths) |
                            {
                                nodes: [n IN nodes(path) | {
                                    id: COALESCE(n.req_id, n.path, n.name, 'unknown'),
                                    type: labels(n)[0],
                                    name: COALESCE(n.name, n.path, n.title, 'unknown')
                                }],
                                length: length(path)
                            }
                        ] as forward_paths
                """

                result = await session.run(
                    forward_query,
                    entity=changed_entity,
                    depth=max_depth
                )
                record = await result.single()
                forward_paths = record.get("forward_paths", []) if record else []

                reverse_paths = []
                if include_reverse:
                    # Reverse paths (entities that this entity depends on)
                    reverse_query = """
                        MATCH (changed)
                        WHERE changed.req_id = $entity OR changed.path = $entity
                           OR changed.name = $entity
                        OPTIONAL MATCH paths = (dependent)<-[:DEPENDS_ON|DEFINES|CREATES|QUERIES|CALLS*1..$depth]-(changed)
                        RETURN
                            [path IN collect(paths) |
                                {
                                    nodes: [n IN nodes(path) | {
                                        id: COALESCE(n.req_id, n.path, n.name, 'unknown'),
                                        type: labels(n)[0],
                                        name: COALESCE(n.name, n.path, n.title, 'unknown')
                                    }],
                                    length: length(path)
                                }
                            ] as reverse_paths
                    """

                    result = await session.run(
                        reverse_query,
                        entity=changed_entity,
                        depth=max_depth
                    )
                    record = await result.single()
                    reverse_paths = record.get("reverse_paths", []) if record else []

                max_depth_reached = max(
                    (p.get("length", 0) for p in forward_paths + reverse_paths),
                    default=0
                )

                logger.debug(
                    f"[K15] Traced {len(forward_paths)} forward and {len(reverse_paths)} "
                    f"reverse paths (max depth: {max_depth_reached})"
                )

                return {
                    "changed_entity": changed_entity,
                    "forward_paths": forward_paths,
                    "reverse_paths": reverse_paths,
                    "path_count": len(forward_paths) + len(reverse_paths),
                    "deepest_path_length": max_depth_reached,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        except Exception as e:
            logger.error(f"[K15] Path tracing failed: {str(e)}", exc_info=True)
            return {
                "changed_entity": changed_entity,
                "forward_paths": [],
                "reverse_paths": [],
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    # ========================================================================
    # Risk Assessment
    # ========================================================================

    def calculate_risk_level(self, affected_count: int) -> str:
        """Calculate risk level based on affected entity count.

        Args:
            affected_count: Number of affected downstream entities

        Returns:
            Risk level: LOW | MEDIUM | HIGH | CRITICAL
        """
        if affected_count == 0:
            return "LOW"
        elif affected_count <= 3:
            return "LOW"
        elif affected_count <= 8:
            return "MEDIUM"
        elif affected_count <= 20:
            return "HIGH"
        else:
            return "CRITICAL"

    def _calculate_risk_level(self, affected_count: int) -> str:
        """Internal method for risk calculation."""
        return self.calculate_risk_level(affected_count)

    async def calculate_change_risk(
        self,
        changed_entity: str,
        change_type: str = "modification",
        entity_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Calculate comprehensive risk assessment for a change.

        Args:
            changed_entity: Entity that changed
            change_type: Type of change (modification, deletion, addition)
            entity_type: Optional entity type filter

        Returns:
            Dict with:
                - overall_risk: LOW | MEDIUM | HIGH | CRITICAL
                - change_type: Type of change
                - affected_count: Number of affected entities
                - risk_factors: List of risk factors
                - recommendations: List of recommended actions
        """
        impact = await self.analyze_impact(changed_entity, entity_type=entity_type)
        affected_count = impact.get("affected_count", 0)

        # Determine risk factors
        risk_factors = []
        if change_type == "deletion":
            risk_factors.append("Deletion of critical entity")
        if affected_count > 15:
            risk_factors.append("High propagation reach (15+ entities)")
        if affected_count > 0:
            risk_factors.append(f"Affects {affected_count} downstream entities")

        # Generate recommendations
        recommendations = []
        risk_level = impact.get("risk_level", "UNKNOWN")

        if risk_level == "CRITICAL":
            recommendations.extend([
                "Execute full regression test suite",
                "Perform manual review of all affected modules",
                "Consider staged rollout or blue-green deployment",
                "Notify all affected teams before deployment",
            ])
        elif risk_level == "HIGH":
            recommendations.extend([
                "Execute integration tests for all affected modules",
                "Review changes with domain experts",
                "Plan for potential rollback",
            ])
        elif risk_level == "MEDIUM":
            recommendations.extend([
                "Execute smoke tests for affected modules",
                "Review changes with team lead",
            ])
        else:
            recommendations.append("Execute standard test suite")

        return {
            "changed_entity": changed_entity,
            "change_type": change_type,
            "affected_count": affected_count,
            "overall_risk": risk_level,
            "risk_factors": risk_factors,
            "recommendations": recommendations,
            "detailed_impact": impact,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    async def _find_entity(
        self,
        session: AsyncSession,
        entity_name: str,
        entity_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Find an entity in the graph by name/path/req_id.

        Args:
            session: Neo4j async session
            entity_name: Entity identifier
            entity_type: Optional label filter

        Returns:
            Entity node dict or None
        """
        if entity_type:
            query = f"""
                MATCH (n:{entity_type})
                WHERE n.req_id = $entity OR n.path = $entity OR n.name = $entity
                RETURN n LIMIT 1
            """
        else:
            query = """
                MATCH (n)
                WHERE n.req_id = $entity OR n.path = $entity OR n.name = $entity
                RETURN n LIMIT 1
            """

        result = await session.run(query, entity=entity_name)
        record = await result.single()
        return dict(record.get("n")) if record else None

    async def _find_affected_entities(
        self,
        session: AsyncSession,
        changed_entity: str,
        entity_type: str,
        max_depth: int
    ) -> List[Dict[str, Any]]:
        """Find all entities affected by a change.

        Args:
            session: Neo4j async session
            changed_entity: Changed entity identifier
            entity_type: Type of changed entity
            max_depth: Maximum traversal depth

        Returns:
            List of impact path dicts
        """
        query = """
            MATCH (changed)
            WHERE changed.req_id = $entity OR changed.path = $entity OR changed.name = $entity
            OPTIONAL MATCH paths = (changed)-[:DEPENDS_ON|DEFINES|CREATES|QUERIES|CALLS*1..$depth]->(affected)
            RETURN
                collect({
                    nodes: [n IN nodes(path) | {
                        id: COALESCE(n.req_id, n.path, n.name, 'unknown'),
                        type: labels(n)[0],
                        name: COALESCE(n.name, n.path, n.title, 'unknown')
                    }],
                    length: length(path)
                }) as impact_paths
        """

        result = await session.run(query, entity=changed_entity, depth=max_depth)
        record = await result.single()
        return record.get("impact_paths", []) if record else []

    @staticmethod
    def _extract_unique_nodes(impact_paths: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract unique affected nodes from impact paths.

        Args:
            impact_paths: List of path dicts

        Returns:
            List of unique node dicts
        """
        seen_nodes = {}
        for path in impact_paths:
            for node in path.get("nodes", [])[1:]:  # Skip first (the changed entity itself)
                node_id = node.get("id")
                if node_id and node_id not in seen_nodes:
                    seen_nodes[node_id] = node

        return list(seen_nodes.values())

    @staticmethod
    def _determine_entity_type(node: Dict[str, Any]) -> str:
        """Determine entity type from Neo4j node labels.

        Args:
            node: Neo4j node dict

        Returns:
            Entity type string
        """
        # Neo4j nodes have different structures, try common attributes
        if "req_id" in node:
            return "Requirement"
        elif "path" in node and "http_method" in node:
            return "APIEndpoint"
        elif "name" in node and "type" in node and node["type"] in ["table", "view"]:
            return "Database"
        elif "path" in node and "language" in node:
            return "Module"
        elif "name" in node and "type" in node and node["type"] in ["backend", "frontend"]:
            return "Service"
        else:
            return "Unknown"


# ============================================================================
# Standalone convenience functions
# ============================================================================

async def analyze_entity_impact(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    changed_entity: str,
    max_depth: int = 3
) -> Dict[str, Any]:
    """Convenience function to analyze impact."""
    propagation = ChangePropagation(neo4j_uri, neo4j_user, neo4j_password)
    try:
        return await propagation.analyze_impact(changed_entity, max_depth)
    finally:
        await propagation.close()


async def calculate_change_risk_score(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    changed_entity: str,
    change_type: str = "modification"
) -> Dict[str, Any]:
    """Convenience function to calculate risk."""
    propagation = ChangePropagation(neo4j_uri, neo4j_user, neo4j_password)
    try:
        return await propagation.calculate_change_risk(changed_entity, change_type)
    finally:
        await propagation.close()
