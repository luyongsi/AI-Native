"""
sampling.py — OpenTelemetry Sampling Strategies

Configures probabilistic sampling with parent-based decision propagation.
Supports environment-based sampling rates for dev, staging, and production.

Usage:
    from infra.observability.sampling import get_sampler

    sampler = get_sampler(environment="dev")  # 100% sampling
    tracer_provider = TracerProvider(sampler=sampler)
"""
import os
import logging
from typing import Optional

from opentelemetry.sdk.trace.sampling import (
    Sampler,
    ParentBased,
    TraceIdRatioBased,
    AlwaysOn,
)

logger = logging.getLogger(__name__)


def get_sampler(environment: str = "dev") -> Sampler:
    """
    Get sampling strategy based on environment.

    Args:
        environment: "dev", "staging", or "prod"

    Returns:
        Configured Sampler instance

    Sampling rates:
        - dev: 100% (all traces)
        - staging: 50% (reasonable overhead)
        - prod: 10% (minimal overhead for high-volume services)

    The ParentBased wrapper ensures:
        - If parent span is sampled, child is sampled
        - If parent span is not sampled, child is not sampled
        - For root spans, applies the environment-based ratio
    """
    # Read sampling rate from environment variable if set
    sampling_rate_str = os.environ.get("OTEL_TRACES_SAMPLER_ARG")
    if sampling_rate_str is not None:
        try:
            sampling_rate = float(sampling_rate_str)
            logger.info(f"Using sampling rate from env: {sampling_rate}")
            return ParentBased(root=TraceIdRatioBased(sampling_rate))
        except ValueError:
            logger.warning(f"Invalid OTEL_TRACES_SAMPLER_ARG: {sampling_rate_str}, using default")

    # Default sampling rates by environment
    sampling_rates = {
        "dev": 1.0,         # 100% — full debugging
        "staging": 0.5,     # 50% — balance visibility and overhead
        "prod": 0.1,        # 10% — minimal overhead
    }

    sampling_rate = sampling_rates.get(environment, 1.0)
    logger.info(f"Using sampling rate for {environment}: {sampling_rate}")

    # ParentBased: respect parent's decision; for root spans, use ratio-based
    return ParentBased(root=TraceIdRatioBased(sampling_rate))


def get_always_on_sampler() -> Sampler:
    """
    Get a sampler that always creates spans.

    Useful for critical paths (authentication, errors, high-value operations).
    Use sparingly to avoid trace explosion.
    """
    return AlwaysOn()


def get_error_sampler() -> Sampler:
    """
    Get a sampler for error spans.

    Always samples error traces (100%) to ensure observability of failures.
    """
    return AlwaysOn()
