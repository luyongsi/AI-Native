"""Unit tests for sanitizers: SecretScanner, PIIDetector, ContextSanitizer."""

import pytest
import asyncio
from sanitizers.secret_scanner import SecretScanner, SecretFinding
from sanitizers.pii_detector import PIIDetector, PIIFinding
from sanitizers.context_sanitizer import ContextSanitizer, Metrics


class TestSecretScanner:
    """Test SecretScanner detection and redaction."""

    def setup_method(self):
        self.scanner = SecretScanner()

    def test_detect_openai_api_key(self):
        """Test detection of OpenAI-style API key."""
        text = "My API key is sk-1234567890abcdefghijklmnopqrst"
        findings = self.scanner.scan(text)
        assert len(findings) > 0
        assert findings[0].type == 'api_key'
        assert 'sk-' in findings[0].value

    def test_detect_api_key_with_assignment(self):
        """Test detection of API key with assignment."""
        text = 'api_key = "abcdef1234567890abcdef1234567890"'
        findings = self.scanner.scan(text)
        assert len(findings) > 0
        assert findings[0].type == 'api_key'

    def test_detect_password(self):
        """Test detection of password."""
        text = 'password: "MySecurePassword123!"'
        findings = self.scanner.scan(text)
        assert len(findings) > 0
        assert findings[0].type == 'password'

    def test_detect_db_connection(self):
        """Test detection of database connection strings."""
        text = 'connect to postgres://user:secretpassword@localhost:5432'
        findings = self.scanner.scan(text)
        assert len(findings) > 0
        assert findings[0].type == 'db_connection'

    def test_detect_jwt_token(self):
        """Test detection of JWT tokens."""
        text = 'token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U'
        findings = self.scanner.scan(text)
        assert len(findings) > 0
        assert findings[0].type == 'jwt_token'

    def test_detect_aws_key(self):
        """Test detection of AWS access keys."""
        text = 'AWS key: AKIAIOSFODNN7EXAMPLE'
        findings = self.scanner.scan(text)
        assert len(findings) > 0
        assert findings[0].type == 'aws_key'

    def test_redact_api_key(self):
        """Test redaction of API key."""
        text = 'My API key is sk-1234567890abcdefghijklmnopqrst and it is secret'
        findings = self.scanner.scan(text)
        redacted = self.scanner.redact(text, findings)
        assert 'sk-' not in redacted
        assert '***REDACTED_SECRET***' in redacted
        assert 'and it is secret' in redacted

    def test_redact_db_connection(self):
        """Test redaction of database connection."""
        text = 'connect postgres://user:mypassword@localhost:5432 to database'
        findings = self.scanner.scan(text)
        redacted = self.scanner.redact(text, findings)
        assert 'mypassword' not in redacted
        assert 'postgres://' in redacted
        assert 'to database' in redacted

    def test_scan_and_redact(self):
        """Test scan_and_redact combined operation."""
        text = 'api_key="secret123456789012345678" and password="pass123"'
        redacted, findings = self.scanner.scan_and_redact(text)
        assert len(findings) == 2
        assert 'secret' not in redacted
        assert 'pass123' not in redacted
        assert '***REDACTED_SECRET***' in redacted

    def test_no_false_positives(self):
        """Test that normal text doesn't trigger false positives."""
        text = 'The API concept is important. Password management is critical.'
        findings = self.scanner.scan(text)
        assert len(findings) == 0


class TestPIIDetector:
    """Test PIIDetector detection and redaction."""

    def setup_method(self):
        self.detector = PIIDetector()

    def test_detect_china_phone(self):
        """Test detection of Chinese phone numbers."""
        text = 'Call me at 13812345678'
        findings = self.detector.detect(text)
        assert len(findings) > 0
        assert findings[0].type == 'phone_cn'
        assert '13812345678' in findings[0].value

    def test_detect_email(self):
        """Test detection of email addresses."""
        text = 'Contact me at john.doe@example.com for details'
        findings = self.detector.detect(text)
        assert len(findings) > 0
        assert findings[0].type == 'email'
        assert 'john.doe@example.com' in findings[0].value

    def test_detect_china_id_card(self):
        """Test detection of Chinese ID cards."""
        text = 'ID: 110101199003071234'
        findings = self.detector.detect(text)
        assert len(findings) > 0
        assert findings[0].type == 'id_card_cn'

    def test_detect_credit_card(self):
        """Test detection of credit card numbers."""
        text = 'Card: 1234-5678-9012-3456'
        findings = self.detector.detect(text)
        assert len(findings) > 0
        assert findings[0].type == 'credit_card'

    def test_detect_us_ssn(self):
        """Test detection of US Social Security Numbers."""
        text = 'SSN: 123-45-6789'
        findings = self.detector.detect(text)
        assert len(findings) > 0
        assert findings[0].type == 'ssn_us'

    def test_detect_china_passport(self):
        """Test detection of Chinese passports."""
        text = 'Passport: G12345678'
        findings = self.detector.detect(text)
        assert len(findings) > 0
        assert findings[0].type == 'passport_cn'

    def test_redact_email(self):
        """Test redaction of email."""
        text = 'Email john@example.com is private'
        findings = self.detector.detect(text)
        redacted = self.detector.redact(text, findings)
        assert 'john@example.com' not in redacted
        assert '[EMAIL_REDACTED]' in redacted
        assert 'is private' in redacted

    def test_redact_phone(self):
        """Test redaction of phone number."""
        text = 'Call 13812345678 tomorrow'
        findings = self.detector.detect(text)
        redacted = self.detector.redact(text, findings)
        assert '13812345678' not in redacted
        assert '[PHONE_REDACTED]' in redacted
        assert 'tomorrow' in redacted

    def test_detect_and_redact(self):
        """Test detect_and_redact combined operation."""
        text = 'Contact john@example.com or call 13812345678'
        redacted, findings = self.detector.detect_and_redact(text)
        assert len(findings) == 2
        assert 'john@example.com' not in redacted
        assert '13812345678' not in redacted
        assert '[EMAIL_REDACTED]' in redacted
        assert '[PHONE_REDACTED]' in redacted

    def test_no_false_positives(self):
        """Test that normal text doesn't trigger false positives."""
        text = 'Email is a communication tool. The phone system is down.'
        findings = self.detector.detect(text)
        assert len(findings) == 0


