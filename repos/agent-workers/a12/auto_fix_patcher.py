"""
a12/auto_fix_patcher.py — Auto-Fix Patcher

Generates and applies automated fixes for code review findings.
Produces unified-diff-style patches with before/after snippets.

Real implementation pattern:
  - Use tree-sitter or AST to parse the source file
  - Generate a structured edit (insert, delete, replace) at a specific range
  - Produce a unified diff using difflib or similar
  - Apply the patch via git apply or direct file write (with backup)
  - Validate by re-running the linter / type checker
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class AutoFixPatcher:
    """Generates and applies auto-fix patches for code review issues.

    Designed to fix deterministic, low-risk issues automatically:
    - Unused imports / variables
    - Missing type hints
    - Style violations
    - Simple refactors (rename, extract constant)

    Does NOT auto-fix complex logic errors or security issues — those
    are flagged for manual review.
    """

    def __init__(self, backup_dir: str = ".a12-backups"):
        self.backup_dir = backup_dir

    async def generate_fix(self, issue: dict, file_content: str) -> dict:
        """Generate a fix patch for a given issue.

        Args:
            issue: Issue dict with file, line, severity, category, rule, description
            file_content: The current content of the file to patch

        Returns:
            dict with fixed, patch, confidence, before_snippet, after_snippet, explanation
        """
        logger.info(
            "Generating fix for %s:%s (%s)",
            issue.get("file", "?"), issue.get("line", "?"), issue.get("rule", "?"),
        )

        # Simulate generation time
        await asyncio.sleep(0.15)

        file_name = issue.get("file", "unknown.py")
        line = issue.get("line", 1)
        rule = issue.get("rule", "unknown")
        category = issue.get("category", "style")

        # Determine fixability
        auto_fixable_categories = {"style", "unused-import", "missing-type-hint", "naming"}
        fixable = category in auto_fixable_categories or rule in {
            "no-unused-vars", "prefer-const", "missing-return-type", "unused-import",
        }

        if not fixable:
            return {
                "fixed": False,
                "patch": "",
                "confidence": 0.0,
                "before_snippet": f"// line {line}: {issue.get('description', rule)}",
                "after_snippet": "",
                "explanation": f"Rule '{rule}' (category: {category}) is not auto-fixable. Manual review required.",
            }

        # Generate a realistic stub patch
        confidence = round(random.uniform(0.75, 0.99), 3)
        before_snippet, after_snippet, patch = self._build_patch(file_name, line, rule)

        result = {
            "fixed": True,
            "patch": patch,
            "confidence": confidence,
            "before_snippet": before_snippet,
            "after_snippet": after_snippet,
            "explanation": f"Auto-fix applied for rule '{rule}' at {file_name}:{line}",
        }

        logger.info("Fix generated for %s:%s confidence=%.2f", file_name, line, confidence)
        return result

    async def apply_fix(self, file_path: str, patch: str) -> dict:
        """Apply a patch to a file, creating a backup first.

        In production this would:
          - Write the patch to a temp file
          - Run `git apply --check` to verify
          - Apply with `git apply` or direct file write
          - Create a backup at backup_dir/YYYYMMDD-HHMMSS/filename

        Args:
            file_path: Absolute or relative path to the file to patch
            patch: Unified diff patch string

        Returns:
            dict with applied, backup_path, new_content_hash
        """
        logger.info("Applying patch to %s", file_path)

        # Simulate apply time
        await asyncio.sleep(0.1)

        backup_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = f"{self.backup_dir}/{backup_id}/{file_path}"

        # Simulate new content hash
        new_content_hash = hashlib.sha256(
            f"{file_path}:{patch}:{uuid.uuid4()}".encode()
        ).hexdigest()[:16]

        result = {
            "applied": True,
            "backup_path": backup_path,
            "new_content_hash": new_content_hash,
            "file_path": file_path,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("Patch applied to %s (backup: %s)", file_path, backup_path)
        return result

    def _build_patch(self, file_name: str, line: int, rule: str) -> tuple[str, str, str]:
        """Build a realistic stub patch with before/after snippets."""
        patches: dict[str, tuple[str, str]] = {
            "no-unused-vars": (
                f"const unusedVar = getData();  // line {line}",
                "// (removed unused variable)",
            ),
            "prefer-const": (
                f"let count = items.length;  // line {line}",
                f"const count = items.length;  // line {line}",
            ),
            "missing-return-type": (
                f"def get_user(user_id):  # line {line}",
                f"def get_user(user_id: str) -> User:  # line {line}",
            ),
            "unused-import": (
                f"import {{ OldParser }} from './parser';  // line {line}",
                "// (removed unused import: OldParser)",
            ),
            "missing-auth-check": (
                f"@app.route('/api/orders')  # line {line}",
                f"@app.route('/api/orders')\n@require_auth  # line {line}",
            ),
            "sql-injection-risk": (
                f"cursor.execute(f\"SELECT * FROM users WHERE id={{user_id}}\")  # line {line}",
                f'cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))  # line {line}',
            ),
            "hardcoded-credentials": (
                f'DB_PASSWORD = "admin123"  # line {line}',
                f'DB_PASSWORD = os.getenv("DB_PASSWORD")  # line {line}',
            ),
        }

        before, after = patches.get(
            rule,
            (
                f"// {rule} violation at line {line}",
                f"// {rule} fixed at line {line}",
            ),
        )

        patch = (
            f"--- a/{file_name}\n"
            f"+++ b/{file_name}\n"
            f"@@ -{line},1 +{line},1 @@\n"
            f"-{before}\n"
            f"+{after}\n"
        )

        return before, after, patch
