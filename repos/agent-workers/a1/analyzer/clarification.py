"""
A1 Analyzer — ClarificationEngine

Analyses the current requirement draft to identify ambiguous or
under-specified areas, returning a list of clarification questions
with suggested defaults.
"""
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")

CLARIFICATION_PROMPT = """你是一个需求分析师。请分析以下需求草案，找出其中模糊、缺失或需要进一步澄清的地方。

对每个待澄清点，给出：
1. 具体问题
2. 一个推荐的默认方案（最佳实践推断）
3. 该问题对应的需求草案字段路径（如 entities[0].attributes、constraints、acceptance_criteria 等）

如果没有明显的模糊点，返回空列表。

需求草案:
__DRAFT__

请只输出 JSON 数组，不要 markdown 代码块包裹，不要任何解释文字:
[{"question": "具体问题", "suggestion": "推荐方案", "field": "字段路径"}]"""


class ClarificationEngine:
    """Identifies clarification points from a requirement draft."""

    def __init__(self):
        self.model = DEEPSEEK_MODEL
        self.base_url = DEEPSEEK_BASE_URL
        self.api_key = DEEPSEEK_API_KEY

    async def identify(
        self, draft: dict, history: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Analyse the draft for ambiguities.

        Returns:
            [{"question": "...", "suggestion": "...", "field": "..."}, ...]
            Empty list if nothing needs clarification.
        """
        if not draft or not draft.get("title"):
            return []

        if not self.api_key:
            return self._heuristic_identify(draft)

        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        prompt = CLARIFICATION_PROMPT.replace("__DRAFT__", draft_text)

        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
            ) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1024,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return self._parse_response(content)

        except Exception as e:
            logger.exception("ClarificationEngine LLM call failed")
            return self._heuristic_identify(draft)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_response(content: str) -> list[dict]:
        """Parse LLM response into clarification items."""
        try:
            result = json.loads(content.strip())
            if isinstance(result, list):
                return [
                    {
                        "question": item.get("question", ""),
                        "suggestion": item.get("suggestion", ""),
                        "field": item.get("field", ""),
                    }
                    for item in result
                    if isinstance(item, dict) and item.get("question")
                ]
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code blocks
        if "```" in content:
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if match:
                try:
                    result = json.loads(match.group(1))
                    if isinstance(result, list):
                        return [
                            {
                                "question": item.get("question", ""),
                                "suggestion": item.get("suggestion", ""),
                                "field": item.get("field", ""),
                            }
                            for item in result
                            if isinstance(item, dict) and item.get("question")
                        ]
                except json.JSONDecodeError:
                    pass

        return []

    @staticmethod
    def _heuristic_identify(draft: dict) -> list[dict]:
        """Rule-based fallback when LLM is unavailable."""
        points = []

        if not draft.get("description") or len(draft.get("description", "")) < 20:
            points.append({
                "question": "需求描述较为简略，能否补充更多细节？",
                "suggestion": "描述系统的核心功能、目标用户和主要价值",
                "field": "description",
            })

        entities = draft.get("entities")
        if isinstance(entities, list) and len(entities) > 0:
            for i, entity in enumerate(entities):
                if not entity.get("attributes") or len(entity.get("attributes", [])) < 2:
                    points.append({
                        "question": f"实体 '{entity.get('name', '未知')}' 的属性较少，是否需要补充？",
                        "suggestion": f"列出{entity.get('name', '该实体')}的3-8个关键属性",
                        "field": f"entities[{i}].attributes",
                    })

        use_cases = draft.get("use_cases")
        if not isinstance(use_cases, list) or len(use_cases) < 2:
            points.append({
                "question": "用例数量较少，是否还有其他核心使用场景？",
                "suggestion": "补充边界场景和异常流程的用例",
                "field": "use_cases",
            })

        ac = draft.get("acceptance_criteria")
        if not isinstance(ac, list) or len(ac) < 2:
            points.append({
                "question": "验收标准不足，需要补充GWT格式的验收条件",
                "suggestion": "为每个核心用例补充Given-When-Then验收标准",
                "field": "acceptance_criteria",
            })

        return points
