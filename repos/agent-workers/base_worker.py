"""
base_worker.py — Agent Worker 基类

所有 Agent (A1-A13, K14-K15, FC) 共用此运行时基类。
提供 NATS 连接、Temporal Activity 注册、状态上报、产物上报。

Phase 5.3: 集成 mc_observability — 自动记录 agent 执行耗时、状态、LLM 调用。
"""
import asyncio
import json
import logging
import time as _time_module
import uuid
from datetime import datetime, timezone

import nats
from temporalio import activity, workflow
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Lazy import observability — falls back gracefully if not available
try:
    from mc_observability import record_agent_start, record_agent_end, record_nats_event, record_llm_call
    _HAS_OBSERVABILITY = True
except ImportError:
    _HAS_OBSERVABILITY = False
    def record_agent_start(aid, rid): pass
    def record_agent_end(aid, rid, status="completed"): pass
    def record_nats_event(et, aid="", rid=""): pass
    def record_llm_call(provider, agent_id, duration_s, success): pass


class StatusDetail(BaseModel):
    agent_id: str
    req_id: str
    status: str          # "pending", "running", "completed", "failed"
    message: str = ""
    timestamp: str = ""


class ArtifactRecord(BaseModel):
    agent_id: str
    req_id: str
    artifact_type: str   # "requirement_draft", "knowledge_brief", "openapi_spec", "erd", "code_diff", "test_report"
    data: dict
    timestamp: str = ""


class BaseAgentWorker:
    """所有 Agent Worker 的基类"""

    # 子类覆盖
    agent_id: str = ""
    agent_type: str = ""

    def __init__(self, agent_id: str, agent_type: str, nats_url: str = "nats://localhost:4222"):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.nats_url = nats_url
        self.nc = None          # NATS connection
        self.js = None          # JetStream context

    async def init(self):
        """连接 NATS，初始化 JetStream"""
        logger.info(f"[{self.agent_id}] Initializing {self.agent_type} worker...")
        self.nc = await nats.connect(self.nats_url)
        self.js = self.nc.jetstream()
        logger.info(f"[{self.agent_id}] Connected to NATS at {self.nats_url}")

    async def close(self):
        """关闭连接"""
        if self.nc:
            await self.nc.drain()
            logger.info(f"[{self.agent_id}] NATS connection closed")

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """子类重写此方法 — 执行 Agent 核心逻辑"""
        raise NotImplementedError

    async def subscribe_nats(self, subject: str = "", extra_subjects: list[str] | None = None):
        """Subscribe to NATS subjects and handle messages.

        When a message arrives on the subscribed subject, parse it as a dispatch
        envelope, call self.execute(), and publish results back.
        """
        async def _handle(msg):
            try:
                data = json.loads(msg.data.decode())
                logger.info(f"[{self.agent_id}] Received NATS message on '{msg.subject}'")
                req_id = data.get("req_id", "") or data.get("payload", {}).get("req_id", "")
                context = data.get("payload", {})
                context["event_type"] = data.get("event_type", "")
                record_agent_start(self.agent_id, req_id)
                try:
                    result = await self.execute(req_id, context)
                    record_agent_end(self.agent_id, req_id, "completed")
                except Exception as exec_err:
                    record_agent_end(self.agent_id, req_id, "failed")
                    raise exec_err
                # Publish result
                reply_subject = f"agent.result.{self.agent_id}"
                await self.nc.publish(reply_subject, json.dumps({
                    "agent_id": self.agent_id,
                    "req_id": req_id,
                    "result": result,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False, default=str).encode())
                logger.info(f"[{self.agent_id}] Published result to '{reply_subject}'")
                await msg.ack()
            except Exception as e:
                logger.error(f"[{self.agent_id}] Error handling NATS message: {e}", exc_info=True)
                await msg.nak()

        subjects = [subject or f"context.ready.{self.agent_type}"]
        if extra_subjects:
            subjects.extend(extra_subjects)
        import time as _time
        for subj in subjects:
            consumer_name = f"{self.agent_id}_consumer_{subj.replace('.','_')}_{int(_time.time())}"
            try:
                await self.js.subscribe(subj, cb=_handle, stream="AI_NATIVE_EVENTS", durable=consumer_name)
            except Exception:
                # If durable consumer conflicts, try ephemeral
                await self.js.subscribe(subj, cb=_handle, stream="AI_NATIVE_EVENTS")
            logger.info(f"[{self.agent_id}] Subscribed to NATS subject: {subj}")

    async def report_status(self, req_id: str, status: str, detail: str):
        """发布 agent.status.changed 事件到 NATS"""
        payload = StatusDetail(
            agent_id=self.agent_id,
            req_id=req_id,
            status=status,
            message=detail,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        subject = f"agent.status.changed.{self.agent_id}"
        await self.nc.publish(subject, payload.model_dump_json().encode())
        logger.info(f"[{self.agent_id}] Status -> {status}: {detail}")

    async def report_artifact(self, req_id: str, artifact_type: str, data: dict):
        """发布 artifact.produced 事件到 NATS"""
        payload = ArtifactRecord(
            agent_id=self.agent_id,
            req_id=req_id,
            artifact_type=artifact_type,
            data=data,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        subject = f"artifact.produced.{self.agent_id}"
        await self.nc.publish(subject, payload.model_dump_json().encode())
        logger.info(f"[{self.agent_id}] Artifact produced: {artifact_type}")


def make_temporal_activity(agent: BaseAgentWorker, activity_name: str):
    """为 Agent 创建一个 Temporal Activity 闭包，供 worker_launcher 注册"""
    @activity.defn(name=activity_name)
    async def _activity(req_id: str, context_package: dict) -> dict:
        logger.info(f"[{agent.agent_id}] Temporal Activity '{activity_name}' triggered for req={req_id}")
        await agent.report_status(req_id, "running", f"{activity_name} started")
        record_agent_start(agent.agent_id, req_id)
        try:
            result = await agent.execute(req_id, context_package)
            await agent.report_status(req_id, "completed", f"{activity_name} finished")
            record_agent_end(agent.agent_id, req_id, "completed")
            return result
        except Exception as e:
            await agent.report_status(req_id, "failed", str(e))
            record_agent_end(agent.agent_id, req_id, "failed")
            raise
    return _activity
