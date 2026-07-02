"""
A9 Prometheus Metrics — Observability for dual-brain system

Tracks:
- Coder iterations and code generation metrics
- Auditor decisions and quality metrics
- Approval rates and cycle times
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Try to import Prometheus client; graceful fallback if not available
try:
    from prometheus_client import Counter, Gauge, Histogram, Summary
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False
    logger.warning("[A9Metrics] prometheus_client not installed, metrics disabled")

    # Mock implementations for when prometheus is not available
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs):
            return self

    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass
        def inc(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs):
            return self

    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs):
            return self

    class Summary:
        def __init__(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs):
            return self


class A9Metrics:
    """Prometheus metrics for A9 dual-brain system"""

    # Coder metrics
    CODER_ITERATIONS = Counter(
        "a9_coder_iterations_total",
        "Total number of Coder iterations",
        ["status"],  # status: success, failed
    )

    CODER_GENERATION_TIME = Histogram(
        "a9_coder_generation_seconds",
        "Time taken by Coder to generate code",
        buckets=(1, 5, 10, 30, 60, 120),
    )

    CODER_FILES_GENERATED = Summary(
        "a9_coder_files_generated",
        "Number of files generated per iteration",
    )

    CODER_LINES_CHANGED = Summary(
        "a9_coder_lines_changed",
        "Number of lines added/removed per iteration",
    )

    CODER_CONFIDENCE = Gauge(
        "a9_coder_confidence",
        "Average Coder self-confidence score (0-1)",
    )

    # Auditor metrics
    AUDITOR_REVIEWS = Counter(
        "a9_auditor_reviews_total",
        "Total number of Auditor reviews",
        ["decision"],  # decision: approved, rejected
    )

    AUDITOR_REVIEW_TIME = Histogram(
        "a9_auditor_review_seconds",
        "Time taken by Auditor to review code",
        buckets=(1, 5, 10, 30, 60),
    )

    AUDITOR_ISSUES_FOUND = Summary(
        "a9_auditor_issues_found",
        "Number of issues found per review",
    )

    AUDITOR_CONFIDENCE = Gauge(
        "a9_auditor_confidence",
        "Average Auditor confidence score (0-1)",
    )

    # Approval metrics
    APPROVAL_RATE = Gauge(
        "a9_approval_rate",
        "Approval rate (0-1)",
    )

    APPROVALS_BY_ITERATION = Gauge(
        "a9_approvals_by_iteration",
        "Number of approvals at each iteration (1, 2, 3+)",
        ["iteration"],
    )

    # Cycle time metrics
    CYCLE_TIME = Histogram(
        "a9_cycle_time_seconds",
        "Total time from code generation to approval/escalation",
        buckets=(5, 10, 30, 60, 120, 300),
    )

    # Escalation metrics
    ESCALATIONS = Counter(
        "a9_escalations_total",
        "Number of escalations after max iterations",
    )

    # Error metrics
    GENERATION_ERRORS = Counter(
        "a9_generation_errors_total",
        "Number of code generation errors",
        ["stage"],  # stage: coder, auditor
    )

    @classmethod
    def record_coder_start(cls):
        """Record Coder start"""
        pass  # No explicit start needed

    @classmethod
    def record_coder_iteration(cls, status: str, duration_seconds: float, files_count: int,
                               lines_added: int, lines_removed: int, confidence: float):
        """Record Coder iteration metrics"""
        if HAS_PROMETHEUS:
            cls.CODER_ITERATIONS.labels(status=status).inc()
            cls.CODER_GENERATION_TIME.observe(duration_seconds)
            cls.CODER_FILES_GENERATED.observe(files_count)
            cls.CODER_LINES_CHANGED.observe(lines_added + lines_removed)
            cls.CODER_CONFIDENCE.set(confidence)

    @classmethod
    def record_auditor_review(cls, decision: str, duration_seconds: float, issues_count: int,
                              confidence: float):
        """Record Auditor review metrics"""
        if HAS_PROMETHEUS:
            cls.AUDITOR_REVIEWS.labels(decision=decision).inc()
            cls.AUDITOR_REVIEW_TIME.observe(duration_seconds)
            cls.AUDITOR_ISSUES_FOUND.observe(issues_count)
            cls.AUDITOR_CONFIDENCE.set(confidence)

    @classmethod
    def record_approval_rate(cls, approved_count: int, total_count: int):
        """Record overall approval rate"""
        if HAS_PROMETHEUS:
            rate = approved_count / total_count if total_count > 0 else 0
            cls.APPROVAL_RATE.set(rate)

    @classmethod
    def record_approval_by_iteration(cls, iteration: int, count: int):
        """Record approvals by iteration number"""
        if HAS_PROMETHEUS:
            iter_label = str(min(iteration, 3))  # Group 3+ as "3+"
            cls.APPROVALS_BY_ITERATION.labels(iteration=iter_label).set(count)

    @classmethod
    def record_cycle_time(cls, duration_seconds: float):
        """Record total cycle time"""
        if HAS_PROMETHEUS:
            cls.CYCLE_TIME.observe(duration_seconds)

    @classmethod
    def record_escalation(cls):
        """Record escalation"""
        if HAS_PROMETHEUS:
            cls.ESCALATIONS.inc()

    @classmethod
    def record_error(cls, stage: str):
        """Record error"""
        if HAS_PROMETHEUS:
            cls.GENERATION_ERRORS.labels(stage=stage).inc()


class A9MetricsCollector:
    """Collects and reports metrics from A9 execution"""

    def __init__(self):
        self.start_time = None
        self.iterations_data = []

    def start_cycle(self):
        """Mark cycle start"""
        self.start_time = datetime.now(timezone.utc)
        self.iterations_data = []

    def record_iteration(self, iteration_num: int, coder_result: dict, auditor_result: dict,
                        coder_duration: float, auditor_duration: float):
        """Record metrics for a single iteration"""
        # Extract Coder metrics
        coder_diff = coder_result.get("diff", {})
        coder_confidence = coder_result.get("self_inspection", {}).get("confidence", 0.5)

        files_created = coder_diff.get("files_created", 0)
        files_modified = coder_diff.get("files_modified", 0)
        lines_added = sum(c.get("lines_added", 0) for c in coder_diff.get("files_changed", []))
        lines_removed = sum(c.get("lines_removed", 0) for c in coder_diff.get("files_changed", []))

        A9Metrics.record_coder_iteration(
            status="success" if coder_result.get("status") == "success" else "failed",
            duration_seconds=coder_duration,
            files_count=files_created + files_modified,
            lines_added=lines_added,
            lines_removed=lines_removed,
            confidence=coder_confidence,
        )

        # Extract Auditor metrics
        auditor_decision = auditor_result.get("decision", "rejected")
        auditor_confidence = auditor_result.get("confidence", 0.5)
        issues_count = len(auditor_result.get("issues", []))

        A9Metrics.record_auditor_review(
            decision=auditor_decision,
            duration_seconds=auditor_duration,
            issues_count=issues_count,
            confidence=auditor_confidence,
        )

        # Store iteration data
        self.iterations_data.append({
            "iteration": iteration_num,
            "coder_duration": coder_duration,
            "auditor_duration": auditor_duration,
            "decision": auditor_decision,
            "files_changed": files_created + files_modified,
            "issues": issues_count,
        })

    def finalize_cycle(self, final_status: str):
        """Finalize cycle and record aggregate metrics"""
        if not self.start_time:
            return

        cycle_duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        A9Metrics.record_cycle_time(cycle_duration)

        # Compute approval rate
        approvals = sum(1 for it in self.iterations_data if it["decision"] == "approved")
        A9Metrics.record_approval_rate(approvals, len(self.iterations_data))

        # Record by iteration
        for i in range(1, 4):
            count = sum(1 for it in self.iterations_data if it["iteration"] == i and it["decision"] == "approved")
            A9Metrics.record_approval_by_iteration(i, count)

        if final_status == "escalated":
            A9Metrics.record_escalation()

        logger.info(
            f"[A9Metrics] Cycle finalized: "
            f"status={final_status}, duration={cycle_duration}s, "
            f"iterations={len(self.iterations_data)}, approvals={approvals}"
        )
