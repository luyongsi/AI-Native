"""
A6: Spec Decomposer Agent (Spec 拆解 + DAG 生成)

Real LLM: 调用 DeepSeek API 分析 Spec，生成任务 DAG
Fallback: 关键词规则

触发条件:
  - context.ready.spec_decomposer (NATS from Orchestrator)
  - review.completed (NATS from A5 Design Review)
"""
from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone

from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A6"
AGENT_TYPE = "spec_decomposer"


class SpecDecomposerAgent(BaseAgentWorker):
    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)

    async def execute(self, req_id: str, context_package: dict) -> dict:
        event_type = context_package.get("event_type", "")
        spec = context_package.get("spec_package", {})
        draft = context_package.get("requirement_draft", {})
        title = draft.get("title", context_package.get("message", "未命名"))

        # If triggered by review.completed, check pass status
        if event_type == "review.completed":
            review_pass = context_package.get("pass", False)
            logger.info(f"[A6] Review pass status: {review_pass}, scores: {context_package.get('scores', {})}")
            if not review_pass:
                logger.info(f"[A6] Review NOT passed for req={req_id}, skipping decomposition. Scores: {json.dumps(context_package.get('scores', {}), ensure_ascii=False)}")
                return {"status": "skipped", "reason": "review_not_passed", "scores": context_package.get("scores", {})}
            # Extract spec data from review payload
            title = context_package.get("req_id", req_id)

        logger.info(f"[A6] Decomposing spec for req={req_id} (event={event_type})")

        await self.report_status(req_id, "running", "Phase 1: LLM 拆解任务")

        # Try LLM decomposition
        dag = await self._llm_decompose(title, spec, draft, req_id, context_package)

        if dag is None:
            await self.report_status(req_id, "running", "Fallback: 规则拆解")
            dag = self._fallback_decompose(title, spec)

        dag["dag_id"] = f"dag-{req_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        dag["created_at"] = datetime.now(timezone.utc).isoformat()

        await self.report_artifact(req_id, "dag", dag)

        await self.report_status(req_id, "completed",
                                 f"DAG 生成完成: {len(dag.get('nodes',[]))} 节点")

        return {"status": "completed", "dag": dag}

    async def _llm_decompose(self, title: str, spec: dict, draft: dict, req_id: str, context_package: dict) -> dict | None:
        """Use LLM to decompose spec into task DAG"""
        context_text = await self.prepare_llm_context(context_package, state="decomposing")
        prompt = f"""你是一个技术项目经理。将以下需求拆解为开发任务 DAG。

需求标题: {title}
{context_text}

输出严格 JSON：
{{
  "nodes": [
    {{"id": "task-01", "type": "planning|backend|frontend|db|testing|deployment", "title": "任务名称", "description": "任务描述", "complexity": "low|medium|high", "estimated_hours": 4, "agent": "A1-A13", "steps": ["步骤1"]}}
  ],
  "edges": [
    {{"from": "task-01", "to": "task-02", "type": "sequential|parallel"}}
  ],
  "critical_path": ["task-01", "task-02"],
  "parallel_groups": [{{"name": "并行组名", "tasks": ["task-03","task-04"]}}],
  "total_estimated_hours": 40
}}

规则：
- 至少 5 个任务节点
- 标注哪些任务可以并行
- 标注需要人工审核的任务（complexity=high）
- 只输出 JSON"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="task_decomposition",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.2,
            max_tokens=4000,
        )
        if not content:
            return None

        try:
            content = content.strip()
            if content.startswith("```"): content = content.split("```")[1].split("```")[0].strip()
            if content.startswith("json"): content = content[4:].strip()
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"[A6] LLM JSON parse failed: {e}")
            return None

    def _fallback_decompose(self, title: str, spec: dict) -> dict:
        """Keyword-based fallback"""
        has_backend = any(kw in str(spec) for kw in ["API", "endpoint", "backend", "/api/"])
        has_frontend = any(kw in str(spec) for kw in ["UI", "前端", "页面", "界面", "frontend", "交互"])

        nodes = [
            {"id": "task-01", "type": "planning", "title": "需求分析 & 技术方案", "complexity": "low", "estimated_hours": 2},
        ]
        idx = 2

        if has_backend or not has_frontend:
            nodes.append({"id": f"task-{idx:02d}", "type": "backend", "title": "API 接口开发", "complexity": "medium", "estimated_hours": 8}); idx += 1
            nodes.append({"id": f"task-{idx:02d}", "type": "db", "title": "数据库设计与迁移", "complexity": "medium", "estimated_hours": 4}); idx += 1
            nodes.append({"id": f"task-{idx:02d}", "type": "backend", "title": "业务逻辑层开发", "complexity": "medium", "estimated_hours": 12}); idx += 1

        if has_frontend:
            nodes.append({"id": f"task-{idx:02d}", "type": "frontend", "title": "前端页面开发", "complexity": "medium", "estimated_hours": 10}); idx += 1
            nodes.append({"id": f"task-{idx:02d}", "type": "frontend", "title": "前端交互 & 动效", "complexity": "low", "estimated_hours": 4}); idx += 1

        nodes.append({"id": f"task-{idx:02d}", "type": "testing", "title": "集成测试", "complexity": "medium", "estimated_hours": 6}); idx += 1
        nodes.append({"id": f"task-{idx:02d}", "type": "deployment", "title": "部署上线", "complexity": "low", "estimated_hours": 2})

        edges = [{"from": nodes[i]["id"], "to": nodes[i+1]["id"], "type": "sequential"} for i in range(len(nodes)-1)]

        return {
            "nodes": nodes,
            "edges": edges,
            "critical_path": [n["id"] for n in nodes],
            "total_estimated_hours": sum(n["estimated_hours"] for n in nodes),
            "source": "fallback",
        }
