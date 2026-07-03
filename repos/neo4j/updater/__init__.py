"""Phase 6C: Neo4j Knowledge Graph — Event-Driven Updater.

Listens for platform events (via NATS) and keeps the Neo4j knowledge
graph in sync in near real-time.
"""

from repos.neo4j.updater.event_driven_updater import EventDrivenUpdater

__all__ = ["EventDrivenUpdater"]
