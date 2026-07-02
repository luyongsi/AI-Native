"""
sources/feishu_meeting.py — Feishu Meeting Minutes Extractor

Extracts meeting transcripts and generates structured minutes.
Real implementation would use the Feishu Open API to fetch recording
transcripts and then call an LLM to summarize into structured minutes.

Contract:
    class FeishuMeetingSource
        async extract_minutes(meeting_id: str) -> dict
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class FeishuMeetingSource:
    """Extract and summarize meeting minutes from a Feishu meeting recording."""

    def __init__(self, tenant_access_token: str = ""):
        self.tenant_access_token = tenant_access_token

    async def extract_minutes(self, meeting_id: str) -> dict:
        """Fetch transcript and summarize minutes for a given meeting.

        Args:
            meeting_id: Feishu meeting / VC room ID.

        Returns:
            dict with ``meeting_id``, ``title``, ``date``, ``participants``,
            ``transcript_snippets``, ``summary``, ``action_items``, and
            ``decisions``.
        """
        logger.info("Extracting minutes for meeting_id=%s", meeting_id)

        # In production:
        #   1. GET https://open.feishu.cn/open-apis/vc/v1/meetings/{meeting_id}
        #   2. GET recording transcripts
        #   3. POST-to-LLM: "Summarize the following meeting transcript..."
        # Stub returns realistic mock data.

        return {
            "meeting_id": meeting_id,
            "title": "需求评审：订单导出功能",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "participants": [
                {"name": "张三", "role": "产品经理"},
                {"name": "李四", "role": "前端开发"},
                {"name": "王五", "role": "后端开发"},
            ],
            "transcript_snippets": [
                {"speaker": "张三", "start_ms": 120000, "text": "本次主要讨论订单导出功能的交互方案..."},
                {"speaker": "李四", "start_ms": 300000, "text": "导出按钮位置建议放在列表页工具栏..."},
            ],
            "summary": (
                "会议讨论了订单导出功能的需求范围：支持Excel/PDF格式，"
                "大数据量采用异步导出+下载链接通知，导出字段可由用户自定义选择。"
            ),
            "action_items": [
                {"owner": "张三", "task": "整理最终交互稿", "due": "本周五"},
                {"owner": "王五", "task": "评估异步导出技术方案", "due": "下周一"},
            ],
            "decisions": ["导出按钮统一放在列表页右上角工具栏", "默认导出近3个月数据", "超1万条走异步"],
        }
