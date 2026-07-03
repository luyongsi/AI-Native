"""
StreamManager — manages NATS JetStream Streams and Consumers for the ai-native event bus.

Stream: AI_NATIVE_EVENTS
Subjects: gate.*.*, agent.*.*, requirement.*.*, artifact.*.*, loop.*.*, test.*, system.*
Config: max_msgs=1_000_000, max_bytes=10GB, duplicate_window=2min (persistent)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import nats
from nats.js.api import (
    ConsumerConfig,
    DeliverPolicy,
    DiscardPolicy,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.client import JetStreamContext

logger = logging.getLogger(__name__)

STREAM_NAME = "AI_NATIVE_EVENTS"
STREAM_SUBJECTS = [
    "gate.*.*",
    "agent.*.*",
    "requirement.>",
    "artifact.>",
    "loop.>",
    "test.>",
    "system.>",
    "code.>",
    "pipeline.>",
    "context.>",
    "propagation.>",
    "msg.>",
    "msg_received",
    "dag.>",
    "release.>",
    "knowledge.>",
    "design.>",
    "architecture.>",
    "spec.>",
]

DEFAULT_MAX_MSGS = 1_000_000
DEFAULT_MAX_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
DEFAULT_DUPLICATE_WINDOW = 120  # 2 minutes in seconds

STREAM_CONFIG = StreamConfig(
    name=STREAM_NAME,
    subjects=STREAM_SUBJECTS,
    retention=RetentionPolicy.INTEREST,
    max_consumers=-1,
    max_msgs=DEFAULT_MAX_MSGS,
    max_bytes=DEFAULT_MAX_BYTES,
    discard=DiscardPolicy.OLD,
    storage=StorageType.FILE,
    duplicate_window=DEFAULT_DUPLICATE_WINDOW,
    allow_direct=True,
)


class StreamManager:
    """Manages the AI_NATIVE_EVENTS JetStream stream and its consumers."""

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._nats_url = nats_url
        self._nc: Optional[nats.NATS] = None
        self._js: Optional[JetStreamContext] = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> JetStreamContext:
        """Connect to NATS and return the JetStream context."""
        if self._nc is None:
            self._nc = await nats.connect(self._nats_url)
            logger.info("Connected to NATS at %s", self._nats_url)
        if self._js is None:
            self._js = self._nc.jetstream()
        return self._js

    async def disconnect(self) -> None:
        """Drain and close the NATS connection."""
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None
            self._js = None
            logger.info("Disconnected from NATS")

    @property
    def js(self) -> Optional[JetStreamContext]:
        return self._js

    @property
    def nc(self) -> Optional[nats.NATS]:
        return self._nc

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------

    async def ensure_stream(self) -> None:
        """Create or update the AI_NATIVE_EVENTS stream."""
        js = await self.connect()
        try:
            stream_info = await js.stream_info(STREAM_NAME)
            logger.info(
                "Stream %s already exists (msgs=%s bytes=%s)",
                STREAM_NAME,
                stream_info.state.messages,
                stream_info.state.bytes,
            )
            await js.update_stream(config=STREAM_CONFIG)
            logger.info("Stream %s updated", STREAM_NAME)
        except Exception:
            await js.add_stream(config=STREAM_CONFIG)
            logger.info("Stream %s created", STREAM_NAME)

    async def delete_stream(self) -> bool:
        """Delete the AI_NATIVE_EVENTS stream. Returns True if it existed."""
        js = await self.connect()
        try:
            await js.delete_stream(STREAM_NAME)
            logger.info("Stream %s deleted", STREAM_NAME)
            return True
        except Exception:
            logger.warning("Stream %s not found for deletion", STREAM_NAME)
            return False

    async def stream_info(self):
        """Return stream info dict or None."""
        js = await self.connect()
        try:
            return await js.stream_info(STREAM_NAME)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Consumer helpers
    # ------------------------------------------------------------------

    async def add_consumer(
        self,
        consumer_name: str,
        filter_subject: str,
        durable: bool = True,
        deliver_policy: DeliverPolicy = DeliverPolicy.ALL,
        ack_wait: int = 30,
        max_deliver: int = -1,
        max_ack_pending: int = 1000,
    ) -> None:
        """Add (or update) a consumer for a given subject filter."""
        js = await self.connect()
        config = ConsumerConfig(
            durable_name=consumer_name if durable else None,
            deliver_policy=deliver_policy,
            filter_subject=filter_subject,
            ack_wait=ack_wait,
            max_deliver=max_deliver,
            max_ack_pending=max_ack_pending,
        )
        try:
            await js.add_consumer(stream=STREAM_NAME, config=config)
            logger.info("Consumer %s added on %s", consumer_name, filter_subject)
        except Exception:
            # Consumer may already exist — update it
            await js.update_consumer(stream=STREAM_NAME, durable=consumer_name, config=config)
            logger.info("Consumer %s updated on %s", consumer_name, filter_subject)

    async def delete_consumer(self, consumer_name: str) -> bool:
        """Delete a durable consumer. Returns True if it existed."""
        js = await self.connect()
        try:
            await js.delete_consumer(stream=STREAM_NAME, consumer=consumer_name)
            logger.info("Consumer %s deleted", consumer_name)
            return True
        except Exception:
            logger.warning("Consumer %s not found for deletion", consumer_name)
            return False

    async def purge_stream(self) -> None:
        """Purge all messages from the stream."""
        js = await self.connect()
        await js.purge_stream(STREAM_NAME)
        logger.info("Stream %s purged", STREAM_NAME)
