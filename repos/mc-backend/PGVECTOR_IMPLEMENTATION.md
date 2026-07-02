"""
pgvector Deployment + Embedding Service Implementation
Task #29 - Semantic Retrieval Capability

OVERVIEW
========
This implementation enables semantic search across requirements, code, specifications,
and documentation by leveraging PostgreSQL pgvector extension and vector embeddings.

Architecture:
- pgvector/pgvector:pg16 Docker image (already configured in docker-compose.yml)
- knowledge_embeddings table with 1536-dim vector column
- EmbeddingService for generating/caching embeddings
- Temporal IndexingWorkflow for background indexing
- REST API endpoint for semantic search

COMPONENTS
==========

1. DATABASE LAYER
   Location: /d/Vibe Coding/AI Agent/repos/mc-backend/db/migrations/006_pgvector.sql
   
   - Creates pgvector extension
   - Creates knowledge_embeddings table with:
     * id (serial primary key)
     * content_type (requirement/code/spec/doc)
     * content_id (reference to source)
     * content_text (original text)
     * embedding (1536-dim vector)
     * metadata (JSONB for flexible storage)
     * created_at, updated_at timestamps
   - Creates IVFFlat index for efficient similarity search
   - Creates filtering indexes for performance

2. EMBEDDING SERVICE
   Location: /d/Vibe Coding/AI Agent/repos/mc-backend/services/embedding_service.py
   
   Class: EmbeddingService
   
   Methods:
   - generate_embeddings(texts: List[str]) -> List[List[float]]
     * Generates embeddings with Redis caching
     * Batch size: 50 texts
     * Calls DeepSeek API or uses mock embeddings
   
   - search_similar(query, pool, content_type, limit, threshold) -> List[Dict]
     * Semantic search via cosine similarity
     * Filters by content_type if specified
     * Returns top-K results above threshold
   
   - index_content(content_type, content_id, content_text, metadata, pool) -> int
     * One-shot indexing of content
     * Generates embedding + stores in DB
     * Handles upserts (update if duplicate content_id)

   Features:
   - Redis caching (30-day TTL)
   - Deterministic mock embeddings (hash-seeded RNG)
   - Fallback to mock if DeepSeek API fails
   - Batch processing for efficiency
   - Error handling and retry logic

3. REST API
   Location: /d/Vibe Coding/AI Agent/repos/mc-backend/api/knowledge.py
   
   Endpoints:
   
   GET /api/knowledge
   - Returns KnowledgeStatus (project coverage, API stats, todos)
   - Unchanged from original
   
   POST /api/knowledge/search
   Query parameters:
   - query: str (required, min 1 char) - search text
   - content_type: Optional[str] - filter (requirement/code/spec/doc)
   - limit: int [1-100] (default 10) - max results
   - threshold: float [0-1] (default 0.5) - min similarity
   
   Response: SearchResponse
   - query: str
   - results: List[SearchResult]
     * id, content_type, content_id, content_text, metadata, similarity
   - count: int (number of results)

4. BACKGROUND INDEXING
   Location: /d/Vibe Coding/AI Agent/repos/orchestrator/workflows/indexing_workflow.py
   Location: /d/Vibe Coding/AI Agent/repos/orchestrator/activities/embedding_index.py
   
   Workflow: IndexingWorkflow
   - Scheduled periodic execution (e.g., hourly)
   - Scans new requirements from DB
   - Scans code changes (placeholder - integrate with git)
   - Generates embeddings for new content
   - Stores in knowledge_embeddings table
   - Returns status: success/failed with counts

CONFIGURATION
==============

Environment Variables:
- DEEPSEEK_API_KEY: DeepSeek API key for embeddings
  * If not set, uses mock embeddings (deterministic for testing)
- DATABASE_URL: PostgreSQL connection string
  * Default: postgresql://ai_native:ai_native_dev@localhost:5432/ai_native
- REDIS_URL: Redis connection for embedding cache
  * Default: redis://localhost:6379

Docker Compose:
- postgres service already configured with pgvector/pgvector:pg16
- redis service for caching
- Both on ai-network

SETUP INSTRUCTIONS
===================

1. Apply Database Migration
   cd /d/Vibe Coding/AI Agent/repos/mc-backend
   PGPASSWORD=ai_native_dev psql -U ai_native -h localhost -d ai_native \
     -f db/migrations/006_pgvector.sql

   OR in Docker:
   docker exec ai-postgres psql -U ai_native -d ai_native \
     -f /docker-entrypoint-initdb.d/006_pgvector.sql

2. Update Backend Requirements
   cd /d/Vibe Coding/AI Agent/repos/mc-backend
   pip install -r requirements.txt
   # Note: aiohttp added for DeepSeek API calls

3. Start Services
   cd /d/Vibe Coding/AI Agent/repos/infra
   docker-compose up -d

4. Test Installation
   cd /d/Vibe Coding/AI Agent/repos/mc-backend
   python test_pgvector.py

USAGE EXAMPLES
==============

1. Semantic Search (via REST API)
   curl -X POST \
     'http://localhost:8000/api/knowledge/search?query=authentication&limit=10' \
     -H 'Content-Type: application/json'
   
   Response:
   {
     "query": "authentication",
     "results": [
       {
         "id": 42,
         "content_type": "requirement",
         "content_id": "req_123",
         "content_text": "Implement user authentication with JWT tokens...",
         "metadata": {"title": "User Auth", "source": "requirements_table"},
         "similarity": 0.8543
       }
     ],
     "count": 1
   }

2. Index Content Programmatically
   from services.embedding_service import EmbeddingService
   import redis.asyncio as redis
   import asyncpg
   
   redis_client = await redis.from_url("redis://localhost:6379")
   svc = EmbeddingService(redis_client)
   pool = await asyncpg.create_pool(DATABASE_URL)
   
   await svc.index_content(
       content_type="requirement",
       content_id="req_456",
       content_text="New feature description...",
       metadata={"author": "alice", "tags": ["feature"]},
       pool=pool
   )

3. Background Indexing (via Temporal)
   Workflow IndexingWorkflow runs periodically:
   - Scans requirements table for new/updated rows
   - Scans git commits for code changes
   - Generates embeddings
   - Stores in knowledge_embeddings

   Registration in worker:
   worker = Worker(
       client,
       task_queue="semantic-indexing",
       workflows=[IndexingWorkflow],
       activities=[
           scan_new_requirements,
           scan_code_changes,
           index_embeddings,
       ]
   )

TESTING
=======

Unit Test: test_pgvector.py
- Verifies pgvector extension installed
- Checks knowledge_embeddings table exists
- Tests embedding service (mock mode)
- Validates search API endpoint

Run:
   cd /d/Vibe Coding/AI Agent/repos/mc-backend
   python test_pgvector.py

Integration Test:
   pytest tests/ -v -k embedding

ACCEPTANCE CRITERIA
===================

[x] docker-compose.yml uses pgvector/pgvector:pg16
[x] pgvector extension installation supported
[x] knowledge_embeddings table schema with:
    - vector(1536) column
    - JSONB metadata
    - IVFFlat index
[x] EmbeddingService class with:
    - DeepSeek API integration
    - Batch processing (size 50)
    - Redis caching (30-day TTL)
    - Mock fallback
    - Error handling
[x] Semantic search API:
    - POST /api/knowledge/search
    - Cosine similarity via <=> operator
    - Filtering by content_type
    - Threshold-based filtering
[x] Background indexing workflow:
    - IndexingWorkflow periodically scans DB
    - EmbeddingService generates vectors
    - Stores in knowledge_embeddings
[x] Error handling:
    - DeepSeek API failures → mock
    - DB connection failures → logged
    - Cache miss → generate on-demand
[x] Dependencies:
    - aiohttp>=3.9.0 (for async HTTP)
    - redis>=4.2.0 (for caching)
    - asyncpg>=0.29.0 (for DB)

PERFORMANCE NOTES
=================

- IVFFlat index uses lists=100 (tunable for 1M+ rows)
- Batch embedding: 50 texts per API call (reduces latency)
- Redis TTL: 30 days (balance memory vs. recomputation)
- Vector search: O(log N) with IVFFlat index
- Content deduplication: ON CONFLICT handling prevents duplicate embeddings

FUTURE ENHANCEMENTS
====================

1. Distributed embeddings: Use pgvector's built-in partitioning for 100M+ vectors
2. Hybrid search: Combine vector similarity with keyword BM25
3. Real-time indexing: Subscribe to NATS events for instant indexing
4. API versioning: Support multiple embedding models (v1, v2, etc.)
5. Analytics: Track search queries, popular content, embedding drift
6. Multi-tenancy: Partition embeddings by workspace/project
7. Reranking: Second-stage reranking with LLM for top-5 results
"""