"""
mc-backend/api/knowledge_topology.py — Neo4j Knowledge Graph Visualization API

Provides REST endpoints for querying and visualizing the Neo4j topology:
  - GET /api/knowledge-topology/{req_id} — Full requirement topology graph
  - GET /api/knowledge-topology/impact/{entity_name} — Change impact analysis
  - GET /api/knowledge-topology/trace/{entity_name} — Dependency propagation tracing

Integrates K14 (DependencyTopology) and K15 (ChangePropagation) for graph queries.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from k14.dependency_topology import DependencyTopology
from k15.change_propagation import ChangePropagation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-topology", tags=["knowledge-topology"])

# Neo4j configuration
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://172.27.78.109:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "ai-native-2026")


# ============================================================================
# K14: Dependency Topology Endpoints
# ============================================================================

@router.get("/{req_id}")
async def get_topology(
    req_id: str,
    depth: int = Query(3, ge=1, le=10)
) -> Dict[str, Any]:
    """Get the complete dependency topology for a requirement.

    Args:
        req_id: Requirement ID (UUID)
        depth: Maximum traversal depth (1-10, default 3)

    Returns:
        Topology graph dict with:
            - req_id: Requirement ID
            - requirement: Requirement node details
            - nodes: List of all nodes (APIEndpoint, Database, etc.)
            - edges: List of relationships
            - summary: Statistics

    Example:
        GET /api/knowledge-topology/req-uuid-123?depth=2
    """
    logger.info(f"[API] Querying topology for req_id={req_id}, depth={depth}")

    try:
        topology = DependencyTopology(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            result = await topology.query_full_graph(req_id, depth=depth)

            if not result.get("requirement"):
                raise HTTPException(
                    status_code=404,
                    detail=f"Requirement {req_id} not found in topology"
                )

            return result

        finally:
            await topology.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Topology query failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query topology: {str(e)}"
        )


@router.get("/{req_id}/dependencies")
async def get_req_dependencies(
    req_id: str,
    depth: int = Query(2, ge=1, le=5)
) -> Dict[str, Any]:
    """Get dependency paths from a requirement.

    Args:
        req_id: Requirement ID
        depth: Maximum path depth (1-5, default 2)

    Returns:
        Dict with:
            - req_id: Requirement ID
            - paths: List of dependency path dicts
            - total_paths: Count of paths
    """
    logger.info(f"[API] Querying dependencies for req_id={req_id}")

    try:
        topology = DependencyTopology(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            paths = await topology.query_dependencies(req_id, depth=depth)

            return {
                "req_id": req_id,
                "paths": paths,
                "total_paths": len(paths),
            }

        finally:
            await topology.close()

    except Exception as e:
        logger.error(f"[API] Dependency query failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query dependencies: {str(e)}"
        )


# ============================================================================
# K15: Change Impact Analysis Endpoints
# ============================================================================

@router.get("/impact/{entity_name}")
async def get_impact_analysis(
    entity_name: str,
    max_depth: int = Query(3, ge=1, le=10),
    entity_type: Optional[str] = None
) -> Dict[str, Any]:
    """Analyze downstream impact of a change to an entity.

    Args:
        entity_name: Entity identifier (path, table name, req_id, etc.)
        max_depth: Maximum traversal depth (1-10, default 3)
        entity_type: Optional filter (APIEndpoint, Database, Module, etc.)

    Returns:
        Impact analysis dict with:
            - changed_entity: Entity that changed
            - entity_type: Type of entity
            - affected_count: Number of affected entities
            - affected_nodes: List of affected nodes
            - risk_level: LOW | MEDIUM | HIGH | CRITICAL
            - impact_paths: Detailed propagation paths
            - timestamp: Analysis timestamp

    Example:
        GET /api/knowledge-topology/impact/users_table?max_depth=3
        GET /api/knowledge-topology/impact//api/users?entity_type=APIEndpoint
    """
    logger.info(f"[API] Analyzing impact for {entity_name}")

    try:
        propagation = ChangePropagation(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            impact = await propagation.analyze_impact(
                entity_name,
                max_depth=max_depth,
                entity_type=entity_type
            )

            return impact

        finally:
            await propagation.close()

    except Exception as e:
        logger.error(f"[API] Impact analysis failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze impact: {str(e)}"
        )


@router.post("/impact/batch")
async def batch_impact_analysis(
    entities: List[str] = Query(...),
    max_depth: int = Query(3, ge=1, le=10)
) -> Dict[str, Any]:
    """Analyze impact of multiple entity changes.

    Args:
        entities: List of entity identifiers (query param repeated)
        max_depth: Maximum traversal depth

    Returns:
        Batch analysis dict with:
            - total_changed: Number of changed entities
            - total_affected: Total unique affected entities
            - individual_impacts: List of impact dicts for each entity
            - combined_risk_level: Overall risk level
            - timestamp: Analysis timestamp

    Example:
        GET /api/knowledge-topology/impact/batch?entities=users_table&entities=posts_table&entities=/api/users
    """
    logger.info(f"[API] Batch impact analysis for {len(entities)} entities")

    try:
        propagation = ChangePropagation(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            batch_result = await propagation.analyze_batch_impact(entities, max_depth)
            return batch_result

        finally:
            await propagation.close()

    except Exception as e:
        logger.error(f"[API] Batch impact analysis failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze batch impact: {str(e)}"
        )


@router.get("/risk/{entity_name}")
async def calculate_risk(
    entity_name: str,
    change_type: str = Query("modification", regex="^(modification|deletion|addition)$")
) -> Dict[str, Any]:
    """Calculate comprehensive risk assessment for a change.

    Args:
        entity_name: Entity identifier
        change_type: Type of change (modification | deletion | addition)

    Returns:
        Risk assessment dict with:
            - overall_risk: LOW | MEDIUM | HIGH | CRITICAL
            - change_type: Type of change
            - affected_count: Number of affected entities
            - risk_factors: List of risk factors
            - recommendations: List of recommended actions
            - detailed_impact: Full impact analysis

    Example:
        GET /api/knowledge-topology/risk/critical_service?change_type=deletion
    """
    logger.info(f"[API] Calculating risk for {entity_name} ({change_type})")

    try:
        propagation = ChangePropagation(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            risk = await propagation.calculate_change_risk(
                entity_name,
                change_type=change_type
            )
            return risk

        finally:
            await propagation.close()

    except Exception as e:
        logger.error(f"[API] Risk calculation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate risk: {str(e)}"
        )


# ============================================================================
# Tracing Endpoints
# ============================================================================

@router.get("/trace/{entity_name}")
async def trace_propagation(
    entity_name: str,
    max_depth: int = Query(3, ge=1, le=10),
    include_reverse: bool = Query(False)
) -> Dict[str, Any]:
    """Trace detailed propagation paths for a changed entity.

    Shows how changes propagate through the dependency graph, both
    forward (downstream impacts) and reverse (upstream dependencies).

    Args:
        entity_name: Entity identifier
        max_depth: Maximum traversal depth
        include_reverse: Include reverse (upstream) paths

    Returns:
        Propagation trace dict with:
            - changed_entity: Entity identifier
            - forward_paths: Downstream propagation paths
            - reverse_paths: Upstream dependency paths (if requested)
            - path_count: Total number of paths
            - deepest_path_length: Maximum depth reached
            - timestamp: Trace timestamp

    Example:
        GET /api/knowledge-topology/trace/database_schema?max_depth=4&include_reverse=true
    """
    logger.info(f"[API] Tracing propagation for {entity_name}")

    try:
        propagation = ChangePropagation(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            trace = await propagation.trace_propagation_paths(
                entity_name,
                max_depth=max_depth,
                include_reverse=include_reverse
            )
            return trace

        finally:
            await propagation.close()

    except Exception as e:
        logger.error(f"[API] Propagation trace failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trace propagation: {str(e)}"
        )


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@router.get("/health")
async def topology_health() -> Dict[str, Any]:
    """Check Neo4j connection and topology service health.

    Returns:
        Health status dict with:
            - status: "healthy" | "unhealthy"
            - neo4j_connected: boolean
            - timestamp: Check timestamp
    """
    try:
        topology = DependencyTopology(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            # Try a simple query
            async with topology.driver.session() as session:
                result = await session.run("RETURN 1")
                await result.single()

            return {
                "status": "healthy",
                "neo4j_connected": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        finally:
            await topology.close()

    except Exception as e:
        logger.error(f"[API] Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "neo4j_connected": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ============================================================================
# Stats & Aggregation
# ============================================================================

@router.get("/stats/{req_id}")
async def get_topology_stats(req_id: str) -> Dict[str, Any]:
    """Get summary statistics for a requirement's topology.

    Args:
        req_id: Requirement ID

    Returns:
        Statistics dict with:
            - req_id: Requirement ID
            - total_nodes: Total nodes in topology
            - total_edges: Total relationships
            - node_types: Count by type (APIEndpoint, Database, etc.)
            - edge_types: Count by relationship type
            - api_endpoints: Count of APIEndpoint nodes
            - databases: Count of Database nodes
    """
    logger.info(f"[API] Querying stats for req_id={req_id}")

    try:
        topology = DependencyTopology(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        try:
            graph = await topology.query_full_graph(req_id, depth=10)
            summary = graph.get("summary", {})

            # Aggregate node types
            node_types = {}
            for node in graph.get("nodes", []):
                node_type = node.get("type", "unknown")
                node_types[node_type] = node_types.get(node_type, 0) + 1

            # Aggregate edge types
            edge_types = {}
            for edge in graph.get("edges", []):
                rel_type = edge.get("type", "unknown")
                edge_types[rel_type] = edge_types.get(rel_type, 0) + 1

            return {
                "req_id": req_id,
                "total_nodes": summary.get("total_nodes", 0),
                "total_edges": summary.get("total_edges", 0),
                "node_types": node_types,
                "edge_types": edge_types,
                "api_endpoints": summary.get("api_endpoints", 0),
                "databases": summary.get("databases", 0),
            }

        finally:
            await topology.close()

    except Exception as e:
        logger.error(f"[API] Stats query failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query stats: {str(e)}"
        )
