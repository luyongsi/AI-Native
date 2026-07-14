"""
Mission Control Backend — Outbox Publisher

Polls event_log for pending OUT records and publishes to NATS JetStream.
Runs as a background asyncio task in the FastAPI process.

Config:
  - Poll interval: 2 seconds
  - Max batch: 50 records
  - Max retries: 5, with exponential backoff (1s/2s/4s/8s/16s)
  - Failed records are marked 'failed' after exhausting retries
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")
POLL_INTERVAL = 2.0          # seconds
BATCH_SIZE = 50
MAX_RETRIES = 5
RETRY_BACKOFF = [1, 2, 4, 8, 16]  # seconds per retry


class OutboxPublisher:
    """Polls event_log and publishes pending outbox records to NATS."""

    def __init__(self, db_pool, nats_url: str = NATS_URL):
        self.db_pool = db_pool
        self.nats_url = nats_url
        self._nats = None
        self._js = None
        self._running = False

    async def start(self):
        """Connect NATS and begin the polling loop."""
        import nats
        try:
            self._nats = await nats.connect(self.nats_url)
            self._js = self._nats.jetstream()
            logger.info("[outbox] Connected to NATS at %s", self.nats_url)
        except Exception as e:
            logger.error("[outbox] NATS connection failed: %s", e)
            self._nats = None
            self._js = None

        self._running = True
        asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._nats:
            await self._nats.drain()

    # ------------------------------------------------------------------
    async def _poll_loop(self):
        while self._running:
            try:
                await self._publish_pending()
            except Exception as e:
                logger.error("[outbox] Poll loop error: %s", e)
            await asyncio.sleep(POLL_INTERVAL)

    async def _publish_pending(self):
        if not self._nats or not self._js:
            return

        conn = await self.db_pool.acquire()
        try:
            rows = await conn.fetch(
                """SELECT id, event_name, payload
                   FROM event_log
                   WHERE outbox_status = 'pending'
                   ORDER BY created_at
                   LIMIT $1
                   FOR UPDATE SKIP LOCKED""",
                BATCH_SIZE,
            )

            for row in rows:
                await self._publish_one(conn, row)
        finally:
            await conn.close()

    async def _publish_one(self, conn, row):
        event_name = row["event_name"]
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await self._js.publish(
                    event_name,
                    json.dumps(payload, ensure_ascii=False).encode(),
                    headers={"Nats-Msg-Id": f"outbox-{row['id']}"},
                )
                # Success — mark published
                await conn.execute(
                    """UPDATE event_log
                       SET outbox_status = 'published', published_at = $2
                       WHERE id = $1""",
                    row["id"],
                    datetime.now(timezone.utc),
                )
                return
            except Exception as e:
                wait = RETRY_BACKOFF[attempt - 1]
                logger.warning(
                    "[outbox] NATS publish failed (attempt %d/%d) for id=%d, event=%s: %s",
                    attempt, MAX_RETRIES, row["id"], event_name, e,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(wait)

        # All retries exhausted
        await conn.execute(
            "UPDATE event_log SET outbox_status = 'failed' WHERE id = $1",
            row["id"],
        )
        logger.error(
            "[outbox] Marked event_log id=%d as failed after %d retries",
            row["id"], MAX_RETRIES,
        )
        # TODO: fire Prometheus counter a1_outbox_failed_total.inc()
