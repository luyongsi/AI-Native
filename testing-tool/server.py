"""Testing tool server — A1 Dialogue Dashboard (FastAPI + SSE)."""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

# Load env
_ENV_FILE = "/etc/ai-native.env"
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ[_key.strip()] = _val.strip()

import yaml
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from checks.infra import _check_postgresql, _check_nats, _check_mc_backend
from checks.truth_spec_self_check import validate_truth_spec
from utils.mc_client import (
    create_requirement, dialogue_chat, dialogue_confirm,
    dialogue_history, dialogue_current, get_requirements,
    get_requirement_detail,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("server")

app = FastAPI(title="A1 Dialogue Test Dashboard", version="2.0")

# ── Global state ──
TRUTH_SPEC: dict = {}
INFRA_BASELINE: dict = {}
SSE_QUEUES: dict[str, asyncio.Queue] = {}
STATUS_CACHE: dict = {}
STATUS_AGE: datetime | None = None


async def _refresh_status_cache():
    global STATUS_CACHE, STATUS_AGE
    spec_issues = validate_truth_spec(TRUTH_SPEC)
    infra = {}
    infra["postgresql"] = await _check_postgresql(INFRA_BASELINE)
    infra["nats"] = await _check_nats(INFRA_BASELINE)
    infra["mc_backend"] = await _check_mc_backend(INFRA_BASELINE)
    infra["redis"] = {"passed": True, "message": "skipped"}
    infra["temporal"] = {"passed": True, "message": "skipped"}
    infra["llm"] = {"passed": True, "message": "skipped"}
    infra["bridge"] = {"passed": True, "message": "skipped"}

    STATUS_CACHE = {
        "spec_self_check": {
            "passed": len([i for i in spec_issues if i.get("severity") == "error"]) == 0,
            "issues": spec_issues,
        },
        "infra": infra,
    }
    STATUS_AGE = datetime.now(timezone.utc)


# ── Startup / Shutdown ─────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global TRUTH_SPEC, INFRA_BASELINE
    spec_path = _THIS_DIR / "truth-spec.yaml"
    infra_path = _THIS_DIR / "infra-baseline.yaml"
    TRUTH_SPEC = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    INFRA_BASELINE = yaml.safe_load(infra_path.read_text(encoding="utf-8"))
    logger.info(f"Loaded truth-spec v{TRUTH_SPEC.get('meta', {}).get('version')}")
    await _refresh_status_cache()
    asyncio.create_task(_status_cache_updater())
    logger.info("A1 Dashboard ready — http://0.0.0.0:8500")


async def _status_cache_updater():
    while True:
        await asyncio.sleep(60)
        try:
            await _refresh_status_cache()
        except Exception as e:
            logger.warning(f"Status cache refresh failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Server shutdown complete")


# ── Static files ───────────────────────────────────────────────────────

static_dir = _THIS_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>A1 Dialogue Dashboard</h1><p>index.html not found</p>")


# ── Status / Config ────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    if STATUS_CACHE:
        return {**STATUS_CACHE, "cached_at": STATUS_AGE.isoformat() if STATUS_AGE else None}
    await _refresh_status_cache()
    return {**STATUS_CACHE, "cached_at": STATUS_AGE.isoformat() if STATUS_AGE else None}


@app.get("/api/config")
async def api_config():
    return {
        "agents": TRUTH_SPEC.get("agents", {}).get("state_agent_map", {}),
    }


# ── Requirements CRUD ──────────────────────────────────────────────────

@app.post("/api/requirements")
async def api_create_requirement(req: dict):
    title = req.get("title", "").strip()
    desc = req.get("description", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    result = await create_requirement(title, desc)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create requirement")
    return result


@app.get("/api/requirements")
async def api_list_requirements(status: str | None = Query(None), limit: int = Query(20)):
    return await get_requirements(limit=limit, status=status)


@app.get("/api/requirements/{req_id}")
async def api_get_requirement(req_id: str):
    detail = await get_requirement_detail(req_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return detail


# ── Dialogue ───────────────────────────────────────────────────────────

@app.get("/api/dialogue/current/{req_id}")
async def api_dialogue_current(req_id: str):
    result = await dialogue_current(req_id)
    if not result:
        raise HTTPException(status_code=404, detail="Failed to get session info")
    return result


@app.get("/api/dialogue/history/{session_id}")
async def api_dialogue_history(session_id: str):
    result = await dialogue_history(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Failed to get history")
    return result


@app.post("/api/dialogue/confirm")
async def api_dialogue_confirm(req: dict):
    session_id = req.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    result = await dialogue_confirm(session_id)
    if not result:
        raise HTTPException(status_code=500, detail="Confirm failed")
    return result


@app.post("/api/dialogue/chat")
async def api_dialogue_chat(req: dict):
    """Start or continue dialogue, stream SSE to frontend."""
    req_id = req.get("req_id", "").strip()
    message = req.get("message", "").strip()
    session_id = req.get("session_id") or None

    if not req_id or not message:
        raise HTTPException(status_code=400, detail="req_id and message required")

    chat_id = f"chat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    queue: asyncio.Queue = asyncio.Queue()
    SSE_QUEUES[chat_id] = queue

    async def event_generator():
        collected_events = []
        try:
            async for line in dialogue_chat(req_id, message, session_id):
                # Strip "data: " prefix if present
                data_str = line
                if line.startswith("data: "):
                    data_str = line[6:]
                try:
                    evt = json.loads(data_str)
                    collected_events.append(evt)
                except json.JSONDecodeError:
                    evt = {"raw": data_str}
                await queue.put({"event": "sse-data", "data": evt})
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"Chat stream error: {e}", exc_info=True)
            err = {"type": "error", "content": str(e)}
            await queue.put({"event": "sse-data", "data": err})
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
        finally:
            await queue.put({"event": "chat-complete", "data": {
                "chat_id": chat_id,
                "events": collected_events,
            }})
            # Keep queue for 5min then cleanup
            asyncio.get_event_loop().call_later(300, lambda: SSE_QUEUES.pop(chat_id, None))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/dialogue/stream/{chat_id}")
async def api_chat_stream(chat_id: str, request: Request):
    """Secondary SSE endpoint: replay collected events from a completed chat."""
    queue = SSE_QUEUES.get(chat_id)
    if not queue:
        raise HTTPException(status_code=404, detail="chat_id not found")

    async def replay():
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'], ensure_ascii=False, default=str)}\n\n"
            except asyncio.TimeoutError:
                yield f"event: ping\ndata: {json.dumps({'ts': datetime.now(timezone.utc).isoformat()})}\n\n"

    return StreamingResponse(replay(), media_type="text/event-stream")


# ── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8500)
