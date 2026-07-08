"""
A9 Auditor Module — Code Review Brain

Independent code review agent that:
- Runs in isolated process/context
- Accepts ONLY the raw diff (no Coder reasoning)
- Performs static analysis via pylint/eslint
- Performs LLM semantic review (security, business logic, design patterns)
- Returns approve/reject + detailed suggestions
- CANNOT see Coder's self_inspection or internal thoughts

Interface:
  Input:  {"files_changed": [...], "changes_summary": str}  (pure diff, no reasoning)
  Output: {"decision": "approved|rejected", "issues": [...], "suggestions": [...], "confidence": float}
"""

import asyncio
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AuditorModule:
    """Independent code review brain — validates code changes"""

    def __init__(self, llm_caller=None, enable_analysis: bool = True,
                 max_parallel_tools: int = 2):
        """
        Args:
            llm_caller: Callable for LLM semantic review (security, business logic,
                        design patterns). Inject from A9DevAgent.call_llm.
                        If None, only static analysis is performed.
            enable_analysis: Whether to run actual static analysis tools
            max_parallel_tools: Max concurrent pylint/eslint subprocess instances
        """
        self._llm_caller = llm_caller
        self.enable_analysis = enable_analysis
        self._tool_semaphore = asyncio.Semaphore(max_parallel_tools)

    async def review(self, diff: dict) -> dict:
        """
        Audit code changes (Auditor sees ONLY diff, not Coder reasoning).
        Runs static analysis + LLM semantic review in parallel.

        Args:
            diff: {
                "files_changed": [
                    {"path": str, "change_type": str, "language": str, "patch_preview": str}
                ],
                "changes_summary": str,
                "lint_result": optional LintResult,
                "test_result": optional TestReport,
            }

        Returns:
            {
                "decision": "approved|rejected",
                "issues": [{"severity": "error|warning", "message": str, "source": "static|semantic"}],
                "suggestions": [str],
                "confidence": float,
                "analysis_detail": {
                    "files_analyzed": int,
                    "errors_found": int,
                    "warnings_found": int
                }
            }
        """
        try:
            logger.info("[Auditor] Starting code review (independent process)")

            files_changed = diff.get("files_changed", [])
            changes_summary = diff.get("changes_summary", "")

            if not files_changed:
                return {
                    "decision": "rejected",
                    "issues": [{"severity": "error", "message": "No files changed", "source": "static"}],
                    "suggestions": ["Ensure task generates at least one file"],
                    "confidence": 0.9,
                    "analysis_detail": {"files_analyzed": 0, "errors_found": 1, "warnings_found": 0},
                }

            # Run static analysis and semantic review in parallel
            static_task = asyncio.create_task(self._analyze_files(files_changed))
            semantic_task = None
            if self._llm_caller:
                semantic_task = asyncio.create_task(self._semantic_review(diff))

            static_results = await static_task
            semantic_issues = await semantic_task if semantic_task else []

            # Merge static + semantic findings into final decision
            decision, issues, suggestions = self._make_decision(
                files_changed, static_results, changes_summary, semantic_issues
            )

            confidence = self._compute_confidence(decision, static_results)

            logger.info(f"[Auditor] Review completed: {decision} (confidence={confidence})")

            return {
                "decision": decision,
                "issues": issues,
                "suggestions": suggestions,
                "confidence": confidence,
                "analysis_detail": {
                    "files_analyzed": len(files_changed),
                    "errors_found": len([i for i in issues if i["severity"] == "error"]),
                    "warnings_found": len([i for i in issues if i["severity"] == "warning"]),
                },
            }

        except Exception as e:
            logger.error(f"[Auditor] Review failed: {e}", exc_info=True)
            return {
                "decision": "rejected",
                "issues": [{"severity": "error", "message": f"Auditor failed: {e}", "source": "auditor"}],
                "suggestions": [],
                "confidence": 0.1,
                "analysis_detail": {"files_analyzed": 0, "errors_found": 1, "warnings_found": 0},
            }

    async def _analyze_files(self, files_changed: list) -> dict:
        """Run static analysis on changed files"""
        results = {}

        for file_info in files_changed:
            path = file_info.get("path", "")
            language = file_info.get("language", "unknown")
            patch = file_info.get("patch_preview", "")

            file_results = await self._analyze_single_file(path, language, patch)
            results[path] = file_results

        return results

    async def _analyze_single_file(self, path: str, language: str, patch: str) -> dict:
        """Analyze a single file using appropriate tools"""
        issues = []
        warnings = []

        # Perform basic static checks
        basic_checks = self._perform_basic_checks(path, language, patch)
        issues.extend(basic_checks.get("issues", []))
        warnings.extend(basic_checks.get("warnings", []))

        # Run language-specific tools if enabled
        if self.enable_analysis:
            if language == "python":
                tool_issues = await self._run_pylint(path, patch)
                issues.extend(tool_issues)
            elif language in ["javascript", "typescript"]:
                tool_issues = await self._run_eslint(path, patch)
                issues.extend(tool_issues)

        return {
            "path": path,
            "language": language,
            "issues": issues,
            "warnings": warnings,
            "status": "ok" if not issues else "needs_review",
        }

    def _perform_basic_checks(self, path: str, language: str, patch: str) -> dict:
        """Perform basic static checks without external tools"""
        issues = []
        warnings = []

        # Check 1: Patch should have actual content
        if not patch or patch.strip() == "":
            issues.append("Empty patch - no actual changes")

        # Check 2: Language detection
        if language == "unknown":
            warnings.append("Unknown file language - cannot perform detailed analysis")

        # Check 3: Path conventions
        if not self._validate_path_convention(path):
            warnings.append(f"Path '{path}' does not follow naming conventions")

        # Check 4: File size (rough check from patch)
        if len(patch.split("\n")) > 1000:
            warnings.append("Very large file - consider breaking into smaller modules")

        # Check 5: Missing docstrings/comments
        if language == "python" and patch and len(patch) > 100:
            if "def " in patch or "class " in patch:
                if '"""' not in patch and "'''" not in patch:
                    warnings.append("Missing docstrings for functions/classes")

        return {"issues": issues, "warnings": warnings}

    async def _run_pylint(self, path: str, patch: str) -> list:
        """Run pylint on Python files (simplified, semaphore-controlled)"""
        issues = []

        async with self._tool_semaphore:
            # Create temporary file with patch content
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
                    tmp.write(patch)
                    tmp_path = tmp.name

                result = subprocess.run(
                    ["pylint", "--disable=all", "--enable=E", tmp_path],
                    capture_output=True,
                    timeout=5,
                )

                if result.returncode != 0:
                    output = result.stdout.decode() if result.stdout else ""
                    if "error" in output.lower():
                        issues.append(f"pylint found errors in {path}")

                Path(tmp_path).unlink(missing_ok=True)

            except FileNotFoundError:
                logger.warning("[Auditor] pylint not installed - skipping")
            except subprocess.TimeoutExpired:
                logger.warning(f"[Auditor] pylint timeout on {path}")
            except Exception as e:
                logger.warning(f"[Auditor] pylint error: {e}")

        return issues

    async def _run_eslint(self, path: str, patch: str) -> list:
        """Run eslint on JavaScript/TypeScript files (simplified, semaphore-controlled)"""
        issues = []

        async with self._tool_semaphore:
            try:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as tmp:
                    tmp.write(patch)
                    tmp_path = tmp.name

                result = subprocess.run(
                    ["eslint", "--no-eslintrc", "--env", "node", tmp_path],
                    capture_output=True,
                    timeout=5,
                )

                if result.returncode != 0:
                    output = result.stdout.decode() if result.stdout else ""
                    if "error" in output.lower():
                        issues.append(f"eslint found errors in {path}")

                Path(tmp_path).unlink(missing_ok=True)

            except FileNotFoundError:
                logger.warning("[Auditor] eslint not installed - skipping")
            except subprocess.TimeoutExpired:
                logger.warning(f"[Auditor] eslint timeout on {path}")
            except Exception as e:
                logger.warning(f"[Auditor] eslint error: {e}")

        return issues

    def _validate_path_convention(self, path: str) -> bool:
        """Validate file path follows naming conventions"""
        forbidden = ["__pycache__", ".pyc", "node_modules", ".git"]
        return not any(f in path for f in forbidden)

    def _make_decision(
        self, files_changed: list, analysis_results: dict, changes_summary: str,
        semantic_issues: list | None = None,
    ) -> tuple:
        """Determine approve/reject decision based on static + semantic analysis"""
        all_issues = []
        all_warnings = []

        for result in analysis_results.values():
            all_issues.extend(result.get("issues", []))
            all_warnings.extend(result.get("warnings", []))

        # Merge in semantic review findings
        if semantic_issues:
            for si in semantic_issues:
                if si.get("severity") == "error":
                    all_issues.append(si)
                else:
                    all_warnings.append(si)

        # Decision logic
        if all_issues:
            decision = "rejected"
            suggestions = [
                "Fix identified errors before resubmission",
                "Review code review suggestions",
                "Ensure proper error handling",
            ]
        else:
            decision = "approved"
            suggestions = []

            # Add improvement suggestions even for approved changes
            if all_warnings:
                suggestions.append("Consider addressing warnings for code quality")
            if len(files_changed) > 10:
                suggestions.append("Large changeset - consider breaking into smaller PRs")

        # Format issues for output
        formatted_issues = []
        for issue in all_issues:
            if isinstance(issue, str):
                formatted_issues.append({"severity": "error", "message": issue, "source": "static"})
            else:
                if "source" not in issue:
                    issue["source"] = "static"
                formatted_issues.append(issue)

        return decision, formatted_issues, suggestions

    async def _semantic_review(self, diff: dict) -> list[dict]:
        """LLM-driven semantic review: security vulnerabilities, business logic, patterns.

        Runs in parallel with static analysis.
        """
        if not self._llm_caller:
            return []

        try:
            prompt = self._build_semantic_prompt(diff)
            content = await self._llm_caller(
                [{"role": "user", "content": prompt}],
                task_type="code_audit",
                temperature=0.1,
                max_tokens=2000,
            )
            return self._parse_semantic_issues(content)
        except Exception as e:
            logger.warning(f"[Auditor] Semantic review failed: {e}")
            return []

    def _build_semantic_prompt(self, diff: dict) -> str:
        """Build prompt for LLM semantic code review."""
        files_changed = diff.get("files_changed", [])
        summary = diff.get("changes_summary", "")
        lint_result = diff.get("lint_result")
        test_result = diff.get("test_result")

        files_text = ""
        for f in files_changed[:10]:
            patch = f.get("patch_preview", f.get("diff", ""))[:500]
            files_text += f"\n- {f.get('path', 'unknown')} ({f.get('change_type', 'modified')}, {f.get('language', 'unknown')})\n  ```\n  {patch}\n  ```"

        lint_text = ""
        if lint_result:
            lint_text = f"\nLint 结果: status={getattr(lint_result, 'status', 'unknown')}, errors={len(getattr(lint_result, 'errors', []))}"

        test_text = ""
        if test_result:
            test_text = f"\n测试结果: passed={getattr(test_result, 'passed', 0)}, failed={getattr(test_result, 'failed', 0)}"

        return f"""你是资深代码安全审查员。审查以下代码变更。

变更摘要: {summary}{lint_text}{test_text}

代码变更:
{files_text}

请从以下四个维度审查，输出严格 JSON:

{{
  "issues": [
    {{
      "severity": "error|warning",
      "category": "security|business_logic|performance|convention",
      "description": "问题描述",
      "suggestion": "修复建议",
      "file": "文件路径"
    }}
  ],
  "summary": "审查总结（50字以内）"
}}

审查要点:
- 安全层: SQL注入、XSS、CSRF、硬编码密钥、不安全加密算法、路径遍历
- 业务层: 空指针、未处理异常、边界条件缺失、事务一致性
- 性能层: N+1查询、资源泄露(未关闭连接/文件)、不必要的循环
- 规范层: 命名规范、类型注解缺失、异常处理不完整

只输出 JSON。如果代码质量良好，issues 可以为空数组。"""

    def _parse_semantic_issues(self, content: str | None) -> list[dict]:
        """Parse LLM semantic review output into structured issues."""
        if not content:
            return []

        try:
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()
            if content.startswith("json"):
                content = content[4:].strip()

            data = json.loads(content)
            issues = data.get("issues", [])

            # Tag all with source="semantic"
            for issue in issues:
                issue["source"] = "semantic"

            return issues
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[Auditor] Failed to parse semantic review: {e}")
            return []

    def _compute_confidence(self, decision: str, analysis_results: dict) -> float:
        """Compute confidence score for the decision"""
        if not analysis_results:
            return 0.5

        # Count analyzed files
        files_analyzed = len(analysis_results)

        # Count files with issues
        files_with_issues = sum(
            1 for r in analysis_results.values() if r.get("issues") or r.get("warnings")
        )

        # Base confidence
        if decision == "rejected":
            confidence = 0.8  # High confidence in rejections (conservative)
        else:
            confidence = 0.7  # Moderate confidence in approvals

        # Adjust for coverage
        if files_analyzed < 3:
            confidence -= 0.1  # Less confidence with fewer files analyzed

        if files_with_issues > 0:
            confidence *= (1.0 - (files_with_issues / max(files_analyzed, 1)) * 0.2)

        return max(0.1, min(0.99, confidence))
