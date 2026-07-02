"""
Result Converter — Bidirectional conversion between VisAgent and AI Agent formats.

Pure functions with no async dependencies. Converts test case and result
representations between the two ecosystems.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ResultConverter:
    """Converts data between VisAgent API format and AI Agent internal format."""

    @staticmethod
    def visagent_to_ai_format(visagent_result: dict) -> dict:
        """
        Convert a VisAgent API response to the AI Agent TestResult format.

        VisAgent format:
            { test_case_id, passed, confidence, issues[], screenshots[], duration_ms, raw_response }

        AI Agent format:
            { test_id, status: "passed"|"failed", score: 0-100,
              findings: [{ severity, description }], artifacts: [{ type, url }],
              duration_ms, raw_source }

        Args:
            visagent_result: The raw VisAgent API response

        Returns:
            AI Agent TestResult dict
        """
        test_case_id = visagent_result.get("test_case_id", "")
        passed = visagent_result.get("passed", False)
        confidence = visagent_result.get("confidence", 0.0)
        issues = visagent_result.get("issues", [])
        screenshots = visagent_result.get("screenshots", [])
        duration_ms = visagent_result.get("duration_ms", 0)

        # Map confidence to a 0-100 score
        score = round(confidence * 100)

        # Convert issues to findings
        findings = []
        for issue in issues:
            severity = "critical" if "crash" in issue.lower() or "error" in issue.lower() else "warning"
            findings.append({
                "severity": severity,
                "description": issue,
            })

        # Convert screenshots to artifacts
        artifacts = []
        for url in screenshots:
            artifacts.append({
                "type": "screenshot",
                "url": url,
            })

        status = "passed" if passed else "failed"

        logger.debug(
            f"ResultConverter: visagent -> ai: {test_case_id} -> status={status} score={score}"
        )

        return {
            "test_id": test_case_id,
            "status": status,
            "score": score,
            "findings": findings,
            "artifacts": artifacts,
            "duration_ms": duration_ms,
            "raw_source": visagent_result.get("raw_response", ""),
            "converted_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def ai_to_visagent_format(ai_test_case: dict) -> dict:
        """
        Convert an AI Agent test case to VisAgent API format.

        AI Agent format:
            { id, title, description, steps[], expected_result, tags[], priority,
              preconditions, auto_generate }

        VisAgent format:
            { external_id, title, steps[], preconditions, priority, tags[],
              expected_outcome, auto_generate_script }

        Args:
            ai_test_case: The AI Agent test case dict

        Returns:
            VisAgent API request dict
        """
        steps = ai_test_case.get("steps", [])
        if isinstance(steps, str):
            steps = [s.strip() for s in steps.split("\n") if s.strip()]

        tags = ai_test_case.get("tags", [])

        visagent_format = {
            "external_id": ai_test_case.get("id", ""),
            "title": ai_test_case.get("title", ai_test_case.get("description", "Untitled")),
            "steps": steps,
            "preconditions": ai_test_case.get("preconditions", ""),
            "priority": ai_test_case.get("priority", "medium"),
            "tags": tags,
            "expected_outcome": ai_test_case.get("expected_result", ""),
            "auto_generate_script": ai_test_case.get("auto_generate", False),
        }

        logger.debug(
            f"ResultConverter: ai -> visagent: "
            f"{visagent_format['external_id']} -> {visagent_format['title']}"
        )

        return visagent_format
