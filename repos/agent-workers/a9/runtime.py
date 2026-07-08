"""
A9Runtime — Per-task isolated dev environment.

Each dev task creates an independent A9Runtime instance with its own git worktree.
Lifecycle: setup → work (lint/build/test/service) → cleanup.

Provides:
- git worktree isolation
- Multi-language lint (pylint, eslint)
- Multi-language build (compileall, tsc, go build)
- Test runner (pytest, jest, go test) with output parsing
- Service start/stop for smoke testing
- Stale worktree cleanup
"""

import asyncio
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data types ────────────────────────────────────────────────────────

@dataclass
class LintResult:
    """Result of a lint check."""
    language: str
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    status: str = "ok"  # ok | warning | error
    tool: str = "none"


@dataclass
class BuildResult:
    """Result of a build/compile check."""
    language: str
    success: bool = True
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0


@dataclass
class TestReport:
    """Result of running tests."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: float = 0
    coverage_pct: float = 0.0
    failures_detail: list[dict] = field(default_factory=list)
    raw_output: str = ""


@dataclass
class RuntimeConfig:
    """Configuration for A9Runtime."""
    work_base: str = "/tmp/a9-runtimes"
    timeout_lint: int = 30
    timeout_build: int = 120
    timeout_test: int = 300
    max_worktree_age: int = 3600


# Language → (lint_cmd, build_cmd) mapping
_LANG_COMMANDS: dict[str, tuple[list[str], list[str]]] = {
    "python": (
        ["pylint", "--output-format=json"],
        ["python", "-m", "compileall", "-q"],
    ),
    "javascript": (
        ["eslint", "--format=json"],
        ["npm", "run", "build"],
    ),
    "typescript": (
        ["eslint", "--format=json"],
        ["npx", "tsc", "--noEmit"],
    ),
    "go": (
        ["golangci-lint", "run", "--out-format=json"],
        ["go", "build", "./..."],
    ),
}


class A9Runtime:
    """
    Per-task isolated dev environment.

    Usage:
        runtime = A9Runtime()
        await runtime.setup(repo_url, branch)
        try:
            lint_result = await runtime.lint(["src/api.py"], "python")
            build_result = await runtime.build("python")
            test_result = await runtime.test()
            service = await runtime.start_service(["python", "-m", "uvicorn", "main:app"])
            await runtime.stop_all_services()
        finally:
            await runtime.cleanup()

    Or use as context manager:
        async with A9Runtime() as runtime:
            await runtime.setup(repo_url, branch)
            ...
    """

    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig()
        self.session_id = f"a9rt-{uuid.uuid4().hex[:8]}"
        self.worktree_path: Optional[Path] = None
        self._repo_url: str = ""
        self._branch: str = "main"
        self._running_services: list = []

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def setup(self, repo_url: str, branch: str = "main") -> Path:
        """
        Prepare isolated environment.

        Strategy:
          1. Has repo_url → git clone --bare → worktree add
          2. No repo_url (new project) → temp directory + git init
        """
        self._repo_url = repo_url
        self._branch = branch or "main"

        if repo_url:
            self.worktree_path = await self._create_worktree(repo_url, branch)
        else:
            self.worktree_path = await self._create_temp_workspace()

        logger.info(f"[{self.session_id}] Workspace ready: {self.worktree_path}")
        return self.worktree_path

    async def cleanup(self):
        """Clean up isolated environment, release disk space."""
        if not self.worktree_path:
            return

        # Stop any running services first
        await self.stop_all_services()

        try:
            wt = str(self.worktree_path)
            if (self.worktree_path / ".git").exists():
                await self._run_git(
                    ["worktree", "remove", wt, "--force"],
                    cwd=wt, timeout=15,
                )
            elif self.worktree_path.name.startswith("a9rt-"):
                shutil.rmtree(self.worktree_path, ignore_errors=True)
            logger.info(f"[{self.session_id}] Cleanup complete: {wt}")
        except Exception as e:
            logger.warning(f"[{self.session_id}] Cleanup warning: {e}")
            # Force remove if git worktree remove failed
            if self.worktree_path.exists():
                shutil.rmtree(self.worktree_path, ignore_errors=True)

    # ── Git Operations ────────────────────────────────────────────────

    async def _create_worktree(self, repo_url: str, branch: str) -> Path:
        """git clone --bare → worktree add on target branch."""
        base = Path(self.config.work_base)
        base.mkdir(parents=True, exist_ok=True)

        # Derive a stable bare repo name from URL
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        bare_dir = base / f"{repo_name}.bare"

        if not bare_dir.exists():
            await self._run_git(
                ["clone", "--bare", repo_url, str(bare_dir)],
                cwd=base, timeout=120,
            )

        # Fetch latest if bare repo already exists
        await self._run_git(["fetch", "--all"], cwd=bare_dir, timeout=30)

        # Create worktree
        wt_path = base / f"wt-{self.session_id}"
        await self._run_git(
            ["worktree", "add", str(wt_path), f"origin/{branch}"],
            cwd=bare_dir,
        )

        return wt_path

    async def _create_temp_workspace(self) -> Path:
        """Create a temp workspace for tasks without a repo (new project)."""
        tmp = Path(tempfile.mkdtemp(prefix=f"a9rt-{self.session_id}-"))
        (tmp / "src").mkdir(exist_ok=True)
        (tmp / "tests").mkdir(exist_ok=True)
        await self._run_git(["init"], cwd=tmp)
        return tmp

    async def checkout(self, branch: str):
        """Switch branch in the worktree."""
        if self.worktree_path:
            await self._run_git(["checkout", branch], cwd=self.worktree_path)

    async def pull(self):
        """Pull latest changes."""
        if self.worktree_path:
            await self._run_git(
                ["pull", "--rebase"], cwd=self.worktree_path, timeout=60,
            )

    # ── Lint ──────────────────────────────────────────────────────────

    async def lint(self, files: list[str], language: str) -> LintResult:
        """Run linter on specified files."""
        if not self.worktree_path:
            return LintResult(
                language=language, status="error",
                errors=[{"line": 0, "message": "No workspace", "rule": "runtime"}],
            )

        cmd_info = _LANG_COMMANDS.get(language)
        if not cmd_info:
            return LintResult(language=language, status="ok", tool="none")

        lint_cmd, _ = cmd_info
        try:
            proc = await asyncio.create_subprocess_exec(
                *lint_cmd,
                *[str(self.worktree_path / f) for f in files],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.worktree_path),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout_lint,
            )
            return self._parse_lint_output(language, stdout, proc.returncode)

        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return LintResult(
                language=language, status="warning",
                warnings=[{"line": 0, "message": "Lint timeout", "rule": "timeout"}],
            )
        except FileNotFoundError:
            return LintResult(language=language, status="ok", tool="none")
        except Exception as e:
            logger.warning(f"[{self.session_id}] Lint error: {e}")
            return LintResult(language=language, status="ok", tool="none")

    # ── Build ─────────────────────────────────────────────────────────

    async def build(self, language: str, target: str = "") -> BuildResult:
        """Run build/compile/type check."""
        if not self.worktree_path:
            return BuildResult(language=language, success=False, stderr="No workspace")

        cmd_info = _LANG_COMMANDS.get(language)
        if not cmd_info:
            # No build step for this language
            return BuildResult(language=language, success=True)

        _, build_cmd = cmd_info
        start = asyncio.get_event_loop().time()

        try:
            args = [*build_cmd]
            if target:
                args.append(target)

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.worktree_path),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout_build,
            )
            duration = (asyncio.get_event_loop().time() - start) * 1000

            return BuildResult(
                language=language,
                success=(proc.returncode == 0),
                exit_code=proc.returncode or 0,
                stdout=stdout.decode()[:2000] if stdout else "",
                stderr=stderr.decode()[:2000] if stderr else "",
                duration_ms=duration,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return BuildResult(
                language=language, success=False,
                stderr=f"Build timeout ({self.config.timeout_build}s)",
            )
        except FileNotFoundError:
            return BuildResult(
                language=language, success=True,
                stdout="Build tool not installed — skipping",
            )
        except Exception as e:
            logger.warning(f"[{self.session_id}] Build error: {e}")
            return BuildResult(language=language, success=False, stderr=str(e))

    # ── Test Runner ───────────────────────────────────────────────────

    async def test(self, command: list[str] | None = None) -> TestReport:
        """
        Run tests. Auto-detects framework if no command given.

        Supports: pytest, jest, go test.
        """
        if not self.worktree_path:
            return TestReport(
                errors=1,
                failures_detail=[{"message": "No workspace"}],
            )

        if command is None:
            command = self._detect_test_command()

        start = asyncio.get_event_loop().time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.worktree_path),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout_test,
            )
            duration = (asyncio.get_event_loop().time() - start) * 1000

            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            return self._parse_test_output(
                stdout_text, stderr_text, duration, proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            duration = (asyncio.get_event_loop().time() - start) * 1000
            return TestReport(
                errors=1, duration_ms=duration,
                failures_detail=[{"message": f"Test timeout ({self.config.timeout_test}s)"}],
            )
        except Exception as e:
            logger.error(f"[{self.session_id}] Test error: {e}")
            return TestReport(
                errors=1,
                failures_detail=[{"message": str(e)}],
            )

    # ── Service Start/Stop ────────────────────────────────────────────

    async def start_service(self, command: list[str],
                            health_check_url: str = "",
                            timeout: int = 30,
                            bind_host: str = "127.0.0.1") -> dict:
        """
        Start a project process for smoke testing.
        Binds to localhost by default — worktree code must not be exposed on the network.

        Returns {"pid": int, "port": int, "url": str}.
        """
        if not self.worktree_path:
            raise RuntimeError("No workspace — call setup() first")

        # Find a free port
        port = self._find_free_port(bind_host)

        env = {**os.environ, "PORT": str(port), "BIND_HOST": bind_host}
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.worktree_path),
            env=env,
        )
        self._running_services.append(proc)

        # Wait for health check to pass
        health_ok = True
        if health_check_url:
            url = f"http://{bind_host}:{port}{health_check_url}"
            health_ok = False
            for _ in range(timeout):
                await asyncio.sleep(1)
                try:
                    check = await asyncio.create_subprocess_exec(
                        "curl", "-sf", "-o", os.devnull, url,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    if await check.wait() == 0:
                        health_ok = True
                        break
                except Exception:
                    pass

        return {"pid": proc.pid, "port": port, "url": f"http://{bind_host}:{port}",
                "health_ok": health_ok}

    async def stop_all_services(self):
        """Terminate all running services."""
        for proc in self._running_services:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._running_services.clear()

    # ── Docker Compose (optional) ─────────────────────────────────────

    async def deploy_dev_compose(self, compose_file: str,
                                  project_name: str = "") -> dict:
        """docker-compose up -d --wait."""
        name = project_name or f"a9-dev-{self.session_id}"
        proc = await asyncio.create_subprocess_exec(
            "docker-compose", "-f", compose_file,
            "-p", name, "up", "-d", "--wait",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.worktree_path),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=180,
        )
        return {"project": name, "success": proc.returncode == 0}

    async def cleanup_dev_compose(self, project_name: str):
        """docker-compose down -v --remove-orphans."""
        proc = await asyncio.create_subprocess_exec(
            "docker-compose", "-p", project_name,
            "down", "-v", "--remove-orphans",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.worktree_path),
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)

    # ── Stale cleanup ─────────────────────────────────────────────────

    @staticmethod
    async def cleanup_stale_worktrees(work_base: str = "/tmp/a9-runtimes",
                                       max_age_minutes: int = 120):
        """Remove stale worktree directories older than max_age_minutes."""
        import time
        base = Path(work_base)
        if not base.exists():
            return

        now = time.time()
        cutoff = now - (max_age_minutes * 60)

        for item in base.iterdir():
            if not item.name.startswith("wt-a9rt-"):
                continue
            try:
                mtime = item.stat().st_mtime
                if mtime < cutoff:
                    logger.info(f"[A9Runtime] Cleaning stale worktree: {item}")
                    if (item / ".git").exists():
                        subprocess.run(
                            ["git", "worktree", "remove", str(item), "--force"],
                            capture_output=True, timeout=10,
                        )
                    else:
                        shutil.rmtree(item, ignore_errors=True)
            except Exception as e:
                logger.warning(f"[A9Runtime] Stale cleanup error for {item}: {e}")

    # ── Context Manager ───────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.cleanup()

    # ── Internal Helpers ──────────────────────────────────────────────

    async def _run_git(self, args: list[str], cwd: str | Path,
                        timeout: int = 30) -> str:
        """Run a git command and return stdout. Raises on failure."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
        if proc.returncode != 0:
            stderr_text = stderr.decode()[:200] if stderr else ""
            raise RuntimeError(
                f"git {' '.join(args)} failed (exit={proc.returncode}): {stderr_text}"
            )
        return stdout.decode() if stdout else ""

    @staticmethod
    def _find_free_port(bind_host: str = "127.0.0.1") -> int:
        """Find a free TCP port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((bind_host, 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _parse_lint_output(self, language: str, stdout: bytes,
                            exit_code: int) -> LintResult:
        """Parse pylint/eslint JSON stdout into LintResult."""
        import json as _json

        errors, warnings = [], []
        text = stdout.decode() if stdout else ""

        if text.strip():
            try:
                data = _json.loads(text)
                if language == "python":
                    items = data if isinstance(data, list) else [data]
                    for issue in items:
                        sev = "error" if issue.get("type") in ("error", "fatal") else "warning"
                        item = {
                            "line": issue.get("line", 0),
                            "message": issue.get("message", ""),
                            "rule": issue.get("message-id", ""),
                            "severity": sev,
                        }
                        (errors if sev == "error" else warnings).append(item)
                else:
                    items = data if isinstance(data, list) else [data]
                    for file_report in items:
                        for msg in file_report.get("messages", []):
                            sev = "error" if msg.get("severity") == 2 else "warning"
                            item = {
                                "line": msg.get("line", 0),
                                "message": msg.get("message", ""),
                                "rule": msg.get("ruleId", ""),
                                "severity": sev,
                            }
                            (errors if sev == "error" else warnings).append(item)
            except (_json.JSONDecodeError, Exception):
                pass

        status = "error" if errors else ("warning" if warnings else "ok")
        tool = {
            "python": "pylint",
            "javascript": "eslint",
            "typescript": "eslint",
        }.get(language, "none")

        return LintResult(
            language=language, errors=errors, warnings=warnings,
            status=status, tool=tool,
        )

    def _detect_test_command(self) -> list[str]:
        """Auto-detect test framework from project files."""
        if not self.worktree_path:
            return ["pytest", "-v", "--tb=short"]

        root = self.worktree_path
        if (root / "jest.config.js").exists() or (root / "jest.config.ts").exists():
            return ["npx", "jest", "--verbose"]
        if (root / "vitest.config.ts").exists() or (root / "vitest.config.js").exists():
            return ["npx", "vitest", "--run"]
        if (root / "go.mod").exists():
            return ["go", "test", "./...", "-v"]
        # Default: pytest
        return ["pytest", "-v", "--tb=short"]

    @staticmethod
    def _parse_test_output(stdout: str, stderr: str, duration_ms: float,
                            exit_code: int) -> TestReport:
        """Parse test runner output into structured TestReport."""
        output = stdout + "\n" + stderr

        # Try pytest pattern: "N passed, M failed, E errors"
        m = re.search(
            r"(\d+)\s+passed[,;\s]*\s*(\d+)\s+failed",
            output,
        )
        if m:
            passed = int(m.group(1))
            failed = int(m.group(2))
            skipped_match = re.search(r"(\d+)\s+skipped", output)
            skipped = int(skipped_match.group(1)) if skipped_match else 0
            err_match = re.search(r"(\d+)\s+errors?", output)
            errors = int(err_match.group(1)) if err_match else 0
            return TestReport(
                total=passed + failed + errors + skipped,
                passed=passed, failed=failed, errors=errors,
                skipped=skipped, duration_ms=duration_ms,
                raw_output=output[:3000],
            )

        # Try jest pattern: "Tests: N passed, M failed, T total"
        m = re.search(
            r"Tests:\s+(\d+)\s+passed,\s*(\d+)\s+failed,\s*(\d+)\s+total",
            output,
        )
        if m:
            passed = int(m.group(1))
            failed = int(m.group(2))
            total = int(m.group(3))
            return TestReport(
                total=total, passed=passed, failed=failed,
                duration_ms=duration_ms, raw_output=output[:3000],
            )

        # Try go test: "--- PASS" / "--- FAIL" lines
        pass_count = len(re.findall(r"--- PASS:", output))
        fail_count = len(re.findall(r"--- FAIL:", output))
        if pass_count > 0 or fail_count > 0:
            return TestReport(
                total=pass_count + fail_count,
                passed=pass_count, failed=fail_count,
                duration_ms=duration_ms, raw_output=output[:3000],
            )

        # Fallback: rely on exit code
        if exit_code == 0:
            return TestReport(
                total=0, passed=0, failed=0,
                duration_ms=duration_ms, raw_output=output[:1000],
            )
        else:
            return TestReport(
                total=1, passed=0, failed=1, errors=0,
                duration_ms=duration_ms,
                failures_detail=[{"message": output[:500]}],
                raw_output=output[:1000],
            )

    def detect_start_command(self, language: str) -> list[str]:
        """Detect the command to start a service for smoke testing."""
        if not self.worktree_path:
            return ["python", "-m", "uvicorn", "main:app"]

        root = self.worktree_path

        if language == "python":
            if (root / "manage.py").exists():
                return ["python", "manage.py", "runserver", "127.0.0.1:0"]
            if (root / "pyproject.toml").exists():
                return ["python", "-m", "uvicorn", "main:app"]
            return ["python", "-m", "uvicorn", "main:app"]

        elif language in ("javascript", "typescript"):
            if (root / "package.json").exists():
                return ["npm", "start"]
            return ["npx", "serve", "-l"]

        elif language == "go":
            return ["go", "run", "./cmd/server"]

        return ["python", "-m", "http.server"]  # generic fallback
