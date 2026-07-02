"""
A9 TDD Coder Module — Test-Driven Development mode for A9 Claude Code Bridge.

When test_assets are available in context (from A7), use TDD mode:
1. Inject pre-generated test cases into the prompt
2. Instruct Claude/LLM to write code that passes the tests
3. Emit test.tdd_dev_complete event when code generation finishes

Integrates with a9_claude_code_bridge.py execute_task() workflow.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TDDCoderModule:
    """Test-Driven Development code generation module for A9."""

    def __init__(self):
        self.tdd_enabled = False
        self.test_assets = None

    def inject_test_assets(self, context: dict) -> bool:
        """Check if test_assets are available in context and enable TDD mode.

        Args:
            context: Context package that may contain test_assets

        Returns:
            True if test_assets found and TDD enabled, False otherwise
        """
        # Look for test_assets in context
        test_assets = context.get("test_assets")
        if test_assets and isinstance(test_assets, dict):
            # Validate structure
            if any(test_assets.get(k) for k in ["unit_tests", "integration_tests", "e2e_tests"]):
                self.test_assets = test_assets
                self.tdd_enabled = True
                logger.info(f"[A9-TDD] TDD mode enabled with {len(self._get_all_tests())} test cases")
                return True

        self.tdd_enabled = False
        self.test_assets = None
        return False

    def _get_all_tests(self) -> list:
        """Get all test cases from test_assets."""
        if not self.test_assets:
            return []
        tests = []
        for key in ["unit_tests", "integration_tests", "e2e_tests", "visual_tests"]:
            tests.extend(self.test_assets.get(key, []))
        return tests

    def build_tdd_prompt(self, task_spec: dict) -> str:
        """Build TDD prompt that includes test cases to drive development.

        Args:
            task_spec: Task specification from A9

        Returns:
            Enhanced prompt with test cases for TDD
        """
        if not self.tdd_enabled or not self.test_assets:
            return self._build_standard_prompt(task_spec)

        title = task_spec.get("title", "untitled")
        task_type = task_spec.get("type", "backend")
        plan = task_spec.get("plan", {})
        files_needed = plan.get("files_to_create", plan.get("files_to_modify", ["src/main.py"]))

        # Format test cases for inclusion in prompt
        unit_tests_str = self._format_tests("Unit Tests", self.test_assets.get("unit_tests", []))
        integration_tests_str = self._format_tests("Integration Tests", self.test_assets.get("integration_tests", []))
        e2e_tests_str = self._format_tests("E2E Tests", self.test_assets.get("e2e_tests", []))

        coverage_targets = self.test_assets.get("coverage_targets", {})
        coverage_str = f"""
Required Coverage Targets:
- Overall: {coverage_targets.get('overall', 0.8) * 100}%
- Branches: {coverage_targets.get('branches', 0.75) * 100}%
- Lines: {coverage_targets.get('lines', 0.85) * 100}%
"""

        prompt = f"""你是一名全栈开发工程师，采用测试驱动开发 (TDD) 模式。

任务: {title}
类型: {task_type}
需要创建/修改的文件: {', '.join(files_needed[:10])}

CRITICAL: 以下测试用例必须通过。请先理解每个测试的意图，然后编写代码确保所有测试通过。

{unit_tests_str}

{integration_tests_str}

{e2e_tests_str}

{coverage_str}

输出严格 JSON 格式:
{{
  "files_changed": [
    {{
      "path": "src/xxx.py",
      "added": 45,
      "removed": 5,
      "language": "python",
      "diff": "完整的 diff 内容，包含足够上下文"
    }}
  ],
  "test_coverage_plan": "说明如何满足上述测试和覆盖率目标",
  "summary": "变更摘要（50字以内）",
  "dependencies_added": ["包名1"],
  "tdd_notes": "TDD 开发笔记"
}}

重要规则:
1. 代码必须通过所有上述测试
2. 必须达到指定的覆盖率目标
3. 包含足够的类型注解和文档
4. 考虑边界条件和错误处理
5. 只输出 JSON，不要 markdown

使用 TDD 红绿重构周期:
- RED: 理解测试需求
- GREEN: 编写最小化代码通过测试
- REFACTOR: 优化和清理代码
"""
        return prompt

    def _build_standard_prompt(self, task_spec: dict) -> str:
        """Build standard prompt without TDD when no test_assets available."""
        title = task_spec.get("title", "untitled")
        task_type = task_spec.get("type", "backend")
        plan = task_spec.get("plan", {})
        files_needed = plan.get("files_to_create", plan.get("files_to_modify", ["src/main.py"]))

        prompt = f"""你是一个全栈开发工程师。需要为以下任务生成代码变更。

任务: {title}
类型: {task_type}
需要创建/修改的文件: {', '.join(files_needed[:10])}

输出严格 JSON 格式:
{{
  "files_changed": [
    {{
      "path": "src/xxx.py",
      "added": 45,
      "removed": 5,
      "language": "python",
      "diff": "完整的 diff 内容"
    }}
  ],
  "summary": "变更摘要（50字以内）",
  "dependencies_added": ["包名1"]
}}

只输出 JSON。diff 内容应该是实际的代码变更，包含足够的上下文。
请确保代码可以直接运行，包含必要的 import 和类型注解。"""
        return prompt

    def _format_tests(self, test_type_title: str, tests: list) -> str:
        """Format test cases for inclusion in prompt."""
        if not tests:
            return ""

        lines = [f"\n{test_type_title}:"]
        for i, test in enumerate(tests[:5], 1):  # Limit to first 5 per type
            name = test.get("title", f"Test {i}")
            description = test.get("description", "")
            steps = test.get("steps", [])

            lines.append(f"\n{i}. {name}")
            if description:
                lines.append(f"   描述: {description}")

            if steps:
                lines.append("   步骤:")
                for step in steps[:3]:  # Limit steps
                    step_num = step.get("step_number", 1)
                    action = step.get("action", "")
                    expected = step.get("expected", "")
                    lines.append(f"     {step_num}. {action} -> 预期: {expected}")

        if len(tests) > 5:
            lines.append(f"\n... 还有 {len(tests) - 5} 个测试")

        return "\n".join(lines)

    def get_metrics(self) -> dict:
        """Return TDD mode metrics."""
        if not self.test_assets:
            return {"tdd_enabled": False}

        return {
            "tdd_enabled": True,
            "total_test_cases": len(self._get_all_tests()),
            "unit_tests": len(self.test_assets.get("unit_tests", [])),
            "integration_tests": len(self.test_assets.get("integration_tests", [])),
            "e2e_tests": len(self.test_assets.get("e2e_tests", [])),
            "visual_tests": len(self.test_assets.get("visual_tests", [])),
            "coverage_targets": self.test_assets.get("coverage_targets", {}),
        }
