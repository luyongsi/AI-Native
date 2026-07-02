"""pgvector data source for semantic similarity search and historical knowledge retrieval."""

import logging
from typing import List, Dict, Any, Optional
import asyncpg

logger = logging.getLogger(__name__)


class VectorSource:
    """Query pgvector for semantic similarity and historical knowledge.

    This source provides:
    - Semantic similarity search across requirement descriptions
    - Historical knowledge and design decisions
    - Similar resolved requirements
    - Related documentation and patterns
    """

    def __init__(self, db_config: Dict[str, Any]):
        """Initialize vector source with pgvector support.

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
        self._embedder = None

    def _get_embedder(self):
        """Get embedder instance."""
        if self._embedder is None:
            try:
                from embedder import get_embedder
                self._embedder = get_embedder()
            except ImportError:
                logger.error("Failed to import embedder")
        return self._embedder

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

    async def query(self, req_id: str, query_text: str = "") -> List[Dict[str, Any]]:
        """Query for semantically similar requirements and knowledge.

        Args:
            req_id: Requirement identifier
            query_text: Optional query text for semantic search

        Returns:
            List of candidate context items from vector similarity search
        """
        candidates = []
        try:
            embedder = self._get_embedder()
            if embedder is None:
                logger.warning("Embedder not available, skipping vector queries")
                return candidates

            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # Query 1: Similar requirements
                similar_reqs = await self._query_similar_requirements(
                    conn, embedder, req_id, query_text
                )
                candidates.extend(similar_reqs)

                # Query 2: Historical knowledge
                historical_knowledge = await self._query_historical_knowledge(
                    conn, embedder, req_id, query_text
                )
                candidates.extend(historical_knowledge)

                # Query 3: Design patterns and decisions
                design_patterns = await self._query_design_patterns(
                    conn, embedder, req_id, query_text
                )
                candidates.extend(design_patterns)

        except Exception as e:
            logger.error(f"Vector query failed for req_id={req_id}: {e}")
            # Return empty list on error to allow fallback to other sources

        return candidates

    async def _query_similar_requirements(
        self,
        conn: asyncpg.Connection,
        embedder: Any,
        req_id: str,
        query_text: str,
    ) -> List[Dict[str, Any]]:
        """Query semantically similar requirements.

        Args:
            conn: Database connection
            embedder: Embedder instance
            req_id: Requirement identifier
            query_text: Query text for similarity search

        Returns:
            List of similar requirement items
        """
        try:
            search_text = query_text or f"requirement {req_id}"
            query_embedding = embedder.embed(search_text)
            embedding_str = f"[{','.join(f'{v:.8f}' for v in query_embedding)}]"

            rows = await conn.fetch("""
                SELECT
                    id,
                    req_id,
                    title,
                    description,
                    status,
                    created_at,
                    updated_at,
                    1.0 - (embedding <=> $1::vector) as similarity
                FROM requirements
                WHERE req_id != $2
                ORDER BY embedding <=> $1::vector
                LIMIT 8
            """, embedding_str, req_id)

            candidates = []
            for row in rows:
                similarity = 1.0 - (row['similarity'] or 0.0)
                # Only include if similarity is reasonably high
                if similarity > 0.5:
                    candidates.append({
                        'source': 'vector_similar_reqs',
                        'source_id': str(row['id']),
                        'req_id': row['req_id'],
                        'type': 'knowledge',
                        'title': f"Similar Requirement: {row['title']}",
                        'content': row['description'] or '',
                        'metadata': {
                            'status': row['status'],
                            'created_at': str(row['created_at']),
                            'updated_at': str(row['updated_at']),
                            'similarity': round(similarity, 4),
                        },
                        'relevance': max(0.6, similarity),  # Use similarity as relevance, min 0.6
                    })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query similar requirements: {e}")
            return []

    async def _query_historical_knowledge(
        self,
        conn: asyncpg.Connection,
        embedder: Any,
        req_id: str,
        query_text: str,
    ) -> List[Dict[str, Any]]:
        """Query historical knowledge and design decisions.

        Args:
            conn: Database connection
            embedder: Embedder instance
            req_id: Requirement identifier
            query_text: Query text for similarity search

        Returns:
            List of historical knowledge items
        """
        try:
            search_text = query_text or f"requirement {req_id}"
            query_embedding = embedder.embed(search_text)
            embedding_str = f"[{','.join(f'{v:.8f}' for v in query_embedding)}]"

            rows = await conn.fetch("""
                SELECT
                    id,
                    title,
                    content,
                    knowledge_type,
                    created_at,
                    updated_at,
                    1.0 - (embedding <=> $1::vector) as similarity
                FROM knowledge_base
                WHERE knowledge_type IN ('design_decision', 'architectural_pattern', 'best_practice')
                ORDER BY embedding <=> $1::vector
                LIMIT 10
            """, embedding_str)

            candidates = []
            for row in rows:
                similarity = 1.0 - (row['similarity'] or 0.0)
                if similarity > 0.45:
                    candidates.append({
                        'source': 'vector_historical_knowledge',
                        'source_id': str(row['id']),
                        'req_id': req_id,
                        'type': 'knowledge',
                        'title': f"{row['knowledge_type']}: {row['title']}",
                        'content': row['content'] or '',
                        'metadata': {
                            'knowledge_type': row['knowledge_type'],
                            'created_at': str(row['created_at']),
                            'updated_at': str(row['updated_at']),
                            'similarity': round(similarity, 4),
                        },
                        'relevance': max(0.55, similarity * 0.9),  # Slightly lower weight for historical
                    })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query historical knowledge: {e}")
            return []

    async def _query_design_patterns(
        self,
        conn: asyncpg.Connection,
        embedder: Any,
        req_id: str,
        query_text: str,
    ) -> List[Dict[str, Any]]:
        """Query design patterns and related solutions.

        Args:
            conn: Database connection
            embedder: Embedder instance
            req_id: Requirement identifier
            query_text: Query text for similarity search

        Returns:
            List of design pattern items
        """
        try:
            search_text = query_text or f"requirement {req_id}"
            query_embedding = embedder.embed(search_text)
            embedding_str = f"[{','.join(f'{v:.8f}' for v in query_embedding)}]"

            rows = await conn.fetch("""
                SELECT
                    id,
                    pattern_name,
                    description,
                    use_cases,
                    example_code,
                    created_at,
                    1.0 - (embedding <=> $1::vector) as similarity
                FROM design_patterns
                ORDER BY embedding <=> $1::vector
                LIMIT 8
            """, embedding_str)

            candidates = []
            for row in rows:
                similarity = 1.0 - (row['similarity'] or 0.0)
                if similarity > 0.50:
                    content = f"{row['description'] or ''}\n\nUse Cases: {row['use_cases'] or ''}\n\nExample:\n{row['example_code'] or ''}"
                    candidates.append({
                        'source': 'vector_design_patterns',
                        'source_id': str(row['id']),
                        'req_id': req_id,
                        'type': 'code',
                        'title': f"Design Pattern: {row['pattern_name']}",
                        'content': content,
                        'metadata': {
                            'pattern_name': row['pattern_name'],
                            'created_at': str(row['created_at']),
                            'similarity': round(similarity, 4),
                        },
                        'relevance': max(0.60, similarity * 0.85),  # Weight design patterns
                    })

            return candidates

        except Exception as e:
            logger.error(f"Failed to query design patterns: {e}")
            return []

    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
