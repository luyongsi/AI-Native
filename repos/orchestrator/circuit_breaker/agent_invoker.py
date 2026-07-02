"""Agent invocation with circuit breaker integration.

Provides the main orchestration logic for invoking agents with
automatic escalation (few-shot → strong model → human).
"""

import logging
from typing import Optional, Any

from .circuit_breaker import (
    CircuitBreaker,
    EscalationLevel,
    get_circuit_breaker,
)
from .few_shot_examples import (
    inject_few_shot_into_context,
)
from .model_selector import (
    get_model_selector,
    override_model_in_context,
)
from .human_escalation import (
    escalate_to_human,
)
from .metrics import (
    get_metrics,
)

logger = logging.getLogger(__name__)


class AgentInvoker:
    """Orchestrate agent invocation with circuit breaker escalation."""

    def __init__(
        self,
        circuit_breaker: Optional[CircuitBreaker] = None,
        max_retries: int = 3
    ):
        """Initialize agent invoker.

        Args:
            circuit_breaker: Circuit breaker instance (uses default if None)
            max_retries: Maximum number of retry attempts
        """
        self.circuit_breaker = circuit_breaker or get_circuit_breaker()
        self.max_retries = max_retries
        self.model_selector = get_model_selector()
        self.metrics = get_metrics()

    async def invoke_with_escalation(
        self,
        agent_func,
        req_id: str,
        agent_id: str,
        context: dict,
        task_type: str = None
    ) -> Any:
        """Invoke agent with automatic escalation on failure.

        Escalation strategy:
          1. First failure (FEW_SHOT): Inject few-shot examples
          2. Second failure (STRONG_MODEL): Switch to stronger model
          3. Third failure (HUMAN): Request human intervention

        Args:
            agent_func: Async callable agent function
            req_id: Requirement ID
            agent_id: Agent identifier (e.g., 'A4', 'A9')
            context: Execution context dict
            task_type: Task type for few-shot selection (optional)

        Returns:
            Agent execution result

        Raises:
            Exception: If all retries exhausted
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                # Get current escalation level
                level = self.circuit_breaker.get_level(req_id, agent_id)

                # Prepare context based on escalation level
                attempt_context = context.copy()

                if level == EscalationLevel.FEW_SHOT:
                    logger.info(
                        f"[Escalation] Attempt {attempt + 1}: Injecting few-shot examples "
                        f"req_id={req_id} agent_id={agent_id}"
                    )
                    inject_few_shot_into_context(attempt_context, agent_id, task_type)
                    self.metrics.increment_escalation(agent_id, "FEW_SHOT")

                elif level == EscalationLevel.STRONG_MODEL:
                    logger.info(
                        f"[Escalation] Attempt {attempt + 1}: Switching to strong model "
                        f"req_id={req_id} agent_id={agent_id}"
                    )
                    override_model_in_context(attempt_context, failure_count=1)
                    self.metrics.increment_escalation(agent_id, "STRONG_MODEL")

                elif level == EscalationLevel.HUMAN:
                    logger.warning(
                        f"[Escalation] Attempt {attempt + 1}: Triggering human escalation "
                        f"req_id={req_id} agent_id={agent_id}"
                    )
                    await escalate_to_human(
                        req_id, agent_id,
                        error_message=f"Agent failed multiple times: {last_error}",
                        context_summary=f"Requirement context available at dashboard"
                    )
                    # Still attempt with ultra model before giving up
                    override_model_in_context(attempt_context, failure_count=2)
                    self.metrics.increment_escalation(agent_id, "HUMAN")
                    self.metrics.increment_human_request(agent_id)

                # Execute agent
                logger.debug(
                    f"Invoking agent req_id={req_id} agent_id={agent_id} "
                    f"attempt={attempt + 1}/{self.max_retries} level={level.name}"
                )
                result = await agent_func(req_id, agent_id, attempt_context)

                # Success: reset circuit breaker
                self.circuit_breaker.reset(req_id, agent_id)
                logger.info(
                    f"Agent succeeded req_id={req_id} agent_id={agent_id} "
                    f"attempt={attempt + 1}"
                )
                return result

            except Exception as e:
                last_error = str(e)
                logger.error(
                    f"Agent failed req_id={req_id} agent_id={agent_id} "
                    f"attempt={attempt + 1}: {last_error}"
                )

                # Record failure and get new escalation level
                if attempt < self.max_retries - 1:
                    new_level = self.circuit_breaker.record_failure(req_id, agent_id)
                    logger.info(
                        f"Recording failure and escalating to {new_level.name}"
                    )
                    self.metrics.set_failure_count(
                        req_id, agent_id,
                        self.circuit_breaker._state[(req_id, agent_id)].failure_count
                    )
                else:
                    # Last attempt: give up
                    logger.error(
                        f"All retries exhausted req_id={req_id} agent_id={agent_id}"
                    )
                    raise

        # Should not reach here, but safeguard
        raise RuntimeError(f"Agent invocation failed after {self.max_retries} attempts")


# Module-level singleton
_invoker: AgentInvoker | None = None


def get_agent_invoker() -> AgentInvoker:
    """Get or create the module-level agent invoker instance."""
    global _invoker
    if _invoker is None:
        _invoker = AgentInvoker()
    return _invoker
