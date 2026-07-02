"""
Critic Mode — A11 LLM-powered test case generation based on survived mutations.

Analyzes survived mutations and generates targeted test cases to kill them.
Uses Claude API to generate high-quality, focused test cases.
"""

import asyncio
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CriticMode:
    """Generates supplementary test cases based on survived mutations."""

    def __init__(self, llm_client: Any = None):
        """
        Initialize Critic mode.

        Args:
            llm_client: Optional LLM client (Claude/similar)
                       If None, uses mock generation
        """
        self.llm = llm_client
        self.mutation_score_threshold = 0.80

    async def analyze_and_generate(
        self,
        survived_mutations: list,
        source_code: str,
        language: str = "python",
        max_tests: int = 10,
    ) -> list:
        """
        Analyze survived mutations and generate targeted test cases.

        Args:
            survived_mutations: List of mutation dicts with keys:
                               id, location, mutator, original, mutated
            source_code: Full source code being tested
            language: 'python', 'javascript', 'typescript'
            max_tests: Maximum number of tests to generate

        Returns:
            List of test case dicts with keys: mutation_id, test_code, language, target
        """
        if not survived_mutations:
            return []

        logger.info(
            f"[A11-Critic] Analyzing {len(survived_mutations)} survived mutations"
        )

        test_cases = []

        # Group mutations by type for more efficient generation
        mutations_by_type = {}
        for mutation in survived_mutations:
            mutator = mutation.get("mutator", "unknown")
            if mutator not in mutations_by_type:
                mutations_by_type[mutator] = []
            mutations_by_type[mutator].append(mutation)

        # Process each mutation type
        for mutator, mutations in mutations_by_type.items():
            if len(test_cases) >= max_tests:
                break

            logger.debug(
                f"[A11-Critic] Processing {len(mutations)} mutations of type: {mutator}"
            )

            for mutation in mutations:
                if len(test_cases) >= max_tests:
                    break

                test_case = await self._generate_test_for_mutation(
                    mutation, source_code, language
                )

                if test_case:
                    test_cases.append(test_case)
                    logger.info(
                        f"[A11-Critic] Generated test for mutation {mutation.get('id')}"
                    )

        logger.info(f"[A11-Critic] Generated {len(test_cases)} test cases")
        return test_cases

    async def _generate_test_for_mutation(
        self, mutation: dict, source_code: str, language: str
    ) -> Optional[dict]:
        """
        Generate a single test case for a mutation.

        Args:
            mutation: Mutation dict
            source_code: Full source code
            language: Programming language

        Returns:
            Test case dict or None if generation fails
        """
        try:
            location = mutation.get("location", {})
            line_num = location.get("line", "?")
            mutator = mutation.get("mutator", "unknown")

            prompt = self._build_test_generation_prompt(
                mutation, source_code, language
            )

            if self.llm:
                # Use actual LLM
                response = await self._call_llm(prompt)
            else:
                # Use mock generation
                response = await self._mock_generate_test(mutation, language)

            test_code = self._extract_test_code(response, language)

            if test_code:
                return {
                    "mutation_id": mutation.get("id", ""),
                    "test_code": test_code,
                    "language": language,
                    "target": f"Line {line_num} ({mutator})",
                    "mutator_type": mutator,
                    "source": "critic_generated",
                }
        except Exception as e:
            logger.warning(
                f"[A11-Critic] Failed to generate test for mutation: {e}"
            )

        return None

    def _build_test_generation_prompt(
        self, mutation: dict, source_code: str, language: str
    ) -> str:
        """Build LLM prompt for test generation."""

        location = mutation.get("location", {})
        line_num = location.get("line", "?")
        mutator = mutation.get("mutator", "unknown")
        original = mutation.get("original", "")
        mutated = mutation.get("mutated", "")

        file_context = self._extract_code_context(source_code, line_num, language)

        if language == "python":
            test_template = "def test_..._killed():\n    pass"
        else:
            test_template = "test('...', () => {\n  // test code\n});"

        prompt = f"""You are an expert test engineer. Your task is to generate a minimal, focused test case that will KILL (detect) a specific mutation in the code.

## Code Context
Location: Line {line_num}
Mutation Type: {mutator}

### Original Code (around mutation):
```{language}
{file_context}
```

### Mutation Details:
- **Original**: {original}
- **Mutated to**: {mutated}

## Full Source Code:
```{language}
{source_code[:2000]}
```

## Task:
Generate a {language} test case that will FAIL with the mutated code but PASS with the original code. This means your test must specifically exercise the behavior that the mutation changes.

### Requirements:
1. The test must be complete and runnable
2. It should be minimal (focus on the specific mutation)
3. Use assertions that directly target the mutated behavior
4. Include necessary imports and setup

### Output Format:
Return ONLY the test code in a code block:

```{language}
{test_template}
```

Do NOT include any explanation outside the code block."""

        return prompt

    def _extract_code_context(
        self, source_code: str, line_num: int, language: str, context_lines: int = 5
    ) -> str:
        """Extract lines around the target mutation."""
        try:
            lines = source_code.split("\n")
            line_idx = int(line_num) - 1 if isinstance(line_num, (int, str)) else 0

            start = max(0, line_idx - context_lines)
            end = min(len(lines), line_idx + context_lines + 1)

            context_lines_list = lines[start:end]
            return "\n".join(context_lines_list)
        except Exception:
            return source_code[:500]

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM (Claude API) with the prompt."""
        try:
            if hasattr(self.llm, "generate"):
                # Async generation
                response = await self.llm.generate(prompt, temperature=0.2)
                return response
            elif hasattr(self.llm, "create"):
                # Sync wrapper (e.g., OpenAI-style)
                response = self.llm.create(model="claude-3-sonnet-20240229", messages=[{
                    "role": "user",
                    "content": prompt
                }])
                return response.get("content", [{}])[0].get("text", "")
        except Exception as e:
            logger.warning(f"[A11-Critic] LLM call failed: {e}")

        return ""

    async def _mock_generate_test(self, mutation: dict, language: str) -> str:
        """Generate mock test when LLM unavailable."""
        mutator = mutation.get("mutator", "unknown")
        location = mutation.get("location", {})
        line_num = location.get("line", "?")

        if language == "python":
            test_code = f"""def test_mutation_{line_num}_killed():
    \"\"\"Test to kill mutation: {mutator}\"\"\"
    # This is a generated test for the {mutator} mutation
    # TODO: Replace with actual test logic
    assert True
