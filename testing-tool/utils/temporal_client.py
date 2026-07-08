"""Temporal client utilities for the testing tool."""

import logging
from temporalio.client import Client

logger = logging.getLogger(__name__)


async def connect_temporal(host: str = "localhost:7233",
                           namespace: str = "ai-native") -> Client | None:
    try:
        client = await Client.connect(host, namespace=namespace)
        logger.info(f"Connected to Temporal at {host} (ns={namespace})")
        return client
    except Exception as e:
        logger.warning(f"Temporal connection failed: {e}")
        return None


async def list_workflows(client: Client) -> list[dict]:
    workflows = []
    try:
        async for wf in client.list_workflows():
            workflows.append({
                "id": wf.id,
                "type": wf.type,
                "status": str(wf.status),
            })
    except Exception:
        pass
    return workflows


async def start_workflow(client: Client, workflow_name: str,
                         args: list, task_queue: str = "orchestrator-task-queue",
                         workflow_id: str | None = None) -> str:
    handle = await client.start_workflow(
        workflow_name,
        args=args,
        id=workflow_id or "",
        task_queue=task_queue,
    )
    return handle.id


async def query_workflow_progress(client: Client, workflow_id: str) -> dict | None:
    try:
        handle = client.get_workflow_handle(workflow_id)
        return await handle.query("get_progress")
    except Exception:
        return None


async def terminate_workflow(client: Client, workflow_id: str, reason: str = "test cleanup") -> dict:
    try:
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        if desc.status in (1, 2):  # RUNNING / CONTINUED_AS_NEW
            await handle.terminate(reason=reason)
            return {"terminated": True, "workflow_id": workflow_id}
        return {"terminated": False, "workflow_id": workflow_id,
                "message": f"status={desc.status}, not running"}
    except Exception as e:
        return {"terminated": False, "workflow_id": workflow_id, "error": str(e)}
