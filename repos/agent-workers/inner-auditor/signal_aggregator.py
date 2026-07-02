"""
Signal Aggregator — combines audit results into a pass/fail verdict.

Receives the output of InnerAuditor.run_all() and produces a structured
verdict with score, issue list, and summary.
"""

import logging

logger = logging.getLogger(__name__)


class SignalAggregator:
    """Aggregates lint, type-check, and security scan results into a pass/fail verdict."""

    @staticmethod
    def aggregate(lint_result: dict, type_check_result: dict, security_result: dict) -> dict:
        """
        Aggregate individual check results into a unified verdict.

        Rules:
        - Fail if: any critical security issue, >5 lint errors, or any type error.
        - Score: 100 - (lint_errors * 3) - (type_errors * 10) - (security_critical * 25)

        Args:
            lint_result: Result dict from InnerAuditor.run_lint()
            type_check_result: Result dict from InnerAuditor.run_type_check()
            security_result: Result dict from InnerAuditor.run_security_scan()

        Returns:
            dict with keys: verdict ("pass"|"fail"), score (0-100), issues (list), summary (str)
        """
        # Extract counts
        lint_errors = lint_result.get("error_count", 0)
        lint_warnings = lint_result.get("warning_count", 0)
        type_errors = type_check_result.get("error_count", 0)
        security_critical = security_result.get("critical_count", 0)
        security_high = security_result.get("high_count", 0)
        security_medium = security_result.get("medium_count", 0)
        security_low = security_result.get("low_count", 0)

        # Compute score
        score = 100
        score -= lint_errors * 3
        score -= type_errors * 10
        score -= security_critical * 25
        score = max(score, 0)  # Floor at 0

        # Determine verdict
        fail_reasons = []

        if security_critical > 0:
            fail_reasons.append(f"{security_critical} critical security issue(s)")

        if lint_errors > 5:
            fail_reasons.append(f"{lint_errors} lint errors (threshold: 5)")

        if type_errors > 0:
            fail_reasons.append(f"{type_errors} type error(s)")

        verdict = "fail" if fail_reasons else "pass"

        # Collect all issues into a flat list
        all_issues = []
        all_issues.extend(lint_result.get("issues", []))
        all_issues.extend(type_check_result.get("errors", []))
        all_issues.extend(security_result.get("vulnerabilities", []))

        # Build summary
        if verdict == "pass":
            summary_parts = ["All quality gates passed."]
            if lint_warnings > 0:
                summary_parts.append(f"{lint_warnings} lint warning(s) (non-blocking).")
            summary_parts.append(
                f"Score: {score}/100 (lint={lint_errors}, type={type_errors}, sec_crit={security_critical})"
            )
            summary = " ".join(summary_parts)
        else:
            summary = (
                f"Quality gate FAILED. Reasons: {'; '.join(fail_reasons)}. "
                f"Score: {score}/100. "
                f"Total issues: {len(all_issues)}."
            )

        logger.info(
            "[SignalAggregator] Verdict: %s | Score: %d | Lint errors: %d | Type errors: %d | Security critical: %d",
            verdict, score, lint_errors, type_errors, security_critical,
        )

        return {
            "verdict": verdict,
            "score": score,
            "issues": all_issues,
            "summary": summary,
        }
