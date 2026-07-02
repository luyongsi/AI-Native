"""
A9 Dev Agent — Dual-Brain Architecture (Coder ↔ Auditor)

Orchestrates the two-brain system:
  1. Coder generates code → diff + self_inspection (internal reasoning)
  2. Auditor reviews diff (sees ONLY the diff, not Coder's reasoning)
  3. If rejected: feedback loops back to Coder (max 3 iterations)
  4. If approved: returns approved diff
  5. After 3 iterations: escalate to human review

Max iterations: 3
Architecture: Dual-brain with strict separation of concerns
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from base_worker import BaseAgentWorker
from a9.coder import CoderModule
from a9.auditor import AuditorModule

logger = logging.getLogger(__name__)


class A9DevAgent(BaseAgentWorker):
    """A9 Dev Agent — Coder ↔ Auditor dual-brain orchestrator"""

    agent_id = "A9"
    agent_type = "dev_agent"

    def __init__(self, nats_url: str = "nats://localhost:4222", enable_llm: bool = True):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self.coder = CoderModule(enable_llm=enable_llm)
        self.auditor = AuditorModule(enable_analysis=True)
        self.max_iterations = 3

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """
        Execute dual-brain code generation with iterative review.

        Args:
            req_id: Request ID
            context_package: {
                "spec_package": {
                    "openapi": dict,
                    "erd": dict
                },
                "task": {
                    "type": "backend|frontend|test",
                    "title": str,
                    "description": str
                }
            }

        Returns:
            {
                "status": "approved|escalated|failed",
                "final_diff": dict,
                "iterations": int,
                "approval_reason": str,
                "audit_history": [...]
            }
        """
        spec_package = context_package.get("spec_package", {})
        task = context_package.get("task", {})

        logger.info(f"[A9] Dual-brain execution started: req={req_id}, task={task.get('title')}")

        await self.report_status(req_id, "running", "Phase 1: Preparing dual-brain system")

        # Build task spec for Coder
        task_spec = {
            "type": task.get("type", "backend"),
            "title": task.get("title", "Development Task"),
            "plan": self._build_dev_plan(spec_package),
            "openapi_paths": len(spec_package.get("openapi", {}).get("paths", {})),
            "erd_tables": len(spec_package.get("erd", {}).get("tables", [])),
        }

        audit_history = []
        final_diff = None
        final_decision = None

        # Dual-brain loop: max 3 iterations
        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"[A9] Iteration {iteration}/{self.max_iterations}")

            await self.report_status(
                req_id,
                "running",
                f"Phase 2.{iteration}: Coder generating code changes",
            )

            # Step 1: Coder generates code
            coder_result = await self.coder.generate(task_spec, context_package)

            if coder_result.get("status") == "failed":
                logger.error(f"[A9] Coder failed: {coder_result.get('error')}")
                return {
                    "status": "failed",
                    "error": f"Coder generation failed: {coder_result.get('error')}",
                    "iterations": iteration,
                }

            final_diff = coder_result.get("diff")

            # CRITICAL: Pass ONLY diff to Auditor (NOT self_inspection or metadata)
            diff_for_audit = {
                "files_changed": final_diff.get("files_changed", []),
                "changes_summary": final_diff.get("changes_summary", ""),
            }

            await self.report_status(
                req_id,
                "running",
                f"Phase 2.{iteration}: Auditor reviewing changes",
            )

            # Step 2: Auditor reviews (independent process, sees only diff)
            audit_result = await self.auditor.review(diff_for_audit)

            audit_record = {
                "iteration": iteration,
                "coder_session": final_diff.get("session_id"),
                "coder_confidence": coder_result.get("self_inspection", {}).get("confidence"),
                "auditor_decision": audit_result.get("decision"),
                "auditor_confidence": audit_result.get("confidence"),
                "issues": audit_result.get("issues", []),
                "suggestions": audit_result.get("suggestions", []),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            audit_history.append(audit_record)

            logger.info(
                f"[A9] Iteration {iteration} result: {audit_result.get('decision')} "
                f"(auditor_confidence={audit_result.get('confidence')})"
            )

            # Step 3: Decision check
            if audit_result.get("decision") == "approved":
                final_decision = "approved"
                logger.info(f"[A9] Code approved in iteration {iteration}")
                await self.report_status(
                    req_id,
                    "running",
                    f"Phase 3: Code approved after {iteration} iteration(s)",
                )
                break
            else:
                # Rejected: update task spec with feedback for next iteration
                if iteration < self.max_iterations:
                    feedback = audit_result.get("suggestions", [])
                    logger.info(f"[A9] Iteration {iteration} rejected, feeding back to Coder: {feedback}")

                    # Add feedback to task context (Coder can use for refinement)
                    task_spec["previous_feedback"] = feedback
                    task_spec["previous_issues"] = audit_result.get("issues", [])

                    await self.report_status(
                        req_id,
                        "running",
                        f"Phase 2.{iteration + 1}: Feedback sent to Coder for refinement",
                    )
                else:
                    # Max iterations reached
                    final_decision = "escalated"
                    logger.warning(f"[A9] Max iterations ({self.max_iterations}) reached, escalating to human")
                    await self.report_status(
                        req_id,
                        "running",
                        "Phase 4: Max iterations reached, escalating for human review",
                    )

        # Phase 4: Generate final report
        await self.report_status(req_id, "running", "Phase 4: Generating final report")

        final_report = {
            "status": final_decision or "escalated",
            "final_diff": final_diff,
            "iterations": iteration,
            "audit_history": audit_history,
            "approval_reason": self._generate_approval_reason(final_decision, audit_history),
            "metrics": self._compute_metrics(audit_history),
        }

        # Report final artifact
        await self.report_artifact(req_id, "code_diff", final_report)

        logger.info(
            f"[A9] Dual-brain execution completed: "
            f"status={final_decision}, iterations={iteration}"
        )

        return final_report

    def _build_dev_plan(self, spec_package: dict) -> dict:
        """Build development plan from spec package"""
        openapi = spec_package.get("openapi", {})
        erd = spec_package.get("erd", {})

        paths = openapi.get("paths", {})
        tables = erd.get("tables", [])

        plan_files = []

        # Generate routes from API paths
        for endpoint in list(paths.keys())[:3]:
            resource = endpoint.split("/")[1] if "/" in endpoint else "items"
            plan_files.append(f"src/routes/{resource}.py")
            plan_files.append(f"src/models/{resource}.py")
            plan_files.append(f"tests/test_{resource}.py")

        # Generate models from ERD tables
        for table in tables[:3]:
            table_name = table.get("name", "items")
            plan_files.append(f"src/models/{table_name}.py")

        return {
            "domain": openapi.get("info", {}).get("title", "general"),
            "files_to_create": list(dict.fromkeys(plan_files[:6])),
            "files_to_modify": ["src/main.py", "src/db.py"],
            "estimated_lines": sum(
                len(paths.get(p, {}).get("parameters", [])) * 10 + 50 for p in paths
            ),
        }

    def _generate_approval_reason(self, decision: Optional[str], audit_history: list) -> str:
        """Generate human-readable approval reason"""
        if not audit_history:
            return "No audit history available"

        last_audit = audit_history[-1]

        if decision == "approved":
            return (
                f"Code approved in iteration {last_audit['iteration']} "
                f"with auditor confidence {last_audit['auditor_confidence']:.1%}"
            )
        elif decision == "escalated":
            return (
                f"Max iterations ({self.max_iterations}) reached. "
                f"Last auditor feedback: {'; '.join(last_audit.get('suggestions', [])[:2])}"
            )
        else:
            return "Review process could not reach approval"

    def _compute_metrics(self, audit_history: list) -> dict:
        """Compute metrics from audit history"""
        if not audit_history:
            return {}

        approvals = sum(1 for a in audit_history if a["auditor_decision"] == "approved")
        avg_auditor_confidence = (
            sum(a.get("auditor_confidence", 0) for a in audit_history) / len(audit_history)
            if audit_history
            else 0
        )
        avg_coder_confidence = (
            sum(a.get("coder_confidence", 0) for a in audit_history) / len(audit_history)
            if audit_history
            else 0
        )

        total_issues = sum(len(a.get("issues", [])) for a in audit_history)

        return {
            "total_iterations": len(audit_history),
            "approvals": approvals,
            "avg_auditor_confidence": avg_auditor_confidence,
            "avg_coder_confidence": avg_coder_confidence,
            "total_issues_found": total_issues,
        }
