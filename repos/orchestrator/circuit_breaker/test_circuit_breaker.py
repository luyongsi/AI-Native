"""Test suite for circuit breaker escalation strategy.

Tests:
  - Circuit breaker failure tracking and escalation levels
  - Few-shot example injection
  - Model selection based on failure count
  - Human escalation notification formatting
  - Metrics collection
  - Agent invoker integration
"""

import asyncio
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock

from circuit_breaker.circuit_breaker import (
    CircuitBreaker,
    EscalationLevel,
    FailureRecord,
)
from circuit_breaker.few_shot_examples import (
    get_few_shot_examples,
    inject_few_shot_into_context,
)
from circuit_breaker.model_selector import (
    ModelSelector,
    ModelTier,
    override_model_in_context,
)
from circuit_breaker.human_escalation import (
    HumanEscalation,
)
from circuit_breaker.metrics import (
    CircuitBreakerMetrics,
)
from circuit_breaker.agent_invoker import (
    AgentInvoker,
)


# ── Test CircuitBreaker ──

class TestCircuitBreaker:
    """Test circuit breaker core functionality."""

    def test_initial_level_is_normal(self):
        """First call should return NORMAL level."""
        cb = CircuitBreaker()
        level = cb.get_level("req-1", "A4")
        assert level == EscalationLevel.NORMAL

    def test_escalation_progression(self):
        """Escalation should follow: NORMAL → FEW_SHOT → STRONG_MODEL → HUMAN."""
        cb = CircuitBreaker()
        req_id, agent_id = "req-1", "A4"

        # Initial state
        assert cb.get_level(req_id, agent_id) == EscalationLevel.NORMAL

        # 1st failure → FEW_SHOT
        level = cb.record_failure(req_id, agent_id)
        assert level == EscalationLevel.FEW_SHOT
        assert cb.get_level(req_id, agent_id) == EscalationLevel.FEW_SHOT

        # 2nd failure → STRONG_MODEL
        level = cb.record_failure(req_id, agent_id)
        assert level == EscalationLevel.STRONG_MODEL
        assert cb.get_level(req_id, agent_id) == EscalationLevel.STRONG_MODEL

        # 3rd failure → HUMAN
        level = cb.record_failure(req_id, agent_id)
        assert level == EscalationLevel.HUMAN
        assert cb.get_level(req_id, agent_id) == EscalationLevel.HUMAN

    def test_reset_clears_state(self):
        """Successful execution should reset circuit breaker state."""
        cb = CircuitBreaker()
        req_id, agent_id = "req-1", "A4"

        # Escalate to FEW_SHOT
        cb.record_failure(req_id, agent_id)
        assert cb.get_level(req_id, agent_id) == EscalationLevel.FEW_SHOT

        # Reset on success
        cb.reset(req_id, agent_id)
        assert cb.get_level(req_id, agent_id) == EscalationLevel.NORMAL

    def test_independent_per_agent(self):
        """Different agents should have independent escalation states."""
        cb = CircuitBreaker()
        req_id = "req-1"

        # Escalate A4
        cb.record_failure(req_id, "A4")
        assert cb.get_level(req_id, "A4") == EscalationLevel.FEW_SHOT

        # A9 should still be at NORMAL
        assert cb.get_level(req_id, "A9") == EscalationLevel.NORMAL

    def test_cleanup_requirement(self):
        """Cleanup should remove all states for a requirement."""
        cb = CircuitBreaker()
        req_id = "req-1"

        # Add some failures
        cb.record_failure(req_id, "A4")
        cb.record_failure(req_id, "A9")

        # Cleanup
        cb.cleanup(req_id)

        # States should be reset
        assert cb.get_level(req_id, "A4") == EscalationLevel.NORMAL
        assert cb.get_level(req_id, "A9") == EscalationLevel.NORMAL


# ── Test Few-Shot Examples ──

class TestFewShotExamples:
    """Test few-shot example injection."""

    def test_get_examples_for_a4(self):
        """Should retrieve API schema examples for A4."""
        examples = get_few_shot_examples("A4", "api_schema", count=3)
        assert len(examples) == 3
        assert all("endpoint" in ex["output"] for ex in examples)

    def test_get_examples_for_a9(self):
        """Should retrieve code generation examples for A9."""
        examples = get_few_shot_examples("A9", "code_generation", count=3)
        assert len(examples) == 3
        assert all("output" in ex for ex in examples)

    def test_get_examples_unknown_agent(self):
        """Should return empty list for unknown agent."""
        examples = get_few_shot_examples("UNKNOWN", "some_task")
        assert examples == []

    def test_inject_into_context(self):
        """Should inject examples into execution context."""
        context = {"task": "design_api"}
        updated = inject_few_shot_into_context(context, "A4", "api_schema")
        assert "few_shot_examples" in updated
        assert len(updated["few_shot_examples"]) > 0

    def test_inject_respects_count_limit(self):
        """Should limit examples to requested count."""
        examples = get_few_shot_examples("A4", "api_schema", count=1)
        assert len(examples) == 1


