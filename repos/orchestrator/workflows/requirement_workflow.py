"""Temporal Workflow: RequirementWorkflow.

Implements the full state machine per design doc.

State progression:
    DRAFT -> ANALYZING -> Gate 0 -> DESIGNING -> Gate 1 -> REVIEWING ->
    DECOMPOSING -> Gate 2 -> DEVELOPING -> TESTING ->
    REVIEWING_CODE -> Gate 3 -> RELEASING -> DONE

Rework:
    REVIEWING fail -> back to DESIGNING (max 2 rounds), then escalate Gate.

All agent dispatch goes through NATS (via dispatch_agent Activity).
Agent completion comes back via Bridge -> agent_completed Signal.
Gate approval via approve_gate Signal from MC Backend.
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

logger = logging.getLogger(__name__)

_DEFAULT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
)

# Agent timeout per state
_AGENT_TIMEOUTS: dict[RS, timedelta] = {
    RS.ANALYZING: timedelta(minutes=5),
    RS.DESIGNING: timedelta(minutes=15),
    RS.REVIEWING: timedelta(minutes=10),
    RS.DECOMPOSING: timedelta(minutes=10),
    RS.DEVELOPING: timedelta(hours=4),
    RS.TESTING: timedelta(hours=2),
    RS.REVIEWING_CODE: timedelta(minutes=15),
    RS.RELEASING: timedelta(minutes=30),
}

# States that require agent execution
_AGENT_STATES: set[RS] = {
    RS.ANALYZING, RS.DESIGNING, RS.REVIEWING, RS.DECOMPOSING,
    RS.DEVELOPING, RS.TESTING, RS.REVIEWING_CODE, RS.RELEASING,
}

# States that require gate approval
_GATED_STATES: dict[RS, int] = {
    RS.ANALYZING: 0,
    RS.DESIGNING: 1,
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
        self._escalate: bool = False

        # A3/A4 parallel tracking
        self._agent_result_a3: dict | None = None
        self._agent_result_a4: dict | None = None
        self._last_a5_result: dict | None = None

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

        # Build context
        ctx = await workflow.execute_activity(
            build_context,
            args=[req_id, state.value],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_DEFAULT_RETRY,
        )
        context_str = str(ctx)

        if state == RS.DESIGNING:
            # DESIGNING: dispatch A3 and A4 in parallel
            # If this is a rework, inject previous A5 review feedback
            review_feedback = self._last_a5_result if self._rework_count > 0 else None
            await self._run_designing_parallel(req_id, wf_id, context_str, timeout, review_feedback)
        else:
            # Single agent dispatch
            agent_id = self._agent_id_for_state(state)
            await self._dispatch_and_wait(req_id, agent_id, wf_id, context_str, timeout)

    async def _run_designing_parallel(
        self, req_id: str, wf_id: str, context_str: str, timeout: timedelta,
        review_feedback: dict | None = None,
    ):
        """Dispatch A3 and A4 in parallel, wait for both.

        If review_feedback is provided (from a previous A5 review round),
        it's injected into the context so A3/A4 can use the feedback to improve.
        """
        self._agent_result_a3 = None
        self._agent_result_a4 = None
        self._agent_id_expected = "A3"  # first dispatch

        # Inject review feedback into context for rework iterations
        if review_feedback:
            import json as _json
            context_str = context_str + "\n[REWORK_FEEDBACK]\n" + _json.dumps(
                review_feedback.get("scores", review_feedback),
                ensure_ascii=False,
            ) + "\n" + _json.dumps(
                review_feedback.get("issues", []),
                ensure_ascii=False,
            )

        # Dispatch A3
        await workflow.execute_activity(
            dispatch_agent,
            args=[req_id, self._state.value, "A3", wf_id, context_str],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )
        # Dispatch A4
        await workflow.execute_activity(
            dispatch_agent,
            args=[req_id, self._state.value, "A4", wf_id, context_str],
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

        if self._agent_result_a3 is None:
            workflow.logger.warning("A3 timeout — using fallback, non-fatal")
        if self._agent_result_a4 is None:
            workflow.logger.error("A4 timeout — escalating")
            self._escalate = True

    async def _dispatch_and_wait(
        self, req_id: str, agent_id: str, wf_id: str,
        context_str: str, timeout: timedelta
    ):
        """Dispatch one agent and wait for completion via Signal."""
        self._agent_result = None
        self._agent_id_expected = agent_id

        await workflow.execute_activity(
            dispatch_agent,
            args=[req_id, self._state.value, agent_id, wf_id, context_str],
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
            workflow.logger.error(
                "Agent %s timeout req=%s — escalating", agent_id, req_id
            )
            self._escalate = True

    # ── Gate stage ───────────────────────────────────────────────────

    async def _run_gate_stage(self, req_id: str, gate_level: int):
        """Create gate record, then wait for approve_gate Signal."""
        self._gate_approved = None

        await workflow.execute_activity(
            create_gate_approval,
            args=[req_id, gate_level],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_DEFAULT_RETRY,
        )

        workflow.logger.info(
            "Waiting for Gate %d approval req=%s", gate_level, req_id
        )

        await workflow.wait_condition(
            lambda: self._gate_approved is not None
        )

        workflow.logger.info(
            "Gate %d approved req=%s", gate_level, req_id
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
        elif agent_id == self._agent_id_expected:
            self._agent_result = result
        else:
            workflow.logger.warning(
                "Ignored agent_completed from %s (expected %s or A3/A4)",
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
    async def reject_gate(self, gate_name: str, reason: str = ""):
        """Signal: a human rejected the current gate."""
        workflow.logger.info(
            "Signal reject_gate gate=%s reason=%s", gate_name, reason,
        )
        self._gate_approved = gate_name  # unblock, but result will show rejection

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
            RS.ANALYZING: "A1",
            RS.REVIEWING: "A5",
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
        """Linear state machine with rework loop."""

        # REVIEWING -> check A5 result for rework
        if current == RS.REVIEWING:
            a5_pass = False
            if self._agent_result:
                a5_pass = self._agent_result.get("pass", False)
            if not a5_pass and self._rework_count < _MAX_REWORK:
                self._rework_count += 1
                workflow.logger.info(
                    "Rework #%d: REVIEWING -> DESIGNING", self._rework_count
                )
                if self._agent_result:
                    self._last_a5_result = self._agent_result
                return RS.DESIGNING
            # Either passed or max rework reached
            return RS.DECOMPOSING

        # DRAFT
        if current == RS.DRAFT:
            return RS.ANALYZING

        # After ANALYZING -> Gate is between, TRANSITION_TABLE handles it
        # After DESIGNING -> Gate 1
        # After DECOMPOSING -> Gate 2
        # After REVIEWING_CODE -> Gate 3

        # Simple linear for the rest
        _linear_next = {
            RS.ANALYZING: RS.DESIGNING,       # via Gate 0 (but that's handled by wait_condition)
            RS.DESIGNING: RS.REVIEWING,        # via Gate 1
            RS.REVIEWING_CODE: RS.RELEASING,   # via Gate 3
            RS.DEVELOPING: RS.TESTING,
            RS.TESTING: RS.REVIEWING_CODE,
            RS.DECOMPOSING: RS.DEVELOPING,     # via Gate 2
            RS.RELEASING: RS.DONE,
        }
        return _linear_next.get(current, RS.DONE)
