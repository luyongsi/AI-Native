"""
CI Build Service — NATS request-reply handler for Docker builds.

Not an Agent. Does not inherit BaseAgentWorker.
Responds to NATS request-reply on subject "ci.build".

Separate from ci_agent.py (CICDAgent) which is a pub-sub event subscriber.
"""

import asyncio
import json
import logging
import os
import sys

import nats

logger = logging.getLogger(__name__)


class CIBuildService:
    """Responds to ci.build NATS requests with Docker build results."""

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc = None
        self._sub = None

    async def init(self):
        """Connect to NATS and subscribe to ci.build request-reply."""
        self.nc = await nats.connect(self.nats_url)
        self._sub = await self.nc.subscribe("ci.build", cb=self._handle_build_request)
        logger.info("[CIBuildService] Listening on ci.build (request-reply)")

    async def _handle_build_request(self, msg):
        """Process a Docker build request and reply via NATS."""
        try:
            data = json.loads(msg.data.decode())
            req_id = data.get("req_id", "unknown")
            repo_path = data.get("repo_path", "")
            dockerfile = data.get("dockerfile", "Dockerfile")
            tag = data.get("tag", f"build-{req_id}")

            logger.info(f"[CIBuildService] Build request: req={req_id} tag={tag}")

            if not repo_path or not os.path.isdir(repo_path):
                await self.nc.publish(msg.reply, json.dumps({
                    "success": False,
                    "error": f"Invalid repo_path: {repo_path}",
                }).encode())
                return

            # Execute Docker build
            proc = await asyncio.create_subprocess_exec(
                "docker", "build", "-t", tag, "-f", dockerfile, repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=180,
            )

            result = {
                "success": proc.returncode == 0,
                "image_tag": tag,
                "req_id": req_id,
                "exit_code": proc.returncode,
                "logs": (stderr.decode()[:2000] if stderr else ""),
            }
            await self.nc.publish(msg.reply, json.dumps(result).encode())
            logger.info(f"[CIBuildService] Build complete: success={result['success']}")

        except asyncio.TimeoutError:
            await self.nc.publish(msg.reply, json.dumps({
                "success": False,
                "error": "Docker build timeout (3 min)",
            }).encode())
            logger.warning("[CIBuildService] Build timeout")
        except FileNotFoundError:
            await self.nc.publish(msg.reply, json.dumps({
                "success": False,
                "error": "Docker not installed or not in PATH",
            }).encode())
        except Exception as e:
            logger.error(f"[CIBuildService] Build failed: {e}")
            try:
                await self.nc.publish(msg.reply, json.dumps({
                    "success": False,
                    "error": str(e),
                }).encode())
            except Exception:
                pass

    async def close(self):
        """Close NATS connection."""
        if self._sub:
            try:
                await self._sub.unsubscribe()
            except Exception:
                pass
        if self.nc:
            try:
                await self.nc.close()
            except Exception:
                pass
        logger.info("[CIBuildService] Shutdown complete")


# Standalone entry point
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")

    async def main():
        service = CIBuildService(nats_url)
        await service.init()
        stop = asyncio.Event()
        try:
            await stop.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await service.close()

    asyncio.run(main())
