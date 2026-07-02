"""
span_attributes.py — Standard Span Attributes and Helper Functions

Provides constants for common span attributes and helper functions for
adding context to spans consistently across the system.

Usage:
    from infra.observability.span_attributes import (
        ATTR_REQ_ID, add_request_context, add_llm_context, record_error_event
    )

    with tracer.start_as_current_span("agent_execute") as span:
        add_request_context(span, req_id="abc123", agent_id="a1")
        add_llm_context(span, model="deepseek-v3", tokens_in=150, tokens_out=500)
"""
import logging
from typing import Optional, Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

logger = logging.getLogger(__name__)

# ── Standard attribute names ────────────────────────────────────────────────

# Request/Correlation attributes
ATTR_REQ_ID = "req_id"
ATTR_TRACE_ID = "trace_id"
ATTR_SPAN_ID = "span_id"

# Service attributes
ATTR_SERVICE_NAME = "service.name"
ATTR_SERVICE_VERSION = "service.version"
ATTR_ENVIRONMENT = "deployment.environment"

# Agent/Orchestration attributes
ATTR_AGENT_ID = "agent.id"
ATTR_AGENT_TYPE = "agent.type"
ATTR_WORKFLOW_ID = "workflow.id"
ATTR_WORKFLOW_NAME = "workflow.name"
ATTR_ACTIVITY_NAME = "activity.name"

# User/Auth attributes
ATTR_USER_ID = "user.id"
ATTR_USER_EMAIL = "user.email"
ATTR_ORG_ID = "org.id"

# Message/Event attributes
ATTR_SUBJECT = "nats.subject"
ATTR_EVENT_TYPE = "event.type"
ATTR_MESSAGE_ID = "message.id"

# LLM Call attributes
ATTR_LLM_PROVIDER = "llm.provider"
ATTR_LLM_MODEL = "llm.model"
ATTR_LLM_TOKENS_IN = "llm.tokens.input"
ATTR_LLM_TOKENS_OUT = "llm.tokens.output"
ATTR_LLM_TEMPERATURE = "llm.temperature"
ATTR_LLM_MAX_TOKENS = "llm.max_tokens"

# Database attributes
ATTR_DB_SYSTEM = "db.system"
ATTR_DB_NAME = "db.name"
ATTR_DB_OPERATION = "db.operation"
ATTR_DB_ROWS_AFFECTED = "db.rows_affected"

# HTTP attributes
ATTR_HTTP_METHOD = "http.method"
ATTR_HTTP_URL = "http.url"
ATTR_HTTP_STATUS_CODE = "http.status_code"
ATTR_HTTP_CLIENT_IP = "http.client_ip"

# Error attributes (set by OTEL SDK automatically, but useful for reference)
ATTR_ERROR_TYPE = "error.type"
ATTR_ERROR_MESSAGE = "error.message"
ATTR_ERROR_STACK_TRACE = "error.stack_trace"

# Gate/Decision attributes
ATTR_GATE_NAME = "gate.name"
ATTR_GATE_DECISION = "gate.decision"
ATTR_GATE_REASON = "gate.reason"

# Complexity/Resource attributes
ATTR_COMPLEXITY_LEVEL = "complexity.level"
ATTR_LOOP_COUNT = "loop.count"
ATTR_RETRY_COUNT = "retry.count"


