"""
release_agent.py — A13 Release Agent Worker

Listens for gate.3.approved events and performs a simulated canary deployment
with progressive traffic shifting (5% -> 20% -> 50% -> 100%).
Includes mock Prometheus metric checks.
Publishes release.completed on success.

Usage:
    python3 release_agent.py                # run standalone with mock NATS
    # Or register in worker_launcher.py     # run alongside the rest of the platform
"""

import asyncio
import logging
import random
import sys
from datetime import datetime, timezone
from typing import Optional

from event_bus import EventPublisher, EventSubscriber
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A13"
AGENT_TYPE = "release"

CANARY_STAGES = [
    (5, "canary-5%"),
    (20, "canary-20%"),
    (50, "canary-50%"),
    (100, "full-rollout"),
]

STAGE_DURATION = 2
PROMETHEUS_CHECK_WINDOW = 1
ERROR_RATE_THRESHOLD = 1.0
LATENCY_P99_THRESHOLD_MS = 500


class ReleaseAgent(BaseAgentWorker):
    def __init__(self, nats_url="nats://localhost:4222"):
        super().__init__(agent_id=AGENT_ID, agent_type=AGENT_TYPE, nats_url=nats_url)
        self._publisher = None

    async def init(self):
        await super().init()
        self._publisher = EventPublisher(self.nats_url)
        await self._publisher.connect()
        logger.info("[A13] Release Agent initialized")

    async def close(self):
        if self._publisher:
            await self._publisher.disconnect()
        await super().close()

    async def execute(self, req_id, context_package):
        logger.info("[A13] Canary release started for req=%s", req_id)
        await self.report_status(req_id, "running", "Canary release started")

        release_id = f"release-{req_id[:8]}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        stage_results = []

        for percentage, label in CANARY_STAGES:
            await self.report_status(req_id, "running", f"[RELEASE] {label}: traffic={percentage}%")

            logger.info("[A13] %s - shifting traffic to %d%%", label, percentage)
            await asyncio.sleep(STAGE_DURATION)

            metrics_ok = await self._check_prometheus_metrics(req_id, label, percentage)
            if not metrics_ok:
                return await self._abort_release(req_id, label, "Prometheus metrics out of threshold")

            stage_results.append({
                "stage": label,
                "percentage": percentage,
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("[A13] %s - metrics healthy, proceeding", label)

        await self.report_artifact(req_id, "release", {
            "release_id": release_id,
            "stages": stage_results,
            "final_percentage": 100,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await self.report_status(req_id, "completed", f"Release {release_id} completed")
        await self._publisher.publish(
            event_type="release.completed",
            payload={
                "release_id": release_id,
                "req_id": req_id,
                "status": "completed",
                "stages": stage_results,
            },
            req_id=req_id,
            agent_id=AGENT_ID,
        )
        logger.info("[A13] Release COMPLETED: %s", release_id)

        return {"status": "completed", "release_id": release_id, "stages": stage_results}

    async def _check_prometheus_metrics(self, req_id, stage, pct):
        await asyncio.sleep(PROMETHEUS_CHECK_WINDOW)
        error_rate = round(random.uniform(0.0, 2.0), 3)
        latency_p99 = round(random.uniform(50, 800), 1)

        logger.info(
            "[A13] Prometheus check (%s @ %d%%): error_rate=%.3f%%, p99_latency=%.1fms",
            stage, pct, error_rate, latency_p99,
        )

        if error_rate > ERROR_RATE_THRESHOLD or latency_p99 > LATENCY_P99_THRESHOLD_MS:
            logger.warning(
                "[A13] Metrics breach! error=%.3f%% (thresh=%.1f%%), p99=%.1fms (thresh=%dms)",
                error_rate, ERROR_RATE_THRESHOLD, latency_p99, LATENCY_P99_THRESHOLD_MS,
            )
            return False
        return True

    async def _abort_release(self, req_id, stage, reason):
        await self.report_status(req_id, "failed", f"Release aborted at {stage}: {reason}")
        logger.error("[A13] Release ABORTED at %s: %s - rolling back", stage, reason)

        await asyncio.sleep(STAGE_DURATION)
        logger.info("[A13] Rollback complete")

        await self._publisher.publish(
            event_type="release.failed",
            payload={
                "req_id": req_id,
                "status": "aborted",
                "stage": stage,
                "reason": reason,
            },
            req_id=req_id,
            agent_id=AGENT_ID,
        )

        return {"status": "aborted", "stage": stage, "reason": reason}


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    agent = ReleaseAgent()
    await agent.init()

    subscriber = EventSubscriber()

    @subscriber.on("gate.3.approved")
    async def on_gate3_approved(event):
        req_id = event.get("req_id", "unknown")
        logger.info("[A13] Received gate.3.approved for req=%s", req_id)
        result = await agent.execute(req_id, event.get("context", {}))
        logger.info("[A13] Release result: %s", result)

    await subscriber.start()
    logger.info("[A13] Release Agent listening on gate.3.approved - Ctrl+C to stop")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("[A13] Shutting down...")
    finally:
        await subscriber.stop()
        await agent.close()

if __name__ == "__main__":
    asyncio.run(main())
