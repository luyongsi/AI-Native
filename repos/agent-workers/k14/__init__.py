"""
k14 sub-package — Knowledge Keeper sub-modules.

Phase 2 (Current):
  - ArtifactVectorizer: Simulated embedding generation + pgvector storage.
  - KnowledgeGraphUpdater: Hardcoded graph relationships (no Neo4j).
  - ExpirationMarker: Stale content detection + expiration + conflict detection.

Phase 3 (Planned):
  - ArtifactVectorizer: Real embedding model (e.g., text-embedding-3-large).
  - KnowledgeGraphUpdater: Neo4j integration for live graph traversal.
  - ExpirationMarker: Automated archival pipeline with notification hooks.
"""

from k14.artifact_vectorizer import ArtifactVectorizer
from k14.knowledge_graph_updater import KnowledgeGraphUpdater
from k14.expiration_marker import ExpirationMarker

__all__ = [
    "ArtifactVectorizer",
    "KnowledgeGraphUpdater",
    "ExpirationMarker",
]
