"""
RAG Retriever Skill - Knowledge Search Integration

Provides semantic search capabilities via the /api/knowledge/search endpoint.
Handles graceful fallback to static knowledge base when API is unavailable.
"""

import asyncio
import logging
import os
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class RAGRetriever:
    """Retrieves knowledge from backend API or falls back to static knowledge base."""

    def __init__(self, api_base_url: Optional[str] = None):
        """Initialize RAG retriever with API base URL.

        Args:
            api_base_url: Base URL for MC backend (e.g., http://localhost:8000)
                         Falls back to MC_BACKEND_URL env var or http://localhost:8000
        """
        self.api_base_url = api_base_url or os.getenv("MC_BACKEND_URL", "http://localhost:8000")
        self.timeout = 10.0
        self._static_knowledge_base = self._init_static_kb()

    def _init_static_kb(self) -> List[Dict[str, Any]]:
        """Initialize static knowledge base as fallback."""
        return [
            {
                "id": "kb-001",
                "content_id": "kb-001",
                "content_type": "requirement",
                "content_text": "订单管理模块 - 支持创建、查询、取消订单，支持批量导入导出。高峰期 QPS ~200。",
                "similarity": 0.92,
                "metadata": {"tags": ["order", "CRUD", "batch"]},
            },
            {
                "id": "kb-002",
                "content_id": "kb-002",
                "content_type": "requirement",
                "content_text": "支付网关对接规范 - 对接第三方支付网关(微信/支付宝/银联)，需处理回调幂等和重复通知。",
                "similarity": 0.87,
                "metadata": {"tags": ["payment", "gateway", "idempotent"]},
            },
            {
                "id": "kb-003",
                "content_id": "kb-003",
                "content_type": "requirement",
                "content_text": "用户权限模型(RBAC) - 管理员/审核员/操作员三级角色，细粒度按钮级权限。",
                "similarity": 0.85,
                "metadata": {"tags": ["auth", "rbac", "user"]},
            },
            {
                "id": "kb-004",
                "content_id": "kb-004",
                "content_type": "requirement",
                "content_text": "库存扣减时序方案 - 高并发下预占库存→下单→支付→实扣的四段式方案。",
                "similarity": 0.81,
                "metadata": {"tags": ["inventory", "concurrency"]},
            },
            {
                "id": "kb-005",
                "content_id": "kb-005",
                "content_type": "requirement",
                "content_text": "消息通知模板引擎 - 模板化通知系统，支持邮件/短信/站内信，模板变量动态替换。",
                "similarity": 0.76,
                "metadata": {"tags": ["notification", "template"]},
            },
        ]

    async def search_similar_requirements(
        self, query_text: str, limit: int = 10, threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Search for similar requirements using semantic search.

        Args:
            query_text: The requirement text to search for
            limit: Maximum number of results
            threshold: Minimum similarity score (0-1)

        Returns:
            List of similar requirements with similarity scores
        """
        try:
            import httpx

            url = f"{self.api_base_url}/api/knowledge/search"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    params={
                        "query": query_text,
                        "content_type": "requirement",
                        "limit": limit,
                        "threshold": threshold,
                    },
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                logger.info(
                    f"[RAGRetriever] Found {len(results)} similar requirements from API"
                )
                return results
        except Exception as e:
            logger.warning(
                f"[RAGRetriever] API search failed ({e}), using static knowledge base"
            )
            return self._fallback_search(query_text, limit)

    async def search_similar_code(
        self, query_text: str, limit: int = 10, threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Search for similar code patterns using semantic search.

        Args:
            query_text: The code/pattern text to search for
            limit: Maximum number of results
            threshold: Minimum similarity score (0-1)

        Returns:
            List of similar code pieces with similarity scores
        """
        try:
            import httpx

            url = f"{self.api_base_url}/api/knowledge/search"
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    params={
                        "query": query_text,
                        "content_type": "code",
                        "limit": limit,
                        "threshold": threshold,
                    },
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                logger.info(f"[RAGRetriever] Found {len(results)} similar code patterns from API")
                return results
        except Exception as e:
            logger.warning(
                f"[RAGRetriever] Code search failed ({e}), returning empty results"
            )
            return []

    async def search_general(
        self,
        query_text: str,
        content_type: Optional[str] = None,
        limit: int = 10,
        threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """General semantic search across all content types.

        Args:
            query_text: Search query
            content_type: Filter by content type (requirement, code, spec, doc) or None for all
            limit: Maximum number of results
            threshold: Minimum similarity score (0-1)

        Returns:
            List of search results with similarity scores
        """
        try:
            import httpx

            url = f"{self.api_base_url}/api/knowledge/search"
            params = {
                "query": query_text,
                "limit": limit,
                "threshold": threshold,
            }
            if content_type:
                params["content_type"] = content_type

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, params=params)
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                logger.info(
                    f"[RAGRetriever] Found {len(results)} search results from API"
                )
                return results
        except Exception as e:
            logger.warning(f"[RAGRetriever] General search failed ({e}), using static KB")
            return self._fallback_search(query_text, limit)

    def _fallback_search(self, query_text: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fallback search using static knowledge base with simple keyword matching.

        Args:
            query_text: Search query
            limit: Maximum number of results

        Returns:
            List of static knowledge base entries filtered by keyword match
        """
        query_lower = query_text.lower()
        scored = []

        for doc in self._static_knowledge_base:
            text_lower = doc["content_text"].lower()
            metadata_tags = doc.get("metadata", {}).get("tags", [])

            # Score based on keyword matches
            score = doc.get("similarity", 0.5)

            # Boost for direct keyword matches
            for tag in metadata_tags:
                if tag in query_lower or tag.replace("_", " ") in query_lower:
                    score += 0.1

            # Boost for text substring matches
            if any(word in text_lower for word in query_lower.split()):
                score += 0.05

            score = min(score, 1.0)
            doc_copy = doc.copy()
            doc_copy["similarity"] = round(score, 4)
            scored.append(doc_copy)

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        results = scored[:limit]
        logger.info(
            f"[RAGRetriever] Fallback search returned {len(results)} static KB results"
        )
        return results
