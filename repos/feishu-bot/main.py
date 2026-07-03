"""
Feishu Bot Service — 接收飞书事件回调，通过 NATS 桥接 AI-Native 平台

端口：8400
开发阶段：FEISHU_SKIP_VERIFY=true 跳过 HMAC 签名验证
"""

import json
import hmac
import hashlib
import os
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import nats
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("feishu-bot")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
FEISHU_SKIP_VERIFY = os.environ.get("FEISHU_SKIP_VERIFY", "true").lower() == "true"
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")
BOT_PORT = int(os.environ.get("BOT_PORT", "8400"))

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="Feishu Bot Service", version="0.1.0")

# Global NATS connection (lazy init)
_nc: Optional[nats.NATS] = None


async def get_nats() -> nats.NATS:
    global _nc
    if _nc is None or not _nc.is_connected:
        logger.info(f"Connecting to NATS at {NATS_URL} ...")
        _nc = await nats.connect(NATS_URL)
        logger.info("NATS connected.")
    return _nc


# ---------------------------------------------------------------------------
# HMAC-SHA256 签名验证
# ---------------------------------------------------------------------------
def verify_signature(timestamp: str, nonce: str, body: bytes, signature: str) -> bool:
    if FEISHU_SKIP_VERIFY:
        logger.debug("Signature verification SKIPPED (FEISHU_SKIP_VERIFY=true)")
        return True
    if not FEISHU_APP_SECRET:
        logger.warning("FEISHU_APP_SECRET is empty, cannot verify signature")
        return False
    sign_string = f"{timestamp}{nonce}{body.decode('utf-8')}"
    computed = hmac.new(
        FEISHU_APP_SECRET.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    match = hmac.compare_digest(computed, signature or "")
    if not match:
        logger.warning(
            "Signature mismatch! computed=%s, received=%s",
            computed[:8], (signature or "")[:8],
        )
    return match


# ---------------------------------------------------------------------------
# NATS 消息发布
# ---------------------------------------------------------------------------
async def publish_msg_received(chat_id: str, sender_id: str, text: str, raw_event: dict):
    nc = await get_nats()
    subject = "msg_received"
    event_id = os.urandom(8).hex()
    payload = {
        "event_id": event_id,
        "event_type": "msg_received",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "source": "feishu",
            "chat_id": chat_id,
            "sender_id": sender_id,
            "text": text,
        },
        "raw": raw_event,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await nc.publish(subject, body)
    logger.info(f"Published msg_received: chat_id={chat_id}, text={text[:80]}...")


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------
@app.api_route("/api/v1/feishu/webhook", methods=["POST", "GET"])
async def feishu_webhook(request: Request):
    """
    飞书事件回调入口。

    支持的调用方式：
    - URL Verification（飞书配置回调地址时触发）
    - im.message.receive_v1（收到用户消息时触发）
    """
    raw_body = await request.body()
    body_json = json.loads(raw_body) if raw_body else {}

    # ---------- URL Verification ----------
    if body_json.get("type") == "url_verification":
        challenge = body_json.get("challenge", "")

        if not challenge and request.method == "GET":
            challenge = request.query_params.get("challenge", "")

        logger.info(f"URL Verification: challenge={challenge[:20]}...")
        return JSONResponse(content={"challenge": challenge})

    # ---------- 签名验证 ----------
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")

    if not verify_signature(timestamp, nonce, raw_body, signature):
        raise HTTPException(status_code=403, detail="Signature verification failed")

    # ---------- 事件处理 ----------
    event_type = body_json.get("type", "")
    logger.info(f"Received event: type={event_type}")

    if event_type == "im.message.receive_v1":
        event = body_json.get("event", {})
        message = event.get("message", {})
        chat_id = message.get("chat_id", "")
        sender = event.get("sender", {})
        sender_id = sender.get("sender_id", "")

        content_str = message.get("content", "{}")
        try:
            content_obj = json.loads(content_str)
            text = content_obj.get("text", "")
        except (json.JSONDecodeError, TypeError):
            text = content_str

        logger.info(f"Message from {sender_id} in {chat_id}: {text[:100]}")

        await publish_msg_received(chat_id, sender_id, text, body_json)

        return JSONResponse(content={"code": 0, "msg": "ok"})

    logger.warning(f"Unhandled event type: {event_type}")
    return JSONResponse(content={"code": 0, "msg": "ignored"})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    nc = _nc
    return {
        "status": "ok",
        "nats_connected": nc.is_connected if nc else False,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Starting Feishu Bot Service on port {BOT_PORT} ...")
    logger.info(f"FEISHU_SKIP_VERIFY={FEISHU_SKIP_VERIFY}")
    uvicorn.run(app, host="0.0.0.0", port=BOT_PORT, log_level="info")
