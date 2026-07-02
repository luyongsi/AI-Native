"""Code-specific compressor that removes comments, logs, and whitespace."""

import re
import logging
from typing import Set

logger = logging.getLogger(__name__)


class CodeCompressor:
    """Compress code by removing comments, logs, and unnecessary whitespace."""

    # Language-specific comment patterns
    COMMENT_PATTERNS = {
        # Single-line comments
        'python': r'^\s*#.*$',
        'javascript': r'^\s*//.*$',
        'typescript': r'^\s*//.*$',
        'go': r'^\s*//.*$',
        'rust': r'^\s*//.*$',
        'java': r'^\s*//.*$',
        'c': r'^\s*//.*$',
        'cpp': r'^\s*//.*$',
        'cs': r'^\s*//.*$',
        'ruby': r'^\s*#.*$',
        'php': r'^\s*//.*$|^\s*#.*$',
        'shell': r'^\s*#.*$',
        'bash': r'^\s*#.*$',
    }

    # Common log statement patterns
    LOG_PATTERNS = {
        'python': [
            r'^\s*print\s*\(',
            r'^\s*logger\.(debug|info|warning|error|critical)\s*\(',
            r'^\s*logging\.(debug|info|warning|error|critical)\s*\(',
        ],
        'javascript': [
            r'^\s*console\.(log|debug|info|warn|error)\s*\(',
            r'^\s*logger\.(debug|info|warning|error)\s*\(',
        ],
        'typescript': [
            r'^\s*console\.(log|debug|info|warn|error)\s*\(',
            r'^\s*logger\.(debug|info|warning|error)\s*\(',
        ],
        'java': [
            r'^\s*System\.out\.println\s*\(',
            r'^\s*logger\.(debug|info|warn|error)\s*\(',
        ],
        'go': [
            r'^\s*fmt\.Print(ln|f)?\s*\(',
            r'^\s*log\.(Print|Printf|Println)\s*\(',
        ],
    }

    def __init__(self):
        """Initialize code compressor."""
        self.block_comment_pattern = re.compile(r'/\*[\s\S]*?\*/', re.MULTILINE)

    def compress(self, code: str, language: str = 'python') -> str:
        """Compress code by removing comments, logs, and whitespace.

        Args:
            code: Source code to compress
            language: Programming language (python, javascript, etc.)

        Returns:
            Compressed code
        """
        if not code or len(code.strip()) == 0:
            return code

        lines = code.split('\n')
        compressed_lines = []

        for line in lines:
            # Skip empty lines
            if not line.strip():
                continue

            # Skip single-line comments
            if self._is_comment_line(line, language):
                continue

            # Skip log statements
            if self._is_log_statement(line, language):
                continue

            # Keep the line
            compressed_lines.append(line)

        # Join lines and remove block comments (/* ... */)
        result = '\n'.join(compressed_lines)
        result = self.block_comment_pattern.sub('', result)

        # Remove multiple consecutive empty lines
        result = re.sub(r'\n\s*\n\s*\n+', '\n\n', result)

        # Remove trailing whitespace on each line
        lines = result.split('\n')
        lines = [line.rstrip() for line in lines]
        result = '\n'.join(lines)

        logger.debug(
            f"Code compression ({language}): {len(code)} -> {len(result)} chars "
            f"(ratio: {len(result) / len(code) if code else 1:.2%})"
        )

        return result.strip()

    def _is_comment_line(self, line: str, language: str) -> bool:
        """Check if line is a comment.

        Args:
            line: Line to check
            language: Programming language

        Returns:
            True if line is a comment
        """
        pattern = self.COMMENT_PATTERNS.get(language)
        if pattern:
            return bool(re.match(pattern, line, re.IGNORECASE))
        return False

    def _is_log_statement(self, line: str, language: str) -> bool:
        """Check if line is a log statement.

        Args:
            line: Line to check
            language: Programming language

        Returns:
            True if line is a log statement
        """
        patterns = self.LOG_PATTERNS.get(language, [])
        for pattern in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def estimate_compression_ratio(code: str, language: str = 'python') -> float:
        """Estimate compression ratio for code.

        Args:
            code: Source code
            language: Programming language

        Returns:
            Estimated compression ratio (0.0-1.0)
        """
        compressor = CodeCompressor()
        compressed = compressor.compress(code, language)
        if not code:
            return 1.0
        return len(compressed) / len(code)


def compress_code(code: str, language: str = 'python') -> str:
    """Convenience function to compress code.

    Args:
        code: Source code
        language: Programming language

    Returns:
        Compressed code
    """
    compressor = CodeCompressor()
    return compressor.compress(code, language)
