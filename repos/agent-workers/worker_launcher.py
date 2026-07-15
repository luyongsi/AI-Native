"""
worker_launcher.py — 一键启动阶段一 Agent Worker 的 NATS 订阅 + 桥接服务

当前阶段一只需 A1、A2 和 Gate0（人工审批），其余 Agent 在后续阶段启用。

启动逻辑：
  1. 实例化 A1 + A2 Agent Worker
  2. 初始化 NATS 连接
  3. 启动 NATS-Temporal Bridge（agent.result → Workflow Signal）
  4. 为每个 Agent 订阅 NATS（只订阅 context.ready.{agent_type}）

用法：
  python3 worker_launcher.py
"""

import asyncio
import logging
import os
import signal
import sys

# ── Load environment from /etc/ai-native.env at startup ──────────────
_ENV_FILE = "/etc/ai-native.env"
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ[_key.strip()] = _val.strip()
    print(f"[worker_launcher] Loaded environment from {_ENV_FILE}")

from temporalio.client import Client
from temporalio.worker import Worker

from base_worker import BaseAgentWorker, make_temporal_activity

# ── Phase 1 agents (A1 + A2) ─────────────────────────────────────────
from a1_requirement_intake import A1RequirementIntake
from a2_knowledge_analyst import A2KnowledgeAnalyst

# ── Phase 2 agents (A3 + A4 + A5) — Stage 2 design pipeline ───────────
from a3_ui_generator import UIGeneratorAgent
from a4_spec_writer import A4SpecWriter
from a5_design_review import DesignReviewAgent

# ── Phase 3 agents (A6 + A7 + A8) — Stage 3 tech prep pipeline ─────────
from a6_spec_decomposer import SpecDecomposerAgent
from a7_test_case_generator import TestCaseGeneratorAgent
from a8_architecture_expert import ArchitectureExpertAgent
# ── Phase 4+ agents (disabled for now — enable when stages 4-5 go live)
# from a9.a9_dev_agent import A9DevAgent
# from ci_agent import CICDAgent
# from a11_test_agent_stub import A11TestAgentStub
# from a12_code_review import CodeReviewAgent
# from release_agent import ReleaseAgent
# from k14_knowledge_keeper import KnowledgeKeeperAgent
# from k15_change_propagation import ChangePropagationAgent
# from fast_channel_classifier import FastChannelClassifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker_launcher")

# Agent 注册表
AGENT_REGISTRY: dict[BaseAgentWorker, str] = {}

# ── Phase 1 + Phase 2 + Phase 3 agents: A1 + A2 + A3 + A4 + A5 + A6 + A7 + A8 ──
_PHASE1_AGENTS = [
    A1RequirementIntake(),
    A2KnowledgeAnalyst(),
    UIGeneratorAgent(),
    A4SpecWriter(),
    DesignReviewAgent(),
    SpecDecomposerAgent(),
    TestCaseGeneratorAgent(),
    ArchitectureExpertAgent(),
]


def register_agents():
    """注册当前阶段启用的 Agent Worker。"""
    agents = list(_PHASE1_AGENTS)

    # ── Phase 2+ agents (disabled until their stages go live) ─────────
    # A9_WORKER_COUNT = int(os.environ.get("A9_WORKER_COUNT", "1"))
    # for i in range(A9_WORKER_COUNT):
    #     agents.append(A9DevAgent(...))
    # agents.extend([
    #     UIGeneratorAgent(), A4SpecWriter(), DesignReviewAgent(),
    #     SpecDecomposerAgent(), TestCaseGeneratorAgent(),
    #     ArchitectureExpertAgent(), CICDAgent(), A11TestAgentStub(),
    #     CodeReviewAgent(), ReleaseAgent(),
    #     KnowledgeKeeperAgent(), ChangePropagationAgent(),
    #     FastChannelClassifier(),
    # ])

    for agent in agents:
        activity_name = f"{agent.agent_id}_{agent.agent_type}"
        AGENT_REGISTRY[agent] = activity_name
        logger.info(f"Registered: {agent.agent_id} -> {activity_name}")
    return agents


async def main():
    logger.info("=" * 60)
    logger.info("  Agent Workers Launcher — AI Native Platform (Phase 1+2+3)")
    logger.info(f"  Total Agents: {len(_PHASE1_AGENTS)} (A1 + A2 + A3 + A4 + A5 + A6 + A7 + A8)")
    logger.info("=" * 60)

    agents = register_agents()

    # Step 1: Initialize all NATS connections
    logger.info("Initializing NATS connections...")
    init_tasks = [agent.init() for agent in AGENT_REGISTRY]
    await asyncio.gather(*init_tasks)
    logger.info("All NATS connections established")

    # Step 2: Start NATS-Temporal Bridge
    logger.info("Starting NATS-Temporal Bridge...")
    first_agent = next(iter(AGENT_REGISTRY))
    from nats_temporal_bridge import start_nats_temporal_bridge
    bridge_task = asyncio.create_task(start_nats_temporal_bridge(first_agent.nc))
    logger.info("Bridge task created")

    # Step 3: Subscribe agents — each only to context.ready.{agent_type}
    logger.info("Starting NATS subscriptions (single-subject per agent)...")
    for agent in AGENT_REGISTRY:
        await agent.subscribe_nats()
    agent_ids = [a.agent_id for a in AGENT_REGISTRY]
    logger.info(f"Subscribed agents: {', '.join(agent_ids)}")

    # Step 4: Optional Temporal registration
    all_activities = []
    for agent, activity_name in AGENT_REGISTRY.items():
        activity_fn = make_temporal_activity(agent, activity_name)
        all_activities.append(activity_fn)

    temporal_client = None
    try:
        temporal_client = await Client.connect("localhost:7233")
        logger.info("Connected to Temporal Server at localhost:7233")

        worker = Worker(
            temporal_client,
            task_queue="agent-worker-queue",
            activities=all_activities,
        )
        logger.info("Temporal Worker started on task_queue='agent-worker-queue'")
        logger.info("Listening for workflows... (Ctrl+C to stop)")

        await worker.run()

    except Exception as e:
        logger.warning(f"Temporal Server not available: {e}")
        logger.info("Running in standalone mode — NATS subscriptions active")
        logger.info("Press Ctrl+C to stop")

        stop_event = asyncio.Event()

        def _shutdown(sig, frame):
            logger.info("Shutting down...")
            stop_event.set()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        await stop_event.wait()

    finally:
        logger.info("Closing all connections...")
        bridge_task.cancel()
        close_tasks = [agent.close() for agent in AGENT_REGISTRY]
        await asyncio.gather(*close_tasks, return_exceptions=True)
        logger.info("All workers shut down. Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
