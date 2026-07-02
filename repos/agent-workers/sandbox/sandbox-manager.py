"""
Sandbox Manager — Docker sandbox lifecycle management for Dev Agent (A9).

Provides acquire, release, execute, and status operations on ephemeral
Docker containers used for isolated code execution and testing.

All methods are async stubs that return realistic mock outputs.
Replace with docker-py (`docker from_env`) when moving to production.
"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


class SandboxManager:
    """
    Manages Docker sandbox lifecycle.

    Real implementation (future):
        import docker
        self.client = docker.from_env()

    Mock implementation (current):
        Simulates container lifecycle with deterministic IDs and statuses.
    """

    def __init__(self):
        # In production: self.client = docker.from_env()
        self._containers: dict[str, dict] = {}  # container_id -> {image, status, created_at}
        logger.info("[SandboxManager] Initialized (stub mode)")

    # ------------------------------------------------------------------
    # Acquire
    # ------------------------------------------------------------------

    async def acquire(self, image: str = "ai-sandbox:latest") -> str:
        """
        Start a new sandbox container.

        Real implementation (future):
            container = self.client.containers.run(
                image, detach=True, remove=True,
                network_mode="none",  # isolate network
                mem_limit="512m",
                cpu_quota=50000,
            )
            return container.id

        Args:
            image: Docker image to use (default: ai-sandbox:latest).

        Returns:
            container_id: Unique identifier for the acquired sandbox.
        """
        container_id = f"sandbox-{uuid.uuid4().hex[:12]}"

        logger.info(
            "[SandboxManager] [STUB] Acquiring sandbox: image=%s, container_id=%s",
            image, container_id,
        )

        # Simulate container startup delay (minimal in stub for testability)
        await asyncio.sleep(0.01)

        self._containers[container_id] = {
            "image": image,
            "status": "running",
            "created_at": asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0,
        }

        print(f"[SandboxManager] [STUB] Would run: docker run -d --rm --network=none --memory=512m --cpus=0.5 {image}")
        print(f"[SandboxManager] [STUB] Container acquired: {container_id}")

        return container_id

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    async def release(self, container_id: str) -> None:
        """
        Stop and remove a sandbox container.

        Real implementation (future):
            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove()

        Args:
            container_id: The container ID returned by acquire().
        """
        logger.info("[SandboxManager] [STUB] Releasing sandbox: %s", container_id)

        if container_id not in self._containers:
            logger.warning("[SandboxManager] [STUB] Container not found: %s", container_id)
            print(f"[SandboxManager] [STUB] Container {container_id} not found — nothing to release")
            return

        # Simulate stop + remove
        await asyncio.sleep(0.01)
        self._containers[container_id]["status"] = "stopped"

        print(f"[SandboxManager] [STUB] Would run: docker stop {container_id} && docker rm {container_id}")
        print(f"[SandboxManager] [STUB] Container released: {container_id}")

        # Clean up internal tracking
        del self._containers[container_id]

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(self, container_id: str, command: str) -> dict:
        """
        Execute a command inside a sandbox container.

        Real implementation (future):
            container = self.client.containers.get(container_id)
            exit_code, output = container.exec_run(command)
            return {"stdout": output.decode(), "stderr": "", "exit_code": exit_code}

        Args:
            container_id: The container ID returned by acquire().
            command: Shell command string to execute.

        Returns:
            dict with keys: stdout, stderr, exit_code
        """
        logger.info(
            "[SandboxManager] [STUB] Executing in sandbox %s: %s",
            container_id, command,
        )

        if container_id not in self._containers:
            return {
                "stdout": "",
                "stderr": f"Error: container {container_id} not found",
                "exit_code": 1,
            }

        # Simulate execution
        await asyncio.sleep(0.01)

        print(f"[SandboxManager] [STUB] Would run: docker exec {container_id} {command}")

        # Realistic mock output
        mock_stdout = f"[STUB] Command '{command}' executed in {container_id}"
        mock_exit_code = 0

        return {
            "stdout": mock_stdout,
            "stderr": "",
            "exit_code": mock_exit_code,
        }

    # ------------------------------------------------------------------
    # Get Status
    # ------------------------------------------------------------------

    async def get_status(self, container_id: str) -> str:
        """
        Get the current status of a sandbox container.

        Real implementation (future):
            container = self.client.containers.get(container_id)
            return container.status  # "running", "exited", "paused", etc.

        Args:
            container_id: The container ID returned by acquire().

        Returns:
            One of "running", "stopped", or "error".
        """
        logger.info("[SandboxManager] [STUB] Getting status for: %s", container_id)

        if container_id not in self._containers:
            return "error"

        status = self._containers[container_id]["status"]
        print(f"[SandboxManager] [STUB] Would run: docker inspect --format='{{{{.State.Status}}}}' {container_id}")
        print(f"[SandboxManager] [STUB] Container {container_id} status: {status}")

        return status
