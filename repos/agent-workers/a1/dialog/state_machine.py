"""
dialog/state_machine.py — Dialog State Machine

Manages the multi-round clarification conversation between the A1 agent
and the user. The conversation walks through a fixed state graph:

    IDLE → UNDERSTANDING → GENERATING → WAITING_FOR_USER → (loop) → COMPLETED

When the machine is in WAITING_FOR_USER, a 30-minute timeout guard fires
if the user does not respond, moving the flow to COMPLETED with a warning.

Contract:
    class DialogStateMachine
        states: frozenset[str]
        async transition(event: str) -> str   (returns new state)
"""

import asyncio
import enum
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class DialogState(str, enum.Enum):
    IDLE = "IDLE"
    UNDERSTANDING = "UNDERSTANDING"
    GENERATING = "GENERATING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    COMPLETED = "COMPLETED"


# Valid transitions (current -> allowed next states)
_TRANSITIONS: dict[DialogState, set[DialogState]] = {
    DialogState.IDLE: {DialogState.UNDERSTANDING},
    DialogState.UNDERSTANDING: {DialogState.GENERATING, DialogState.WAITING_FOR_USER, DialogState.COMPLETED},
    DialogState.GENERATING: {DialogState.WAITING_FOR_USER, DialogState.COMPLETED},
    DialogState.WAITING_FOR_USER: {DialogState.UNDERSTANDING, DialogState.GENERATING, DialogState.COMPLETED},
    DialogState.COMPLETED: set(),  # terminal
}

# ---- events that trigger transitions ----
EVENT_MAP: dict[str, DialogState] = {
    "message_received": DialogState.UNDERSTANDING,
    "clarify_complete": DialogState.GENERATING,
    "need_user_input": DialogState.WAITING_FOR_USER,
    "user_responded": DialogState.UNDERSTANDING,
    "generation_done": DialogState.COMPLETED,
    "timeout": DialogState.COMPLETED,
}


class DialogStateMachine:
    """Finite-state machine for A1 multi-round requirement clarification.

    Features:
      - Strict transition guard – invalid transitions raise ValueError.
      - Auto-timeout on WAITING_FOR_USER (default 30 minutes).
      - Each transition is logged with a timestamp for audit trails.
    """

    states = frozenset(s.value for s in DialogState)

    def __init__(self, timeout_minutes: int = 30):
        self.state: DialogState = DialogState.IDLE
        self.timeout_minutes = timeout_minutes
        self._timeout_task: Optional[asyncio.Task] = None
        self._history: list[dict] = []
        logger.info("DialogStateMachine initialised (state=%s, timeout=%dm)", self.state.value, timeout_minutes)

    # ------------------------------------------------------------------
    #  public API
    # ------------------------------------------------------------------

    async def transition(self, event: str) -> str:
        """Process an event and advance the state machine.

        Args:
            event: A recognised event name (see ``EVENT_MAP``).
                   Unknown events trigger a warning but do **not** change state.

        Returns:
            The new state value (string enum member).

        Raises:
            ValueError: if the transition is not allowed.
        """
        logger.info("Transition requested: [%s] --(%s)--> ?", self.state.value, event)

        if event not in EVENT_MAP:
            logger.warning("Unknown event '%s' – staying in %s", event, self.state.value)
            return self.state.value

        target = EVENT_MAP[event]

        if target not in _TRANSITIONS.get(self.state, set()):
            raise ValueError(
                f"Invalid transition: {self.state.value} --({event})--> {target.value}"
            )

        # Advance
        previous = self.state
        self.state = target
        self._history.append({
            "from": previous.value,
            "event": event,
            "to": target.value,
            "at": datetime.now(timezone.utc).isoformat(),
        })

        logger.info("State change: %s → %s", previous.value, target.value)

        # Arm / disarm the WAITING_FOR_USER timeout
        if target == DialogState.WAITING_FOR_USER:
            self._arm_timeout()
        elif self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()

        return self.state.value

    # ------------------------------------------------------------------
    #  timeout guard
    # ------------------------------------------------------------------

    def _arm_timeout(self) -> None:
        """Schedule a transition to COMPLETED after ``timeout_minutes``."""
        async def _guard() -> None:
            await asyncio.sleep(self.timeout_minutes * 60)
            logger.warning("WAITING_FOR_USER timeout reached (%dm) → COMPLETED", self.timeout_minutes)
            if self.state == DialogState.WAITING_FOR_USER:
                self.state = DialogState.COMPLETED
                self._history.append({
                    "from": "WAITING_FOR_USER",
                    "event": "timeout",
                    "to": "COMPLETED",
                    "at": datetime.now(timezone.utc).isoformat(),
                })

        self._timeout_task = asyncio.ensure_future(_guard())

    # ------------------------------------------------------------------
    #  introspection
    # ------------------------------------------------------------------

    @property
    def history(self) -> list[dict]:
        return list(self._history)

    @property
    def is_terminal(self) -> bool:
        return self.state == DialogState.COMPLETED
