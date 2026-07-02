"""
Tool Executor — Run external analysis tools with timeout and error handling.

Provides async execution of static analysis tools (eslint, pylint, mypy, etc.)
with configurable timeouts and graceful degradation on tool unavailability.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Execute external tools with timeout control and error handling."""

    def __init__(self, timeout: int = 30):
        """
        Initialize tool executor.

        Args:
            timeout: Default timeout in seconds for tool execution
        """
        self.timeout = timeout

    async def run_with_timeout(
        self,
        cmd: list,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        """
        Run a command with timeout control.

        Args:
            cmd: Command to execute as list (e.g., ['eslint', '--format=json', 'file.js'])
            cwd: Working directory for command execution
            timeout: Override default timeout (seconds)

        Returns:
            {
                "success": bool,
                "stdout": str,
                "stderr": str,
                "returncode": int,
                "timed_out": bool,
                "error": Optional[str]
            }
        """
        effective_timeout = timeout or self.timeout

        try:
            logger.debug(f"[ToolExecutor] Running: {' '.join(cmd)}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=effective_timeout,
                )

                return {
                    "success": process.returncode == 0,
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                    "returncode": process.returncode,
                    "timed_out": False,
                    "error": None,
                }

            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()

                logger.warning(
                    f"[ToolExecutor] Tool timed out after {effective_timeout}s: {cmd[0]}"
                )

                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "",
                    "returncode": -1,
                    "timed_out": True,
                    "error": f"Tool timed out after {effective_timeout}s",
                }

        except FileNotFoundError:
            logger.warning(f"[ToolExecutor] Tool not found: {cmd[0]}")
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "returncode": 127,
                "timed_out": False,
                "error": f"Tool not found: {cmd[0]}",
            }

        except Exception as e:
            logger.error(f"[ToolExecutor] Execution error: {e}", exc_info=True)
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "timed_out": False,
                "error": str(e),
            }
