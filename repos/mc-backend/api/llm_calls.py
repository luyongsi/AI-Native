"""
LLM Call Monitor API — read audit logs from filesystem.

Reads the JSONL metadata file and per-call JSON files produced by
llm_provider.audit.LLMAuditor. No database dependency.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm-calls", tags=["llm-calls"])

DEFAULT_LOG_PATH = os.environ.get(
    "LLM_AUDIT_LOG", "/opt/ai-native/logs/llm_audit.jsonl"
)
DEFAULT_CALLS_DIR = os.environ.get(
    "LLM_AUDIT_CALLS_DIR",
    str(Path(DEFAULT_LOG_PATH).parent / "llm_calls"),
)
CACHE_TTL_SECONDS = 30

# ── In-memory cache ──────────────────────────────────────────────────────

_cache_timestamp: float = 0
_cached_lines: list[dict] = []
# call_id → req_id index (lazy-built from JSONL metadata)
_call_req_index: dict[str, str] = {}


def _log_path() -> str:
    return DEFAULT_LOG_PATH


def _parse_line(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Skipping malformed JSONL line: %s...", raw[:80])
        return None


def _read_jsonl(force: bool = False) -> list[dict]:
    """Read and parse the JSONL audit file. Returns list of metadata dicts.

    Uses a TTL cache (30 s) to avoid re-reading on every request.
    """
    global _cache_timestamp, _cached_lines
    now = time.monotonic()
    if not force and (now - _cache_timestamp) < CACHE_TTL_SECONDS:
        return _cached_lines

    path = _log_path()
    if not os.path.isfile(path):
        logger.warning("LLM audit log not found: %s", path)
        _cached_lines = []
        _cache_timestamp = now
        return _cached_lines

    lines: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            parsed = _parse_line(raw)
            if parsed is not None:
                lines.append(parsed)

    _cached_lines = lines
    _cache_timestamp = now
    return _cached_lines


def _build_req_index() -> dict[str, str]:
    """Build call_id → req_id lookup from cached JSONL lines."""
    global _call_req_index
    lines = _read_jsonl()
    _call_req_index = {
        line.get("call_id", ""): line.get("req_id", "UNKNOWN")
        for line in lines
        if line.get("call_id")
    }
    return _call_req_index


def _find_req_id(call_id: str) -> str | None:
    """Look up req_id for a given call_id from the cached index."""
    if not _call_req_index:
        _build_req_index()
    return _call_req_index.get(call_id)


# ── Pydantic models ──────────────────────────────────────────────────────


class LLMCallItem(BaseModel):
    call_id: str = ""
    agent_id: str = ""
    req_id: str = ""
    workflow_id: str = ""
    task_type: str = ""
    provider: str = ""
    model: str = ""
    prompt_chars: int = 0
    status: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_chars: int = 0
    response_preview: str = ""
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class LLMCallDetail(LLMCallItem):
    prompt: Optional[str] = None
    response: Optional[str] = None
    tokens_detail: Optional[dict] = None


class LLMCallListResponse(BaseModel):
    items: list[LLMCallItem]
    total: int
    limit: int
    offset: int


# ── Helpers ──────────────────────────────────────────────────────────────


def _row_to_item(row: dict) -> LLMCallItem:
    return LLMCallItem(
        call_id=row.get("call_id", ""),
        agent_id=row.get("agent_id", ""),
        req_id=row.get("req_id", ""),
        workflow_id=row.get("workflow_id", ""),
        task_type=row.get("task_type", ""),
        provider=row.get("provider", ""),
        model=row.get("model", ""),
        prompt_chars=row.get("prompt_chars", 0),
        status=row.get("status", ""),
        started_at=row.get("started_at", ""),
        ended_at=row.get("ended_at", ""),
        duration_ms=row.get("duration_ms", 0),
        prompt_tokens=row.get("prompt_tokens", 0),
        completion_tokens=row.get("completion_tokens", 0),
        total_tokens=row.get("total_tokens", 0),
        response_chars=row.get("response_chars", 0),
        response_preview=(row.get("response_preview") or "")[:500],
        error_type=row.get("error_type"),
        error_message=row.get("error_message"),
    )


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("")
async def list_llm_calls(
    agent_id: Optional[str] = Query(None, description="Filter by agent_id"),
    req_id: Optional[str] = Query(None, description="Filter by req_id (substring match)"),
    task_type: Optional[str] = Query(None, description="Filter by task_type"),
    status: Optional[str] = Query(None, description="Filter by status (success/error)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> LLMCallListResponse:
    """List LLM calls from the audit log, with filtering and pagination."""
    lines = _read_jsonl()

    # Apply filters
    filtered: list[dict] = []
    for row in lines:
        if agent_id and row.get("agent_id") != agent_id:
            continue
        if req_id and req_id not in row.get("req_id", ""):
            continue
        if task_type and row.get("task_type") != task_type:
            continue
        if status and row.get("status") != status:
            continue
        filtered.append(row)

    # Sort by started_at descending (most recent first)
    filtered.sort(key=lambda r: r.get("started_at", ""), reverse=True)

    total = len(filtered)
    page = filtered[offset : offset + limit]

    items = [_row_to_item(r) for r in page]
    return LLMCallListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{call_id}")
async def get_llm_call(call_id: str) -> LLMCallDetail:
    """Get full detail of a single LLM call including prompt and response."""
    req_id = _find_req_id(call_id)
    if req_id is None:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    req_prefix = req_id[:8] if req_id else "UNKNOWN"
    calls_dir = Path(DEFAULT_CALLS_DIR)
    call_file = calls_dir / req_prefix / f"{call_id}.json"

    if not call_file.is_file():
        # Fallback: return metadata-only from JSONL
        lines = _read_jsonl()
        for row in lines:
            if row.get("call_id") == call_id:
                item = _row_to_item(row)
                return LLMCallDetail(**item.model_dump(), prompt=None, response=None)
        raise HTTPException(status_code=404, detail=f"Call file not found: {call_id}")

    try:
        full = json.loads(call_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse call file")

    # Build metadata row from the full call file
    tokens = full.get("tokens", {}) or {}
    item = LLMCallItem(
        call_id=full.get("call_id", call_id),
        agent_id=full.get("agent_id", ""),
        req_id=req_id,
        workflow_id="",
        task_type=full.get("task_type", ""),
        provider="",
        model=full.get("model", ""),
        prompt_chars=len(full.get("prompt", "") or ""),
        status=full.get("status", ""),
        started_at=full.get("timestamp", ""),
        ended_at="",
        duration_ms=full.get("duration_ms", 0),
        prompt_tokens=tokens.get("prompt", 0),
        completion_tokens=tokens.get("completion", 0),
        total_tokens=tokens.get("total", 0),
        response_chars=len(full.get("response", "") or ""),
        response_preview=(full.get("response", "") or "")[:500],
    )

    return LLMCallDetail(
        **item.model_dump(),
        prompt=full.get("prompt", ""),
        response=full.get("response", ""),
        tokens_detail=tokens,
    )
