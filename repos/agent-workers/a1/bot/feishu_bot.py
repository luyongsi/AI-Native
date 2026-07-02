"""
bot/feishu_bot.py — Feishu Bot Card Messenger

Sends interactive card messages to users via the Feishu Open API and
handles button-click callbacks with Rich Hover (H5) preview.

Real implementation would:
  1. Use the Feishu SDK (lark-oapi) for message sending and card management.
  2. Register interactive card actions via the Card Builder API.
  3. Handle button-click events with signature verification.

Contract:
    class FeishuBot
        async send_card_message(user_id: str, card: dict) -> dict
        async handle_button_click(action: dict) -> dict
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class FeishuBot:
    """Feishu bot integration for sending card-based messages.

    In production this would be initialised with:
      - ``APP_ID`` / ``APP_SECRET`` from environment
      - ``lark_oapi.Client`` for the Feishu Open Platform SDK
    """

    def __init__(self, app_id: str = "", app_secret: str = ""):
        self.app_id = app_id
        self.app_secret = app_secret
        # Production: self.client = lark_oapi.Client.builder()
        #    .app_id(app_id).app_secret(app_secret).build()

    # ------------------------------------------------------------------
    #  send card message
    # ------------------------------------------------------------------

    async def send_card_message(self, user_id: str, card: dict) -> dict:
        """Send an interactive card to a Feishu user.

        Args:
            user_id: Feishu open_id or union_id of the target user.
            card:    Feishu Card JSON body (Card Builder schema).

        Returns:
            dict with ``message_id``, ``status``, ``sent_at``.

        Example card structure::

            {
              "header": {"title": {"tag": "plain_text", "content": "需求确认"}},
              "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": "请确认以下需求草案..."}},
                {"tag": "action", "actions": [
                  {"tag": "button", "text": {"tag": "plain_text", "content": "确认"},
                   "type": "primary", "value": "{\"action\":\"confirm\"}"},
                  {"tag": "button", "text": {"tag": "plain_text", "content": "修改"},
                   "type": "default", "value": "{\"action\":\"modify\"}"},
                ]}
              ]
            }
        """
        logger.info("Sending card to user=%s, card_header=%s",
                    user_id, card.get("header", {}).get("title", {}).get("content", "")[:40])

        # Production:
        #   resp = self.client.im.v1.message.create({
        #       "receive_id_type": "open_id",
        #       "receive_id": user_id,
        #       "msg_type": "interactive",
        #       "content": json.dumps(card),
        #   })
        #   return {"message_id": resp.data.message_id, "status": "sent"}

        return {
            "message_id": f"om_{user_id}_{int(datetime.now(timezone.utc).timestamp())}",
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    #  button click handler
    # ------------------------------------------------------------------

    async def handle_button_click(self, action: dict) -> dict:
        """Handle a card button-click callback from Feishu.

        Args:
            action: The ``action`` object from the Feishu interactive card
                    callback payload.  Contains ``value`` (JSON string with
                    ``action`` key), ``tag``, ``user_id``, ``open_message_id``.

        Returns:
            dict with ``action``, ``user_id``, ``ack_status``, ``reply_required``.
        """
        import json as _json

        raw_value = action.get("value", "{}")
        try:
            parsed_value = _json.loads(raw_value)
        except _json.JSONDecodeError:
            parsed_value = {"action": "unknown"}

        logger.info("Button click from user=%s action=%s",
                    action.get("user_id"), parsed_value.get("action"))

        # In production:
        #   1. Validate the callback signature.
        #   2. Look up the associated requirement session.
        #   3. Transition the DialogStateMachine accordingly.
        #   4. Optionally update the card via the message patch API.

        return {
            "action": parsed_value.get("action", "unknown"),
            "user_id": action.get("user_id", ""),
            "ack_status": "processed",
            "reply_required": True,
        }
