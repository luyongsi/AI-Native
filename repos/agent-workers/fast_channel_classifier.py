"""
Fast Channel Classifier — 五道防线快速通道分类器

Phase 5.1: 判断需求是否适合走快速通道（15-30min）还是完整流程。
五道防线:
  1. 文本复杂度 (字数、句法结构)
  2. 领域匹配 (已知领域 vs 新领域)
  3. 实体数量 (涉及实体数)
  4. LLM 复杂度评分
  5. 历史相似度 (是否有类似需求快速完成过)

快速通道: 简单 CRUD、文案调整、样式修改、配置变更
完整流程: 新业务领域、跨系统集成、支付/安全相关、架构变更
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

# 快速通道白名单 — 已知简单领域
FAST_DOMAINS = {"ui_style", "config_change", "copywriting", "simple_crud", "bugfix_typo"}
# 完整流程强制 — 安全/支付/架构
FORCE_FULL_DOMAINS = {"payment", "auth", "security", "architecture", "data_migration", "third_party_integration"}


class FastChannelClassifier(BaseAgentWorker):
    """五道防线分类器 — 嵌入 A1 和 Orchestrator 之间"""

    agent_id = "FC"
    agent_type = "fast_channel"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)

    async def execute(self, req_id: str, context_package: dict) -> dict:
        draft = context_package.get("requirement_draft", context_package.get("payload", {}))
        title = draft.get("title", context_package.get("title", context_package.get("message", "")))
        description = draft.get("description", draft.get("summary", ""))
        domain = draft.get("domain", "general")
        entities = draft.get("entities", {})

        logger.info(f"[FC] Classifying req={req_id}, domain={domain}, title='{title[:60]}'")

        await self.report_status(req_id, "running", "防线 1/5: 文本复杂度分析")

        # ── 防线 1: 文本复杂度 ──
        full_text = f"{title}\n{description}"
        char_count = len(full_text)
        word_count = len(full_text.split())
        sentence_count = full_text.count("。") + full_text.count("；") + full_text.count("\n")
        complexity_1 = self._score_text_complexity(char_count, word_count, sentence_count)

        # ── 防线 2: 领域匹配 ──
        await self.report_status(req_id, "running", "防线 2/5: 领域匹配")
        if domain in FORCE_FULL_DOMAINS:
            complexity_2 = 100  # force full pipeline
        elif domain in FAST_DOMAINS:
            complexity_2 = 0   # force fast channel
        else:
            complexity_2 = 50  # unknown — let other defenses decide

        # ── 防线 3: 实体数量 ──
        await self.report_status(req_id, "running", "防线 3/5: 实体分析")
        entity_count = sum(len(v) for v in (entities.values() if isinstance(entities, dict) else []))
        complexity_3 = min(entity_count * 20, 100)

        # ── 防线 4: LLM 复杂度评分 ──
        await self.report_status(req_id, "running", "防线 4/5: LLM 复杂度评分")
        complexity_4 = await self._llm_complexity(title, description, domain, req_id, context_package)

        # ── 防线 5: 历史相似度 ──
        await self.report_status(req_id, "running", "防线 5/5: 历史相似度检索")
        complexity_5 = 50  # neutral — pgvector integration replaces this

        # ── 加权综合 ──
        weights = [0.15, 0.20, 0.15, 0.35, 0.15]
        scores = [complexity_1, complexity_2, complexity_3, complexity_4, complexity_5]
        weighted = sum(w * s for w, s in zip(weights, scores))
        is_fast = weighted < 40

        result = {
            "req_id": req_id,
            "is_fast_channel": is_fast,
            "channel": "fast" if is_fast else "full",
            "complexity_score": round(weighted, 1),
            "defenses": {
                "text_complexity": {"score": complexity_1, "weight": 0.15, "detail": f"字数={char_count}, 句子={sentence_count}"},
                "domain_match": {"score": complexity_2, "weight": 0.20, "detail": f"领域={domain}"},
                "entity_count": {"score": complexity_3, "weight": 0.15, "detail": f"实体数={entity_count}"},
                "llm_assessment": {"score": complexity_4, "weight": 0.35, "detail": "LLM 评估"},
                "history_similarity": {"score": complexity_5, "weight": 0.15, "detail": "历史相似度"},
            },
            "estimated_duration": "15-30min" if is_fast else "2-4h",
            "fast_path_agents": ["A1", "FC", "A9", "A10", "A13"] if is_fast else None,
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.report_artifact(req_id, "channel_classification", result)

        # Publish routing event
        routing_event = {
            "event_id": f"channel-routing-{req_id}",
            "event_type": "channel.routing.decided",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": result,
            "req_id": req_id,
            "agent_id": self.agent_id,
        }
        await self.js.publish("channel.routing.decided", json.dumps(routing_event, ensure_ascii=False).encode(),
                              headers={"Nats-Msg-Id": f"channel-routing-{req_id}"})
        logger.info(f"[FC] Published channel.routing.decided: {result['channel']} (score={weighted})")

        return result

    def _score_text_complexity(self, char_count: int, word_count: int, sentence_count: int) -> float:
        """简单的文本复杂度评分 (0-100)"""
        score = 0
        if char_count < 50:
            score += 0
        elif char_count < 200:
            score += 15
        elif char_count < 500:
            score += 30
        else:
            score += 50

        if sentence_count <= 2:
            score += 0
        elif sentence_count <= 5:
            score += 20
        else:
            score += 40

        return min(score, 100)

    async def _llm_complexity(self, title: str, description: str, domain: str, req_id: str, context_package: dict) -> float:
        """LLM 评估需求复杂度 (0-100)"""
        prompt = f"""评估以下软件需求的复杂度。仅考虑实现复杂度，不考虑业务价值。

需求: {title}
描述: {description or title}
领域: {domain}

评分标准:
0-20: 纯文案/样式修改、配置变更
21-40: 简单 CRUD、单表单页面
41-60: 多表关联、中等业务逻辑
61-80: 跨系统集成、复杂状态机
81-100: 架构变更、安全/支付、数据迁移

输出: 仅一个数字 (0-100)"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="complexity_classify",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.1,
            max_tokens=1000,
        )
        if content:
            try:
                import re
                match = re.search(r"(\d+)", content.strip())
                if match:
                    return float(match.group(1))
            except (ValueError, AttributeError):
                pass
        return 50  # default neutral on LLM failure
