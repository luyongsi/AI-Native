"""
A1 Analyzer — DraftBuilder: LLM streaming requirement draft builder.

Streams LLM output, parses complete JSON objects from the buffer,
and yields full requirement_draft dicts each time a parse succeeds.
"""
import json
import logging
import os
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")

SYSTEM_PROMPT_TEMPLATE = """你是一个资深需求分析师，帮助用户把模糊的想法澄清为结构化的需求文档。

## 核心原则 — 对话引导模式

你要像一个耐心的分析师一样，逐步引导用户说清楚需求。不要一次性输出完整的最终文档。

### 行为规则

1. **第一轮对话（用户初次表达需求）**:
   - 先做简要总结（1-2句话），确认你理解了用户的核心意图。
   - 然后输出一个**不完整的草案**，只填你有把握的部分。
   - 接着提出 2-3 个具体的、引导性的问题，帮助用户补充信息。
   - 问题必须是选择题式的，给出 2-3 个明确选项，让用户容易回答。
   - 示例："您需要支持哪些登录方式？A) 仅用户名密码 B) 用户名密码 + 手机验证码 C) 还要支持第三方登录（微信/支付宝等）"

2. **后续对话**:
   - 根据用户的回答逐步完善草案。
   - 每次完善后，继续提 1-2 个跟进问题。
   - 当信息足够充分时（>=3 个实体、>=3 个用例、>=5 条验收标准），输出较完整草案并明确告诉用户"可以确认了"。

3. **收敛时机**:
   - 当字段覆盖度 >= 70%（entities、use_cases、acceptance_criteria 都基本齐全），主动告诉用户可以确认。
   - 不要追求完美再结束，有合理推断的地方直接填上合理值，让用户修正。

4. **中文输出**: 所有文本用中文，提问友好自然，像在和一个同事讨论。

## 输出结构（严格 JSON，不要 markdown 代码块包裹）

{
  "mode": "clarify",
  "summary": "一句话总结当前理解（必填，你理解了什么）",
  "questions": [
    {"question": "引导性选择问题", "options": ["选项A", "选项B", "选项C"], "field": "对应 draft 字段名"}
  ],
  "title": "需求标题（<=50字）",
  "description": "需求概述（2-5句话）",
  "domain": "领域枚举值之一",
  "entities": [
    {
      "name": "实体名称",
      "attributes": ["属性1", "属性2"],
      "description": "实体的一句话描述"
    }
  ],
  "use_cases": ["用户故事或用例描述"],
  "acceptance_criteria": ["Given <前置> When <操作> Then <结果>"],
  "constraints": ["技术约束、业务约束、合规要求"],
  "risks": ["可能的风险点和缓解思路"],
  "estimated_cost": "工时/成本估算（如无信息则为 null）"
}

### mode 字段说明
- "clarify": 草案还不完善，需要用户提供更多信息。questions 数组必须填 2-3 个选择题。
- "draft": 草案基本完善，可以审阅。questions 数组填 0-1 个最终确认问题。
- "ready": 草案已经完成，可以确认。questions 数组为空，所有字段完整。

### 领域枚举
user_management | order_management | payment | product_catalog | inventory | auth | notification | reporting | approval | general

### 字段指南
- title: <=50字
- entities: 每个实体列出 3-8 个关键属性
- use_cases: 覆盖正常流程和异常流程
- acceptance_criteria: GWT 格式，每条可独立验证
- constraints: 技术限制、业务规则、合规要求
- risks: 可能的风险和对应的缓解思路
- estimated_cost: 如有足够信息则给出人月估算，否则为 null

## 知识库参考
__KNOWLEDGE_CONTEXT__

## 当前草案（多轮对话时）
__CURRENT_DRAFT__

## 对话历史
__HISTORY__

## 用户最新输入
__USER_MESSAGE__

请输出 JSON。只输出 JSON，不要 markdown 代码块包裹，不要任何解释文字。"""


