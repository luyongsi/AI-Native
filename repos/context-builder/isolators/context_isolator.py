"""ContextIsolator: determine if Agent execution needs isolation (worktree/container).

Main entry point for the ISOLATE stage in the Context Builder pipeline.
"""

import logging
import time
from typing import Dict, Any, Optional
from .risk_evaluator import RiskEvaluator

logger = logging.getLogger(__name__)


class ContextIsolator:
    """Determine and enforce Agent isolation requirements.

    Evaluates changes and decides whether to run Agent in:
    - NONE: No isolation (read-only operations)
    - WORKTREE: Git worktree isolation (code changes)
    - CONTAINER: Container isolation (risky operations)
    """

    def __init__(self, evaluator: Optional[RiskEvaluator] = None):
        """Initialize the context isolator.

        Args:
            evaluator: RiskEvaluator instance (created if not provided)
        """
        self.evaluator = evaluator or RiskEvaluator()
        self._decision_count = {'NONE': 0, 'WORKTREE': 0, 'CONTAINER': 0}
        self._total_duration = 0.0
        self._decision_samples = []

    async def determine_isolation(self, context: Dict[str, Any],
                                  agent_id: str) -> Dict[str, Any]:
        """Determine isolation mode for Agent execution.

        Args:
            context: Context dict with change information
            agent_id: Agent identifier (e.g., 'A1', 'agent-123')

        Returns:
            Dict with:
            - 'isolation_mode': 'NONE', 'WORKTREE', or 'CONTAINER'
            - 'risk_level': 'low', 'medium', 'high'
            - 'risk_details': Dict of detected risks
            - 'reasoning': str explaining decision
            - 'agent_id': Agent identifier
            - 'duration_ms': Decision time in milliseconds
        """
        start_time = time.time()

        try:
            # Evaluate risks
            evaluation = self.evaluator.evaluate(context)

            result = {
                'isolation_mode': evaluation['isolation_mode'],
                'risk_level': evaluation['risk_level'],
                'risk_details': evaluation['risks'],
                'reasoning': evaluation['reasoning'],
                'agent_id': agent_id,
            }

            # Record metrics
            duration_ms = (time.time() - start_time) * 1000
            result['duration_ms'] = round(duration_ms, 2)

            mode = result['isolation_mode']
            self._decision_count[mode] = self._decision_count.get(mode, 0) + 1
            self._total_duration += duration_ms
            self._decision_samples.append({
                'mode': mode,
                'duration_ms': duration_ms,
                'agent_id': agent_id,
                'risk_level': result['risk_level'],
            })

            # Keep only last 1000 samples for performance stats
            if len(self._decision_samples) > 1000:
                self._decision_samples = self._decision_samples[-1000:]

            logger.info(
                f"ContextIsolator: Agent {agent_id} -> {mode} "
                f"(risk={result['risk_level']}, {duration_ms:.1f}ms)"
            )

            return result

        except Exception as e:
            logger.error(f"ContextIsolator failed for agent {agent_id}: {e}")
            duration_ms = (time.time() - start_time) * 1000
            return {
                'isolation_mode': 'WORKTREE',  # safe default
                'risk_level': 'unknown',
                'risk_details': {},
                'reasoning': f"Evaluation failed: {str(e)}. Using safe default (WORKTREE).",
                'agent_id': agent_id,
                'duration_ms': round(duration_ms, 2),
                'error': str(e),
            }

    def get_metrics(self) -> Dict[str, Any]:
        """Return current decision metrics.

        Returns:
            Dict with decision counts and performance stats.
        """
        total_decisions = sum(self._decision_count.values())
        avg_duration = (self._total_duration / total_decisions
                        if total_decisions > 0 else 0)

        # Calculate P95 duration
        p95_duration = self._calculate_percentile(95)

        return {
            'total_decisions': total_decisions,
            'by_mode': self._decision_count,
            'average_duration_ms': round(avg_duration, 2),
            'p95_duration_ms': round(p95_duration, 2),
            'total_duration_ms': round(self._total_duration, 2),
        }

    def _calculate_percentile(self, percentile: int) -> float:
        """Calculate percentile of decision durations."""
        if not self._decision_samples:
            return 0.0

        durations = sorted([s['duration_ms'] for s in self._decision_samples])
        idx = int(len(durations) * (percentile / 100.0))
        return durations[min(idx, len(durations) - 1)]

    def reset_metrics(self):
        """Reset all metrics."""
        self._decision_count = {'NONE': 0, 'WORKTREE': 0, 'CONTAINER': 0}
        self._total_duration = 0.0
        self._decision_samples = []
