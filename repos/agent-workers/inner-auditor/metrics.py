"""
Prometheus Metrics — Instrumentation for Inner Auditor.

Provides metrics for tool execution, findings, and performance monitoring.
"""

try:
    from prometheus_client import Counter, Histogram, Gauge
except ImportError:
    # Graceful degradation if prometheus_client not installed
    class Counter:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, **kwargs):
            return self
        def inc(self, *args, **kwargs):
            pass

    class Histogram:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, **kwargs):
            return self
        def observe(self, *args, **kwargs):
            pass

    class Gauge:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, **kwargs):
            return self
        def set(self, *args, **kwargs):
            pass
        def inc(self, *args, **kwargs):
            pass


# Tool execution metrics
AUDITOR_TOOL_EXECUTIONS = Counter(
    "auditor_tool_executions_total",
    "Total number of tool executions",
    ["tool", "status"],
)

AUDITOR_TOOL_DURATION = Histogram(
    "auditor_tool_duration_seconds",
    "Tool execution duration in seconds",
    ["tool"],
)

AUDITOR_TOOL_TIMEOUTS = Counter(
    "auditor_tool_timeouts_total",
    "Total number of tool timeouts",
    ["tool"],
)

# Findings metrics
AUDITOR_FINDINGS_COUNT = Gauge(
    "auditor_findings_count",
    "Count of findings by severity",
    ["severity", "tool"],
)

AUDITOR_LINT_ISSUES = Gauge(
    "auditor_lint_issues_total",
    "Total lint issues found",
    ["severity"],
)

AUDITOR_TYPE_ERRORS = Gauge(
    "auditor_type_errors_total",
    "Total type checking errors",
)

AUDITOR_SECURITY_VULNS = Gauge(
    "auditor_security_vulnerabilities_total",
    "Total security vulnerabilities found",
    ["severity"],
)

# Audit run metrics
AUDITOR_RUNS = Counter(
    "auditor_runs_total",
    "Total audit runs",
    ["status"],
)

AUDITOR_RUN_DURATION = Histogram(
    "auditor_run_duration_seconds",
    "Full audit run duration in seconds",
)

AUDITOR_FILES_ANALYZED = Gauge(
    "auditor_files_analyzed",
    "Number of files analyzed in last run",
)


def record_tool_execution(tool_name: str, status: str, duration: float):
    """Record a tool execution metric."""
    AUDITOR_TOOL_EXECUTIONS.labels(tool=tool_name, status=status).inc()
    if status == "success":
        AUDITOR_TOOL_DURATION.labels(tool=tool_name).observe(duration)


def record_tool_timeout(tool_name: str):
    """Record a tool timeout."""
    AUDITOR_TOOL_TIMEOUTS.labels(tool=tool_name).inc()


def record_findings(findings: list, tool: str):
    """Record findings by severity."""
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for finding in findings:
        severity = finding.get("severity", "low").lower()
        if severity in severity_counts:
            severity_counts[severity] += 1

    for severity, count in severity_counts.items():
        AUDITOR_FINDINGS_COUNT.labels(severity=severity, tool=tool).set(count)


def record_audit_run(status: str, duration: float, files_analyzed: int):
    """Record a full audit run."""
    AUDITOR_RUNS.labels(status=status).inc()
    AUDITOR_RUN_DURATION.observe(duration)
    AUDITOR_FILES_ANALYZED.set(files_analyzed)
