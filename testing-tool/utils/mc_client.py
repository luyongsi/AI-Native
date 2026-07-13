"""MC Backend HTTP client utilities."""

import json
import logging
import os
import httpx

logger = logging.getLogger(__name__)

MC_BACKEND_URL = "http://localhost:8000"
AUTH_TOKEN = os.environ.get("MC_AUTH_TOKEN", "Bearer dev-internal-key")


async def create_requirement(title: str, description: str = "",
                              priority: str = "medium") -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{MC_BACKEND_URL}/api/requirements",
                json={
                    "title": title,
                    "description": description,
                    "priority": priority,
                    "source_type": "manual",
                },
                headers={"Authorization": AUTH_TOKEN},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Failed to create requirement: {e}")
        return None


async def trigger_workflow(req_id: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{MC_BACKEND_URL}/api/requirements/{req_id}/trigger",
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("workflow_id")
    except Exception as e:
        logger.error(f"Failed to trigger workflow: {e}")
        return None


async def approve_gate(gate_id: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{MC_BACKEND_URL}/api/approvals/{gate_id}/approve",
            )
            return resp.status_code < 400
    except Exception:
        return False


async def check_mc_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                f"{MC_BACKEND_URL}/api/requirements?limit=1",
                headers={"Authorization": AUTH_TOKEN},
            )
            return {"passed": resp.status_code < 500, "status": resp.status_code}
    except Exception as e:
        return {"passed": False, "error": str(e)}


async def dialogue_chat(req_id: str, message: str, session_id: str | None = None):
    """POST /api/dialogue/chat — returns SSE streaming response.

    MC Backend sends SSE with separate event: and data: lines.
    The event type is in the event: line, data content in data: line.
    We merge them together so downstream only needs to parse data: lines.
    """
    try:
        async with httpx.AsyncClient(timeout=300) as http:
            async with http.stream(
                "POST",
                f"{MC_BACKEND_URL}/api/dialogue/chat",
                json={
                    "req_id": req_id,
                    "message": message,
                    "session_id": session_id,
                },
                headers={"Authorization": AUTH_TOKEN},
            ) as resp:
                resp.raise_for_status()
                current_type = None
                async for line in resp.aiter_lines():
                    if line.startswith("event: "):
                        current_type = line[7:].strip()
                    elif line.startswith("data: "):
                        data_str = line[6:].strip()
                        if current_type and data_str:
                            try:
                                evt = json.loads(data_str)
                                evt["type"] = current_type
                                yield f"data: {json.dumps(evt, ensure_ascii=False)}"
                            except json.JSONDecodeError:
                                yield f"data: {{\"type\":\"{current_type}\",\"raw\":{json.dumps(data_str)}}}"
                        elif data_str:
                            yield f"data: {data_str}"
                        current_type = None
    except Exception as e:
        logger.error(f"dialogue_chat failed: {e}")
        yield f"data: {{\"type\":\"error\",\"content\":\"{str(e)}\"}}"


async def dialogue_confirm(session_id: str) -> dict | None:
    """POST /api/dialogue/confirm — confirm analysis completion."""
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{MC_BACKEND_URL}/api/dialogue/confirm",
                json={"session_id": session_id},
                headers={"Authorization": AUTH_TOKEN},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"dialogue_confirm failed: {e}")
        return None


async def dialogue_history(session_id: str) -> dict | None:
    """GET /api/dialogue/history/{session_id} — get conversation history."""
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{MC_BACKEND_URL}/api/dialogue/history/{session_id}",
                headers={"Authorization": AUTH_TOKEN},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"dialogue_history failed: {e}")
        return None


async def dialogue_current(req_id: str) -> dict | None:
    """GET /api/dialogue/current/{req_id} — get current session info."""
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{MC_BACKEND_URL}/api/dialogue/current/{req_id}",
                headers={"Authorization": AUTH_TOKEN},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"dialogue_current failed: {e}")
        return None


async def get_requirements(limit: int = 20, status: str | None = None) -> dict:
    """GET /api/requirements — list requirements."""
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            params = {"limit": limit}
            if status:
                params["status"] = status
            resp = await http.get(
                f"{MC_BACKEND_URL}/api/requirements",
                params=params,
                headers={"Authorization": AUTH_TOKEN},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"get_requirements failed: {e}")
        return {"items": []}


async def get_requirement_detail(req_id: str) -> dict | None:
    """GET /api/requirements/{req_id} — get requirement detail."""
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{MC_BACKEND_URL}/api/requirements/{req_id}",
                headers={"Authorization": AUTH_TOKEN},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"get_requirement_detail failed: {e}")
        return None