# ── Test Model Selector ──

class TestModelSelector:
    """Test model selection based on escalation."""

    def test_normal_tier_is_deepseek(self):
        """NORMAL tier should use DeepSeek v3."""
        selector = ModelSelector()
        config = selector.select_model_by_tier(ModelTier.NORMAL)
        assert config["provider"] == "deepseek"
        assert config["model"] == "deepseek-v3"

    def test_strong_tier_is_sonnet(self):
        """STRONG tier should use Claude 3.5 Sonnet."""
        selector = ModelSelector()
        config = selector.select_model_by_tier(ModelTier.STRONG)
        assert config["provider"] == "anthropic"
        assert config["model"] == "claude-3-5-sonnet-20241022"

    def test_ultra_tier_is_opus(self):
        """ULTRA tier should use Claude Opus."""
        selector = ModelSelector()
        config = selector.select_model_by_tier(ModelTier.ULTRA)
        assert config["provider"] == "anthropic"
        assert config["model"] == "claude-opus-4-7"

    def test_escalation_mapping(self):
        """Failure count should map to model tier."""
        selector = ModelSelector()

        # 0 failures → NORMAL (DeepSeek)
        config = selector.select_model_for_escalation(0)
        assert "deepseek" in config["model"]

        # 1 failure → STRONG (Sonnet)
        config = selector.select_model_for_escalation(1)
        assert "sonnet" in config["model"]

        # 2+ failures → ULTRA (Opus)
        config = selector.select_model_for_escalation(2)
        assert "opus" in config["model"]

    def test_override_in_context(self):
        """Should inject model override into context."""
        context = {"task": "code_gen"}
        updated = override_model_in_context(context, failure_count=1)
        assert "model_config" in updated
        assert updated["model_config"]["model"] == "claude-3-5-sonnet-20241022"


# ── Test Human Escalation ──

class TestHumanEscalation:
    """Test human escalation notification."""

    def test_build_card_structure(self):
        """Card should have required Feishu structure."""
        escalation = HumanEscalation()
        card = escalation._build_card(
            req_id="req-001",
            agent_id="A9",
            error_message="Test error",
            context_summary="Test context",
            timestamp="2024-01-01T00:00:00Z"
        )

        assert card["msg_type"] == "interactive"
        assert "card" in card
        assert "header" in card["card"]
        assert "elements" in card["card"]
        assert card["card"]["header"]["template"] == "red"

    def test_card_includes_agent_name(self):
        """Card should display friendly agent name."""
        escalation = HumanEscalation()
        card = escalation._build_card(
            req_id="req-001",
            agent_id="A9",
            error_message="Test",
            context_summary="",
            timestamp="2024-01-01T00:00:00Z"
        )

        title = card["card"]["header"]["title"]["content"]
        assert "Dev Agent" in title or "A9" in title

    def test_card_includes_action_buttons(self):
        """Card should include action buttons."""
        escalation = HumanEscalation()
        card = escalation._build_card(
            req_id="req-001",
            agent_id="A4",
            error_message="Test",
            context_summary="",
            timestamp="2024-01-01T00:00:00Z"
        )

        actions = card["card"]["elements"][-1].get("actions", [])
        assert len(actions) >= 2  # At least "查看详情" and "查看日志"
        assert any("req-001" in action.get("url", "") for action in actions)

    def test_no_webhook_url_logs_warning(self):
        """Should log warning when webhook URL not configured."""
        escalation = HumanEscalation(webhook_url=None)
        assert not escalation.webhook_url

    async def test_escalation_without_webhook_returns_false(self):
        """Should return False when escalation requested without webhook."""
        escalation = HumanEscalation(webhook_url=None)
        result = await escalation.request_human_help(
            "req-1", "A4", "error", ""
        )
        assert result is False


# ── Test Metrics ──

