"""Temporal Workflow: FastChannelWorkflow.

Accelerated path for d4/extreme requirements. Operates on the
FAST_TRANSITION_TABLE, skipping DESIGNING, REVIEWING, DECOMPOSING,
and REVIEWING_CODE stages entirely.

Path:
    DRAFT -> FAST_PASS -> DEVELOPING -> TESTING -> RELEASING -> DONE
"""

from __future__ import annotations

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from state_machine.states import RequirementState as RS
    from state_machine.transitions import FAST_TRANSITION_TABLE
    from activities.dispatch_agent import dispatch_agent
    from activities.gate_await import await_gate_approval
    from activities.context_build import build_context
    from activities.notify_mc import notify_mc
    from circuit_breaker.loop_tracker import loop_tracker

logger = logging.getLogger(__name__)

_DEFAULT_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn(name="FastChannelWorkflow")
class FastChannelWorkflow:
    """Fast-track workflow for extreme-priority requirements."""

    def __init__(self) -> None:
        self._state: RS = RS.DRAFT
        self._log: list[dict] = []

    @workflow.run
    async def run(self, req_id: str, initial_msg: str) -> str:
        workflow.logger.info(
            "FastChannelWorkflow started req=%s msg=%s", req_id, initial_msg[:80]
        )

        # Fast-track stages (no gates for DESIGN/REVIEW/DECOMPOSE/CODE_REVIEW)
        _fast_pipeline: list[RS] = [
            RS.FAST_PASS,
            RS.DEVELOPING,
            RS.TESTING,
            RS.RELEASING,
            RS.DONE,
        ]

        try:
            for stage in _fast_pipeline:
                workflow.logger.info(
                    "FastChannelWorkflow req=%s stage=%s", req_id, stage
                )

                # Transition
                await self._transition(req_id, stage)

                if stage == RS.DONE:
                    break

                # Build context
                ctx = await workflow.execute_activity(
                    build_context,
                    args=[req_id, stage.value],
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=_DEFAULT_RETRY,
                )

                # Dispatch agent
                await workflow.execute_activity(
                    dispatch_agent,
                    args=[req_id, stage.value, str(ctx)],
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=_DEFAULT_RETRY,
                )

                # Gate only for RELEASING in fast track
                if stage == RS.RELEASING:
                    gate = await workflow.execute_activity(
                        await_gate_approval,
                        args=[req_id, "release"],
                        start_to_close_timeout=timedelta(seconds=360),
                        retry_policy=_DEFAULT_RETRY,
                    )
                    if not gate.get("approved"):
                        await self._transition(req_id, RS.BLOCKED, {"gate_denied": "release"})
                        return "blocked"

                # Inner loop: DEVELOPING <-> TESTING (max 2)
                if stage == RS.TESTING and loop_tracker.get(req_id).inner < 2:
                    workflow.logger.info(
                        "FastChannel inner loop req=%s cnt=%d",
                        req_id, loop_tracker.get(req_id).inner,
                    )
                    # In fast track, re-dispatch on DEVELOPING
                    await workflow.execute_activity(
                        dispatch_agent,
                        args=[req_id, RS.DEVELOPING.value, str(ctx)],
                        start_to_close_timeout=timedelta(seconds=120),
                        retry_policy=_DEFAULT_RETRY,
                    )
                    loop_tracker.increment(req_id, "inner")

        except Exception as exc:
            workflow.logger.error(
                "FastChannelWorkflow error req=%s: %s -> BLOCKED", req_id, exc
            )
            await self._transition(req_id, RS.BLOCKED, {"error": str(exc)})
            return "blocked"

        return "done"

    async def _transition(
        self, req_id: str, new_state: RS, extra: dict | None = None
    ) -> None:
        old = self._state
        if new_state == old:
            return
        if new_state != RS.BLOCKED and new_state not in FAST_TRANSITION_TABLE.get(old, []):
            workflow.logger.error(
                "Invalid fast transition req=%s %s -> %s", req_id, old.value, new_state.value
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
