"""
intent_extractor.py — Intent and Entity Extraction (NLP sub-module)

Stub implementation using keyword matching. Real implementation would use
a fine-tuned BERT or an LLM (e.g. Claude) for intent classification and
named entity recognition (NER).

Contract:
    class IntentExtractor
        async extract(text: str) -> dict
        -> {intent: str, entities: list[dict], confidence: float}
"""

import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ---------- mock keyword tables ----------

INTENT_PATTERNS = {
    "create": re.compile(r"(创建|新建|添加|增加|录入|生成|造|做[一个]?)"),
    "query": re.compile(r"(查询|查看|搜索|检索|列出|展示|显示|看[一下]?)"),
    "update": re.compile(r"(修改|编辑|更新|变更|调整|改)"),
    "delete": re.compile(r"(删除|移除|去掉|清理|作废)"),
    "export": re.compile(r"(导出|下载|另存|备份)"),
    "approve": re.compile(r"(审批|通过|驳回|批准|同意|拒绝)"),
    "configure": re.compile(r"(配置|设置|参数|开关|启用|禁用)"),
}

ENTITY_PATTERNS: dict[str, re.Pattern] = {
    "role": re.compile(r"(管理员|普通用户|审核员|操作员|游客|超级管理员)"),
    "entity": re.compile(r"([一-龥]{2,10}(?:单|表|记录|信息|档案|台账|日志|工单|页面|模块))"),
    "quantity": re.compile(r"(\d+\s*[个条笔次件份张台套组次])"),
    "deadline": re.compile(r"(\d+[天周月年]|明天|后天|下周|下月|今天|本周|本月)"),
    "platform": re.compile(r"(Web|App|小程序|H5|桌面端|移动端|管理后台|门户)"),
}


class IntentExtractor:
    """Extract intent and entities from a natural-language requirement message.

    In production this would call a hosted LLM via the Anthropic SDK with tool-use
    for structured extraction.  The stub uses deterministic keyword matching so tests
    are reproducible without an API key.
    """

    def __init__(self, min_confidence: float = 0.55):
        self.min_confidence = min_confidence

    async def extract(self, text: str) -> dict:
        """Parse *text* and return structured intent + entities.

        Returns:
            dict with keys:
                intent      (str)   – primary intent label or "unknown"
                entities    (list)  – [{label, value, start, end}, ...]
                confidence  (float) – 0.0 – 1.0
        """
        logger.info("Extracting intent from text length=%d", len(text))

        intent = self._classify_intent(text)
        entities = self._extract_entities(text)
        confidence = self._compute_confidence(intent, entities)

        return {
            "intent": intent,
            "entities": entities,
            "confidence": round(confidence, 3),
        }

    # ------------------------------------------------------------------
    #  private helpers
    # ------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        """Simple keyword priority: first match wins."""
        for label, pattern in INTENT_PATTERNS.items():
            if pattern.search(text):
                logger.debug("Intent matched: %s", label)
                return label
        logger.debug("No intent keyword matched – returning 'unknown'")
        return "unknown"

    def _extract_entities(self, text: str) -> list:
        """Walk every entity pattern and collect non-overlapping matches."""
        results: list[dict] = []
        for label, pattern in ENTITY_PATTERNS.items():
            for m in pattern.finditer(text):
                results.append({
                    "label": label,
                    "value": m.group(1).strip(),
                    "start": m.start(1),
                    "end": m.end(1),
                })
        return results

    def _compute_confidence(self, intent: str, entities: list) -> float:
        """Naive confidence heuristic — real impl would use model logits."""
        if intent == "unknown":
            return 0.30
        base = 0.75
        # More entities = higher confidence (up to a point)
        bonus = min(len(entities) * 0.05, 0.15)
        return min(base + bonus, 1.0)
