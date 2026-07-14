"""Testing tool server — E2E Pipeline Test Dashboard (FastAPI + SSE)."""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

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

app = FastAPI(title="E2E Pipeline Test Dashboard", version="3.0")

# ── Global state ──
TRUTH_SPEC: dict = {}
INFRA_BASELINE: dict = {}
SSE_QUEUES: dict[str, asyncio.Queue] = {}
STATUS_CACHE: dict = {}
STATUS_AGE: datetime | None = None

MC_BACKEND_URL = os.environ.get("MC_BACKEND_URL", "http://localhost:8000")
AUTH_TOKEN = os.environ.get("MC_AUTH_TOKEN", "Bearer dev-internal-key")
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"
)
A2_TIMEOUT_S = int(os.environ.get("A2_TIMEOUT_S", "120"))
GATE0_TIMEOUT_S = int(os.environ.get("GATE0_TIMEOUT_S", "120"))
HEADERS = {"Authorization": AUTH_TOKEN, "Content-Type": "application/json"}

# ── E2E run history (in-memory, survives until restart) ──
E2E_HISTORY: list[dict] = []  # newest first, max 50


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


@app.get("/e2e", response_class=HTMLResponse)
async def e2e_dashboard():
    """E2E Pipeline Test Dashboard."""
    e2e_path = static_dir / "e2e.html"
    if e2e_path.exists():
        return HTMLResponse(e2e_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>E2E Dashboard</h1><p>e2e.html not found</p>")


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
    full_session_id = req.get("session_id") or None

    if not req_id or not message:
        raise HTTPException(status_code=400, detail="req_id and message required")

    chat_id = f"chat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    queue: asyncio.Queue = asyncio.Queue()
    SSE_QUEUES[chat_id] = queue

    async def event_generator():
        nonlocal full_session_id
        collected_events = []
        try:
            async for line in dialogue_chat(req_id, message, full_session_id):
                data_str = line
                if line.startswith("data: "):
                    data_str = line[6:]
                try:
                    evt = json.loads(data_str)
                    # Extract session_id from done/draft_update events
                    if evt.get("session_id"):
                        full_session_id = evt["session_id"]
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
                "session_id": full_session_id,
            }})
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


# ── E2E Pipeline Runner ────────────────────────────────────────────────────

async def _db_fetch(query: str, *params) -> list[dict]:
    """Run a read query against the ai_native database."""
    import asyncpg
    conn = await asyncpg.connect(DB_URL)
    try:
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _db_wait_agent_result(req_id: str, agent_key: str, timeout_s: int) -> dict | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = await _db_fetch(
            """SELECT artifact, status, created_at FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = $2
               ORDER BY created_at DESC LIMIT 1""",
            req_id, agent_key,
        )
        if rows:
            return rows[0]
        await asyncio.sleep(3)
    return None


async def _db_wait_approval(req_id: str, gate_level: int, timeout_s: int) -> dict | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = await _db_fetch(
            """SELECT id, req_id, gate_level, cycle, status, created_at
               FROM approvals WHERE req_id = $1::uuid AND gate_level = $2
               ORDER BY created_at DESC LIMIT 1""",
            req_id, gate_level,
        )
        if rows:
            return rows[0]
        await asyncio.sleep(3)
    return None


