"""Neo4j data source for querying dependency topology and service call relationships."""

import asyncio
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class Neo4jSource:
    """Query Neo4j for dependency topology and service call relationships.

    This source provides:
    - Dependency graph traversal (upstream and downstream dependencies)
    - Service-to-service call relationships
    - Code module dependencies
    - Related microservice contexts
    """

    def __init__(self, neo4j_config: Dict[str, Any]):
        """Initialize Neo4j source.

        Args:
            neo4j_config: Neo4j connection config with keys:
                - uri: Neo4j connection URI (e.g., 'neo4j://localhost:7687')
                - username: Neo4j username
                - password: Neo4j password
        """
        self.neo4j_config = neo4j_config
        self._driver = None

    def _get_driver(self):
        """Get or create Neo4j driver."""
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
                self._driver = GraphDatabase.driver(
                    self.neo4j_config.get('uri', 'neo4j://localhost:7687'),
                    auth=(
                        self.neo4j_config.get('username', 'neo4j'),
                        self.neo4j_config.get('password', 'password')
                    )
                )
            except Exception as e:
                logger.error(f"Failed to initialize Neo4j driver: {e}")
        return self._driver

    async def query(self, req_id: str) -> List[Dict[str, Any]]:
        """Query dependency topology and service relationships.

        Args:
            req_id: Requirement identifier

        Returns:
            List of candidate context items from Neo4j dependency graph
        """
        candidates = []
        try:
            driver = self._get_driver()
            if driver is None:
                logger.warning("Neo4j driver not available, skipping Neo4j queries")
                return candidates

            with driver.session() as session:
                # Query 1: Upstream dependencies
                upstream_deps = await self._query_upstream_dependencies(session, req_id)
                candidates.extend(upstream_deps)

                # Query 2: Downstream dependencies
                downstream_deps = await self._query_downstream_dependencies(session, req_id)
                candidates.extend(downstream_deps)

                # Query 3: Service call relationships
                service_calls = await self._query_service_calls(session, req_id)
                candidates.extend(service_calls)

        except Exception as e:
            logger.error(f"Neo4j query failed for req_id={req_id}: {e}")
            # Return empty list on error to allow fallback to other sources

        return candidates

    async def _query_upstream_dependencies(self, session: Any, req_id: str) -> List[Dict[str, Any]]:
        """Query upstream dependencies (services that this service depends on).

        Args:
            session: Neo4j session
            req_id: Requirement identifier

        Returns:
            List of upstream dependency items
        """
        try:
            result = session.run("""
                MATCH (service:Service {req_id: $req_id})-[:DEPENDS_ON*1..3]->(dep:Service)
                RETURN DISTINCT
                    dep.id as id,
                    dep.name as name,
                    dep.description as description,
                    dep.api_schema as api_schema,
                    count(*) as path_count
                LIMIT 10
            """, req_id=req_id)

            candidates = []
            for record in result:
                candidates.append({
                    'source': 'neo4j_upstream_deps',
                    'source_id': record['id'],
                    'req_id': req_id,
                    'type': 'knowledge',
                    'title': f"Upstream Service: {record['name']}",
                    'content': f"{record['description'] or ''}\n\nAPI Schema:\n{record['api_schema'] or ''}",
                    'metadata': {
                        'service_name': record['name'],
                        'path_count': record['path_count'],
                    },
                    'relevance': 0.7,  # Moderate relevance for upstream deps
                })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query upstream dependencies: {e}")
            return []

    async def _query_downstream_dependencies(self, session: Any, req_id: str) -> List[Dict[str, Any]]:
        """Query downstream dependencies (services that depend on this service).

        Args:
            session: Neo4j session
            req_id: Requirement identifier

        Returns:
            List of downstream dependency items
        """
        try:
            result = session.run("""
                MATCH (service:Service {req_id: $req_id})<-[:DEPENDS_ON*1..3]-(dep:Service)
                RETURN DISTINCT
                    dep.id as id,
                    dep.name as name,
                    dep.description as description,
                    dep.api_schema as api_schema,
                    count(*) as path_count
                LIMIT 10
            """, req_id=req_id)

            candidates = []
            for record in result:
                candidates.append({
                    'source': 'neo4j_downstream_deps',
                    'source_id': record['id'],
                    'req_id': req_id,
                    'type': 'knowledge',
                    'title': f"Downstream Service: {record['name']}",
                    'content': f"{record['description'] or ''}\n\nAPI Schema:\n{record['api_schema'] or ''}",
                    'metadata': {
                        'service_name': record['name'],
                        'path_count': record['path_count'],
                    },
                    'relevance': 0.65,  # Moderate relevance for downstream deps
                })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query downstream dependencies: {e}")
            return []

    async def _query_service_calls(self, session: Any, req_id: str) -> List[Dict[str, Any]]:
        """Query service-to-service call relationships.

        Args:
            session: Neo4j session
            req_id: Requirement identifier

        Returns:
            List of service call relationship items
        """
        try:
            result = session.run("""
                MATCH (service:Service {req_id: $req_id})-[call:CALLS]->(target:Service)
                RETURN
                    call.method as method,
                    call.endpoint as endpoint,
                    call.response_schema as response_schema,
                    target.id as target_id,
                    target.name as target_name,
                    call.frequency as frequency
                LIMIT 15
            """, req_id=req_id)

            candidates = []
            for record in result:
                candidates.append({
                    'source': 'neo4j_service_calls',
                    'source_id': f"{record['target_id']}_call",
                    'req_id': req_id,
                    'type': 'knowledge',
                    'title': f"Service Call: {record['method']} {record['endpoint']}",
                    'content': f"Target Service: {record['target_name']}\n\nResponse Schema:\n{record['response_schema'] or ''}",
                    'metadata': {
                        'method': record['method'],
                        'endpoint': record['endpoint'],
                        'target_service': record['target_name'],
                        'frequency': record['frequency'],
                    },
                    'relevance': 0.72,  # Good relevance for direct service calls
                })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query service calls: {e}")
            return []

    async def close(self):
        """Close Neo4j driver."""
        if self._driver:
            self._driver.close()
