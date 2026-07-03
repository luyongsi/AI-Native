"""complexity_classifier Activity — classify a requirement's complexity tier.

Wraps the complexity.classify_requirement_llm() function as a Temporal
Activity so workflows can obtain the tier via the standard activity
lifecycle (retries, timeouts, heartbeats).
"""

from __future__ import annotations

import logging

from temporalio import activity

logger = logging.getLogger(__name__)


@activity.defn(name="complexity_classifier")
async def complexity_classifier(
    req_id: str,
    message: str,
    title: str = "",
) -> dict:
    """Classify the complexity tier of a requirement.

    Calls the LLM-augmented classifier which first runs a keyword
    heuristic and then refines d2+ tiers via the LLM Provider.

    Returns:
        dict with keys: req_id, tier (int 0-4), tier_name (str), method
        ("heuristic" or "llm"), and detail (optional extra context).
    """
    activity.logger.info(
        "complexity_classifier req=%s title=%r", req_id, title
    )

    # Import here to avoid circular imports at module level.
    from complexity import classify_requirement, classify_requirement_llm

    # Always run the LLM path first; classify_requirement_llm uses the
    # heuristic internally as a pre-filter, so we get both tiers back.
    try:
        tier = await classify_requirement_llm(
            req_id=req_id,
            message=message,
            title=title,
        )
    except Exception as exc:
        activity.logger.warning(
            "classify_requirement_llm failed (%s), falling back to heuristic only", exc
        )
        tier = classify_requirement(req_id, message)

    result = {
        "req_id": req_id,
        "tier": int(tier),
        "tier_name": tier.name,
        "ok": True,
    }
    activity.logger.info(
        "complexity_classifier result req=%s tier=%s", req_id, tier.name
    )
    return result
