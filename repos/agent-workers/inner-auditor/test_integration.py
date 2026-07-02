"""
Integration tests for Inner Auditor real toolchain.

Tests lint, type-check, and security scanning with real tools and fallback patterns.
"""

import asyncio
import pytest
import tempfile
from pathlib import Path

from inner_auditor.auditor import InnerAuditor
from inner_auditor.enhanced_static_analyzer import EnhancedStaticAnalyzer
from inner_auditor.security_rules import SecurityRules
from inner_auditor.semgrep_analyzer import SemgrepAnalyzer
from inner_auditor.tool_executor import ToolExecutor


class TestToolExecutor:
    """Test tool execution with timeout."""

    @pytest.mark.asyncio
    async def test_run_with_timeout_success(self):
        """Test successful tool execution."""
        executor = ToolExecutor(timeout=30)
        result = await executor.run_with_timeout(["echo", "hello"])

        assert result["success"]
        assert "hello" in result["stdout"]
        assert not result["timed_out"]

    @pytest.mark.asyncio
    async def test_run_with_timeout_not_found(self):
        """Test tool not found handling."""
        executor = ToolExecutor(timeout=5)
        result = await executor.run_with_timeout(["nonexistent_tool_12345"])

        assert not result["success"]
        assert result["error"] is not None
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_run_with_timeout_exceeded(self):
        """Test timeout handling."""
        executor = ToolExecutor(timeout=1)
        result = await executor.run_with_timeout(["sleep", "10"])

        assert not result["success"]
        assert result["timed_out"]


class TestSecurityRules:
    """Test pattern-based security detection."""

    def test_sql_injection_detection(self):
        """Test SQL injection pattern detection."""
        code = 'query = f"SELECT * FROM users WHERE id = {user_id}"'
        vulns = SecurityRules.scan_content(code, "python")

        assert any(v["rule"] == "sql_injection" for v in vulns)

    def test_hardcoded_secrets_detection(self):
        """Test hardcoded credentials detection."""
        code = 'api_key = "sk-1234567890abcdefghij"'
        vulns = SecurityRules.scan_content(code, "python")

        assert any(v["rule"] == "hardcoded_secrets" for v in vulns)

    def test_xss_detection(self):
        """Test XSS vulnerability detection."""
        code = "element.innerHTML = userInput + extra"
        vulns = SecurityRules.scan_content(code, "javascript")

        assert any(v["rule"] == "xss_vulnerability" for v in vulns)

    def test_insecure_deserialization(self):
        """Test insecure deserialization detection."""
        code = "data = pickle.load(file)"
        vulns = SecurityRules.scan_content(code, "python")

        assert any(v["rule"] == "insecure_deserialization" for v in vulns)

    def test_weak_cryptography(self):
        """Test weak cryptography detection."""
        code = "hash_value = hashlib.md5(password).hexdigest()"
        vulns = SecurityRules.scan_content(code, "python")

        assert any(v["rule"] == "weak_cryptography" for v in vulns)

    def test_command_injection(self):
        """Test command injection detection."""
        code = 'os.system(f"rm {filename}")'
        vulns = SecurityRules.scan_content(code, "python")

        assert any(v["rule"] == "command_injection" for v in vulns)


class TestEnhancedStaticAnalyzer:
    """Test multi-tool static analysis."""

    @pytest.mark.asyncio
    async def test_analyze_python_no_issues(self):
        """Test Python analysis on clean code."""
        code = '''
def hello(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"
'''

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            analyzer = EnhancedStaticAnalyzer()
            result = await analyzer.analyze_comprehensive(tmp_path, "python")

            assert result["language"] == "python"
            assert result["status"] in ["ok", "warning", "error"]

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_analyze_javascript(self):
        """Test JavaScript analysis."""
        code = "const x = 1; console.log(x);"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            analyzer = EnhancedStaticAnalyzer()
            result = await analyzer.analyze_comprehensive(tmp_path, "javascript")

            assert result["language"] == "javascript"
            assert "tools" in result

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_analyze_with_content(self):
        """Test analysis with provided content."""
        code = "print('hello')\n"

        analyzer = EnhancedStaticAnalyzer()
        result = await analyzer.analyze_comprehensive(
            "/tmp/test.py",
            "python",
            content=code,
        )

        assert result["language"] == "python"


class TestSemgrepAnalyzer:
    """Test Semgrep integration."""

    @pytest.mark.asyncio
    async def test_semgrep_unavailable(self):
        """Test graceful handling when Semgrep is unavailable."""
        analyzer = SemgrepAnalyzer()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write("print('hello')")
            tmp_path = tmp.name

        try:
            result = await analyzer.scan(tmp_path)

            # Should gracefully handle unavailable tool
            assert "success" in result
            assert "tool_unavailable" in result

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_categorize_findings(self):
        """Test finding categorization."""
        findings = [
            {
                "check_id": "security.sql-injection",
                "extra": {"severity": "HIGH", "message": "SQL injection"},
            },
            {
                "check_id": "performance.loop-optimization",
                "extra": {"severity": "MEDIUM", "message": "Loop issue"},
            },
        ]

        analyzer = SemgrepAnalyzer()
        categories = analyzer._categorize_findings(findings)

        assert len(categories["security"]) == 1
        assert len(categories["performance"]) == 1


class TestInnerAuditor:
    """Test main Inner Auditor integration."""

    @pytest.mark.asyncio
    async def test_run_lint_empty(self):
        """Test lint with no files."""
        auditor = InnerAuditor()
        result = await auditor.run_lint([])

        assert result["error_count"] == 0
        assert result["warning_count"] == 0
        assert not result["mock"]

    @pytest.mark.asyncio
    async def test_run_type_check_empty(self):
        """Test type check with no files."""
        auditor = InnerAuditor()
        result = await auditor.run_type_check([])

        assert result["error_count"] == 0
        assert not result["mock"]

    @pytest.mark.asyncio
    async def test_run_security_scan_empty(self):
        """Test security scan with no files."""
        auditor = InnerAuditor()
        result = await auditor.run_security_scan([])

        assert result["critical_count"] == 0
        assert result["high_count"] == 0
        assert not result["mock"]

    @pytest.mark.asyncio
    async def test_run_all_empty(self):
        """Test all checks with no files."""
        auditor = InnerAuditor()
        result = await auditor.run_all([])

        assert "lint" in result
        assert "type_check" in result
        assert "security_scan" in result

    @pytest.mark.asyncio
    async def test_run_all_with_vulnerable_code(self):
        """Test detection of vulnerable code."""
        code = 'query = f"SELECT * FROM users WHERE id = {user_id}"'

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            auditor = InnerAuditor(enable_semgrep=False)
            result = await auditor.run_security_scan([tmp_path])

            # Should detect SQL injection
            assert result["critical_count"] > 0 or result["high_count"] > 0

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_detect_language(self):
        """Test language detection."""
        auditor = InnerAuditor()

        assert auditor._detect_language("test.py") == "python"
        assert auditor._detect_language("test.js") == "javascript"
        assert auditor._detect_language("test.ts") == "typescript"
        assert auditor._detect_language("test.go") == "go"
        assert auditor._detect_language("test.rs") == "rust"
        assert auditor._detect_language("test.unknown") == "unknown"

    def test_group_by_language(self):
        """Test language grouping."""
        auditor = InnerAuditor()

        files = ["test.py", "app.js", "types.ts", "main.py"]
        grouped = auditor._group_by_language(files)

        assert len(grouped["python"]) == 2
        assert len(grouped["javascript"]) == 1
        assert len(grouped["typescript"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
