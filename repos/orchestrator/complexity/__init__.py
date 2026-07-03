"""Five-defence-line classifier (d0-d4) per 04 §11.1.

Determines the complexity tier of a requirement to decide routing:
  d0 — trivial   (skip straight to DEVELOPMENT)
  d1 — simple    (standard pipe, no gate)
  d2 — moderate  (standard pipe + gates)
  d3 — complex   (standard pipe + gates + optional debate)
  d4 — extreme   (fast-track eligible, escalated models)
"""

from __future__ import annotations

import logging
import os
import sys
from enum import IntEnum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ComplexityTier(IntEnum):
    D0_TRIVIAL = 0
    D1_SIMPLE = 1
    D2_MODERATE = 2
    D3_COMPLEX = 3
    D4_EXTREME = 4


# ---------------------------------------------------------------------------
# LLM Provider lazy-initialization
# ---------------------------------------------------------------------------

_llm_provider: Optional[object] = None


def _get_llm_provider():
    """Return a lazily-initialized LLMProviderManager singleton.

    Tries to register at least one text-capable adapter (DeepSeek, then
    Qwen, then Anthropic) so the complexity classifier has something to
    call.  If no adapter can be initialised the function returns None and
    the classifier falls back to the heuristic tier.
    """
    global _llm_provider
    if _llm_provider is not None:
        return _llm_provider

    # Ensure llm_provider is importable (sibling repo).
    _llm_root = Path(__file__).resolve().parents[2] / "llm-provider"
    if str(_llm_root) not in sys.path:
        sys.path.insert(0, str(_llm_root))

    try:
        from llm_provider import (
            AnthropicAdapter,
            DeepSeekAdapter,
            GLMAdapter,
            LLMProviderManager,
            QwenAdapter,
        )
    except ImportError:
        logger.warning("llm_provider package not available; LLM classification disabled.")
        return None

    manager = LLMProviderManager()

    # Register whatever adapters we can based on available env vars.
    registered = False
    for adapter_cls, env_var, name in (
        (DeepSeekAdapter, "DEEPSEEK_API_KEY", "deepseek"),
        (QwenAdapter, "QWEN_API_KEY", "qwen"),
        (AnthropicAdapter, "ANTHROPIC_API_KEY", "anthropic"),
    ):
        if os.environ.get(env_var):
            try:
                manager.register(name, adapter_cls())
                registered = True
            except Exception as exc:
                logger.debug("Failed to register %s: %s", name, exc)

    if not registered:
        logger.warning(
            "No LLM provider API keys found (DEEPSEEK_API_KEY, QWEN_API_KEY, "
            "ANTHROPIC_API_KEY). LLM classification disabled; heuristic fallback active."
        )
        return None

    _llm_provider = manager
    return _llm_provider


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_requirement(req_id: str, message: str) -> ComplexityTier:
    """Heuristic complexity classifier.

    In production this would query the Complexity Prober.  Here we
    implement a lightweight keyword/pattern matching heuristic per
    04 §11.1 defence lines.
    """
    lower = message.lower()

    # d4 extreme markers
    if any(kw in lower for kw in
           ("emergency", "p0", "incident", "breach", "hotfix", "sev0", "sev1")):
        return ComplexityTier.D4_EXTREME

    # d3 complex markers
    if any(kw in lower for kw in
           ("multi-tenant", "distributed transaction", "eventual consistency",
            "caching strategy", "circuit breaker", "failover", "sharding",
            "multi-region")):
        return ComplexityTier.D3_COMPLEX

    # d2 moderate markers
    if any(kw in lower for kw in
           ("database migration", "api endpoint", "authentication",
            "authorization", "webhook", "middleware", "validation",
            "rate limit")):
        return ComplexityTier.D2_MODERATE

    # d1 simple markers
    if any(kw in lower for kw in
           ("crud", "form", "static page", "config", "env var", "logging",
            "health check", "status endpoint")):
        return ComplexityTier.D1_SIMPLE

    # d0 trivial markers
    if any(kw in lower for kw in
           ("typo", "spelling", "comment", "whitespace", "readme")):
        return ComplexityTier.D0_TRIVIAL

    # Default: moderate
    return ComplexityTier.D2_MODERATE


def is_fast_track(req_id: str, message: str) -> bool:
    """Return True when the requirement qualifies for fast-track processing."""
    return classify_requirement(req_id, message) >= ComplexityTier.D4_EXTREME


async def classify_requirement_llm(
    req_id: str,
    message: str,
    title: str = "",
) -> ComplexityTier:
    """LLM-augmented complexity classifier.

    Runs the keyword heuristic first as a fast pre-filter:
    - d0 (trivial) and d1 (simple) results are returned immediately — no
      LLM call is needed for these low-complexity tiers.
    - d2 (moderate), d3 (complex), and d4 (extreme) are re-evaluated by
      the LLM Provider for a more accurate classification.

    If the LLM call fails (no provider, network error, etc.) the heuristic
    result is returned as a safe fallback.
    """
    # Fast pre-filter via keyword heuristic.
    heuristic_tier = classify_requirement(req_id, message)
    if heuristic_tier <= ComplexityTier.D1_SIMPLE:
        logger.debug(
            "req=%s tier=%s (heuristic, no LLM needed)",
            req_id, heuristic_tier.name,
        )
        return heuristic_tier

    # For d2+ we attempt LLM-based refinement.
    provider = _get_llm_provider()
    if provider is None:
        logger.debug(
            "req=%s no LLM provider available, falling back to heuristic tier=%s",
            req_id, heuristic_tier.name,
        )
        return heuristic_tier

    prompt = (
        "Classify the complexity of this requirement on a scale of "
        "0 (trivial) to 4 (extreme).\n"
        "Title: {title}\n"
        "Description: {message}\n"
        "Reply with just the number.".format(
            title=title or "(none)",
            message=message,
        )
    )

    try:
        response = provider.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10,
            task_type="text",
        )
        raw = response.content.strip()
        # Extract the first integer from the response.
        tier_num = _parse_llm_tier(raw)
        tier = ComplexityTier(max(0, min(4, tier_num)))
        logger.info(
            "req=%s LLM classified as %s (heuristic was %s, raw=%r)",
            req_id, tier.name, heuristic_tier.name, raw,
        )
        return tier

    except Exception as exc:
        logger.warning(
            "req=%s LLM classification failed (%s), falling back to heuristic tier=%s",
            req_id, exc, heuristic_tier.name,
        )
        return heuristic_tier


def _parse_llm_tier(raw: str) -> int:
    """Extract the first integer from *raw*, defaulting to 2 on parse failure."""
    for char in raw:
        if char.isdigit():
            return int(char)
    logger.debug("Could not parse tier from LLM response: %r", raw)
    return 2  # safe default: moderate
