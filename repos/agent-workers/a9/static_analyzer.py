"""
A9 Static Analyzer — Simplified code analysis utilities

Provides subprocess-based integration with pylint and eslint.
Used by Auditor for basic static analysis checks.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StaticAnalyzer:
    """Static code analysis wrapper"""

    @staticmethod
    async def analyze(file_path: str, language: str, content: str = "") -> dict:
        """
        Analyze code file using appropriate static analysis tool.

        Args:
            file_path: Path to file being analyzed
            language: Programming language ("python", "javascript", "typescript")
            content: File content (if analyzing from string)

        Returns:
            {
                "language": str,
                "errors": [{"line": int, "message": str, "severity": str}],
                "warnings": [{"line": int, "message": str, "severity": str}],
                "status": "ok|warning|error",
                "tool": "pylint|eslint|none"
            }
        """
        if language == "python":
            return await StaticAnalyzer._analyze_python(file_path, content)
        elif language in ["javascript", "typescript"]:
            return await StaticAnalyzer._analyze_javascript(file_path, content)
        else:
            return {
                "language": language,
                "errors": [],
                "warnings": [],
                "status": "ok",
                "tool": "none",
            }

    @staticmethod
    async def _analyze_python(file_path: str, content: str = "") -> dict:
        """Run pylint analysis on Python code"""
        errors = []
        warnings = []

        try:
            # Use provided content or read from file
            if content:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
            else:
                tmp_path = file_path

            result = subprocess.run(
                [
                    "pylint",
                    "--disable=all",
                    "--enable=E,W",
                    "--output-format=json",
                    tmp_path,
                ],
                capture_output=True,
                timeout=10,
                text=True,
            )

            if result.stdout:
                try:
                    import json

                    pylint_output = json.loads(result.stdout)
                    for issue in pylint_output:
                        issue_obj = {
                            "line": issue.get("line", 0),
                            "message": issue.get("message", ""),
                            "severity": "error" if issue.get("type") in ["error", "fatal"] else "warning",
                        }
                        if issue.get("type") in ["error", "fatal"]:
                            errors.append(issue_obj)
                        else:
                            warnings.append(issue_obj)
                except Exception as e:
                    logger.warning(f"[StaticAnalyzer] Failed to parse pylint output: {e}")

            if content:
                Path(tmp_path).unlink(missing_ok=True)

            status = "error" if errors else ("warning" if warnings else "ok")

            return {
                "language": "python",
                "errors": errors,
                "warnings": warnings,
                "status": status,
                "tool": "pylint",
            }

        except FileNotFoundError:
            logger.info("[StaticAnalyzer] pylint not installed")
            return {
                "language": "python",
                "errors": [],
                "warnings": [],
                "status": "ok",
                "tool": "none",
            }
        except subprocess.TimeoutExpired:
            logger.warning(f"[StaticAnalyzer] pylint timeout on {file_path}")
            return {
                "language": "python",
                "errors": [{"line": 0, "message": "Analysis timeout", "severity": "warning"}],
                "warnings": [],
                "status": "warning",
                "tool": "pylint",
            }
        except Exception as e:
            logger.error(f"[StaticAnalyzer] pylint error: {e}")
            return {
                "language": "python",
                "errors": [],
                "warnings": [],
                "status": "ok",
                "tool": "none",
            }

    @staticmethod
    async def _analyze_javascript(file_path: str, content: str = "") -> dict:
        """Run eslint analysis on JavaScript/TypeScript code"""
        errors = []
        warnings = []

        try:
            if content:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
            else:
                tmp_path = file_path

            result = subprocess.run(
                [
                    "eslint",
                    "--format=json",
                    "--no-eslintrc",
                    "--env=node,es2020",
                    tmp_path,
                ],
                capture_output=True,
                timeout=10,
                text=True,
            )

            if result.stdout:
                try:
                    import json

                    eslint_output = json.loads(result.stdout)
                    for file_report in eslint_output:
                        for message in file_report.get("messages", []):
                            issue_obj = {
                                "line": message.get("line", 0),
                                "message": message.get("message", ""),
                                "severity": "error" if message.get("severity") == 2 else "warning",
                            }
                            if message.get("severity") == 2:
                                errors.append(issue_obj)
                            else:
                                warnings.append(issue_obj)
                except Exception as e:
                    logger.warning(f"[StaticAnalyzer] Failed to parse eslint output: {e}")

            if content:
                Path(tmp_path).unlink(missing_ok=True)

            status = "error" if errors else ("warning" if warnings else "ok")

            return {
                "language": "javascript",
                "errors": errors,
                "warnings": warnings,
                "status": status,
                "tool": "eslint",
            }

        except FileNotFoundError:
            logger.info("[StaticAnalyzer] eslint not installed")
            return {
                "language": "javascript",
                "errors": [],
                "warnings": [],
                "status": "ok",
                "tool": "none",
            }
        except subprocess.TimeoutExpired:
            logger.warning(f"[StaticAnalyzer] eslint timeout on {file_path}")
            return {
                "language": "javascript",
                "errors": [{"line": 0, "message": "Analysis timeout", "severity": "warning"}],
                "warnings": [],
                "status": "warning",
                "tool": "eslint",
            }
        except Exception as e:
            logger.error(f"[StaticAnalyzer] eslint error: {e}")
            return {
                "language": "javascript",
                "errors": [],
                "warnings": [],
                "status": "ok",
                "tool": "none",
            }
