"""MC Backend HTTP client utilities."""

import logging
import httpx

logger = logging.getLogger(__name__)

MC_BACKEND_URL = "http://localhost:8000"


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
            resp = await http.get(f"{MC_BACKEND_URL}/api/requirements?limit=1")
            return {"passed": resp.status_code < 500, "status": resp.status_code}
    except Exception as e:
        return {"passed": False, "error": str(e)}
