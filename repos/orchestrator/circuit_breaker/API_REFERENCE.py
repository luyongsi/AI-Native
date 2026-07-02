"""
Circuit Breaker Strategy Upgrade (Task #43) - Public API Reference

Quick reference for all exported classes, functions, and enums.
"""

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

from circuit_breaker import (
    # Core escalation
    CircuitBreaker,
    EscalationLevel,
    get_circuit_breaker,

    # Few-shot examples
    get_few_shot_examples,
    inject_few_shot_into_context,

    # Model selection
    ModelSelector,
    ModelTier,
    get_model_selector,
    override_model_in_context,

    # Human escalation
    HumanEscalation,
    get_human_escalation,
    escalate_to_human,

    # Metrics
    CircuitBreakerMetrics,
    get_metrics,

    # Agent orchestration
    AgentInvoker,
    get_agent_invoker,
)


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class EscalationLevel:
    """Escalation levels for circuit breaker.

    Values:
        NORMAL (0):        No escalation, use normal model
        FEW_SHOT (1):      Inject few-shot examples
        STRONG_MODEL (2):  Switch to Claude Sonnet
        HUMAN (3):         Request human intervention (Feishu)
    """
    pass


class ModelTier:
    """Model tier selection.

    Values:
        NORMAL:  DeepSeek v3 (cost-optimized)
        STRONG:  Claude 3.5 Sonnet (balanced)
        ULTRA:   Claude Opus (highest quality)
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER (circuit_breaker.py)
# ══════════════════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Main circuit breaker state management.

    Tracks per-(req_id, agent_id) failure counts and escalation levels.
    Automatically escalates through three levels on repeated failures.

    Example:
        cb = CircuitBreaker()
        level = cb.get_level("req-1", "A4")  # EscalationLevel.NORMAL
        new_level = cb.record_failure("req-1", "A4")  # FEW_SHOT
        cb.reset("req-1", "A4")  # Back to NORMAL
    """

    def get_level(self, req_id: str, agent_id: str) -> EscalationLevel:
        """Get current escalation level."""
        pass

    def record_failure(self, req_id: str, agent_id: str) -> EscalationLevel:
        """Record a failure and return new escalation level."""
        pass

    def reset(self, req_id: str, agent_id: str) -> None:
        """Reset escalation state on success."""
        pass

    def cleanup(self, req_id: str) -> None:
        """Clean up all states for a requirement."""
        pass


def get_circuit_breaker() -> CircuitBreaker:
    """Get or create module-level circuit breaker instance."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
# FEW-SHOT EXAMPLES (few_shot_examples.py)
# ══════════════════════════════════════════════════════════════════════════════

def get_few_shot_examples(
    agent_id: str,
    task_type: str = None,
    count: int = 3
) -> list:
    """Get few-shot examples for an agent.

    Args:
        agent_id: Agent identifier (e.g., 'A4', 'A9')
        task_type: Task type (e.g., 'api_schema', 'code_generation')
        count: Number of examples to return (default 3)

    Returns:
        List of example dicts with 'requirement', 'output', etc.

    Example:
        examples = get_few_shot_examples("A4", "api_schema", count=3)
        # Returns 3 API schema examples for spec writer
    """
    pass


def inject_few_shot_into_context(
    context: dict,
    agent_id: str,
    task_type: str = None
) -> dict:
    """Inject few-shot examples into agent execution context.

    Args:
        context: Agent execution context dict
        agent_id: Agent identifier
        task_type: Task type (optional)

    Returns:
        Updated context with 'few_shot_examples' key

    Example:
        context = {"task": "design_api"}
        context = inject_few_shot_into_context(context, "A4", "api_schema")
        # context["few_shot_examples"] now contains 3 examples
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# MODEL SELECTOR (model_selector.py)
# ══════════════════════════════════════════════════════════════════════════════

