"""
Report Generator for Phase 6 E2E tests.

Generates comprehensive test reports including timings, quality metrics, and event logs.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from e2e_test_framework import TestResult

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates comprehensive E2E test reports."""

    @staticmethod
    def generate_report(
        test_results: List[TestResult],
        include_events: bool = False,
        include_details: bool = True,
    ) -> str:
        """
        Generate a comprehensive test report.

        Args:
            test_results: List of test results
            include_events: Include event timeline details
            include_details: Include detailed information

        Returns:
            Formatted report as string
        """
        if not test_results:
            return "No test results to report."

        # Calculate metrics
        passed_count = sum(1 for r in test_results if r.status == "passed")
        failed_count = sum(1 for r in test_results if r.status == "failed")
        timeout_count = sum(1 for r in test_results if r.status == "timeout")

        pass_rate = (passed_count / len(test_results) * 100) if test_results else 0

        total_duration = sum(r.duration_seconds for r in test_results)
        avg_duration = (total_duration / len(test_results)) if test_results else 0

        # Calculate quality metrics
        quality_scores = []
        coverage_values = []

        for result in test_results:
            if "code" in result.outputs:
                code_quality = result.outputs.get("code", {}).get("quality_score", 0)
                if code_quality:
                    quality_scores.append(code_quality)

            if "tests" in result.outputs:
                coverage = result.outputs.get("tests", {}).get("coverage", 0)
                if coverage:
                    coverage_values.append(coverage)

        avg_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else 0
        avg_coverage = (sum(coverage_values) / len(coverage_values)) if coverage_values else 0

        # Build report
        report_lines = [
            "=" * 80,
            "Phase 6 End-to-End Integration Test Report",
            "=" * 80,
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "EXECUTIVE SUMMARY",
            "-" * 80,
            f"Total Tests: {len(test_results)}",
            f"Passed: {passed_count} ({pass_rate:.1f}%)",
            f"Failed: {failed_count}",
            f"Timeout: {timeout_count}",
            "",
            f"Total Duration: {total_duration:.2f}s ({total_duration / 3600:.2f}h)",
            f"Average Duration: {avg_duration:.2f}s",
            f"Average Code Quality: {avg_quality:.1f}/5",
            f"Average Test Coverage: {avg_coverage:.1f}%",
            "",
        ]

        # Scenario results
        report_lines.extend([
            "SCENARIO RESULTS",
            "-" * 80,
        ])

        for i, result in enumerate(test_results, 1):
            status_icon = "✅" if result.status == "passed" else "❌" if result.status == "failed" else "⏱️"

            report_lines.extend([
                f"{status_icon} Scenario {i}: {result.scenario_name}",
                f"   Requirement ID: {result.req_id}",
                f"   Status: {result.status.upper()}",
                f"   Duration: {result.duration_seconds:.2f}s",
            ])

            if result.outputs:
                if "code" in result.outputs:
                    quality = result.outputs["code"].get("quality_score", 0)
                    report_lines.append(f"   Code Quality: {quality:.1f}/5")

                if "tests" in result.outputs:
                    pass_rate_test = result.outputs["tests"].get("pass_rate", 0) * 100
                    coverage = result.outputs["tests"].get("coverage", 0)
                    report_lines.append(f"   Test Pass Rate: {pass_rate_test:.1f}%")
                    report_lines.append(f"   Test Coverage: {coverage:.1f}%")

            if result.errors:
                report_lines.append("   Errors:")
                for error in result.errors:
                    report_lines.append(f"     - {error}")

            report_lines.append("")

        # Verification criteria
        report_lines.extend([
            "ACCEPTANCE CRITERIA",
            "-" * 80,
        ])

        criteria = [
            ("Scenario 1 (Simple) passed", any(
                r.scenario_id == "scenario_1" and r.status == "passed" and r.duration_seconds < 7200
                for r in test_results
            )),
            ("Scenario 2 (Medium) passed", any(
                r.scenario_id == "scenario_2" and r.status == "passed" and r.duration_seconds < 28800
                for r in test_results
            )),
            ("Scenario 3 (Complex) complete", any(
                r.scenario_id == "scenario_3"
                for r in test_results
            )),
            ("Code quality >= 4.0/5", avg_quality >= 4.0),
            ("Test coverage >= 70%", avg_coverage >= 70.0),
            ("Pass rate >= 80%", pass_rate >= 80.0),
        ]

        for criterion, met in criteria:
            status = "✅ PASS" if met else "❌ FAIL"
            report_lines.append(f"{status}: {criterion}")

        report_lines.extend(["", ""])

        # Detailed results
        if include_details:
            report_lines.extend([
                "DETAILED RESULTS",
                "-" * 80,
            ])

            for i, result in enumerate(test_results, 1):
                report_lines.extend([
                    f"Scenario {i}: {result.scenario_name}",
                    f"Start: {result.start_time.isoformat()}",
                    f"End: {result.end_time.isoformat()}",
                    f"Duration: {result.duration_seconds:.2f}s",
                ])

                if result.outputs:
                    report_lines.append("Outputs:")
                    report_lines.append(json.dumps(result.outputs, indent=2))

                report_lines.append("")

        # Event timeline
        if include_events:
            report_lines.extend([
                "EVENT TIMELINE",
                "-" * 80,
            ])

            for i, result in enumerate(test_results, 1):
                if result.events:
                    report_lines.append(f"Scenario {i}: {result.scenario_name}")
                    report_lines.append(f"Total events: {len(result.events)}")

                    # Group by subject
                    subjects = {}
                    for event in result.events:
                        subject = event.get("subject", "unknown")
                        if subject not in subjects:
                            subjects[subject] = 0
                        subjects[subject] += 1

                    for subject, count in sorted(subjects.items()):
                        report_lines.append(f"  {subject}: {count}")

                    report_lines.append("")

        # Footer
        report_lines.extend([
            "=" * 80,
            f"Report generated at {datetime.now().isoformat()}",
            "=" * 80,
        ])

        return "\n".join(report_lines)

    @staticmethod
    def generate_json_report(test_results: List[TestResult]) -> str:
        """Generate report in JSON format."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(test_results),
            "passed": sum(1 for r in test_results if r.status == "passed"),
            "failed": sum(1 for r in test_results if r.status == "failed"),
            "timeout": sum(1 for r in test_results if r.status == "timeout"),
            "results": [
                {
                    "scenario_id": r.scenario_id,
                    "scenario_name": r.scenario_name,
                    "req_id": r.req_id,
                    "status": r.status,
                    "duration_seconds": r.duration_seconds,
                    "start_time": r.start_time.isoformat(),
                    "end_time": r.end_time.isoformat(),
                    "outputs": r.outputs,
                    "errors": r.errors,
                    "event_count": len(r.events),
                }
                for r in test_results
            ],
        }

        return json.dumps(data, indent=2)

    @staticmethod
    def generate_csv_report(test_results: List[TestResult]) -> str:
        """Generate report in CSV format."""
        lines = [
            "Scenario,Name,RequirementID,Status,Duration(s),Quality,Coverage(%),Events",
        ]

        for i, result in enumerate(test_results, 1):
            quality = result.outputs.get("code", {}).get("quality_score", "N/A")
            coverage = result.outputs.get("tests", {}).get("coverage", "N/A")
            events = len(result.events)

            line = f"Scenario {i},{result.scenario_name},{result.req_id},{result.status},{result.duration_seconds:.2f},{quality},{coverage},{events}"
            lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def generate_summary(test_results: List[TestResult]) -> Dict[str, Any]:
        """Generate summary statistics."""
        if not test_results:
            return {}

        passed_count = sum(1 for r in test_results if r.status == "passed")
        failed_count = sum(1 for r in test_results if r.status == "failed")
        timeout_count = sum(1 for r in test_results if r.status == "timeout")

        pass_rate = (passed_count / len(test_results) * 100) if test_results else 0

        total_duration = sum(r.duration_seconds for r in test_results)
        avg_duration = (total_duration / len(test_results)) if test_results else 0
        min_duration = min((r.duration_seconds for r in test_results), default=0)
        max_duration = max((r.duration_seconds for r in test_results), default=0)

        quality_scores = [
            r.outputs.get("code", {}).get("quality_score", 0)
            for r in test_results
            if "code" in r.outputs
        ]
        avg_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else 0

        coverage_values = [
            r.outputs.get("tests", {}).get("coverage", 0)
            for r in test_results
            if "tests" in r.outputs
        ]
        avg_coverage = (sum(coverage_values) / len(coverage_values)) if coverage_values else 0

        return {
            "total_tests": len(test_results),
            "passed": passed_count,
            "failed": failed_count,
            "timeout": timeout_count,
            "pass_rate": pass_rate,
            "total_duration_seconds": total_duration,
            "average_duration_seconds": avg_duration,
            "min_duration_seconds": min_duration,
            "max_duration_seconds": max_duration,
            "average_code_quality": avg_quality,
            "average_test_coverage": avg_coverage,
        }
