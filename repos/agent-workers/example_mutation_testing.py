"""
A11 Mutation Testing Engine — Quick Start Example

Demonstrates the complete mutation testing + Critic mode workflow.
"""

import asyncio
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def example_python_project():
    """Example: Run mutation testing on a Python project."""
    from a11.mutation_tester import MutationTester
    from a11.critic_mode import CriticMode
    from a11.test_file_writer import TestFileWriter
    from a11.mutation_metrics import MutationMetrics

    logger.info("=" * 60)
    logger.info("Example 1: Python Project Mutation Testing + Critic Mode")
    logger.info("=" * 60)

    project_path = "/path/to/python/project"
    target_file = "src/calculator.py"

    # 1. Initialize components
    tester = MutationTester(timeout=300)
    critic = CriticMode()
    writer = TestFileWriter()
    metrics = MutationMetrics()

    # 2. Run mutation testing
    logger.info(f"[Step 1] Running mutmut on {project_path}")
    result = await tester.run_mutmut(project_path, target_file=target_file)

    logger.info(f"Mutation score: {result['mutation_score']:.1%}")
    logger.info(f"Killed: {len(result['killed'])}, Survived: {len(result['survived'])}")

    # 3. Record metrics
    metrics.record_mutation_result(
        project="calculator",
        language="python",
        mutation_score=result["mutation_score"],
        survived=len(result["survived"]),
        killed=len(result["killed"]),
        total=result["total_mutations"],
    )

    # 4. Check if Critic mode should trigger
    if critic.should_trigger_critic_mode(result["mutation_score"]):
        logger.info("[Step 2] Mutation score below threshold, triggering Critic mode")

        # Read source code
        try:
            with open(target_file, "r") as f:
                source_code = f.read()
        except FileNotFoundError:
            source_code = "def example():\n    pass"

        # Generate tests
        logger.info(f"[Step 2a] Analyzing {len(result['survived'])} survived mutations")
        tests = await critic.analyze_and_generate(
            result["survived"],
            source_code,
            language="python",
            max_tests=10,
        )

        if tests:
            logger.info(f"[Step 2b] Generated {len(tests)} test cases")

            # Write tests
            logger.info(f"[Step 2c] Writing tests to disk")
            test_file = writer.write_tests(
                tests, project_path, language="python", output_file="test_critic.py"
            )
            logger.info(f"Tests written to: {test_file}")

            # Record Critic mode metrics
            metrics.record_critic_mode_triggered("calculator", "python")
            metrics.record_critic_tests_generated("calculator", "python", len(tests))

            # Re-run mutation testing (simulated)
            logger.info("[Step 2d] Re-running mutation tests with new tests")
            new_result = await tester.run_mutmut(project_path, target_file=target_file)

            improvement = new_result["mutation_score"] - result["mutation_score"]
            logger.info(f"Mutation score: {result['mutation_score']:.1%} → "
                       f"{new_result['mutation_score']:.1%} "
                       f"(improvement: +{improvement:.1%})")

            if improvement > 0:
                metrics.record_critic_improvement(
                    "calculator", "python",
                    improvement=improvement,
                    execution_time_ms=5000
                )
    else:
        logger.info("[Step 2] Mutation score acceptable, skipping Critic mode")

    logger.info("=" * 60)
    logger.info("Example 1 Complete")
    logger.info("=" * 60)


async def example_javascript_project():
    """Example: Run mutation testing on a JavaScript project."""
    from a11.mutation_tester import MutationTester
    from a11.critic_mode import CriticMode
    from a11.test_file_writer import TestFileWriter

    logger.info("=" * 60)
    logger.info("Example 2: JavaScript Project Mutation Testing + Critic Mode")
    logger.info("=" * 60)

    project_path = "/path/to/javascript/project"

    # 1. Initialize components
    tester = MutationTester(timeout=600)  # Stryker can be slower
    critic = CriticMode()
    writer = TestFileWriter()

    # 2. Run Stryker mutation testing
    logger.info(f"[Step 1] Running Stryker on {project_path}")
    result = await tester.run_stryker(project_path, config_path="stryker.conf.json")

    logger.info(f"Mutation score: {result['mutation_score']:.1%}")
    logger.info(f"Killed: {len(result['killed'])}, Survived: {len(result['survived'])}")

    # 3. Generate tests if needed
    if critic.should_trigger_critic_mode(result["mutation_score"]):
        logger.info("[Step 2] Triggering Critic mode for JavaScript project")

        # Mock source code
        source_code = """
function add(a, b) {
  return a + b;
}

function subtract(a, b) {
  return a - b;
}

module.exports = { add, subtract };
"""

        tests = await critic.analyze_and_generate(
            result["survived"],
            source_code,
            language="javascript",
            max_tests=5,
        )

        if tests:
            logger.info(f"Generated {len(tests)} test cases")
            test_file = writer.write_tests(
                tests,
                project_path,
                language="javascript",
                output_file="test.critic.js",
            )
            logger.info(f"Tests written to: {test_file}")

    logger.info("=" * 60)
    logger.info("Example 2 Complete")
    logger.info("=" * 60)


async def example_mock_workflow():
    """Example: Mock workflow without actual tools installed."""
    from a11.critic_mode import CriticMode
    from a11.test_file_writer import TestFileWriter
    import tempfile

    logger.info("=" * 60)
    logger.info("Example 3: Mock Workflow (No Tools Required)")
    logger.info("=" * 60)

    # Simulate mutation results
    survived_mutations = [
        {
            "id": "1",
            "mutator": "ArithmeticOperator",
            "location": {"line": 5, "column": 12},
            "original": "x + y",
            "mutated": "x - y",
        },
        {
            "id": "2",
            "mutator": "ComparisonOperator",
            "location": {"line": 10, "column": 8},
            "original": "a == b",
            "mutated": "a != b",
        },
    ]

    mutation_score = 0.75  # Below 0.80 threshold

    logger.info(f"[Step 1] Simulated mutation score: {mutation_score:.1%}")
    logger.info(f"Survived mutations: {len(survived_mutations)}")

    # Initialize components
    critic = CriticMode()
    writer = TestFileWriter()

    # Check if Critic mode should trigger
    if critic.should_trigger_critic_mode(mutation_score):
        logger.info("[Step 2] Critic mode triggered")

        source_code = """
def add(a, b):
    return a + b

def compare(a, b):
    return a == b
"""

        # Generate tests
        logger.info("[Step 2a] Generating tests for survived mutations")
        tests = await critic.analyze_and_generate(
            survived_mutations,
            source_code,
            language="python",
            max_tests=10,
        )

        logger.info(f"Generated {len(tests)} test cases")

        # Write tests to temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info("[Step 2b] Writing tests to temporary directory")
            test_file = writer.write_tests(
                tests, tmpdir, language="python"
            )

            # Show generated content
            with open(test_file, "r") as f:
                content = f.read()
                logger.info("Generated test file content (first 500 chars):")
                logger.info(content[:500] + "...")

    logger.info("=" * 60)
    logger.info("Example 3 Complete")
    logger.info("=" * 60)


async def main():
    """Run all examples."""
    logger.info("\n")
    logger.info("A11 Mutation Testing Engine - Quick Start Examples")
    logger.info("=" * 60)

    # Run the mock workflow (doesn't require tools)
    await example_mock_workflow()

    logger.info("\n")
    logger.info("NOTE: The following examples require actual tools installed:")
    logger.info("  - Example 1 (Python): pip install mutmut")
    logger.info("  - Example 2 (JavaScript): npm install -D @stryker-mutator/core")
    logger.info("\n")


if __name__ == "__main__":
    asyncio.run(main())
