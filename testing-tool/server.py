"""Testing tool server — FastAPI + SSE dashboard."""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Load env from /etc/ai-native.env (same as worker_launcher)
_ENV_FILE = "/etc/ai-native.env"
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ[_key.strip()] = _val.strip()
    logger = logging.getLogger("env")
    logger.info("Loaded environment from /etc/ai-native.env")

import yaml
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Ensure testing-tool directory on path
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from checks.infra import run_all_infra_checks
from checks.truth_spec_self_check import validate_truth_spec
from checks.source_truth_consistency import check_source_truth_consistency
from observer import PipelineObserver
from preflight import PreFlightValidator
from cleanup import (
    cleanup_all_test_data, cleanup_orphan_test_data,
    cleanup_worktrees, full_test_cleanup,
)
from utils.db import get_pool, close_pool, insert_requirement, fetch_requirement
from utils.mc_client import create_requirement, trigger_workflow
from utils.temporal_client import connect_temporal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("server")

app = FastAPI(title="AI Native Pipeline Test Dashboard", version="1.0")

# ── Global state ──
DB_POOL = None
TRUTH_SPEC: dict = {}
INFRA_BASELINE: dict = {}
TEMPORAL_CLIENT = None
RUNNING_OBSERVERS: dict[str, PipelineObserver] = {}
SSE_QUEUES: dict[str, asyncio.Queue] = {}
HISTORY: list[dict] = []
STATUS_CACHE: dict = {}
STATUS_AGE: datetime | None = None


async def _refresh_status_cache():
    """Background: refresh infra + truth spec status (skip heavy LLM check)."""
    global STATUS_CACHE, STATUS_AGE
    nats_url = INFRA_BASELINE.get("nats", {}).get("url", "nats://localhost:4222")
    spec_issues = validate_truth_spec(TRUTH_SPEC)

    # Lightweight checks only: PG, NATS, MC Backend, worktrees (skip LLM/Temporal/Bridge)
    infra = {}
    from checks.infra import _check_postgresql, _check_nats, _check_mc_backend
    infra["postgresql"] = await _check_postgresql(INFRA_BASELINE)
    infra["nats"] = await _check_nats(INFRA_BASELINE)
    infra["mc_backend"] = await _check_mc_backend(INFRA_BASELINE)
    infra["redis"] = {"passed": True, "message": "skipped in background cache"}
    infra["temporal"] = {"passed": True, "message": "skipped in background cache"}
    infra["llm"] = {"passed": True, "message": "skipped in background cache, checked on /api/tests/run"}
    infra["bridge"] = {"passed": True, "message": "skipped in background cache"}

    preflight = {"ready": True, "issues": [], "checks": {}}
    STATUS_CACHE = {
        "spec_self_check": {
            "passed": len([i for i in spec_issues if i.get("severity", "error") == "error"]) == 0,
            "issues": spec_issues,
        },
        "infra": infra,
        "preflight": preflight,
    }
    STATUS_AGE = datetime.now(timezone.utc)

# ══════════════════════════════════════════════════════════════════════
# Startup / Shutdown
# ══════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    global DB_POOL, TRUTH_SPEC, INFRA_BASELINE, TEMPORAL_CLIENT, STATUS_CACHE, STATUS_AGE

    # Load config
    spec_path = _THIS_DIR / "truth-spec.yaml"
    infra_path = _THIS_DIR / "infra-baseline.yaml"
    TRUTH_SPEC = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    INFRA_BASELINE = yaml.safe_load(infra_path.read_text(encoding="utf-8"))
    logger.info(f"Loaded truth-spec.yaml (version={TRUTH_SPEC.get('meta', {}).get('version')})")
    logger.info(f"Loaded infra-baseline.yaml")

    # Init DB
    from utils.db import DATABASE_URL
    DB_POOL = await get_pool()
    logger.info("Database pool initialized")

    # Init Temporal
    TEMPORAL_CLIENT = await connect_temporal()

    # Orphan cleanup on startup
    try:
        db_result = await cleanup_orphan_test_data(DB_POOL, max_age_hours=24)
        if db_result.get("cleaned"):
            logger.info(f"Startup orphan cleanup: {db_result['orphans_cleaned']} requirements removed")
        wt_result = cleanup_worktrees()
        if wt_result.get("cleaned"):
            logger.info(f"Startup worktree cleanup: {wt_result['removed_count']} directories removed")
    except Exception as e:
        logger.warning(f"Startup orphan cleanup failed (non-fatal): {e}")

    # Fill initial status cache
    await _refresh_status_cache()
    # Start background cache updater
    asyncio.create_task(_status_cache_updater())
    logger.info("Server ready — Dashboard at http://0.0.0.0:8500")