class DraftBuilder:
    """LLM streaming requirement draft builder."""

    def __init__(self):
        self.model = DEEPSEEK_MODEL
        self.base_url = DEEPSEEK_BASE_URL
        self.api_key = DEEPSEEK_API_KEY

    async def stream_analyze(
        self, user_message: str, ctx: dict,
    ) -> AsyncGenerator[dict, None]:
        """Stream LLM analysis, yielding complete requirement_draft dicts.

        ctx = {
            "history": [dialogue_messages dicts ...],
            "current_draft": requirement_draft | None,
            "knowledge": {"similar_requirements": [...], ...},
            "cycle": 0,
            "user_message": "用户最新输入",
        }
        """
        system_prompt = self._build_system_prompt(ctx)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        buffer = ""
        last_valid_draft = ctx.get("current_draft") or {}
        has_yielded = False

        async for text_chunk in self._stream_llm(messages):
            buffer += text_chunk

            while True:
                draft, consumed = self._try_parse_json(buffer)
                if draft is not None:
                    last_valid_draft = draft
                    has_yielded = True
                    yield draft
                    buffer = buffer[consumed:]
                else:
                    break

        if not has_yielded:
            yield last_valid_draft

    # ------------------------------------------------------------------
    def _build_system_prompt(self, ctx: dict) -> str:
        knowledge_text = self._format_knowledge_context(ctx.get("knowledge", {}))
        current_draft = ctx.get("current_draft")
        draft_text = (
            json.dumps(current_draft, ensure_ascii=False, indent=2)
            if current_draft
            else "尚无"
        )
        history_text = self._format_history(ctx.get("history", []))

        return (
            SYSTEM_PROMPT_TEMPLATE.replace("__KNOWLEDGE_CONTEXT__", knowledge_text)
            .replace("__CURRENT_DRAFT__", draft_text)
            .replace("__HISTORY__", history_text)
            .replace("__USER_MESSAGE__", ctx.get("user_message", ""))
        )

    @staticmethod
    def _format_knowledge_context(knowledge: dict) -> str:
        parts = []

        similar = knowledge.get("similar_requirements", [])
        if similar:
            items = "\n".join(
                "  • [{sim:.0%}] {title}".format(
                    sim=r.get("similarity", 0), title=r.get("title", "")[:100],
                )
                for r in similar[:5]
            )
            parts.append("相似历史需求:\n" + items)

        risks = knowledge.get("domain_risks", [])
        if risks:
            items = "\n".join(
                "  • [{sev}] {risk}: {desc}".format(
                    sev=r.get("severity", "?"), risk=r.get("risk", ""),
                    desc=r.get("description", ""),
                )
                for r in risks
            )
            parts.append("领域常见风险:\n" + items)

        tech = knowledge.get("tech_stack", {})
        if tech:
            items = "\n".join(
                "  • {k}: {v}".format(k=k, v=v) for k, v in tech.items()
            )
            parts.append("推荐技术栈:\n" + items)

        cost = knowledge.get("cost_baseline")
        if cost:
            parts.append(
                "成本基线:\n  • 预估工时: {effort} 人月, 团队规模: {size} 人".format(
                    effort=cost.get("estimated_effort_months", "N/A"),
                    size=cost.get("team_size", "N/A"),
                )
            )

        return "\n\n".join(parts) if parts else "无可用的历史参考数据"

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        if not history:
            return "（无对话历史）"
        lines = []
        for msg in history:
            role_label = {"human": "用户", "ai": "AI助手", "system": "系统通知"}.get(
                msg.get("role", ""), msg.get("role", ""),
            )
            content = msg.get("content", {})
            if isinstance(content, dict):
                text = content.get("text", json.dumps(content, ensure_ascii=False))
            else:
                text = str(content)
            lines.append("{role}: {text}".format(role=role_label, text=text[:500]))
        return "\n".join(lines[-20:])

    @staticmethod
    def _try_parse_json(buffer: str) -> tuple[dict | None, int]:
        """Attempt to extract a complete JSON object from buffer.

        Uses bracket-depth counting to detect closure.

        Returns:
            (parsed_dict, consumed_length) — consumed_length > 0 on success
            (None, 0) — no complete JSON yet
        """
        start = buffer.find("{")
        if start == -1:
            return None, 0

        depth = 0
        in_string = False
        escape = False

        for i, ch in enumerate(buffer):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    json_str = buffer[: i + 1]
                    clean_json = json_str[start:]
                    try:
                        parsed = json.loads(clean_json)
                    except json.JSONDecodeError:
                        return None, 0
                    if not isinstance(parsed, dict):
                        return None, 0

                    # Check for array wrapper: reject if [ precedes the first {
                    prefix = buffer[:start]
                    if prefix.rstrip() and prefix.rstrip()[-1] == "[":
                        return None, 0

                    return parsed, i + 1
        return None, 0

    # ------------------------------------------------------------------
    async def _stream_llm(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """Call DeepSeek streaming API, yielding text chunks."""
        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY not set — cannot call LLM")
            return

        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=10.0),
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 4096,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as e:
            logger.exception("LLM streaming failed")
            raise
