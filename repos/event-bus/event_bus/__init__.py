"""
Event Bus - NATS JetStream-based async event system for ai-native platform.

Provides:
  - StreamManager: JetStream stream/consumer lifecycle
  - EventPublisher: typed async publisher with idempotent delivery
  - EventSubscriber: decorator-based async subscriber with auto ack/nak
"""

from event_bus.publisher import EventPublisher
from event_bus.subscriber import EventSubscriber
from event_bus.stream_manager import StreamManager

__all__ = ["EventPublisher", "EventSubscriber", "StreamManager"]
