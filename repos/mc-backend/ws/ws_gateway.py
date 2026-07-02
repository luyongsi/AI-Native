"""
Mission Control Backend - WebSocket Gateway
NATS -> WebSocket real-time push gateway.

- JWT authentication during handshake
- Subscribes to agent.status.changed and pushes to WS clients
- Redis PubSub for cross-pod broadcast (optional, single-pod without it)
"""
import json
import asyncio
import os
import uuid
import logging
try:
    import redis.asyncio as redis
    _HAS_REDIS = True
except ImportError:
    redis = None  # type: ignore
    _HAS_REDIS = False
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from ws.ws_auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# In-memory connection registry: req_id -> set of WebSocket connections
CONNECTIONS: dict[str, set[WebSocket]] = {}

# Redis client for cross-pod broadcast (None = single-pod mode)
_redis_client: "redis.Redis | None" = None
_redis_listener_task: asyncio.Task | None = None


async def init_redis(redis_url: str = None):
    """Initialize Redis PubSub for cross-pod broadcast.

    If REDIS_URL env var is not set, stays in single-pod mode.
    """
    global _redis_client, _redis_listener_task
    if not _HAS_REDIS:
        logger.info("[WS] redis library not available, running in single-pod mode")
        return
    redis_url = redis_url or os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.info("[WS] REDIS_URL not set, running in single-pod mode")
        return

    try:
        _redis_client = redis.from_url(redis_url)
        await _redis_client.ping()
        logger.info(f"[WS] Redis connected: {redis_url}")

        # Start the listener for cross-pod broadcasts
        _redis_listener_task = asyncio.create_task(_redis_listener())
    except Exception as e:
        logger.warning(f"[WS] Redis connection failed ({e}), running in single-pod mode")
        _redis_client = None


async def _redis_listener():
    """Subscribe to ws:broadcast:* pattern and forward to local WebSocket connections."""
    if not _redis_client:
        return

    try:
        pubsub = _redis_client.pubsub()
        await pubsub.psubscribe("ws:broadcast:*")
        logger.info("[WS] Redis listener started on pattern ws:broadcast:*")

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            # channel format: ws:broadcast:{req_id}
            channel = message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"]
            req_id = channel.split(":", 2)[-1]
            data_raw = message["data"]

            if data_raw and req_id and req_id in CONNECTIONS:
                try:
                    payload = data_raw.decode() if isinstance(data_raw, bytes) else data_raw
                    data = json.loads(payload)
                    ws_payload = json.dumps(data)
                    dead = set()
                    for ws in CONNECTIONS.get(req_id, set()):
                        try:
                            await ws.send_text(ws_payload)
                        except Exception:
                            dead.add(ws)
                    for ws in dead:
                        _remove_connection(req_id, ws)
                except Exception:
                    pass
    except asyncio.CancelledError:
        await pubsub.punsubscribe("ws:broadcast:*")
        raise
    except Exception as e:
        logger.error(f"[WS] Redis listener error: {e}")


async def broadcast_to_req(req_id: str, data: dict):
    """Broadcast a message to all WebSocket connections subscribed to req_id.

    Uses Redis PubSub if available (cross-pod), otherwise direct local delivery.
    """
    if _redis_client:
        # Cross-pod broadcast via Redis
        try:
            await _redis_client.publish(f"ws:broadcast:{req_id}", json.dumps(data))
        except Exception as e:
            logger.warning(f"[WS] Redis publish failed: {e}, falling back to local")
            _deliver_locally(req_id, data)
    else:
        _deliver_locally(req_id, data)


def _deliver_locally(req_id: str, data: dict):
    """Deliver a message directly to local WebSocket connections (single-pod mode)."""
    if req_id not in CONNECTIONS:
        return
    payload = json.dumps(data)
    dead = set()
    for ws in CONNECTIONS.get(req_id, set()):
        try:
            # Schedule send on the event loop
            asyncio.ensure_future(_ws_send(ws, payload, req_id, dead))
        except Exception:
            dead.add(ws)
    for ws in dead:
        _remove_connection(req_id, ws)


async def _ws_send(ws: WebSocket, payload: str, req_id: str, dead: set):
    """Helper to send to a single WebSocket, tracking dead connections."""
    try:
        await ws.send_text(payload)
    except Exception:
        dead.add(ws)


async def nats_message_handler(msg):
    """Handle incoming NATS messages and push to relevant WebSocket clients."""
    try:
        data = json.loads(msg.data.decode())
        req_id = data.get("req_id")
        if req_id and req_id in CONNECTIONS:
            payload = json.dumps(data)
            dead = set()
            for ws in CONNECTIONS.get(req_id, set()):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                _remove_connection(req_id, ws)
    except Exception:
        pass  # silently ignore malformed messages


def _add_connection(req_id: str, ws: WebSocket):
    if req_id not in CONNECTIONS:
        CONNECTIONS[req_id] = set()
    CONNECTIONS[req_id].add(ws)
    # Update metrics and log
    try:
        from main import ws_connections_gauge
        ws_connections_gauge.inc()
    except Exception:
        pass
    total = sum(len(v) for v in CONNECTIONS.values())
    logger.info(f"[WS] Connection added for req_id={req_id}, total connections={total}")


def _remove_connection(req_id: str, ws: WebSocket):
    if req_id in CONNECTIONS:
        CONNECTIONS[req_id].discard(ws)
        if not CONNECTIONS[req_id]:
            del CONNECTIONS[req_id]
    # Update metrics and log
    try:
        from main import ws_connections_gauge
        ws_connections_gauge.dec()
    except Exception:
        pass
    total = sum(len(v) for v in CONNECTIONS.values())
    logger.info(f"[WS] Connection removed for req_id={req_id}, total connections={total}")


@router.websocket("/gateway")
async def ws_gateway(websocket: WebSocket, token: str = Query(...)):
    """WebSocket endpoint: /ws/gateway?token=<jwt>&req_id=<optional>"""
    # Validate JWT
    payload = verify_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Extract optional req_id from query
    req_id = websocket.query_params.get("req_id")

    await websocket.accept()
    connection_id = str(uuid.uuid4())[:8]

    if req_id:
        _add_connection(req_id, websocket)

    try:
        # Send welcome message
        await websocket.send_text(json.dumps({
            "type": "connected",
            "connection_id": connection_id,
            "req_id": req_id,
            "user": payload.get("sub"),
        }))

        # Keep connection alive, listen for client messages (ping/pong)
        while True:
            msg = await websocket.receive_text()
            # Client can update subscription by sending {"subscribe": "<req_id>"}
            try:
                data = json.loads(msg)
                if "subscribe" in data:
                    old_req_id = req_id
                    new_req_id = data["subscribe"]
                    if old_req_id:
                        _remove_connection(old_req_id, websocket)
                    req_id = new_req_id
                    if req_id:
                        _add_connection(req_id, websocket)
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "req_id": req_id,
                    }))
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if req_id:
            _remove_connection(req_id, websocket)
