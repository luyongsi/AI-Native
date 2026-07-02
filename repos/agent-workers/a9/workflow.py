"""
A9 Temporal Workflow — Orchestration layer

Provides:
- Temporal workflow definition for dual-brain system
- Activity definitions for Coder and Auditor
- Error handling and retry logic
- Status tracking
"""

import logging
from datetime import timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Conditional Temporal imports
try:
    from temporalio import workflow, activity
    from temporalio.exceptions import ApplicationError
    HAS_TEMPORAL = True
except ImportError:
    HAS_TEMPORAL = False
    logger.warning("[A9Workflow] temporalio not installed, using mock mode")

    # Mock decorators
    def workflow(fn):
        return fn

    def activity(fn):
        return fn

    class ApplicationError(Exception):
        pass


@activity.defn
async def coder_activity(task_spec: dict, context: dict) -> dict:
    """Temporal Activity: Code generation by Coder"""
    from a9.coder import CoderModule

    logger.info(f"[A9Workflow] Coder activity started: {task_spec.get('title')}")

    coder = CoderModule(enable_llm=True)
    result = await coder.generate(task_spec, context)

    logger.info(f"[A9Workflow] Coder activity completed: {result.get('status')}")
    return result


@activity.defn
async def auditor_activity(diff: dict) -> dict:
    """Temporal Activity: Code review by Auditor"""
    from a9.auditor import AuditorModule

    logger.info("[A9Workflow] Auditor activity started")

    auditor = AuditorModule(enable_analysis=True)
    result = await auditor.review(diff)

    logger.info(f"[A9Workflow] Auditor activity completed: {result.get('decision')}")
    return result


@workflow.defn
async def a9_dual_brain_workflow(
    req_id: str,
    spec_package: dict,
    task: dict,
    max_iterations: int = 3,
) -> dict:
    """
    A9 Dual-Brain Workflow

    Orchestrates:
    1. Coder generates code
    2. Auditor reviews (independent)
    3. Loop with feedback (max iterations)
    4. Escalate if max iterations reached

    Args:
        req_id: Request ID
        spec_package: OpenAPI + ERD
        task: Task specification
        max_iterations: Max iterations (default 3)

    Returns:
        Final result with status, diff, audit history
    """

    logger.info(f"[A9Workflow] Starting dual-brain workflow: req={req_id}")

    # Build task spec
    task_spec = {
        "type": task.get("type", "backend"),
        "title": task.get("title", "Development Task"),
        "plan": _build_plan_from_spec(spec_package),
        "openapi_paths": len(spec_package.get("openapi", {}).get("paths", {})),
        "erd_tables": len(spec_package.get("erd", {}).get("tables", [])),
    }

    context = {"spec_package": spec_package, "task": task}
    audit_history = []
    final_diff = None

    # Temporal activity options
    activity_options = {
        "start_to_close_timeout": timedelta(minutes=5),
        "retry_policy": {"maximum_attempts": 2},
    }

    # Dual-brain loop
    for iteration in range(1, max_iterations + 1):
        logger.info(f"[A9Workflow] Iteration {iteration}/{max_iterations}")

        try:
            # Step 1: Coder generates code
            coder_result = await workflow.execute_activity(
                coder_activity,
                task_spec,
                context,
                **activity_options,
            )

            if coder_result.get("status") == "failed":
                logger.error(f"[A9Workflow] Coder failed: {coder_result.get('error')}")
                return {
                    "status": "failed",
                    "error": f"Coder failed: {coder_result.get('error')}",
                    "iterations": iteration,
                }

            final_diff = coder_result.get("diff")

            # Step 2: Prepare diff for Auditor (ONLY diff, no Coder reasoning)
            diff_for_audit = {
                "files_changed": final_diff.get("files_changed", []),
                "changes_summary": final_diff.get("changes_summary", ""),
            }

            # Step 3: Auditor reviews (independent process)
            audit_result = await workflow.execute_activity(
                auditor_activity,
                diff_for_audit,
                **activity_options,
            )

            # Record audit result
            audit_record = {
                "iteration": iteration,
                "coder_session": final_diff.get("session_id"),
                "auditor_decision": audit_result.get("decision"),
                "confidence": audit_result.get("confidence"),
                "issues": audit_result.get("issues", []),
                "suggestions": audit_result.get("suggestions", []),
            }
            audit_history.append(audit_record)

            logger.info(f"[A9Workflow] Iteration {iteration}: {audit_result.get('decision')}")

            # Step 4: Decision check
            if audit_result.get("decision") == "approved":
                logger.info(f"[A9Workflow] Approved in iteration {iteration}")
                return {
                    "status": "approved",
                    "final_diff": final_diff,
                    "iterations": iteration,
                    "audit_history": audit_history,
                    "approval_reason": f"Approved in iteration {iteration}",
                }

            # Feedback to Coder for next iteration
            if iteration < max_iterations:
                feedback = audit_result.get("suggestions", [])
                task_spec["previous_feedback"] = feedback
                task_spec["previous_issues"] = audit_result.get("issues", [])
                logger.info(f"[A9Workflow] Feedback sent to Coder: {feedback}")

        except Exception as e:
            logger.error(f"[A9Workflow] Activity failed: {e}")
            raise ApplicationError(f"Workflow failed at iteration {iteration}: {e}")

    # Max iterations reached
    logger.warning(f"[A9Workflow] Max iterations ({max_iterations}) reached, escalating")

    return {
        "status": "escalated",
        "final_diff": final_diff,
        "iterations": max_iterations,
        "audit_history": audit_history,
        "approval_reason": f"Max iterations ({max_iterations}) reached, requires human review",
    }


def _build_plan_from_spec(spec_package: dict) -> dict:
    """Build development plan from spec package"""
    openapi = spec_package.get("openapi", {})
    erd = spec_package.get("erd", {})

    paths = openapi.get("paths", {})
    tables = erd.get("tables", [])

    plan_files = []

    for endpoint in list(paths.keys())[:3]:
        resource = endpoint.split("/")[1] if "/" in endpoint else "items"
        plan_files.append(f"src/routes/{resource}.py")
        plan_files.append(f"src/models/{resource}.py")

    for table in tables[:3]:
        table_name = table.get("name", "items")
        plan_files.append(f"src/models/{table_name}.py")

    return {
        "domain": openapi.get("info", {}).get("title", "general"),
        "files_to_create": list(dict.fromkeys(plan_files[:6])),
        "files_to_modify": ["src/main.py"],
        "estimated_lines": len(paths) * 50 + len(tables) * 30,
    }


# Mock workflow for testing (when Temporal not available)
class MockA9Workflow:
    """Mock workflow for testing without Temporal"""

    @staticmethod
    async def execute(req_id: str, spec_package: dict, task: dict) -> dict:
        """Mock workflow execution"""
        from a9.a9_dev_agent import A9DevAgent

        logger.info("[A9Workflow] Running in mock mode (Temporal unavailable)")

        agent = A9DevAgent(enable_llm=False)

        # Mock NATS for standalone execution
        class MockNC:
            async def publish(self, *args, **kwargs):
                pass

        agent.nc = MockNC()

        context_package = {
            "spec_package": spec_package,
            "task": task,
        }

        return await agent.execute(req_id, context_package)
