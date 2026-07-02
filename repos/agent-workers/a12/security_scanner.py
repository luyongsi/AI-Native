"""
A12 Security Scanner — Integration with real security scanning tools.

Provides unified interface to Bandit, npm audit, and Semgrep for comprehensive
security analysis. Supports Python, JavaScript, and TypeScript code.

Tools integrated:
  - Bandit: Python security scanning
  - npm audit: JavaScript/TypeScript dependency vulnerability detection
  - Semgrep: Cross-language static analysis with custom rules
"""

import asyncio
import json
import logging
import os
import sys
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from inner_auditor.semgrep_analyzer import SemgrepAnalyzer
    from inner_auditor.tool_executor import ToolExecutor
except ImportError:
    # Fallback: provide stub implementations for testing
    logger = logging.getLogger(__name__)
    logger.warning("[A12] inner_auditor not available, using stubs")

    class ToolExecutor:
        """Stub ToolExecutor for when inner_auditor is unavailable."""
        def __init__(self, timeout: int = 30):
            self.timeout = timeout

        async def run_with_timeout(self, cmd: list, cwd: Optional[str] = None, timeout: Optional[int] = None) -> dict:
            """Stub implementation."""
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "timed_out": False,
                "error": "inner_auditor not available",
            }

    class SemgrepAnalyzer:
        """Stub SemgrepAnalyzer for when inner_auditor is unavailable."""
        def __init__(self, rules_path: Optional[str] = None, timeout: int = 30):
            self.rules_path = rules_path or "auto"
            self.executor = ToolExecutor(timeout=timeout)
            self.timeout = timeout

        async def scan(self, file_path: str, cwd: Optional[str] = None) -> dict:
            """Stub implementation."""
            return {
                "success": False,
                "findings": [],
                "errors": [],
                "categories": {},
                "tool_unavailable": True,
            }

logger = logging.getLogger(__name__)


