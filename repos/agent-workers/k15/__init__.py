"""
k15 sub-package — Change Propagation sub-modules.

Phase 2 (Current):
  - DependencyTraverser: Hardcoded agent dependency graph traversal.
  - EventDebouncer:      Groups events within a time window before processing.
  - ImpactRater:         Classifies change impact as breaking/major/minor/patch.

Phase 3 (Planned):
  - DependencyTraverser: Neo4j graph queries for real dependency traversal.
  - EventDebouncer:      Redis-backed persistent debounce queues.
  - ImpactRater:         ML-based impact scoring from historical change data.
"""

from k15.dependency_traverser import DependencyTraverser
from k15.event_debouncer import EventDebouncer
from k15.impact_rater import ImpactRater

__all__ = [
    "DependencyTraverser",
    "EventDebouncer",
    "ImpactRater",
]
