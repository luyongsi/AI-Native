"""
Workflow Trigger API — starts the Temporal RequirementWorkflow when a user submits a requirement.
POST /api/requirements/{req_id}/trigger
"""
import logging
import os
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/requirements", tags=["workflow"])

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "ai-native")

_temp_client = None


async def get_temporal_client():
    global _temp_client
    if _temp_client is None:
        try:
            from temporalio.client import Client
            _temp_client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
            logger.info(f"Connected to Temporal at {TEMPORAL_HOST} (ns={TEMPORAL_NAMESPACE})")
        except Exception as e:
            logger.warning(f"Temporal not available: {e}")
            return None
    return _temp_client


class WorkflowStatus(BaseModel):
    status: str
    req_id: str
    workflow_id: str | None = None
    current_state: str | None = None
    started_at: str | None = None


@router.post("/{req_id}/trigger")
async def trigger_workflow(req_id: str) -> WorkflowStatus:
    """Start the AI Native RequirementWorkflow for this requirement."""
    # Verify requirement exists
    conn = None
    try:
        from main import DB_POOL
        conn = await DB_POOL.acquire()
        row = await conn.fetchrow(
            "SELECT id, title, status FROM requirements WHERE id = $1::uuid", req_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Requirement not found")
        title = row["title"]
    finally:
        if conn:
            await conn.close()

    client = await get_temporal_client()
    if client is None:
        # Run locally without Temporal — update requirement status directly
        update_conn = None
        try:
            from main import DB_POOL
            update_conn = await DB_POOL.acquire()
            await update_conn.execute(
                "UPDATE requirements SET status = 'analyzing', updated_at = $1 WHERE id = $2::uuid",
                datetime.now(timezone.utc), req_id,
            )
        finally:
            if update_conn:
                await update_conn.close()

        return WorkflowStatus(
            status="started_local",
            req_id=req_id,
            current_state="analyzing",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    # Start Temporal workflow
    try:
        import time
        workflow_id = f"req-{req_id[:8]}-{int(time.time())}"
        handle = await client.start_workflow(
            "RequirementWorkflow",
            args=[req_id, json.dumps({"title": title, "status": "draft"})],
            id=workflow_id,
            task_queue="orchestrator-task-queue",
        )
        logger.info(f"Workflow started: {workflow_id}")

        return WorkflowStatus(
            status="started",
            req_id=req_id,
            workflow_id=workflow_id,
            current_state="draft",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        err_msg = str(e)
        # If workflow already exists, return its current status instead of error
        if "already started" in err_msg.lower() or "already exist" in err_msg.lower():
            try:
                # Try to get status of the existing workflow
                existing_id = await get_workflow_status(req_id)
                return WorkflowStatus(
                    status="already_running",
                    req_id=req_id,
                    workflow_id=existing_id.get("workflow_id", ""),
                    current_state=existing_id.get("status", "running"),
                    started_at=existing_id.get("start_time", ""),
                )
            except Exception:
                pass
        logger.error(f"Failed to start workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {e}")


@router.get("/{req_id}/workflow-status")
async def get_workflow_status(req_id: str):
    """Get the current workflow status for a requirement."""
    client = await get_temporal_client()
    if client is None:
        conn = None
        try:
            from main import DB_POOL
            conn = await DB_POOL.acquire()
            row = await conn.fetchrow(
                "SELECT status, updated_at FROM requirements WHERE id = $1::uuid", req_id
            )
            if row:
                return {"req_id": req_id, "status": row["status"], "source": "database"}
            return {"req_id": req_id, "status": "unknown"}
        finally:
            if conn:
                await conn.close()

    try:
        workflow_id = f"req-{req_id[:8]}"
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        return {
            "req_id": req_id,
            "workflow_id": workflow_id,
            "status": desc.status.name if desc.status else "unknown",
            "start_time": desc.start_time.isoformat() if desc.start_time else None,
            "source": "temporal",
        }
    except Exception as e:
        return {"req_id": req_id, "status": "not_found", "error": str(e)}