class ModelSelector:
    """Select model configuration based on escalation level.

    Example:
        selector = ModelSelector()
        config = selector.select_model_by_tier(ModelTier.STRONG)
        # Returns: {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", ...}
    """

    def select_model_by_tier(self, tier: ModelTier) -> dict:
        """Select model config for a given tier.

        Returns dict with: provider, model, temperature, max_tokens, cost_tier
        """
        pass

    def select_model_for_escalation(self, failure_count: int) -> dict:
        """Select model based on failure count."""
        pass

    def record_switch(self, from_model: str, to_model: str) -> None:
        """Record a model switch for metrics."""
        pass

    def get_switch_metrics(self) -> dict:
        """Get model switch statistics."""
        pass


def get_model_selector() -> ModelSelector:
    """Get or create module-level model selector instance."""
    pass


def override_model_in_context(
    context: dict,
    failure_count: int
) -> dict:
    """Inject model override into agent execution context.

    Args:
        context: Agent execution context
        failure_count: Number of consecutive failures

    Returns:
        Updated context with 'model_config' key

    Example:
        context = {}
        context = override_model_in_context(context, failure_count=1)
        # context["model_config"] now has Sonnet settings
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# HUMAN ESCALATION (human_escalation.py)
# ══════════════════════════════════════════════════════════════════════════════

class HumanEscalation:
    """Handle human escalation via Feishu webhook.

    Configuration:
        Set FEISHU_WEBHOOK_URL environment variable

    Example:
        escalation = HumanEscalation()
        result = await escalation.request_human_help(
            req_id="req-1",
            agent_id="A9",
            error_message="Failed to generate code",
            context_summary="Python backend"
        )
    """

    def __init__(self, webhook_url: str = None) -> None:
        """Initialize with Feishu webhook URL.

        If webhook_url is None, reads from FEISHU_WEBHOOK_URL env var.
        """
        pass

    async def request_human_help(
        self,
        req_id: str,
        agent_id: str,
        error_message: str,
        context_summary: str = ""
    ) -> bool:
        """Request human intervention via Feishu notification.

        Args:
            req_id: Requirement ID
            agent_id: Agent identifier
            error_message: Error or failure reason
            context_summary: Optional context information

        Returns:
            True if notification sent successfully
        """
        pass

    def build_test_card(self) -> dict:
        """Build a test card for webhook validation."""
        pass


def get_human_escalation() -> HumanEscalation:
    """Get or create module-level human escalation instance."""
    pass


async def escalate_to_human(
    req_id: str,
    agent_id: str,
    error_message: str,
    context_summary: str = ""
) -> bool:
    """Convenience function to escalate to human via Feishu.

    Example:
        await escalate_to_human(
            req_id="req-1",
            agent_id="A9",
            error_message="Code generation failed"
        )
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# METRICS (metrics.py)
# ══════════════════════════════════════════════════════════════════════════════

class CircuitBreakerMetrics:
    """In-memory metrics collection for circuit breaker.

    Tracks:
        - Escalations by (agent_id, level)
        - Human requests by agent_id
        - Model switches by (from_model, to_model)
        - Current failure counts by (req_id, agent_id)

    Example:
        metrics = get_metrics()
        metrics.increment_escalation("A9", "FEW_SHOT")
        metrics.increment_human_request("A9")
        data = metrics.to_dict()  # Export for monitoring
    """

    def increment_escalation(self, agent_id: str, level: str) -> None:
        """Increment escalation counter."""
        pass

    def increment_human_request(self, agent_id: str) -> None:
        """Increment human escalation request counter."""
        pass

    def increment_model_switch(self, from_model: str, to_model: str) -> None:
        """Increment model switch counter."""
        pass

    def set_failure_count(self, req_id: str, agent_id: str, count: int) -> None:
        """Set current failure count gauge."""
        pass

    def get_escalation_count(
        self,
        agent_id: str = None,
        level: str = None
    ) -> int:
        """Get escalation count with optional filtering."""
        pass

    def get_human_request_count(self, agent_id: str = None) -> int:
        """Get human request count with optional filtering."""
        pass

    def get_model_switch_count(
        self,
        from_model: str = None,
        to_model: str = None
    ) -> int:
        """Get model switch count with optional filtering."""
        pass

    def to_dict(self) -> dict:
        """Export metrics as dictionary."""
        pass

    def reset(self) -> None:
        """Reset all metrics (useful for testing)."""
        pass


