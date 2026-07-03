"""
base_worker.py — Agent Worker 基类

所有 Agent (A1-A13, K14-K15, FC) 共用此运行时基类。
提供 NATS 连接、Temporal Activity 注册、状态上报、产物上报。

Phase 5.3: 集成 mc_observability — 自动记录 agent 执行耗时、状态、LLM 调用。
Phase 5.4: 集成 OpenTelemetry — 分布式追踪到 Jaeger。
Phase 5.5: SSE Activity Streaming — 集成 ActivityRecorder 进行实时事件推送。
"""
import asyncio
import json
import logging
import os
import threading
import time as _time_module
import uuid
from datetime import datetime, timezone
from typing import Optional

import nats
from temporalio import activity, workflow
from pydantic import BaseModel

# Lazy import OpenTelemetry — falls back gracefully if not available
try:
    from opentelemetry import trace
    from opentelemetry.trace import Span, Status, StatusCode
    _HAS_OTEL_IMPORT = True
except ImportError:
    _HAS_OTEL_IMPORT = False
    trace = None
    Span = None
    Status = None
    StatusCode = None

logger = logging.getLogger(__name__)

# Lazy import activity recorder — falls back gracefully if not available
try:
    from activity_recorder import ActivityRecorder
    _HAS_ACTIVITY_RECORDER = True
except ImportError:
    _HAS_ACTIVITY_RECORDER = False
    ActivityRecorder = None

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

