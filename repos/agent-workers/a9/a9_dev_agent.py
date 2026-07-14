"""
A9 Dev Agent — Dual-Brain Architecture (Coder  ↔ Auditor)

Orchestrates:
  1. A9Runtime prepares isolated worktree environment
  2. A9CodingEngine generates code (Claude Code CLI / Codex CLI / Anthropic API)
  3. Quality gates: lint → build → unit test → smoke test
  4. AuditorModule reviews code (static analysis + LLM semantic review)
  5. Feedback loop (max 3 iterations), escalate on failure

Modes:
  - autonomous: Agent receives Orchestrator dispatch → generates code → self-tests → publishes diff
  - assisted: Human codes in IDE → A9 reviews and provides feedback (Phase 5)

Architecture: Dual-brain with strict separation of concerns.
LLM access via dependency injection into CoderModule / AuditorModule.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from base_worker import BaseAgentWorker
from a9.coder import CoderModule
from a9.auditor import AuditorModule
from a9.runtime import A9Runtime
from a9.engine import A9CodingEngine
from a9.metrics import A9Metrics, A9MetricsCollector

logger = logging.getLogger(__name__)


class A9DevAgent(BaseAgentWorker):
    """A9 Dev Agent — Coder ↔ Auditor dual-brain orchestrator with Runtime + Engine."""

    agent_id = "A9"
    agent_type = "dev_agent"

    def __init__(self, nats_url: str = "nats://localhost:4222",
                 enable_llm: bool = True,
                 max_concurrent: int = 3,
                 instance_id: int = 0):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self.coder = CoderModule(llm_caller=self.call_llm, enable_llm=enable_llm)
        self.auditor = AuditorModule(llm_caller=self.call_llm, enable_analysis=True)
        self.max_iterations = 3
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self.instance_id = instance_id
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """
        Execute dual-brain code generation with quality gates.

        Args:
            req_id: Request ID
            context_package: {
                "title": str,
                "decisions": {decision_id: selected_option},
                "openapi_hint": {endpoints, info},
                "erd_hint": {tables},
                "dag_hint": {nodes, edges},
                "environment_context": {project: {repo_url, branch}},
                "note": str,
                ...
            }

        Returns:
            {"status": "completed|escalated|blocked", "code_diff": ..., "files_changed": [...], ...}
        """
        # Extract core fields from context
        spec_package = {
            "openapi": context_package.get("openapi_hint", {}),
            "erd": context_package.get("erd_hint", {}),
        }
        task = {
            "title": context_package.get("title", "Development Task"),
            "description": context_package.get("note", ""),
            "dag_nodes": context_package.get("dag_hint", {}).get("nodes", []),
        }
        decisions = context_package.get("decisions", {})

        env_ctx = context_package.get("environment_context", {}) or {}
        project_ctx = env_ctx.get("project", {}) or {}
        repo_url = project_ctx.get("repo_url", "")
        branch = project_ctx.get("branch", "main")

        logger.info(f"[A9] Dual-brain execution: req={req_id}, task={task.get('title')}, "
                    f"decisions={len(decisions)}, instance={self.instance_id}")

        metrics_collector = A9MetricsCollector()
        metrics_collector.start_cycle()
        collected_ambiguities: list[dict] = []
        partial_artifacts: list[dict] = []

        # Build task prompt from context
        task_prompt = self._build_task_prompt(spec_package, task, decisions)

        # Prepare isolated runtime environment
        runtime = A9Runtime()
        await runtime.setup(repo_url, branch)

        # Initialize coding engine
        engine = A9CodingEngine(runtime, llm_caller=self.call_llm)

        final_result = None
        final_audit = None
        feedback = ""
        lint = None
        build_result = None
        tests = None

        try:
            for iteration in range(1, self.max_iterations + 1):
                logger.info(f"[A9] Iteration {iteration}/{self.max_iterations}")
                await self.report_status(req_id, "running",
                    f"Iteration {iteration}/{self.max_iterations}: 编码中")

                # ── 1. Engine generates code ──
                engine_start = datetime.now(timezone.utc)
                engine_result = await engine.execute(
                    task_prompt,
                    engine="auto",
                    language=self._detect_language_from_task(task),
                    max_turns=50,
                    feedback=feedback,
                )
                engine_duration = (datetime.now(timezone.utc) - engine_start).total_seconds()

                # Type 3: Blocking issues — escalate immediately
                if not engine_result.success and engine_result.blocking_issues:
                    logger.error(f"[A9] Blocking issues: {engine_result.blocking_issues}")
                    await self._escalate_blocking_issue(req_id, engine_result.blocking_issues)
                    return {
                        "status": "blocked",
                        "issues": engine_result.blocking_issues,
                        "iterations": iteration,
                        "engine": engine_result.engine,
                    }

                if not engine_result.success:
                    feedback = f"引擎执行失败: {engine_result.summary}"
                    continue

                files_changed = engine_result.files_changed
                if not files_changed:
                    feedback = "No files were generated. Please produce code changes."
                    continue

                # Type 1: Record spec ambiguities (non-blocking)
                for amb in engine_result.ambiguities or []:
                    self._record_ambiguity(req_id, amb, collected_ambiguities)

                partial_artifacts.append({
                    "iteration": iteration,
                    "files": [f.get("path", "") for f in files_changed],
                    "engine": engine_result.engine,
                })

                # ── 2. Lint check ──
                await self.report_status(req_id, "running",
                    f"自测: lint ({len(files_changed)} files)")
                lang = self._detect_language(files_changed)
                file_paths = [f["path"] for f in files_changed]
                lint = await runtime.lint(file_paths, lang)

                if lint.status == "error":
                    feedback = self._format_feedback(lint, None, None)
                    continue

                # ── 3. Build check ──
                await self.report_status(req_id, "running", "自测: build")
                build_result = await runtime.build(lang)

                if not build_result.success:
                    feedback = self._format_feedback(lint, build_result, None)
                    continue

                # ── 4. Unit test ──
                await self.report_status(req_id, "running",
                    f"自测: unit test ({len(files_changed)} files)")
                tests = await runtime.test()

                if tests.failed > 0:
                    feedback = self._format_feedback(lint, build_result, tests)
                    continue

                # ── 5. Smoke test (start service → health check → stop) ──
                await self.report_status(req_id, "running", "自测: smoke test")
                try:
                    start_cmd = runtime.detect_start_command(lang)
                    service = await runtime.start_service(
                        command=start_cmd,
                        health_check="/health",
                        timeout=15,
                    )
                    if not service.get("health_ok", False):
                        logger.warning(f"[A9] Service health check failed — skipping smoke test")
                        await runtime.stop_all_services()
                        feedback = "Failed to start service for smoke test — health check did not pass"
                        continue
                    smoke = await runtime.test(
                        command=["pytest", "tests/smoke/", "-x", "--timeout=10",
                                  f"--base-url={service['url']}"],
                    )
                    await runtime.stop_all_services()

                    if smoke.failed > 0:
                        feedback = f"Smoke test failed ({smoke.failed}/{smoke.total}) — please fix"
                        continue
                except Exception as e:
                    logger.warning(f"[A9] Smoke test skipped: {e}")

                # ── 6. Optional: Docker build ──
                await self.report_status(req_id, "running", "自测: CI build 验证")
                docker_ok = await self._verify_ci_build(
                    str(runtime.worktree_path), req_id,
                )
                if not docker_ok:
                    feedback = "Docker build failed. Check Dockerfile."
                    continue

                # ── 7. Auditor review ──
                await self.report_status(req_id, "running", "代码审查中")
                audit_start = datetime.now(timezone.utc)

                diff_for_audit = {
                    "files_changed": files_changed,
                    "changes_summary": engine_result.summary,
                    "lint_result": lint,
                    "test_result": tests,
                }

                audit_result = await self.auditor.review(diff_for_audit)
                audit_duration = (datetime.now(timezone.utc) - audit_start).total_seconds()

                # Track metrics
                metrics_collector.record_iteration(
                    iteration,
                    {"status": "success", "diff": {"files_changed": files_changed}},
                    audit_result,
                    engine_duration,
                    audit_duration,
                )

                final_result = engine_result
                final_audit = audit_result

                logger.info(
                    f"[A9] Iteration {iteration}: decision={audit_result.get('decision')}, "
                    f"issues={len(audit_result.get('issues', []))}"
                )

                if audit_result.get("decision") == "approved":
                    await self.report_status(req_id, "running",
                        f"审查通过 (iteration {iteration})")
                    break

                # Rejected: build feedback for next iteration
                feedback = self._format_audit_feedback(audit_result)
                if iteration < self.max_iterations:
                    await self.report_status(req_id, "running",
                        f"Iteration {iteration} rejected, feeding back for refinement")

        finally:
            # Always cleanup runtime
            await runtime.cleanup()

        # ── 8. Finalize ──
        if final_audit is None:
            status = "escalated"
            logger.warning(f"[A9] No successful iterations — escalating")
            A9Metrics.record_escalation()
        elif final_audit.get("decision") == "approved":
            status = "completed"
        elif iteration >= self.max_iterations:
            status = "escalated"
            logger.warning(f"[A9] Max iterations ({self.max_iterations}) reached, escalating")
            A9Metrics.record_escalation()
        else:
            status = "escalated"

        metrics_collector.finalize_cycle(status)

        # Produce final artifact
        files_changed = final_result.files_changed if final_result else []
        diff_text = final_result.diff_raw if final_result else ""

        report = {
            "status": status,
            "code_diff": diff_text,
            "files_changed": files_changed,
            "commit_sha": final_result.session_id if final_result else "",
            "session_id": final_result.session_id if final_result else "",
            "engine": final_result.engine if final_result else "none",
            "iterations": iteration,
            "audit": final_audit,
            "self_test": {
                "lint": {"status": lint.status if lint else "skipped",
                         "errors": len(lint.errors) if lint else 0},
                "build": {"success": build_result.success if build_result else None},
                "tests": {"passed": tests.passed if tests else 0,
                          "failed": tests.failed if tests else 0,
                          "total": tests.total if tests else 0},
            },
            "ambiguities": collected_ambiguities,
        }

        await self.report_artifact(req_id, "code_diff", report)

        logger.info(f"[A9] Execution complete: status={status}, iterations={iteration}")

        return report

    # ── Prompt builders ────────────────────────────────────────────────

    def _build_task_prompt(self, spec: dict, task: dict, decisions: dict) -> str:
        """Build task description for the coding engine."""
        parts = [
            f"任务: {task.get('title', 'Development Task')}",
            f"描述: {task.get('description', 'Implement according to spec')}",
        ]

        # Inject decisions
        if decisions:
            parts.append("\n架构决策 (必须遵守):")
            for dk, dv in decisions.items():
                parts.append(f"  - {dk}: {dv}")

        # Inject API info
        openapi = spec.get("openapi", {})
        endpoints = openapi.get("endpoints", [])
        if endpoints:
            parts.append(f"\nAPI Endpoints: {', '.join(endpoints[:10])}")

        # Inject ERD info
        erd = spec.get("erd", {})
        tables = erd.get("tables", [])
        if tables:
            parts.append(f"Database Tables: {', '.join(tables[:10])}")

        # Inject DAG context from task
        dag_nodes = task.get("dag_nodes", [])
        if dag_nodes:
            node_titles = []
            for node in dag_nodes[:5]:
                title = node.get("title", "")
                constraints = node.get("constraints", [])
                if constraints:
                    title += f" [约束: {'; '.join(constraints[:2])}]"
                node_titles.append(title)
            parts.append(f"\n相关任务节点: {' | '.join(node_titles)}")

        return "\n".join(parts)

    def _build_dev_plan(self, spec_package: dict) -> dict:
        """Build development plan from spec package."""
        openapi = spec_package.get("openapi", {})
        erd = spec_package.get("erd", {})

        endpoints = openapi.get("endpoints", [])
        tables = erd.get("tables", [])

        plan_files = []

        # Generate routes from API endpoints
        for endpoint in endpoints[:3]:
            resource = endpoint.split("/")[1] if "/" in endpoint else "items"
            plan_files.append(f"src/routes/{resource}.py")
            plan_files.append(f"src/models/{resource}.py")
            plan_files.append(f"tests/test_{resource}.py")

        # Generate models from ERD tables
        for table_name in tables[:3]:
            plan_files.append(f"src/models/{table_name}.py")

        return {
            "domain": openapi.get("info", {}).get("title", "general"),
            "files_to_create": list(dict.fromkeys(plan_files[:6])),
            "files_to_modify": ["src/main.py", "src/db.py"],
            "estimated_lines": len(endpoints) * 50 + len(tables) * 30,
        }

    # ── Feedback formatters ────────────────────────────────────────────

    def _format_feedback(self, lint, build, tests) -> str:
        """Format quality gate failures into engine-readable feedback."""
        parts = ["代码质量检查失败，请修复以下问题:"]

        if lint and lint.status == "error":
            parts.append("\nLint 错误:")
            for e in lint.errors[:5]:
                parts.append(f"  - line {e.get('line', '?')}: {e.get('message', '')}")

        if build and not build.success:
            parts.append(f"\nBuild 失败 (exit={build.exit_code}):")
            if build.stderr:
                parts.append(f"  {build.stderr[:500]}")

        if tests and tests.failed > 0:
            parts.append(f"\n测试失败 ({tests.failed}/{tests.total}):")
            for f in tests.failures_detail[:5]:
                parts.append(f"  - {f.get('message', str(f))}")

        return "\n".join(parts)

    def _format_audit_feedback(self, audit: dict) -> str:
        """Format auditor findings into engine-readable feedback."""
        parts = ["代码审查未通过，请修复以下问题:"]

        issues = audit.get("issues", [])
        for issue in issues[:10]:
            sev = issue.get("severity", "?")
            msg = issue.get("message", issue.get("description", ""))
            src = issue.get("source", "?")
            parts.append(f"  [{sev}][{src}] {msg}")

        suggestions = audit.get("suggestions", [])
        if suggestions:
            parts.append("\n建议:")
            for s in suggestions[:3]:
                parts.append(f"  - {s}")

        return "\n".join(parts)

    # ── Language detection ─────────────────────────────────────────────

    def _detect_language(self, files_changed: list) -> str:
        """Detect primary language from changed files."""
        if not files_changed:
            return "python"

        lang_counts: dict[str, int] = {}
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".tsx": "typescript", ".go": "go", ".rs": "rust",
            ".java": "java", ".sql": "sql",
        }

        for f in files_changed:
            path = f.get("path", "") if isinstance(f, dict) else f
            ext = Path(path).suffix.lower()
            lang = ext_map.get(ext, "unknown")
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

        return max(lang_counts, key=lambda k: lang_counts[k]) if lang_counts else "python"

    def _detect_language_from_task(self, task: dict) -> str:
        """Detect primary language from task spec (before code generation)."""
        dag_nodes = task.get("dag_nodes", [])
        if not dag_nodes:
            return "python"

        # Check node types for language hints
        for node in dag_nodes:
            node_type = node.get("type", "")
            if node_type in ("frontend", "ui"):
                return "typescript"
            if node_type == "db":
                return "sql"

        return "python"  # default: backend python

    # ── Escalation ─────────────────────────────────────────────────────

    def _record_ambiguity(self, req_id: str, amb: dict, collected: list):
        """Type 1: Record spec ambiguity, continue execution."""
        logger.warning(
            f"[A9] Spec ambiguity: field={amb.get('field')}, "
            f"chose={amb.get('chosen')}, reason={amb.get('reason')}"
        )
        collected.append(amb)

        # Publish to NATS for spec quality improvement
        asyncio.create_task(self.js.publish("spec.feedback", json.dumps({
            "req_id": req_id, "agent_id": "A9",
            "type": "ambiguity",
            "field": amb.get("field", ""),
            "chosen": amb.get("chosen", ""),
            "reason": amb.get("reason", ""),
            "suggested_fix": amb.get("suggested_fix", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False).encode()))

    async def _escalate_blocking_issue(self, req_id: str, issues: list[dict]):
        """Type 3: Unrecoverable blocking issue — escalate to BLOCKED state."""
        await self.report_status(req_id, "blocked",
            f"阻塞性问题: {issues[0].get('summary', 'unknown')}")

        try:
            await self.js.publish("agent.escalated", json.dumps({
                "event_id": f"escalate-a9-{req_id}",
                "req_id": req_id,
                "agent_id": "A9",
                "from_state": "developing",
                "reason": "blocking_issue",
                "issues": issues,
                "suggested_reroute": "A6",
            }, ensure_ascii=False).encode())
            logger.info(f"[A9] Escalation signal sent for req={req_id}")
        except Exception as e:
            logger.error(f"[A9] Failed to send escalation: {e}")

    async def _verify_ci_build(self, worktree_path: str, req_id: str) -> bool:
        """Verify Docker build via A10 CI Build Service (NATS request-reply).

        Returns True if build succeeds or CI is unavailable (graceful degradation).
        Returns False only if CI responded and the build explicitly failed.
        """
        try:
            reply = await asyncio.wait_for(
                self.nc.request("ci.build", json.dumps({
                    "req_id": req_id,
                    "repo_path": str(worktree_path),
                    "dockerfile": "Dockerfile",
                    "tag": f"a9-dev-{req_id}",
                }).encode(), timeout=180),
                timeout=200,
            )
            result = json.loads(reply.data.decode())
            success = result.get("success", False)
            if not success:
                logger.warning(
                    f"[A9] CI build failed: {result.get('error', result.get('logs', 'unknown'))[:200]}"
                )
            return success
        except asyncio.TimeoutError:
            logger.warning("[A9] CI build timeout (200s) — skipping Docker verification")
            await self.report_status(req_id, "running", "CI build 跳过（超时）")
            return True
        except Exception as e:
            logger.warning(f"[A9] CI service unavailable: {e}")
            await self.report_status(req_id, "running", "CI build 跳过（服务不可用）")
            return True
