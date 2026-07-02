"""
k14_knowledge_keeper.py — K14 Knowledge Keeper Agent Worker

Subscribes to artifact.produced events and indexes knowledge chunks into
the pgvector knowledge_chunks table for later retrieval.

Usage:
    python3 k14_knowledge_keeper.py         # run standalone
    # Or register in worker_launcher.py     # run alongside the rest of the platform
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from event_bus import EventPublisher, EventSubscriber
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AGENT_ID = "K14"
AGENT_TYPE = "knowledge_keeper"

DB_DSN = "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"
EMBEDDING_DIM = 1024  # vector(1024) as defined in the schema


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class KnowledgeKeeperAgent(BaseAgentWorker):
    """K14 Knowledge Keeper — indexes artifacts into pgvector."""

    def __init__(self, nats_url: str = "nats://localhost:4222", db_dsn: str = DB_DSN):
        super().__init__(agent_id=AGENT_ID, agent_type=AGENT_TYPE, nats_url=nats_url)
        self._db_dsn = db_dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._publisher: Optional[EventPublisher] = None

    async def init(self):
        await super().init()
        self._publisher = EventPublisher(self.nats_url)
        await self._publisher.connect()

        self._pool = await asyncpg.create_pool(dsn=self._db_dsn, min_size=1, max_size=5)
        # Verify the table exists
        async with self._pool.acquire() as conn:
            table_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'knowledge_chunks')"
            )
            if table_exists:
                logger.info("[K14] knowledge_chunks table verified")
            else:
                logger.warning("[K14] knowledge_chunks table NOT found — writes will fail")
        logger.info("[K14] Knowledge Keeper initialized")

    async def close(self):
        if self._pool:
            await self._pool.close()
        if self._publisher:
            await self._publisher.disconnect()
        await super().close()

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """Index an artifact into the knowledge_chunks table."""
        artifact = context_package.get("payload", context_package).get("artifact", {})
        artifact_id = artifact.get("id", "unknown")
        artifact_type = artifact.get("type", "unknown")
        data = artifact.get("metadata", artifact)

        logger.info("[K14] Indexing artifact %s (type=%s) for req=%s", artifact_id, artifact_type, req_id)

        chunks_written = await self._write_chunks(req_id, artifact_id, artifact_type, data)

        if chunks_written > 0:
            await self.report_status(req_id, "completed", f"Indexed {chunks_written} chunk(s) for {artifact_id}")
        else:
            await self.report_status(req_id, "completed", f"No chunks written for {artifact_id}")

        logger.info("[K14] Indexed %d chunk(s) for artifact %s", chunks_written, artifact_id)

        return {
            "status": "completed",
            "artifact_id": artifact_id,
            "chunks_written": chunks_written,
        }

    # ------------------------------------------------------------------
    # PGVector write
    # ------------------------------------------------------------------

    async def _write_chunks(self, req_id: str, artifact_id: str, artifact_type: str, data: dict) -> int:
        """
        Break artifact data into text chunks and write to knowledge_chunks.
        In dev mode, we store the artifact as a single chunk with a zero-vector
        placeholder (since we don't have an embedding model loaded).
        """
        if not self._pool:
            logger.error("[K14] No database pool available")
            return 0

        async with self._pool.acquire() as conn:
            # Prepare chunk content: serialize artifact data as text
            import json
            content = json.dumps(data, ensure_ascii=False, indent=2)
            title = f"{artifact_type}: {artifact_id}"[:500]
            doc_id = f"{artifact_type}:{artifact_id}:v1"

            # Use zero-vector as placeholder (production would call an embedding model)
            zero_vector = "[0] * EMBEDDING_DIM"  # placeholder - in production use real embeddings
            embedding_placeholder = "[" + ",".join(["0"] * EMBEDDING_DIM) + "]"

            try:
                await conn.execute(
                    """
                    INSERT INTO knowledge_chunks (doc_id, title, content, doc_type, embedding, updated_at)
                    VALUES (, , , , ::vector, )
                    ON CONFLICT (doc_id) DO UPDATE
                      SET content = EXCLUDED.content,
                          title = EXCLUDED.title,
                          updated_at = EXCLUDED.updated_at
                    """,
                    doc_id,
                    title,
                    content,
                    artifact_type,
                    embedding_placeholder,
                    datetime.now(timezone.utc),
                )
                logger.info("[K14] Written chunk doc_id=%s", doc_id)
                return 1
            except Exception as exc:
                logger.error("[K14] Failed to write chunk doc_id=%s: %s", doc_id, exc)
                return 0


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

async def main():
    """Run Knowledge Keeper directly for development/testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    agent = KnowledgeKeeperAgent()
    await agent.init()

    subscriber = EventSubscriber()
    # Subscribe to multiple subject patterns that match artifact types
    # The pattern "artifact.produced" will also catch "artifact.produced.*"
    # per NATS subject token matching

    @subscriber.on("artifact.produced")
    async def on_artifact_produced(event: dict):
        req_id = event.get("req_id", "unknown")
        agent_id = event.get("agent_id", "unknown")
        logger.info("[K14] Received artifact.produced from agent=%s for req=%s", agent_id, req_id)
        result = await agent.execute(req_id, event)
        logger.info("[K14] Index result: %s", result)

    await subscriber.start()
    logger.info("[K14] Knowledge Keeper listening on artifact.produced — Ctrl+C to stop")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("[K14] Shutting down...")
    finally:
        await subscriber.stop()
        await agent.close()

if __name__ == "__main__":
    asyncio.run(main())
