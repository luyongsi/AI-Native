"""
Mutation Tester — Executes mutation testing via mutmut (Python) and Stryker (JS/TS).

Orchestrates mutation test execution, result parsing, and survived mutation analysis.
Provides unified interface for both Python and JavaScript/TypeScript projects.
"""

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MutationTester:
    """Executes mutation tests using mutmut (Python) or Stryker (JS/TS)."""

    def __init__(self, timeout: int = 300):
        """
        Initialize the mutation tester.

        Args:
            timeout: Maximum execution time in seconds (default 5 minutes)
        """
        self.timeout = timeout

    async def run_mutmut(
        self,
        project_path: str,
        target_file: Optional[str] = None,
        tests_dir: str = "tests",
    ) -> dict:
        """
        Run mutmut mutation testing on Python code.

        Args:
            project_path: Root directory of the project
            target_file: Optional specific file to mutate
            tests_dir: Directory containing tests (default: tests)

        Returns:
            dict with keys: survived[], killed[], mutation_score, total_mutations
        """
        logger.info(f"[MutationTester] Running mutmut on {project_path}")

        project_path = str(Path(project_path).resolve())
        tests_dir = str(Path(project_path) / tests_dir)

        try:
            # Run mutmut
            cmd = ["mutmut", "run", "--paths-to-mutate", project_path]
            if target_file:
                cmd.extend(["--paths-to-mutate", target_file])
            cmd.extend(["--tests-dir", tests_dir])

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    result.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"[MutationTester] mutmut timeout after {self.timeout}s")
                result.kill()
                return self._empty_result()

            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            if result.returncode not in (0, 1):
                logger.warning(
                    f"[MutationTester] mutmut returned {result.returncode}: {stderr_str}"
                )

            # Get results
            results = await self._get_mutmut_results(project_path)
            parsed = self._parse_mutmut_results(results)

            logger.info(
                f"[MutationTester] mutmut score: {parsed['mutation_score']:.1%} "
                f"({len(parsed['killed'])} killed, {len(parsed['survived'])} survived)"
            )

            return parsed

        except FileNotFoundError:
            logger.error("[MutationTester] mutmut not found, install with: pip install mutmut")
            return self._empty_result()
        except Exception as e:
            logger.error(f"[MutationTester] mutmut execution failed: {e}")
            return self._empty_result()

    async def run_stryker(
        self,
        project_path: str,
        config_path: Optional[str] = None,
    ) -> dict:
        """
        Run Stryker mutation testing on JavaScript/TypeScript code.

        Args:
            project_path: Root directory of the project
            config_path: Optional path to stryker.conf.json

        Returns:
            dict with keys: survived[], killed[], mutation_score, total_mutations
        """
        logger.info(f"[MutationTester] Running Stryker on {project_path}")

        project_path = str(Path(project_path).resolve())

        try:
            # Run Stryker
            cmd = ["npx", "stryker", "run"]
            if config_path:
                cmd.extend(["--configFile", config_path])

            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    result.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"[MutationTester] Stryker timeout after {self.timeout}s")
                result.kill()
                return self._empty_result()

            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            if result.returncode != 0:
                logger.warning(
                    f"[MutationTester] Stryker returned {result.returncode}: {stderr_str}"
                )

            # Try to load report
            report_path = Path(project_path) / "reports" / "mutation" / "mutation.json"
            if report_path.exists():
                with open(report_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                parsed = self._parse_stryker_results(data)
            else:
                logger.warning(
                    f"[MutationTester] Stryker report not found at {report_path}"
                )
                parsed = self._parse_stryker_stdout(stdout_str)

            logger.info(
                f"[MutationTester] Stryker score: {parsed['mutation_score']:.1%} "
                f"({len(parsed['killed'])} killed, {len(parsed['survived'])} survived)"
            )

            return parsed

        except FileNotFoundError:
            logger.error("[MutationTester] npx/Stryker not found")
            return self._empty_result()
        except Exception as e:
            logger.error(f"[MutationTester] Stryker execution failed: {e}")
            return self._empty_result()

    async def _get_mutmut_results(self, project_path: str) -> str:
        """Get mutmut results in JSON format."""
        try:
            cmd = ["mutmut", "results", "--json"]
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
            )

            stdout, stderr = await asyncio.wait_for(
                result.communicate(), timeout=30
            )
            return stdout.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"[MutationTester] Failed to get mutmut results: {e}")
            return ""

    def _parse_mutmut_results(self, output: str) -> dict:
        """Parse mutmut JSON output."""
        survived = []
        killed = []

        try:
            data = json.loads(output)
            for file_path, mutations in data.items():
                for mut_id, mut_data in mutations.items():
                    status = mut_data.get("status", "unknown")
                    mutation_entry = {
                        "id": mut_id,
                        "file": file_path,
                        "location": {
                            "line": mut_data.get("line", 0),
                            "column": mut_data.get("column", 0),
                        },
                        "mutator": mut_data.get("mutation_type", "unknown"),
                        "original": mut_data.get("original_source", ""),
                        "mutated": mut_data.get("mutated_source", ""),
                    }

                    if status == "survived":
                        survived.append(mutation_entry)
                    elif status == "killed":
                        killed.append(mutation_entry)
        except json.JSONDecodeError:
            logger.warning("[MutationTester] Could not parse mutmut JSON output")

        total = len(survived) + len(killed)
        score = (len(killed) / total * 100) if total > 0 else 100.0

        return {
            "survived": survived,
            "killed": killed,
            "mutation_score": score / 100.0,
            "total_mutations": total,
        }

    def _parse_stryker_results(self, data: dict) -> dict:
        """Parse Stryker JSON report."""
        survived = []
        killed = []

        for file_data in data.get("files", {}).values():
            for mutant in file_data.get("mutants", []):
                mutation_entry = {
                    "id": mutant.get("id", ""),
                    "location": mutant.get("location", {}),
                    "mutator": mutant.get("mutatorName", "unknown"),
                    "original": mutant.get("originalLines", ""),
                    "mutated": mutant.get("mutatedLines", ""),
                }

                status = mutant.get("status", "unknown")
                if status == "Survived":
                    survived.append(mutation_entry)
                elif status == "Killed":
                    killed.append(mutation_entry)

        total = len(survived) + len(killed)
        score = data.get("mutationScore", 0) / 100.0

        return {
            "survived": survived,
            "killed": killed,
            "mutation_score": score,
            "total_mutations": total,
        }

    def _parse_stryker_stdout(self, stdout: str) -> dict:
        """Parse Stryker results from stdout if JSON report unavailable."""
        # Try to extract mutation score from stdout
        # e.g., "Mutation score: 87.5%"
        match = re.search(r"Mutation score:\s*([\d.]+)%", stdout)
        score = float(match.group(1)) / 100.0 if match else 0.0

        return {
            "survived": [],
            "killed": [],
            "mutation_score": score,
            "total_mutations": 0,
        }

    def _empty_result(self) -> dict:
        """Return empty result dict."""
        return {
            "survived": [],
            "killed": [],
            "mutation_score": 0.0,
            "total_mutations": 0,
        }
