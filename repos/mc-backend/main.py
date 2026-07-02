"""
Mission Control Backend - Main Application Entry Point
FastAPI app that mounts all API routers, connects to NATS + PostgreSQL on startup.

Phase 5.3: Observability — integrated mc_observability middleware + metrics.
"""
import asyncio
import os
import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import nats
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from prometheus_client import generate_latest

from mc_observability import (
    setup_observability,
    REGISTRY as METRICS_REGISTRY,
    collect_db_metrics,
    ws_connections_gauge,
    record_nats_event,
)

logger = logging.getLogger(__name__)

# Global connection pool and NATS client
DB_POOL: asyncpg.Pool | None = None
NATS_CLIENT: nats.NATS | None = None
REDIS_CLIENT: Any | None = None

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
)
NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


async def start_nats():
    """Connect to NATS and subscribe to agent status changes."""
    global NATS_CLIENT
    try:
        NATS_CLIENT = await nats.connect(NATS_URL)
        await NATS_CLIENT.subscribe("agent.status.changed", cb=ws_nats_handler)
        print(f"[NATS] Connected to {NATS_URL}, subscribed to agent.status.changed")
    except Exception as e:
        print(f"[NATS] Connection failed: {e}")


def ws_nats_handler(msg):
    """NATS message callback — bridges to asyncio for ws_gateway + metrics."""
    from ws.ws_gateway import nats_message_handler
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(nats_message_handler(msg), loop=loop)
    # Record event for observability
    try:
        import json
        data = json.loads(msg.data.decode())
        event_type = data.get("event_type", msg.subject)
        record_nats_event(event_type, data.get("agent_id", ""), data.get("req_id", ""))
    except Exception:
        pass


async def start_db():
    """Create asyncpg connection pool."""
    global DB_POOL
    DB_POOL = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    print(f"[DB] Connection pool created for {DATABASE_URL}")


async def stop_nats():
    global NATS_CLIENT
    if NATS_CLIENT:
        await NATS_CLIENT.drain()
        print("[NATS] Disconnected")


async def stop_db():
    global DB_POOL
    if DB_POOL:
        await DB_POOL.close()
        print("[DB] Connection pool closed")


# Background metrics collector
async def metrics_collector_loop():
    """Periodically refresh DB-sourced metrics gauges."""
    while True:
        try:
            if DB_POOL:
                await collect_db_metrics(DB_POOL)
        except Exception as e:
            logger.warning(f"Metrics collector error: {e}")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global REDIS_CLIENT
    await start_db()
    await start_nats()
    from ws.ws_gateway import init_redis
    await init_redis()
    # Initialize Redis for embedding service
    import redis.asyncio as redis
    try:
        REDIS_CLIENT = await redis.from_url("redis://localhost:6379", decode_responses=False)
        await REDIS_CLIENT.ping()
        logger.info("[Redis] Connected for embedding cache")
    except Exception as e:
        logger.warning(f"[Redis] Connection failed for embeddings: {e}")
    # Start background metrics collector
    bg_task = asyncio.create_task(metrics_collector_loop())
    yield
    # Shutdown
    bg_task.cancel()
    if REDIS_CLIENT:
        await REDIS_CLIENT.close()
    await stop_nats()
    await stop_db()


app = FastAPI(title="Mission Control Backend", version="0.1.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Observability middleware (request latency + structured logging)
setup_observability(app)

# Mount API routers
from api.dashboard import router as dashboard_router
from api.requirements import router as requirements_router
from api.agents import router as agents_router
from api.approvals import router as approvals_router
from api.tests import router as tests_router
from api.insights import router as insights_router
from ws.ws_gateway import router as ws_router
from api.workflow import router as workflow_router

app.include_router(dashboard_router)
app.include_router(requirements_router)
app.include_router(agents_router)
app.include_router(approvals_router)
app.include_router(tests_router)
app.include_router(insights_router)
app.include_router(ws_router)
app.include_router(workflow_router)

# Optional Phase 4 routers
optional_routers = {
    "topology": "api.topology", "releases": "api.releases",
    "alerts": "api.alerts", "notifications": "api.notifications",
    "knowledge": "api.knowledge", "chat_spec": "api.chat_spec",
    "test_cases": "api.test_cases",
}
for name, module_path in optional_routers.items():
    try:
        mod = __import__(module_path, fromlist=["router"])
        router = getattr(mod, "router", None)
        if router is not None:
            app.include_router(router)
    except ImportError:
        pass


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(METRICS_REGISTRY), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
