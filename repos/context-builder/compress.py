"""ContextCompressor: compress mid-position items, preserve head/tail.

Head & tail items are kept intact.
Mid items:
  - Code items: keep signatures + comments, strip body (simplified).
  - Knowledge items: pass through for now (TODO: LLM summarization).
"""

import re
from typing import List

from context_item import ContextItem


# Simple patterns for code compression (signature extraction)
# Matches function/method/class definitions
CODE_SIGNATURE_RE = re.compile(
    r'^(\s*)((?:async\s+)?(?:def|class)\s+\w+\s*\([^)]*\)\s*(?:->.*?)?\s*:)',
    re.MULTILINE
)


def _extract_signatures(code: str) -> str:
    """Extract function/class signatures + comments from code.

    For mid-position code, keep only structural elements + comments,
    dropping implementation bodies.
    """
    lines = code.split('\n')
    result = []
    in_docstring = False
    docstring_quote = None

    for line in lines:
        stripped = line.strip()

        # Always keep comments
        if stripped.startswith('#') or stripped.startswith('//'):
            result.append(line)
            continue

        # Track docstrings / block comments
        if '"""' in stripped or "'''" in stripped:
            result.append(line)
            if in_docstring:
                in_docstring = False
            else:
                in_docstring = True
            continue

        if in_docstring:
            result.append(line)
            continue

        # Keep decorators
        if stripped.startswith('@'):
            result.append(line)
            continue

        # Keep function/class signatures
        match = CODE_SIGNATURE_RE.match(line)
        if match:
            indent = match.group(1)
            sig = match.group(2)
            result.append(f"{indent}{sig}  # [body compressed]")
            continue

    return '\n'.join(result) if result else code[:200] + '...'


class ContextCompressor:
    """Compress context items based on position strategy.

    - head / tail items: kept as-is (most important context)
    - mid items:
        - code items: keep signatures + comments only
        - knowledge items: TODO LLM summarization (pass-through for now)
    """

    # File extensions treated as code
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java',
        '.c', '.cpp', '.h', '.hpp', '.cs', '.rb', '.php', '.swift',
        '.kt', '.scala', '.r', '.sql', '.sh', '.bash', '.ps1',
    }

    @staticmethod
    def _is_code(item: ContextItem) -> bool:
        if item.type == 'code':
            return True
        if item.file:
            ext = '.' + item.file.rsplit('.', 1)[-1] if '.' in item.file else ''
            return ext.lower() in ContextCompressor.CODE_EXTENSIONS
        return False

    def compress(self, items: List[ContextItem],
                 target_tokens: int = 0) -> List[ContextItem]:
        """Compress context items.

        Args:
            items: List of context items (with position already set)
            target_tokens: If > 0, try to fit within this budget by
                           compressing mid items.

        Returns:
            List of context items (some may now have compressed=True)
        """
        for item in items:
            if item.position in ('head', 'tail'):
                # Head and tail items are preserved as-is
                continue

            if item.position == 'discard':
                continue

            # mid items: apply compression
            if self._is_code(item):
                item.content = _extract_signatures(item.content)
                item.tokens = max(1, len(item.content) // 3)
                item.compressed = True

            elif item.type in ('knowledge', 'doc'):
                # TODO: Use LLM to summarize knowledge snippets
                # For now, truncate long content
                if len(item.content) > 2000:
                    item.content = item.content[:2000] + '\n...[truncated, TODO: LLM summary]...'
                    item.tokens = max(1, len(item.content) // 3)
                    item.compressed = True

            # spec, prototype, log: keep as-is for now

        # If a target token budget is provided, further compress mid items
        if target_tokens > 0:
            current_tokens = sum(it.tokens for it in items if it.position != 'discard')
            if current_tokens > target_tokens:
                # Aggressively compress mid code items
                for item in items:
                    if item.position == 'mid' and self._is_code(item):
                        # Keep only the absolute minimum
                        if len(item.content) > 500:
                            item.content = item.content[:500] + '\n...[aggressive compression]...'
                            item.tokens = max(1, len(item.content) // 3)
                            item.compressed = True
                        break  # One item at a time; caller can loop

        return items
