"""
ci_agent.py — A10 CI/CD Agent Worker

Listens for code.pushed events and simulates a Docker Build + Lint + Staging Deploy pipeline.
In development, all steps are mocked (sleep-based).
10% chance of pipeline failure.
Publishes pipeline.passed (with mock staging_url) or pipeline.failed on completion.

Supports config-driven pipelines via a YAML pipeline config file.

Usage:
    python3 ci_agent.py                     # run standalone with mock NATS
    python3 ci_agent.py --pipeline-config templates/ci-pipeline.yaml.j2  # parses rendered config
    # Or register in worker_launcher.py     # run alongside the rest of the platform
"""

import argparse
import asyncio
import logging
import random
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yaml

from event_bus import EventPublisher, EventSubscriber
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AGENT_ID = "A10"
AGENT_TYPE = "ci_cd"
FAILURE_PROBABILITY = 0.10  # 10% chance of pipeline failure in dev mode
MOCK_STAGING_URL = "https://staging.ai-native.internal/deploy/{}"

# Step durations (seconds) — accelerated for development
BUILD_DURATION = 5   # Docker build
LINT_DURATION = 3    # Lint check
DEPLOY_DURATION = 2  # Staging deploy


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class CICDAgent(BaseAgentWorker):
    """A10 CI/CD Agent — build, lint, deploy pipeline.

    Supports config-driven pipelines via a YAML config file.  When
    ``pipeline_config`` is provided at init (or loaded later via
    :meth:`load_pipeline_config`), the pipeline respects the config's
    step definitions (build / test / lint / deploy).  Without config,
    the agent falls back to the default 3-step mock pipeline.
    """

    def __init__(
        self,
        nats_url: str = "nats://localhost:4222",
        pipeline_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(agent_id=AGENT_ID, agent_type=AGENT_TYPE, nats_url=nats_url)
        self._publisher: Optional[EventPublisher] = None
        self.pipeline_config: Optional[Dict[str, Any]] = pipeline_config

    async def init(self):
        await super().init()
        self._publisher = EventPublisher(self.nats_url)
        await self._publisher.connect()
        logger.info("[A10] CI/CD Agent initialized")

    async def close(self):
        if self._publisher:
            await self._publisher.disconnect()
        await super().close()

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def load_pipeline_config(self, path: str) -> Dict[str, Any]:
        """Load a YAML pipeline configuration file.

        Uses ``yaml.safe_load`` for secure deserialization.  The loaded
        config is stored on ``self.pipeline_config`` and also returned.

        Args:
            path: Filesystem path to the YAML pipeline config file.

        Returns:
            The parsed configuration dictionary.

        Raises:
            FileNotFoundError: If *path* does not exist.
            yaml.YAMLError: If the file contains invalid YAML.
        """
        logger.info("[A10] Loading pipeline config from %s", path)
        with open(path, "r", encoding="utf-8") as fh:
            config: Dict[str, Any] = yaml.safe_load(fh)
        self.pipeline_config = config
        logger.info("[A10] Pipeline config loaded: %s", config.get("pipeline", {}).get("name", "unnamed"))
        return config

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    async def _build_image(self, image_name: str, dockerfile: str) -> bool:
        """Execute (mock) Docker image build step.

        Args:
            image_name: Docker image name (e.g. ``"ai-native/app"``).
            dockerfile: Path to the Dockerfile (e.g. ``"Dockerfile"``).

        Returns:
            ``True`` if the build succeeded, ``False`` otherwise.
        """
        logger.info(
            "[A10] [BUILD] Building image '%s' from %s (mock, %ds)...",
            image_name, dockerfile, BUILD_DURATION,
        )
        await asyncio.sleep(BUILD_DURATION)
        if not self._maybe_fail(f"Docker build failed for {image_name}"):
            return False
        logger.info("[A10] [BUILD] Image '%s' built successfully", image_name)
        return True

    async def _run_tests(self, test_command: str) -> bool:
        """Execute (mock) test step.

        Args:
            test_command: Shell command to run tests
                          (e.g. ``"npm test"``, ``"pytest"``).

        Returns:
            ``True`` if tests passed, ``False`` otherwise.
        """
        logger.info(
            "[A10] [TEST] Running '%s' (mock, %ds)...",
            test_command, BUILD_DURATION,
        )
        await asyncio.sleep(BUILD_DURATION)
        if not self._maybe_fail(f"Tests failed: {test_command}"):
            return False
        logger.info("[A10] [TEST] Tests passed")
        return True

    # ------------------------------------------------------------------
    # execute  (config-driven or default)
    # ------------------------------------------------------------------

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """
        Execute the CI/CD pipeline.

        If ``self.pipeline_config`` is set the pipeline is driven by
        the config's *pipeline* section (build / test / lint / deploy).
        Each step whose ``enabled`` key is ``true`` is executed in order.

        Without config, the agent falls back to the original default
        3-step mock pipeline (Docker Build -> Lint -> Staging Deploy).

        Returns pipeline result dict.
        """
        logger.info("[A10] Pipeline started for req=%s", req_id)
        await self.report_status(req_id, "running", "CI/CD pipeline started")

        if self.pipeline_config:
            return await self._execute_config_driven(req_id, context_package)
        else:
            return await self._execute_default(req_id, context_package)

    async def _execute_config_driven(
        self, req_id: str, context_package: dict,
    ) -> dict:
        """Config-driven pipeline: honour the pipeline YAML section."""
        pipeline = self.pipeline_config.get("pipeline", {})
        pipeline_name: str = pipeline.get("name", "default")
        step_times: Dict[str, float] = {}
        staging_url = MOCK_STAGING_URL.format(req_id)

        logger.info("[A10] Config-driven pipeline '%s' for req=%s", pipeline_name, req_id)

        # ── Build ──
        build_cfg = pipeline.get("build", {})
        if build_cfg.get("enabled", False):
            await self.report_status(req_id, "running", "[BUILD] Docker image build in progress...")
            image_name: str = build_cfg.get("image_name", "ai-native/app")
            dockerfile: str = build_cfg.get("dockerfile", "Dockerfile")
            ok = await self._build_image(image_name, dockerfile)
            step_times["build_time_s"] = BUILD_DURATION
            if not ok:
                return await self._fail_pipeline(
                    req_id, "docker_build",
                    f"Build of '{image_name}' via {dockerfile} failed",
                )

        # ── Test ──
        test_cfg = pipeline.get("test", {})
        if test_cfg.get("enabled", False):
            await self.report_status(req_id, "running", "[TEST] Running tests...")
            test_command: str = test_cfg.get("command", "npm test")
            ok = await self._run_tests(test_command)
            step_times["test_time_s"] = BUILD_DURATION
            if not ok:
                return await self._fail_pipeline(
                    req_id, "test",
                    f"Tests failed: {test_command}",
                )

        # ── Lint ──
        lint_cfg = pipeline.get("lint", {})
        if lint_cfg.get("enabled", False):
            await self.report_status(req_id, "running", "[LINT] Running lint checks...")
            lint_command: str = lint_cfg.get("command", "npm run lint")
            logger.info("[A10] [LINT] %s (mock, %ds)...", lint_command, LINT_DURATION)
            await asyncio.sleep(LINT_DURATION)
            step_times["lint_time_s"] = LINT_DURATION
            if not self._maybe_fail(f"Lint failed: {lint_command}"):
                return await self._fail_pipeline(
                    req_id, "lint",
                    f"Lint check '{lint_command}' found errors",
                )

        # ── Deploy ──
        deploy_cfg = pipeline.get("deploy", {})
        if deploy_cfg.get("enabled", False):
            deploy_target: str = deploy_cfg.get("target", "staging")
            deploy_url: str = deploy_cfg.get("url", staging_url)
            health_path: str = deploy_cfg.get("health_check_path", "/health")
            await self.report_status(
                req_id, "running",
                f"[DEPLOY] Deploying to {deploy_target} ({deploy_url})...",
            )
            logger.info(
                "[A10] [DEPLOY] Deploy to %s (mock, %ds)...",
                deploy_target, DEPLOY_DURATION,
            )
            await asyncio.sleep(DEPLOY_DURATION)
            step_times["deploy_time_s"] = DEPLOY_DURATION
            if not self._maybe_fail(f"Deploy to {deploy_target} failed"):
                return await self._fail_pipeline(
                    req_id, "staging_deploy",
                    f"Health check {health_path} on {deploy_url} timed out",
                )
            # Override staging URL if config supplies one
            staging_url = deploy_url

        # ── Notifications (config-driven) ──
        notif_cfg = pipeline.get("notifications", {})
        on_success: str = notif_cfg.get("on_success", "pipeline.passed")
        on_failure: str = notif_cfg.get("on_failure", "pipeline.failed")

        # ── Success ──
        await self.report_artifact(req_id, "staging_deployment", {
            "staging_url": staging_url,
            **step_times,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pipeline_name": pipeline_name,
            "notification_event": on_success,
        })

        await self.report_status(
            req_id, "completed",
            f"Pipeline '{pipeline_name}' passed — staging at {staging_url}",
        )
        await self._publisher.pipeline_passed(
            req_id=req_id,
            agent_id=AGENT_ID,
            staging_url=staging_url,
        )
        logger.info(
            "[A10] Pipeline '%s' PASSED for req=%s url=%s",
            pipeline_name, req_id, staging_url,
        )

        return {"status": "passed", "staging_url": staging_url, "pipeline_name": pipeline_name}

    async def _execute_default(
        self, req_id: str, context_package: dict,
    ) -> dict:
        """Default 3-step mock pipeline (backward-compatible fallback)."""
        # ── Step 1: Docker Build ──
        await self.report_status(req_id, "running", "[BUILD] Docker image build in progress...")
        logger.info("[A10] [BUILD] Building Docker image (mock, %ds)...", BUILD_DURATION)
        await asyncio.sleep(BUILD_DURATION)
        if not self._maybe_fail("Docker build failed: mock error"):
            return await self._fail_pipeline(req_id, "docker_build", "Mock build error — image pull timeout")

        # ── Step 2: Lint ──
        await self.report_status(req_id, "running", "[LINT] Running lint checks...")
        logger.info("[A10] [LINT] Lint checks (mock, %ds)...", LINT_DURATION)
        await asyncio.sleep(LINT_DURATION)
        if not self._maybe_fail("Lint failed: mock error"):
            return await self._fail_pipeline(req_id, "lint", "Mock lint error — ESLint found 3 errors")

        # ── Step 3: Staging Deploy ──
        await self.report_status(req_id, "running", "[DEPLOY] Staging deploy in progress...")
        logger.info("[A10] [DEPLOY] Deploying to staging (mock, %ds)...", DEPLOY_DURATION)
        await asyncio.sleep(DEPLOY_DURATION)
        if not self._maybe_fail("Staging deploy failed: mock error"):
            return await self._fail_pipeline(req_id, "staging_deploy", "Mock deploy error — health check timeout")

        # ── Success ──
        staging_url = MOCK_STAGING_URL.format(req_id)
        await self.report_artifact(req_id, "staging_deployment", {
            "staging_url": staging_url,
            "build_time_s": BUILD_DURATION,
            "lint_time_s": LINT_DURATION,
            "deploy_time_s": DEPLOY_DURATION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await self.report_status(req_id, "completed", f"Pipeline passed — staging at {staging_url}")
        await self._publisher.pipeline_passed(
            req_id=req_id,
            agent_id=AGENT_ID,
            staging_url=staging_url,
        )
        logger.info("[A10] Pipeline PASSED for req=%s url=%s", req_id, staging_url)

        return {"status": "passed", "staging_url": staging_url}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _maybe_fail(self, _reason: str) -> bool:
        """Return True if the step succeeds, False if mock failure triggers."""
        if random.random() < FAILURE_PROBABILITY:
            logger.warning("[A10] Mock failure triggered")
            return False
        return True

    async def _fail_pipeline(self, req_id: str, step: str, reason: str) -> dict:
        """Handle pipeline failure: publish events and return result."""
        await self.report_status(req_id, "failed", f"Pipeline failed at step '{step}': {reason}")
        await self._publisher.pipeline_failed(
            req_id=req_id,
            agent_id=AGENT_ID,
            reason=f"[{step}] {reason}",
        )
        logger.error("[A10] Pipeline FAILED for req=%s at %s: %s", req_id, step, reason)
        return {"status": "failed", "step": step, "reason": reason}


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

async def main(pipeline_config_path: Optional[str] = None):
    """Run CI Agent directly for development/testing.

    Args:
        pipeline_config_path: If provided, the YAML config is loaded and
            passed to the agent so the pipeline runs in config-driven mode.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    agent = CICDAgent()
    if pipeline_config_path:
        agent.load_pipeline_config(pipeline_config_path)
    await agent.init()

    subscriber = EventSubscriber()
    publisher = EventPublisher()
    await publisher.connect()

    # Register to listen for code.pushed
    @subscriber.on("code.pushed")
    async def on_code_pushed(event: dict):
        req_id = event.get("req_id", "unknown")
        logger.info("[A10] Received code.pushed for req=%s", req_id)
        result = await agent.execute(req_id, event.get("context", {}))
        logger.info("[A10] Pipeline result: %s", result)

    await subscriber.start()
    logger.info("[A10] CI Agent listening on code.pushed — Ctrl+C to stop")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("[A10] Shutting down...")
    finally:
        await subscriber.stop()
        await agent.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A10 CI/CD Agent — standalone runner",
    )
    parser.add_argument(
        "--pipeline-config",
        dest="pipeline_config",
        default=None,
        help="Path to a YAML pipeline configuration file (config-driven mode).",
    )
    args = parser.parse_args()
    asyncio.run(main(pipeline_config_path=args.pipeline_config))
