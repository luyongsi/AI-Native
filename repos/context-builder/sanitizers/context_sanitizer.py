"""ContextSanitizer: remove sensitive information before passing context to agents."""

import logging
import time
from typing import Dict, List, Any, Optional
from sanitizers.secret_scanner import SecretScanner, SecretFinding
from sanitizers.pii_detector import PIIDetector, PIIFinding

logger = logging.getLogger(__name__)


class Metrics:
    """Simple metrics collection for sanitization operations."""

    def __init__(self):
        self.redactions_total = 0
        self.sanitize_durations = []
        self.whitelist_bypasses = 0

    def record_redactions(self, count: int):
        """Record number of redactions."""
        self.redactions_total += count

    def record_duration(self, duration_seconds: float):
        """Record sanitization duration."""
        self.sanitize_durations.append(duration_seconds)

    def record_whitelist_bypass(self):
        """Record a whitelist bypass."""
        self.whitelist_bypasses += 1

    def get_p95_duration(self) -> float:
        """Get P95 duration in seconds."""
        if not self.sanitize_durations:
            return 0.0
        sorted_durations = sorted(self.sanitize_durations)
        index = int(len(sorted_durations) * 0.95)
        return sorted_durations[index] if index < len(sorted_durations) else 0.0

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregated statistics."""
        return {
            'redactions_total': self.redactions_total,
            'sanitize_operations': len(self.sanitize_durations),
            'avg_duration_ms': (
                sum(self.sanitize_durations) / len(self.sanitize_durations) * 1000
                if self.sanitize_durations
                else 0.0
            ),
            'p95_duration_ms': self.get_p95_duration() * 1000,
            'whitelist_bypasses': self.whitelist_bypasses,
        }


class ContextSanitizer:
    """Sanitize context by removing sensitive information (secrets and PII).

    Features:
      - Scan for API keys, passwords, DB connections, JWT tokens, AWS keys
      - Detect PII: phone numbers, emails, ID cards, credit cards
      - Whitelist certain agents for unrestricted access
      - Audit logging for all sanitization operations
      - Prometheus-style metrics
    """

    # Whitelist configuration: agents that bypass sanitization
    WHITELIST_CONFIG = {
        'agents': ['A12'],  # Security Reviewer can access original data
        'secret_types': {
            'A12': ['api_key', 'password', 'db_connection', 'jwt_token', 'aws_key']
        },
    }

    def __init__(self):
        """Initialize sanitizer with scanners and metrics."""
        self.secret_scanner = SecretScanner()
        self.pii_detector = PIIDetector()
        self.metrics = Metrics()
        self.whitelist = self.WHITELIST_CONFIG

    def _is_agent_whitelisted(self, agent_id: str) -> bool:
        """Check if agent is in the whitelist."""
        return agent_id in self.whitelist['agents']

    async def sanitize_context(
        self, context: Dict[str, Any], agent_id: str
    ) -> Dict[str, Any]:
        """
        Sanitize context by removing sensitive information.

        Args:
            context: Context dict with candidates
            agent_id: Target agent ID

        Returns:
            Sanitized context dict
        """
        start_time = time.time()

        # Check whitelist
        if self._is_agent_whitelisted(agent_id):
            logger.info(
                f"[Sanitizer] agent={agent_id} is whitelisted, skipping sanitization"
            )
            self.metrics.record_whitelist_bypass()
            return context

        # Sanitize context
        sanitized = self._sanitize_context_impl(context, agent_id)

        # Record metrics
        duration = time.time() - start_time
        self.metrics.record_duration(duration)

        if duration > 0.2:  # 200ms threshold
            logger.warning(
                f"[Sanitizer] sanitization took {duration*1000:.1f}ms for agent={agent_id}"
            )

        return sanitized

    def _sanitize_context_impl(
        self, context: Dict[str, Any], agent_id: str
    ) -> Dict[str, Any]:
        """Internal implementation of context sanitization."""
        sanitized = dict(context)
        candidates = sanitized.get('candidates', [])
        total_redactions = 0

        for candidate in candidates:
            content = candidate.get('content', '')
            file_path = candidate.get('file_path', 'unknown')

            # Scan for secrets and PII
            secret_findings = self.secret_scanner.scan(content)
            pii_findings = self.pii_detector.detect(content)

            # Redact
            content = self.secret_scanner.redact(content, secret_findings)
            content = self.pii_detector.redact(content, pii_findings)

            candidate['content'] = content
            candidate['sanitized'] = True
            candidate['redactions'] = len(secret_findings) + len(pii_findings)
            total_redactions += candidate['redactions']

            # Audit log
            if secret_findings or pii_findings:
                self._audit_log(
                    agent_id, file_path, secret_findings, pii_findings
                )

        self.metrics.record_redactions(total_redactions)
        return sanitized

    def _audit_log(
        self,
        agent_id: str,
        file_path: str,
        secret_findings: List[SecretFinding],
        pii_findings: List[PIIFinding],
    ):
        """Log sanitization audit event."""
        secret_summary = {}
        for finding in secret_findings:
            secret_summary[finding.type] = secret_summary.get(finding.type, 0) + 1

        pii_summary = {}
        for finding in pii_findings:
            pii_summary[finding.type] = pii_summary.get(finding.type, 0) + 1

        logger.info(
            f'[Sanitizer] agent={agent_id}, file={file_path}, '
            f'secrets={len(secret_findings)}, pii={len(pii_findings)}, '
            f'secret_types={secret_summary}, pii_types={pii_summary}'
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        return self.metrics.get_stats()
