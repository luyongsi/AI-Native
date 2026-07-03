"""PostgreSQL data source for querying requirement history, associated PRs, and existing specs."""

import asyncio
import logging
from typing import List, Dict, Any, Optional
import asyncpg

logger = logging.getLogger(__name__)


class PostgresSource:
    """Query PostgreSQL for requirement history, related PRs, and existing specs.

    This source provides:
    - Requirement history and related context
    - Associated PRs and their metadata
    - Existing specs and specifications
    - Related task records
    """

    def __init__(self, db_config: Dict[str, Any]):
        """Initialize PostgreSQL source.

        Args:
            db_config: Database connection config with keys:
                - host: PostgreSQL hostname
                - port: PostgreSQL port (default 5432)
                - database: Database name
                - user: Database user
                - password: Database password
        """
        self.db_config = db_config
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                host=self.db_config.get('host', 'localhost'),
                port=self.db_config.get('port', 5432),
                database=self.db_config.get('database', 'ai_native'),
                user=self.db_config.get('user', 'ai_native'),
                password=self.db_config.get('password', 'ai_native_dev'),
                min_size=1,
                max_size=5,
            )
        return self._pool

    async def query(self, req_id: str) -> List[Dict[str, Any]]:
        """Query requirement history, related PRs, specs, and test assets.

        Args:
            req_id: Requirement identifier

        Returns:
            List of candidate context items from PostgreSQL sources
        """
        candidates = []
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # Query 1: Requirement history
                req_history = await self._query_requirement_history(conn, req_id)
                candidates.extend(req_history)

                # Query 2: Related PRs
                related_prs = await self._query_related_prs(conn, req_id)
                candidates.extend(related_prs)

                # Query 3: Existing specs
                existing_specs = await self._query_existing_specs(conn, req_id)
                candidates.extend(existing_specs)

                # Query 4: Test Assets (NEW - highest priority for A9)
                test_assets = await self._query_test_assets(conn, req_id)
                candidates.extend(test_assets)

        except Exception as e:
            logger.error(f"PostgreSQL query failed for req_id={req_id}: {e}")
            # Return empty list on error to allow fallback to other sources

        return candidates

    async def _query_requirement_history(self, conn: asyncpg.Connection, req_id: str) -> List[Dict[str, Any]]:
        """Query requirement history from requirements table.

        Args:
            conn: Database connection
            req_id: Requirement identifier

        Returns:
            List of requirement history items
        """
        try:
            rows = await conn.fetch("""
                SELECT
                    id,
                    req_id,
                    title,
                    description,
                    version,
                    created_at,
                    updated_at,
                    status
                FROM requirements
                WHERE req_id = $1 OR related_req_ids @> $2
                ORDER BY version DESC
                LIMIT 10
            """, req_id, f'["{req_id}"]')

            candidates = []
            for row in rows:
                candidates.append({
                    'source': 'postgres_requirements',
                    'source_id': str(row['id']),
                    'req_id': row['req_id'],
                    'type': 'spec',
                    'title': row['title'] or '',
                    'content': row['description'] or '',
                    'metadata': {
                        'version': row['version'],
                        'status': row['status'],
                        'created_at': str(row['created_at']),
                        'updated_at': str(row['updated_at']),
                    },
                    'relevance': 0.8,  # High relevance for direct requirement matches
                })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query requirement history: {e}")
            return []

    async def _query_related_prs(self, conn: asyncpg.Connection, req_id: str) -> List[Dict[str, Any]]:
        """Query related PRs from pull_requests table.

        Args:
            conn: Database connection
            req_id: Requirement identifier

        Returns:
            List of related PR items
        """
        try:
            rows = await conn.fetch("""
                SELECT
                    id,
                    pr_number,
                    title,
                    description,
                    state,
                    created_at,
                    merged_at,
                    related_req_ids
                FROM pull_requests
                WHERE related_req_ids @> $1
                ORDER BY merged_at DESC NULLS LAST
                LIMIT 15
            """, f'["{req_id}"]')

            candidates = []
            for row in rows:
                candidates.append({
                    'source': 'postgres_prs',
                    'source_id': str(row['id']),
                    'req_id': req_id,
                    'type': 'code',
                    'title': f"PR #{row['pr_number']}: {row['title']}",
                    'content': row['description'] or '',
                    'metadata': {
                        'pr_number': row['pr_number'],
                        'state': row['state'],
                        'created_at': str(row['created_at']),
                        'merged_at': str(row['merged_at']) if row['merged_at'] else None,
                    },
                    'relevance': 0.75,  # High relevance for related PRs
                })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query related PRs: {e}")
            return []

    async def _query_existing_specs(self, conn: asyncpg.Connection, req_id: str) -> List[Dict[str, Any]]:
        """Query existing specs from specifications table.

        Args:
            conn: Database connection
            req_id: Requirement identifier

        Returns:
            List of existing spec items
        """
        try:
            rows = await conn.fetch("""
                SELECT
                    id,
                    req_id,
                    title,
                    content,
                    spec_type,
                    created_at,
                    updated_at
                FROM specifications
                WHERE req_id = $1 OR related_req_ids @> $2
                ORDER BY updated_at DESC
                LIMIT 10
            """, req_id, f'["{req_id}"]')

            candidates = []
            for row in rows:
                candidates.append({
                    'source': 'postgres_specs',
                    'source_id': str(row['id']),
                    'req_id': row['req_id'],
                    'type': 'spec',
                    'title': row['title'] or '',
                    'content': row['content'] or '',
                    'metadata': {
                        'spec_type': row['spec_type'],
                        'created_at': str(row['created_at']),
                        'updated_at': str(row['updated_at']),
                    },
                    'relevance': 0.85,  # High relevance for existing specs
                })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query existing specs: {e}")
            return []

    async def _query_test_assets(self, conn: asyncpg.Connection, req_id: str) -> List[Dict[str, Any]]:
        """Query test assets from test_assets table for TDD injection into A9 context.

        Args:
            conn: Database connection
            req_id: Requirement identifier

        Returns:
            List of test asset items (highest priority)
        """
        try:
            rows = await conn.fetch("""
                SELECT
                    id,
                    req_id,
                    unit_tests,
                    integration_tests,
                    e2e_tests,
                    visual_tests,
                    coverage_targets,
                    total_cases,
                    priority_distribution,
                    source,
                    created_at
                FROM test_assets
                WHERE req_id = $1
                ORDER BY created_at DESC
                LIMIT 1
            """, req_id)

            candidates = []
            for row in rows:
                # Parse JSONB fields
                import json
                unit_tests = json.loads(row['unit_tests']) if row['unit_tests'] else []
                integration_tests = json.loads(row['integration_tests']) if row['integration_tests'] else []
                e2e_tests = json.loads(row['e2e_tests']) if row['e2e_tests'] else []
                visual_tests = json.loads(row['visual_tests']) if row['visual_tests'] else []
                coverage_targets = json.loads(row['coverage_targets']) if row['coverage_targets'] else {}

                # Create comprehensive test assets object
                test_assets_obj = {
                    'unit_tests': unit_tests,
                    'integration_tests': integration_tests,
                    'e2e_tests': e2e_tests,
                    'visual_tests': visual_tests,
                    'coverage_targets': coverage_targets,
                    'total_cases': row['total_cases'],
                    'priority_distribution': json.loads(row['priority_distribution']) if row['priority_distribution'] else {},
                }

                candidates.append({
                    'source': 'postgres_test_assets',
                    'source_id': str(row['id']),
                    'req_id': req_id,
                    'type': 'test_assets',
                    'title': f"Test Assets: {row['total_cases']} cases ({row['source']})",
                    'content': json.dumps(test_assets_obj, ensure_ascii=False),
                    'test_assets': test_assets_obj,  # Structured data for A9 consumption
                    'metadata': {
                        'total_cases': row['total_cases'],
                        'source': row['source'],
                        'coverage_targets': coverage_targets,
                        'created_at': str(row['created_at']),
                    },
                    'relevance': 1.0,  # Highest priority - test assets must be in context
                })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query test assets: {e}")
            return []


    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
