"""Temporal Workflow: RequirementWorkflow.

Implements the full state machine per design docs v3.5.

State progression (Phase 1):
    DRAFT -> ANALYZING (A1 via HTTP+SSE, waits for Signal)
    -> KNOWLEDGE_ANALYSIS (A2 via NATS dispatch)
    -> Gate 0 -> DESIGNING (A3+A4) -> Gate 1 -> REVIEWING (A5) ->
    DECOMPOSING (A6) -> Gate 2 -> DEVELOPING (A9) -> TESTING (A11) ->
    REVIEWING_CODE (A12) -> Gate 3 -> RELEASING (A13) -> DONE

Gate0 reject -> back to ANALYZING (A1 revision, cycle++), then re-run A2->Gate0.

Rework:
    REVIEWING fail -> back to DESIGNING (max 2 rounds), then escalate Gate.

A1 (ANALYZING): runs via HTTP+SSE, workflow waits for agent_completed Signal
    from NATS-Temporal Bridge (triggered by agent.result.A1).
A2-A13: dispatched via NATS (dispatch_agent Activity).
Gate approval via approve_gate/reject_gate Signal from MC Backend.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from state_machine.states import RequirementState as RS
    from state_machine.transitions import TRANSITION_TABLE
    from activities.dispatch_agent import dispatch_agent
    from activities.context_build import build_context
    from activities.notify_mc import notify_mc
    from activities.gate_await import create_gate_approval
    from activities.store_agent_result import store_agent_result

logger = logging.getLogger(__name__)

_DEFAULT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
)

# Agents that persist their own results — skip store_agent_result
_AGENTS_THAT_PERSIST = {"A4", "A6", "A7", "A8"}

# Agent timeout per state
_AGENT_TIMEOUTS: dict[RS, timedelta] = {
    RS.ANALYZING: timedelta(minutes=30),           # A1 via HTTP+SSE — humans are slow
    RS.KNOWLEDGE_ANALYSIS: timedelta(minutes=10),  # A2 knowledge analysis
    RS.DESIGNING: timedelta(minutes=15),
    RS.REVIEWING: timedelta(minutes=10),
    RS.DECOMPOSING: timedelta(minutes=15),          # Phase3: A6+A7 parallel, then A8
    RS.DEVELOPING: timedelta(hours=4),
    RS.TESTING: timedelta(hours=2),
    RS.REVIEWING_CODE: timedelta(minutes=15),
    RS.RELEASING: timedelta(minutes=30),
}

# Gate SLA — timeout triggers notification, NOT auto-approval
_GATE_SLA: dict[int, timedelta] = {
    0: timedelta(hours=1),
    1: timedelta(hours=4),
    2: timedelta(hours=4),
    3: timedelta(hours=2),
}

# Gate grace period — extra wait window after SLA expiry before escalation
# Gate 0/3: no grace period (notify then wait indefinitely)
# Gate 1/2: 1-hour grace period
_GATE_GRACE_PERIOD: dict[int, timedelta | None] = {
    0: None,
    1: timedelta(hours=1),
    2: timedelta(hours=1),
    3: None,
}

# States that require agent execution (ANALYZING=A1 is special — HTTP+SSE, not NATS dispatch)
# ANALYZING is NOT in _AGENT_STATES — workflow waits for agent_completed Signal instead
_AGENT_STATES: set[RS] = {
    RS.KNOWLEDGE_ANALYSIS,  # A2 — NATS dispatch
    RS.SPEC_WRITING, RS.REVIEWING, RS.DECOMPOSING,
    RS.DEVELOPING, RS.TESTING, RS.REVIEWING_CODE, RS.RELEASING,
}

# States that require gate approval
_GATED_STATES: dict[RS, int] = {
    RS.KNOWLEDGE_ANALYSIS: 0,  # Gate 0 after A2
    RS.REVIEWING: 1,            # Gate 1 after A5 design review
    RS.DECOMPOSING: 2,
    RS.REVIEWING_CODE: 3,
}

# Rework config
_MAX_REWORK = 2


@workflow.defn(name="RequirementWorkflow")
class RequirementWorkflow:
    """Top-level orchestrator workflow for a single requirement."""

    def __init__(self) -> None:
        self._state: RS = RS.DRAFT
        self._log: list[dict] = []
        self._rework_count: int = 0

        # Signal-driven state
        self._agent_result: dict | None = None
        self._agent_id_expected: str = ""
        self._gate_approved: str | None = None
        self._agent_progress: dict[str, dict] = {}
        self._agent_failures: dict[str, int] = {}

        # A3/A4 parallel tracking
        self._agent_result_a3: dict | None = None
        self._agent_result_a4: dict | None = None
        self._last_a5_result: dict | None = None

        # Phase3 (DECOMPOSING) GATHER tracking — A6+A7 parallel, then A8
        self._a6_done: bool = False
        self._a7_done: bool = False
        self._a8_done: bool = False
        self._a6_result: dict | None = None
        self._a7_result: dict | None = None
        self._a8_result: dict | None = None
        self._tech_prep_revision_count: int = 0

        # DEVELOPING ↔ TESTING inner loop (T8)
        self._inner_loop_count: int = 0
        self._last_test_result: dict | None = None

    @workflow.run
    async def run(self, req_id: str, initial_msg: str) -> str:
        workflow.logger.info(
            "RequirementWorkflow started req=%s state=%s", req_id, self._state
        )

        try:
            while self._state not in (RS.DONE, RS.BLOCKED):
                current = self._state
                workflow.logger.info(
                    "Entering stage req=%s state=%s rework=%d",
                    req_id, current.value, self._rework_count,
                )

                if current in _AGENT_STATES:
                    await self._run_agent_stage(req_id, initial_msg)

                if current in _GATED_STATES:
                    gate_level = _GATED_STATES[current]
                    await self._run_gate_stage(req_id, gate_level)

                # Compute next state
                next_state = self._compute_next_state(req_id, current)
                await self._transition(req_id, next_state)

        except Exception as exc:
            workflow.logger.error(
                "Workflow error req=%s: %s -> BLOCKED", req_id, exc
            )
            await self._transition(req_id, RS.BLOCKED, {"error": str(exc)})

        final = self._state.value
        workflow.logger.info(
            "RequirementWorkflow finished req=%s result=%s", req_id, final
        )
        return final

    # ── Agent stage ──────────────────────────────────────────────────

    async def _run_agent_stage(self, req_id: str, initial_msg: str):
        state = self._state
        wf_id = workflow.info().workflow_id
        timeout = _AGENT_TIMEOUTS.get(state, timedelta(minutes=10))

        # A1 (ANALYZING): runs via HTTP+SSE, workflow waits for agent_completed Signal
        if state == RS.ANALYZING:
            workflow.logger.info(
                "Waiting for A1 (HTTP/SSE) to complete req=%s", req_id,
            )
            deadline = workflow.now() + timeout
            await workflow.wait_condition(
                lambda: self._agent_result is not None or workflow.now() >= deadline,
            )
            if self._agent_result is None:
                workflow.logger.error("A1 timeout req=%s — blocking for human intervention", req_id)
                await self._transition(req_id, RS.BLOCKED, {"reason": "A1_timeout"})
            else:
                # A1 result: persist it
                agent_id = "A1"
                await workflow.execute_activity(
                    store_agent_result,
                    args=[req_id, agent_id, self._agent_result],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DEFAULT_RETRY,
                )
            return

        # Build context for NATS-dispatched agents
        ctx = await workflow.execute_activity(
            build_context,
            args=[req_id, state.value],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_DEFAULT_RETRY,
        )
        context_str = str(ctx)

        # DECOMPOSING (Phase3): A6+A7 parallel → A8 → Gate2
        if state == RS.DECOMPOSING:
            await self._run_phase3_subflow(req_id, wf_id, ctx)
            return

        if state == RS.DESIGNING:
            # DESIGNING: dispatch A3 only（用户通过 HTTP+SSE 确认后发布 agent.result.A3）
            # A3 确认后 Orchestrator 转换到 spec_writing → context.ready.A4
            # Note: A3 is primarily HTTP+SSE driven; the NATS dispatch here serves
            # as a notification that the design phase has started. A3's actual
            # generation/annotation/confirm flow happens via MC Backend endpoints.
            # Once A3 confirms (agent.result.A3 received), workflow advances to
            # KNOWLEDGE_ANALYSIS-style wait for the A3 → A4 transition via state machine.
            agent_id = "A3"
            await self._dispatch_and_wait(req_id, agent_id, wf_id, context_str, timeout, ctx_meta=ctx)
        elif state == RS.DEVELOPING and self._last_test_result:
            # Inner loop: A11 test failed, inject failure feedback into A9 context
            import json as _json
            context_str = (
                context_str
                + "\n[TEST_FAILURE_FEEDBACK]\n"
                + _json.dumps({
                    "failed_tests": self._last_test_result.get("failed_tests", []),
                    "failures_detail": self._last_test_result.get("failures_detail", []),
                    "coverage_pct": self._last_test_result.get("coverage_pct", 0),
                    "errors": (self._last_test_result.get("errors", []) or [])[:10],
                }, ensure_ascii=False)
            )
            self._last_test_result = None
            agent_id = self._agent_id_for_state(state)
            await self._dispatch_and_wait(req_id, agent_id, wf_id, context_str, timeout, ctx_meta=ctx)
        else:
            # Single agent dispatch
            agent_id = self._agent_id_for_state(state)
            await self._dispatch_and_wait(req_id, agent_id, wf_id, context_str, timeout, ctx_meta=ctx)

    # ── Phase3 sub-flow (DECOMPOSING) ─────────────────────────────────

    async def _run_phase3_subflow(self, req_id: str, wf_id: str, ctx: dict):
        """Phase3 DECOMPOSING sub-flow: A6+A7 parallel → GATHER → A8 → Gate2.

        GATHER logic: A6+A7 both complete → dispatch A8
        Gate2 reject: tech_prep_revision_count += 1, re-dispatch A6+A7
        Gate2 pass: advance to DEVELOPING
        """
        max_phase3_revisions = 5  # safety limit for Gate2 reject loops

        while self._tech_prep_revision_count < max_phase3_revisions:
            # Reset GATHER tracking
            self._a6_done = False
            self._a7_done = False
            self._a6_result = None
            self._a7_result = None
            self._a8_done = False
            self._a8_result = None

            workflow.logger.info(
                "Phase3 sub-flow start req=%s revision=%d",
                req_id, self._tech_prep_revision_count,
            )

            # Update DB: tech_prep_status = 'decomposing'
            await self._update_phase3_status(req_id, "decomposing")

            # ── Phase 3a: Dispatch A6 + A7 in parallel ─────────────
            await self.report_status(req_id, "running",
                "Phase3: 并行调度 A6+A7 (revision=%d)" % self._tech_prep_revision_count)

            # Build revision_context for rework
            revision_context = {}
            if self._tech_prep_revision_count > 0:
                revision_context = {
                    "is_revision": True,
                    "tech_prep_revision_count": self._tech_prep_revision_count,
                    "gate2_rejection": getattr(self, '_gate2_rejection', {}),
                    "previous_a8_report": getattr(self, '_previous_a8_report', {}),
                }

            # Dispatch A6
            a6_ctx = await workflow.execute_activity(
                build_context,
                args=[req_id, "decomposing", "A6", revision_context],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_DEFAULT_RETRY,
            )
            await workflow.execute_activity(
                dispatch_agent,
                args=[req_id, "decomposing", "A6", wf_id, str(a6_ctx),
                      revision_context, a6_ctx],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY,
            )

            # Dispatch A7 (dag_preview.dag_available=false for first dispatch)
            a7_ctx = await workflow.execute_activity(
                build_context,
                args=[req_id, "decomposing", "A7", revision_context],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_DEFAULT_RETRY,
            )
            await workflow.execute_activity(
                dispatch_agent,
                args=[req_id, "decomposing", "A7", wf_id, str(a7_ctx),
                      revision_context, a7_ctx],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY,
            )

            # ── GATHER: Wait for A6+A7 both complete ──────────────
            gather_timeout = timedelta(minutes=15)
            gather_deadline = workflow.now() + gather_timeout

            await workflow.wait_condition(
                lambda: (self._a6_done and self._a7_done)
                         or workflow.now() >= gather_deadline,
            )

            if not self._a6_done or not self._a7_done:
                workflow.logger.warning(
                    "Phase3 GATHER timeout req=%s (a6=%s a7=%s)",
                    req_id, self._a6_done, self._a7_done,
                )
                # Update status based on partial completion
                if self._a6_done and not self._a7_done:
                    await self._update_phase3_status(req_id, "decomposed")
                elif self._a7_done and not self._a6_done:
                    await self._update_phase3_status(req_id, "test_ready")
                # Wait longer for remaining agent
                extra_deadline = workflow.now() + timedelta(minutes=10)
                await workflow.wait_condition(
                    lambda: (self._a6_done and self._a7_done)
                             or workflow.now() >= extra_deadline,
                )
                if not (self._a6_done and self._a7_done):
                    workflow.logger.error(
                        "Phase3 GATHER extended timeout req=%s — blocking",
                        req_id,
                    )
                    await self._transition(req_id, RS.BLOCKED,
                                           {"reason": "phase3_gather_timeout"})
                    return

            # ── Phase 3b: Dispatch A8 ──────────────────────────────
            await self._update_phase3_status(req_id, "reviewing")

            await self.report_status(req_id, "running",
                "Phase3: 调度 A8 架构评审")

            # Build A8 context with DAG from A6 result
            a8_revision_context = revision_context.copy()
            a8_ctx = await workflow.execute_activity(
                build_context,
                args=[req_id, "decomposing", "A8", a8_revision_context],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_DEFAULT_RETRY,
            )
            await workflow.execute_activity(
                dispatch_agent,
                args=[req_id, "decomposing", "A8", wf_id, str(a8_ctx),
                      a8_revision_context, a8_ctx],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY,
            )

            # Wait for A8
            a8_timeout = timedelta(minutes=10)
            a8_deadline = workflow.now() + a8_timeout

            await workflow.wait_condition(
                lambda: self._a8_done or workflow.now() >= a8_deadline,
            )

            if not self._a8_done:
                workflow.logger.warning("A8 timeout req=%s — proceeding to Gate2 without A8", req_id)
                # Store partial A8 result for Gate2 review
                self._a8_result = {"status": "timeout", "review": {
                    "verdict": "fail", "score": 0,
                    "gate2_required": True,
                    "summary": "A8 架构评审超时",
                }}

            # ── Phase 3c: Gate2 approval ────────────────────────────
            await self._run_gate_stage(req_id, 2)

            # Check Gate2 decision
            if getattr(self, '_gate_decision_reject', False):
                # Gate2 reject: tech_prep_revision_count += 1, loop back
                self._tech_prep_revision_count += 1
                self._gate_decision_reject = False

                # Save rejection info for next iteration's revision_context
                self._gate2_rejection = {
                    "reject_reasons": getattr(self, '_gate_reject_reasons', []),
                    "revision_guidance": getattr(self, '_gate_revision_guidance', ""),
                }
                if self._a8_result:
                    self._previous_a8_report = self._a8_result.get("review", {})

                workflow.logger.info(
                    "Gate2 reject req=%s revision=%d — re-entering Phase3",
                    req_id, self._tech_prep_revision_count,
                )
                await self._update_phase3_status(req_id, "revising")
                continue  # loop back to Phase 3a

            # Gate2 pass: advance
            await self._update_phase3_status(req_id, "tech_prep_completed")
            workflow.logger.info(
                "Phase3 complete req=%s (revisions=%d)",
                req_id, self._tech_prep_revision_count,
            )
            return  # exit sub-flow, workflow will transition to DEVELOPING

        # Safety limit reached
        workflow.logger.error(
            "Phase3 revision limit reached req=%s — blocking",
            req_id,
        )
        await self._transition(req_id, RS.BLOCKED,
                               {"reason": "phase3_revision_limit"})

    async def _update_phase3_status(self, req_id: str, tech_prep_status: str):
        """Update requirements.tech_prep_status in DB."""
        await workflow.execute_activity(
            notify_mc,
            args=[req_id, self._state.value, self._state.value,
                  {"event": "tech_prep_status_update",
                   "tech_prep_status": tech_prep_status,
                   "tech_prep_revision_count": self._tech_prep_revision_count}],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )

    async def _run_designing_parallel(
        self, req_id: str, wf_id: str, context_str: str, timeout: timedelta,
        review_feedback: dict | None = None,
        ctx_meta: dict | None = None,
    ):
        """Dispatch A3 and A4 in parallel, wait for both.

        If review_feedback is provided (from a previous A5 review round),
        it's injected into the context so A3/A4 can use the feedback to improve.
        """
        self._agent_result_a3 = None
        self._agent_result_a4 = None
        self._agent_id_expected = "A3"  # first dispatch

        # Inject review feedback as rework_context into the context string
        # so Agent-side prepare_llm_context and rework_context parsing can pick it up
        rework_block = {}
        if review_feedback:
            import json as _json
            scores = review_feedback.get("scores", {})
            issues = review_feedback.get("issues", [])
            rework_block = {
                "round_number": self._rework_count,
                "issues": issues,
                "scores": scores,
                "suggestion": "请重点修复 critical 和 major 级别的问题",
                "previous_result": None,
            }
            context_str = (
                context_str
                + "\n[REWORK_FEEDBACK]\n"
                + _json.dumps(rework_block, ensure_ascii=False)
            )

        # Dispatch A3
        await workflow.execute_activity(
            dispatch_agent,
            args=[req_id, self._state.value, "A3", wf_id, context_str, rework_block, ctx_meta],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )
        # Dispatch A4
        await workflow.execute_activity(
            dispatch_agent,
            args=[req_id, self._state.value, "A4", wf_id, context_str, rework_block, ctx_meta],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )

        deadline = workflow.now() + timeout
        while (self._agent_result_a3 is None or self._agent_result_a4 is None) \
                and workflow.now() < deadline:
            await workflow.wait_condition(
                lambda: (self._agent_result_a3 is not None
                         and self._agent_result_a4 is not None)
                         or workflow.now() >= deadline
            )

        # Track A3/A4 failures independently
        for agent, result in [("A3", self._agent_result_a3), ("A4", self._agent_result_a4)]:
            if result is None:
                self._agent_failures[agent] = self._agent_failures.get(agent, 0) + 1
                failures = self._agent_failures[agent]
                level = "warning" if agent == "A3" else "error"
                if agent == "A3":
                    workflow.logger.warning("A3 timeout — non-fatal (failure #%d)", failures)
                else:
                    workflow.logger.error("A4 timeout req=%s — escalating (failure #%d)", req_id, failures)
                if failures >= 2:
                    await workflow.execute_activity(
                        notify_mc,
                        args=[req_id, self._state.value, self._state.value,
                              {"event": "agent_repeated_timeout", "agent_id": agent,
                               "consecutive_failures": failures}],
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=_DEFAULT_RETRY,
                    )
            else:
                self._agent_failures[agent] = 0

                # T8: Check if agent requested BLOCKED before persisting
                agent_status = result.get("status", "")
                if agent_status in ("blocked", "escalated"):
                    workflow.logger.warning(
                        "Agent %s requested block: %s",
                        agent, result.get("reason", "unknown"),
                    )
                    continue  # skip store_agent_result

            # Persist A3/A4 results (A4 is in _AGENTS_THAT_PERSIST, so only A3 persists)
            if result is not None and agent not in _AGENTS_THAT_PERSIST:
                await workflow.execute_activity(
                    store_agent_result,
                    args=[req_id, agent, result],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DEFAULT_RETRY,
                )

    async def _dispatch_and_wait(
        self, req_id: str, agent_id: str, wf_id: str,
        context_str: str, timeout: timedelta,
        ctx_meta: dict | None = None,
    ):
        """Dispatch one agent and wait for completion via Signal.

        Tracks consecutive timeout failures per agent_id.
        Two consecutive timeouts trigger notify_mc escalation.
        Successful completion resets the failure counter.
        """
        ctx_meta = ctx_meta or {}
        self._agent_result = None
        self._agent_id_expected = agent_id

        await workflow.execute_activity(
            dispatch_agent,
            args=[req_id, self._state.value, agent_id, wf_id, context_str, {},
                  ctx_meta],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )

        deadline = workflow.now() + timeout
        while self._agent_result is None and workflow.now() < deadline:
            await workflow.wait_condition(
                lambda: self._agent_result is not None
                         or workflow.now() >= deadline
            )

        if self._agent_result is None:
            self._agent_failures[agent_id] = self._agent_failures.get(agent_id, 0) + 1
            failures = self._agent_failures[agent_id]
            workflow.logger.warning(
                "Agent %s timeout #%d req=%s", agent_id, failures, req_id,
            )
            if failures >= 2:
                await workflow.execute_activity(
                    notify_mc,
                    args=[req_id, self._state.value, self._state.value,
                          {"event": "agent_repeated_timeout", "agent_id": agent_id,
                           "consecutive_failures": failures}],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_DEFAULT_RETRY,
                )
        else:
            # Success resets the failure counter
            self._agent_failures[agent_id] = 0

            # T8: Check if agent requested BLOCKED before persisting
            agent_status = self._agent_result.get("status", "")
            if agent_status in ("blocked", "escalated"):
                workflow.logger.warning(
                    "Agent %s requested block: %s",
                    agent_id, self._agent_result.get("reason", "unknown"),
                )
                return  # skip store_agent_result, _compute_next_state handles BLOCKED

        # Persist agent result to DB (skip A4 — writes itself)
        if self._agent_result is not None and agent_id not in _AGENTS_THAT_PERSIST:
            await workflow.execute_activity(
                store_agent_result,
                args=[req_id, agent_id, self._agent_result],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY,
            )

    # ── Gate stage ───────────────────────────────────────────────────

    async def _run_gate_stage(self, req_id: str, gate_level: int):
        """Create gate record, then wait for human approval.

        Three phases:
          1. Wait within SLA → if approved, return
          2. SLA expired → notify (gate_timeout), enter grace period (Gate 1/2)
          3. Grace expired → escalate, wait indefinitely for human approval
        Gate is NEVER auto-approved — only approve_gate or gate_timeout Signal.
        """
        self._gate_approved = None
        sla = _GATE_SLA.get(gate_level, timedelta(hours=4))
        sla_seconds = sla.total_seconds()

        await workflow.execute_activity(
            create_gate_approval,
            args=[req_id, gate_level, sla_seconds],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )

        workflow.logger.info(
            "Waiting for Gate %d approval req=%s sla=%ds",
            gate_level, req_id, sla_seconds,
        )

        # Phase 1: Wait for approval within SLA
        sla_deadline = workflow.now() + sla
        await workflow.wait_condition(
            lambda: self._gate_approved is not None
                     or workflow.now() >= sla_deadline,
        )

        if self._gate_approved is not None:
            workflow.logger.info(
                "Gate %d approved req=%s (within SLA)", gate_level, req_id,
            )
            return

        # Phase 2: SLA expired — notify, check grace period
        workflow.logger.warning(
            "Gate %d SLA expired req=%s — notifying", gate_level, req_id,
        )
        await workflow.execute_activity(
            notify_mc,
            args=[req_id, self._state.value, self._state.value,
                  {"event": "gate_timeout", "gate_level": gate_level,
                   "sla_hours": sla_seconds / 3600}],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )

        grace = _GATE_GRACE_PERIOD.get(gate_level)
        if grace is not None:
            # Gate 1/2: give extra wait window
            grace_deadline = workflow.now() + grace
            workflow.logger.info(
                "Gate %d grace period %ds req=%s",
                gate_level, grace.total_seconds(), req_id,
            )
            await workflow.wait_condition(
                lambda: self._gate_approved is not None
                         or workflow.now() >= grace_deadline,
            )
            if self._gate_approved is not None:
                workflow.logger.info(
                    "Gate %d approved req=%s (during grace)", gate_level, req_id,
                )
                return

            # Grace period expired — escalate
            workflow.logger.warning(
                "Gate %d grace expired req=%s — escalating", gate_level, req_id,
            )
            await workflow.execute_activity(
                notify_mc,
                args=[req_id, self._state.value, self._state.value,
                      {"event": "gate_grace_expired", "gate_level": gate_level}],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY,
            )

        # Phase 3: Wait indefinitely for human approval (never auto-advance)
        workflow.logger.info(
            "Gate %d waiting indefinitely for human approval req=%s",
            gate_level, req_id,
        )
        await self._wait_for_gate()
        workflow.logger.info(
            "Gate %d approved req=%s", gate_level, req_id,
        )

    async def _wait_for_gate(self):
        """Block indefinitely until gate approved or force-skipped by admin."""
        await workflow.wait_condition(
            lambda: self._gate_approved is not None,
        )

    # ── Temporal Signals ────────────────────────────────────────────

    @workflow.signal
    async def agent_completed(self, agent_id: str, result: dict):
        """Signal: an agent has completed its work."""
        workflow.logger.info(
            "Signal agent_completed agent=%s", agent_id
        )
        if agent_id == "A3":
            self._agent_result_a3 = result
        elif agent_id == "A4":
            self._agent_result_a4 = result
        elif agent_id == "A6":
            self._a6_done = True
            self._a6_result = result
        elif agent_id == "A7":
            self._a7_done = True
            self._a7_result = result
        elif agent_id == "A8":
            self._a8_done = True
            self._a8_result = result
        elif agent_id == self._agent_id_expected:
            self._agent_result = result
        else:
            workflow.logger.warning(
                "Ignored agent_completed from %s (expected %s or A3/A4/A6/A7/A8)",
                agent_id, self._agent_id_expected,
            )

    @workflow.signal
    async def agent_status(self, agent_id: str, status: str, message: str):
        """Signal: agent progress update (best-effort)."""
        self._agent_progress[agent_id] = {
            "status": status,
            "message": message,
        }

    @workflow.signal
    async def approve_gate(self, gate_name: str, approver: str = ""):
        """Signal: a human approved the current gate."""
        workflow.logger.info(
            "Signal approve_gate gate=%s approver=%s", gate_name, approver,
        )
        self._gate_approved = gate_name

    @workflow.signal
    async def reject_gate(self, gate_name: str, reason: str = "",
                          reject_reasons: list | None = None,
                          revision_guidance: str = ""):
        """Signal: a human rejected the current gate."""
        workflow.logger.info(
            "Signal reject_gate gate=%s reason=%s", gate_name, reason,
        )
        self._gate_approved = gate_name  # unblock wait_condition
        self._gate_decision = "reject"
        self._gate_reject_reasons = reject_reasons or []
        self._gate_revision_guidance = revision_guidance
        # For Gate 0: set flag to route back to ANALYZING
        self._gate_decision_reject = True

    @workflow.signal
    async def gate_timeout(self, gate_level: int, approver: str = ""):
        """Signal: admin manually skip a gate.

        Distinct from SLA timeout — this is a deliberate human action.
        Records the approver so the audit trail distinguishes manual skip
        from normal approval.
        """
        workflow.logger.warning(
            "Gate %d force-skipped by admin: %s", gate_level, approver,
        )
        self._gate_approved = f"force-skip-gate-{gate_level}-by-{approver}"

    @workflow.signal
    async def pause(self):
        """Signal: pause the workflow."""
        workflow.logger.info("Signal pause received")

    @workflow.signal
    async def resume(self):
        """Signal: resume the workflow."""
        workflow.logger.info("Signal resume received")

    # ── Queries ──────────────────────────────────────────────────────

    @workflow.query
    def get_state(self) -> dict:
        """Query current workflow state."""
        return {
            "state": self._state.value,
            "log_len": len(self._log),
            "rework_count": self._rework_count,
        }

    @workflow.query
    def get_progress(self) -> dict:
        """Query current progress including agent statuses."""
        return {
            "state": self._state.value,
            "agent_progress": dict(self._agent_progress),
            "rework_count": self._rework_count,
            "log": self._log[-10:],
        }

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _agent_id_for_state(state: RS) -> str:
        """Map a pipeline state to the primary agent ID."""
        _map = {
            RS.DRAFT: "A1",
            RS.ANALYZING: "A1",              # HTTP+SSE, not dispatched
            RS.KNOWLEDGE_ANALYSIS: "A2",     # new A2 knowledge analysis
            RS.DESIGNING: "A3",              # A3 UI prototype (HTTP+SSE)
            RS.SPEC_WRITING: "A4",           # A4 Spec/OpenAPI/ERD/DDL
            RS.REVIEWING: "A5",              # A5 design review
            RS.DECOMPOSING: "A6",
            RS.DEVELOPING: "A9",
            RS.TESTING: "A11",
            RS.REVIEWING_CODE: "A12",
            RS.RELEASING: "A13",
        }
        return _map.get(state, "A1")

    async def _transition(
        self, req_id: str, new_state: RS, extra: dict | None = None
    ):
        old = self._state
        if new_state == old:
            return
        allowed = TRANSITION_TABLE.get(old, [])
        if new_state not in allowed:
            workflow.logger.error(
                "Invalid transition req=%s %s -> %s (blocking)",
                req_id, old.value, new_state.value,
            )
            self._state = RS.BLOCKED
        else:
            self._state = new_state
        self._log.append({
            "from": old.value,
            "to": self._state.value,
            "extra": extra or {},
        })
        await workflow.execute_activity(
            notify_mc,
            args=[req_id, old.value, self._state.value, extra],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )

    def _compute_next_state(self, req_id: str, current: RS) -> RS:
        """State machine with rework loop, inner loop, and BLOCKED path."""

        # T8: Agent may request BLOCKED — check before all other branches
        if self._agent_result:
            agent_status = self._agent_result.get("status", "")
            if agent_status in ("blocked", "escalated"):
                workflow.logger.warning(
                    "Agent %s requested block: %s",
                    self._agent_id_expected,
                    self._agent_result.get("reason", "unknown"),
                )
                return RS.BLOCKED

        # REVIEWING (A5) — non-blocking design check, always advance
        # A5 produces a report, never a pass/fail verdict.
        # Rework is driven by Gate1 rejection, not by A5.
        if current == RS.REVIEWING:
            if self._agent_result:
                self._last_a5_result = self._agent_result
            workflow.logger.info(
                "A5 design review complete (non-blocking) — advancing to DECOMPOSING"
            )
            return RS.DECOMPOSING

        # T8: TESTING fail → back to DEVELOPING (inner loop, max 2)
        if current == RS.TESTING:
            a11_pass = False
            if self._agent_result:
                a11_pass = self._agent_result.get(
                    "pass", self._agent_result.get("status") == "completed"
                )
            if not a11_pass and self._inner_loop_count < 2:
                self._inner_loop_count += 1
                workflow.logger.info(
                    "Inner loop #%d: TESTING -> DEVELOPING (rework)",
                    self._inner_loop_count,
                )
                self._last_test_result = self._agent_result
                return RS.DEVELOPING
            # Pass or exhausted → continue
            self._inner_loop_count = 0
            return RS.REVIEWING_CODE

        # DRAFT
        if current == RS.DRAFT:
            return RS.ANALYZING

        # KNOWNLEDGE_ANALYSIS with Gate 0 reject: back to ANALYZING
        if current == RS.KNOWLEDGE_ANALYSIS:
            # Gate 0 decision handled in _run_gate_stage — if rejected,
            # _gate_decision_reject is set to True, go back to ANALYZING
            if getattr(self, '_gate_decision_reject', False):
                self._gate_decision_reject = False
                workflow.logger.info(
                    "Gate 0 rejected req=%s — returning to ANALYZING for revision", req_id,
                )
                return RS.ANALYZING

        # Simple linear for the rest
        _linear_next = {
            RS.ANALYZING: RS.KNOWLEDGE_ANALYSIS,       # A1 -> A2
            RS.KNOWLEDGE_ANALYSIS: RS.DESIGNING,       # Gate 0 pass
            RS.DESIGNING: RS.REVIEWING,                # Gate 1 pass
            RS.REVIEWING_CODE: RS.RELEASING,           # Gate 3 pass
            RS.DEVELOPING: RS.TESTING,
            RS.DECOMPOSING: RS.DEVELOPING,             # Gate 2 pass
            RS.RELEASING: RS.DONE,
        }
        return _linear_next.get(current, RS.DONE)
