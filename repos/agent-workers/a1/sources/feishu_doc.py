"""
sources/feishu_doc.py — Feishu Document Parser

Parses Feishu Docs (formerly Lark Docs) into structured requirement text.
Real implementation would use the Feishu Open API (Drive + Docs APIs)
to fetch document blocks and convert rich text to markdown.

Contract:
    class FeishuDocSource
        async parse_document(doc_id: str) -> dict
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class FeishuDocSource:
    """Parse a Feishu document into structured text blocks."""

    def __init__(self, tenant_access_token: str = ""):
        self.tenant_access_token = tenant_access_token

    async def parse_document(self, doc_id: str) -> dict:
        """Fetch and parse the content of a Feishu document.

        Args:
            doc_id: Feishu document token (e.g. ``doxcnBxxxxxxx``).

        Returns:
            dict with ``doc_id``, ``title``, ``blocks`` (list of text/heading/list items),
            ``plain_text`` (concatenated for downstream NLP), and metadata.
        """
        logger.info("Parsing Feishu document doc_id=%s", doc_id)

        # Production flow:
        #   1. GET /open-apis/docx/v1/documents/{doc_id}  (metadata)
        #   2. GET /open-apis/docx/v1/documents/{doc_id}/blocks  (content blocks)
        #   3. Walk the block tree and convert to markdown / plain text

        return {
            "doc_id": doc_id,
            "title": "[Mock] 订单导出需求文档",
            "url": f"https://xxx.feishu.cn/docx/{doc_id}",
            "blocks": [
                {"type": "heading1", "text": "订单导出功能 PRD"},
                {"type": "paragraph", "text": "背景：当前运营人员需要手动复制数据到Excel，效率低。"},
                {"type": "heading2", "text": "功能范围"},
                {"type": "bullet", "text": "支持按日期范围筛选"},
                {"type": "bullet", "text": "支持Excel和PDF两种格式"},
                {"type": "bullet", "text": "超1万条走异步导出"},
                {"type": "heading2", "text": "非功能需求"},
                {"type": "ordered", "text": "导出任务超时时间 5 分钟"},
                {"type": "ordered", "text": "并发导出上限 10 个/人"},
            ],
            "plain_text": (
                "订单导出功能 PRD\n"
                "背景：当前运营人员需要手动复制数据到Excel，效率低。\n"
                "功能范围：支持按日期范围筛选，支持Excel和PDF两种格式，超1万条走异步导出。\n"
                "非功能需求：导出任务超时5分钟，并发导出上限10个/人。"
            ),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