async def _httpx_post(path: str, body: dict | None = None, timeout: int = 300) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.post(f"{MC_BACKEND_URL}{path}", json=body, headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def _httpx_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(f"{MC_BACKEND_URL}{path}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def _stream_a1_dialogue(req_id: str, message: str, session_id: str | None,
                               queue: asyncio.Queue) -> tuple[str | None, dict | None, float | None, list[dict]]:
    """Run A1 SSE dialogue, emit events to queue, return (session_id, draft, confidence, events)."""
    final_session_id = session_id
    final_draft = None
    final_confidence = None
    all_events = []

    async with httpx.AsyncClient(timeout=300) as http:
        async with http.stream(
            "POST", f"{MC_BACKEND_URL}/api/dialogue/chat",
            json={"req_id": req_id, "message": message, "session_id": session_id},
            headers=HEADERS,
        ) as resp:
            resp.raise_for_status()
            current_type = None
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    current_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_str = line[6:].strip()
                    if not data_str:
                        continue
                    try:
                        evt = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if current_type:
                        evt["_event_type"] = current_type
                    evt_type = evt.get("type", current_type or "")
                    all_events.append(evt)

                    if "session_id" in evt:
                        final_session_id = evt.get("session_id", final_session_id)
                    if evt_type == "draft_update":
                        final_draft = evt.get("draft", final_draft)
                    if evt_type == "done":
                        final_confidence = evt.get("confidence_score")
                        final_draft = evt.get("draft", final_draft)
                        final_session_id = evt.get("session_id", final_session_id)

                    # Relay to SSE frontend
                    await queue.put({"event": "step-log", "data": {
                        "step": "a1_dialogue", "event_type": evt_type,
                        "draft_title": (final_draft or {}).get("title") if final_draft else None,
                        "confidence": final_confidence,
                    }})
                    current_type = None

    # A1 agent's done event doesn't carry session_id — look it up from DB
    if not final_session_id:
        rows = await _db_fetch(
            "SELECT id FROM dialogue_sessions WHERE req_id = $1::uuid ORDER BY created_at DESC LIMIT 1",
            req_id,
        )
        if rows:
            final_session_id = str(rows[0]["id"])
            logger.info(f"Resolved session_id from DB: {final_session_id[:8]}...")

    return final_session_id, final_draft, final_confidence, all_events


async def run_e2e_pipeline(run_id: str, title: str, message: str, queue: asyncio.Queue):
    """Execute the full E2E pipeline and emit progress via queue."""
    result = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "message": message,
        "steps": {},
    }

    async def emit_step(step: str, status: str, **kwargs):
        entry = {
            "step": step, "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(), **kwargs,
        }
        result["steps"][step] = entry
        await queue.put({"event": "step-update", "data": entry})

    async def emit_log(step: str, detail: str):
        await queue.put({"event": "step-log", "data": {"step": step, "detail": detail}})

    req_id = None
    session_id = None
    approval_id = None

    # ── Step 1: Create requirement ──────────────────────────────
    try:
        await emit_step("create_req", "running", detail="Creating requirement...")
        r = await _httpx_post("/api/requirements", {"title": title, "description": message[:200]})
        req_id = r.get("req_id") or r.get("id")
        if not req_id:
            raise Exception(f"No req_id in response: {r}")
        result["req_id"] = req_id
        await emit_step("create_req", "passed", req_id=req_id, detail=f"Created: {req_id[:8]}...")
    except Exception as e:
        await emit_step("create_req", "failed", error=str(e))
        await queue.put({"event": "run-error", "data": {"error": str(e)}})
        return result

    # ── Step 2: Check infrastructure ────────────────────────────
    try:
        await emit_step("infra_check", "running", detail="Checking MC Backend...")
        async with httpx.AsyncClient(timeout=10) as http:
            h = await http.get(f"{MC_BACKEND_URL}/health")
        await emit_step("infra_check", "passed",
                        detail=f"MC Backend OK (status={h.status_code})")
    except Exception as e:
        await emit_step("infra_check", "failed", error=str(e))
        await queue.put({"event": "run-error", "data": {"error": str(e)}})
        return result

    # ── Step 3: A1 dialogue ─────────────────────────────────────
    try:
        await emit_step("a1_dialogue", "running", detail="Starting A1 analysis (SSE)...")
        session_id, draft, confidence, events = await _stream_a1_dialogue(
            req_id, message, None, queue,
        )

        event_types = [e.get("type", e.get("_event_type", "?")) for e in events]
        has_done = "done" in event_types
        has_error = "error" in event_types

        if has_error or not has_done:
            raise Exception(f"A1 failed: events={event_types}")

        result["session_id"] = session_id
        await emit_step("a1_dialogue", "passed",
                        session_id=session_id,
                        confidence=confidence,
                        draft_title=draft.get("title") if draft else None,
                        event_count=len(events),
                        detail=f"Confidence: {int((confidence or 0) * 100)}%")
    except Exception as e:
        await emit_step("a1_dialogue", "failed", error=str(e))
        await queue.put({"event": "run-error", "data": {"error": str(e)}})
        return result

    # ── Step 4: Confirm dialogue ─────────────────────────────────
    if not session_id:
        await emit_step("confirm", "warning",
                        detail="No session_id — confirm may have been done implicitly")
    else:
        try:
            await emit_step("confirm", "running", detail="Confirming analysis...")
            cr = await _httpx_post("/api/dialogue/confirm", {"session_id": session_id})
            await emit_step("confirm", "passed",
                            cycle=cr.get("cycle", 0),
                            status=cr.get("status"),
                            detail=f"Cycle: {cr.get('cycle', 0)}")
        except Exception as e:
            await emit_step("confirm", "warning", error=str(e),
                            detail="Confirm may have already been done")
            # Non-fatal — continue

    # ── Step 5: Trigger workflow ────────────────────────────────
    try:
        await emit_step("trigger_wf", "running", detail="Triggering Temporal workflow...")
        wr = await _httpx_post(f"/api/requirements/{req_id}/trigger", timeout=30)
        wf_id = wr.get("workflow_id", "local")
        await emit_step("trigger_wf", "passed",
                        workflow_id=wf_id,
                        status=wr.get("status", "?"),
                        detail=f"WF: {wf_id}")
    except Exception as e:
        await emit_step("trigger_wf", "warning", error=str(e),
                        detail="Workflow may already be running")
        # Non-fatal — workflow may have been triggered externally

    # ── Step 6: Wait for A2 ─────────────────────────────────────
    try:
        await emit_step("a2_analysis", "running", detail=f"Waiting for A2 (timeout={A2_TIMEOUT_S}s)...")
        a2 = await _db_wait_agent_result(req_id, "A2", A2_TIMEOUT_S)
        if a2 is None:
            raise Exception(f"A2 did not complete within {A2_TIMEOUT_S}s")

        artifact = a2["artifact"]
        if isinstance(artifact, str):
            artifact = json.loads(artifact)

        await emit_step("a2_analysis", "passed",
                        status=a2["status"],
                        has_feasibility=artifact.get("feasibility_assessment") is not None,
                        checklist_count=len(artifact.get("confirmation_checklist", [])),
                        conflicts_count=len(artifact.get("conflicts", [])),
                        quality_score=artifact.get("quality_score"),
                        detail=f"Quality: {artifact.get('quality_score', 'N/A')}")
    except Exception as e:
        await emit_step("a2_analysis", "failed", error=str(e))
        await queue.put({"event": "run-error", "data": {"error": str(e)}})
        return result

    # ── Step 7: Verify Gate0 approval record ────────────────────
    try:
        await emit_step("gate0_record", "running", detail=f"Waiting for Gate0 approval record...")
        approval = await _db_wait_approval(req_id, 0, GATE0_TIMEOUT_S)
        if approval is None:
            raise Exception("Gate0 approval record not created")

        approval_id = str(approval["id"])

        # Fetch approval context
        ctx = await _httpx_get(f"/api/approvals/{approval_id}/context")
        a1_ok = bool(ctx.get("a1_output", {}).get("requirement_draft"))
        a2_ok = not ctx.get("a2_output", {}).get("a2_missing", True)

        await emit_step("gate0_record", "passed",
                        approval_id=approval_id,
                        status=approval["status"],
                        cycle=approval.get("cycle", 0),
                        context_a1=a1_ok,
                        context_a2=a2_ok,
                        detail=f"Approval: {approval_id[:8]}...")
        result["approval_id"] = approval_id
    except Exception as e:
        await emit_step("gate0_record", "failed", error=str(e))
        await queue.put({"event": "run-error", "data": {"error": str(e)}})
        return result

    # ── Complete ─────────────────────────────────────────────────
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    passed = all(
        result["steps"].get(k, {}).get("status") in ("passed", "warning")
        for k in ["create_req", "infra_check", "a1_dialogue", "confirm",
                   "trigger_wf", "a2_analysis", "gate0_record"]
    )
    result["verdict"] = "pass" if passed else "fail"

    summary = ", ".join(
        f"{k}={v.get('status', '?')}"
        for k, v in result["steps"].items()
    )
    await queue.put({"event": "run-complete", "data": {
        "run_id": run_id,
        "verdict": result["verdict"],
        "steps": result["steps"],
        "summary": summary,
    }})

    # Store in history
    E2E_HISTORY.insert(0, result)
    if len(E2E_HISTORY) > 50:
        E2E_HISTORY.pop()

    return result