"""
        else:
            test_code = f"""test('mutation_{line_num}_killed', () => {{
  // Test to kill mutation: {mutator}
  // This is a generated test for the {mutator} mutation
  // TODO: Replace with actual test logic
  expect(true).toBe(true);
}});
"""

        return test_code

    def _extract_test_code(self, response: str, language: str) -> Optional[str]:
        """Extract test code from LLM response."""
        if not response:
            return None

        # Try to extract code block
        patterns = [
            (f"```{language}\\n(.*?)\\n```", "triple backtick with language"),
            (r"```\n(.*?)\n```", "triple backtick plain"),
            (r"```(.*?)```", "triple backtick flexible"),
        ]

        for pattern, desc in patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                code = match.group(1).strip()
                if code:
                    logger.debug(
                        f"[A11-Critic] Extracted test code using pattern: {desc}"
                    )
                    return code

        # If no code block found, try to extract function/test definition
        if language == "python":
            match = re.search(r"(def test_.*?)(?=\ndef |$)", response, re.DOTALL)
        else:
            match = re.search(r"(test\(.*?\{.*?\}\);)", response, re.DOTALL)

        if match:
            code = match.group(1).strip()
            if code:
                logger.debug(
                    "[A11-Critic] Extracted test code from function definition"
                )
                return code

        return None

    def should_trigger_critic_mode(self, mutation_score: float) -> bool:
        """
        Determine if Critic mode should be triggered.

        Args:
            mutation_score: Current mutation score (0.0 - 1.0)

        Returns:
            True if score is below threshold
        """
        return mutation_score < self.mutation_score_threshold
