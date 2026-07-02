"""Model selection and escalation strategy based on circuit breaker level.

Provides model tier selection:
  NORMAL: DeepSeek v3 (cost-optimized)
  STRONG_MODEL: Claude 3.5 Sonnet (balanced)
  HUMAN: Claude Opus (highest quality, last resort)
"""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ModelTier(Enum):
    """Available model tiers."""
    NORMAL = "normal"
    STRONG = "strong"
    ULTRA = "ultra"


# Model configuration per tier
MODEL_TIERS = {
    ModelTier.NORMAL: {
        "provider": "deepseek",
        "model": "deepseek-v3",
        "temperature": 0.3,
        "max_tokens": 4096,
        "cost_tier": "standard"
    },
    ModelTier.STRONG: {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "temperature": 0.2,
        "max_tokens": 4096,
        "cost_tier": "premium"
    },
    ModelTier.ULTRA: {
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "temperature": 0.1,
        "max_tokens": 4096,
        "cost_tier": "ultra"
    }
}


class ModelSelector:
    """Select model configuration based on escalation level."""

    def __init__(self):
        """Initialize model selector."""
        self._model_switches = {}  # Track model switches for metrics

    def select_model_by_tier(self, tier: ModelTier) -> dict:
        """Select model configuration for a given tier.

        Args:
            tier: ModelTier enum value

        Returns:
            Dict with model config (provider, model, temperature, max_tokens, cost_tier)
        """
        if tier not in MODEL_TIERS:
            logger.warning(f"Unknown model tier {tier}, defaulting to NORMAL")
            tier = ModelTier.NORMAL

        config = MODEL_TIERS[tier].copy()
        logger.debug(f"Selected model tier={tier.value} model={config['model']}")
        return config

    def select_model_for_escalation(self, failure_count: int) -> dict:
        """Select model based on failure count (circuit breaker integration).

        Args:
            failure_count: Number of consecutive failures

        Returns:
            Dict with model config
        """
        if failure_count == 0:
            tier = ModelTier.NORMAL
        elif failure_count == 1:
            tier = ModelTier.STRONG
        else:  # failure_count >= 2
            tier = ModelTier.ULTRA

        config = self.select_model_by_tier(tier)
        logger.info(
            f"Selected model for failure_count={failure_count} "
            f"tier={tier.value} model={config['model']}"
        )
        return config

    def record_switch(self, from_model: str, to_model: str) -> None:
        """Record a model switch for metrics/monitoring.

        Args:
            from_model: Previous model
            to_model: New model
        """
        key = f"{from_model}→{to_model}"
        self._model_switches[key] = self._model_switches.get(key, 0) + 1
        logger.info(f"Model switch recorded: {from_model} → {to_model}")

    def get_switch_metrics(self) -> dict:
        """Get model switch statistics.

        Returns:
            Dict with switch counts
        """
        return self._model_switches.copy()


# Module-level singleton
_selector: ModelSelector | None = None


def get_model_selector() -> ModelSelector:
    """Get or create the module-level model selector instance."""
    global _selector
    if _selector is None:
        _selector = ModelSelector()
    return _selector


def override_model_in_context(context: dict, failure_count: int) -> dict:
    """Inject model override into agent execution context.

    Args:
        context: Agent execution context
        failure_count: Number of consecutive failures

    Returns:
        Updated context with 'model_config' key
    """
    selector = get_model_selector()
    model_config = selector.select_model_for_escalation(failure_count)
    context["model_config"] = model_config
    logger.info(
        f"Overriding model in context: failure_count={failure_count} "
        f"model={model_config['model']}"
    )
    return context