def get_metrics() -> CircuitBreakerMetrics:
    """Get or create module-level metrics instance."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
# AGENT INVOKER (agent_invoker.py)
# ══════════════════════════════════════════════════════════════════════════════

class AgentInvoker:
    """Orchestrate agent invocation with circuit breaker escalation.

    Automatically escalates agents through:
        1. Few-shot example injection
        2. Strong model switching
        3. Human escalation

    Example:
        invoker = get_agent_invoker()

        async def my_agent(req_id, agent_id, context):
            # Agent implementation
            return {"result": "..."}

        result = await invoker.invoke_with_escalation(
            agent_func=my_agent,
            req_id="req-12345",
            agent_id="A9",
            context={"task": "generate_code"},
            task_type="code_generation"
        )
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker = None,
        max_retries: int = 3
    ) -> None:
        """Initialize agent invoker.

        Args:
            circuit_breaker: Circuit breaker instance (uses default if None)
            max_retries: Maximum number of retry attempts
        """
        pass

    async def invoke_with_escalation(
        self,
        agent_func,
        req_id: str,
        agent_id: str,
        context: dict,
        task_type: str = None
    ):
        """Invoke agent with automatic escalation on failure.

        Escalation strategy:
            1. FEW_SHOT (1st failure): Inject few-shot examples
            2. STRONG_MODEL (2nd failure): Switch to stronger model
            3. HUMAN (3rd failure): Request human intervention

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
        pass


def get_agent_invoker() -> AgentInvoker:
    """Get or create module-level agent invoker instance."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
# QUICK START EXAMPLES
# ══════════════════════════════════════════════════════════════════════════════

"""
1. BASIC AGENT INVOCATION WITH ESCALATION

    from circuit_breaker import get_agent_invoker

    invoker = get_agent_invoker()

    async def my_agent(req_id, agent_id, context):
        # Your agent logic
        return {"success": True}

    result = await invoker.invoke_with_escalation(
        agent_func=my_agent,
        req_id="req-123",
        agent_id="A9",
        context={"data": "..."},
        task_type="code_generation"
    )


2. MANUAL ESCALATION CONTROL

    from circuit_breaker import (
        get_circuit_breaker,
        get_model_selector,
        inject_few_shot_into_context
    )

    cb = get_circuit_breaker()
    selector = get_model_selector()

    # Check escalation level
    level = cb.get_level("req-1", "A4")

    # Apply few-shot if needed
    if level == EscalationLevel.FEW_SHOT:
        context = inject_few_shot_into_context(context, "A4", "api_schema")

    # Get model config
    model_config = selector.select_model_for_escalation(failure_count)

    # Reset on success
    cb.reset("req-1", "A4")


3. MONITORING & METRICS

    from circuit_breaker import get_metrics

    metrics = get_metrics()

    # Export metrics for Prometheus
    data = metrics.to_dict()

    # Query specific metrics
    escalations = metrics.get_escalation_count("A9", "FEW_SHOT")
    human_requests = metrics.get_human_request_count()

    # Monitor model upgrades
    switch_cost = metrics.get_model_switch_count("deepseek-v3", "sonnet")


4. CLEANUP ON REQUIREMENT COMPLETION

    from circuit_breaker import get_circuit_breaker

    cb = get_circuit_breaker()

    # Free up memory after requirement completes
    cb.cleanup("req-123")


5. TESTING

    from circuit_breaker import CircuitBreaker, EscalationLevel

    cb = CircuitBreaker()

    # Simulate failure sequence
    level1 = cb.record_failure("req-1", "A4")
    assert level1 == EscalationLevel.FEW_SHOT

    level2 = cb.record_failure("req-1", "A4")
    assert level2 == EscalationLevel.STRONG_MODEL

    # Reset
    cb.reset("req-1", "A4")
    assert cb.get_level("req-1", "A4") == EscalationLevel.NORMAL
"""


if __name__ == "__main__":
    print(__doc__)
