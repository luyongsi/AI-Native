"""
rag_search.py — RAG (Retrieval-Augmented Generation) Search

Performs semantic search over the knowledge base to find related documents
and historical context for a new requirement. Real implementation would use
pgvector with a sentence-transformer embedding model.

Contract:
    class RAGSearch
        async search(query: str, top_k: int = 10) -> dict
        -> {results: [{doc_id, title, content, score}], total_found: int}
"""

import logging
import random
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ---- mock knowledge base (15 documents) ----

_MOCK_DOCS: list[dict] = [
    {"doc_id": "kb-001", "title": "订单管理模块历史需求",
     "content": "此前实现的订单管理支持创建、查询、取消订单，批量导入导出。高峰期QPS约200。",
     "tags": ["order_management", "CRUD", "batch"], "relevance": 0.94},
    {"doc_id": "kb-002", "title": "支付网关对接规范",
     "content": "对接第三方支付网关，支持微信/支付宝/银联，需处理回调幂等和重复通知。",
     "tags": ["payment", "gateway", "idempotent"], "relevance": 0.91},
    {"doc_id": "kb-003", "title": "用户权限模型设计",
     "content": "RBAC模型设计文档，管理员/审核员/操作员三级，细粒度按钮级权限，动态菜单。",
     "tags": ["auth", "rbac", "user_management"], "relevance": 0.88},
    {"doc_id": "kb-004", "title": "库存扣减时序方案",
     "content": "高并发下预占库存→下单→支付→实扣的四段式方案，基于Redis Lua保证原子性，避免超卖。",
     "tags": ["inventory", "concurrency", "redis"], "relevance": 0.85},
    {"doc_id": "kb-005", "title": "消息通知模板引擎",
     "content": "模板化通知系统，支持邮件/短信/站内信多通道，模板变量动态替换，失败自动重试。",
     "tags": ["notification", "template", "multi-channel"], "relevance": 0.82},
    {"doc_id": "kb-006", "title": "审批工作流引擎",
     "content": "基于Temporal实现多级审批，支持并行审批、委托、驳回、加签，可视化流程配置。",
     "tags": ["approval", "workflow", "temporal"], "relevance": 0.79},
    {"doc_id": "kb-007", "title": "报表导出服务",
     "content": "异步报表生成，支持Excel/PDF，Celery异步任务编排，大文件分片下载。",
     "tags": ["reporting", "export", "async"], "relevance": 0.76},
    {"doc_id": "kb-008", "title": "API 网关限流方案",
     "content": "基于Token Bucket的分布式限流，Redis + Lua，支持按用户/IP/API三级限流策略。",
     "tags": ["api", "rate-limiting", "redis"], "relevance": 0.72},
    {"doc_id": "kb-009", "title": "数据脱敏规范",
     "content": "手机号/身份证/银行卡号的脱敏规则，日志脱敏切面AOP实现，动态字段配置。",
     "tags": ["security", "data-masking", "compliance"], "relevance": 0.68},
    {"doc_id": "kb-010", "title": "微服务间鉴权方案",
     "content": "基于JWT的服务间认证，短期token + refresh，支持token黑名单实时失效。",
     "tags": ["auth", "jwt", "microservice"], "relevance": 0.65},
    {"doc_id": "kb-011", "title": "文件存储方案",
     "content": "对接OSS/S3/MinIO，支持断点续传、CDN加速、图片压缩/水印，统一文件网关。",
     "tags": ["storage", "oss", "cdn"], "relevance": 0.62},
    {"doc_id": "kb-012", "title": "日志采集与分析",
     "content": "EFK(Elasticsearch+Fluentd+Kibana)统一日志平台，结构化JSON日志，链路追踪。",
     "tags": ["observability", "logging", "tracing"], "relevance": 0.58},
    {"doc_id": "kb-013", "title": "配置中心设计",
     "content": "基于Nacos的动态配置管理，热更新、灰度发布、版本回滚，配置变更审计。",
     "tags": ["config", "nacos", "devops"], "relevance": 0.54},
    {"doc_id": "kb-014", "title": "定时任务调度",
     "content": "XXL-Job分布式定时任务，Cron表达式、分片广播、失败重试、任务依赖编排。",
     "tags": ["scheduler", "cron", "distributed"], "relevance": 0.50},
    {"doc_id": "kb-015", "title": "前端组件库规范",
     "content": "基于Ant Design Pro的组件封装规范，自定义主题、国际化、Table/Hook高阶封装。",
     "tags": ["frontend", "antd", "component"], "relevance": 0.47},
]


class RAGSearch:
    """Semantic search over the document knowledge base.

    In production this delegates to pgvector::

        SELECT doc_id, title, content,
               1 - (embedding <=> query_embedding) AS score
        FROM documents
        ORDER BY embedding <=> query_embedding
        LIMIT $top_k;
    """

    def __init__(self, top_k_default: int = 10):
        self.top_k_default = top_k_default

    async def search(self, query: str, top_k: int = 10) -> dict:
        """Search the knowledge base for documents relevant to *query*.

        Args:
            query:  Natural-language search string.
            top_k:  Maximum number of results to return.

        Returns:
            dict with ``results`` (list of doc dicts sorted by score desc)
            and ``total_found``.
        """
        logger.info("RAG search: query='%s', top_k=%d", query[:80], top_k)

        # ---- stub: keyword-boosted mock scoring ----
        scored: list[dict] = []
        for doc in _MOCK_DOCS:
            base_score = doc["relevance"]
            boost = self._keyword_boost(query, doc)
            score = round(min(base_score + boost + random.uniform(-0.03, 0.03), 1.0), 4)
            scored.append({
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "content": doc["content"],
                "score": score,
            })

        scored.sort(key=lambda d: d["score"], reverse=True)
        top_results = scored[:top_k]

        logger.info("RAG search returned %d results, top score=%.3f",
                    len(top_results), top_results[0]["score"] if top_results else 0)

        return {
            "results": top_results,
            "total_found": len(top_results),
        }

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _keyword_boost(query: str, doc: dict) -> float:
        """Give a small score bump when query words match doc tags or title."""
        q_lower = query.lower()
        boost = 0.0
        for tag in doc.get("tags", []):
            if tag.replace("_", " ") in q_lower or tag in q_lower:
                boost += 0.06
        # Title match
        title_words = set(doc.get("title", "").lower().split())
        query_words = set(q_lower.split())
        overlap = title_words & query_words
        boost += len(overlap) * 0.03
        return min(boost, 0.20)
