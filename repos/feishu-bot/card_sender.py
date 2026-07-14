"""
card_sender.py — 飞书卡片消息发送

开发阶段：不连接真实飞书 API，改为 log 输出卡片内容 + 发 NATS bot.message.sent 事件
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

import nats

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("feishu-card-sender")

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")

_nc: Optional[nats.NATS] = None


async def get_nats() -> nats.NATS:
    global _nc
    if _nc is None or not _nc.is_connected:
        logger.info(f"Connecting to NATS at {NATS_URL} ...")
        _nc = await nats.connect(NATS_URL)
        logger.info("NATS connected.")
    return _nc


# ---------------------------------------------------------------------------
# 卡片模板构建
# ---------------------------------------------------------------------------

def _build_choice_card(question: str, options: List[str]) -> dict:
    """构建飞书交互式卡片（选项按钮）"""
    elements = []
    for i, opt in enumerate(options[:5]):
        elements.append({
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": opt,
            },
            "type": "primary" if i == 0 else "default",
            "value": {f"choice_{i}": opt},
        })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "需求确认",  # 需求确认
            }
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**{question}**\n请选择一个选项：",  # 请选择一个选项：
            },
            {
                "tag": "action",
                "actions": elements,
            },
        ],
    }
    return card


def _build_text_card(text: str) -> dict:
    """构建飞书纯文本卡片"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "AI Native 助手",  # AI Native 助手
            }
        },
        "elements": [
            {
                "tag": "markdown",
                "content": text,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def send_choice_card(chat_id: str, question: str, options: List[str]) -> dict:
    """
    发送选择卡片到飞书。

    开发阶段：
    - 打印卡片 JSON 到 log
    - 发布 bot.message.sent 事件到 NATS
    - 不调用真实飞书 API
    """
    card = _build_choice_card(question, options)
    card_json = json.dumps(card, ensure_ascii=False, indent=2)

    logger.info("-" * 60)
    logger.info(f"[CARD] Choice Card -> chat_id={chat_id}")
    logger.info(f"[CARD] Question: {question}")
    logger.info(f"[CARD] Options: {options[:5]}")
    logger.info(f"[CARD] Card JSON:\n{card_json}")
    logger.info("-" * 60)

    nc = await get_nats()
    event_payload = {
        "event_id": os.urandom(8).hex(),
        "event_type": "bot.message.sent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "chat_id": chat_id,
            "message_type": "interactive",
            "question": question,
            "options": options[:5],
            "card": card,
        },
    }
    js = nc.jetstream()
    await js.publish(
        "bot.message.sent",
        json.dumps(event_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Nats-Msg-Id": f"bot-msg-{chat_id}-{int(time.time())}"},
    )
    logger.info(f"Published bot.message.sent for chat_id={chat_id}")

    return {"status": "sent", "chat_id": chat_id, "message_type": "interactive"}


async def send_text_message(chat_id: str, text: str) -> dict:
    """
    发送纯文本消息到飞书。

    开发阶段：
    - 打印消息到 log
    - 发布 bot.message.sent 事件到 NATS
    - 不调用真实飞书 API
    """
    logger.info("-" * 60)
    logger.info(f"[TEXT] Text Message -> chat_id={chat_id}")
    logger.info(f"[TEXT] Content: {text}")
    logger.info("-" * 60)

    nc = await get_nats()
    event_payload = {
        "event_id": os.urandom(8).hex(),
        "event_type": "bot.message.sent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "chat_id": chat_id,
            "message_type": "text",
            "text": text,
        },
    }
    js = nc.jetstream()
    await js.publish(
        "bot.message.sent",
        json.dumps(event_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Nats-Msg-Id": f"bot-msg-text-{chat_id}-{int(time.time())}"},
    )
    logger.info(f"Published bot.message.sent for chat_id={chat_id}")

    return {"status": "sent", "chat_id": chat_id, "message_type": "text"}


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
async def _main():
    print("=== card_sender standalone test ===")
    await send_text_message("oc_test_chat", "你好！需求已收到，正在处理中…")
    await send_choice_card(
        "oc_test_chat",
        "这个需求涉及哪个业务领域？",
        ["订单管理", "用户管理", "支付系统", "物流追踪", "通知服务"],
    )
    if _nc:
        await _nc.drain()


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
