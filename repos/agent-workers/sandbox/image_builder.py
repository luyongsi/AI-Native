"""
Sandbox Image Builder — Builds and manages Firecracker-compatible rootfs images.

Provides build, list, and delete operations for sandbox images used as the
base root filesystem for Firecracker microVMs.

Default tools installed in each image:
    - claude-code  (Claude Code CLI)
    - node22       (Node.js 22.x)
    - python3.12   (Python 3.12)
    - git          (Git SCM)
    - curl         (HTTP client)
    - jq           (JSON processor)

All methods are async stubs that return realistic mock outputs.
Real implementation described in method docstrings.

Production build pipeline:
    1. `docker run` an Alpine base container
    2. Install tools via apk / pip / npm
    3. `docker export` the container to a tar
    4. Convert tar to ext4 rootfs image via `mkfs.ext4`
    5. Store in /opt/firecracker/images/<image_id>/
"""

import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)


class ImageBuilder:
    """
    Builds and manages sandbox rootfs images for Firecracker microVMs.

    Real implementation (future):
        import docker, subprocess, os
        from pathlib import Path

        self.client = docker.from_env()
        self.image_store = Path("/opt/firecracker/images")

    Stub implementation (current):
        Pre-seeded with one image "ai-sandbox:firecracker".
        Build/lifecycle operations are simulated with realistic timings.
    """

    # Default tools installed in each sandbox image
    DEFAULT_TOOLS: list[str] = [
        "claude-code",
        "node22",
        "python3.12",
        "git",
        "curl",
        "jq",
    ]

    # Known tool-to-package-install commands for the production build pipeline
    TOOL_INSTALL_COMMANDS: dict[str, str] = {
        "claude-code": "npm install -g @anthropic-ai/claude-code",
        "node22": "apk add nodejs=22",
        "python3.12": "apk add python3=3.12 py3-pip",
        "git": "apk add git",
        "curl": "apk add curl",
        "jq": "apk add jq",
    }

    def __init__(self):
        # Pre-seeded sandbox image
        self._images: dict[str, dict] = {
            "img-sandbox-001": {
                "image_id": "img-sandbox-001",
                "image_name": "ai-sandbox:firecracker",
                "base_image": "alpine:3.19",
                "size_mb": 512,
                "tools_installed": list(self.DEFAULT_TOOLS),
                "created_at": time.time(),
                "build_time_seconds": 45.2,
            },
        }
        logger.info(
            "[ImageBuilder] Initialized with %d pre-built image(s) (stub mode)",
            len(self._images),
        )

    # ------------------------------------------------------------------
    # Build Image
    # ------------------------------------------------------------------

    async def build_sandbox_image(
        self,
        base_image: str = "alpine:3.19",
        tools: list[str] = None,
    ) -> dict:
        """
        Build a new sandbox rootfs image from a base Alpine image.

        Simulates the production pipeline:
            1. Pull base image (docker pull alpine:3.19)
            2. Create ephemeral container
            3. Install toolchain packages
            4. Export container filesystem to tar
            5. Convert tar to ext4 rootfs
            6. Register image in the catalog

        Real implementation (future):
            container = self.client.containers.run(base_image, detach=True, command="sleep infinity")
            for tool in tools:
                cmd = self.TOOL_INSTALL_COMMANDS.get(tool)
                if cmd:
                    container.exec_run(f"sh -c '{cmd}'")
            container.stop()
            # Export and convert
            os.system(f"docker export {container.id} | ... > {image_path}")

        Args:
            base_image: Base Docker image to build from (default "alpine:3.19").
            tools: List of tool identifiers to install. If None, uses DEFAULT_TOOLS.
                   Valid values: "claude-code", "node22", "python3.12", "git", "curl", "jq".

        Returns:
            dict with keys:
                image_id            - Unique identifier for the built image
                image_name          - Human-readable image name/tag
                size_mb             - Rootfs image size in MiB
                build_time_seconds  - Total build duration in seconds
                tools_installed     - List of tools actually installed
        """
        if tools is None:
            tools = list(self.DEFAULT_TOOLS)

        image_id = f"img-{uuid.uuid4().hex[:8]}"
        image_name = f"ai-sandbox:{image_id[:12]}"

        # Validate tools
        valid_tools = [t for t in tools if t in self.TOOL_INSTALL_COMMANDS]
        invalid_tools = [t for t in tools if t not in self.TOOL_INSTALL_COMMANDS]
        if invalid_tools:
            logger.warning(
                "[ImageBuilder] [STUB] Unknown tools ignored: %s",
                ", ".join(invalid_tools),
            )

        logger.info(
            "[ImageBuilder] [STUB] Building sandbox image: base=%s, tools=%s, image_id=%s",
            base_image, ", ".join(valid_tools), image_id,
        )

        build_start = time.perf_counter()

        # Simulate build time: ~2s base + 5s per tool
        build_delay = 2.0 + (0.5 * len(valid_tools))
        await asyncio.sleep(build_delay)

        build_end = time.perf_counter()
        build_time_seconds = round(build_end - build_start, 1)

        # Estimate image size: base 80MB + tool overhead
        tool_size_overheads = {
            "claude-code": 120,
            "node22": 85,
            "python3.12": 90,
            "git": 15,
            "curl": 8,
            "jq": 3,
        }
        size_mb = 80 + sum(tool_size_overheads.get(t, 10) for t in valid_tools)

        image_record = {
            "image_id": image_id,
            "image_name": image_name,
            "base_image": base_image,
            "size_mb": size_mb,
            "tools_installed": valid_tools,
            "created_at": time.time(),
            "build_time_seconds": build_time_seconds,
        }
        self._images[image_id] = image_record

        # Log the equivalent production build commands
        print(
            f"[ImageBuilder] [STUB] Would run: docker pull {base_image}"
        )
        for tool in valid_tools:
            print(
                f"[ImageBuilder] [STUB] Would run: docker exec <temp-container> "
                f"sh -c '{self.TOOL_INSTALL_COMMANDS.get(tool, '')}'"
            )
        print(
            f"[ImageBuilder] [STUB] Would run: docker export <temp-container> | "
            f"mkfs.ext4 -d /dev/stdin /opt/firecracker/images/{image_id}/rootfs.ext4"
        )
        print(
            f"[ImageBuilder] [STUB] Image built: {image_name} "
            f"({size_mb}MiB, {build_time_seconds}s, {len(valid_tools)} tools)"
        )

        return {
            "image_id": image_id,
            "image_name": image_name,
            "size_mb": size_mb,
            "build_time_seconds": build_time_seconds,
            "tools_installed": valid_tools,
        }

    # ------------------------------------------------------------------
    # List Images
    # ------------------------------------------------------------------

    async def list_images(self) -> list[dict]:
        """
        List all available sandbox images in the catalog.

        Real implementation (future):
            images = []
            for img_dir in self.image_store.iterdir():
                if img_dir.is_dir():
                    manifest = json.loads((img_dir / "manifest.json").read_text())
                    images.append(manifest)
            return images

        Returns:
            list of dict, each with keys:
                image_id, image_name, size_mb, tools_installed, created_at, build_time_seconds
        """
        logger.info(
            "[ImageBuilder] [STUB] Listing images — %d available",
            len(self._images),
        )

        images = []
        for img in self._images.values():
            images.append({
                "image_id": img["image_id"],
                "image_name": img["image_name"],
                "size_mb": img["size_mb"],
                "tools_installed": img["tools_installed"],
                "created_at": img["created_at"],
                "build_time_seconds": img["build_time_seconds"],
            })

        print(f"[ImageBuilder] [STUB] Would run: ls /opt/firecracker/images/")
        print(f"[ImageBuilder] [STUB] Found {len(images)} image(s)")

        return images

    # ------------------------------------------------------------------
    # Delete Image
    # ------------------------------------------------------------------

    async def delete_image(self, image_id: str) -> dict:
        """
        Delete a sandbox image from the catalog and its rootfs from disk.

        Real implementation (future):
            img_path = self.image_store / image_id
            if img_path.exists():
                shutil.rmtree(img_path)
            del self._images[image_id]

        Args:
            image_id: The image identifier returned by build_sandbox_image().

        Returns:
            dict with keys:
                deleted   - True if the image was deleted
                image_id  - The image ID that was targeted
                image_name - The image name (only present if found)
        """
        logger.info("[ImageBuilder] [STUB] Deleting image: %s", image_id)

        if image_id not in self._images:
            logger.warning("[ImageBuilder] [STUB] Image not found: %s", image_id)
            print(f"[ImageBuilder] [STUB] Image {image_id} not found — nothing to delete")
            return {
                "deleted": False,
                "image_id": image_id,
            }

        image_record = self._images[image_id]

        # Simulate disk cleanup
        await asyncio.sleep(0.05)

        print(
            f"[ImageBuilder] [STUB] Would run: "
            f"rm -rf /opt/firecracker/images/{image_id}/"
        )
        print(
            f"[ImageBuilder] [STUB] Image deleted: {image_record['image_name']} "
            f"({image_record['size_mb']}MiB freed)"
        )

        image_name = image_record["image_name"]
        del self._images[image_id]

        return {
            "deleted": True,
            "image_id": image_id,
            "image_name": image_name,
        }