# Lazy import OpenTelemetry config — falls back gracefully if not available
try:
    from infra.observability.otel_config import init_tracer, get_tracer
    from infra.observability.span_attributes import (
        add_request_context, add_agent_context, add_llm_context,
        record_error_event, set_span_success, add_nats_context, ATTR_REQ_ID
    )
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False
    def init_tracer(name, **kwargs): return None
    def get_tracer(name): return None
    def add_request_context(span, **kwargs): pass
    def add_agent_context(span, **kwargs): pass
    def add_llm_context(span, **kwargs): pass
    def record_error_event(span, exc): pass
    def set_span_success(span): pass
    def add_nats_context(span, **kwargs): pass
    ATTR_REQ_ID = "req_id"


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

    # ── Class-level shared LLM provider ──────────────────────────────
    _shared_llm: object = None
    _shared_llm_lock = threading.Lock()

    def __init__(self, agent_id: str, agent_type: str, nats_url: str = "nats://localhost:4222"):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.nats_url = nats_url
        self.nc = None          # NATS connection
        self.js = None          # JetStream context
        self.tracer: Optional[trace.Tracer] = None if not _HAS_OTEL_IMPORT else None  # OpenTelemetry tracer
        self._current_span: Optional[Span] = None   # Current active span for context
        self.activity_recorder: Optional[ActivityRecorder] = None  # Activity recorder for SSE streaming
        self._processed_ids: set = set()  # Dedup: event_ids processed in last 5 min
        self._llm: object = None  # LLMProviderManager instance (shared across agents)

    async def init(self):
        """连接 NATS，初始化 JetStream、OpenTelemetry 和 ActivityRecorder"""
        logger.info(f"[{self.agent_id}] Initializing {self.agent_type} worker...")
        self.nc = await nats.connect(self.nats_url)
        self.js = self.nc.jetstream()
        logger.info(f"[{self.agent_id}] Connected to NATS at {self.nats_url}")

        # Initialize shared LLM provider manager (lazy, first agent to init)
        self._init_llm()

        # Initialize ActivityRecorder for SSE streaming
        if _HAS_ACTIVITY_RECORDER and ActivityRecorder:
            try:
                self.activity_recorder = ActivityRecorder(self.nc, self.js, self.agent_id)
                logger.info(f"[{self.agent_id}] ActivityRecorder initialized for SSE streaming")
            except Exception as e:
                logger.warning(f"[{self.agent_id}] Failed to initialize ActivityRecorder: {e}")
                self.activity_recorder = None

        # Initialize OpenTelemetry tracer
        if _HAS_OTEL:
            try:
                service_name = f"agent-{self.agent_id}"
                self.tracer = init_tracer(service_name, environment="dev")
                logger.info(f"[{self.agent_id}] OpenTelemetry tracer initialized: {service_name}")
            except Exception as e:
                logger.warning(f"[{self.agent_id}] Failed to initialize OpenTelemetry: {e}")
                self.tracer = None

    async def close(self):
        """关闭连接"""
        if self.nc:
            await self.nc.drain()
            logger.info(f"[{self.agent_id}] NATS connection closed")

    def _init_llm(self):
        """Initialize the LLM provider manager — shared across all agent instances.

        Uses a class-level lock to ensure only one LLMProviderManager is
        created. All agents share the same httpx connection pool and auditor.
        """
        if BaseAgentWorker._shared_llm is not None:
            self._llm = BaseAgentWorker._shared_llm
            return

        with BaseAgentWorker._shared_llm_lock:
            if BaseAgentWorker._shared_llm is not None:
                self._llm = BaseAgentWorker._shared_llm
                return

            try:
                from llm_provider.audit import get_auditor
                from llm_provider.manager import LLMProviderManager
                from llm_provider.deepseek_adapter import DeepSeekAdapter
                from llm_provider.context import LLMCallContext
            except ImportError as e:
                logger.warning(
                    "[%s] llm_provider not available, LLM calls will fail: %s",
                    self.agent_id, e,
                )
                return

            auditor = get_auditor(outputs=["file", "stdout"])
            adapter = DeepSeekAdapter(
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn"),
                model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606"),
            )
            manager = LLMProviderManager(
                adapters={"deepseek": adapter},
                default_routes={
                    "text": "deepseek",
                    "requirement_analysis": "deepseek",
                    "knowledge_analysis": "deepseek",
                    "ui_prototype": "deepseek",
                    "openapi_gen": "deepseek",
                    "erd_gen": "deepseek",
                    "design_review": "deepseek",
                    "task_decomposition": "deepseek",
                    "test_case_gen": "deepseek",
                    "architecture_review": "deepseek",
                    "code_generation": "deepseek",
                    "test_execution": "deepseek",
                    "code_review": "deepseek",
                    "complexity_classify": "deepseek",
                },
                auditor=auditor,
            )
            BaseAgentWorker._shared_llm = manager
            self._llm = manager
            logger.info(
                "[%s] LLM provider initialized (shared DeepSeekAdapter)",
                self.agent_id,
            )

    async def call_llm(
        self,
        messages: list,
        *,
        task_type: str = "text",
        temperature: float = 0.3,
        max_tokens: int = 2000,
        req_id: str = "",
        workflow_id: str = "",
    ) -> str | None:
        """Unified LLM call entry point — replaces all per-agent _call_llm methods.

        Uses asyncio.to_thread to run the synchronous llm-provider in a
        thread-pool, avoiding event-loop blockage. Audit logging happens
        automatically inside the provider layer.
        """
        if self._llm is None:
            self._init_llm()

        if self._llm is None:
            logger.error("[%s] LLM provider not initialized", self.agent_id)
            return None

        from llm_provider.context import LLMCallContext

        ctx = LLMCallContext(
            agent_id=self.agent_id,
            req_id=req_id or "",
            workflow_id=workflow_id or "",
            task_type=task_type,
        )

        try:
            result = await asyncio.to_thread(
                self._llm.chat,
                messages=messages,
                task_type=task_type,
                temperature=temperature,
                max_tokens=max_tokens,
                ctx=ctx,
            )
            return result.content
        except Exception as e:
            logger.error("[%s] LLM call failed: %s", self.agent_id, e)
            return None

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """子类重写此方法 — 执行 Agent 核心逻辑"""
        raise NotImplementedError

    async def subscribe_nats(self, subject: str = "", extra_subjects: list[str] | None = None):
        """Subscribe to NATS subjects and handle messages.

        When a message arrives on the subscribed subject, parse it as a dispatch
        envelope, call self.execute(), and publish results back.
        Ack is sent BEFORE execute() to prevent JetStream redelivery.
        Dedup via event_id set (5-minute rolling window).
        """
        import time as _time

        async def _handle(msg):
            try:
                data = json.loads(msg.data.decode())

                event_id = data.get("event_id", "")
                # Dedup check — use set of (event_id, timestamp) tuples
                if event_id and any(eid == event_id for eid, _ in self._processed_ids):
                    logger.info(
                        f"[{self.agent_id}] Duplicate message {event_id}, skipping"
                    )
                    await msg.ack()
                    return

                logger.info(f"[{self.agent_id}] Received NATS message on '{msg.subject}'")
                req_id = data.get("req_id", "") or data.get("payload", {}).get("req_id", "")
                context = data.get("payload", {})
                context["event_type"] = data.get("event_type", "")
                context["workflow_id"] = data.get("payload", {}).get("workflow_id", "")

                # ── Ack BEFORE execute (prevents JetStream redelivery) ──
                await msg.ack()

                # Register as processed with time-based eviction
                if event_id:
                    self._processed_ids.add((event_id, _time.time()))
                    # Purge entries older than 5 minutes instead of clearing all
                    cutoff = _time.time() - 300
                    self._processed_ids = {
                        (eid, ts) for eid, ts in self._processed_ids
                        if ts > cutoff
                    }

                # Create OpenTelemetry span for agent execution
                span = None
                if self.tracer:
                    span = self.tracer.start_span(
                        f"{self.agent_id}.execute",
                        attributes={
                            "agent.id": self.agent_id,
                            "agent.type": self.agent_type,
                            "nats.subject": msg.subject,
                        }
                    )
                    add_request_context(span, req_id, agent_id=self.agent_id)
                    add_nats_context(span, msg.subject, context.get("event_type"))
                    span.__enter__()

                try:
                    record_agent_start(self.agent_id, req_id)
                    result = await self.execute(req_id, context)
                    record_agent_end(self.agent_id, req_id, "completed")
                    if span:
                        set_span_success(span)
                except Exception as exec_err:
                    record_agent_end(self.agent_id, req_id, "failed")
                    if span:
                        record_error_event(span, exec_err)
                    logger.error(
                        f"[{self.agent_id}] execute() failed: {exec_err}", exc_info=True
                    )
                    return

                finally:
                    if span:
                        span.__exit__(None, None, None)

                # Publish result — include workflow_id for Bridge routing
                wf_id = context.get("workflow_id", "")
                reply_subject = f"agent.result.{self.agent_id}"
                await self.nc.publish(reply_subject, json.dumps({
                    "agent_id": self.agent_id,
                    "req_id": req_id,
                    "workflow_id": wf_id,
                    "result": result,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False, default=str).encode())
                logger.info(f"[{self.agent_id}] Published result to '{reply_subject}'")
            except Exception as e:
                logger.error(f"[{self.agent_id}] Error handling NATS message: {e}", exc_info=True)
                try:
                    await msg.ack()
                except Exception:
                    pass

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

    async def record_progress(
        self,
        req_id: str,
        step: str,
        details: Optional[str] = None,
        progress_percent: Optional[int] = None,
        metadata: Optional[dict] = None,
    ):
        """Record a progress update via ActivityRecorder (if available)."""
        if self.activity_recorder:
            try:
                await self.activity_recorder.record_progress(
                    req_id, step, details, progress_percent, metadata
                )
            except Exception as e:
                logger.warning(f"[{self.agent_id}] Failed to record progress: {e}")

    async def record_activity_status(
        self,
        req_id: str,
        status: str,
        message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """Record a status update via ActivityRecorder (if available)."""
        if self.activity_recorder:
            try:
                await self.activity_recorder.record_status(req_id, status, message, metadata)
            except Exception as e:
                logger.warning(f"[{self.agent_id}] Failed to record status: {e}")

    async def record_activity_artifact(
        self,
        req_id: str,
        artifact_type: str,
        artifact_data: dict,
        metadata: Optional[dict] = None,
    ):
        """Record an artifact via ActivityRecorder (if available)."""
        if self.activity_recorder:
            try:
                await self.activity_recorder.record_artifact(
                    req_id, artifact_type, artifact_data, metadata
                )
            except Exception as e:
                logger.warning(f"[{self.agent_id}] Failed to record artifact: {e}")


def make_temporal_activity(agent: BaseAgentWorker, activity_name: str):
    """为 Agent 创建一个 Temporal Activity 闭包，供 worker_launcher 注册"""
    @activity.defn(name=activity_name)
    async def _activity(req_id: str, context_package: dict) -> dict:
        logger.info(f"[{agent.agent_id}] Temporal Activity '{activity_name}' triggered for req={req_id}")

        # Create OpenTelemetry span for activity
        span = None
        if agent.tracer:
            span = agent.tracer.start_span(
                f"{agent.agent_id}.temporal_activity",
                attributes={
                    "agent.id": agent.agent_id,
                    "activity.name": activity_name,
                }
            )
            add_request_context(span, req_id, agent_id=agent.agent_id)
            span.__enter__()

        try:
            await agent.report_status(req_id, "running", f"{activity_name} started")
            record_agent_start(agent.agent_id, req_id)
            result = await agent.execute(req_id, context_package)
            await agent.report_status(req_id, "completed", f"{activity_name} finished")
            record_agent_end(agent.agent_id, req_id, "completed")
            if span:
                set_span_success(span)
            return result
        except Exception as e:
            await agent.report_status(req_id, "failed", str(e))
            record_agent_end(agent.agent_id, req_id, "failed")
            if span:
                record_error_event(span, e)
            raise
        finally:
            if span:
                span.__exit__(None, None, None)

    return _activity
