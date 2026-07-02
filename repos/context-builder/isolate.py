"""ContextIsolate: monitor fill rate and enforce isolation thresholds.

Fill rate = tokens_used / max_tokens

Thresholds:
  - > 50% -> warning logged
  - > 75% -> force compact (triggers aggressive compression)
"""

import logging
from typing import List, Optional

from context_item import ContextItem

logger = logging.getLogger(__name__)


class FillRateWarning(Exception):
    """Raised when fill rate exceeds warning threshold."""
    pass


class FillRateCritical(Exception):
    """Raised when fill rate exceeds critical threshold and compaction fails."""
    pass


class ContextIsolate:
    """Context isolation guard.

    Monitors token fill rate and enforces compaction when thresholds
    are exceeded.
    """

    def __init__(self,
                 warning_threshold: float = 0.50,
                 critical_threshold: float = 0.75):
        """
        Args:
            warning_threshold: Fill rate at which to log a warning (0.0 - 1.0)
            critical_threshold: Fill rate at which to force compaction (0.0 - 1.0)
        """
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self._warning_count = 0
        self._critical_count = 0

    def check(self, items: List[ContextItem], max_tokens: int) -> float:
        """Check fill rate and take action if needed.

        Args:
            items: Context items (position already assigned)
            max_tokens: Token budget

        Returns:
            Current fill rate (0.0 - 1.0+)
        """
        active_items = [it for it in items if it.position != 'discard']
        tokens_used = sum(it.tokens for it in active_items)
        fill_rate = tokens_used / max_tokens if max_tokens > 0 else 0.0

        if fill_rate > self.critical_threshold:
            self._critical_count += 1
            logger.warning(
                f"ContextIsolate: Fill rate {fill_rate:.1%} exceeds CRITICAL "
                f"threshold {self.critical_threshold:.1%}. "
                f"Tokens: {tokens_used}/{max_tokens}. Force compact required."
            )
            # Could raise FillRateCritical if caller wants to abort

        elif fill_rate > self.warning_threshold:
            self._warning_count += 1
            logger.warning(
                f"ContextIsolate: Fill rate {fill_rate:.1%} exceeds WARNING "
                f"threshold {self.warning_threshold:.1%}. "
                f"Tokens: {tokens_used}/{max_tokens}."
            )

        return fill_rate

    def force_compact(self, items: List[ContextItem],
                      max_tokens: int) -> List[ContextItem]:
        """Aggressively compact context: promote best items to head,
        discard everything else to get under max_tokens.

        Returns:
            Compacted list (positions reassigned).
        """
        active = [it for it in items if it.position != 'discard']
        active.sort(key=lambda x: x.relevance, reverse=True)

        used = 0
        for item in active:
            if used + item.tokens <= max_tokens:
                item.position = 'head'
                used += item.tokens
            else:
                item.position = 'discard'

        return items

    @property
    def warning_count(self) -> int:
        return self._warning_count

    @property
    def critical_count(self) -> int:
        return self._critical_count