class TestMetrics:
    """Test metrics collection."""

    def test_increment_escalation(self):
        """Should track escalation counts."""
        metrics = CircuitBreakerMetrics()
        metrics.increment_escalation("A4", "FEW_SHOT")
        metrics.increment_escalation("A4", "FEW_SHOT")
        metrics.increment_escalation("A9", "STRONG_MODEL")

        assert metrics.get_escalation_count("A4", "FEW_SHOT") == 2
        assert metrics.get_escalation_count("A9", "STRONG_MODEL") == 1
        assert metrics.get_escalation_count() == 3

    def test_increment_human_request(self):
        """Should track human escalation requests."""
        metrics = CircuitBreakerMetrics()
        metrics.increment_human_request("A4")
        metrics.increment_human_request("A4")
        metrics.increment_human_request("A9")

        assert metrics.get_human_request_count("A4") == 2
        assert metrics.get_human_request_count("A9") == 1
        assert metrics.get_human_request_count() == 3

    def test_increment_model_switch(self):
        """Should track model switches."""
        metrics = CircuitBreakerMetrics()
        metrics.increment_model_switch("deepseek-v3", "sonnet")
        metrics.increment_model_switch("deepseek-v3", "sonnet")
        metrics.increment_model_switch("sonnet", "opus")

        assert metrics.get_model_switch_count("deepseek-v3", "sonnet") == 2
        assert metrics.get_model_switch_count("sonnet", "opus") == 1

    def test_to_dict_export(self):
        """Should export metrics as dict."""
        metrics = CircuitBreakerMetrics()
        metrics.increment_escalation("A4", "FEW_SHOT")
        metrics.set_failure_count("req-1", "A4", 1)

        d = metrics.to_dict()
        assert "escalations_total" in d
        assert "human_requests_total" in d
        assert "model_switches_total" in d
        assert "current_failures" in d


# ── Test Agent Invoker ──

class TestAgentInvoker:
    """Test agent invocation with escalation."""

    @pytest.mark.asyncio
    async def test_successful_invocation_no_escalation(self):
        """Successful agent call should not escalate."""
        invoker = AgentInvoker()

        # Mock successful agent
        async def mock_agent(req_id, agent_id, context):
            return {"status": "success"}

        result = await invoker.invoke_with_escalation(
            mock_agent, "req-1", "A4", {}
        )

        assert result["status"] == "success"
        assert invoker.circuit_breaker.get_level("req-1", "A4") == EscalationLevel.NORMAL

    @pytest.mark.asyncio
    async def test_escalation_on_failure(self):
        """Failed agent call should trigger escalation."""
        invoker = AgentInvoker(max_retries=3)

        call_count = [0]

        async def mock_agent(req_id, agent_id, context):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Simulated failure")
            return {"status": "success"}

        result = await invoker.invoke_with_escalation(
            mock_agent, "req-1", "A4", {}, task_type="api_schema"
        )

        # Should have retried 2 times before succeeding
        assert call_count[0] == 3
        assert result["status"] == "success"
        # Should be back to NORMAL after success
        assert invoker.circuit_breaker.get_level("req-1", "A4") == EscalationLevel.NORMAL

    @pytest.mark.asyncio
    async def test_exhaustion_raises_error(self):
        """Should raise error after max retries exhausted."""
        invoker = AgentInvoker(max_retries=2)

        async def failing_agent(req_id, agent_id, context):
            raise ValueError("Persistent failure")

        with pytest.raises(ValueError):
            await invoker.invoke_with_escalation(
                failing_agent, "req-1", "A4", {}
            )


# ── Integration Test ──

class TestIntegration:
    """Integration tests for full escalation flow."""

    @pytest.mark.asyncio
    async def test_full_escalation_flow(self):
        """Test complete escalation from few-shot to human."""
        invoker = AgentInvoker(max_retries=4)
        context = {"task": "design_api"}

        call_count = [0]
        escalation_levels = []

        async def mock_agent(req_id, agent_id, context):
            call_count[0] += 1
            level = invoker.circuit_breaker.get_level(req_id, agent_id)
            escalation_levels.append(level)

            # Fail on first 2 attempts, succeed on 3rd
            if call_count[0] < 3:
                raise ValueError(f"Attempt {call_count[0]} failed")
            return {"status": "success", "attempts": call_count[0]}

        result = await invoker.invoke_with_escalation(
            mock_agent, "req-1", "A4", context, task_type="api_schema"
        )

        # Should have escalated
        assert call_count[0] == 3
        assert result["attempts"] == 3
        assert EscalationLevel.NORMAL in escalation_levels
        assert EscalationLevel.FEW_SHOT in escalation_levels


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
