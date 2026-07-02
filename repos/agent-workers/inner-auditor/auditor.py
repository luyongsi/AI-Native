"""
Inner Auditor — Real toolchain integration for quality-gate checks.

Runs lint, type-check, and security scans against changed files using:
- ESLint/Pylint for linting
- mypy/tsc for type checking
- Semgrep/bandit for security scanning
- Pattern-based detection for common vulnerabilities

Gracefully degrades if tools are unavailable.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from .enhanced_static_analyzer import EnhancedStaticAnalyzer
from .security_rules import SecurityRules
from .semgrep_analyzer import SemgrepAnalyzer
from .tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class InnerAuditor:
    """Runs real quality checks on changed files before Dev Agent submits code."""

    def __init__(self, timeout: int = 30, enable_semgrep: bool = True):
        """
        Initialize Inner Auditor with real tools.

        Args:
            timeout: Timeout for tool execution in seconds
            enable_semgrep: Whether to use Semgrep for security scanning
        """
        self.timeout = timeout
        self.enable_semgrep = enable_semgrep

        self.static_analyzer = EnhancedStaticAnalyzer(timeout=timeout)
        self.semgrep_analyzer = SemgrepAnalyzer(timeout=timeout)
        self.executor = ToolExecutor(timeout=timeout)

        self.tools = {
            "lint": "pylint / eslint / golangci-lint",
            "type_check": "mypy / tsc / (Go/Rust native)",
            "security_scan": "semgrep / bandit / pattern-based",
        }

    # ------------------------------------------------------------------
    # Lint Check
    # ------------------------------------------------------------------

    async def run_lint(self, file_paths: list[str]) -> dict:
        """
        Run linting on files using language-appropriate tools.

        Args:
            file_paths: List of file paths to lint.

        Returns:
            {
                "tool": str,
                "issues": list,
                "error_count": int,
                "warning_count": int,
                "mock": bool,
                "by_file": dict
            }
        """
        logger.info(f"[InnerAuditor] Running lint on {len(file_paths)} file(s): {self.tools['lint']}")

        if not file_paths:
            return {
                "tool": self.tools["lint"],
                "issues": [],
                "error_count": 0,
                "warning_count": 0,
                "mock": False,
                "by_file": {},
            }

        # Group files by language
        by_language = self._group_by_language(file_paths)

        all_issues = []
        by_file = {}

        # Analyze files per language
        for language, paths in by_language.items():
            for file_path in paths:
                if not self._file_exists(file_path):
                    logger.warning(f"[InnerAuditor] File not found: {file_path}")
                    continue

                try:
                    result = await self.static_analyzer.analyze_comprehensive(file_path, language)

                    formatted_issues = []
                    for issue in result.get("merged_issues", []):
                        formatted_issues.append({
                            "file": file_path,
                            "line": issue.get("line", 0),
                            "column": issue.get("column", 0),
                            "severity": "error",
                            "message": issue.get("message", ""),
                            "tool": result.get("tools", {}).get(list(result.get("tools", {}).keys())[0], {}).get("tool"),
                        })

                    for warning in result.get("merged_warnings", []):
                        formatted_issues.append({
                            "file": file_path,
                            "line": warning.get("line", 0),
                            "column": warning.get("column", 0),
                            "severity": "warning",
                            "message": warning.get("message", ""),
                            "tool": result.get("tools", {}).get(list(result.get("tools", {}).keys())[0], {}).get("tool"),
                        })

                    all_issues.extend(formatted_issues)
                    by_file[file_path] = formatted_issues

                except Exception as e:
                    logger.error(f"[InnerAuditor] Lint error on {file_path}: {e}")

        # Count by severity
        errors = [i for i in all_issues if i["severity"] == "error"]
        warnings = [i for i in all_issues if i["severity"] == "warning"]

        return {
            "tool": self.tools["lint"],
            "issues": errors + warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "mock": False,
            "by_file": by_file,
        }

    # ------------------------------------------------------------------
    # Type Check
    # ------------------------------------------------------------------

    async def run_type_check(self, file_paths: list[str]) -> dict:
        """
        Run type checking on files using language-appropriate tools.

        Args:
            file_paths: List of file paths to type-check.

        Returns:
            {
                "tool": str,
                "errors": list,
                "error_count": int,
                "mock": bool,
                "by_file": dict
            }
        """
        logger.info(f"[InnerAuditor] Running type check on {len(file_paths)} file(s): {self.tools['type_check']}")

        if not file_paths:
            return {
                "tool": self.tools["type_check"],
                "errors": [],
                "error_count": 0,
                "mock": False,
                "by_file": {},
            }

        # Group files by language
        by_language = self._group_by_language(file_paths)

        all_errors = []
        by_file = {}

        # Run type checks per language
        for language, paths in by_language.items():
            if language == "python":
                # Run mypy
                for file_path in paths:
                    if not self._file_exists(file_path):
                        continue

                    try:
                        result = await self.executor.run_with_timeout(
                            ["mypy", "--json", file_path],
                            timeout=self.timeout,
                        )

                        if result["success"] or result["stdout"]:
                            try:
                                import json
                                errors_found = json.loads(result["stdout"])
                                for error in errors_found if isinstance(errors_found, list) else []:
                                    formatted_error = {
                                        "file": file_path,
                                        "line": error.get("line", 0),
                                        "column": error.get("column", 0),
                                        "code": error.get("code", ""),
                                        "message": error.get("message", ""),
                                    }
                                    all_errors.append(formatted_error)
                                    if file_path not in by_file:
                                        by_file[file_path] = []
                                    by_file[file_path].append(formatted_error)
                            except Exception as e:
                                logger.debug(f"[InnerAuditor] Failed to parse mypy output: {e}")

                    except Exception as e:
                        logger.debug(f"[InnerAuditor] mypy error on {file_path}: {e}")

            elif language in ["typescript"]:
                # Run tsc
                for file_path in paths:
                    if not self._file_exists(file_path):
                        continue

                    try:
                        result = await self.executor.run_with_timeout(
                            ["tsc", "--noEmit", "--listFilesOnly", file_path],
                            timeout=self.timeout,
                        )

                        if not result["success"] and result["stderr"]:
                            # Parse TypeScript errors from stderr
                            for line in result["stderr"].split("\n"):
                                if "error TS" in line:
                                    formatted_error = {
                                        "file": file_path,
                                        "line": 0,
                                        "column": 0,
                                        "code": "",
                                        "message": line.strip(),
                                    }
                                    all_errors.append(formatted_error)

                    except Exception as e:
                        logger.debug(f"[InnerAuditor] tsc error on {file_path}: {e}")

        return {
            "tool": self.tools["type_check"],
            "errors": all_errors,
            "error_count": len(all_errors),
            "mock": False,
            "by_file": by_file,
        }

    # ------------------------------------------------------------------
    # Security Scan
    # ------------------------------------------------------------------

    async def run_security_scan(self, file_paths: list[str]) -> dict:
        """
        Run security scanning using Semgrep and pattern-based detection.

        Args:
            file_paths: List of file paths to scan.

        Returns:
            {
                "tool": str,
                "vulnerabilities": list,
                "critical_count": int,
                "high_count": int,
                "medium_count": int,
                "low_count": int,
                "mock": bool,
                "by_file": dict
            }
        """
        logger.info(
            f"[InnerAuditor] Running security scan on {len(file_paths)} file(s): {self.tools['security_scan']}"
        )

        if not file_paths:
            return {
                "tool": self.tools["security_scan"],
                "vulnerabilities": [],
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "mock": False,
                "by_file": {},
            }

        all_vulnerabilities = []
        by_file = {}

        # First, try Semgrep if enabled
        if self.enable_semgrep:
            try:
                semgrep_result = await self.semgrep_analyzer.scan_multiple(file_paths)

                if not semgrep_result.get("tool_unavailable"):
                    for finding in semgrep_result.get("all_findings", []):
                        path = finding.get("path", "unknown")
                        line = finding.get("start", {}).get("line", 0)

                        severity_map = {
                            "CRITICAL": "critical",
                            "HIGH": "high",
                            "MEDIUM": "medium",
                            "LOW": "low",
                            "INFO": "low",
                        }

                        vuln = {
                            "file": path,
                            "line": line,
                            "severity": severity_map.get(
                                finding.get("extra", {}).get("severity", "INFO").upper(),
                                "low",
                            ),
                            "rule": finding.get("check_id", "unknown"),
                            "message": finding.get("extra", {}).get("message", ""),
                            "source": "semgrep",
                        }

                        all_vulnerabilities.append(vuln)
                        if path not in by_file:
                            by_file[path] = []
                        by_file[path].append(vuln)

            except Exception as e:
                logger.warning(f"[InnerAuditor] Semgrep scan failed: {e}")

        # Also run pattern-based security checks
        try:
            for file_path in file_paths:
                if not self._file_exists(file_path):
                    continue

                try:
                    content = Path(file_path).read_text(errors="replace")
                    language = self._detect_language(file_path)

                    vulnerabilities = SecurityRules.scan_content(content, language)

                    for vuln_data in vulnerabilities:
                        vuln = {
                            "file": file_path,
                            "line": vuln_data["line"],
                            "severity": "critical" if vuln_data["severity"] == "CRITICAL" else "high",
                            "rule": vuln_data["rule"],
                            "message": vuln_data["message"],
                            "source": "pattern-based",
                            "cwe": vuln_data.get("cwe", ""),
                        }

                        all_vulnerabilities.append(vuln)
                        if file_path not in by_file:
                            by_file[file_path] = []
                        by_file[file_path].append(vuln)

                except Exception as e:
                    logger.debug(f"[InnerAuditor] Pattern scan error on {file_path}: {e}")

        except Exception as e:
            logger.warning(f"[InnerAuditor] Pattern-based security scan failed: {e}")

        # Count by severity
        critical = [v for v in all_vulnerabilities if v["severity"] == "critical"]
        high = [v for v in all_vulnerabilities if v["severity"] == "high"]
        medium = [v for v in all_vulnerabilities if v["severity"] == "medium"]
        low = [v for v in all_vulnerabilities if v["severity"] == "low"]

        return {
            "tool": self.tools["security_scan"],
            "vulnerabilities": critical + high + medium + low,
            "critical_count": len(critical),
            "high_count": len(high),
            "medium_count": len(medium),
            "low_count": len(low),
            "mock": False,
            "by_file": by_file,
        }

    # ------------------------------------------------------------------
    # Run All Checks
    # ------------------------------------------------------------------

    async def run_all(self, file_paths: list[str]) -> dict:
        """
        Run all three checks (lint, type-check, security) in parallel.

        Args:
            file_paths: List of file paths to check.

        Returns:
            dict with keys: lint, type_check, security_scan — each the result of the respective check.
        """
        logger.info(f"[InnerAuditor] Running all checks on {len(file_paths)} file(s) in parallel")

        lint_result, type_check_result, security_result = await asyncio.gather(
            self.run_lint(file_paths),
            self.run_type_check(file_paths),
            self.run_security_scan(file_paths),
        )

        return {
            "lint": lint_result,
            "type_check": type_check_result,
            "security_scan": security_result,
        }

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    def _group_by_language(self, file_paths: list[str]) -> dict:
        """
        Group files by programming language.

        Args:
            file_paths: List of file paths

        Returns:
            dict mapping language to list of file paths
        """
        by_language = {}

        for path in file_paths:
            language = self._detect_language(path)
            if language not in by_language:
                by_language[language] = []
            by_language[language].append(path)

        return by_language

    def _detect_language(self, file_path: str) -> str:
        """
        Detect programming language from file extension.

        Args:
            file_path: File path

        Returns:
            Language string
        """
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".cs": "csharp",
            ".rb": "ruby",
            ".php": "php",
        }

        suffix = Path(file_path).suffix.lower()
        return ext_map.get(suffix, "unknown")

    def _file_exists(self, file_path: str) -> bool:
        """
        Check if file exists and is readable.

        Args:
            file_path: File path

        Returns:
            True if file exists and is readable
        """
        try:
            return Path(file_path).is_file() and Path(file_path).stat().st_size > 0
        except Exception:
            return False