class TestMetrics:
    """Test Metrics collection."""

    def test_metrics_initialization(self):
        """Test metrics initialization."""
        from sanitizers.context_sanitizer import Metrics
        metrics = Metrics()
        assert metrics.redactions_total == 0
        assert len(metrics.sanitize_durations) == 0
        assert metrics.whitelist_bypasses == 0

    def test_record_redactions(self):
        """Test recording redactions."""
        from sanitizers.context_sanitizer import Metrics
        metrics = Metrics()
        metrics.record_redactions(5)
        metrics.record_redactions(3)
        assert metrics.redactions_total == 8

    def test_record_duration(self):
        """Test recording duration."""
        from sanitizers.context_sanitizer import Metrics
        metrics = Metrics()
        metrics.record_duration(0.05)
        metrics.record_duration(0.10)
        metrics.record_duration(0.15)
        assert len(metrics.sanitize_durations) == 3

    def test_p95_duration(self):
        """Test P95 duration calculation."""
        from sanitizers.context_sanitizer import Metrics
        metrics = Metrics()
        for i in range(100):
            metrics.record_duration(0.001 * i)
        p95 = metrics.get_p95_duration()
        assert p95 > 0
        assert p95 < 0.1

    def test_get_stats(self):
        """Test aggregated statistics."""
        from sanitizers.context_sanitizer import Metrics
        metrics = Metrics()
        metrics.record_redactions(10)
        metrics.record_duration(0.05)
        metrics.record_whitelist_bypass()
        stats = metrics.get_stats()
        assert stats['redactions_total'] == 10
        assert stats['sanitize_operations'] == 1
        assert stats['whitelist_bypasses'] == 1


class TestContextSanitizer:
    """Test ContextSanitizer integration."""

    def setup_method(self):
        self.sanitizer = ContextSanitizer()

    @pytest.mark.asyncio
    async def test_sanitize_context_normal_agent(self):
        """Test sanitization for normal agent."""
        context = {
            'candidates': [
                {
                    'content': 'API key: sk-1234567890abcdefghijklmnopqrst',
                    'file_path': 'config.py',
                }
            ]
        }
        result = await self.sanitizer.sanitize_context(context, 'A1')
        assert result['candidates'][0]['sanitized'] is True
        assert result['candidates'][0]['redactions'] > 0
        assert 'sk-' not in result['candidates'][0]['content']

    @pytest.mark.asyncio
    async def test_sanitize_context_whitelisted_agent(self):
        """Test that whitelisted agent bypasses sanitization."""
        context = {
            'candidates': [
                {
                    'content': 'API key: sk-1234567890abcdefghijklmnopqrst',
                    'file_path': 'config.py',
                }
            ]
        }
        result = await self.sanitizer.sanitize_context(context, 'A12')
        assert result['candidates'][0]['content'] == context['candidates'][0]['content']

    @pytest.mark.asyncio
    async def test_sanitize_multiple_issues(self):
        """Test sanitization of content with multiple secrets and PII."""
        context = {
            'candidates': [
                {
                    'content': (
                        'Database: postgres://user:secretpass@localhost:5432 '
                        'Email: john@example.com, Phone: 13812345678'
                    ),
                    'file_path': 'db_config.py',
                }
            ]
        }
        result = await self.sanitizer.sanitize_context(context, 'A5')
        sanitized_content = result['candidates'][0]['content']
        assert 'secretpass' not in sanitized_content
        assert 'john@example.com' not in sanitized_content
        assert '13812345678' not in sanitized_content
        assert result['candidates'][0]['redactions'] >= 3

    @pytest.mark.asyncio
    async def test_sanitize_clean_content(self):
        """Test that clean content is not modified."""
        context = {
            'candidates': [
                {
                    'content': 'This is clean code with no secrets or PII',
                    'file_path': 'main.py',
                }
            ]
        }
        result = await self.sanitizer.sanitize_context(context, 'A1')
        assert result['candidates'][0]['redactions'] == 0
        assert result['candidates'][0]['content'] == context['candidates'][0]['content']

    def test_metrics_collection(self):
        """Test that metrics are properly collected."""
        metrics = self.sanitizer.get_metrics()
        assert 'redactions_total' in metrics
        assert 'sanitize_operations' in metrics
        assert 'p95_duration_ms' in metrics

    def test_whitelist_config(self):
        """Test whitelist configuration."""
        assert 'A12' in self.sanitizer.whitelist['agents']
        assert self.sanitizer._is_agent_whitelisted('A12')
        assert not self.sanitizer._is_agent_whitelisted('A1')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
