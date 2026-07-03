"""
A12 Security Scanner — Integration Tests

Tests for security scanner functionality with Bandit, npm audit, and Semgrep.
Includes both unit tests and integration tests with mocked tools.
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List

import pytest

from a12.cwe_mapper import CWEMapper
from a12.security_scanner import SecurityScanner

logger = logging.getLogger(__name__)


class TestSecurityScanner:
    """Test suite for SecurityScanner."""

    @pytest.fixture
    def scanner(self):
        """Create scanner instance."""
        return SecurityScanner(timeout=30)

    @pytest.fixture
    def cwe_mapper(self):
        """Create CWE mapper instance."""
        return CWEMapper()

    @pytest.fixture
    def temp_python_file(self):
        """Create a temporary Python file for testing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(
                """
import os
import pickle

# Vulnerable code examples for testing
api_key = "sk-1234567890abcdef"
password = "admin123"

def execute_command(user_input):
    os.system(user_input)  # Command injection

def parse_data(data):
    return pickle.loads(data)  # Insecure deserialization

def unsafe_redirect(url):
    return redirect(url)  # Unvalidated redirect
"""
            )
            yield f.name
            os.unlink(f.name)

    @pytest.fixture
    def temp_js_file(self):
        """Create a temporary JavaScript file for testing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False
        ) as f:
            f.write(
                """
const apiKey = "sk-1234567890abcdef";
const password = "admin123";

function handleUserInput(input) {
    document.innerHTML = input;  // XSS vulnerability
}

function unsafeRedirect(url) {
    window.location = url;  // Unvalidated redirect
}

