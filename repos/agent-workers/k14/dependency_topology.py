"""
k14/dependency_topology.py — K14 Neo4j Integration: Dependency Topology Analysis

Builds and queries the Neo4j knowledge graph for requirement-to-infrastructure
dependency relationships. Integrates API schemas and ERDs to create a complete
topology model.

Phase 3 implementation: Real Neo4j queries instead of hardcoded mocks.

Usage:
    topology = DependencyTopology(uri="neo4j://host:7687", user="neo4j", password="...")
    await topology.build_topology(req_id, api_schema, erd)
    deps = await topology.query_dependencies(entity_name, depth=2)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from neo4j import AsyncGraphDatabase, AsyncSession
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False

logger = logging.getLogger(__name__)


class DependencyTopology:
    """Builds and queries Neo4j knowledge graph for dependency analysis.

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
        logger.info(f"[K14] DependencyTopology initialized: uri={uri}, user={user}")

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self.driver:
            await self.driver.close()
            logger.info("[K14] Neo4j driver closed")

    # ========================================================================
    # Topology Building
    # ========================================================================

    async def build_topology(
        self,
        req_id: str,
        api_schema: Dict[str, Any],
        erd: Dict[str, Any],
        requirement_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build complete dependency topology from requirement, API schema, and ERD.

        Args:
            req_id: Requirement ID (UUID)
            api_schema: OpenAPI/Swagger schema dict with 'paths' and 'components'
            erd: Entity-Relationship Diagram with 'entities' and 'relationships'
            requirement_context: Optional requirement metadata (title, description, etc.)

        Returns:
            Dict with keys:
                status: "completed" or "error"
                req_id: Requirement ID
                nodes_created: Count of nodes created
                edges_created: Count of edges created
                error: If status is "error"
        """
        logger.info(f"[K14] Building topology for req_id={req_id}")

        try:
            async with self.driver.session() as session:
                # Phase 1: Create Requirement node
                logger.debug(f"[K14] Phase 1: Creating Requirement node for {req_id}")
                await self._create_requirement_node(session, req_id, requirement_context)

                # Phase 2: Process API Schema
                logger.debug(f"[K14] Phase 2: Processing API schema")
                api_nodes_created, api_edges_created = await self._process_api_schema(
                    session, req_id, api_schema
                )

                # Phase 3: Process ERD (Entity-Relationship Diagram)
                logger.debug(f"[K14] Phase 3: Processing ERD")
                erd_nodes_created, erd_edges_created = await self._process_erd(
                    session, req_id, erd
                )

                total_nodes = 1 + api_nodes_created + erd_nodes_created
                total_edges = api_edges_created + erd_edges_created

                logger.info(
                    f"[K14] Topology built: {total_nodes} nodes, {total_edges} edges"
                )

                return {
                    "status": "completed",
                    "req_id": req_id,
                    "nodes_created": total_nodes,
                    "edges_created": total_edges,
                }

        except Exception as e:
            logger.error(f"[K14] Topology build failed: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "req_id": req_id,
                "error": str(e),
            }

    async def _create_requirement_node(
        self,
        session: AsyncSession,
        req_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Create or update a Requirement node in Neo4j.

        Args:
            session: Neo4j async session
            req_id: Requirement ID
            context: Optional metadata (title, description, complexity, etc.)
        """
        context = context or {}
        query = """
            MERGE (r:Requirement {req_id: $req_id})
            SET
                r.title = $title,
                r.description = $description,
                r.complexity = $complexity,
                r.status = $status,
                r.created_at = $created_at,
                r.updated_at = $updated_at
            RETURN r.req_id
        """

        result = await session.run(
            query,
            req_id=req_id,
            title=context.get("title", f"Requirement {req_id}"),
            description=context.get("description", ""),
            complexity=context.get("complexity", "medium"),
            status=context.get("status", "active"),
            created_at=context.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        await result.single()

    async def _process_api_schema(
        self,
        session: AsyncSession,
        req_id: str,
        api_schema: Dict[str, Any]
    ) -> tuple:
        """Process OpenAPI schema to create APIEndpoint nodes and relationships.

        Args:
            session: Neo4j async session
            req_id: Requirement ID
            api_schema: OpenAPI schema dict

        Returns:
            Tuple of (nodes_created, edges_created)
        """
        nodes_created = 0
        edges_created = 0

        paths = api_schema.get("paths", {})
        logger.debug(f"[K14] Processing {len(paths)} API paths")

        for path, methods_dict in paths.items():
            for http_method, endpoint_info in methods_dict.items():
                # Skip non-HTTP method keys (like parameters)
                if http_method.lower() not in ["get", "post", "put", "delete", "patch", "head", "options"]:
                    continue

                # Create APIEndpoint node
                query = """
                    MERGE (a:APIEndpoint {path: $path, http_method: $http_method})
                    SET
                        a.description = $description,
                        a.status = 'active',
                        a.created_at = $created_at
                    RETURN a.path
                """

                description = endpoint_info.get("summary", endpoint_info.get("description", ""))

                result = await session.run(
                    query,
                    path=path,
                    http_method=http_method.upper(),
                    description=description,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                await result.single()
                nodes_created += 1

                # Create DEFINES relationship: Requirement -> APIEndpoint
                link_query = """
                    MATCH (r:Requirement {req_id: $req_id})
                    MATCH (a:APIEndpoint {path: $path, http_method: $http_method})
                    MERGE (r)-[:DEFINES]->(a)
                """
                await session.run(
                    link_query,
                    req_id=req_id,
                    path=path,
                    http_method=http_method.upper(),
                )
                edges_created += 1

        logger.debug(f"[K14] API schema: +{nodes_created} nodes, +{edges_created} edges")
        return nodes_created, edges_created

    async def _process_erd(
        self,
        session: AsyncSession,
        req_id: str,
        erd: Dict[str, Any]
    ) -> tuple:
        """Process Entity-Relationship Diagram to create Database nodes and relationships.

        Args:
            session: Neo4j async session
            req_id: Requirement ID
            erd: ERD dict with 'entities' and 'relationships'

        Returns:
            Tuple of (nodes_created, edges_created)
        """
        nodes_created = 0
        edges_created = 0

        # Create Database (table) nodes
        entities = erd.get("entities", [])
        logger.debug(f"[K14] Processing {len(entities)} ERD entities")

        for entity in entities:
            table_name = entity.get("name", "unknown")
            entity_type = entity.get("type", "table")

            # Create Database node
            query = """
                MERGE (d:Database {name: $table_name})
                SET
                    d.type = $db_type,
                    d.schema = $schema,
                    d.description = $description,
                    d.created_at = $created_at
                RETURN d.name
            """

            result = await session.run(
                query,
                table_name=table_name,
                db_type=entity_type,
                schema=entity.get("schema", "public"),
                description=entity.get("description", ""),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            await result.single()
            nodes_created += 1

            # Create CREATES relationship: Requirement -> Database
            link_query = """
                MATCH (r:Requirement {req_id: $req_id})
                MATCH (d:Database {name: $table_name})
                MERGE (r)-[:CREATES]->(d)
            """
            await session.run(
                link_query,
                req_id=req_id,
                table_name=table_name,
            )
            edges_created += 1

        # Process foreign key relationships
        relationships = erd.get("relationships", [])
        logger.debug(f"[K14] Processing {len(relationships)} ERD relationships (FK)")

        for rel in relationships:
            from_table = rel.get("from", rel.get("source"))
            to_table = rel.get("to", rel.get("target"))
            rel_type = rel.get("type", "foreign_key")

            if not from_table or not to_table:
                logger.warning(f"[K14] Skipping incomplete relationship: {rel}")
                continue

            # Create DEPENDS_ON relationship between tables
            query = """
                MATCH (t1:Database {name: $from_table})
                MATCH (t2:Database {name: $to_table})
                MERGE (t1)-[:DEPENDS_ON {type: $rel_type}]->(t2)
            """

            await session.run(
                query,
                from_table=from_table,
                to_table=to_table,
                rel_type=rel_type,
            )
            edges_created += 1

        logger.debug(f"[K14] ERD: +{nodes_created} nodes, +{edges_created} edges")
        return nodes_created, edges_created

    # ========================================================================
    # Dependency Querying
    # ========================================================================

    async def query_dependencies(
        self,
        entity_name: str,
        depth: int = 2,
        entity_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query dependency paths for an entity using breadth-first traversal.

        Args:
            entity_name: Entity identifier (path, table name, req_id, etc.)
            depth: Maximum traversal depth (default 2)
            entity_type: Optional filter (APIEndpoint, Database, Requirement, etc.)

        Returns:
            List of path dicts, each containing:
                - path: List of node dicts with id, type, name
                - length: Path length
        """
        logger.debug(f"[K14] Querying dependencies for {entity_name} (depth={depth})")

        try:
            async with self.driver.session() as session:
                # Build the match clause based on entity type
                match_clause = self._build_entity_match_clause(entity_name, entity_type)

                query = f"""
                    {match_clause}
                    OPTIONAL MATCH path = (start)-[:DEPENDS_ON|DEFINES|CREATES|QUERIES|CALLS*1..{depth}]->(end)
                    RETURN
                        COLLECT({{
                            nodes: [n IN nodes(path) | {{
                                id: COALESCE(n.req_id, n.path, n.name, 'unknown'),
                                type: labels(n)[0],
                                name: COALESCE(n.name, n.path, n.title, 'unknown')
                            }}],
                            length: length(path)
                        }}) as paths
                """

                result = await session.run(query)
                record = await result.single()

                if not record:
                    logger.warning(f"[K14] No dependencies found for {entity_name}")
                    return []

                paths = record.get("paths", [])
                logger.debug(f"[K14] Found {len(paths)} dependency paths")
                return paths

        except Exception as e:
            logger.error(f"[K14] Dependency query failed: {str(e)}", exc_info=True)
            return []

    async def query_full_graph(
        self,
        req_id: str,
        depth: int = 3
    ) -> Dict[str, Any]:
        """Query the complete topology graph for a requirement.

        Args:
            req_id: Requirement ID
            depth: Maximum traversal depth

        Returns:
            Dict with:
                - req_id: Requirement ID
                - nodes: List of all nodes (Requirement, APIEndpoint, Database, etc.)
                - edges: List of all relationships
                - summary: Statistics
        """
        logger.debug(f"[K14] Querying full graph for req_id={req_id} (depth={depth})")

        try:
            async with self.driver.session() as session:
                # Query all connected nodes
                query = """
                    MATCH (req:Requirement {req_id: $req_id})
                    OPTIONAL MATCH path = (req)-[r:DEFINES|CREATES|DEPENDS_ON*1..$depth]->(connected)
                    WITH req,
                         collect(DISTINCT connected) as connected_nodes,
                         collect(DISTINCT r) as relationships

                    RETURN
                        req {.req_id, .title, .description, .status, .created_at},
                        [n IN connected_nodes |
                            CASE
                                WHEN n:APIEndpoint THEN n {.path, .http_method, .description}
                                WHEN n:Database THEN n {.name, .type, .schema}
                                WHEN n:Module THEN n {.path, .language, .type}
                                WHEN n:Service THEN n {.name, .type}
                                ELSE n {id: COALESCE(n.id, 'unknown')}
                            END
                        ] as nodes,
                        relationships
                """

                result = await session.run(query, req_id=req_id, depth=depth)
                record = await result.single()

                if not record:
                    logger.warning(f"[K14] No graph found for req_id={req_id}")
                    return {"req_id": req_id, "nodes": [], "edges": [], "summary": {}}

                req_node = record.get("req", {})
                connected_nodes = record.get("nodes", [])
                relationships = record.get("relationships", [])

                # Build edges list
                edges = [
                    {
                        "from": rel.start_node.get("req_id") or rel.start_node.get("path") or rel.start_node.get("name"),
                        "to": rel.end_node.get("req_id") or rel.end_node.get("path") or rel.end_node.get("name"),
                        "type": rel.type,
                        "properties": dict(rel)
                    }
                    for rel in relationships
                ]

                summary = {
                    "total_nodes": len(connected_nodes) + 1,  # +1 for requirement
                    "total_edges": len(edges),
                    "api_endpoints": len([n for n in connected_nodes if "APIEndpoint" in str(type(n))]),
                    "databases": len([n for n in connected_nodes if "Database" in str(type(n))]),
                }

                logger.debug(f"[K14] Graph query complete: {summary}")

                return {
                    "req_id": req_id,
                    "requirement": req_node,
                    "nodes": connected_nodes,
                    "edges": edges,
                    "summary": summary,
                }

        except Exception as e:
            logger.error(f"[K14] Full graph query failed: {str(e)}", exc_info=True)
            return {"req_id": req_id, "nodes": [], "edges": [], "error": str(e)}

    # ========================================================================
    # Helper Methods
    # ========================================================================

    @staticmethod
    def _build_entity_match_clause(entity_name: str, entity_type: Optional[str]) -> str:
        """Build a Cypher MATCH clause to locate the starting entity.

        Args:
            entity_name: Entity identifier
            entity_type: Optional label filter

        Returns:
            Cypher MATCH clause string
        """
        if entity_type:
            return f"MATCH (start:{entity_type}) WHERE start.req_id = '{entity_name}' OR start.path = '{entity_name}' OR start.name = '{entity_name}'"
        else:
            return (
                f"MATCH (start) WHERE "
                f"start.req_id = '{entity_name}' OR "
                f"start.path = '{entity_name}' OR "
                f"start.name = '{entity_name}'"
            )


# ============================================================================
# Standalone convenience functions
# ============================================================================

async def build_topology_for_requirement(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    req_id: str,
    api_schema: Dict[str, Any],
    erd: Dict[str, Any],
    requirement_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Convenience function to build topology and return result."""
    topology = DependencyTopology(neo4j_uri, neo4j_user, neo4j_password)
    try:
        result = await topology.build_topology(req_id, api_schema, erd, requirement_context)
        return result
    finally:
        await topology.close()


async def query_entity_dependencies(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    entity_name: str,
    depth: int = 2
) -> List[Dict[str, Any]]:
    """Convenience function to query dependencies."""
    topology = DependencyTopology(neo4j_uri, neo4j_user, neo4j_password)
    try:
        return await topology.query_dependencies(entity_name, depth)
    finally:
        await topology.close()
