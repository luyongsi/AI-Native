"""DAG parallel dispatch — wait for all tasks in a dependency graph.

dispatch_parallel submits a set of tasks (dag_tasks) as child-workflow
or activity stubs and waits for every task to reach a terminal state.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.dispatch_agent import dispatch_agent

logger = logging.getLogger(__name__)

_DEFAULT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn(name="dispatch_parallel")
class DispatchParallelWorkflow:
    """Orchestrator sub-workflow that fans out to N tasks in parallel."""

    @workflow.run
    async def run(self, req_id: str, dag_tasks: list[dict]) -> dict:
        """Execute all *dag_tasks* in parallel and return aggregated results.

        Each task dict must have keys: `task_id`, `state` (optional).

        Returns:
            dict with keys: ok, completed, failed, results
        """
        workflow.logger.info(
            "dispatch_parallel req=%s tasks=%d", req_id, len(dag_tasks)
        )

        if not dag_tasks:
            workflow.logger.warning("dispatch_parallel: empty task list")
            return {"ok": True, "completed": 0, "failed": 0, "results": []}

        # Fan-out: launch each task as an activity
        coros = []
        for task in dag_tasks:
            tid = task.get("task_id", "unknown")
            st = task.get("state", "developing")
            msg = task.get("message", "")
            coros.append(
                workflow.execute_activity(
                    dispatch_agent,
                    args=[f"{req_id}/{tid}", st, msg],
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=_DEFAULT_RETRY,
                )
            )

        # Gather all results
        results = []
        completed = 0
        failed = 0
        for i, coro in enumerate(coros):
            try:
                r = await coro
                completed += 1
                results.append({"task_index": i, "ok": True, "result": r})
            except Exception as exc:
                failed += 1
                results.append({"task_index": i, "ok": False, "error": str(exc)})
                workflow.logger.error(
                    "dispatch_parallel task %d failed: %s", i, exc
                )

        workflow.logger.info(
            "dispatch_parallel done req=%s done=%d fail=%d",
            req_id, completed, failed,
        )
        return {
            "ok": failed == 0,
            "completed": completed,
            "failed": failed,
            "results": results,
        }


# Standalone helper to call the workflow programmatically (for worker registration).
dispatch_parallel = DispatchParallelWorkflow
