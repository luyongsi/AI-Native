"""Deduplication and token counting utilities for context compression."""

import logging
from typing import List, Dict, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def count_tokens(text: str) -> int:
    """Count tokens in text using simple estimation.

    Estimation: 1 token ≈ 4 characters (common approximation)

    Args:
        text: Text to count

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def jaccard_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between two texts.

    Uses word-level n-grams for similarity calculation.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score (0.0-1.0)
    """
    if not text1 or not text2:
        return 0.0

    # Simple word-level tokenization
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0


def sequence_similarity(text1: str, text2: str) -> float:
    """Calculate sequence similarity using difflib.

    More accurate than Jaccard for longer texts.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score (0.0-1.0)
    """
    if not text1 or not text2:
        return 0.0

    return SequenceMatcher(None, text1, text2).ratio()


def calculate_similarity(text1: str, text2: str, method: str = 'hybrid') -> float:
    """Calculate similarity between two texts.

    Args:
        text1: First text
        text2: Second text
        method: 'jaccard', 'sequence', or 'hybrid'

    Returns:
        Similarity score (0.0-1.0)
    """
    if method == 'jaccard':
        return jaccard_similarity(text1, text2)
    elif method == 'sequence':
        return sequence_similarity(text1, text2)
    elif method == 'hybrid':
        # Combine both methods
        j_sim = jaccard_similarity(text1, text2)
        s_sim = sequence_similarity(text1, text2)
        return (j_sim + s_sim) / 2
    else:
        return 0.0


class Deduplicator:
    """Deduplicate similar documents using similarity threshold."""

    def __init__(self, similarity_threshold: float = 0.90):
        """Initialize deduplicator.

        Args:
            similarity_threshold: Keep documents with similarity above this threshold
                                 (0.0-1.0, default 0.90 = 90%)
        """
        self.similarity_threshold = similarity_threshold

    def deduplicate(
        self,
        candidates: List[Dict],
        similarity_method: str = 'hybrid',
    ) -> List[Dict]:
        """Remove duplicate candidates based on content similarity.

        Strategy:
        - Group by similar content
        - Keep document with highest relevance_score
        - Preserve metadata (source, relevance_score)

        Args:
            candidates: List of candidate dictionaries with 'content' and 'relevance' keys
            similarity_method: Method for similarity calculation

        Returns:
            Deduplicated list of candidates
        """
        if not candidates:
            return []

        kept = []
        skipped_dups = []

        for candidate in candidates:
            is_duplicate = False

            for kept_candidate in kept:
                similarity = calculate_similarity(
                    candidate.get('content', ''),
                    kept_candidate.get('content', ''),
                    method=similarity_method,
                )

                if similarity >= self.similarity_threshold:
                    is_duplicate = True

                    # Keep candidate with higher relevance
                    candidate_relevance = candidate.get('relevance', 0)
                    kept_relevance = kept_candidate.get('relevance', 0)

                    if candidate_relevance > kept_relevance:
                        # Replace with higher relevance candidate
                        kept_candidate['relevance'] = candidate_relevance
                        kept_candidate['source'] = candidate.get('source', kept_candidate.get('source'))
                        logger.debug(
                            f"Dedup: replaced with higher relevance candidate "
                            f"(similarity: {similarity:.2%})"
                        )
                    else:
                        logger.debug(
                            f"Dedup: skipped duplicate "
                            f"(similarity: {similarity:.2%})"
                        )

                    skipped_dups.append(candidate)
                    break

            if not is_duplicate:
                kept.append(candidate)

        logger.info(
            f"Deduplication: {len(candidates)} -> {len(kept)} candidates "
            f"(removed {len(skipped_dups)} duplicates, threshold: {self.similarity_threshold:.0%})"
        )

        return kept

    def get_dedup_stats(self) -> Dict:
        """Get deduplication statistics.

        Returns:
            Dictionary with dedup stats
        """
        return {
            'similarity_threshold': self.similarity_threshold,
            'method': 'hybrid similarity matching',
        }


def deduplicate_candidates(
    candidates: List[Dict],
    similarity_threshold: float = 0.90,
) -> Tuple[List[Dict], int]:
    """Convenience function to deduplicate candidates.

    Args:
        candidates: List of candidates
        similarity_threshold: Similarity threshold (0.0-1.0)

    Returns:
        (deduplicated_candidates, removed_count)
    """
    deduplicator = Deduplicator(similarity_threshold=similarity_threshold)
    deduped = deduplicator.deduplicate(candidates)
    removed = len(candidates) - len(deduped)
    return deduped, removed
