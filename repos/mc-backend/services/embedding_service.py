"""Embedding Service - vector embeddings with caching and semantic search."""

import asyncio
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp
import redis.asyncio as redis

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/embeddings"
EMBEDDING_MODEL = "deepseek-coder"
EMBEDDING_DIM = 1536
BATCH_SIZE = 50


class EmbeddingService:
    """Generate and cache vector embeddings for semantic search."""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.use_mock = not DEEPSEEK_API_KEY
        if self.use_mock:
            logger.warning("DeepSeek API key not configured. Using mock embeddings.")

    async def generate_embeddings(
        self, texts: List[str], use_cache: bool = True
    ) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []

        cache_hits = {}
        texts_to_embed = []

        if use_cache and self.redis:
            for i, text in enumerate(texts):
                cache_key = self._cache_key(text)
                try:
                    cached = await self.redis.get(cache_key)
                    if cached:
                        cache_hits[i] = json.loads(cached)
                except Exception as e:
                    logger.warning(f"Cache lookup failed: {e}")

        for i, text in enumerate(texts):
            if i not in cache_hits:
                texts_to_embed.append((i, text))

        if texts_to_embed:
            batch_embeddings = await self._batch_embed(texts_to_embed)
            for i, text, embedding in batch_embeddings:
                cache_hits[i] = embedding
                if self.redis:
                    cache_key = self._cache_key(text)
                    try:
                        await self.redis.setex(
                            cache_key, 86400 * 30, json.dumps(embedding)
                        )
                    except Exception as e:
                        logger.warning(f"Cache write failed: {e}")

        embeddings = [None] * len(texts)
        for i, embedding in cache_hits.items():
            embeddings[i] = embedding
        return embeddings

    async def _batch_embed(
        self, indexed_texts: List[tuple]
    ) -> List[tuple]:
        """Batch process texts."""
        if self.use_mock:
            return self._mock_embed(indexed_texts)

        results = []
        for batch_start in range(0, len(indexed_texts), BATCH_SIZE):
            batch = indexed_texts[batch_start : batch_start + BATCH_SIZE]
            batch_texts = [text for _, text in batch]

            try:
                embeddings = await self._call_deepseek_api(batch_texts)
                for (idx, text), embedding in zip(batch, embeddings):
                    results.append((idx, text, embedding))
            except Exception as e:
                logger.error(f"DeepSeek API error: {e}. Using mock.")
                results.extend(self._mock_embed(batch))

        return results

    async def _call_deepseek_api(self, texts: List[str]) -> List[List[float]]:
        """Call DeepSeek embedding API."""
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"model": EMBEDDING_MODEL, "input": texts}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    DEEPSEEK_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"DeepSeek API {resp.status}")
                    data = await resp.json()
                    return [item["embedding"] for item in data.get("data", [])]
        except asyncio.TimeoutError:
            raise Exception("DeepSeek API timeout")

    def _mock_embed(self, indexed_texts: List[tuple]) -> List[tuple]:
        """Generate deterministic mock embeddings."""
        import random

        results = []
        for idx, text in indexed_texts:
            seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % (2**31)
            rng = random.Random(seed)
            embedding = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
            norm = (sum(x**2 for x in embedding) ** 0.5) or 1.0
            embedding = [x / norm for x in embedding]
            results.append((idx, text, embedding))
        return results

    async def search_similar(
        self,
        query: str,
        pool: Any,
        content_type: Optional[str] = None,
        limit: int = 10,
        threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """Semantic search via cosine similarity."""
        query_embeddings = await self.generate_embeddings([query])
        if not query_embeddings or not query_embeddings[0]:
            return []

        query_embedding = query_embeddings[0]
        where_clauses = []
        params = [query_embedding]

        if content_type:
            where_clauses.append(f"content_type = ${len(params) + 1}")
            params.append(content_type)

        where_sql = " AND ".join(where_clauses) if where_clauses else ""
        where_sql = f"WHERE {where_sql}" if where_sql else ""

        sql = f"""
        SELECT
            id, content_type, content_id, content_text, metadata,
            (1 - (embedding <=> $1::vector)) as similarity
        FROM knowledge_embeddings
        {where_sql}
        ORDER BY embedding <=> $1::vector
        LIMIT ${len(params) + 1}
        """
        params.append(limit)

        try:
            conn = await pool.acquire()
            try:
                rows = await conn.fetch(sql, *params)
                results = []
                for row in rows:
                    sim = row["similarity"]
                    if sim >= threshold:
                        results.append(
                            {
                                "id": row["id"],
                                "content_type": row["content_type"],
                                "content_id": row["content_id"],
                                "content_text": row["content_text"],
                                "metadata": row["metadata"] or {},
                                "similarity": round(sim, 4),
                            }
                        )
                return results
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Search query failed: {e}")
            return []

    async def index_content(
        self,
        content_type: str,
        content_id: str,
        content_text: str,
        metadata: Optional[Dict] = None,
        pool: Optional[Any] = None,
    ) -> int:
        """Index content by generating embedding and storing."""
        if not pool:
            raise ValueError("pool is required")

        embeddings = await self.generate_embeddings([content_text])
        if not embeddings or not embeddings[0]:
            raise Exception("Failed to generate embedding")

        embedding = embeddings[0]
        conn = await pool.acquire()
        try:
            result = await conn.fetchval(
                """
                INSERT INTO knowledge_embeddings
                (content_type, content_id, content_text, embedding, metadata)
                VALUES ($1, $2, $3, $4::vector, $5)
                ON CONFLICT (content_type, content_id)
                DO UPDATE SET
                    content_text = $2,
                    embedding = $4::vector,
                    metadata = $5,
                    updated_at = NOW()
                RETURNING id
                """,
                content_type,
                content_id,
                content_text,
                embedding,
                json.dumps(metadata or {}),
            )
            logger.info(f"Indexed {content_type}:{content_id} -> id={result}")
            return result
        finally:
            await conn.close()

    @staticmethod
    def _cache_key(text: str) -> str:
        """Generate Redis cache key for text."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"embedding:{text_hash}"
