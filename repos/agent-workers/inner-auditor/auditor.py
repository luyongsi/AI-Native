"""
Inner Auditor — quality-gate checks run before code submission.

Runs lint, type-check, and security scans against changed files.
All methods are async stubs that return realistic mock outputs.
Replace with real tool invocations (ESLint, Pylint, tsc, mypy, bandit, semgrep)
when moving to production.
"""

import asyncio
import logging
import random

logger = logging.getLogger(__name__)


class InnerAuditor:
    """Runs quality checks on changed files before Dev Agent submits code."""

    def __init__(self):
        self.tools = {
            "lint": "eslint / pylint",
            "type_check": "tsc / mypy",
            "security_scan": "bandit / semgrep",
        }

    # ------------------------------------------------------------------
    # Lint Check
    # ------------------------------------------------------------------

    async def run_lint(self, file_paths: list[str]) -> dict:
        """
        Simulate running a linter (ESLint for JS/TS, Pylint for Python).

        Args:
            file_paths: List of file paths to lint.

        Returns:
            dict with keys: tool, issues (list), error_count, warning_count, mock
        """
        logger.info(f"[InnerAuditor] Running lint on {len(file_paths)} file(s): {self.tools['lint']}")

        if not file_paths:
            return {
                "tool": self.tools["lint"],
                "issues": [],
                "error_count": 0,
                "warning_count": 0,
                "mock": True,
            }

        # Realistic mock: some files have issues, some don't
        issues = []
        for fp in file_paths:
            # Simulate occasional lint issues
            if random.random() < 0.3:
                issues.append({
                    "file": fp,
                    "line": random.randint(10, 200),
                    "column": random.randint(1, 80),
                    "severity": random.choice(["error", "warning"]),
                    "rule": random.choice([
                        "no-unused-vars",
                        "max-len",
                        "import/order",
                        "missing-type-annotation",
                    ]),
                    "message": f"[STUB] Lint issue in {fp} — would be a real finding in production",
                })

        # Sort: errors first, then warnings
        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]

        return {
            "tool": self.tools["lint"],
            "issues": errors + warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "mock": True,
        }

    # ------------------------------------------------------------------
    # Type Check
    # ------------------------------------------------------------------

    async def run_type_check(self, file_paths: list[str]) -> dict:
        """
        Simulate running a type checker (tsc for TypeScript, mypy for Python).

        Args:
            file_paths: List of file paths to type-check.

        Returns:
            dict with keys: tool, errors (list), error_count, mock
        """
        logger.info(f"[InnerAuditor] Running type check on {len(file_paths)} file(s): {self.tools['type_check']}")

        if not file_paths:
            return {
                "tool": self.tools["type_check"],
                "errors": [],
                "error_count": 0,
                "mock": True,
            }

        errors = []
        for fp in file_paths:
            # Simulate occasional type errors (less frequent than lint)
            if random.random() < 0.15:
                errors.append({
                    "file": fp,
                    "line": random.randint(5, 150),
                    "column": random.randint(1, 60),
                    "code": random.choice([
                        "TS2322", "TS2345", "TS2339",
                        "mypy[arg-type]", "mypy[return-value]",
                    ]),
                    "message": f"[STUB] Type error in {fp} — would be a real mypy/tsc error in production",
                })

        return {
            "tool": self.tools["type_check"],
            "errors": errors,
            "error_count": len(errors),
            "mock": True,
        }

    # ------------------------------------------------------------------
    # Security Scan
    # ------------------------------------------------------------------

    async def run_security_scan(self, file_paths: list[str]) -> dict:
        """
        Simulate running a security scanner (bandit for Python, semgrep for general).

        Args:
            file_paths: List of file paths to scan.

        Returns:
            dict with keys: tool, vulnerabilities (list), critical_count, high_count, medium_count, low_count, mock
        """
        logger.info(f"[InnerAuditor] Running security scan on {len(file_paths)} file(s): {self.tools['security_scan']}")

        if not file_paths:
            return {
                "tool": self.tools["security_scan"],
                "vulnerabilities": [],
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "mock": True,
            }

        vulnerabilities = []
        for fp in file_paths:
            # Simulate occasional security findings (rare)
            if random.random() < 0.08:
                severity = random.choice(["critical", "high", "medium", "low"])
                vulnerabilities.append({
                    "file": fp,
                    "line": random.randint(1, 100),
                    "severity": severity,
                    "rule": random.choice([
                        "B301: pickle",
                        "B602: subprocess_shell",
                        "semgrep.sql-injection",
                        "semgrep.xss",
                    ]),
                    "message": f"[STUB] Security issue ({severity}) in {fp} — would be a real finding in production",
                })

        critical = [v for v in vulnerabilities if v["severity"] == "critical"]
        high = [v for v in vulnerabilities if v["severity"] == "high"]
        medium = [v for v in vulnerabilities if v["severity"] == "medium"]
        low = [v for v in vulnerabilities if v["severity"] == "low"]

        return {
            "tool": self.tools["security_scan"],
            "vulnerabilities": critical + high + medium + low,
            "critical_count": len(critical),
            "high_count": len(high),
            "medium_count": len(medium),
            "low_count": len(low),
            "mock": True,
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
