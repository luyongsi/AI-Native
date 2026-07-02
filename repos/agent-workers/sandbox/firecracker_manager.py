"""
Firecracker MicroVM Manager — Production sandbox isolation via Firecracker microVMs.

Provides create, destroy, execute, and status operations on ephemeral Firecracker
microVMs used for isolated agent code execution and testing.

All methods are async stubs that return realistic mock outputs with realistic
timings (boot <200ms as required by the Firecracker performance target).

Real implementation patterns noted in comments for production migration.
    - Boot: firectl or Firecracker REST API + jailer for process isolation
    - Networking: CNI (tc-redirect-tap) + NAT bridge to egress firewall
    - Storage: overlayfs root drive from base image + writable scratch layer
    - Cleanup: SIGTERM → graceful shutdown → force kill after timeout
"""

import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)


class FirecrackerManager:
    """
    Manages Firecracker microVM lifecycle for sandboxed agent execution.

    VM specs (configurable per vm_config):
        - 4 vCPU
        - 8192 MiB memory
        - Kernel boot args: console=ttyS0 reboot=k panic=1

    Real implementation (future):
        import os, json, socket, struct, tempfile
        from pathlib import Path

        # Build kernel + rootfs paths
        KERNEL_IMAGE = "/opt/firecracker/kernel/vmlinux-6.1"
        ROOTFS_BASE = "/opt/firecracker/images"
        FIRECRACKER_BIN = "/usr/bin/firecracker"

        async def create_vm(self, image: str, vm_config: dict = None) -> dict:
            # 1. Allocate IP from CNI pool
            ip_addr = self._cni_alloc_ip()
            tap_device = f"fc-{vm_id[:8]}-tap"

            # 2. Create overlay scratch layer
            scratch = tempfile.mkdtemp(prefix=f"fc-{vm_id[:8]}-")
            merge_dir = tempfile.mkdtemp(prefix=f"fc-merge-{vm_id[:8]}-")

            # 3. Launch firecracker via jailer
            #    jailer --id {vm_id} --exec-file /usr/bin/firecracker --uid 1000 --gid 1000
            #    Then configure via REST API socket: PUT /boot-source, PUT /drives, PUT /network-interfaces
            #    Then PUT /actions with action_type="InstanceStart"
            ...

    Stub implementation (current):
        Simulates microVM lifecycle with deterministic IDs, realistic timings,
        and VM tracking in an in-memory dict.
    """

    # Default kernel boot arguments
    DEFAULT_KERNEL_ARGS = "console=ttyS0 reboot=k panic=1"

    # Default VM configuration
    DEFAULT_VM_CONFIG: dict = {
        "vcpu_count": 4,
        "memory_mb": 8192,
        "kernel_args": DEFAULT_KERNEL_ARGS,
    }

    def __init__(self):
        # In production: self.cni_pool = CNIIPPool(subnet="10.42.0.0/16")
        # In production: self.jailer_base = Path("/srv/jailer/firecracker")
        self._vms: dict[str, dict] = {}  # vm_id -> {image, status, ip, config, created_at, ...}
        self._boot_count = 0
        logger.info("[FirecrackerManager] Initialized (stub mode)")

    # ------------------------------------------------------------------
    # Create VM
    # ------------------------------------------------------------------

    async def create_vm(self, image: str, vm_config: dict = None) -> dict:
        """
        Create and boot a new Firecracker microVM.

        Simulates:
            1. Allocating IP from CNI pool
            2. Creating overlay scratch rootfs
            3. Launching firecracker binary via jailer
            4. Waiting for VM to become reachable (boot <200ms target)

        Real implementation (future):
            See class docstring for detailed production pattern.

        Args:
            image: Sandbox image identifier (e.g., "ai-sandbox:firecracker").
            vm_config: Optional dict overrides:
                - vcpu_count (int, default 4)
                - memory_mb (int, default 8192)
                - kernel_args (str, default "console=ttyS0 reboot=k panic=1")

        Returns:
            dict with keys:
                vm_id        - Unique microVM identifier
                ip_address   - Allocated IP address for the VM
                status       - "running" or "error"
                boot_time_ms - Time taken to boot the VM
                vcpu_count   - Number of vCPUs allocated
                memory_mb    - Memory allocated in MiB
        """
        vm_id = f"fc-{uuid.uuid4().hex[:12]}"

        # Merge default config with overrides
        config = dict(self.DEFAULT_VM_CONFIG)
        if vm_config:
            config.update(vm_config)

        # Allocate an IP from the mock CNI pool
        ip_octet = len(self._vms) % 254 + 2
        ip_address = f"10.42.0.{ip_octet}"

        boot_start = time.perf_counter()

        logger.info(
            "[FirecrackerManager] [STUB] Creating Firecracker VM: image=%s, vm_id=%s, "
            "vcpu=%d, memory=%dMiB",
            image, vm_id, config["vcpu_count"], config["memory_mb"],
        )

        # Simulate Firecracker boot time — target <200ms
        # Real Firecracker cold-boot is typically 100-150ms; we simulate ~125ms
        await asyncio.sleep(0.125)

        boot_end = time.perf_counter()
        boot_time_ms = round((boot_end - boot_start) * 1000, 1)
        self._boot_count += 1

        vm_record = {
            "image": image,
            "status": "running",
            "ip_address": ip_address,
            "config": config,
            "created_at": time.time(),
            "boot_time_ms": boot_time_ms,
            "ssh_port": 2200 + self._boot_count,  # mock SSH forwarding port
        }
        self._vms[vm_id] = vm_record

        # Log the equivalent production command
        print(
            f"[FirecrackerManager] [STUB] Would run: "
            f"jailer --id {vm_id} --exec-file /usr/bin/firecracker "
            f"--uid 1000 --gid 1000 --chroot-base-dir /srv/jailer "
            f"&& curl -X PUT --unix-socket /srv/jailer/{vm_id}/api.socket "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"boot-source\":{{\"kernel_image_path\":\"vmlinux-6.1\","
            f"\"boot_args\":\"{config['kernel_args']}\"}}}}'"
        )
        print(
            f"[FirecrackerManager] [STUB] VM booted: {vm_id} "
            f"image={image} ip={ip_address} boot={boot_time_ms}ms"
        )

        return {
            "vm_id": vm_id,
            "ip_address": ip_address,
            "status": "running",
            "boot_time_ms": boot_time_ms,
            "vcpu_count": config["vcpu_count"],
            "memory_mb": config["memory_mb"],
        }

    # ------------------------------------------------------------------
    # Destroy VM
    # ------------------------------------------------------------------

    async def destroy_vm(self, vm_id: str) -> dict:
        """
        Gracefully shut down and destroy a Firecracker microVM.

        Simulates:
            1. Sending SIGTERM to firecracker process
            2. Waiting for graceful shutdown
            3. Force kill after timeout
            4. Cleaning up: tap device, IP lease, overlay scratch dir
            5. Removing jailer directory

        Real implementation (future):
            # Send CTRL+ALT+DEL via action API
            resp = requests.put(
                f"http://unix{socket_path}/actions",
                json={"action_type": "SendCtrlAltDel"},
            )
            # Wait for process to exit, force kill if needed
            # Cleanup: os.remove(tap_device), self._cni_release_ip(ip), shutil.rmtree(scratch)

        Args:
            vm_id: The microVM ID returned by create_vm().

        Returns:
            dict with keys:
                destroyed      - True if the VM was successfully destroyed
                vm_id          - The VM ID that was targeted
                cleanup_time_ms - Time taken to clean up
        """
        cleanup_start = time.perf_counter()

        logger.info("[FirecrackerManager] [STUB] Destroying Firecracker VM: %s", vm_id)

        if vm_id not in self._vms:
            logger.warning("[FirecrackerManager] [STUB] VM not found: %s", vm_id)
            print(f"[FirecrackerManager] [STUB] VM {vm_id} not found — nothing to destroy")
            return {
                "destroyed": False,
                "vm_id": vm_id,
                "cleanup_time_ms": 0,
            }

        vm_record = self._vms[vm_id]

        # Simulate graceful shutdown + cleanup
        # Real Firecracker cleanup takes ~50-100ms
        await asyncio.sleep(0.08)

        cleanup_end = time.perf_counter()
        cleanup_time_ms = round((cleanup_end - cleanup_start) * 1000, 1)

        print(
            f"[FirecrackerManager] [STUB] Would run: "
            f"kill -TERM $(cat /srv/jailer/{vm_id}/pid) "
            f"&& ip link del fc-{vm_id[:8]}-tap "
            f"&& rm -rf /srv/jailer/{vm_id} "
            f"&& rm -rf /tmp/fc-scratch-{vm_id[:8]}-*"
        )
        print(
            f"[FirecrackerManager] [STUB] VM destroyed: {vm_id} "
            f"(was ip={vm_record['ip_address']}, cleanup={cleanup_time_ms}ms)"
        )

        del self._vms[vm_id]

        return {
            "destroyed": True,
            "vm_id": vm_id,
            "cleanup_time_ms": cleanup_time_ms,
        }

    # ------------------------------------------------------------------
    # Execute Command
    # ------------------------------------------------------------------

    async def execute_command(self, vm_id: str, command: str, timeout_seconds: int = 300) -> dict:
        """
        Execute a command inside a running Firecracker microVM.

        Simulates:
            1. Checking VM is in "running" state
            2. Opening SSH connection to VM IP
            3. Executing command with deadline
            4. Capturing stdout, stderr, exit code

        Real implementation (future):
            import asyncssh

            async with asyncssh.connect(
                self._vms[vm_id]["ip_address"],
                username="agent",
                client_keys=["/opt/firecracker/keys/agent_ed25519"],
                known_hosts=None,
            ) as conn:
                result = await conn.run(command, timeout=timeout_seconds)
                return {
                    "stdout": result.stdout or "",
                    "stderr": result.stderr or "",
                    "exit_code": result.exit_status or 0,
                    "duration_ms": ...,
                }

        Args:
            vm_id: The microVM ID returned by create_vm().
            command: Shell command string to execute.
            timeout_seconds: Maximum execution time (default 300).

        Returns:
            dict with keys:
                stdout      - Standard output from the command
                stderr      - Standard error from the command
                exit_code   - Exit code (0 for success)
                duration_ms - Wall-clock duration of command execution
        """
        exec_start = time.perf_counter()

        logger.info(
            "[FirecrackerManager] [STUB] Executing in Firecracker VM %s: %s (timeout=%ds)",
            vm_id, command, timeout_seconds,
        )

        # Check VM exists and is running
        if vm_id not in self._vms:
            return {
                "stdout": "",
                "stderr": f"Error: Firecracker VM '{vm_id}' not found",
                "exit_code": 1,
                "duration_ms": 0,
            }

        if self._vms[vm_id]["status"] != "running":
            return {
                "stdout": "",
                "stderr": f"Error: Firecracker VM '{vm_id}' is in state '{self._vms[vm_id]['status']}'",
                "exit_code": 1,
                "duration_ms": 0,
            }

        # Simulate command execution latency (varies by command "complexity")
        exec_delay = 0.02  # base latency
        if "pip install" in command or "npm install" in command:
            exec_delay = 0.15
        elif "claude" in command:
            exec_delay = 0.3

        await asyncio.sleep(exec_delay)

        exec_end = time.perf_counter()
        duration_ms = round((exec_end - exec_start) * 1000, 1)

        vm_ip = self._vms[vm_id]["ip_address"]

        print(
            f"[FirecrackerManager] [STUB] Would run: "
            f"ssh -i /opt/firecracker/keys/agent_ed25519 agent@{vm_ip} '{command}'"
        )

        # Realistic mock output
        if "claude-code" in command:
            mock_stdout = (
                f"[STUB] Claude Code executed in Firecracker VM ({vm_id})\n"
                f"  Model: claude-sonnet-4-6\n"
                f"  Tokens: 1,247 in / 856 out\n"
                f"  Result: Code modification applied successfully\n"
            )
        elif "test" in command.lower():
            mock_stdout = (
                f"[STUB] Test suite executed in Firecracker VM ({vm_id})\n"
                f"  Ran 42 tests in 3.847s\n"
                f"  PASSED: 41\n"
                f"  FAILED: 1\n"
                f"  SKIPPED: 0\n"
            )
        else:
            mock_stdout = f"[STUB] Command '{command}' executed in Firecracker VM {vm_id}"

        return {
            "stdout": mock_stdout,
            "stderr": "",
            "exit_code": 0,
            "duration_ms": duration_ms,
        }

    # ------------------------------------------------------------------
    # Get VM Status
    # ------------------------------------------------------------------

    async def get_vm_status(self, vm_id: str) -> dict:
        """
        Get the current status and metadata of a Firecracker microVM.

        Real implementation (future):
            resp = requests.get(f"http://unix{socket_path}/")
            machine_config = resp.json()
            # Also check jailer process health via /proc/<pid>/status

        Args:
            vm_id: The microVM ID returned by create_vm().

        Returns:
            dict with keys:
                vm_id       - The VM identifier
                status      - "running", "stopped", or "error"
                image       - The sandbox image name
                ip_address  - Allocated IP address
                vcpu_count  - Number of vCPUs
                memory_mb   - Memory in MiB
                uptime_seconds - Time since VM was created
                kernel_args - Kernel boot arguments
        """
        logger.info("[FirecrackerManager] [STUB] Getting status for Firecracker VM: %s", vm_id)

        if vm_id not in self._vms:
            print(f"[FirecrackerManager] [STUB] VM {vm_id} not found")
            return {
                "vm_id": vm_id,
                "status": "error",
                "image": None,
                "ip_address": None,
                "vcpu_count": None,
                "memory_mb": None,
                "uptime_seconds": None,
                "kernel_args": None,
            }

        vm = self._vms[vm_id]

        print(
            f"[FirecrackerManager] [STUB] Would run: "
            f"curl --unix-socket /srv/jailer/{vm_id}/api.socket http://localhost/"
        )

        uptime_seconds = round(time.time() - vm["created_at"], 1)

        return {
            "vm_id": vm_id,
            "status": vm["status"],
            "image": vm["image"],
            "ip_address": vm["ip_address"],
            "vcpu_count": vm["config"]["vcpu_count"],
            "memory_mb": vm["config"]["memory_mb"],
            "uptime_seconds": uptime_seconds,
            "kernel_args": vm["config"]["kernel_args"],
        }
