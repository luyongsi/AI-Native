"""SecretScanner: detect and redact API keys, passwords, and database credentials."""

import re
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class SecretFinding:
    """Represents a detected secret in text."""
    type: str
    value: str
    start: int
    end: int


class SecretScanner:
    """Scan text for common secret patterns: API keys, passwords, DB connections, JWT tokens, AWS keys."""

    # Regex patterns for different secret types
    PATTERNS = {
        'api_key': [
            r'api[_-]?key["\']?\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']',
            r'API[_-]?KEY["\']?\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']',
            r'sk-[a-zA-Z0-9]{20,}',  # OpenAI-style keys (sk-xxxxx...)
        ],
        'password': [
            r'password["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'PASSWORD["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'passwd["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'pwd["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        ],
        'db_connection': [
            r'(postgres|mysql|mongodb)://[^:]+:([^@]+)@',
            r'jdbc:[^:]+://[^:]+:([^@]+)@',
        ],
        'jwt_token': [
            r'eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+',
        ],
        'aws_key': [
            r'AKIA[0-9A-Z]{16}',
        ],
        'private_key': [
            r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----',
            r'-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----',
        ],
    }

    def __init__(self):
        """Initialize scanner with compiled regex patterns."""
        self.compiled_patterns = {}
        for secret_type, patterns in self.PATTERNS.items():
            self.compiled_patterns[secret_type] = [
                re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for pattern in patterns
            ]

    def scan(self, text: str) -> List[SecretFinding]:
        """
        Scan text for secrets.

        Args:
            text: Text to scan

        Returns:
            List of SecretFinding objects
        """
        findings = []

        for secret_type, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                try:
                    matches = pattern.finditer(text)
                    for match in matches:
                        findings.append(
                            SecretFinding(
                                type=secret_type,
                                value=match.group(0),
                                start=match.start(),
                                end=match.end(),
                            )
                        )
                except Exception as e:
                    # Skip malformed patterns silently
                    pass

        return findings

    def redact(self, text: str, findings: List[SecretFinding]) -> str:
        """
        Redact secrets from text.

        Args:
            text: Original text
            findings: List of SecretFinding objects

        Returns:
            Text with secrets replaced by redaction markers
        """
        if not findings:
            return text

        # Sort findings in reverse order by start position
        # to avoid index shifting during replacement
        sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)

        for finding in sorted_findings:
            if finding.type in ['api_key', 'password', 'jwt_token', 'aws_key']:
                replacement = '***REDACTED_SECRET***'
            elif finding.type == 'db_connection':
                # For DB connections, preserve protocol info but redact credentials
                value = finding.value
                # Extract protocol (postgres://, mysql://, etc)
                proto_match = re.match(r'(\w+://[^:]+:)', value)
                if proto_match:
                    replacement = proto_match.group(1) + '****'
                else:
                    replacement = '***REDACTED_SECRET***'
            elif finding.type == 'private_key':
                replacement = '***REDACTED_PRIVATE_KEY***'
            else:
                replacement = '***REDACTED_SECRET***'

            text = text[: finding.start] + replacement + text[finding.end :]

        return text

    def scan_and_redact(self, text: str) -> tuple[str, List[SecretFinding]]:
        """
        Scan and redact secrets in one pass.

        Args:
            text: Text to process

        Returns:
            Tuple of (redacted_text, findings)
        """
        findings = self.scan(text)
        redacted_text = self.redact(text, findings)
        return redacted_text, findings
