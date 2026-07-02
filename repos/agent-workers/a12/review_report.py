"""
a12/review_report.py — Review Report Generator

Generates formatted code review reports in Markdown and JSON formats.
Consumes findings from the code review process and metrics from the
analysis pipeline.

Real implementation pattern:
  - Aggregate findings from multiple linters (ESLint, Pylint, etc.)
  - Merge with cross-module impact analysis results
  - Format as GitHub-flavored Markdown for PR comments
  - Produce structured JSON for downstream automation (CI/CD dashboard,
    quality gates, etc.)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class ReviewReportGenerator:
    """Generates human- and machine-readable code review reports.

    Two output formats are supported:
      - Markdown: suitable for PR comments, Slack messages, email
      - JSON: suitable for CI/CD dashboards, quality gates, data pipelines
    """

    def __init__(self):
        pass

    def generate_markdown(self, findings: list[dict], metrics: dict) -> str:
        """Generate a GitHub-flavored Markdown review report.

        Args:
            findings: List of issue dicts, each with:
                      {file, line, severity, category, description, suggestion, auto_fixable}
            metrics: Dict with {files_reviewed, issues_found, issues_fixed, time_spent}

        Returns:
            Markdown string
        """
        logger.info("Generating Markdown review report...")

        severity_order = {"error": 0, "warning": 1, "info": 2}
        sorted_findings = sorted(
            findings,
            key=lambda f: severity_order.get(f.get("severity", "info"), 99),
        )

        total = len(findings)
        errors = sum(1 for f in findings if f.get("severity") == "error")
        warnings = sum(1 for f in findings if f.get("severity") == "warning")
        infos = sum(1 for f in findings if f.get("severity") == "info")
        auto_fixable = sum(1 for f in findings if f.get("auto_fixable"))

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines: list[str] = []
        lines.append("# Code Review Report")
        lines.append("")
        lines.append(f"**Generated:** {now}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"| ------ | ----- |")
        lines.append(f"| Files reviewed | {metrics.get('files_reviewed', 'N/A')} |")
        lines.append(f"| Issues found | {total} |")
        lines.append(f"| Issues fixed (auto) | {metrics.get('issues_fixed', 0)} |")
        lines.append(f"| Time spent | {metrics.get('time_spent', 'N/A')} |")
        lines.append("")
        lines.append(f"| Severity | Count |")
        lines.append(f"| -------- | ----- |")
        lines.append(f"| Error | {errors} |")
        lines.append(f"| Warning | {warnings} |")
        lines.append(f"| Info | {infos} |")
        lines.append("")
        lines.append(f"**Auto-fixable issues:** {auto_fixable}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Findings")
        lines.append("")

        if not findings:
            lines.append("No issues found. Code looks great!")
        else:
            for i, f in enumerate(sorted_findings, 1):
                severity_icon = {"error": "X", "warning": "!", "info": "i"}.get(
                    f.get("severity", "info"), "?"
                )
                lines.append(f"### {i}. [{severity_icon}] `{f.get('file', '?')}`:{f.get('line', '?')}")
                lines.append("")
                lines.append(f"- **Severity:** {f.get('severity', 'N/A')}")
                lines.append(f"- **Category:** {f.get('category', 'N/A')}")
                lines.append(f"- **Description:** {f.get('description', 'N/A')}")
                if f.get("suggestion"):
                    lines.append(f"- **Suggestion:** {f['suggestion']}")
                if f.get("auto_fixable"):
                    lines.append(f"- **Auto-fix:** Available")
                lines.append("")

        # Recommendations section
        lines.append("---")
        lines.append("")
        lines.append("## Recommendations")
        lines.append("")

        recommendations = metrics.get("recommendations", [])
        if recommendations:
            for rec in recommendations:
                lines.append(f"- {rec}")
        else:
            if errors > 0:
                lines.append("- Fix all **error** severity issues before merging.")
            if warnings > 0:
                lines.append("- Review **warning** level issues; consider fixing before next release.")
            if infos > 0:
                lines.append("- **Info** level findings are advisory; no action required.")
            if total == 0:
                lines.append("- All checks passed. Safe to proceed with release.")

        lines.append("")
        return "\n".join(lines)

    def generate_json(self, findings: list[dict], metrics: dict) -> dict:
        """Generate a structured JSON review report.

        Args:
            findings: List of issue dicts
            metrics: Dict with {files_reviewed, issues_found, issues_fixed, time_spent,
                              recommendations[]}

        Returns:
            dict with summary, findings[], metrics{}, recommendations[]
        """
        logger.info("Generating JSON review report...")

        total = len(findings)
        errors = sum(1 for f in findings if f.get("severity") == "error")
        warnings = sum(1 for f in findings if f.get("severity") == "warning")
        infos = sum(1 for f in findings if f.get("severity") == "info")
        auto_fixable = sum(1 for f in findings if f.get("auto_fixable"))

        report = {
            "summary": {
                "total_issues": total,
                "errors": errors,
                "warnings": warnings,
                "infos": infos,
                "auto_fixable": auto_fixable,
                "verdict": "fail" if errors > 0 else "pass",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "findings": [
                {
                    "file": f.get("file", ""),
                    "line": f.get("line", 0),
                    "severity": f.get("severity", "info"),
                    "category": f.get("category", "unknown"),
                    "description": f.get("description", ""),
                    "suggestion": f.get("suggestion", ""),
                    "auto_fixable": f.get("auto_fixable", False),
                }
                for f in findings
            ],
            "metrics": {
                "files_reviewed": metrics.get("files_reviewed", 0),
                "issues_found": total,
                "issues_fixed": metrics.get("issues_fixed", 0),
                "time_spent": metrics.get("time_spent", "0s"),
            },
            "recommendations": metrics.get("recommendations", []),
        }

        logger.info("JSON report generated: %d findings, verdict=%s",
                     total, report["summary"]["verdict"])
        return report
