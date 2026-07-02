"""
Mutation Reporter — Parses Stryker results and generates human-readable reports.

Analyzes mutation testing output to compute composite quality scores and
determines whether retesting is warranted.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class MutationReporter:
    """Generates mutation testing reports from Stryker output."""

    RETRY_THRESHOLD = 70  # Composite score below this triggers a retry

    @staticmethod
    def parse_results(stryker_output: dict) -> dict:
        """
        Parse raw Stryker output into a structured analysis.

        Args:
            stryker_output: Raw dict from StrykerRunner.run() with keys:
                            score, total_mutants, killed, survived, timeout,
                            no_coverage, runtime_errors, duration_ms

        Returns:
            dict with: mutation_score, assertion_quality, boundary_coverage,
                       deduplication, composite_score, weak_assertions[],
                       survived_details[]
        """
        score = stryker_output.get("score", 100.0)
        total = stryker_output.get("total_mutants", 0)
        killed = stryker_output.get("killed", 0)
        survived = stryker_output.get("survived", 0)
        timeout = stryker_output.get("timeout", 0)
        no_coverage = stryker_output.get("no_coverage", 0)
        runtime_errors = stryker_output.get("runtime_errors", 0)

        # Derived metrics
        mutation_score = score

        # Assertion quality: ratio of killed to total (excluding no-coverage)
        detectable = total - no_coverage
        assertion_quality = round((killed / detectable) * 100, 1) if detectable > 0 else 100.0

        # Boundary coverage: penalize for timeout + runtime_errors
        boundary_loss = (timeout + runtime_errors) / total if total > 0 else 0
        boundary_coverage = round(max(0, 100 - boundary_loss * 100), 1)

        # Deduplication: survivors that could be equivalent mutants
        dedup_ratio = min(survived / total, 0.3) if total > 0 else 0
        deduplication = round(100 - dedup_ratio * 100, 1)

        # Composite score: weighted average
        composite_score = round(
            mutation_score * 0.50
            + assertion_quality * 0.25
            + boundary_coverage * 0.15
            + deduplication * 0.10,
            1,
        )

        # Identify weak areas
        weak_assertions: list[str] = []
        if assertion_quality < 75:
            weak_assertions.append(
                f"Low assertion quality ({assertion_quality}%): "
                "consider hardening test assertions"
            )
        if boundary_coverage < 80:
            weak_assertions.append(
                f"Low boundary coverage ({boundary_coverage}%): "
                "timeout/runtime errors indicate flaky tests"
            )
        if deduplication < 90:
            weak_assertions.append(
                f"Possible equivalent mutants detected "
                "(deduplication={deduplication}%): review survivors manually"
            )

        # Survived mutant details
        survived_details: list[dict] = []
        if survived > 0:
            survived_details.append({
                "count": survived,
                "severity": "warning" if survived > 5 else "info",
                "recommendation": (
                    "Review survived mutants and add targeted tests"
                    if survived > 3
                    else "Low survived count, within acceptable range"
                ),
            })

        logger.info(
            f"MutationReporter: composite={composite_score}% "
            f"(mutation={mutation_score}, assertion={assertion_quality}, "
            f"boundary={boundary_coverage}, dedup={deduplication})"
        )

        return {
            "mutation_score": mutation_score,
            "assertion_quality": assertion_quality,
            "boundary_coverage": boundary_coverage,
            "deduplication": deduplication,
            "composite_score": composite_score,
            "weak_assertions": weak_assertions,
            "survived_details": survived_details,
        }

    @staticmethod
    def should_retry(result: dict) -> bool:
        """
        Determine if mutation testing should be retried.

        Args:
            result: The parsed result dict from parse_results()

        Returns:
            True if the composite score is below the retry threshold
        """
        composite = result.get("composite_score", 0)
        should = composite < MutationReporter.RETRY_THRESHOLD

        if should:
            logger.warning(
                f"MutationReporter: composite score {composite}% is below "
                f"threshold {MutationReporter.RETRY_THRESHOLD}% — recommend retry"
            )
        else:
            logger.info(f"MutationReporter: composite score {composite}% meets threshold")

        return should

    @staticmethod
    def generate_report(result: dict) -> str:
        """
        Generate a markdown-formatted mutation testing report.

        Args:
            result: The parsed result dict from parse_results()

        Returns:
            Markdown string
        """
        lines = [
            "# Mutation Testing Report",
            "",
            f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Scores",
            "",
            f"| Metric | Score |",
            f"|--------|-------|",
            f"| Mutation Score | {result.get('mutation_score', 0)}% |",
            f"| Assertion Quality | {result.get('assertion_quality', 0)}% |",
            f"| Boundary Coverage | {result.get('boundary_coverage', 0)}% |",
            f"| Deduplication | {result.get('deduplication', 0)}% |",
            f"| **Composite Score** | **{result.get('composite_score', 0)}%** |",
            "",
        ]

        weak = result.get("weak_assertions", [])
        if weak:
            lines.append("## Weaknesses Identified")
            lines.append("")
            for w in weak:
                lines.append(f"- {w}")
            lines.append("")

        survived = result.get("survived_details", [])
        if survived:
            lines.append("## Survived Mutants")
            lines.append("")
            for s in survived:
                lines.append(f"- **{s.get('count', 0)} survived** ({s.get('severity', 'info')}): "
                             f"{s.get('recommendation', '')}")
            lines.append("")

        retry = MutationReporter.should_retry(result)
        lines.append(f"## Recommendation")
        lines.append("")
        if retry:
            lines.append("**RETRY RECOMMENDED** — Composite score below 70% threshold.")
            lines.append("Address the weaknesses above and re-run mutation testing.")
        else:
            lines.append("Score meets quality threshold. No retry required.")
        lines.append("")

        return "\n".join(lines)
