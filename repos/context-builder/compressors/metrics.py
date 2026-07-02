"""Prometheus metrics for context compression."""

import logging
from typing import Dict
from collections import defaultdict

logger = logging.getLogger(__name__)


class CompressionMetrics:
    """Prometheus-style metrics for compression stage."""

    def __init__(self):
        """Initialize compression metrics."""
        self.compress_ratio = 0.0  # Gauge: overall compression ratio
        self.compress_duration_ms = 0.0  # Histogram: compression duration
        self.code_compress_count = 0  # Counter: number of code compressions
        self.llm_compress_count = 0  # Counter: number of LLM compressions
        self.dedup_removed_count = 0  # Counter: duplicates removed
        self.token_reduction = 0  # Gauge: total tokens reduced
        self.errors_count = 0  # Counter: compression errors

        # Histograms (simplified as lists for tracking)
        self.duration_samples = []  # List of duration samples in ms
        self.ratio_samples = []  # List of compression ratio samples

    def record_compression(
        self,
        original_tokens: int,
        compressed_tokens: int,
        duration_ms: float,
        compress_type: str = 'unknown',
    ):
        """Record a compression operation.

        Args:
            original_tokens: Original token count
            compressed_tokens: Compressed token count
            duration_ms: Compression duration in milliseconds
            compress_type: Type of compression ('code', 'llm', etc.)
        """
        if original_tokens > 0:
            ratio = compressed_tokens / original_tokens
            self.compress_ratio = ratio
            self.ratio_samples.append(ratio)

        self.compress_duration_ms = duration_ms
        self.duration_samples.append(duration_ms)
        self.token_reduction = original_tokens - compressed_tokens

        if compress_type == 'code':
            self.code_compress_count += 1
        elif compress_type == 'llm':
            self.llm_compress_count += 1

        logger.debug(
            f"Compression recorded: {compress_type}, "
            f"tokens {original_tokens} -> {compressed_tokens} "
            f"(ratio: {ratio:.2%}), duration: {duration_ms:.1f}ms"
        )

    def record_deduplication(self, original_count: int, deduped_count: int):
        """Record deduplication operation.

        Args:
            original_count: Original candidate count
            deduped_count: After deduplication count
        """
        removed = original_count - deduped_count
        self.dedup_removed_count += removed
        logger.debug(f"Deduplication: {original_count} -> {deduped_count} (removed {removed})")

    def record_error(self, error: str):
        """Record a compression error.

        Args:
            error: Error description
        """
        self.errors_count += 1
        logger.error(f"Compression error recorded: {error}")

    def get_percentile(self, samples: list, percentile: float) -> float:
        """Calculate percentile from samples.

        Args:
            samples: List of samples
            percentile: Percentile (0.0-1.0)

        Returns:
            Percentile value
        """
        if not samples:
            return 0.0
        sorted_samples = sorted(samples)
        index = int(len(sorted_samples) * percentile)
        return sorted_samples[min(index, len(sorted_samples) - 1)]

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary (Prometheus format).

        Returns:
            Dictionary with all metrics
        """
        return {
            'context_builder_compress_ratio': self.compress_ratio,
            'context_builder_compress_duration_seconds': self.compress_duration_ms / 1000.0,
            'context_builder_compress_duration_ms': self.compress_duration_ms,
            'context_builder_compress_code_total': self.code_compress_count,
            'context_builder_compress_llm_total': self.llm_compress_count,
            'context_builder_compress_dedup_removed_total': self.dedup_removed_count,
            'context_builder_compress_token_reduction': self.token_reduction,
            'context_builder_compress_errors_total': self.errors_count,
            'context_builder_compress_duration_p50_ms': (
                self.get_percentile(self.duration_samples, 0.50) if self.duration_samples else 0.0
            ),
            'context_builder_compress_duration_p95_ms': (
                self.get_percentile(self.duration_samples, 0.95) if self.duration_samples else 0.0
            ),
            'context_builder_compress_duration_p99_ms': (
                self.get_percentile(self.duration_samples, 0.99) if self.duration_samples else 0.0
            ),
            'context_builder_compress_ratio_avg': (
                sum(self.ratio_samples) / len(self.ratio_samples) if self.ratio_samples else 0.0
            ),
        }

    def reset(self):
        """Reset all metrics."""
        self.compress_ratio = 0.0
        self.compress_duration_ms = 0.0
        self.code_compress_count = 0
        self.llm_compress_count = 0
        self.dedup_removed_count = 0
        self.token_reduction = 0
        self.errors_count = 0
        self.duration_samples = []
        self.ratio_samples = []
        logger.debug("Compression metrics reset")
