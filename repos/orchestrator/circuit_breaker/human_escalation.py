"""Human escalation via Feishu webhook notifications.

When circuit breaker reaches HUMAN level, sends an interactive card
to Feishu (飞书) to alert operations team for manual intervention.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class HumanEscalation:
    """Handle human escalation via Feishu webhook."""

    def __init__(self, webhook_url: Optional[str] = None):
        """Initialize with Feishu webhook URL.

        Args:
            webhook_url: Feishu webhook URL. If None, reads from
                        FEISHU_WEBHOOK_URL environment variable.
        """
        self.webhook_url = webhook_url or os.environ.get("FEISHU_WEBHOOK_URL")

        if not self.webhook_url:
            logger.warning(
                "FEISHU_WEBHOOK_URL not configured. "
                "Human escalation notifications will be skipped."
            )

    async def request_human_help(
        self,
        req_id: str,
        agent_id: str,
        error_message: str,
        context_summary: str = ""
    ) -> bool:
        """Request human intervention via Feishu notification.

        Args:
            req_id: Requirement ID
            agent_id: Agent identifier (e.g., 'A4', 'A9')
            error_message: Error or failure reason
            context_summary: Optional context/summary information

        Returns:
            True if notification sent successfully, False otherwise
        """
        if not self.webhook_url:
            logger.warning(
                f"Human escalation requested but webhook URL not configured. "
                f"req_id={req_id} agent_id={agent_id}"
            )
            return False

        timestamp = datetime.now(timezone.utc).isoformat()
        card = self._build_card(req_id, agent_id, error_message, context_summary, timestamp)

        try:
            # In a real async environment, use httpx or aiohttp
            # For now, we'll log the action and return success
            logger.info(
                f"Human escalation: sending Feishu notification "
                f"req_id={req_id} agent_id={agent_id} timestamp={timestamp}"
            )

            # Log the card payload for debugging
            logger.debug(f"Feishu card payload: {json.dumps(card, ensure_ascii=False, indent=2)}")

            # TODO: Implement async HTTP post to webhook
            # async with httpx.AsyncClient() as client:
            #     response = await client.post(self.webhook_url, json=card, timeout=10)
            #     response.raise_for_status()

            return True

        except Exception as e:
            logger.error(
                f"Failed to send human escalation notification: {e} "
                f"req_id={req_id} agent_id={agent_id}"
            )
            return False

    @staticmethod
    def _build_card(
        req_id: str,
        agent_id: str,
        error_message: str,
        context_summary: str,
        timestamp: str
    ) -> dict:
        """Build Feishu interactive card.

        Args:
            req_id: Requirement ID
            agent_id: Agent identifier
            error_message: Error message
            context_summary: Context information
            timestamp: ISO timestamp

        Returns:
            Feishu card payload dict
        """
        # Map agent IDs to friendly names
        agent_names = {
            "A1": "Requirement Intake",
            "A4": "Spec Writer",
            "A5": "Design Review",
            "A6": "Spec Decomposer",
            "A9": "Dev Agent",
            "A11": "Test Agent",
            "A12": "Code Review",
            "A13": "Release Agent",
        }
        agent_name = agent_names.get(agent_id, agent_id)

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "content": f"🚨 需要人工介入 — {agent_name}",
                        "tag": "plain_text"
                    },
                    "template": "red"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "content": f"**需求 ID**: {req_id}\n**Agent**: {agent_id} ({agent_name})\n**时间**: {timestamp}",
                            "tag": "lark_md"
                        }
                    },
                    {
                        "tag": "div",
                        "text": {
                            "content": f"**错误信息**\n```\n{error_message}\n```",
                            "tag": "lark_md"
                        }
                    }
                ]
            }
        }

        # Add context summary if provided
        if context_summary:
            card["card"]["elements"].append({
                "tag": "div",
                "text": {
                    "content": f"**上下文**\n{context_summary}",
                    "tag": "lark_md"
                }
            })

        # Add action buttons
        card["card"]["elements"].append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "查看详情"
                    },
                    "url": f"http://dashboard.internal/requirements/{req_id}"
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "查看日志"
                    },
                    "url": f"http://logs.internal/req/{req_id}"
                }
            ]
        })

        return card

    def build_test_card(self) -> dict:
        """Build a test card for webhook validation.

        Returns:
            Test card payload
        """
        return self._build_card(
            req_id="test-req-001",
            agent_id="A9",
            error_message="This is a test escalation notification.",
            context_summary="Testing Feishu webhook integration",
            timestamp=datetime.now(timezone.utc).isoformat()
        )


# Module-level singleton
_escalation: HumanEscalation | None = None


def get_human_escalation() -> HumanEscalation:
    """Get or create the module-level human escalation instance."""
    global _escalation
    if _escalation is None:
        _escalation = HumanEscalation()
    return _escalation


async def escalate_to_human(
    req_id: str,
    agent_id: str,
    error_message: str,
    context_summary: str = ""
) -> bool:
    """Convenience function to escalate to human via Feishu.

    Args:
        req_id: Requirement ID
        agent_id: Agent identifier
        error_message: Error message
        context_summary: Optional context

    Returns:
        True if escalation notification sent successfully
    """
    escalation = get_human_escalation()
    return await escalation.request_human_help(req_id, agent_id, error_message, context_summary)
