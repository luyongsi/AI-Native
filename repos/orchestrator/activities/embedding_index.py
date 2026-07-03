"""Activities for IndexingWorkflow

Handles scanning and indexing of requirements and code changes.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import asyncpg

logger = logging.getLogger(__name__)

# Configuration from environment
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


async def scan_new_requirements(hours_back: int = 1) -> List[Dict[str, Any]]:
    """
    Scan database for new/updated requirements.

    Returns list of dicts with: id, title, description, created_at
    """
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        conn = await pool.acquire()
        try:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    title,
                    description,
                    created_at
                FROM requirements
                WHERE created_at > NOW() - INTERVAL '%d hours'
                   OR updated_at > NOW() - INTERVAL '%d hours'
                ORDER BY updated_at DESC
                """
                % (hours_back, hours_back)
            )
            return [dict(row) for row in rows]
        finally:
            await conn.close()
            await pool.close()
    except Exception as e:
        logger.error(f"scan_new_requirements failed: {e}")
        return []


async def scan_code_changes(hours_back: int = 1) -> List[Dict[str, Any]]:
    """
    Scan git repositories for recent commits.

    Returns list of dicts with: file_path, commit_hash, commit_msg, timestamp
    Note: In a real implementation, this would scan actual git repos.
    For now, returns empty list (placeholder).
    """
    try:
        # Placeholder: In production, scan git repositories
        # For now, return empty list
        logger.info(f"Code change scan placeholder (hours_back={hours_back})")
        return []
    except Exception as e:
        logger.error(f"scan_code_changes failed: {e}")
        return []


async def index_embeddings(
    requirements: List[Dict[str, Any]],
    code_changes: List[Dict[str, Any]],
) -> int:
    """
    Generate embeddings for requirements and code changes.
    Store in knowledge_embeddings table.

    Returns count of successfully indexed items.
    """
    import redis.asyncio as redis
    from services.embedding_service import EmbeddingService

    indexed_count = 0

    try:
        # Initialize services
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        redis_client = await redis.from_url(REDIS_URL, decode_responses=False)
        svc = EmbeddingService(redis_client)

        # Index requirements
        for req in requirements:
            try:
                req_id = req.get("id")
                title = req.get("title", "")
                description = req.get("description", "")
                content_text = f"{title}\n\n{description}".strip()

                if content_text:
                    await svc.index_content(
                        content_type="requirement",
                        content_id=str(req_id),
                        content_text=content_text,
                        metadata={"title": title, "source": "requirements_table"},
                        pool=pool,
                    )
                    indexed_count += 1
                    logger.debug(f"Indexed requirement {req_id}")
            except Exception as e:
                logger.warning(f"Failed to index requirement {req.get('id')}: {e}")

        # Index code changes
        for change in code_changes:
            try:
                file_path = change.get("file_path", "")
                commit_msg = change.get("commit_msg", "")
                content_text = f"{file_path}\n{commit_msg}".strip()

                if content_text:
                    await svc.index_content(
                        content_type="code",
                        content_id=change.get("commit_hash", "unknown"),
                        content_text=content_text,
                        metadata={"file": file_path, "source": "git_commits"},
                        pool=pool,
                    )
                    indexed_count += 1
                    logger.debug(f"Indexed code change {file_path}")
            except Exception as e:
                logger.warning(
                    f"Failed to index code change {change.get('file_path')}: {e}"
                )

        logger.info(f"IndexingActivity: indexed {indexed_count} items")
        return indexed_count

    except Exception as e:
        logger.error(f"index_embeddings failed: {e}")
        return indexed_count
    finally:
        try:
            if pool:
                await pool.close()
            if redis_client:
                await redis_client.close()
        except:
            pass
