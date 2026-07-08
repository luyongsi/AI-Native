"""
A1: Requirement Intake Agent (需求引导)

Real LLM: 调用 DeepSeek API 提取意图、实体，生成需求草案
Fallback: 关键词匹配（当 LLM 不可用时）
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import logging
from datetime import datetime, timezone

from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

# Fallback 关键词映射
DOMAIN_KEYWORDS = {
    "下单": "order_management", "订单": "order_management",
    "支付": "payment", "退款": "refund",
    "用户": "user_management", "登录": "auth",
    "商品": "product_catalog", "库存": "inventory",
    "物流": "logistics", "通知": "notification",
    "报表": "reporting", "审批": "approval",
}

ENTITY_PATTERNS = {
    "user_role": re.compile(r"(管理员|普通用户|审核员|操作员|游客)"),
    "entity_name": re.compile(r"([一-龥]{2,10}(?:单|表|记录|信息|档案|台账|日志|工单))"),
    "quantity": re.compile(r"(\d+[个条笔次件份张])"),
    "deadline": re.compile(r"(\d+[天周月]|明天|后天|下周|今天)"),
}


class A1RequirementIntake(BaseAgentWorker):
    agent_id = "A1"
    agent_type = "requirement_intake"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)

    async def execute(self, req_id: str, context_package: dict) -> dict:
        # A1 receives context_package from the NATS dispatch payload.
        # Priority: message → title+description → requirement_draft field
        raw_message = context_package.get("message", "")
        if not raw_message:
            raw_message = context_package.get("msg_received", {}).get("text", "")
        if not raw_message:
            title = context_package.get("title", "")
            description = context_package.get("description", "")
            if description:
                raw_message = f"{title}: {description}" if title else description
            else:
                raw_message = title
        if not raw_message:
            # Last resort: requirement_draft from build_context passthrough
            rd = context_package.get("requirement_draft", {})
            if isinstance(rd, dict):
                t = rd.get("title", "")
                d = rd.get("description", rd.get("summary", ""))
                if d:
                    raw_message = f"{t}: {d}" if t else d
                else:
                    raw_message = t

        logger.info(f"[A1] Processing req={req_id}, message='{raw_message[:100]}...'")

        # Phase 1: 尝试 LLM 分析
        await self.report_status(req_id, "running", "Phase 1: LLM 需求分析")
        llm_result = await self._analyze_with_llm(raw_message, req_id, context_package.get("workflow_id", ""))

        if llm_result:
            logger.info("[A1] Using LLM-generated analysis")
            draft = llm_result
        else:
            logger.info("[A1] LLM unavailable, falling back to keyword matching")
            domain = self._detect_domain(raw_message)
            entities = self._extract_entities(raw_message)
            draft = self._build_mock_draft(raw_message, domain, entities)

        # Phase 2: 发布 artifact
        await self.report_status(req_id, "running", "Phase 2: 发布需求草案")
        await self.report_artifact(req_id, "requirement_draft", draft)

        return {
            "status": "completed",
            "domain": draft.get("domain", ""),
            "entities": draft.get("entities", {}),
            "requirement_draft": draft,
            "source": "llm" if llm_result else "keyword_fallback",
        }

    async def _analyze_with_llm(self, message: str, req_id: str = "", workflow_id: str = "") -> dict | None:
        """使用 DeepSeek LLM 分析需求并生成结构化草案"""
        system_prompt = """你是一个需求分析师。分析用户的需求描述，输出 JSON 格式的结构化需求草案。

输出格式（严格 JSON）：
{
  "title": "简短的需求标题（15字以内）",
  "domain": "order_management|payment|user_management|product_catalog|inventory|auth|notification|reporting|general",
  "summary": "一段话概括需求（50字以内）",
  "entities": {"user_role": ["角色1"], "entity_name": ["实体1"], "deadline": ["时间"]},
  "acceptance_criteria": ["验收条件1", "验收条件2", "验收条件3"],
  "tech_stack_suggestion": {"backend": "建议后端方案", "frontend": "建议前端方案", "database": "建议数据库"},
  "risk_points": ["风险点1"],
  "priority_suggestion": "P0|P1|P2|P3"
}

只输出 JSON，不要其他内容。"""

        content = await self.call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
            task_type="requirement_analysis",
            req_id=req_id,
            workflow_id=workflow_id,
            temperature=0.3,
            max_tokens=2000,
        )

        if not content:
            return None

        # Parse JSON from LLM response
        try:
            # Strip markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"[A1] Failed to parse LLM JSON: {e}, content={content[:200]}")
            return None

    # ---- Fallback methods ----
    def _detect_domain(self, message: str) -> str:
        for keyword, domain in DOMAIN_KEYWORDS.items():
            if keyword in message:
                return domain
        return "general"

    def _extract_entities(self, message: str) -> dict:
        result = {}
        for entity_type, pattern in ENTITY_PATTERNS.items():
            matches = pattern.findall(message)
            if matches:
                result[entity_type] = matches
        return result

    def _build_mock_draft(self, raw: str, domain: str, entities: dict) -> dict:
        return {
            "title": f"[Mock] {raw[:40]}",
            "domain": domain,
            "entities": entities,
            "acceptance_criteria": [
                "用户应能通过 UI 完成操作",
                "系统应处理异常并给出明确提示",
                "操作结果应记录审计日志",
            ],
            "priority_suggestion": "P2",
            "status": "draft",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "mock_fallback",
        }
