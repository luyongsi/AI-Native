"""
otel_config.py — OpenTelemetry SDK Initialization

Provides tracer initialization with OTLP/gRPC exporter for Jaeger backend.
Singleton tracer provider and batch span processor for efficiency.

Usage:
    from infra.observability.otel_config import init_tracer

    tracer = init_tracer("my-service")
    with tracer.start_as_current_span("operation_name") as span:
        span.set_attribute("key", "value")
        # ... work ...
"""
import os
import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

# Global tracer provider (singleton)
_TRACER_PROVIDER: Optional[TracerProvider] = None


def get_tracer_provider() -> TracerProvider:
    """Get or create the global tracer provider."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is None:
        raise RuntimeError("Tracer provider not initialized. Call init_tracer() first.")
    return _TRACER_PROVIDER


def init_tracer(
    service_name: str,
    environment: str = "dev",
    jaeger_endpoint: Optional[str] = None,
) -> trace.Tracer:
    """
    Initialize OpenTelemetry tracer with OTLP/gRPC exporter to Jaeger.

    Args:
        service_name: Name of the service (e.g., "mc-backend", "agent-a1")
        environment: Deployment environment ("dev", "staging", "prod")
        jaeger_endpoint: OTLP gRPC endpoint (default: from OTEL_EXPORTER_OTLP_ENDPOINT env)

    Returns:
        Configured tracer instance

    Example:
        tracer = init_tracer("mc-backend", environment="dev")
        with tracer.start_as_current_span("api_request"):
            # ... code ...
    """
    global _TRACER_PROVIDER

    # Get endpoint from env or parameter
    if jaeger_endpoint is None:
        jaeger_endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://localhost:4317"  # Default to local OTEL collector
        )

    logger.info(f"Initializing tracer '{service_name}' → {jaeger_endpoint}")

    # Create resource with service metadata
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.environ.get("SERVICE_VERSION", "0.1.0"),
        "deployment.environment": environment,
        "host.name": os.environ.get("HOSTNAME", "unknown"),
    })

    # Create tracer provider with resource
    tracer_provider = TracerProvider(resource=resource)

    # Create OTLP/gRPC exporter
    otlp_exporter = OTLPSpanExporter(
        endpoint=jaeger_endpoint,
        insecure=True  # For development; set False for production with TLS
    )

    # Add batch span processor (more efficient than simple processor)
    batch_processor = BatchSpanProcessor(
        otlp_exporter,
        schedule_delay_millis=1000,  # 1 second
        max_queue_size=1024,
        max_export_batch_size=512,
    )
    tracer_provider.add_span_processor(batch_processor)

    # Set as global tracer provider
    trace.set_tracer_provider(tracer_provider)
    _TRACER_PROVIDER = tracer_provider

    logger.info(f"Tracer '{service_name}' initialized successfully")

    # Return tracer instance
    return trace.get_tracer(service_name)


def get_tracer(service_name: str) -> trace.Tracer:
    """
    Get a tracer instance for the given service name.

    Must call init_tracer() at least once before using this.
    """
    return trace.get_tracer(service_name)


async def shutdown_tracer() -> None:
    """Flush and shut down the tracer provider gracefully."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        logger.info("Shutting down tracer provider...")
        _TRACER_PROVIDER.force_flush(timeout_millis=5000)
        _TRACER_PROVIDER.shutdown()
        _TRACER_PROVIDER = None
        logger.info("Tracer provider shut down")
