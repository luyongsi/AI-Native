"""
Test suite for mutation testing and A11 Critic mode.

Tests MutationTester, CriticMode, TestFileWriter, and MutationMetrics.
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from a11.mutation_tester import MutationTester
from a11.critic_mode import CriticMode
from a11.test_file_writer import TestFileWriter
from a11.mutation_metrics import MutationMetrics


class TestMutationTester:
    """Test MutationTester class."""

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """Test empty result structure."""
        tester = MutationTester()
        result = tester._empty_result()

        assert result["survived"] == []
        assert result["killed"] == []
        assert result["mutation_score"] == 0.0
        assert result["total_mutations"] == 0

    def test_parse_mutmut_results_json(self):
        """Test parsing mutmut JSON output."""
        tester = MutationTester()

        mutmut_output = json.dumps({
            "src/utils.py": {
                "1": {
                    "status": "survived",
                    "line": 10,
                    "column": 5,
                    "mutation_type": "ArithmeticOperator",
                    "original_source": "x + y",
                    "mutated_source": "x - y",
                },
                "2": {
                    "status": "killed",
                    "line": 15,
                    "column": 3,
                    "mutation_type": "ComparisonOperator",
                    "original_source": "a == b",
                    "mutated_source": "a != b",
                },
            }
        })

        result = tester._parse_mutmut_results(mutmut_output)

        assert len(result["survived"]) == 1
        assert len(result["killed"]) == 1
        assert result["mutation_score"] == 0.5
        assert result["total_mutations"] == 2

    def test_parse_stryker_results_json(self):
        """Test parsing Stryker JSON output."""
        tester = MutationTester()

        stryker_output = {
            "mutationScore": 75.0,
            "files": {
                "src/index.ts": {
                    "mutants": [
                        {
                            "id": "1",
                            "status": "Survived",
                            "location": {"start": {"line": 10, "column": 5}},
                            "mutatorName": "BinaryOperator",
                            "originalLines": "a + b",
                            "mutatedLines": "a - b",
                        },
                        {
                            "id": "2",
                            "status": "Killed",
                            "location": {"start": {"line": 20, "column": 2}},
                            "mutatorName": "ConditionalExpression",
                            "originalLines": "x ? y : z",
                            "mutatedLines": "x ? z : y",
                        },
                    ]
                }
            }
        }

        result = tester._parse_stryker_results(stryker_output)

        assert len(result["survived"]) == 1
        assert len(result["killed"]) == 1
        assert result["mutation_score"] == 0.75

    def test_parse_stryker_stdout(self):
        """Test parsing Stryker stdout."""
        tester = MutationTester()

        stdout = """
        [...] Running mutator...
        Mutation score: 85.5%
        [...] Results: 10 killed, 3 survived
        """

        result = tester._parse_stryker_stdout(stdout)

        assert result["mutation_score"] == 0.855
        assert len(result["survived"]) == 0
        assert len(result["killed"]) == 0

    def test_extract_code_context(self):
        """Test extracting code context around mutation."""
        critic = CriticMode()

        source = "line1\nline2\nline3\nline4\nline5"
        context = critic._extract_code_context(source, 3, "python", context_lines=1)

        assert "line2" in context
        assert "line3" in context
        assert "line4" in context


class TestCriticMode:
    """Test CriticMode class."""

    @pytest.mark.asyncio
    async def test_mock_generate_test_python(self):
        """Test mock test generation for Python."""
        critic = CriticMode()

        mutation = {
            "id": "1",
            "mutator": "ArithmeticOperator",
            "location": {"line": 10},
        }

        response = await critic._mock_generate_test(mutation, "python")

        assert "def test_mutation_" in response
        assert "assert" in response
        assert "ArithmeticOperator" in response

    @pytest.mark.asyncio
    async def test_mock_generate_test_javascript(self):
        """Test mock test generation for JavaScript."""
        critic = CriticMode()

        mutation = {
            "id": "2",
            "mutator": "BinaryOperator",
            "location": {"line": 25},
        }

        response = await critic._mock_generate_test(mutation, "javascript")

        assert "test(" in response
        assert "expect(" in response
        assert "BinaryOperator" in response

    def test_extract_test_code_triple_backtick(self):
        """Test extracting test code from triple backtick block."""
        critic = CriticMode()

        response = """Here's the test:

```python
def test_example():
    assert True
```

That should work."""

        code = critic._extract_test_code(response, "python")

        assert code == "def test_example():\n    assert True"

    def test_extract_test_code_function_def(self):
        """Test extracting test code from function definition."""
        critic = CriticMode()

        response = """
def test_my_function():
    x = 5
    assert x == 5

