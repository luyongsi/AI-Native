"""PIIDetector: detect and redact personally identifiable information."""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class PIIFinding:
    """Represents a detected PII element in text."""
    type: str
    value: str
    start: int
    end: int


class PIIDetector:
    """Scan text for PII: phone numbers, emails, IDs, credit cards (China + International standards)."""

    # Regex patterns for different PII types
    PATTERNS = {
        'phone_cn': r'1[3-9]\d{9}',  # China mobile: 1[3-9]xxxxxxxx
        'phone_intl': r'\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}',
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'id_card_cn': r'\d{17}[\dXx]',  # China ID: 17 digits + check digit (X or 0-9)
        'credit_card': r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
        'ssn_us': r'\b\d{3}-\d{2}-\d{4}\b',  # US Social Security Number
        'passport_cn': r'[GE]\d{8}',  # China passport format
    }

    def __init__(self):
        """Initialize detector with compiled regex patterns."""
        self.compiled_patterns = {}
        for pii_type, pattern in self.PATTERNS.items():
            self.compiled_patterns[pii_type] = re.compile(
                pattern, re.IGNORECASE | re.MULTILINE
            )

    def detect(self, text: str) -> List[PIIFinding]:
        """
        Detect PII in text.

        Args:
            text: Text to scan

        Returns:
            List of PIIFinding objects
        """
        findings = []

        for pii_type, pattern in self.compiled_patterns.items():
            try:
                matches = pattern.finditer(text)
                for match in matches:
                    findings.append(
                        PIIFinding(
                            type=pii_type,
                            value=match.group(0),
                            start=match.start(),
                            end=match.end(),
                        )
                    )
            except Exception as e:
                # Skip malformed patterns silently
                pass

        return findings

    def redact(self, text: str, findings: List[PIIFinding]) -> str:
        """
        Redact PII from text.

        Args:
            text: Original text
            findings: List of PIIFinding objects

        Returns:
            Text with PII replaced by redaction markers
        """
        if not findings:
            return text

        # Sort findings in reverse order by start position
        # to avoid index shifting during replacement
        sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)

        for finding in sorted_findings:
            if finding.type == 'phone_cn' or finding.type == 'phone_intl':
                replacement = '[PHONE_REDACTED]'
            elif finding.type == 'email':
                replacement = '[EMAIL_REDACTED]'
            elif finding.type == 'id_card_cn':
                replacement = '[ID_CARD_REDACTED]'
            elif finding.type == 'credit_card':
                replacement = '[CARD_REDACTED]'
            elif finding.type == 'ssn_us':
                replacement = '[SSN_REDACTED]'
            elif finding.type == 'passport_cn':
                replacement = '[PASSPORT_REDACTED]'
            else:
                replacement = '[PII_REDACTED]'

            text = text[: finding.start] + replacement + text[finding.end :]

        return text

    def detect_and_redact(self, text: str) -> tuple[str, List[PIIFinding]]:
        """
        Detect and redact PII in one pass.

        Args:
            text: Text to process

        Returns:
            Tuple of (redacted_text, findings)
        """
        findings = self.detect(text)
        redacted_text = self.redact(text, findings)
        return redacted_text, findings
