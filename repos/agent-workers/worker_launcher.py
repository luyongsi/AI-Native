"""
worker_launcher.py — 一键启动所有 Agent Worker 的 Temporal Activities

启动逻辑：
  1. 实例化所有已注册的 Agent Worker (A1-A13, K14-K15)
  2. 初始化 NATS 连接
  3. 为每个 Agent 创建对应的 Temporal Activity
  4. 注册到 Temporal Worker，开始监听 workflow 任务

用法：
  python3 worker_launcher.py
"""

import asyncio
import logging
import signal
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from base_worker import BaseAgentWorker, make_temporal_activity

# 导入所有 Agent 实现 (A1-A13, K14-K15 = 15 agents)
from a1_requirement_intake import A1RequirementIntake        # A1
from a2_knowledge_analyst import A2KnowledgeAnalyst          # A2
from a3_ui_generator import UIGeneratorAgent                 # A3
from a4_spec_writer import A4SpecWriter                      # A4
from a5_design_review import DesignReviewAgent               # A5
from a6_spec_decomposer import SpecDecomposerAgent            # A6
from a7_test_case_generator import TestCaseGeneratorAgent     # A7
from a8_architecture_expert import ArchitectureExpertAgent    # A8
from a9_dev_agent_stub import DevAgent                        # A9
from ci_agent import CICDAgent                                # A10
from a11_test_agent_stub import A11TestAgentStub              # A11
from a12_code_review import CodeReviewAgent                   # A12
from release_agent import ReleaseAgent                        # A13
from k14_knowledge_keeper import KnowledgeKeeperAgent         # K14
from k15_change_propagation import ChangePropagationAgent     # K15
from fast_channel_classifier import FastChannelClassifier      # FC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker_launcher")

# ---- Agent 注册表 ----
# 格式: { agent_instance: activity_name }
AGENT_REGISTRY: dict[BaseAgentWorker, str] = {}


def register_agents():
    """注册所有 15 个 Agent Worker (A1-A13, K14-K15)"""
    agents = [
        A1RequirementIntake(),          # A1  需求提取
        A2KnowledgeAnalyst(),           # A2  知识分析
        UIGeneratorAgent(),             # A3  原型生成
        A4SpecWriter(),                 # A4  Spec 编写
        DesignReviewAgent(),            # A5  设计评审
        SpecDecomposerAgent(),          # A6  DAG 拆解
        TestCaseGeneratorAgent(),       # A7  测试生成
        ArchitectureExpertAgent(),      # A8  架构评审
        DevAgent(),                     # A9  开发 Agent
        CICDAgent(),                    # A10 CI/CD
        A11TestAgentStub(),             # A11 测试执行
        CodeReviewAgent(),              # A12 Code Review
        ReleaseAgent(),                 # A13 发布上线
        KnowledgeKeeperAgent(),         # K14 知识沉淀
        ChangePropagationAgent(),       # K15 变更传播
        FastChannelClassifier(),         # FC  快速通道分类器
    ]
    for agent in agents:
        activity_name = f"{agent.agent_id}_{agent.agent_type}"
        AGENT_REGISTRY[agent] = activity_name
        logger.info(f"Registered: {agent.agent_id} -> {activity_name}")
    return agents


async def main():
    logger.info("=" * 60)
    logger.info("  Agent Workers Launcher — AI Native Platform")
    logger.info(f"  Total Agents: 16 (A1-A13, K14-K15, FC)")
    logger.info("=" * 60)

    # Step 1: 注册 Agent
    agents = register_agents()

    # Step 2: 初始化所有 Agent 的 NATS 连接
    logger.info("Initializing NATS connections...")
    init_tasks = [agent.init() for agent in AGENT_REGISTRY]
    await asyncio.gather(*init_tasks)
    logger.info("All NATS connections established")

    # Step 3: Start NATS subscriptions — each agent subscribes to its own subject(s)
    logger.info("Starting NATS subscriptions...")
    # Define extra NATS subjects per agent
    _extra_subjects = {
        "A4": ["spec.ready.designing"],  # A4 also listens to spec.ready from chat
        "A5": ["review.start"],          # A5 triggered by approval chain
        "A6": ["review.completed"],      # A6 triggered after A5 review
        "A3": ["gate.0.approved"],       # A3 triggered by Gate 0 approval
        "A13": ["gate.3.approved"],      # A13 triggered by Gate 3 approval
        "A9": ["context.ready.dev_agent"], # A9 triggered by Gate 2 approval
        "FC": ["requirement_draft.created"], # FC triggered by new requirement drafts
    }
    for agent in AGENT_REGISTRY:
        extra = _extra_subjects.get(agent.agent_id, None)
        await agent.subscribe_nats(extra_subjects=extra)
    agent_ids = [a.agent_id for a in AGENT_REGISTRY]
    logger.info(f"Subscribed agents: {', '.join(agent_ids)} — listening via NATS JetStream")

    # Step 4: 创建 Temporal Activity 并注册到 Worker (optional, for Temporal fallback)
    all_activities = []
    for agent, activity_name in AGENT_REGISTRY.items():
        activity_fn = make_temporal_activity(agent, activity_name)
        all_activities.append(activity_fn)

    # Step 4: 尝试连接 Temporal Server
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
        logger.info("Running in standalone mode — activities are defined but not consuming from Temporal")
        logger.info("Press Ctrl+C to stop")

        stop_event = asyncio.Event()

        def _shutdown(sig, frame):
            logger.info("Shutting down...")
            stop_event.set()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        await stop_event.wait()

    finally:
        logger.info("Closing all NATS connections...")
        close_tasks = [agent.close() for agent in AGENT_REGISTRY]
        await asyncio.gather(*close_tasks, return_exceptions=True)
        logger.info("All workers shut down. Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
