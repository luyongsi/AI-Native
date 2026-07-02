"""
sources/feishu_chat.py — Feishu (Lark) Chat Webhook Handler

Processes incoming Feishu bot messages via webhook callbacks.
Real implementation would:
  1. Validate the HMAC-SHA256 signature in the X-Lark-Signature header
     using the app secret configured in settings.
  2. Decrypt the message body if encryption is enabled.
  3. Deserialize the event payload and route to IntentExtractor.

Contract:
    class FeishuChatSource
        async handle_webhook(payload: dict) -> dict
"""

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


class FeishuChatSource:
    """Handles inbound Feishu chat messages delivered via webhook.

    In production the webhook flow is:
      Feishu server → POST /api/webhook/feishu → validate HMAC → decrypt → handler
    """

    def __init__(self, app_secret: str = ""):
        # In production this would come from a config/settings provider
        self.app_secret = app_secret

    async def handle_webhook(self, payload: dict) -> dict:
        """Process an inbound webhook payload from Feishu.

        Args:
            payload: Raw JSON body from the Feishu webhook POST, containing
                     at minimum ``event``, ``sender``, ``message`` keys.

        Returns:
            dict with parsed ``message_text``, ``sender_id``, ``chat_id``,
            ``message_type``, and a boolean ``verified`` flag.
        """
        logger.info("Feishu webhook received, type=%s", payload.get("event", {}).get("type", "unknown"))

        # ---------- HMAC verification (stub) ----------
        # Real code:
        #   signature = request.headers.get("X-Lark-Signature", "")
        #   timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
        #   nonce = request.headers.get("X-Lark-Request-Nonce", "")
        #   body_str = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        #   sign_str = f"{timestamp}{nonce}{self.app_secret}{body_str}"
        #   expected = hashlib.sha256(sign_str.encode()).hexdigest()
        #   if not hmac.compare_digest(signature, expected):
        #       raise ValueError("HMAC signature verification failed")
        verified = True  # stub — always passes

        # Parse the inner event envelope
        event = payload.get("event", {})
        sender = payload.get("sender", {})
        message = event.get("message", {})

        parsed = {
            "verified": verified,
            "message_id": event.get("message_id", ""),
            "message_text": message.get("content", {}).get("text", ""),
            "message_type": message.get("message_type", "text"),
            "sender_id": sender.get("sender_id", {}).get("open_id", ""),
            "chat_id": event.get("chat_id", ""),
            "timestamp": event.get("create_time", ""),
        }

        logger.info("Parsed Feishu message: sender=%s text='%s'",
                    parsed["sender_id"], parsed["message_text"][:60])

        return parsed