fetch(userProvidedUrl);  // Potential SSRF
"""
            )
            yield f.name
            os.unlink(f.name)

    @pytest.fixture
    def temp_package_json(self):
        """Create a temporary package.json for testing."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="package.json", delete=False
        ) as f:
            f.write(
                json.dumps(
                    {
                        "name": "test-app",
                        "version": "1.0.0",
                        "dependencies": {
                            "express": "^4.17.0",
                            "lodash": "^4.17.0",
                        },
                    }
                )
            )
            yield f.name
            os.unlink(f.name)

    # ========================================================================
    # Bandit Integration Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_parse_bandit_findings(self, scanner):
        """Test Bandit findings parser."""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_confidence": "MEDIUM",
                    "issue_cwe": {"id": "CWE-78"},
                    "issue_text": "Use of system calls with shell=True",
                    "line_number": 42,
                    "filename": "app.py",
                    "test_id": "B602",
                    "test_name": "shell_injection",
                },
                {
                    "issue_severity": "CRITICAL",
                    "issue_confidence": "HIGH",
                    "issue_cwe": {"id": "CWE-798"},
                    "issue_text": "Hardcoded credentials",
                    "line_number": 15,
                    "filename": "config.py",
                    "test_id": "B105",
                    "test_name": "hardcoded_credentials",
                },
            ]
        }

        findings = scanner._parse_bandit_findings(bandit_output["results"])

        assert len(findings) == 2
        assert findings[0]["tool"] == "bandit"
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["cwe"] == "CWE-78"
        assert findings[1]["severity"] == "CRITICAL"

    def test_parse_npm_audit_findings(self, scanner):
        """Test npm audit findings parser."""
        npm_output = {
            "vulnerabilities": {
                "lodash": {
                    "name": "lodash",
                    "severity": "high",
                    "version": "4.17.15",
                    "vulnerable_versions": "<4.17.20",
                    "title": "Prototype Pollution in lodash",
                    "url": "https://nvd.nist.gov/vuln/detail/CVE-2020-8203",
                    "cvss": {"score": 7.4},
                    "cwe": ["CWE-1321"],
                },
                "express": {
                    "name": "express",
                    "severity": "moderate",
                    "version": "4.17.0",
                    "vulnerable_versions": "<4.17.1",
                    "title": "Express middleware bypass",
                    "url": "https://nvd.nist.gov/vuln/detail/CVE-2021-12345",
                    "cvss": {"score": 5.3},
                    "cwe": ["CWE-79"],
                },
            }
        }

        findings = scanner._parse_npm_audit_findings(npm_output)

        assert len(findings) == 2
        assert findings[0]["tool"] == "npm_audit"
        assert findings[0]["package"] == "lodash"
        assert findings[0]["severity"] == "HIGH"
        assert findings[1]["severity"] == "MEDIUM"  # moderate -> MEDIUM

    def test_convert_semgrep_findings(self, scanner):
        """Test Semgrep findings converter."""
        semgrep_findings = [
            {
                "check_id": "hardcoded-credentials",
                "extra": {
                    "severity": "ERROR",
                    "message": "Hardcoded API key detected",
                    "metadata": {"cwe": "CWE-798"},
                },
                "path": "config.py",
                "start": {"line": 10, "col": 5},
            },
            {
                "check_id": "sql-injection-risk",
                "extra": {
                    "severity": "ERROR",
                    "message": "Potential SQL injection",
                    "metadata": {"cwe": "CWE-89"},
                },
                "path": "db.py",
                "start": {"line": 42, "col": 0},
            },
        ]

        findings = scanner._convert_semgrep_findings(semgrep_findings)

        assert len(findings) == 2
        assert findings[0]["tool"] == "semgrep"
        assert findings[0]["severity"] == "CRITICAL"  # ERROR -> CRITICAL
        assert findings[1]["severity"] == "CRITICAL"

    def test_summarize_findings(self, scanner):
        """Test findings summarization."""
        findings = [
            {"tool": "bandit", "severity": "CRITICAL"},
            {"tool": "bandit", "severity": "HIGH"},
            {"tool": "semgrep", "severity": "HIGH"},
            {"tool": "semgrep", "severity": "MEDIUM"},
            {"tool": "npm_audit", "severity": "LOW"},
        ]

        summary = scanner._summarize_findings(findings)

        assert summary["total_findings"] == 5
        assert summary["by_severity"]["CRITICAL"] == 1
        assert summary["by_severity"]["HIGH"] == 2
        assert summary["by_severity"]["MEDIUM"] == 1
        assert summary["by_severity"]["LOW"] == 1
        assert summary["by_tool"]["bandit"] == 2
        assert summary["by_tool"]["semgrep"] == 2
        assert summary["by_tool"]["npm_audit"] == 1
        assert summary["critical_count"] == 1
        assert summary["high_count"] == 2

    # ========================================================================
    # CWE Mapper Tests
    # ========================================================================

    def test_cwe_mapping(self, cwe_mapper):
        """Test CWE to severity mapping."""
        assert cwe_mapper.map_severity("CWE-89") == "CRITICAL"  # SQL Injection
        assert cwe_mapper.map_severity("CWE-78") == "CRITICAL"  # Command Injection
        assert cwe_mapper.map_severity("CWE-79") == "HIGH"      # XSS
        assert cwe_mapper.map_severity("CWE-22") == "HIGH"      # Path Traversal
        assert cwe_mapper.map_severity("CWE-327") == "MEDIUM"   # Weak Crypto
        assert cwe_mapper.map_severity("CWE-319") == "LOW"      # Cleartext
        assert cwe_mapper.map_severity("UNKNOWN-999") == "MEDIUM"  # Default

    def test_bandit_test_cwe_mapping(self, cwe_mapper):
        """Test Bandit test ID to severity mapping."""
        assert cwe_mapper.map_bandit_test_to_severity("B602") == "CRITICAL"  # Shell injection
        assert cwe_mapper.map_bandit_test_to_severity("B105") == "CRITICAL"  # Hardcoded SQL
        assert cwe_mapper.map_bandit_test_to_severity("B301") == "HIGH"      # Pickle
        assert cwe_mapper.map_bandit_test_to_severity("B501") == "MEDIUM"    # Request verify

    def test_risk_score_calculation(self, cwe_mapper):
        """Test risk score calculation."""
        findings = [
            {"severity": "CRITICAL"},
            {"severity": "CRITICAL"},
            {"severity": "HIGH"},
            {"severity": "MEDIUM"},
        ]

        score = cwe_mapper.calculate_risk_score(findings)

        # 3.0 + 3.0 + 2.0 + 1.0 = 9.0
        assert score == 9.0

    def test_risk_score_capped_at_10(self, cwe_mapper):
        """Test risk score is capped at 10.0."""
        findings = [{"severity": "CRITICAL"} for _ in range(10)]

        score = cwe_mapper.calculate_risk_score(findings)

        assert score == 10.0  # Capped

    def test_risk_level_estimation(self, cwe_mapper):
        """Test risk level estimation from score."""
        assert cwe_mapper.estimate_risk_level(9.0) == "CRITICAL"
        assert cwe_mapper.estimate_risk_level(7.0) == "HIGH"
        assert cwe_mapper.estimate_risk_level(4.0) == "MEDIUM"
        assert cwe_mapper.estimate_risk_level(1.0) == "LOW"
        assert cwe_mapper.estimate_risk_level(0.0) == "NONE"

    def test_recommendation_generation(self, cwe_mapper):
        """Test recommendation generation."""
        rec = cwe_mapper.get_recommendation(risk_score=9.5, critical_count=2, high_count=1)
        assert "REJECT" in rec
        assert "critical" in rec

        rec = cwe_mapper.get_recommendation(risk_score=7.5, critical_count=0, high_count=3)
        assert "REJECT" in rec

        rec = cwe_mapper.get_recommendation(risk_score=5.0, critical_count=0, high_count=2)
        assert "CONDITIONAL" in rec or "REVIEW" in rec

        rec = cwe_mapper.get_recommendation(risk_score=1.0, critical_count=0, high_count=0)
        assert "APPROVE" in rec

    def test_categorize_findings(self, cwe_mapper):
        """Test findings categorization."""
        findings = [
            {"severity": "CRITICAL", "tool": "bandit", "cwe": "CWE-78"},
            {"severity": "HIGH", "tool": "semgrep", "cwe": "CWE-79"},
            {"severity": "MEDIUM", "tool": "bandit", "cwe": "CWE-327"},
            {"severity": "LOW", "tool": "npm_audit", "cwe": "CWE-319"},
        ]

        categories = cwe_mapper.categorize_findings(findings)

        assert len(categories["by_severity"]["CRITICAL"]) == 1
        assert len(categories["by_severity"]["HIGH"]) == 1
        assert len(categories["by_severity"]["MEDIUM"]) == 1
        assert len(categories["by_severity"]["LOW"]) == 1
        assert len(categories["by_tool"]["bandit"]) == 2
        assert len(categories["by_tool"]["semgrep"]) == 1
        assert len(categories["by_tool"]["npm_audit"]) == 1
        assert "CWE-78" in categories["by_cwe"]

    def test_generate_report(self, cwe_mapper):
        """Test comprehensive report generation."""
        findings = [
            {"severity": "CRITICAL", "tool": "bandit"},
            {"severity": "HIGH", "tool": "semgrep"},
            {"severity": "MEDIUM", "tool": "npm_audit"},
        ]

        report = cwe_mapper.generate_report(findings)

        assert report["decision"] == "REJECT"  # Score > 7.0
        assert report["total_findings"] == 3
        assert report["critical_count"] == 1
        assert report["high_count"] == 1
        assert report["medium_count"] == 1
        assert report["risk_level"] == "HIGH"
        assert "recommendation" in report

    # ========================================================================
    # Integration Tests (with real file scanning if tools available)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_scan_multiple_files(self, scanner):
        """Test scanning multiple files."""
        files = ["test.py", "test.js", "package.json"]

        result = await scanner.scan_multiple(files, cwd=None)

        assert result["success"] == True
        assert result["scanned_files"] == 3
        assert "results_by_file" in result
        assert "all_findings" in result
        assert "summary" in result

    def test_scanner_initialization(self):
        """Test scanner initialization."""
        scanner = SecurityScanner(timeout=45)

        assert scanner.timeout == 45
        assert scanner.semgrep is not None
        assert scanner.executor is not None

    def test_scanner_with_custom_rules(self):
        """Test scanner with custom rules path."""
        custom_rules = "/path/to/custom/rules.yaml"
        scanner = SecurityScanner(custom_rules_path=custom_rules)

        assert scanner.semgrep.rules_path == custom_rules

    # ========================================================================
    # End-to-End Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_end_to_end_security_analysis(self, cwe_mapper):
        """Test end-to-end security analysis flow."""
        # Simulate findings from all tools
        findings = [
            {
                "tool": "bandit",
                "severity": "CRITICAL",
                "cwe": "CWE-78",
                "message": "Command injection",
                "file": "app.py",
                "line": 42,
            },
            {
                "tool": "semgrep",
                "severity": "HIGH",
                "cwe": "CWE-79",
                "message": "XSS vulnerability",
                "file": "templates.py",
                "line": 15,
            },
            {
                "tool": "npm_audit",
                "severity": "HIGH",
                "package": "lodash",
                "message": "Prototype pollution",
                "url": "https://nvd.nist.gov/...",
            },
        ]

        report = cwe_mapper.generate_report(findings)

        assert report["decision"] == "REJECT"
        assert report["critical_count"] == 1
        assert report["high_count"] == 2
        assert report["risk_score"] > 7.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
