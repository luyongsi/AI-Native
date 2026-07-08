"""
A9 Coder Module — Code Generation Brain

Provides:
- Worktree isolation (subprocess git worktree)
- Context package input processing
- Code diff generation + self-inspection report
- Stateless LLM-based code generation (via injected llm_caller)

The Coder operates in isolation and produces:
  - code_diff: raw code changes
  - self_inspection: reasoning about changes (NOT sent to Auditor)
  - metadata: files changed, lines added/removed
"""

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CoderModule:
    """Code generation brain — produces code diffs from task specs"""

    def __init__(self, llm_caller=None, work_base: str = "/tmp/a9-worktrees", enable_llm: bool = True):
        """
        Args:
            llm_caller: Callable for LLM code generation (injected from A9DevAgent.call_llm).
                        If None, falls back to mock code generation.
            work_base: Base directory for git worktrees
            enable_llm: Whether to use real LLM or mock mode
        """
        self._llm_caller = llm_caller
        self.work_base = work_base
        self.enable_llm = enable_llm
        Path(work_base).mkdir(parents=True, exist_ok=True)

    async def generate(self, task_spec: dict, context: dict) -> dict:
        """
        Generate code changes in an isolated worktree.

        Args:
            task_spec: {
                "type": "backend|frontend|test",
                "title": "Task description",
                "plan": {"files_to_create": [...], "files_to_modify": [...]},
                "openapi_paths": int,
                "erd_tables": int
            }
            context: Full execution context (not directly used by Coder logic)

        Returns:
            {
                "status": "success|failed",
                "diff": {
                    "files_changed": [...],
                    "changes_summary": str,
                    "commit_sha": str,
                    "session_id": str,
                    "created_at": str,
                    "cost_usd": float,
                    "mock": bool
                },
                "self_inspection": {
                    "reasoning": str,
                    "confidence": float,
                    "issues_identified": [...]
                },
                "metadata": {
                    "files_created": int,
                    "files_modified": int,
                    "total_lines_added": int,
                    "total_lines_removed": int,
                    "worktree_path": str
                }
            }
        """
        session_id = f"coder-{uuid.uuid4().hex[:8]}"
        worktree_path = None

        try:
            logger.info(f"[Coder] Starting code generation: {task_spec.get('title')} (session={session_id})")

            # Create isolated worktree
            worktree_path = await self._create_worktree(session_id)
            logger.info(f"[Coder] Worktree created: {worktree_path}")

            # Generate code changes
            files_changed = await self._generate_code_changes(task_spec, worktree_path, session_id)

            # Build diff structure
            diff = self._build_diff(files_changed, task_spec, session_id)

            # Self-inspection (Coder's own reasoning - NOT sent to Auditor)
            self_inspection = self._perform_self_inspection(files_changed, task_spec)

            # Compute metadata
            metadata = self._compute_metadata(files_changed, worktree_path)

            logger.info(f"[Coder] Code generation completed: {len(files_changed)} files changed")

            return {
                "status": "success",
                "diff": diff,
                "self_inspection": self_inspection,
                "metadata": metadata,
            }

        except Exception as e:
            logger.error(f"[Coder] Code generation failed: {e}", exc_info=True)
            return {
                "status": "failed",
                "error": str(e),
                "self_inspection": {"reasoning": f"Generation failed: {e}", "confidence": 0.0, "issues_identified": []},
                "metadata": {"worktree_path": worktree_path},
            }

    async def _create_worktree(self, session_id: str) -> str:
        """Create a git worktree for isolated code generation"""
        worktree_path = os.path.join(self.work_base, f"wt-{session_id}")

        try:
            # Initialize a bare repo if needed
            repo_dir = os.path.join(self.work_base, "main-repo")
            if not os.path.exists(repo_dir):
                os.makedirs(repo_dir, exist_ok=True)
                subprocess.run(
                    ["git", "init", "--bare", repo_dir],
                    check=True,
                    capture_output=True,
                    cwd=self.work_base,
                )
                logger.info(f"[Coder] Initialized bare repo: {repo_dir}")

            # Create worktree
            subprocess.run(
                ["git", "worktree", "add", worktree_path, "-b", f"feature-{session_id}"],
                check=True,
                capture_output=True,
                cwd=repo_dir,
            )
            logger.info(f"[Coder] Worktree created: {worktree_path}")

            # Initialize basic structure
            Path(worktree_path, "src").mkdir(parents=True, exist_ok=True)
            Path(worktree_path, "tests").mkdir(parents=True, exist_ok=True)

            return worktree_path

        except subprocess.CalledProcessError as e:
            logger.warning(f"[Coder] Worktree creation failed, using temp dir: {e}")
            # Fallback to temp directory
            temp_dir = tempfile.mkdtemp(prefix=f"a9-coder-{session_id}-")
            Path(temp_dir, "src").mkdir(parents=True, exist_ok=True)
            Path(temp_dir, "tests").mkdir(parents=True, exist_ok=True)
            return temp_dir

    async def _generate_code_changes(self, task_spec: dict, worktree_path: str, session_id: str) -> list:
        """Generate code files based on task spec"""
        files_changed = []
        plan = task_spec.get("plan", {})
        title = task_spec.get("title", "untitled")
        task_type = task_spec.get("type", "backend")

        files_to_create = plan.get("files_to_create", [])
        files_to_modify = plan.get("files_to_modify", [])

        if self.enable_llm:
            # Try to use LLM for code generation
            llm_result = await self._call_llm_for_code_generation(task_spec, worktree_path)
            if llm_result:
                return llm_result

        # Mock/fallback code generation
        for file_path in files_to_create[:3]:
            content = self._generate_mock_code(file_path, task_type, title)
            full_path = os.path.join(worktree_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "w") as f:
                f.write(content)

            files_changed.append({
                "path": file_path,
                "change_type": "created",
                "added": len(content.split("\n")),
                "removed": 0,
                "diff": f"+{content[:200]}...",
                "language": self._detect_language(file_path),
            })

        for file_path in files_to_modify[:2]:
            # Simulate modification
            full_path = os.path.join(worktree_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            modification = f"# Modified by A9 Coder (session={session_id})\n"
            with open(full_path, "a") as f:
                f.write(modification)

            files_changed.append({
                "path": file_path,
                "change_type": "modified",
                "added": 1,
                "removed": 0,
                "diff": f"+{modification}",
                "language": self._detect_language(file_path),
            })

        return files_changed

    async def _call_llm_for_code_generation(self, task_spec: dict, worktree_path: str) -> Optional[list]:
        """Call LLM for code generation via injected llm_caller."""
        if not self._llm_caller:
            return None

        try:
            title = task_spec.get("title", "untitled")
            task_type = task_spec.get("type", "backend")
            plan = task_spec.get("plan", {})
            files_needed = plan.get("files_to_create", plan.get("files_to_modify", ["src/main.py"]))

            prompt = f"""你是一个全栈开发工程师。需要为以下任务生成代码变更。

任务: {title}
类型: {task_type}
需要创建/修改的文件: {', '.join(files_needed[:10])}
工作目录: {worktree_path}

输出严格 JSON 格式:
{{
  "files": [
    {{
      "path": "src/xxx.py",
      "content": "完整的文件内容",
      "language": "python"
    }}
  ],
  "summary": "变更摘要（50字以内）",
  "dependencies": ["包名1"]
}}

只输出 JSON。content 应该是完整的文件内容，包含必要的 import 和类型注解。"""

            content = await self._llm_caller(
                [{"role": "user", "content": prompt}],
                task_type="code_generation",
                temperature=0.3,
                max_tokens=4000,
            )

            if content:
                content = content.strip()
                if content.startswith("```"): content = content.split("```")[1].split("```")[0].strip()
                if content.startswith("json"): content = content[4:].strip()
                result = json.loads(content)

                files_changed = []
                for f in result.get("files", []):
                    full_path = os.path.join(worktree_path, f["path"])
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, "w") as fh:
                        fh.write(f["content"])

                    content_lines = f["content"].split("\n")
                    files_changed.append({
                        "path": f["path"],
                        "change_type": "created",
                        "added": len(content_lines),
                        "removed": 0,
                        "diff": f"+{f['content'][:200]}...",
                        "language": f.get("language", self._detect_language(f["path"])),
                    })

                logger.info(f"[Coder] LLM generated {len(files_changed)} files")
                return files_changed

        except Exception as e:
            logger.warning(f"[Coder] LLM code generation failed: {e}")

        return None

    def _generate_mock_code(self, file_path: str, task_type: str, title: str) -> str:
        """Generate mock code content"""
        language = self._detect_language(file_path)

        if language == "python":
            return f'''"""
{title}

Auto-generated by A9 Coder.
Module: {file_path}
"""

# Standard imports
import json
import logging

logger = logging.getLogger(__name__)


class {self._to_class_name(file_path)}:
    """Auto-generated class for {task_type}"""

    def __init__(self):
        logger.info("Initialized {self._to_class_name(file_path)}")

    async def execute(self):
        """Main execution method"""
        return {{"status": "ok", "message": "Placeholder implementation"}}
'''
        elif language in ["javascript", "typescript"]:
            class_name = self._to_class_name(file_path)
            return f'''/**
 * {title}
 * Auto-generated by A9 Coder
 */

export class {class_name} {{
  constructor() {{
    console.log("Initialized {class_name}");
  }}

  async execute() {{
    return {{ status: "ok", message: "Placeholder implementation" }};
  }}
}}
'''
        else:
            return f"# Auto-generated file: {file_path}\n# Task: {title}\n"

    def _build_diff(self, files_changed: list, task_spec: dict, session_id: str) -> dict:
        """Build standardized diff structure"""
        changes = []
        for fc in files_changed:
            content_hash = hashlib.md5(fc.get("diff", "").encode()).hexdigest()[:16]
            changes.append({
                "path": fc["path"],
                "change_type": fc.get("change_type", "created"),
                "lines_added": fc.get("added", 0),
                "lines_removed": fc.get("removed", 0),
                "patch_preview": fc.get("diff", ""),
                "language": fc.get("language", "unknown"),
                "content_hash": content_hash,
            })

        summary = f"Generated {len(changes)} file changes for {task_spec.get('type', 'general')}"

        return {
            "files_changed": changes,
            "changes_summary": summary,
            "files_created": sum(1 for c in changes if c["change_type"] == "created"),
            "files_modified": sum(1 for c in changes if c["change_type"] == "modified"),
            "commit_sha": "a9" + hashlib.md5(str(changes).encode()).hexdigest()[:12],
            "session_id": f"coder-{session_id}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cost_usd": 0.05,  # Estimated
            "mock": not self.enable_llm,
        }

    def _perform_self_inspection(self, files_changed: list, task_spec: dict) -> dict:
        """Coder's self-inspection reasoning (NOT sent to Auditor)"""
        reasoning = f"Generated code for {task_spec.get('type', 'general')} task:\n"
        for fc in files_changed:
            reasoning += f"  - {fc['path']}: {fc.get('change_type', 'created')} "
            reasoning += f"(+{fc.get('added', 0)} -{fc.get('removed', 0)})\n"

        issues = []
        if len(files_changed) == 0:
            issues.append("No files were generated")
        if any("test" not in fc["path"] for fc in files_changed):
            issues.append("No test files generated - Auditor should validate")

        return {
            "reasoning": reasoning,
            "confidence": 0.7 if not issues else 0.5,
            "issues_identified": issues,
            "files_count": len(files_changed),
        }

    def _compute_metadata(self, files_changed: list, worktree_path: Optional[str]) -> dict:
        """Compute metadata about changes"""
        return {
            "files_created": sum(1 for fc in files_changed if fc.get("change_type") == "created"),
            "files_modified": sum(1 for fc in files_changed if fc.get("change_type") == "modified"),
            "total_lines_added": sum(fc.get("added", 0) for fc in files_changed),
            "total_lines_removed": sum(fc.get("removed", 0) for fc in files_changed),
            "worktree_path": worktree_path or "N/A",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension"""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".sql": "sql",
        }
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, "unknown")

    def _to_class_name(self, file_path: str) -> str:
        """Convert file path to class name"""
        name = Path(file_path).stem
        # Convert snake_case to CamelCase
        parts = name.split("_")
        return "".join(p.capitalize() for p in parts)
