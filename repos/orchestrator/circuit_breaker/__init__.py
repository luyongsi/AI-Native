"""Circuit breaker sub-package for the orchestrator."""

from .loop_tracker import LoopCounters, LoopTracker, loop_tracker
from .escalation import escalate, EscalationLevel as EscalationLevelOrig
from .sanitizer import sanitize_context
from .circuit_breaker import (
    CircuitBreaker,
    EscalationLevel,
    get_circuit_breaker,
)
from .few_shot_examples import (
    get_few_shot_examples,
    inject_few_shot_into_context,
)
from .model_selector import (
    ModelSelector,
    ModelTier,
    get_model_selector,
    override_model_in_context,
)
from .human_escalation import (
    HumanEscalation,
    get_human_escalation,
    escalate_to_human,
)
from .metrics import (
    CircuitBreakerMetrics,
    get_metrics,
)
from .agent_invoker import (
    AgentInvoker,
    get_agent_invoker,
)

__all__ = [
    "LoopCounters",
    "LoopTracker",
    "loop_tracker",
    "sanitize_context",
    "escalate",
    "EscalationLevelOrig",
    "CircuitBreaker",
    "EscalationLevel",
    "get_circuit_breaker",
    "get_few_shot_examples",
    "inject_few_shot_into_context",
    "ModelSelector",
    "ModelTier",
    "get_model_selector",
    "override_model_in_context",
    "HumanEscalation",
    "get_human_escalation",
    "escalate_to_human",
    "CircuitBreakerMetrics",
    "get_metrics",
    "AgentInvoker",
    "get_agent_invoker",
]
