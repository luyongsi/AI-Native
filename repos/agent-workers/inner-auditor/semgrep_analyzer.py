"""
Semgrep Analyzer — Integration with Semgrep static analysis tool.

Provides async interface to Semgrep for comprehensive security and code quality scanning.
Includes result categorization and graceful degradation if Semgrep is unavailable.
"""

import asyncio
import json
import logging
from typing import Optional

from .tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class SemgrepAnalyzer:
    """Semgrep static analysis integration."""

    def __init__(self, rules_path: Optional[str] = None, timeout: int = 30):
        """
        Initialize Semgrep analyzer.

        Args:
            rules_path: Path to custom Semgrep rules file (uses 'auto' if None)
            timeout: Timeout for Semgrep execution in seconds
        """
        self.rules_path = rules_path or "auto"
        self.executor = ToolExecutor(timeout=timeout)
        self.timeout = timeout

    async def scan(self, file_path: str, cwd: Optional[str] = None) -> dict:
        """
        Run Semgrep on a single file.

        Args:
            file_path: Path to file to scan
            cwd: Working directory

        Returns:
            {
                "success": bool,
                "findings": list,
                "errors": list,
                "categories": dict,
                "tool_unavailable": bool
            }
        """
        cmd = [
            "semgrep",
            "--config",
            self.rules_path,
            "--json",
            "--quiet",
            file_path,
        ]

        result = await self.executor.run_with_timeout(cmd, cwd=cwd, timeout=self.timeout)

        if not result["success"]:
            if result["error"] and "not found" in result["error"].lower():
                logger.warning("[SemgrepAnalyzer] Semgrep not installed")
                return {
                    "success": False,
                    "findings": [],
                    "errors": [],
                    "categories": {},
                    "tool_unavailable": True,
                }

            if result["timed_out"]:
                logger.warning(f"[SemgrepAnalyzer] Semgrep timeout on {file_path}")
                return {
                    "success": False,
                    "findings": [],
                    "errors": [{"message": "Semgrep timed out", "severity": "warning"}],
                    "categories": {},
                    "tool_unavailable": False,
                }

            return {
                "success": False,
                "findings": [],
                "errors": [{"message": result.get("error", "Unknown error"), "severity": "error"}],
                "categories": {},
                "tool_unavailable": False,
            }

        try:
            output = json.loads(result["stdout"])
            findings = output.get("results", [])

            # Categorize findings
            categories = self._categorize_findings(findings)

            return {
                "success": True,
                "findings": findings,
                "errors": output.get("errors", []),
                "categories": categories,
                "tool_unavailable": False,
            }

        except json.JSONDecodeError as e:
            logger.error(f"[SemgrepAnalyzer] Failed to parse Semgrep output: {e}")
            return {
                "success": False,
                "findings": [],
                "errors": [{"message": "Failed to parse Semgrep output", "severity": "error"}],
                "categories": {},
                "tool_unavailable": False,
            }

    async def scan_multiple(self, file_paths: list, cwd: Optional[str] = None) -> dict:
        """
        Run Semgrep on multiple files in parallel.

        Args:
            file_paths: List of file paths to scan
            cwd: Working directory

        Returns:
            {
                "success": bool,
                "all_findings": list,
                "by_file": dict,
                "categories": dict,
                "tool_unavailable": bool
            }
        """
        if not file_paths:
            return {
                "success": True,
                "all_findings": [],
                "by_file": {},
                "categories": {},
                "tool_unavailable": False,
            }

        # Run scans in parallel
        tasks = [self.scan(fp, cwd=cwd) for fp in file_paths]
        results = await asyncio.gather(*tasks)

        # Check if tool is unavailable
        tool_unavailable = any(r.get("tool_unavailable", False) for r in results)

        # Aggregate results
        all_findings = []
        by_file = {}
        for fp, result in zip(file_paths, results):
            by_file[fp] = result
            all_findings.extend(result.get("findings", []))

        categories = self._categorize_findings(all_findings)

        return {
            "success": all(r["success"] for r in results),
            "all_findings": all_findings,
            "by_file": by_file,
            "categories": categories,
            "tool_unavailable": tool_unavailable,
        }

    def _categorize_findings(self, findings: list) -> dict:
        """
        Categorize Semgrep findings by type.

        Args:
            findings: List of Semgrep findings

        Returns:
            {
                "security": list,
                "performance": list,
                "best_practice": list,
                "error": list,
                "by_severity": dict
            }
        """
        categories = {
            "security": [],
            "performance": [],
            "best_practice": [],
            "error": [],
            "by_severity": {"critical": [], "high": [], "medium": [], "low": []},
        }

        for finding in findings:
            check_id = finding.get("check_id", "").lower()
            severity = finding.get("extra", {}).get("severity", "info").lower()

            # Categorize by type
            if "security" in check_id or "vuln" in check_id:
                categories["security"].append(finding)
            elif "performance" in check_id or "perf" in check_id:
                categories["performance"].append(finding)
            else:
                categories["best_practice"].append(finding)

            # Also categorize by severity
            if severity in categories["by_severity"]:
                categories["by_severity"][severity].append(finding)

        return categories

    def format_findings(self, findings: list, max_per_category: int = 10) -> dict:
        """
        Format findings for display/logging.

        Args:
            findings: List of findings to format
            max_per_category: Max findings to show per severity

        Returns:
            Formatted findings dict
        """
        formatted = {}

        for finding in findings[:max_per_category]:
            check_id = finding.get("check_id", "unknown")
            severity = finding.get("extra", {}).get("severity", "info").upper()
            path = finding.get("path", "unknown")
            line = finding.get("start", {}).get("line", 0)
            message = finding.get("extra", {}).get("message", "")

            if severity not in formatted:
                formatted[severity] = []

            formatted[severity].append({
                "check": check_id,
                "path": path,
                "line": line,
                "message": message,
            })

        return formatted
