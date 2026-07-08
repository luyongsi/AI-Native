"""NATS client utilities for the testing tool."""

import json
import logging
import nats

logger = logging.getLogger(__name__)


def get_nats_url() -> str:
    import os
    return os.environ.get("NATS_URL", "nats://localhost:4222")


async def connect_nats() -> nats.NATS:
    url = get_nats_url()
    nc = await nats.connect(url)
    logger.info(f"Connected to NATS at {url}")
    return nc


async def check_jetstream(nc: nats.NATS, stream_name: str = "AI_NATIVE_EVENTS") -> dict:
    js = nc.jetstream()
    try:
        info = await js.stream_info(stream_name)
        return {
            "exists": True,
            "subjects": list(info.config.subjects),
            "consumer_count": info.state.consumer_count,
            "messages": info.state.messages,
            "retention": str(info.config.retention),
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}


async def publish_event(nc: nats.NATS, subject: str, payload: dict) -> None:
    await nc.publish(subject, json.dumps(payload, ensure_ascii=False, default=str).encode())
    logger.debug(f"Published to {subject}")


async def subscribe_one(nc: nats.NATS, subject: str, timeout: float = 5.0):
    """Subscribe to a subject and return the first message captured within timeout."""
    import asyncio
    captured = []

    async def handler(msg):
        data = json.loads(msg.data.decode())
        captured.append(data)
        await msg.ack()

    sub = await nc.subscribe(subject, cb=handler)
    await asyncio.sleep(timeout)
    await sub.unsubscribe()
    return captured[0] if captured else None
