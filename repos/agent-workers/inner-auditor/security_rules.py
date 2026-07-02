"""
Security Rules — Pattern-based security vulnerability detection.

Provides regex patterns for common security issues that can be detected
without external tools, complementing Semgrep and bandit.
"""

import re
from typing import Optional


class SecurityRules:
    """Pattern-based security vulnerability detection."""

    RULES = {
        "sql_injection": {
            "patterns": [
                r"execute\s*\(\s*[f\"].*{.*}.*[f\"]",  # f-string in execute
                r"query\s*=\s*[f\"].*{.*}.*[f\"]",  # f-string in query
                r"sql\s*=\s*['\"]['\"].*%s.*['\"]['\"]",  # % formatting in SQL
            ],
            "severity": "CRITICAL",
            "message": "Potential SQL injection vulnerability",
            "cwe": "CWE-89",
        },
        "xss_vulnerability": {
            "patterns": [
                r"innerHTML\s*=\s*.*\+",  # String concatenation to innerHTML
                r"dangerouslySetInnerHTML",  # React dangerous API
                r"document\.write\s*\(",  # document.write
            ],
            "severity": "HIGH",
            "message": "Potential XSS vulnerability",
            "cwe": "CWE-79",
        },
        "hardcoded_secrets": {
            "patterns": [
                r"(api_key|apiKey|API_KEY)\s*[=:]\s*['\"][^'\"]{10,}['\"]",
                r"(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{6,}['\"]",
                r"(secret|SECRET)\s*[=:]\s*['\"][^'\"]{10,}['\"]",
                r"(token|TOKEN)\s*[=:]\s*['\"][^'\"]{20,}['\"]",
                r"aws_access_key_id\s*[=:]\s*['\"][^'\"]{20,}['\"]",
            ],
            "severity": "CRITICAL",
            "message": "Hardcoded credentials detected",
            "cwe": "CWE-798",
        },
        "insecure_deserialization": {
            "patterns": [
                r"pickle\.load",
                r"json\.loads\s*\(\s*.*from_string",
                r"yaml\.load\s*\(",
                r"eval\s*\(",
                r"exec\s*\(",
            ],
            "severity": "CRITICAL",
            "message": "Insecure deserialization or code execution",
            "cwe": "CWE-502",
        },
        "weak_cryptography": {
            "patterns": [
                r"md5",
                r"sha1",
                r"DES\(",
                r"hashlib\.md5",
                r"hashlib\.sha1",
            ],
            "severity": "HIGH",
            "message": "Weak cryptographic algorithm",
            "cwe": "CWE-327",
        },
        "insecure_random": {
            "patterns": [
                r"random\.randint",
                r"random\.choice",
                r"Math\.random",
                r"Math\.floor\s*\(\s*Math\.random",
            ],
            "severity": "MEDIUM",
            "message": "Insecure random number generation",
            "cwe": "CWE-338",
        },
        "command_injection": {
            "patterns": [
                r"os\.system\s*\(",
                r"subprocess\.call\s*\([f\"]",
                r"shell\s*=\s*True",
                r"exec\s*\(",
            ],
            "severity": "CRITICAL",
            "message": "Potential command injection vulnerability",
            "cwe": "CWE-78",
        },
        "path_traversal": {
            "patterns": [
                r"open\s*\(\s*.*\+\s*filename",
                r"open\s*\(\s*[f\"].*{.*}.*[f\"]",
            ],
            "severity": "HIGH",
            "message": "Potential path traversal vulnerability",
            "cwe": "CWE-22",
        },
    }

    @classmethod
    def scan_content(cls, content: str, language: str) -> list:
        """
        Scan code content for security vulnerabilities.

        Args:
            content: Code content to scan
            language: Programming language

        Returns:
            List of found vulnerabilities with structure:
            {
                "rule": str,
                "severity": str,
                "message": str,
                "line": int,
                "cwe": str,
                "pattern": str
            }
        """
        vulnerabilities = []
        lines = content.split("\n")

        for rule_name, rule_config in cls.RULES.items():
            patterns = rule_config.get("patterns", [])

            for pattern in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE)

                    for line_num, line in enumerate(lines, 1):
                        if regex.search(line):
                            vulnerabilities.append({
                                "rule": rule_name,
                                "severity": rule_config["severity"],
                                "message": rule_config["message"],
                                "line": line_num,
                                "cwe": rule_config.get("cwe", ""),
                                "pattern": pattern,
                                "matched_text": line.strip()[:100],
                            })

                except re.error:
                    pass

        return vulnerabilities