class SecurityScanner:
    """Unified security scanner for multiple languages and tools."""

    def __init__(self, timeout: int = 60, custom_rules_path: Optional[str] = None):
        """
        Initialize security scanner.

        Args:
            timeout: Timeout for tool execution in seconds
            custom_rules_path: Path to custom Semgrep rules (uses 'auto' if None)
        """
        self.executor = ToolExecutor(timeout=timeout)
        self.semgrep = SemgrepAnalyzer(rules_path=custom_rules_path, timeout=timeout)
        self.timeout = timeout

    async def scan_python(self, file_path: str, cwd: Optional[str] = None) -> dict:
        """
        Scan Python file for security issues using Bandit and Semgrep.

        Args:
            file_path: Path to Python file to scan
            cwd: Working directory for tool execution

        Returns:
            {
                "success": bool,
                "file": str,
                "language": "python",
                "findings": list,
                "tools_run": list,
                "summary": dict
            }
        """
        logger.info(f"[A12] Scanning Python file: {file_path}")

        findings = []
        tools_run = []

        # 1. Bandit - Python security scanning
        bandit_result = await self._run_bandit(file_path, cwd)
        if bandit_result["success"]:
            tools_run.append("bandit")
            findings.extend(bandit_result["findings"])
        elif not bandit_result.get("tool_unavailable"):
            logger.warning(f"[A12] Bandit failed: {bandit_result.get('error')}")

        # 2. Semgrep - Generic security rules
        semgrep_result = await self.semgrep.scan(file_path, cwd=cwd)
        if semgrep_result["success"]:
            tools_run.append("semgrep")
            findings.extend(self._convert_semgrep_findings(semgrep_result["findings"]))
        elif not semgrep_result.get("tool_unavailable"):
            logger.warning(f"[A12] Semgrep failed")

        summary = self._summarize_findings(findings)

        return {
            "success": len(findings) >= 0,
            "file": file_path,
            "language": "python",
            "findings": findings,
            "tools_run": tools_run,
            "summary": summary,
        }

    async def scan_javascript(
        self, file_path: str, cwd: Optional[str] = None
    ) -> dict:
        """
        Scan JavaScript/TypeScript file for security issues.

        Uses npm audit for dependencies (if package.json present) and Semgrep
        for code-level issues.

        Args:
            file_path: Path to JavaScript/TypeScript file or package.json
            cwd: Working directory for tool execution

        Returns:
            {
                "success": bool,
                "file": str,
                "language": "javascript",
                "findings": list,
                "tools_run": list,
                "summary": dict
            }
        """
        is_package_json = file_path.endswith("package.json")
        logger.info(
            f"[A12] Scanning JavaScript/TypeScript: {file_path} "
            f"(package.json={is_package_json})"
        )

        findings = []
        tools_run = []

        # 1. npm audit - Check for vulnerable dependencies
        if is_package_json:
            npm_result = await self._run_npm_audit(file_path, cwd)
            if npm_result["success"]:
                tools_run.append("npm_audit")
                findings.extend(npm_result["findings"])
            elif not npm_result.get("tool_unavailable"):
                logger.warning(f"[A12] npm audit failed: {npm_result.get('error')}")

        # 2. Semgrep - JavaScript/TypeScript security rules
        semgrep_result = await self.semgrep.scan(file_path, cwd=cwd)
        if semgrep_result["success"]:
            tools_run.append("semgrep")
            findings.extend(self._convert_semgrep_findings(semgrep_result["findings"]))
        elif not semgrep_result.get("tool_unavailable"):
            logger.warning(f"[A12] Semgrep failed")

        summary = self._summarize_findings(findings)

        return {
            "success": len(findings) >= 0,
            "file": file_path,
            "language": "javascript",
            "findings": findings,
            "tools_run": tools_run,
            "summary": summary,
        }

    async def scan_multiple(
        self, file_paths: List[str], cwd: Optional[str] = None
    ) -> dict:
        """
        Scan multiple files in parallel.

        Args:
            file_paths: List of file paths to scan
            cwd: Working directory for tool execution

        Returns:
            {
                "success": bool,
                "scanned_files": int,
                "results_by_file": dict,
                "all_findings": list,
                "summary": dict
            }
        """
        logger.info(f"[A12] Scanning {len(file_paths)} files in parallel")

        tasks = []
        for file_path in file_paths:
            if file_path.endswith(".py"):
                tasks.append(self.scan_python(file_path, cwd))
            elif file_path.endswith((".js", ".ts", ".jsx", ".tsx", "package.json")):
                tasks.append(self.scan_javascript(file_path, cwd))
            else:
                logger.debug(f"[A12] Skipping unsupported file: {file_path}")

        results = await asyncio.gather(*tasks)

        results_by_file = {r["file"]: r for r in results}
        all_findings = []
        for result in results:
            all_findings.extend(result.get("findings", []))

        summary = self._summarize_findings(all_findings)

        return {
            "success": True,
            "scanned_files": len(file_paths),
            "results_by_file": results_by_file,
            "all_findings": all_findings,
            "summary": summary,
        }

    # ========================================================================
    # Bandit Integration
    # ========================================================================

    async def _run_bandit(self, file_path: str, cwd: Optional[str] = None) -> dict:
        """
        Run Bandit on a Python file.

        Args:
            file_path: Path to Python file
            cwd: Working directory

        Returns:
            {
                "success": bool,
                "findings": list,
                "error": Optional[str],
                "tool_unavailable": bool
            }
        """
        cmd = ["bandit", "-r", file_path, "-f", "json"]

        result = await self.executor.run_with_timeout(cmd, cwd=cwd, timeout=self.timeout)

        if not result["success"]:
            if result.get("error") and "not found" in result["error"].lower():
                logger.warning("[A12] Bandit not installed")
                return {
                    "success": False,
                    "findings": [],
                    "error": "Bandit not installed",
                    "tool_unavailable": True,
                }

            if result.get("timed_out"):
                logger.warning(f"[A12] Bandit timed out on {file_path}")
                return {
                    "success": False,
                    "findings": [],
                    "error": "Bandit timed out",
                    "tool_unavailable": False,
                }

            return {
                "success": False,
                "findings": [],
                "error": result.get("error", "Unknown error"),
                "tool_unavailable": False,
            }

        try:
            output = json.loads(result["stdout"])
            findings = self._parse_bandit_findings(output.get("results", []))
            return {
                "success": True,
                "findings": findings,
                "error": None,
                "tool_unavailable": False,
            }
        except json.JSONDecodeError as e:
            logger.error(f"[A12] Failed to parse Bandit output: {e}")
            return {
                "success": False,
                "findings": [],
                "error": "Failed to parse Bandit output",
                "tool_unavailable": False,
            }

    def _parse_bandit_findings(self, results: list) -> list:
        """
        Parse Bandit JSON results into standardized finding format.

        Args:
            results: Bandit results array

        Returns:
            List of standardized findings
        """
        findings = []

        for result in results:
            finding = {
                "tool": "bandit",
                "severity": result.get("issue_severity", "MEDIUM").upper(),
                "confidence": result.get("issue_confidence", "MEDIUM").upper(),
                "cwe": result.get("issue_cwe", {}).get("id"),
                "message": result.get("issue_text", ""),
                "line": result.get("line_number"),
                "file": result.get("filename", ""),
                "test_id": result.get("test_id", ""),
                "test_name": result.get("test_name", ""),
            }
            findings.append(finding)

        return findings

    # ========================================================================
    # npm audit Integration
    # ========================================================================

    async def _run_npm_audit(self, file_path: str, cwd: Optional[str] = None) -> dict:
        """
        Run npm audit on a package.json file.

        Args:
            file_path: Path to package.json
            cwd: Working directory

        Returns:
            {
                "success": bool,
                "findings": list,
                "error": Optional[str],
                "tool_unavailable": bool
            }
        """
        # npm audit runs in the directory containing package.json
        if not cwd:
            cwd = os.path.dirname(file_path) or "."

        cmd = ["npm", "audit", "--json"]

        result = await self.executor.run_with_timeout(cmd, cwd=cwd, timeout=self.timeout)

        # npm audit exits with non-zero when vulnerabilities are found
        # We consider this successful if we can parse the output
        try:
            output = json.loads(result["stdout"])
            findings = self._parse_npm_audit_findings(output)
            return {
                "success": True,
                "findings": findings,
                "error": None,
                "tool_unavailable": False,
            }
        except json.JSONDecodeError:
            if result.get("error") and "not found" in result["error"].lower():
                logger.warning("[A12] npm audit not available")
                return {
                    "success": False,
                    "findings": [],
                    "error": "npm not installed",
                    "tool_unavailable": True,
                }

            if result.get("timed_out"):
                logger.warning("[A12] npm audit timed out")
                return {
                    "success": False,
                    "findings": [],
                    "error": "npm audit timed out",
                    "tool_unavailable": False,
                }

            logger.warning(f"[A12] npm audit parsing failed: {result.get('error')}")
            return {
                "success": False,
                "findings": [],
                "error": "Failed to parse npm audit output",
                "tool_unavailable": False,
            }

    def _parse_npm_audit_findings(self, audit_output: dict) -> list:
        """
        Parse npm audit JSON output into standardized finding format.

        Args:
            audit_output: npm audit JSON output

        Returns:
            List of standardized findings
        """
        findings = []

        # npm audit format: vulnerabilities -> package_name -> array of vuln objects
        for pkg_name, vuln_data in audit_output.get("vulnerabilities", {}).items():
            if not isinstance(vuln_data, dict):
                continue

            # Each vulnerability entry
            for key, vuln_info in vuln_data.items():
                if not isinstance(vuln_info, dict) or key == "name":
                    continue

                severity = vuln_info.get("severity", "medium").upper()
                # npm severities: critical, high, moderate, low
                if severity == "MODERATE":
                    severity = "MEDIUM"

                finding = {
                    "tool": "npm_audit",
                    "severity": severity,
                    "package": vuln_info.get("name", pkg_name),
                    "installed_version": vuln_info.get("version", ""),
                    "vulnerable_versions": vuln_info.get("vulnerable_versions", ""),
                    "message": vuln_info.get("title", ""),
                    "cwe": vuln_info.get("cwe", []),
                    "url": vuln_info.get("url", ""),
                    "cvss": vuln_info.get("cvss", {}),
                }
                findings.append(finding)

        return findings

    # ========================================================================
    # Semgrep Integration
    # ========================================================================

    def _convert_semgrep_findings(self, semgrep_results: list) -> list:
        """
        Convert Semgrep findings to standardized format.

        Args:
            semgrep_results: List of Semgrep finding objects

        Returns:
            List of standardized findings
        """
        findings = []

        for result in semgrep_results:
            severity = result.get("extra", {}).get("severity", "INFO").upper()
            # Map Semgrep severity to standard: ERROR -> CRITICAL, WARNING -> HIGH, etc.
            severity_map = {
                "ERROR": "CRITICAL",
                "WARNING": "HIGH",
                "INFO": "MEDIUM",
            }
            severity = severity_map.get(severity, "MEDIUM")

            finding = {
                "tool": "semgrep",
                "severity": severity,
                "check_id": result.get("check_id", ""),
                "message": result.get("extra", {}).get("message", ""),
                "file": result.get("path", ""),
                "line": result.get("start", {}).get("line", 0),
                "column": result.get("start", {}).get("col", 0),
                "metadata": result.get("extra", {}).get("metadata", {}),
            }
            findings.append(finding)

        return findings

    # ========================================================================
    # Utilities
    # ========================================================================

    def _summarize_findings(self, findings: list) -> dict:
        """
        Generate summary statistics from findings.

        Args:
            findings: List of findings

        Returns:
            {
                "total_findings": int,
                "by_severity": dict,
                "by_tool": dict,
                "critical_count": int,
                "high_count": int
            }
        """
        summary = {
            "total_findings": len(findings),
            "by_severity": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
            "by_tool": {},
        }

        for finding in findings:
            severity = finding.get("severity", "MEDIUM")
            if severity in summary["by_severity"]:
                summary["by_severity"][severity] += 1

            tool = finding.get("tool", "unknown")
            summary["by_tool"][tool] = summary["by_tool"].get(tool, 0) + 1

        summary["critical_count"] = summary["by_severity"]["CRITICAL"]
        summary["high_count"] = summary["by_severity"]["HIGH"]

        return summary