def add_request_context(
    span: Span,
    req_id: str,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> None:
    """
    Add request context attributes to a span.

    These attributes help correlate spans across services in distributed traces.

    Args:
        span: The span to annotate
        req_id: Requirement/Request ID (primary correlation ID)
        agent_id: Agent identifier if applicable
        user_id: User making the request (if available)
        org_id: Organization/tenant ID (if applicable)
    """
    span.set_attribute(ATTR_REQ_ID, req_id)
    if agent_id:
        span.set_attribute(ATTR_AGENT_ID, agent_id)
    if user_id:
        span.set_attribute(ATTR_USER_ID, user_id)
    if org_id:
        span.set_attribute(ATTR_ORG_ID, org_id)


def add_agent_context(
    span: Span,
    agent_id: str,
    agent_type: str,
    req_id: Optional[str] = None,
) -> None:
    """
    Add agent execution context to a span.

    Args:
        span: The span to annotate
        agent_id: Agent identifier (e.g., "a1", "a2", "fc")
        agent_type: Agent type/role
        req_id: Associated request ID if available
    """
    span.set_attribute(ATTR_AGENT_ID, agent_id)
    span.set_attribute(ATTR_AGENT_TYPE, agent_type)
    if req_id:
        span.set_attribute(ATTR_REQ_ID, req_id)


def add_workflow_context(
    span: Span,
    workflow_name: str,
    workflow_id: Optional[str] = None,
    req_id: Optional[str] = None,
) -> None:
    """
    Add workflow orchestration context to a span.

    Args:
        span: The span to annotate
        workflow_name: Name of the workflow (e.g., "RequirementWorkflow")
        workflow_id: Temporal workflow ID
        req_id: Associated request ID
    """
    span.set_attribute(ATTR_WORKFLOW_NAME, workflow_name)
    if workflow_id:
        span.set_attribute(ATTR_WORKFLOW_ID, workflow_id)
    if req_id:
        span.set_attribute(ATTR_REQ_ID, req_id)


def add_llm_context(
    span: Span,
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> None:
    """
    Add LLM API call context to a span.

    Useful for tracking and analyzing language model usage across agents.

    Args:
        span: The span to annotate
        provider: LLM provider name (e.g., "deepseek", "openai", "claude")
        model: Model identifier (e.g., "deepseek-v3", "gpt-4")
        tokens_in: Input tokens consumed
        tokens_out: Output tokens generated
        temperature: Sampling temperature (if applicable)
        max_tokens: Max output tokens requested (if applicable)
    """
    span.set_attribute(ATTR_LLM_PROVIDER, provider)
    span.set_attribute(ATTR_LLM_MODEL, model)
    span.set_attribute(ATTR_LLM_TOKENS_IN, tokens_in)
    span.set_attribute(ATTR_LLM_TOKENS_OUT, tokens_out)
    if temperature is not None:
        span.set_attribute(ATTR_LLM_TEMPERATURE, temperature)
    if max_tokens is not None:
        span.set_attribute(ATTR_LLM_MAX_TOKENS, max_tokens)


def add_database_context(
    span: Span,
    db_system: str = "postgresql",
    db_name: Optional[str] = None,
    operation: Optional[str] = None,
    rows_affected: Optional[int] = None,
) -> None:
    """
    Add database operation context to a span.

    Args:
        span: The span to annotate
        db_system: Database system (default: "postgresql")
        db_name: Database name
        operation: SQL operation type (SELECT, INSERT, UPDATE, DELETE)
        rows_affected: Number of rows affected by operation
    """
    span.set_attribute(ATTR_DB_SYSTEM, db_system)
    if db_name:
        span.set_attribute(ATTR_DB_NAME, db_name)
    if operation:
        span.set_attribute(ATTR_DB_OPERATION, operation)
    if rows_affected is not None:
        span.set_attribute(ATTR_DB_ROWS_AFFECTED, rows_affected)


def add_gate_context(
    span: Span,
    gate_name: str,
    decision: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """
    Add gate/decision context to a span.

    Args:
        span: The span to annotate
        gate_name: Name of the gate (e.g., "approval_gate", "quality_gate")
        decision: Decision made (e.g., "approved", "rejected", "pending")
        reason: Reason for the decision
    """
    span.set_attribute(ATTR_GATE_NAME, gate_name)
    if decision:
        span.set_attribute(ATTR_GATE_DECISION, decision)
    if reason:
        span.set_attribute(ATTR_GATE_REASON, reason)


def record_error_event(
    span: Span,
    exception: Exception,
    message: Optional[str] = None,
) -> None:
    """
    Record an error event and set span status to ERROR.

    The OTEL SDK will also automatically record the exception, but this helper
    ensures consistent error handling and status marking.

    Args:
        span: The span to mark as errored
        exception: The exception that occurred
        message: Optional custom error message
    """
    # Record exception event (SDK does this automatically, but explicit is clear)
    span.record_exception(exception)

    # Set span status to ERROR
    error_msg = message or str(exception)
    span.set_status(Status(StatusCode.ERROR, error_msg))

    logger.error(f"Span error recorded: {error_msg}", exc_info=exception)


def set_span_success(span: Span) -> None:
    """
    Mark a span as successfully completed.

    Args:
        span: The span to mark as OK
    """
    span.set_status(Status(StatusCode.OK))


def add_complexity_context(
    span: Span,
    complexity_level: Optional[str] = None,
    loop_count: Optional[int] = None,
    retry_count: Optional[int] = None,
) -> None:
    """
    Add complexity/resource usage context to a span.

    Useful for tracking problematic or resource-intensive operations.

    Args:
        span: The span to annotate
        complexity_level: Complexity classification (e.g., "low", "medium", "high", "critical")
        loop_count: Number of loops/iterations (for circuit breaker tracking)
        retry_count: Number of retries attempted
    """
    if complexity_level:
        span.set_attribute(ATTR_COMPLEXITY_LEVEL, complexity_level)
    if loop_count is not None:
        span.set_attribute(ATTR_LOOP_COUNT, loop_count)
    if retry_count is not None:
        span.set_attribute(ATTR_RETRY_COUNT, retry_count)


def add_nats_context(
    span: Span,
    subject: str,
    event_type: Optional[str] = None,
    message_id: Optional[str] = None,
) -> None:
    """
    Add NATS message context to a span.

    Args:
        span: The span to annotate
        subject: NATS subject/topic
        event_type: Event type (if available)
        message_id: Message ID (if available)
    """
    span.set_attribute(ATTR_SUBJECT, subject)
    if event_type:
        span.set_attribute(ATTR_EVENT_TYPE, event_type)
    if message_id:
        span.set_attribute(ATTR_MESSAGE_ID, message_id)


def add_http_context(
    span: Span,
    method: str,
    url: str,
    status_code: Optional[int] = None,
    client_ip: Optional[str] = None,
) -> None:
    """
    Add HTTP request context to a span.

    Args:
        span: The span to annotate
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        status_code: HTTP response status code (optional, can be added later)
        client_ip: Client IP address (optional)
    """
    span.set_attribute(ATTR_HTTP_METHOD, method)
    span.set_attribute(ATTR_HTTP_URL, url)
    if status_code:
        span.set_attribute(ATTR_HTTP_STATUS_CODE, status_code)
    if client_ip:
        span.set_attribute(ATTR_HTTP_CLIENT_IP, client_ip)
