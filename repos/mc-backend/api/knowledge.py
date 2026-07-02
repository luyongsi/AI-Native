"""
Mission Control Backend - Knowledge API
GET /api/knowledge - Returns KnowledgeStatus with project coverage, API stats, and todos.
POST /api/knowledge/search - Semantic search via vector embeddings.
"""
import logging
from typing import Optional, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ── Pydantic models ──────────────────────────────────────────────────────

class ProjectCoverage(BaseModel):
    name: str
    coverage_pct: float


class ApiStats(BaseModel):
    indexed: int = 0
    deprecated: int = 0
    undocumented: int = 0
    conflicts: int = 0


class KnowledgeTodo(BaseModel):
    level: str
    description: str
    suggestion: str


class KnowledgeStatus(BaseModel):
    projects: list[ProjectCoverage] = Field(default_factory=list)
    api_stats: ApiStats = Field(default_factory=ApiStats)
    todos: list[KnowledgeTodo] = Field(default_factory=list)


class SearchResult(BaseModel):
    id: int
    content_type: str
    content_id: str
    content_text: str
    metadata: dict = Field(default_factory=dict)
    similarity: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)
    count: int = 0


# ── Helpers ──────────────────────────────────────────────────────────────

async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


async def get_embedding_service():
    from main import REDIS_CLIENT
    from services.embedding_service import EmbeddingService
    return EmbeddingService(REDIS_CLIENT)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=KnowledgeStatus)
async def get_knowledge_status():
    conn = await get_db()
    try:
        # ── Project coverage: count chunks per project ──────────────────
        project_rows = await conn.fetch(
            """
            SELECT project, COUNT(*) as cnt
            FROM knowledge_chunks
            WHERE project IS NOT NULL
            GROUP BY project
            ORDER BY cnt DESC
            """
        )
        total_chunks = sum(r["cnt"] for r in project_rows) or 1  # avoid div by zero
        projects: list[ProjectCoverage] = []
        for row in project_rows:
            pct = round((row["cnt"] / total_chunks) * 100, 1)
            projects.append(ProjectCoverage(name=row["project"], coverage_pct=pct))

        # ── API stats: doc_type aggregates ──────────────────────────────
        indexed_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM knowledge_chunks WHERE doc_type = 'api'"
        )
        deprecated_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM knowledge_chunks WHERE doc_type = 'deprecated'"
        )
        undocumented_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM knowledge_chunks WHERE doc_type = 'undocumented'"
        )
        conflicts_row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM knowledge_chunks WHERE doc_type = 'conflict'"
        )

        api_stats = ApiStats(
            indexed=indexed_row["cnt"] if indexed_row else 0,
            deprecated=deprecated_row["cnt"] if deprecated_row else 0,
            undocumented=undocumented_row["cnt"] if undocumented_row else 0,
            conflicts=conflicts_row["cnt"] if conflicts_row else 0,
        )

        # ── Todos: hardcoded improvement suggestions ───────────────────
        todos: list[KnowledgeTodo] = [
            KnowledgeTodo(
                level="info",
                description="API documentation coverage",
                suggestion="Run the API doc scanner to index missing endpoint documentation."
            ),
            KnowledgeTodo(
                level="warning",
                description="Deprecated API surface",
                suggestion="Review and remove deprecated endpoints to reduce maintenance surface."
            ),
            KnowledgeTodo(
                level="info",
                description="Knowledge chunk freshness",
                suggestion="Re-index repositories weekly to keep embeddings up to date."
            ),
            KnowledgeTodo(
                level="warning",
                description="Conflicting API definitions",
                suggestion="Resolve overlapping or conflicting endpoint signatures across services."
            ),
        ]

        return KnowledgeStatus(projects=projects, api_stats=api_stats, todos=todos)
    finally:
        await conn.close()


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(
    query: str = Query(..., min_length=1, description="Search query"),
    content_type: Optional[str] = Query(None, description="Filter by content_type: requirement, code, spec, doc"),
    limit: int = Query(10, ge=1, le=100, description="Max results"),
    threshold: float = Query(0.5, ge=0.0, le=1.0, description="Minimum similarity (0-1)"),
):
    """
    Semantic search via vector embeddings.

    Returns top-K similar content sorted by cosine similarity.
    """
    from main import DB_POOL

    if not DB_POOL:
        return SearchResponse(query=query, results=[], count=0)

    try:
        svc = await get_embedding_service()
        results = await svc.search_similar(
            query=query,
            pool=DB_POOL,
            content_type=content_type,
            limit=limit,
            threshold=threshold,
        )

        return SearchResponse(
            query=query,
            results=[SearchResult(**r) for r in results],
            count=len(results),
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        return SearchResponse(query=query, results=[], count=0)
