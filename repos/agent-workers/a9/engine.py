"""
A9 Coding Engine — Unified wrapper for three coding agent backends.

Backend selection (auto-detected, priority order):
  1. Claude Code CLI  — Primary: autonomous coding in worktree (read→write→lint→test→fix)
  2. Codex CLI        — Alternative: same capability via OpenAI Codex
  3. Anthropic API    — Fallback: single-turn code generation via LLM API

Usage:
    runtime = A9Runtime()
    await runtime.setup(repo_url, branch)
    engine = A9CodingEngine(runtime, llm_caller=agent.call_llm)
    result = await engine.execute("Build a user CRUD API with FastAPI")
"""

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_CODE_ENABLED = os.environ.get("CLAUDE_CODE_ENABLED", "true").lower() in ("true", "1", "yes")
CODEX_ENABLED = os.environ.get("CODEX_ENABLED", "false").lower() in ("true", "1", "yes")


@dataclass
class EngineResult:
    """Result from any coding engine backend."""
    engine: str            # "claude-code" | "codex" | "anthropic-api"
    success: bool
    files_changed: list = field(default_factory=list)
    diff_raw: str = ""
    summary: str = ""
    session_id: str = ""
    cost_estimate: float = 0.0
    duration_ms: float = 0.0
    tool_calls_count: int = 0
    test_results: dict | None = None
    ambiguities: list | None = None      # Type 1: spec ambiguities (non-blocking)
    blocking_issues: list | None = None  # Type 3: unrecoverable issues (blocking)