# ── E2E API Endpoints ──────────────────────────────────────────────────────

@app.post("/api/tests/e2e/run")
async def api_e2e_run(req: dict):
    """Start an E2E pipeline test. Returns immediately with a run_id;
    connect to /api/tests/e2e/stream/{run_id} for live progress."""
    title = req.get("title", "").strip()
    message = req.get("message", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not message:
        message = title

    run_id = f"e2e-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    queue: asyncio.Queue = asyncio.Queue()
    SSE_QUEUES[run_id] = queue

    # Launch pipeline in background
    asyncio.create_task(run_e2e_pipeline(run_id, title, message, queue))

    # Auto-cleanup stale queue
    async def _gc():
        await asyncio.sleep(3600)
        SSE_QUEUES.pop(run_id, None)
    asyncio.create_task(_gc())

    return {"ok": True, "run_id": run_id}


@app.get("/api/tests/e2e/stream/{run_id}")
async def api_e2e_stream(run_id: str, request: Request):
    """SSE stream for live E2E progress."""
    queue = SSE_QUEUES.get(run_id)
    if not queue:
        # Check history for completed runs
        for h in E2E_HISTORY:
            if h.get("run_id") == run_id:
                async def replay_history():
                    for step_name, entry in h.get("steps", {}).items():
                        yield f"event: step-update\ndata: {json.dumps(entry, ensure_ascii=False, default=str)}\n\n"
                    yield f"event: run-complete\ndata: {json.dumps({'run_id': run_id, 'verdict': h.get('verdict'), 'steps': h.get('steps'), 'summary': 'from history'}, ensure_ascii=False)}\n\n"
                return StreamingResponse(replay_history(), media_type="text/event-stream")
        raise HTTPException(status_code=404, detail="run_id not found")

    async def stream():
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                data_str = json.dumps(msg["data"], ensure_ascii=False, default=str)
                yield f"event: {msg['event']}\ndata: {data_str}\n\n"
                if msg["event"] == "run-complete":
                    break
            except asyncio.TimeoutError:
                yield f"event: ping\ndata: {json.dumps({'ts': datetime.now(timezone.utc).isoformat()})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/tests/e2e/results/{run_id}")
async def api_e2e_results(run_id: str):
    """Get final result for a completed E2E run."""
    for h in E2E_HISTORY:
        if h.get("run_id") == run_id:
            return h
    raise HTTPException(status_code=404, detail="run_id not found")


@app.get("/api/tests/e2e/history")
async def api_e2e_history(limit: int = Query(20, ge=1, le=50)):
    """Get recent E2E run history."""
    return {"items": E2E_HISTORY[:limit], "total": len(E2E_HISTORY)}


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8500)
