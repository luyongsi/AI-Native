"""Enhanced context orderer with relevance scoring and agent-specific strategies."""

import asyncio
import logging
import time
from typing import List, Dict, Optional, Tuple

from rankers.relevance_scorer import RelevanceScorer
from rankers.agent_strategy import AgentStrategy
from rankers.order_metrics import OrderMetrics

logger = logging.getLogger(__name__)


class ContextOrdererV2:
    """Advanced context orderer combining relevance scoring, agent strategies, and top-K selection.

    Pipeline:
        1. Calculate relevance scores (multi-factor)
        2. Apply agent-specific content type boosts
        3. Sort by adjusted relevance scores (descending)
        4. Apply top-K truncation (token budget aware)
        5. Record metrics and telemetry
    """

    def __init__(self):
        """Initialize advanced context orderer."""
        self.scorer = RelevanceScorer()
        self.strategy = AgentStrategy()
        self.metrics = OrderMetrics()

    async def order_candidates_async(
        self,
        candidates: List[Dict],
        agent_id: str,
        query_context: Optional[Dict] = None,
        max_tokens: int = 100000,
    ) -> Tuple[List[Dict], Dict]:
        """Order candidates by relevance with agent-specific optimization.

        Args:
            candidates: List of candidate dicts with 'content', 'similarity', etc.
            agent_id: Target agent ID (A1-A10)
            query_context: Optional context (dependencies, max_references, etc.)
            max_tokens: Token budget for final context

        Returns:
            (ordered_candidates, metrics_dict)
        """
        start_time = time.time()
        original_count = len(candidates)

        try:
            if not candidates:
                self.metrics.record_order(0, 0, 0.0, agent_id)
                return [], self.metrics.to_dict()

            # Step 1: Calculate relevance scores
            for candidate in candidates:
                if 'relevance_score' not in candidate:
                    score = self.scorer.calculate_score(candidate, query_context)
                    candidate['relevance_score'] = score

            # Step 2: Apply agent-specific strategy adjustments
            candidates = self.strategy.adjust_scores(candidates, agent_id)

            # Step 3: Sort by relevance (descending)
            candidates = sorted(
                candidates,
                key=lambda x: x.get('relevance_score', 0.0),
                reverse=True,
            )

            # Step 4: Apply top-K truncation
            context_limit = self.strategy.get_context_limit(agent_id)
            effective_limit = min(max_tokens, context_limit)
            top_k = self._apply_top_k(candidates, effective_limit)

            # Step 5: Record metrics
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_order(
                original_count,
                len(top_k),
                duration_ms,
                agent_id,
            )

            logger.info(
                f"ORDER stage complete: {original_count} candidates -> {len(top_k)} top-K "
                f"({len(top_k)/max(1, original_count)*100:.1f}%), "
                f"agent: {agent_id}, duration: {duration_ms:.1f}ms"
            )

            return top_k, self.metrics.to_dict()

        except Exception as e:
            logger.error(f"Async ordering failed: {e}")
            self.metrics.record_error(str(e), agent_id)
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_order(original_count, 0, duration_ms, agent_id)
            return [], self.metrics.to_dict()

    def order_candidates(
        self,
        candidates: List[Dict],
        agent_id: str,
        query_context: Optional[Dict] = None,
        max_tokens: int = 100000,
    ) -> Tuple[List[Dict], Dict]:
        """Synchronous wrapper for order_candidates_async.

        Args:
            candidates: List of candidate dicts
            agent_id: Target agent ID
            query_context: Optional context
            max_tokens: Token budget

        Returns:
            (ordered_candidates, metrics_dict)
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.order_candidates_async(
                    candidates,
                    agent_id,
                    query_context,
                    max_tokens,
                )
            )
        finally:
            loop.close()

    @staticmethod
    def _apply_top_k(candidates: List[Dict], max_tokens: int) -> List[Dict]:
        """Select top-K candidates respecting token budget.

        Args:
            candidates: Already sorted by relevance (descending)
            max_tokens: Token budget limit

        Returns:
            Subset of candidates within token budget
        """
        selected = []
        total_tokens = 0

        for candidate in candidates:
            tokens = candidate.get('token_count', 0)

            # Safety check: if single item exceeds budget, still include it
            if not selected and tokens > max_tokens:
                logger.warning(
                    f"Single candidate exceeds budget: "
                    f"{tokens} > {max_tokens}, including anyway"
                )
                selected.append(candidate)
                total_tokens += tokens
                continue

            # Normal case: check if adding this candidate stays within budget
            if total_tokens + tokens <= max_tokens:
                selected.append(candidate)
                total_tokens += tokens
            else:
                # Budget exceeded, stop selection
                break

        return selected

    def get_metrics(self) -> Dict:
        """Get ordering metrics.

        Returns:
            Metrics dictionary (Prometheus format)
        """
        return self.metrics.to_dict()

    def reset_metrics(self):
        """Reset metrics."""
        self.metrics.reset()

    @staticmethod
    def get_ordering_summary(candidates: List[Dict]) -> Dict:
        """Generate summary statistics for ordered candidates.

        Args:
            candidates: Ordered candidate list

        Returns:
            Summary with counts, scores, and distributions
        """
        if not candidates:
            return {
                'total': 0,
                'avg_score': 0.0,
                'min_score': 0.0,
                'max_score': 0.0,
                'by_content_type': {},
                'by_position': {},
            }

        scores = [c.get('relevance_score', 0.0) for c in candidates]
        content_types = {}
        positions = {}

        for candidate in candidates:
            ct = candidate.get('content_type', 'unknown')
            content_types[ct] = content_types.get(ct, 0) + 1

            pos = candidate.get('position', 'unknown')
            positions[pos] = positions.get(pos, 0) + 1

        return {
            'total': len(candidates),
            'avg_score': sum(scores) / len(scores) if scores else 0.0,
            'min_score': min(scores) if scores else 0.0,
            'max_score': max(scores) if scores else 0.0,
            'by_content_type': content_types,
            'by_position': positions,
        }