async def _status_cache_updater():
    """Periodically refresh the status cache."""
    while True:
        await asyncio.sleep(60)
        try:
            await _refresh_status_cache()
        except Exception as e:
            logger.warning(f"Status cache refresh failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    global DB_POOL
    if DB_POOL:
        await close_pool()
    logger.info("Server shutdown complete")


# ══════════════════════════════════════════════════════════════════════
# Static files
# ══════════════════════════════════════════════════════════════════════

static_dir = _THIS_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Testing Tool Dashboard</h1><p>index.html not found</p>")


# ══════════════════════════════════════════════════════════════════════
# API: Run test
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/tests/run")
async def api_run_test(req: dict):
    title = req.get("title", "").strip()
    description = req.get("description", "").strip()
    gate_strategy = req.get("gate_strategy", "auto")
    keep_data = req.get("keep_data", False)
    timeout_minutes = req.get("timeout_minutes", 120)

    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    # Pre-flight NATS check
    nats_url = INFRA_BASELINE.get("nats", {}).get("url", "nats://localhost:4222")
    preflight = PreFlightValidator(nats_url)
    pf_result = await preflight.validate()
    if not pf_result.get("ready"):
        return {
            "ok": False,
            "error": "Pre-flight check failed",
            "preflight": pf_result,
        }

    # Create requirement via MC Backend
    result = await create_requirement(title, description)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create requirement via MC Backend")

    req_id = result.get("id", "")
    # Trigger workflow
    wf_id = await trigger_workflow(req_id)
    if not wf_id:
        raise HTTPException(status_code=500, detail="Failed to trigger workflow")

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    queue: asyncio.Queue = asyncio.Queue()
    SSE_QUEUES[run_id] = queue

    async def event_cb(event: str, data: dict):
        await queue.put({"event": event, "data": data})

    observer = PipelineObserver(
        req_id=req_id,
        workflow_id=wf_id,
        gate_strategy=gate_strategy,
        truth_spec=TRUTH_SPEC,
        db_pool=DB_POOL,
        temporal_client=TEMPORAL_CLIENT,
        keep_data=keep_data,
        event_callback=event_cb,
    )
    RUNNING_OBSERVERS[run_id] = observer

    # Start observer in background
    async def run_observer():
        try:
            result = await observer.run()
            result["title"] = title
            HISTORY.append({
                "run_id": run_id,
                "title": title,
                "started_at": result["started_at"],
                "final_state": result["final_state"],
                "total_duration_s": result["total_duration_s"],
            })
            # Keep only last 50
            while len(HISTORY) > 50:
                HISTORY.pop(0)
            await queue.put({"event": "run-complete", "data": result})
        except Exception as e:
            logger.error(f"Observer error: {e}", exc_info=True)
            await queue.put({"event": "run-error", "data": {"error": str(e)}})
        finally:
            RUNNING_OBSERVERS.pop(run_id, None)

    asyncio.create_task(run_observer())

    return {
        "ok": True,
        "run_id": run_id,
        "req_id": req_id,
        "workflow_id": wf_id,
        "gate_strategy": gate_strategy,
    }


# ══════════════════════════════════════════════════════════════════════
# API: SSE stream
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/tests/stream/{run_id}")
async def api_stream(run_id: str, request: Request):
    queue = SSE_QUEUES.get(run_id)
    if not queue:
        raise HTTPException(status_code=404, detail="run_id not found")

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'], ensure_ascii=False, default=str)}\n\n"
            except asyncio.TimeoutError:
                yield f"event: ping\ndata: {json.dumps({'ts': datetime.now(timezone.utc).isoformat()})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════
# API: Results / History / Status
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/tests/results/{run_id}")
async def api_results(run_id: str):
    observer = RUNNING_OBSERVERS.get(run_id)
    if observer:
        return observer._build_result()
    # Try history
    for h in HISTORY:
        if h.get("run_id") == run_id:
            return h
    raise HTTPException(status_code=404, detail="run_id not found")


@app.get("/api/tests/history")
async def api_history():
    return {"items": list(reversed(HISTORY[-50:]))}


@app.get("/api/tests/status")
async def api_status():
    """Return cached status (refreshed periodically to avoid slow infra checks)."""
    if STATUS_CACHE:
        return {**STATUS_CACHE, "cached_at": STATUS_AGE.isoformat() if STATUS_AGE else None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    # Fallback: first request before cache filled
    await _refresh_status_cache()
    return {**STATUS_CACHE, "cached_at": STATUS_AGE.isoformat() if STATUS_AGE else None,
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/tests/derived-config")
async def api_derived_config():
    """Return the parsed truth-spec config for frontend state flow rendering."""
    return {
        "transitions": TRUTH_SPEC.get("state_machine", {}).get("normal_flow", {}),
        "state_agents": TRUTH_SPEC.get("agents", {}).get("state_agent_map", {}),
        "parallel_states": TRUTH_SPEC.get("agents", {}).get("parallel_states", {}),
        "gated_states": {
            g["runs_in_state"]: {"level": g["level"], "next_state": g["next_state"]}
            for g in TRUTH_SPEC.get("gates", [])
        },
    }


# ══════════════════════════════════════════════════════════════════════
# API: Cleanup
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/cleanup")
async def api_cleanup_all():
    db_result = await cleanup_all_test_data(DB_POOL)
    wt_result = cleanup_worktrees()
    return {
        "database": db_result,
        "worktrees": wt_result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/cleanup/{req_id}")
async def api_cleanup_single(req_id: str):
    result = await full_test_cleanup(
        db_pool=DB_POOL,
        temporal_client=TEMPORAL_CLIENT,
        req_id=req_id,
        workflow_id=None,
        keep_data=False,
    )
    return result


@app.get("/api/cleanup/stats")
async def api_cleanup_stats():
    async with DB_POOL.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt, MIN(created_at) as oldest "
            "FROM requirements WHERE external_id LIKE 'TEST-%'"
        )
    from pathlib import Path
    wt_path = Path("/tmp/a9-runtimes")
    wt_dirs = list(wt_path.glob("wt-*")) if wt_path.exists() else []
    wt_size_kb = 0
    for d in wt_dirs:
        wt_size_kb += sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) // 1024

    return {
        "test_requirements": row["cnt"] if row else 0,
        "oldest_test_data": row["oldest"].isoformat() if row and row["oldest"] else None,
        "a9_worktrees": len(wt_dirs),
        "worktree_total_size_kb": wt_size_kb,
    }


# ══════════════════════════════════════════════════════════════════════
# API: Diagnose
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/diagnose/{req_id}")
async def api_diagnose(req_id: str):
    """Snapshot diagnosis for an existing req_id (no agents triggered)."""
    req = await fetch_requirement(req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Requirement not found")

    spec = req.get("spec", {})
    db_snapshot = {
        "title": req.get("title", ""),
        "status": req.get("status", ""),
        "spec": {
            "openapi": spec.get("openapi", {}),
            "erd": spec.get("erd", {}),
            "artifacts": spec.get("artifacts", {}),
        },
    }

    from checks.runtime_verifier import RuntimeVerifier
    verifier = RuntimeVerifier(TRUTH_SPEC, DB_POOL)

    # Run all applicable checks for current state
    state = req.get("status", "draft")
    findings = []

    # Check persistence for each agent in the artifacts
    for agent_id in spec.get("artifacts", {}):
        f = await verifier.check_persistence_contracts(agent_id, req_id)
        findings.extend(f)

    # Worktree check
    findings.extend(verifier.check_worktree_cleanup_sync())

    return {
        "req_id": req_id,
        "title": req.get("title"),
        "status": state,
        "external_id": req.get("external_id"),
        "created_at": req.get("created_at"),
        "updated_at": req.get("updated_at"),
        "spec_summary": {
            "has_openapi": bool(spec.get("openapi")),
            "has_erd": bool(spec.get("erd")),
            "artifact_agents": list(spec.get("artifacts", {}).keys()),
        },
        "findings": findings,
    }


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8500)
