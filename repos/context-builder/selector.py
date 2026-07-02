"""ContextSelector: hybrid semantic + full-text search via pgvector + PostgreSQL FTS."""

import json
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from context_item import ContextItem, SelectResult
from embedder import Embedder


# Agent-type -> preferred context types
AGENT_CONTEXT_MAP: Dict[str, List[str]] = {
    'A9':  ['code', 'doc'],               # Code generation agent -> code snippets
    'A2':  ['knowledge', 'doc', 'log'],   # RAG agent -> historical docs
    'A4':  ['prototype', 'spec', 'doc'],  # Prototype agent -> prototypes + specs
    'A1':  ['knowledge', 'spec', 'code'], # Default orchestrator
    'A3':  ['log', 'doc'],                # Audit agent
    'A5':  ['code', 'knowledge'],         # Review agent
    'A6':  ['spec', 'knowledge'],         # Planning agent
    'A7':  ['log', 'doc'],                # Monitoring agent
    'A8':  ['code', 'spec'],              # DevOps agent
    'A10': ['knowledge', 'code', 'doc'],  # Research agent
}

# Default context types when agent not in map
DEFAULT_CONTEXT_TYPES = ['knowledge', 'code', 'doc']

# Weights for hybrid scoring
SEMANTIC_WEIGHT = 0.7    # pgvector cosine similarity weight
FTS_WEIGHT = 0.3         # PostgreSQL ts_rank weight


class ContextSelector:
    """Hybrid context selector mixing pgvector semantic search and full-text search."""

    def __init__(self, db_config: dict, embedder: Embedder):
        self.db_config = db_config
        self.embedder = embedder
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self.db_config)
        return self._conn

    def _context_types_for_agent(self, target_agent: str) -> List[str]:
        """Map agent ID to preferred context types."""
        agent_upper = target_agent.upper().strip()
        return AGENT_CONTEXT_MAP.get(agent_upper, DEFAULT_CONTEXT_TYPES)

    def _build_query(self, query_embedding: List[float], query_text: str,
                     context_types: List[str], semantic_weight: float,
                     fts_weight: float, limit: int = 50) -> tuple:
        """Build the hybrid SQL query string and parameters."""

        # We build an embedding literal string (pgvector format)
        embedding_str = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"

        # Map context types to doc_type filter OR knowledge_chunks.type
        type_placeholders = ",".join(["%s"] * len(context_types))

        query = f"""
        SELECT
            id,
            doc_id,
            title,
            content,
            doc_type,
            file_path,
            repo_path,
            project,
            updated_at,
            1.0 - (embedding <=> %s::vector) AS cosine_similarity,
            ts_rank(search_vector, plainto_tsquery('english', %s)) AS text_rank,
            (
                {semantic_weight} * (1.0 - (embedding <=> %s::vector))
                + {fts_weight} * COALESCE(ts_rank(search_vector, plainto_tsquery('english', %s)), 0.0)
            ) AS hybrid_score
        FROM knowledge_chunks
        WHERE doc_type IN ({type_placeholders})
        ORDER BY hybrid_score DESC
        LIMIT %s
        """

        params = [embedding_str, query_text, embedding_str, query_text]
        params.extend(context_types)
        params.append(limit)

        return query, params

    def select(self, target_agent: str, req_id: str = "", task_id: str = "",
               max_tokens: int = 8000, query_text: str = "") -> SelectResult:
        """
        Execute hybrid retrieval and return selected context items.

        Args:
            target_agent: Agent identifier (A1-A10)
            req_id: Request ID for filtering (optional)
            task_id: Task ID for filtering (optional)
            max_tokens: Token budget ceiling
            query_text: Optional additional query text to guide retrieval

        Returns:
            SelectResult with ranked items
        """
        conn = self._get_conn()
        context_types = self._context_types_for_agent(target_agent)

        # Build search query from inputs
        search_text = query_text or f"agent={target_agent} req={req_id} task={task_id}"

        # Get embedding for the query
        query_embedding = self.embedder.embed(search_text)

        # Hybrid search
        sql, params = self._build_query(
            query_embedding, search_text, context_types,
            SEMANTIC_WEIGHT, FTS_WEIGHT
        )

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception as e:
                print(f"[ContextSelector] Query failed: {e}")
                # Fallback: pure semantic search without FTS
                cur.execute("""
                    SELECT id, doc_id, title, content, doc_type, file_path, repo_path,
                           project, updated_at,
                           1.0 - (embedding <=> %s::vector) AS cosine_similarity,
                           1.0 - (embedding <=> %s::vector) AS hybrid_score
                    FROM knowledge_chunks
                    WHERE doc_type = ANY(%s)
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (f"[{','.join(f'{v:.8f}' for v in query_embedding)}]",
                      context_types, f"[{','.join(f'{v:.8f}' for v in query_embedding)}]",
                      50))
                rows = cur.fetchall()

        # Build items, track tokens
        items = []
        tokens_remaining = max_tokens
        discarded = 0

        for row in rows:
            # Estimate tokens (rough: ~4 chars per token for English, ~2 chars for code)
            content = row.get('content', '') or ''
            file_path = row.get('file_path', '') or ''
            title = row.get('title', '') or ''
            doc_type = row.get('doc_type', 'knowledge')

            # Combine title + content for token estimate
            full_text = f"{title}\n{content}"
            estimated_tokens = max(1, len(full_text) // 3)  # rough estimate ~3 chars/token

            # Normalize relevance score
            raw_score = row.get('hybrid_score', 0.0) or 0.0
            # clip to [0, 1]
            relevance = max(0.0, min(1.0, raw_score))

            if estimated_tokens <= tokens_remaining:
                items.append(ContextItem(
                    type=doc_type,
                    content=content,
                    relevance=relevance,
                    position='mid',  # Will be set by ContextOrderer later
                    tokens=estimated_tokens,
                    file=file_path,
                    compressed=False,
                ))
                tokens_remaining -= estimated_tokens
            else:
                discarded += 1

        # Sort items by relevance descending (orderer will refine this)
        items.sort(key=lambda x: x.relevance, reverse=True)

        return SelectResult(
            items=items,
            tokens_used=max_tokens - tokens_remaining,
            discarded=discarded,
        )

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