class A9CodingEngine:
    """Execute coding tasks in a runtime's isolated worktree."""

    ENGINE_PRIORITY = ["claude-code", "codex", "anthropic-api"]

    def __init__(self, runtime, llm_caller=None):
        """
        Args:
            runtime: A9Runtime instance (worktree already set up)
            llm_caller: Callable for Anthropic API fallback mode
        """
        self.runtime = runtime
        self._llm_caller = llm_caller
        self._claude_cli_config = self._probe_claude_cli()
        self._available = self._detect_available()

    # ── Main entry point ──────────────────────────────────────────────

    async def execute(self, task: str, engine: str = "auto",
                      language: str = "python",
                      max_turns: int = 50,
                      feedback: str = "") -> EngineResult:
        """
        Execute a coding task in the worktree.

        Args:
            task: Natural language task description
            engine: "claude-code" | "codex" | "anthropic-api" | "auto"
            language: Target programming language
            max_turns: Max tool-use rounds (for CLI engines)
            feedback: Previous iteration's feedback (for retries)

        Returns:
            EngineResult
        """
        if engine == "auto":
            engine = self._available[0] if self._available else "anthropic-api"

        if feedback:
            task = f"{task}\n\n【上一轮反馈 - 请重点修复】\n{feedback}"

        logger.info(f"[Engine] Using {engine} for task: {task[:150]}...")

        if engine == "claude-code":
            return await self._run_claude_code(task, language, max_turns)
        elif engine == "codex":
            return await self._run_codex(task, language)
        else:
            return await self._run_anthropic_api(task)

    # ── Claude Code CLI ───────────────────────────────────────────────

    async def _run_claude_code(self, task: str, language: str,
                                max_turns: int) -> EngineResult:
        """Run Claude Code CLI in non-interactive mode inside the worktree."""
        if not self._claude_cli_config:
            return EngineResult(
                engine="claude-code", success=False,
                summary="Claude Code CLI not available",
                blocking_issues=[{"summary": "Claude Code CLI not found in PATH"}],
            )

        worktree = str(self.runtime.worktree_path)
        print_flag = self._claude_cli_config["print_flag"]
        output_flag = self._claude_cli_config["output_flag"]

        cmd = [
            self._claude_cli_config["path"],
            print_flag, task,
            output_flag, "stream-json",
            "--verbose",
            "--add-dir", worktree,
            "--allowedTools", "Read,Write,Edit,Bash(git,pytest,pylint,eslint,npm,npx,go,python)",
        ]

        logger.info(f"[Engine] claude CLI: {' '.join(cmd[:6])}...")
        start = asyncio.get_event_loop().time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=worktree,
                env={**os.environ, "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
            )
        except Exception as e:
            logger.warning(f"[Engine] Failed to start Claude Code CLI: {e}")
            return EngineResult(
                engine="claude-code", success=False,
                summary=f"Failed to start: {e}",
            )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=600,
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return EngineResult(
                engine="claude-code", success=False,
                summary="Claude Code timeout (10 min)",
                duration_ms=(asyncio.get_event_loop().time() - start) * 1000,
            )

        duration = (asyncio.get_event_loop().time() - start) * 1000

        # Parse NDJSON events
        events = []
        if stdout:
            for line in stdout.decode().strip().split("\n"):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        success = proc.returncode == 0
        cost = self._extract_cost(events)
        session_id = self._extract_session_id(events)
        tool_calls = sum(1 for e in events if e.get("type") == "tool_use")
        files_changed = self._extract_files_from_events(events, worktree)
        diff = await self._git_diff(worktree)
        summary = self._extract_summary(events)

        if stderr:
            stderr_text = stderr.decode()[:1000]
            if "error" in stderr_text.lower():
                logger.warning(f"[Engine] Claude Code stderr: {stderr_text}")

        logger.info(
            f"[Engine] Claude Code done: success={success}, "
            f"files={len(files_changed)}, tool_calls={tool_calls}, "
            f"cost=${cost:.4f}, duration={duration:.0f}ms"
        )

        # If CLI failed with no files, fall back to API instead of blocking
        if not success and not files_changed:
            stderr_text = stderr.decode()[:500] if stderr else ""
            logger.warning(f"[Engine] Claude Code CLI failed, falling back to API: {stderr_text}")
            return await self._run_anthropic_api(task)

        return EngineResult(
            engine="claude-code", success=success,
            files_changed=files_changed, diff_raw=diff,
            summary=summary, session_id=session_id,
            cost_estimate=cost, duration_ms=duration,
            tool_calls_count=tool_calls,
            blocking_issues=blocking,
        )

    # ── Codex CLI ─────────────────────────────────────────────────────

    async def _run_codex(self, task: str, language: str) -> EngineResult:
        """Run OpenAI Codex CLI as alternative engine."""
        worktree = str(self.runtime.worktree_path)

        cmd = [
            "codex", "exec", task,
            "--workdir", worktree,
            "--no-sandbox",
            "--model", os.environ.get("CODEX_MODEL", "gpt-4o"),
        ]

        logger.info(f"[Engine] codex CLI: codex exec ... --workdir {worktree}")
        start = asyncio.get_event_loop().time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=worktree,
                env={**os.environ, "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")},
            )
        except Exception as e:
            logger.warning(f"[Engine] Failed to start Codex CLI: {e}")
            return EngineResult(
                engine="codex", success=False,
                summary=f"Failed to start Codex CLI: {e}",
            )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=600,
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return EngineResult(
                engine="codex", success=False,
                summary="Codex timeout (10 min)",
                duration_ms=(asyncio.get_event_loop().time() - start) * 1000,
            )

        duration = (asyncio.get_event_loop().time() - start) * 1000
        success = proc.returncode == 0
        diff = await self._git_diff(worktree)
        output_text = stdout.decode() if stdout else ""
        files_changed = self._parse_codex_files(output_text)

        return EngineResult(
            engine="codex", success=success,
            files_changed=files_changed, diff_raw=diff,
            summary=output_text[:500], session_id="",
            cost_estimate=0.0, duration_ms=duration,
        )

    # ── Anthropic API Fallback ────────────────────────────────────────

    async def _run_anthropic_api(self, task: str) -> EngineResult:
        """
        Fallback: single-turn code generation via injected llm_caller.
        Writes generated files directly into the worktree.
        """
        if not self._llm_caller:
            return EngineResult(
                engine="anthropic-api", success=False,
                summary="No LLM caller available",
                blocking_issues=[{"summary": "No LLM caller injected into A9CodingEngine"}],
            )

        worktree = str(self.runtime.worktree_path)
        prompt = f"""You are a coding agent in a git worktree. Generate code changes.

Task: {task}
Working directory: {worktree}

Output JSON:
{{
  "files": [
    {{"path": "relative/path.py", "content": "full file content", "language": "python"}}
  ],
  "summary": "what you changed",
  "dependencies": ["if any"]
}}

Return ONLY valid JSON, no markdown wrapping."""

        start = asyncio.get_event_loop().time()

        try:
            content = await self._llm_caller(
                [{"role": "user", "content": prompt}],
                task_type="code_generation",
                temperature=0.3,
                max_tokens=8000,
            )

            duration = (asyncio.get_event_loop().time() - start) * 1000

            if not content:
                return EngineResult(
                    engine="anthropic-api", success=False,
                    summary="LLM returned no content",
                    duration_ms=duration,
                )

            # Parse JSON
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()
            if content.startswith("json"):
                content = content[4:].strip()

            data = json.loads(content)
            files = data.get("files", [])

            # Write files to worktree
            wt = self.runtime.worktree_path
            files_changed = []
            for f in files:
                file_path = f["path"]
                full_path = wt / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(f["content"], encoding="utf-8")
                files_changed.append({
                    "path": file_path,
                    "language": f.get("language", self._detect_language(file_path)),
                    "change_type": "created",
                    "added": len(f["content"].split("\n")),
                    "removed": 0,
                    "diff": f"+{f['content'][:200]}...",
                })

            diff = await self._git_diff_all(str(wt))
            summary = data.get("summary", "")

            return EngineResult(
                engine="anthropic-api", success=True,
                files_changed=files_changed, diff_raw=diff,
                summary=summary, session_id="",
                cost_estimate=0.05, duration_ms=duration,
            )

        except json.JSONDecodeError as e:
            duration = (asyncio.get_event_loop().time() - start) * 1000
            logger.warning(f"[Engine] Anthropic API JSON parse failed: {e}")
            return EngineResult(
                engine="anthropic-api", success=False,
                summary=f"Failed to parse LLM output: {e}",
                duration_ms=duration,
            )
        except Exception as e:
            duration = (asyncio.get_event_loop().time() - start) * 1000
            logger.error(f"[Engine] Anthropic API fallback failed: {e}")
            return EngineResult(
                engine="anthropic-api", success=False,
                summary=str(e),
                duration_ms=duration,
            )

    # ── Engine detection ──────────────────────────────────────────────

    def _detect_available(self) -> list[str]:
        """Detect which engines are available in the current environment."""
        engines = []
        if CLAUDE_CODE_ENABLED and self._claude_cli_config:
            engines.append("claude-code")
        if CODEX_ENABLED and shutil.which("codex"):
            engines.append("codex")
        if self._llm_caller:
            engines.append("anthropic-api")
        if not engines:
            engines.append("anthropic-api")  # always register as available
        return engines

    def _probe_claude_cli(self) -> dict | None:
        """
        Detect Claude Code CLI availability and flag names.

        Returns None if CLI is not available.
        Returns {"path", "print_flag", "output_flag", "version"} if found.
        """
        import subprocess as _sp

        claude_path = shutil.which("claude")
        if not claude_path:
            logger.info("[Engine] Claude Code CLI not found in PATH")
            return None

        try:
            result = _sp.run(
                [claude_path, "--help"],
                capture_output=True, text=True, timeout=10,
            )
            help_text = result.stdout + result.stderr

            # Detect flag names from help output
            has_print = "--print" in help_text
            has_prompt = "--prompt" in help_text
            has_output = "--output-format" in help_text
            has_output_short = "--output" in help_text

            if not (has_print or has_prompt):
                logger.info("[Engine] Claude CLI found but no --print/--prompt flag detected")
                return None

            config = {
                "path": claude_path,
                "print_flag": "--print" if has_print else "--prompt",
                "output_flag": "--output-format" if has_output else ("--output" if has_output_short else "--output"),
                "version": help_text.split("\n")[0] if help_text else "unknown",
            }
            logger.info(f"[Engine] Claude CLI detected: {config['version']}")
            return config

        except _sp.TimeoutExpired:
            logger.warning("[Engine] Claude CLI --help timed out")
            return None
        except Exception as e:
            logger.warning(f"[Engine] Claude CLI probe failed: {e}")
            return None

    # ── Helpers ───────────────────────────────────────────────────────

    async def _git_diff(self, worktree: str) -> str:
        """Get staged diff from worktree."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "diff", "--cached",
                stdout=asyncio.subprocess.PIPE,
                cwd=worktree,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode() if stdout else ""
        except Exception:
            return ""

    async def _git_diff_all(self, worktree: str) -> str:
        """Get full diff including new untracked files (git add -A + diff --cached)."""
        try:
            # Stage everything so diff --cached captures new files too
            add = await asyncio.create_subprocess_exec(
                "git", "add", "-A",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=worktree,
            )
            await add.communicate()

            proc = await asyncio.create_subprocess_exec(
                "git", "diff", "--cached",
                stdout=asyncio.subprocess.PIPE,
                cwd=worktree,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode() if stdout else ""
        except Exception:
            return ""

    def _extract_cost(self, events: list) -> float:
        for evt in reversed(events):
            if "total_cost_usd" in evt:
                return float(evt["total_cost_usd"])
        return 0.0

    def _extract_session_id(self, events: list) -> str:
        for evt in reversed(events):
            if evt.get("session_id"):
                return str(evt["session_id"])
        return f"cc-{uuid.uuid4().hex[:8]}"

    def _extract_summary(self, events: list) -> str:
        for evt in reversed(events):
            if evt.get("type") == "result":
                content = evt.get("content", "")
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                    return " ".join(texts)[:500]
                return str(content)[:500]
        return ""

    def _extract_files_from_events(self, events: list, worktree: str) -> list:
        """Extract file changes from Claude Code events."""
        files: dict[str, dict] = {}
        for evt in events:
            if evt.get("type") != "tool_use":
                continue
            name = evt.get("name", "")
            inp = evt.get("input", {})
            if name == "Write":
                path = inp.get("file_path", "")
                files[path] = {"path": path, "change_type": "created",
                               "language": self._detect_language(path)}
            elif name == "Edit":
                path = inp.get("file_path", "")
                files[path] = {"path": path, "change_type": "modified",
                               "language": self._detect_language(path)}
        return list(files.values())

    def _parse_codex_files(self, output: str) -> list:
        """Extract file paths from Codex CLI output."""
        files = set()
        for m in __import__("re").finditer(
            r"(?:created|modified|wrote)\S*\s+([a-zA-Z0-9_/.-]+\.[a-z]+)",
            output,
        ):
            files.add(m.group(1))
        return [{"path": f, "change_type": "modified",
                 "language": self._detect_language(f)} for f in files]

    @staticmethod
    def _detect_language(file_path: str) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".tsx": "typescript", ".go": "go", ".rs": "rust",
            ".java": "java", ".sql": "sql",
        }
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, "unknown")
