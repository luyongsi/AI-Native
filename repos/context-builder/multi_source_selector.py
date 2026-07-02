"""Enhanced context selector with multi-source candidate integration."""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from context_item import ContextItem, SelectResult
from embedder import Embedder
from sources import PostgresSource, Neo4jSource, VectorSource

logger = logging.getLogger(__name__)


# Prometheus-style metrics (simple in-memory implementation)
class SelectMetrics:
    """Simple metrics collector for SELECT stage."""

    def __init__(self):
        self.candidates_total = 0
        self.candidates_deduped = 0
        self.candidates_final = 0
        self.select_duration_ms = 0
        self.source_counts = defaultdict(int)

    def record_candidates(self, source: str, count: int):
        """Record candidates from a source."""
        self.candidates_total += count
        self.source_counts[source] += count

    def record_deduped(self, count: int):
        """Record deduped candidates."""
        self.candidates_deduped += count

    def record_final(self, count: int):
        """Record final candidate count."""
        self.candidates_final += count

    def record_duration(self, duration_ms: float):
        """Record SELECT stage duration."""
        self.select_duration_ms = duration_ms

    def to_dict(self) -> dict:
        """Convert metrics to dictionary."""
        return {
            'context_builder_select_candidates_total': self.candidates_total,
            'context_builder_select_candidates_deduped': self.candidates_deduped,
            'context_builder_select_candidates_final': self.candidates_final,
            'context_builder_select_duration_ms': self.select_duration_ms,
            'source_counts': dict(self.source_counts),
        }


class MultiSourceSelector:
    """Enhanced selector combining multiple data sources with deduplication."""

    def __init__(self, db_config: Dict, embedder: Embedder, neo4j_config: Optional[Dict] = None):
        """Initialize multi-source selector.

        Args:
            db_config: PostgreSQL config
            embedder: Embedder instance
            neo4j_config: Optional Neo4j config
        """
        self.db_config = db_config
        self.embedder = embedder
        self.neo4j_config = neo4j_config or {}
        self.metrics = SelectMetrics()

        # Initialize sources
        self.postgres_source = PostgresSource(db_config)
        self.neo4j_source = Neo4jSource(neo4j_config) if neo4j_config else None
        self.vector_source = VectorSource(db_config)

    async def select_async(
        self,
        target_agent: str,
        req_id: str = "",
        task_id: str = "",
        max_tokens: int = 8000,
        query_text: str = "",
    ) -> SelectResult:
        """Async multi-source SELECT stage.

        Args:
            target_agent: Agent identifier
            req_id: Requirement ID
            task_id: Task ID
            max_tokens: Token budget
            query_text: Optional query text

        Returns:
            SelectResult with merged and deduplicated candidates
        """
        start_time = time.time()

        try:
            # Query all sources in parallel
            postgres_candidates = await self.postgres_source.query(req_id)
            vector_candidates = await self.vector_source.query(req_id, query_text)

            # Neo4j query (optional)
            neo4j_candidates = []
            if self.neo4j_source:
                neo4j_candidates = await self.neo4j_source.query(req_id)

            # Record source metrics
            self.metrics.record_candidates('postgres', len(postgres_candidates))
            self.metrics.record_candidates('vector', len(vector_candidates))
            if neo4j_candidates:
                self.metrics.record_candidates('neo4j', len(neo4j_candidates))

            logger.info(f"SELECT: postgres={len(postgres_candidates)}, "
                       f"vector={len(vector_candidates)}, neo4j={len(neo4j_candidates)}")

            # Merge and deduplicate candidates
            merged_candidates = self._merge_and_deduplicate(
                postgres_candidates + vector_candidates + neo4j_candidates
            )

            self.metrics.record_deduped(
                len(postgres_candidates) + len(vector_candidates) + len(neo4j_candidates) - len(merged_candidates)
            )

            # Convert to ContextItems with token accounting
            items, tokens_used, discarded = self._build_items(merged_candidates, max_tokens)

            self.metrics.record_final(len(items))
            self.metrics.record_duration((time.time() - start_time) * 1000)

            return SelectResult(
                items=items,
                tokens_used=tokens_used,
                discarded=discarded,
            )

        except Exception as e:
            logger.error(f"Multi-source SELECT failed: {e}")
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_duration(duration_ms)
            return SelectResult(items=[], tokens_used=0, discarded=0)

    def _merge_and_deduplicate(self, candidates: List[Dict]) -> List[Dict]:
        """Merge candidates from multiple sources and deduplicate.

        Deduplication strategy:
        - Group by source_id + source
        - Keep highest relevance score
        - Merge metadata tags

        Args:
            candidates: List of raw candidates from all sources

        Returns:
            Deduplicated and merged candidates
        """
        merged = {}

        for candidate in candidates:
            source_id = candidate.get('source_id', '')
            source = candidate.get('source', '')
            key = (source_id, source)

            if key not in merged:
                merged[key] = candidate
            else:
                # Keep higher relevance score
                if candidate.get('relevance', 0) > merged[key].get('relevance', 0):
                    merged[key]['relevance'] = candidate['relevance']

                # Merge metadata
                if 'metadata' in candidate and 'metadata' in merged[key]:
                    merged[key]['metadata'].update(candidate['metadata'])

                # Tag as duplicate
                if 'tags' not in merged[key]:
                    merged[key]['tags'] = []
                merged[key]['tags'].append(f'dup_from_{source}')

        # Sort by relevance descending
        result = list(merged.values())
        result.sort(key=lambda x: x.get('relevance', 0), reverse=True)

        return result

    def _build_items(
        self,
        candidates: List[Dict],
        max_tokens: int,
    ) -> Tuple[List[ContextItem], int, int]:
        """Convert candidates to ContextItems with token accounting.

        Args:
            candidates: Merged and deduplicated candidates
            max_tokens: Token budget

        Returns:
            (items, tokens_used, discarded)
        """
        items = []
        tokens_remaining = max_tokens
        discarded = 0

        for candidate in candidates:
            # Estimate tokens
            content = candidate.get('content', '')
            title = candidate.get('title', '')
            full_text = f"{title}\n{content}"
            estimated_tokens = max(1, len(full_text) // 3)  # ~3 chars/token

            # Build ContextItem
            item = ContextItem(
                type=candidate.get('type', 'knowledge'),
                content=content,
                relevance=candidate.get('relevance', 0.5),
                position='mid',  # Will be refined by ContextOrderer
                tokens=estimated_tokens,
                file=candidate.get('metadata', {}).get('file'),
                compressed=False,
            )

            # Attach source metadata
            item.source = candidate.get('source', '')
            item.source_id = candidate.get('source_id', '')
            item.tags = candidate.get('tags', [])

            if estimated_tokens <= tokens_remaining:
                items.append(item)
                tokens_remaining -= estimated_tokens
            else:
                discarded += 1

        return items, max_tokens - tokens_remaining, discarded

    async def close(self):
        """Close all source connections."""
        await self.postgres_source.close()
        await self.vector_source.close()
        if self.neo4j_source:
            await self.neo4j_source.close()

    def get_metrics(self) -> dict:
        """Get SELECT stage metrics."""
        return self.metrics.to_dict()
