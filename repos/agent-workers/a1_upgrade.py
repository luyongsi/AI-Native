"""
A1: Requirement Intake Agent (需求引导)

升级版：支持 NATS 事件订阅 msg_received + 飞书 Bot 集成

控制流：
  飞书 webhook → NATS msg_received → A1 订阅处理 → 关键词匹配 → requirement.drafted
"""

import json
import asyncio
import os
import sys
import re
import logging
from datetime import datetime, timezone
from typing import Optional

import nats

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("A1")

# ---------------------------------------------------------------------------
# 关键词匹配（模拟 NLP）
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS = {
    "下单": "order_management",
    "订单": "order_management",
    "导出": "order_management",
    "支付": "payment",
    "退款": "refund",
    "用户": "user_management",
    "登录": "auth",
    "商品": "product_catalog",
    "库存": "inventory",
    "物流": "logistics",
    "通知": "notification",
    "报表": "reporting",
    "审批": "approval",
    "权限": "security",
}

INTENT_KEYWORDS = {
    "导出": "feature_request",
    "下载": "feature_request",
    "新增": "feature_request",
    "添加": "feature_request",
    "修改": "change_request",
    "改成": "change_request",
    "颜色": "ui_change",
    "风格": "ui_change",
    "布局": "ui_change",
    "按钮": "ui_change",
    "权限": "security_requirement",
    "审批": "security_requirement",
    "审计": "security_requirement",
    "安全": "security_requirement",
    "登录": "auth_requirement",
    "注册": "auth_requirement",
    "密码": "auth_requirement",
}

ENTITY_PATTERNS = {
    "user_role": re.compile(r"(管理员|普通用户|审核员|操作员|游客)"),
    "entity_name": re.compile(r"([一-龥]{2,10}(?:页|单|表|记录|信息|档案|台账|日志|工单))"),
    "quantity": re.compile(r"(\d+[个条笔次件份张])"),
    "deadline": re.compile(r"(\d+[天周月]|明天|后天|下周|今天)"),
}


def detect_intent(message: str) -> str:
    """简单关键词匹配推断意图类型"""
    for keyword, intent in INTENT_KEYWORDS.items():
        if keyword in message:
            return intent
    return "general_inquiry"


def detect_domain(message: str) -> str:
    """关键词匹配推断业务领域"""
    for keyword, domain in DOMAIN_KEYWORDS.items():
        if keyword in message:
            return domain
    return "general"


def extract_entities(message: str) -> dict:
    """正则提取实体"""
    result = {}
    for entity_type, pattern in ENTITY_PATTERNS.items():
        matches = pattern.findall(message)
        if matches:
            result[entity_type] = matches
    return result


# ---------------------------------------------------------------------------
# A1 Agent — NATS 事件驱动版本
# ---------------------------------------------------------------------------

class A1RequirementIntake:
    """A1 Agent：订阅 NATS msg_received，处理后发布 requirement.drafted"""

    agent_id = "A1"
    agent_type = "requirement_intake"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc: Optional[nats.NATS] = None
        self._running = False

    async def init(self):
        """连接 NATS"""
        self.nc = await nats.connect(self.nats_url)
        logger.info("[A1] Connected to NATS at %s", self.nats_url)
        return self

    async def close(self):
        """关闭连接"""
        self._running = False
        if self.nc:
            await self.nc.drain()
            logger.info("[A1] NATS connection closed")

    # ------------------------------------------------------------------
    # msg_received 事件处理
    # ------------------------------------------------------------------
    async def on_msg_received(self, msg):
        """处理 msg_received NATS 事件"""
        try:
            body = json.loads(msg.data.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning("[A1] Failed to decode msg_received payload")
            return

        payload = body.get("payload", {})
        text = payload.get("text", "")
        source = payload.get("source", "unknown")
        chat_id = payload.get("chat_id", "")
        sender_id = payload.get("sender_id", "")

        if not text:
            logger.warning("[A1] msg_received has no text, skipping")
            return

        req_id = payload.get("event_id", os.urandom(8).hex())
        logger.info("[A1] Received from %s/%s: %s", source, sender_id, text[:80])

        # Step 1: 关键词匹配推断意图
        intent = detect_intent(text)
        domain = detect_domain(text)
        entities = extract_entities(text)

        logger.info(
            "[A1] Intent: %s | Domain: %s | Entities: %s",
            intent, domain, json.dumps(entities, ensure_ascii=False),
        )

        # Step 2: 构建需求草案
        draft = {
            "req_id": req_id,
            "source": source,
            "chat_id": chat_id,
            "sender_id": sender_id,
            "raw_message": text,
            "intent": intent,
            "domain": domain,
            "entities": entities,
            "status": "draft",
            "title": f"[需求草案] {text[:50]}",
            "ac_boilerplate": [
                "用户应能通过 UI 完成操作",
                "系统应处理异常并给出明确提示",
                "操作结果应记录审计日志",
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Step 3: 发布 requirement.drafted
        await self._publish_requirement_drafted(req_id, draft)

        # Step 4: 发布 agent.status.changed
        await self._publish_status(req_id, "completed", f"Intent={intent}, Domain={domain}")

        logger.info("[A1] Requirement drafted: req_id=%s, intent=%s", req_id, intent)

    async def _publish_requirement_drafted(self, req_id: str, draft: dict):
        """发布 requirement.drafted 事件"""
        event = {
            "event_id": os.urandom(8).hex(),
            "event_type": "requirement.drafted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": self.agent_id,
            "req_id": req_id,
            "payload": draft,
        }
        await self.nc.publish(
            "requirement.drafted",
            json.dumps(event, ensure_ascii=False).encode("utf-8"),
        )
        logger.info("[A1] Published requirement.drafted for req_id=%s", req_id)

    async def _publish_status(self, req_id: str, status: str, detail: str):
        """发布 agent.status.changed 事件"""
        event = {
            "event_id": os.urandom(8).hex(),
            "event_type": "agent.status.changed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": self.agent_id,
            "req_id": req_id,
            "status": status,
            "message": detail,
        }
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        await self.nc.publish(f"agent.status.changed.{self.agent_id}", payload)
        logger.info("[A1] Status -> %s: %s", status, detail)

    # ------------------------------------------------------------------
    # 运行主循环
    # ------------------------------------------------------------------
    async def run(self):
        """
        启动 NATS 订阅并进入主循环。
        订阅 msg_received 主题，所有飞书消息通过此通道进入。
        """
        await self.init()
        self._running = True

        # 订阅 msg_received
        sub = await self.nc.subscribe("msg_received", cb=self.on_msg_received)
        logger.info("[A1] Subscribed to msg_received. Waiting for messages...")

        try:
            while self._running:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("[A1] Cancelled, shutting down...")
        finally:
            await sub.unsubscribe()
            await self.close()

    async def run_forever(self):
        """Wrapper that handles graceful shutdown"""
        try:
            await self.run()
        except KeyboardInterrupt:
            logger.info("[A1] KeyboardInterrupt, shutting down...")
            await self.close()


# ---------------------------------------------------------------------------
# Standalone: 从命令行启动独立的 A1 Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
    agent = A1RequirementIntake(nats_url=nats_url)
    asyncio.run(agent.run_forever())
