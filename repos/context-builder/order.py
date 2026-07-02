"""ContextOrderer: assign position (head/mid/tail/discard) to context items.

Strategy:
  - Top-K by relevance -> head (highest priority, most visible)
  - Next-M by relevance -> tail (important but not prime real estate)
  - Middle items -> mid (only if enough token budget remains)
  - Lowest relevance -> discard (excluded from final context)
"""

from typing import List, Tuple

from context_item import ContextItem


class ContextOrderer:
    """Order context items by relevance into head/mid/tail positions."""

    def __init__(self,
                 head_token_budget: int = 2000,
                 tail_token_budget: int = 2000,
                 head_count: int = 3,
                 tail_count: int = 2,
                 min_relevance: float = 0.05):
        """
        Args:
            head_token_budget: Max tokens for head items
            tail_token_budget: Max tokens for tail items
            head_count: Max number of items in head
            tail_count: Max number of items in tail
            min_relevance: Minimum relevance score to include at all
        """
        self.head_token_budget = head_token_budget
        self.tail_token_budget = tail_token_budget
        self.head_count = head_count
        self.tail_count = tail_count
        self.min_relevance = min_relevance

    def order(self, items: List[ContextItem],
              max_tokens: int = 8000) -> List[ContextItem]:
        """Assign positions to items.

        Items already sorted by relevance descending.

        Returns:
            Same list with position field set on each item.
        """
        if not items:
            return items

        # Sort by relevance descending
        items.sort(key=lambda x: x.relevance, reverse=True)

        total_budget = max_tokens
        head_budget = min(self.head_token_budget, total_budget // 3)
        tail_budget = min(self.tail_token_budget, total_budget // 3)
        # mid gets whatever is left

        used_tokens = 0

        # --- Head ---
        head_assigned = 0
        for item in items:
            if head_assigned >= self.head_count:
                break
            if item.relevance < self.min_relevance:
                break
            if used_tokens + item.tokens <= total_budget:
                item.position = 'head'
                used_tokens += item.tokens
                head_assigned += 1
                head_budget -= item.tokens

        # --- Tail ---
        # Pick tail items from the remaining items (skip head items)
        tail_candidates = [it for it in items if it.position != 'head']
        tail_candidates.sort(key=lambda x: x.relevance, reverse=True)

        tail_tokens_used = 0
        tail_assigned = 0
        for item in tail_candidates:
            if tail_assigned >= self.tail_count:
                break
            if item.relevance < self.min_relevance:
                break
            if used_tokens + item.tokens <= total_budget:
                item.position = 'tail'
                used_tokens += item.tokens
                tail_tokens_used += item.tokens
                tail_assigned += 1
                tail_budget -= item.tokens

        # --- Mid ---
        # Remaining items get 'mid' if budget permits, else 'discard'
        for item in items:
            if item.position in ('head', 'tail'):
                continue
            if item.relevance < self.min_relevance:
                item.position = 'discard'
                continue
            if used_tokens + item.tokens <= total_budget:
                item.position = 'mid'
                used_tokens += item.tokens
            else:
                item.position = 'discard'

        return items

    @staticmethod
    def get_position_summary(items: List[ContextItem]) -> dict:
        """Return a summary of positions."""
        head = [it for it in items if it.position == 'head']
        mid = [it for it in items if it.position == 'mid']
        tail = [it for it in items if it.position == 'tail']
        discard = [it for it in items if it.position == 'discard']

        return {
            'head': {'count': len(head), 'tokens': sum(it.tokens for it in head)},
            'mid': {'count': len(mid), 'tokens': sum(it.tokens for it in mid)},
            'tail': {'count': len(tail), 'tokens': sum(it.tokens for it in tail)},
            'discard': {'count': len(discard), 'tokens': sum(it.tokens for it in discard)},
        }