Some other text here.
"""

        code = critic._extract_test_code(response, "python")

        assert "def test_my_function" in code
        assert "assert x == 5" in code

    def test_should_trigger_critic_mode(self):
        """Test Critic mode trigger condition."""
        critic = CriticMode()

        assert critic.should_trigger_critic_mode(0.75) is True  # Below 0.80
        assert critic.should_trigger_critic_mode(0.80) is False  # Exactly at threshold
        assert critic.should_trigger_critic_mode(0.85) is False  # Above threshold

    @pytest.mark.asyncio
    async def test_analyze_and_generate(self):
        """Test analyzing mutations and generating tests."""
        critic = CriticMode()

        survived_mutations = [
            {
                "id": "1",
                "mutator": "ArithmeticOperator",
                "location": {"line": 10},
                "original": "x + y",
                "mutated": "x - y",
            },
            {
                "id": "2",
                "mutator": "ComparisonOperator",
                "location": {"line": 15},
                "original": "a == b",
                "mutated": "a != b",
            },
        ]

        source_code = "x = 1\ny = 2\nz = x + y"

        tests = await critic.analyze_and_generate(
            survived_mutations, source_code, language="python", max_tests=5
        )

        assert len(tests) > 0
        assert tests[0].get("language") == "python"
        assert tests[0].get("test_code") is not None


class TestTestFileWriter:
    """Test TestFileWriter class."""

    def test_build_python_test_file(self):
        """Test building Python test file content."""
        writer = TestFileWriter()

        tests = [
            {
                "mutation_id": "1",
                "test_code": "def test_example():\n    assert True",
                "target": "Line 10 (ArithmeticOperator)",
                "mutator_type": "ArithmeticOperator",
            }
        ]

        content = writer._build_python_test_file(tests)

        assert "# Auto-generated by A11 Critic Mode" in content
        assert "import pytest" in content
        assert "def test_example" in content
        assert "assert True" in content
        assert "Mutation ID: 1" in content

    def test_build_javascript_test_file(self):
        """Test building JavaScript test file content."""
        writer = TestFileWriter()

        tests = [
            {
                "mutation_id": "1",
                "test_code": "test('example', () => {\n  expect(true).toBe(true);\n});",
                "target": "Line 20 (BinaryOperator)",
                "mutator_type": "BinaryOperator",
            }
        ]

        content = writer._build_javascript_test_file(tests)

        assert "// Auto-generated by A11 Critic Mode" in content
        assert "describe(" in content
        assert "test(" in content
        assert "Mutation ID: 1" in content

    def test_write_tests_python(self, tmp_path):
        """Test writing Python tests to file."""
        writer = TestFileWriter()

        tests = [
            {
                "mutation_id": "1",
                "test_code": "def test_python():\n    pass",
                "language": "python",
                "target": "Line 5",
                "mutator_type": "Operator",
            }
        ]

        result = writer.write_tests(tests, str(tmp_path), language="python")

        assert result != ""
        assert Path(result).exists()
        assert Path(result).suffix == ".py"

        content = Path(result).read_text()
        assert "def test_python" in content

    def test_write_tests_javascript(self, tmp_path):
        """Test writing JavaScript tests to file."""
        writer = TestFileWriter()

        tests = [
            {
                "mutation_id": "2",
                "test_code": "test('js test', () => {});",
                "language": "javascript",
                "target": "Line 10",
                "mutator_type": "Operator",
            }
        ]

        result = writer.write_tests(tests, str(tmp_path), language="javascript")

        assert result != ""
        assert Path(result).exists()
        assert ".js" in Path(result).suffix

        content = Path(result).read_text()
        assert "test(" in content


class TestMutationMetrics:
    """Test MutationMetrics class."""

    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = MutationMetrics()
        # Should not raise an error
        assert metrics is not None

    def test_record_mutation_result_no_error(self):
        """Test recording mutation result doesn't raise error."""
        metrics = MutationMetrics()

        try:
            metrics.record_mutation_result(
                project="test_project",
                language="python",
                mutation_score=0.85,
                survived=2,
                killed=10,
                total=12,
            )
        except Exception as e:
            pytest.fail(f"record_mutation_result raised {e}")

    def test_record_critic_tests_no_error(self):
        """Test recording critic tests doesn't raise error."""
        metrics = MutationMetrics()

        try:
            metrics.record_critic_tests_generated(
                project="test_project", language="python", count=5
            )
        except Exception as e:
            pytest.fail(f"record_critic_tests_generated raised {e}")

    def test_record_critic_mode_triggered_no_error(self):
        """Test recording critic trigger doesn't raise error."""
        metrics = MutationMetrics()

        try:
            metrics.record_critic_mode_triggered(
                project="test_project", language="python"
            )
        except Exception as e:
            pytest.fail(f"record_critic_mode_triggered raised {e}")

    def test_record_critic_improvement_no_error(self):
        """Test recording improvement doesn't raise error."""
        metrics = MutationMetrics()

        try:
            metrics.record_critic_improvement(
                project="test_project",
                language="python",
                improvement=0.1,
                execution_time_ms=5000,
            )
        except Exception as e:
            pytest.fail(f"record_critic_improvement raised {e}")


class TestIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_end_to_end_critic_workflow(self):
        """Test complete Critic mode workflow."""
        # Create components
        critic = CriticMode()
        writer = TestFileWriter()
        metrics = MutationMetrics()

        # Simulate survived mutations
        mutations = [
            {
                "id": str(i),
                "mutator": f"Operator{i}",
                "location": {"line": 10 + i},
                "original": f"expr{i}",
                "mutated": f"mutated{i}",
            }
            for i in range(3)
        ]

        # Generate tests
        tests = await critic.analyze_and_generate(
            mutations, "source code here", language="python", max_tests=5
        )

        assert len(tests) > 0

        # Record metrics
        metrics.record_critic_mode_triggered("test_proj", "python")
        metrics.record_critic_tests_generated("test_proj", "python", len(tests))

        # Write tests (without actual filesystem)
        assert all("test_code" in t for t in tests)
