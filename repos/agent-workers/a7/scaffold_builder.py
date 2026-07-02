"""
Scaffold Builder — generates test file scaffolds from test case definitions.

Real implementation would:
  - Use Jinja2 templates for pytest / Jest / Playwright scaffolds
  - Include fixture factories, mock patches, conftest.py generation
  - Read .test-scaffold.yaml project config for framework preferences
  - Auto-detect project structure (src/ vs flat layout)
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ScaffoldBuilder:
    """Build test scaffold code from a list of test case definitions."""

    # Known test frameworks and their default configs
    FRAMEWORKS = {
        "pytest": {
            "extension": ".py",
            "test_dir": "tests/",
            "base_imports": ["import pytest\n", "from unittest.mock import AsyncMock, MagicMock, patch\n"],
        },
        "jest": {
            "extension": ".test.js",
            "test_dir": "__tests__/",
            "base_imports": [],
        },
        "playwright": {
            "extension": ".spec.js",
            "test_dir": "e2e/",
            "base_imports": ["const { test, expect } = require('@playwright/test');\n"],
        },
    }

    async def build(self, test_cases: list, framework: str = "pytest") -> dict:
        """
        Generate test scaffold files from a list of test case dictionaries.

        Args:
            test_cases: List of test case dicts (output from BoundaryAnalyzer or manual).
            framework: Target framework — one of "pytest", "jest", "playwright".

        Returns:
            {
                test_files: [{path, content, test_count}],
                fixtures: [],
                mocks_needed: [],
                total_lines: int,
            }
        """
        if not test_cases:
            logger.warning("No test cases provided; returning empty scaffold.")
            return {
                "test_files": [],
                "fixtures": [],
                "mocks_needed": [],
                "total_lines": 0,
            }

        cfg = self.FRAMEWORKS.get(framework, self.FRAMEWORKS["pytest"])
        extension = cfg["extension"]
        test_dir = cfg["test_dir"]
        base_imports = cfg["base_imports"]

        logger.info(
            "Building %s scaffolds for %d test cases",
            framework,
            len(test_cases),
        )

        # Group test cases by module / component
        modules: Dict[str, List[dict]] = {}
        for tc in test_cases:
            # Derive module name from the test case
            field_or_title = tc.get("field", tc.get("title", "generic"))
            module_key = self._derive_module_name(field_or_title)
            modules.setdefault(module_key, []).append(tc)

        test_files: List[Dict[str, Any]] = []
        fixtures: List[str] = []
        mocks_needed: List[str] = []
        total_lines = 0

        for module_name, cases in modules.items():
            content_lines: List[str] = []
            content_lines.extend(base_imports)

            # Fixtures section
            fixture_block = self._generate_fixtures(cases, framework)
            content_lines.extend(fixture_block)

            # Test function per case
            for tc in cases:
                test_func = self._render_test_function(tc, framework)
                content_lines.append(test_func)
                content_lines.append("")

            content = "\n".join(content_lines)
            file_path = f"{test_dir}test_{module_name}{extension}"
            total_lines += len(content_lines)

            test_files.append({
                "path": file_path,
                "content": content,
                "test_count": len(cases),
            })

            # Collect fixtures and mocks
            fixtures.extend(self._collect_fixtures(cases, framework))
            mocks_needed.extend(self._collect_mocks(cases))

        # Deduplicate
        fixtures = list(dict.fromkeys(fixtures))
        mocks_needed = list(dict.fromkeys(mocks_needed))

        logger.info(
            "Scaffold built: %d files, %d lines, %d fixtures, %d mocks",
            len(test_files),
            total_lines,
            len(fixtures),
            len(mocks_needed),
        )

        return {
            "test_files": test_files,
            "fixtures": fixtures,
            "mocks_needed": mocks_needed,
            "total_lines": total_lines,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _derive_module_name(self, field_or_title: str) -> str:
        """Derive a safe Python module name from a field path or title."""
        # Strip HTTP method prefix if present (e.g. "POST /api/users -> name")
        if " -> " in field_or_title:
            field_or_title = field_or_title.split(" -> ")[0]
        # Remove HTTP method prefix
        for method in ("GET ", "POST ", "PUT ", "PATCH ", "DELETE "):
            if field_or_title.startswith(method):
                field_or_title = field_or_title[len(method):].strip()
        # Sanitize for module name
        safe = (
            field_or_title.replace("/", "_")
            .replace("{", "")
            .replace("}", "")
            .replace("-", "_")
            .replace(".", "_")
            .lower()
            .strip("_")
        )
        return safe or "default_module"

    def _generate_fixtures(self, cases: list, framework: str) -> list:
        """Generate shared fixtures (conftest-style)."""
        lines = []
        if framework == "pytest":
            lines.extend([
                "",
                "",
                "@pytest.fixture",
                "def api_client():",
                '    """Fixture: provides a configured API test client."""',
                "    from httpx import AsyncClient",
                "    return AsyncClient(base_url=\"http://localhost:8000\")",
                "",
                "",
                "@pytest.fixture",
                "def db_session():",
                '    """Fixture: provides a test database session (rollback after test)."""',
                "    # In production: use pytest-postgresql or testcontainers",
                "    yield None  # placeholder",
                "",
            ])
        elif framework == "jest":
            lines.extend([
                "",
                "beforeAll(async () => {",
                "  // Setup: start test server, seed database",
                "});",
                "",
                "afterAll(async () => {",
                "  // Teardown: stop test server, clean up",
                "});",
                "",
            ])
        elif framework == "playwright":
            lines.extend([
                "",
                "test.use({",
                "  baseURL: 'http://localhost:3000',",
                "  screenshot: 'on',",
                "  video: 'retain-on-failure',",
                "});",
                "",
            ])
        return lines

    def _render_test_function(self, tc: dict, framework: str) -> str:
        """Render a single test function."""
        test_id = tc.get("test_id", tc.get("field", "test_case"))
        title = tc.get("title", test_id)
        # Sanitize for function name
        func_name = (
            test_id.replace("-", "_")
            .replace(" ", "_")
            .replace("/", "_")
            .replace(".", "_")
            .lower()
        )

        if framework == "pytest":
            return (
                f"def test_{func_name}(api_client):\n"
                f'    """{title}"""\n'
                f"    # Arrange\n"
                f"    # Act\n"
                f"    # response = await api_client.get('/endpoint')\n"
                f"    # Assert\n"
                f"    # assert response.status_code == 200\n"
                f"    pass  # TODO: implement"
            )
        elif framework == "jest":
            return (
                f"test('{title}', async () => {{\n"
                f"  // Arrange\n"
                f"  // Act\n"
                f"  // const response = await request(app).get('/endpoint');\n"
                f"  // Assert\n"
                f"  // expect(response.status).toBe(200);\n"
                f"}});"
            )
        elif framework == "playwright":
            return (
                f"test('{title}', async ({{ page }}) => {{\n"
                f"  // Navigate\n"
                f"  // await page.goto('/path');\n"
                f"  // Interact\n"
                f"  // await expect(page.locator('h1')).toBeVisible();\n"
                f"}});"
            )
        else:
            return f"# TODO: test_{func_name} — {title}"

    def _collect_fixtures(self, cases: list, framework: str) -> list:
        """Identify fixtures needed by this set of cases."""
        return ["api_client", "db_session"] if framework == "pytest" else []

    def _collect_mocks(self, cases: list) -> list:
        """Identify external services that need mocking."""
        mocks = set()
        for tc in cases:
            field = tc.get("field", "")
            if "users" in field.lower():
                mocks.add("user_service")
            if "orders" in field.lower():
                mocks.add("order_service")
            if "payments" in field.lower() or "payment" in field.lower():
                mocks.add("payment_gateway")
        return sorted(mocks) if mocks else ["external_api"]
