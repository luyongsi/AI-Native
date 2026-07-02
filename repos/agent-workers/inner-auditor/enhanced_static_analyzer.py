"""
Enhanced Static Analyzer — Multi-tool code analysis integration.

Supports pylint/mypy (Python), ESLint (JavaScript/TypeScript), golangci-lint (Go),
and clippy (Rust). Runs multiple tools per language with timeout control and
graceful degradation.
"""

import asyncio
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional

from .tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class EnhancedStaticAnalyzer:
    """Multi-tool static analysis with timeout and error handling."""

    # Tool configuration per language
    TOOL_CHAINS = {
        "python": {
            "tools": [
                {"name": "pylint", "args": ["pylint", "--output-format=json", "--disable=all", "--enable=E,W"]},
                {"name": "mypy", "args": ["mypy", "--json"]},
                {"name": "bandit", "args": ["bandit", "--format=json", "-r"]},
            ],
            "primary": "pylint",
        },
        "javascript": {
            "tools": [
                {"name": "eslint", "args": ["eslint", "--format=json", "--no-eslintrc", "--env=node,es2020"]},
            ],
            "primary": "eslint",
        },
        "typescript": {
            "tools": [
                {"name": "eslint", "args": ["eslint", "--format=json", "--no-eslintrc", "--env=node,es2020", "--ext=.ts"]},
            ],
            "primary": "eslint",
        },
        "go": {
            "tools": [
                {"name": "golangci-lint", "args": ["golangci-lint", "run", "--out-format=json"]},
            ],
            "primary": "golangci-lint",
        },
        "rust": {
            "tools": [
                {"name": "clippy", "args": ["cargo", "clippy", "--message-format=json"]},
            ],
            "primary": "clippy",
        },
    }

    def __init__(self, timeout: int = 30):
        """
        Initialize enhanced static analyzer.

        Args:
            timeout: Default timeout for tool execution in seconds
        """
        self.executor = ToolExecutor(timeout=timeout)
        self.timeout = timeout

    async def analyze_comprehensive(
        self,
        file_path: str,
        language: str,
        content: Optional[str] = None,
    ) -> dict:
        """
        Run comprehensive analysis using all available tools for language.

        Args:
            file_path: Path to file
            language: Programming language
            content: Optional file content (if analyzing from string)

        Returns:
            {
                "language": str,
                "file": str,
                "tools": dict,
                "merged_issues": list,
                "merged_warnings": list,
                "status": "ok|warning|error",
                "all_available": bool
            }
        """
        tool_chains = self.TOOL_CHAINS.get(language, {})

        if not tool_chains:
            logger.info(f"[EnhancedStaticAnalyzer] No tools configured for {language}")
            return {
                "language": language,
                "file": file_path,
                "tools": {},
                "merged_issues": [],
                "merged_warnings": [],
                "status": "ok",
                "all_available": False,
            }

        # Write content to temporary file if provided
        actual_path = file_path
        if content:
            try:
                suffix = Path(file_path).suffix or ".tmp"
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=suffix,
                    delete=False,
                    encoding="utf-8",
                ) as tmp:
                    tmp.write(content)
                    actual_path = tmp.name
            except Exception as e:
                logger.error(f"[EnhancedStaticAnalyzer] Failed to create temp file: {e}")
                actual_path = file_path

        try:
            # Run all tools in parallel
            tools_config = tool_chains.get("tools", [])
            tasks = [
                self._run_tool(tool["name"], tool["args"], actual_path)
                for tool in tools_config
            ]

            tool_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            tools_output = {}
            all_issues = []
            all_warnings = []
            any_available = False

            for tool_config, result in zip(tools_config, tool_results):
                tool_name = tool_config["name"]

                if isinstance(result, Exception):
                    tools_output[tool_name] = {
                        "success": False,
                        "error": str(result),
                        "issues": [],
                        "warnings": [],
                    }
                else:
                    tools_output[tool_name] = result
                    if result.get("success") or (result.get("issues") or result.get("warnings")):
                        any_available = True

                    all_issues.extend(result.get("issues", []))
                    all_warnings.extend(result.get("warnings", []))

            # Determine status
            status = "error" if all_issues else ("warning" if all_warnings else "ok")

            return {
                "language": language,
                "file": file_path,
                "tools": tools_output,
                "merged_issues": all_issues,
                "merged_warnings": all_warnings,
                "status": status,
                "all_available": any_available,
            }

        finally:
            # Clean up temporary file
            if content and actual_path != file_path:
                try:
                    Path(actual_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.debug(f"[EnhancedStaticAnalyzer] Failed to clean temp file: {e}")

    async def _run_tool(
        self,
        tool_name: str,
        args: list,
        file_path: str,
    ) -> dict:
        """
        Run a single analysis tool.

        Args:
            tool_name: Name of the tool
            args: Command arguments (without file path)
            file_path: Path to file to analyze

        Returns:
            {
                "success": bool,
                "tool": str,
                "issues": list,
                "warnings": list,
                "raw_output": str,
                "error": Optional[str]
            }
        """
        cmd = args + [file_path]

        result = await self.executor.run_with_timeout(cmd, timeout=self.timeout)

        if not result["success"]:
            if result["error"] and "not found" in result["error"].lower():
                logger.debug(f"[EnhancedStaticAnalyzer] {tool_name} not available")
            elif result["timed_out"]:
                logger.warning(f"[EnhancedStaticAnalyzer] {tool_name} timed out on {file_path}")

            return {
                "success": False,
                "tool": tool_name,
                "issues": [],
                "warnings": [],
                "raw_output": result.get("stderr", ""),
                "error": result.get("error"),
            }

        # Parse tool-specific output
        issues, warnings = self._parse_output(tool_name, result["stdout"])

        return {
            "success": True,
            "tool": tool_name,
            "issues": issues,
            "warnings": warnings,
            "raw_output": result["stdout"],
            "error": None,
        }

    def _parse_output(self, tool_name: str, output: str) -> tuple:
        """
        Parse tool output based on tool type.

        Args:
            tool_name: Name of the tool
            output: Raw tool output

        Returns:
            (issues, warnings) lists
        """
        issues = []
        warnings = []

        try:
            if tool_name in ["pylint", "eslint", "bandit", "golangci-lint"]:
                # JSON-based tools
                results = json.loads(output)

                if tool_name == "pylint":
                    for item in results if isinstance(results, list) else []:
                        severity = item.get("type", "").lower()
                        issue = {
                            "line": item.get("line", 0),
                            "column": item.get("column", 0),
                            "message": item.get("message", ""),
                            "symbol": item.get("symbol", ""),
                        }
                        if severity in ["error", "fatal"]:
                            issues.append(issue)
                        else:
                            warnings.append(issue)

                elif tool_name == "eslint":
                    for file_result in results if isinstance(results, list) else []:
                        for msg in file_result.get("messages", []):
                            issue = {
                                "line": msg.get("line", 0),
                                "column": msg.get("column", 0),
                                "message": msg.get("message", ""),
                                "rule": msg.get("ruleId", ""),
                            }
                            if msg.get("severity", 1) == 2:
                                issues.append(issue)
                            else:
                                warnings.append(issue)

                elif tool_name == "bandit":
                    results_list = results.get("results", [])
                    for item in results_list:
                        severity = item.get("severity", "").lower()
                        issue = {
                            "line": item.get("line_number", 0),
                            "message": item.get("issue_text", ""),
                            "test_id": item.get("test_id", ""),
                        }
                        if severity == "high":
                            issues.append(issue)
                        else:
                            warnings.append(issue)

            elif tool_name == "mypy":
                # mypy line-based output
                for line in output.split("\n"):
                    if line.strip() and "error:" in line.lower():
                        issues.append({"message": line.strip()})
                    elif line.strip() and "note:" in line.lower():
                        warnings.append({"message": line.strip()})

            elif tool_name == "clippy":
                # Rust clippy JSON output
                for line in output.split("\n"):
                    if line.strip():
                        try:
                            item = json.loads(line)
                            if item.get("level") == "error":
                                issues.append({"message": item.get("message", "")})
                            else:
                                warnings.append({"message": item.get("message", "")})
                        except json.JSONDecodeError:
                            pass

        except Exception as e:
            logger.error(f"[EnhancedStaticAnalyzer] Failed to parse {tool_name} output: {e}")

        return issues, warnings
