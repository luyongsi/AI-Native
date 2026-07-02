"""
activity_stream.py — Server-Sent Events endpoint for real-time agent activity streaming.

GET /api/activity/stream?req_id=<optional> — Streams agent progress, status, and artifact events.
Connects to NATS JetStream and forwards events to client as SSE.
"""
import asyncio
import json
import logging
from typing import Optional, AsyncGenerator

import nats
from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/activity", tags=["activity"])

# Stream configuration
STREAM_NAME = "AI_NATIVE_EVENTS"
ACTIVITY_SUBJECTS = [
    "agent.*.progress",
    "agent.*.status",
    "agent.*.artifact",
]


async def get_nats_client() -> nats.NATS:
    """Get NATS client from main app context."""
    from main import NATS_CLIENT
    if NATS_CLIENT is None:
        raise RuntimeError("NATS client not initialized")
    return NATS_CLIENT


async def stream_activity(req_id: Optional[str] = None) -> AsyncGenerator[dict, None]:
    """
    Stream activity events for a specific request or all requests.

    Subscribes to agent activity subjects and yields events as server-sent events.
    Filters by req_id if provided.

    Args:
        req_id: Optional request ID to filter events

    Yields:
        Dict with event data for SSE response
    """
    nc = await get_nats_client()
    js = nc.jetstream()

    # Create ephemeral subscriptions for activity streams
    subs = []
    try:
        for subject in ACTIVITY_SUBJECTS:
            try:
                sub = await js.subscribe(subject, stream=STREAM_NAME)
                subs.append(sub)
                logger.info(f"[SSE] Subscribed to {subject}")
            except Exception as e:
                logger.warning(f"[SSE] Failed to subscribe to {subject}: {e}")

        if not subs:
            raise RuntimeError("Failed to subscribe to any activity streams")

        # Stream events from all subscriptions
        while True:
            # Use asyncio.wait to handle multiple subscriptions
            tasks = [
                asyncio.create_task(sub.next_msg(timeout=30))
                for sub in subs
            ]

            try:
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED, timeout=30
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()

                if not done:
                    # Timeout — send heartbeat
                    yield {"data": json.dumps({"type": "heartbeat"})}
                    continue

                # Process completed tasks
                for task in done:
                    try:
                        msg = await task
                        data = json.loads(msg.data.decode())

                        # Filter by req_id if specified
                        if req_id and data.get("req_id") != req_id:
                            continue

                        # Yield event
                        yield {
                            "data": json.dumps(data),
                            "event": data.get("event_type", "activity"),
                        }
                        logger.debug(
                            f"[SSE] Sent event: {data.get('event_type')} for req={data.get('req_id')}"
                        )
                    except Exception as e:
                        logger.error(f"[SSE] Error processing message: {e}")

            except asyncio.TimeoutError:
                # Periodic heartbeat
                yield {"data": json.dumps({"type": "heartbeat"})}
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SSE] Stream error: {e}")
                break

    finally:
        # Cleanup subscriptions
        for sub in subs:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        logger.info("[SSE] Stream ended and subscriptions cleaned up")


@router.get("/stream")
async def activity_stream(req_id: Optional[str] = Query(None)):
    """
    Server-Sent Events endpoint for real-time agent activity.

    Query Parameters:
        req_id: Optional request ID to filter events

    Returns:
        EventSourceResponse streaming activity events
    """
    logger.info(f"[SSE] New connection: req_id={req_id}")
    try:
        return EventSourceResponse(
            stream_activity(req_id),
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.error(f"[SSE] Connection failed: {e}", exc_info=True)
        return EventSourceResponse(
            stream_activity_error(str(e)),
            headers={"Cache-Control": "no-cache"},
        )


async def stream_activity_error(error_msg: str) -> AsyncGenerator[dict, None]:
    """Yield error event and close stream."""
    yield {"data": json.dumps({"type": "error", "message": error_msg})}
