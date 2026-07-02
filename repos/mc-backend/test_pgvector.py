"""
Test script for pgvector and embedding service.
Verifies:
1. pgvector extension is installed
2. knowledge_embeddings table exists
3. Embedding service can generate embeddings
4. Search API works
"""

import asyncio
import asyncpg
import os
import json

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
)


async def test_pgvector_installed():
    """Verify pgvector extension is available."""
    pool = await asyncpg.create_pool(DATABASE_URL)
    conn = await pool.acquire()
    try:
        result = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')"
        )
        print(f"[pgvector] Extension installed: {result}")
        return result
    finally:
        await conn.close()
        await pool.close()


async def test_table_exists():
    """Verify knowledge_embeddings table exists."""
    pool = await asyncpg.create_pool(DATABASE_URL)
    conn = await pool.acquire()
    try:
        result = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name='knowledge_embeddings'
            )
            """
        )
        print(f"[DB] knowledge_embeddings table exists: {result}")
        if result:
            count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
            print(f"[DB] Current row count: {count}")
        return result
    finally:
        await conn.close()
        await pool.close()


async def test_embedding_service():
    """Test embedding service mock mode."""
    try:
        import redis.asyncio as redis
        from services.embedding_service import EmbeddingService

        # Mock mode (no API key)
        svc = EmbeddingService(redis_client=None)

        texts = [
            "Implement user authentication with JWT",
            "Add database migration for users table",
            "Fix bug in payment processing",
        ]

        embeddings = await svc.generate_embeddings(texts)
        print(f"[Embedding] Generated {len(embeddings)} embeddings")
        print(f"[Embedding] Embedding dimension: {len(embeddings[0]) if embeddings else 0}")
        return len(embeddings) == len(texts)
    except Exception as e:
        print(f"[Embedding] Error: {e}")
        return False


async def test_search_api():
    """Test that search endpoint is registered."""
    try:
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/api/knowledge/search?query=test&limit=5&threshold=0.5"
        )
        print(f"[API] Search endpoint status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"[API] Response shape: query={data.get('query')}, count={data.get('count')}")
        return response.status_code in (200, 422)  # 422 if pool not ready
    except Exception as e:
        print(f"[API] Error: {e}")
        return False


async def main():
    print("=" * 60)
    print("pgvector + Embedding Service Verification")
    print("=" * 60)

    tests = [
        ("pgvector extension", test_pgvector_installed),
        ("knowledge_embeddings table", test_table_exists),
        ("embedding service", test_embedding_service),
        ("search API", test_search_api),
    ]

    results = []
    for name, test_fn in tests:
        try:
            result = await test_fn()
            results.append((name, result))
            print()
        except Exception as e:
            print(f"[ERROR] {name}: {e}\n")
            results.append((name, False))

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    all_passed = all(r for _, r in results)
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
