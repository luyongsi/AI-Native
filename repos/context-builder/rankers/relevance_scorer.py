"""Relevance scorer with multi-factor weighted scoring."""

import math
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RelevanceScorer:
    """Multi-factor relevance scorer for context candidates.

    Combines semantic similarity, time freshness, reference frequency,
    and dependency scores into a composite relevance score.

    Weights:
        - Semantic similarity: 0.4 (primary factor)
        - Time freshness: 0.2 (newer content preferred)
        - Reference frequency: 0.2 (popular content preferred)
        - Dependency score: 0.2 (explicit dependencies preferred)
    """

    # Weight configuration
    SEMANTIC_WEIGHT = 0.4
    TIME_WEIGHT = 0.2
    REFERENCE_WEIGHT = 0.2
    DEPENDENCY_WEIGHT = 0.2

    # Time freshness decay (half-life in days)
    TIME_DECAY_HALF_LIFE = 30

    def calculate_score(self, candidate: Dict, query_context: Optional[Dict] = None) -> float:
        """Calculate composite relevance score for a candidate.

        Args:
            candidate: Candidate dict with 'similarity', 'timestamp', 'references', etc.
            query_context: Optional context with 'dependencies', 'max_references', etc.

        Returns:
            Composite score between 0.0 and 1.0
        """
        semantic_sim = candidate.get('similarity', 0.0)
        semantic_sim = max(0.0, min(1.0, semantic_sim))  # Normalize to [0, 1]

        time_score = self._calculate_time_freshness(candidate)
        reference_score = self._calculate_reference_frequency(candidate, query_context)
        dependency_score = self._calculate_dependency_score(candidate, query_context)

        # Weighted composite
        final_score = (
            semantic_sim * self.SEMANTIC_WEIGHT +
            time_score * self.TIME_WEIGHT +
            reference_score * self.REFERENCE_WEIGHT +
            dependency_score * self.DEPENDENCY_WEIGHT
        )

        return max(0.0, min(1.0, final_score))

    def _calculate_time_freshness(self, candidate: Dict) -> float:
        """Calculate time freshness score using exponential decay.

        Formula: score = e^(-days / half_life)
        - At 0 days: score = 1.0
        - At half_life (30 days): score = 0.5
        - At 60 days: score = 0.25

        Args:
            candidate: Candidate with 'timestamp' (ISO string or datetime)

        Returns:
            Score between 0.0 and 1.0
        """
        timestamp = candidate.get('timestamp')
        if not timestamp:
            # No timestamp available, assume neutral freshness
            return 0.5

        try:
            # Parse timestamp if string
            if isinstance(timestamp, str):
                # Try ISO format
                if 'T' in timestamp:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                else:
                    # Assume Unix timestamp
                    dt = datetime.fromtimestamp(float(timestamp))
            else:
                dt = timestamp

            # Calculate days elapsed
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            elapsed = (now - dt).total_seconds() / (24 * 3600)  # Convert to days
            elapsed = max(0, elapsed)  # No negative age

            # Exponential decay: e^(-elapsed / half_life)
            decay_rate = elapsed / self.TIME_DECAY_HALF_LIFE
            score = math.exp(-decay_rate)

            return max(0.0, min(1.0, score))

        except (ValueError, TypeError) as e:
            logger.debug(f"Time freshness calculation failed: {e}")
            return 0.5

    def _calculate_reference_frequency(
        self,
        candidate: Dict,
        query_context: Optional[Dict] = None
    ) -> float:
        """Calculate normalized reference frequency score.

        If max_references is known, normalize to that.
        Otherwise, use raw count with saturation at 50 references.

        Args:
            candidate: Candidate with 'references' or 'reference_count'
            query_context: Optional context with 'max_references'

        Returns:
            Score between 0.0 and 1.0
        """
        ref_count = candidate.get('references') or candidate.get('reference_count', 0)

        if not ref_count:
            return 0.5  # Default for items with no reference info

        max_references = 50  # Default saturation point

        if query_context and 'max_references' in query_context:
            max_references = query_context['max_references']

        # Normalize with saturation
        score = min(1.0, ref_count / max(1, max_references))

        return score

    def _calculate_dependency_score(
        self,
        candidate: Dict,
        query_context: Optional[Dict] = None
    ) -> float:
        """Calculate dependency-based relevance score.

        - Direct dependency: 1.0 (explicit connection)
        - Transitive dependency: 0.7 (2+ hops)
        - No dependency: 0.5 (neutral)

        Args:
            candidate: Candidate with 'has_dependency', 'dependency_type', etc.
            query_context: Optional context with query dependencies

        Returns:
            Score between 0.0 and 1.0
        """
        # Check for explicit dependency
        has_dependency = candidate.get('has_dependency', False)
        if has_dependency:
            dependency_type = candidate.get('dependency_type', 'direct')
            if dependency_type == 'direct':
                return 1.0
            elif dependency_type == 'transitive':
                return 0.7
            else:
                return 0.6

        # Check if candidate is in query dependencies
        if query_context and 'dependencies' in query_context:
            query_deps = query_context.get('dependencies', [])
            candidate_id = candidate.get('id') or candidate.get('file')
            if candidate_id in query_deps:
                return 0.9

        # No dependency info
        return 0.5

    @staticmethod
    def batch_calculate_scores(
        candidates: list,
        query_context: Optional[Dict] = None
    ) -> list:
        """Calculate scores for multiple candidates.

        Args:
            candidates: List of candidate dicts
            query_context: Optional shared context

        Returns:
            Same list with 'relevance_score' added to each
        """
        scorer = RelevanceScorer()

        for candidate in candidates:
            if 'relevance_score' not in candidate:
                score = scorer.calculate_score(candidate, query_context)
                candidate['relevance_score'] = score

        return candidates
