"""
A2: Knowledge Analyst Agent (知识检索 + LLM 分析)

Phase 5.2+: RAG-driven Knowledge Analysis
- Semantic search via pgvector embeddings (/api/knowledge/search)
- Neo4j dependency topology queries (graceful fallback if unavailable)
- Related PRs/issues from PostgreSQL
- Knowledge fusion with LLM summarization
- Prometheus metrics for quality tracking
"""
from __future__ import annotations

import asyncio
import json
import os
import logging
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

MC_BACKEND_URL = os.environ.get("MC_BACKEND_URL", "http://localhost:8000")
NEO4J_URL = os.environ.get("NEO4J_URL", "")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# Prometheus metrics (mock if prometheus_client not available)
try:
    from prometheus_client import Counter, Gauge, Histogram
    _METRICS_AVAILABLE = True

    A2_RAG_QUERIES_TOTAL = Counter(
        "a2_rag_queries_total",
        "Total RAG queries executed",
        ["query_type", "status"],
    )
    A2_KNOWLEDGE_QUALITY_SCORE = Gauge(
        "a2_knowledge_quality_score",
        "Knowledge package quality score (0-1)",
    )
    A2_EXECUTION_DURATION_SECONDS = Histogram(
        "a2_execution_duration_seconds",
        "A2 execution duration in seconds",
        ["phase"],
    )
except ImportError:
    _METRICS_AVAILABLE = False
    def _noop_metric(*args, **kwargs): pass
    A2_RAG_QUERIES_TOTAL = type("obj", (object,), {"labels": lambda *a, **k: type("obj", (object,), {"inc": _noop_metric})()})()
    A2_KNOWLEDGE_QUALITY_SCORE = type("obj", (object,), {"set": _noop_metric})()
    A2_EXECUTION_DURATION_SECONDS = type("obj", (object,), {"labels": lambda *a, **k: type("obj", (object,), {"observe": _noop_metric})()})()



class A2KnowledgeAnalyst(BaseAgentWorker):
    """RAG-driven Knowledge Analyst Agent."""

    agent_id = "A2"
    agent_type = "knowledge_analyst"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        # Import RAG retriever lazily
        from a2.rag_retriever import RAGRetriever
        self.rag = RAGRetriever(api_base_url=MC_BACKEND_URL)
        self.neo4j_available = bool(NEO4J_URL)

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """Execute knowledge analysis with RAG integration."""
        start_time = time.time()
        draft = context_package.get("requirement_draft", {})
        raw = context_package.get("message", draft.get("title", ""))
        domain = draft.get("domain", "general")
        title = draft.get("title", "")

        logger.info(f"[A2] Analyzing req={req_id}, domain={domain}, title={title[:50]}")

        try:
            # Phase 1: Semantic search via pgvector
            await self.report_status(req_id, "running", "Phase 1: 语义检索")
            phase1_start = time.time()
            similar_reqs = await self.search_similar_requirements(title or raw)
            A2_RAG_QUERIES_TOTAL.labels(query_type="semantic_search", status="success").inc()
            A2_EXECUTION_DURATION_SECONDS.labels(phase="semantic_search").observe(
                time.time() - phase1_start
            )

            # Phase 2: Query Neo4j dependencies (graceful fallback)
            await self.report_status(req_id, "running", "Phase 2: 依赖拓扑查询")
            phase2_start = time.time()
            dependencies = await self.query_dependencies(req_id)
            A2_EXECUTION_DURATION_SECONDS.labels(phase="dependency_query").observe(
                time.time() - phase2_start
            )

            # Phase 3: Query related PRs/issues
            await self.report_status(req_id, "running", "Phase 3: 相关 PR/Issue 查询")
            phase3_start = time.time()
            related_prs = await self.query_related_prs(title or raw)
            A2_EXECUTION_DURATION_SECONDS.labels(phase="related_prs_query").observe(
                time.time() - phase3_start
            )

            # Phase 4: Knowledge fusion
            await self.report_status(req_id, "running", "Phase 4: 知识融合")
            phase4_start = time.time()
            knowledge_package = await self.fuse_knowledge(
                similar_reqs, dependencies, related_prs, title or raw, req_id, context_package
            )
            A2_EXECUTION_DURATION_SECONDS.labels(phase="knowledge_fusion").observe(
                time.time() - phase4_start
            )

            # Record quality score
            quality_score = self._calculate_quality_score(knowledge_package)
            A2_KNOWLEDGE_QUALITY_SCORE.set(quality_score)

            # Phase 5: Publish event
            await self.report_status(req_id, "running", "Phase 5: 事件发布")
            await self.report_artifact(req_id, "knowledge_brief", knowledge_package)

            logger.info(f"[A2] Analysis completed for req={req_id}, quality_score={quality_score}")
            A2_EXECUTION_DURATION_SECONDS.labels(phase="total").observe(
                time.time() - start_time
            )

            return {
                "status": "completed",
                "req_id": req_id,
                "similar_requirements_count": len(knowledge_package.get("similar_requirements", [])),
                "dependencies_count": len(knowledge_package.get("dependencies", [])),
                "related_prs_count": len(knowledge_package.get("related_prs", [])),
                "quality_score": quality_score,
                "knowledge_package": knowledge_package,
            }

        except Exception as e:
            logger.error(f"[A2] Analysis failed for req={req_id}: {e}", exc_info=True)
            A2_RAG_QUERIES_TOTAL.labels(query_type="execute", status="failed").inc()
            await self.report_status(req_id, "failed", f"Analysis failed: {str(e)}")
            raise

    async def search_similar_requirements(self, query_text: str) -> List[Dict[str, Any]]:
        """Search for similar historical requirements."""
        try:
            results = await self.rag.search_similar_requirements(query_text, limit=5)
            return results
        except Exception as e:
            logger.error(f"[A2] Similar requirements search failed: {e}")
            return []

    async def query_dependencies(self, req_id: str) -> List[Dict[str, Any]]:
        """Query Neo4j for service dependencies (graceful fallback if unavailable)."""
        if not self.neo4j_available:
            logger.debug("[A2] Neo4j not configured, skipping dependency query")
            return []

        try:
            from neo4j import AsyncGraphDatabase

            async with AsyncGraphDatabase.driver(
                NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD)
            ) as driver:
                async with driver.session() as session:
                    # Query: Find services/components related to this requirement
                    result = await session.run(
                        """
                        MATCH (req:Requirement {id: $req_id})-[:DEPENDS_ON]->(service:Service)
                        OPTIONAL MATCH (service)-[:CALLS]->(downstream:Service)
                        RETURN service.name as service_name,
                               collect(downstream.name) as downstream_services
                        LIMIT 10
                        """,
                        req_id=req_id,
                    )
                    records = await result.fetch(10)
                    dependencies = [
                        {
                            "service": r["service_name"],
                            "downstream": r.get("downstream_services", []),
                        }
                        for r in records
                    ]
                    logger.info(f"[A2] Found {len(dependencies)} dependencies for req={req_id}")
                    return dependencies
        except ImportError:
            logger.debug("[A2] neo4j package not installed, skipping dependency query")
            return []
        except Exception as e:
            logger.warning(f"[A2] Neo4j query failed: {e}, continuing without dependencies")
            return []

    async def query_related_prs(self, query_text: str) -> List[Dict[str, Any]]:
        """Query PostgreSQL for related PRs/issues."""
        try:
            import httpx

            url = f"{MC_BACKEND_URL}/api/requirements"
            async with httpx.AsyncClient(timeout=10.0) as client:
                # This is a placeholder — in production would search PRs/issues
                # For now return empty list (DB query would be implemented in backend)
                logger.debug(f"[A2] Querying related PRs for: {query_text[:50]}")
                return []
        except Exception as e:
            logger.warning(f"[A2] Related PRs query failed: {e}")
            return []

    async def fuse_knowledge(
        self,
        similar_reqs: List[Dict[str, Any]],
        dependencies: List[Dict[str, Any]],
        related_prs: List[Dict[str, Any]],
        query_text: str,
        req_id: str = "",
        context_package: dict | None = None,
    ) -> Dict[str, Any]:
        """Fuse knowledge from multiple sources."""
        # Extract key insights from similar requirements
        summary = await self.summarize_similar_requirements(similar_reqs[:5], req_id=req_id, context_package=context_package or {})

        # Extract code patterns (if available in metadata)
        code_patterns = self._extract_code_patterns(similar_reqs)

        # Assess risks based on similar requirements history
        risks = self._assess_risks(similar_reqs)

        # Estimate complexity
        complexity = self._estimate_complexity(similar_reqs, dependencies)

        knowledge_package = {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "query_text": query_text[:200],
            "similar_requirements": [
                {
                    "id": r.get("content_id", r.get("id", "")),
                    "title": r.get("content_text", "")[:100],
                    "similarity": round(r.get("similarity", 0), 4),
                    "metadata": r.get("metadata", {}),
                }
                for r in similar_reqs[:5]
            ],
            "code_patterns": code_patterns,
            "risks": risks,
            "suggested_approach": summary,
            "estimated_complexity": complexity,
            "dependencies": dependencies,
            "related_prs": related_prs,
        }

        return knowledge_package

    async def summarize_similar_requirements(self, requirements: List[Dict], req_id: str = "", context_package: dict | None = None) -> str:
        """Generate LLM-based summary of similar requirements."""
        if not requirements:
            return "No similar requirements found. Consider zero-based design."

        # Format requirements for LLM
        req_text = "\n".join(
            f"{i + 1}. {r.get('content_text', r.get('title', ''))[:200]}"
            for i, r in enumerate(requirements[:5])
        )

        prompt = f"""Analyze these {min(len(requirements), 5)} similar historical requirements and extract key insights:

{req_text}

Provide:
1. Common patterns (max 50 words)
2. Best practices (max 50 words)
3. Pitfalls to avoid (max 50 words)

Be concise and actionable."""

        llm_response = await self.call_llm(
            [{"role": "user", "content": prompt}],
            task_type="knowledge_analysis",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.3,
            max_tokens=2000,
        )

        if llm_response:
            return llm_response.strip()
        else:
            # Fallback template-based summary
            return f"Based on {len(requirements)} similar requirements: Apply established patterns from order/payment/auth domains. Watch for concurrency issues in inventory scenarios. Consider workflow orchestration for multi-step approvals."

    def _extract_code_patterns(self, similar_reqs: List[Dict]) -> List[str]:
        """Extract reusable code patterns from similar requirements."""
        patterns = []
        for req in similar_reqs[:3]:
            metadata = req.get("metadata", {})
            tags = metadata.get("tags", [])
            if tags:
                patterns.extend([f"Pattern: {tag}" for tag in tags[:2]])
        return list(set(patterns))[:5]

    def _assess_risks(self, similar_reqs: List[Dict]) -> List[Dict[str, str]]:
        """Assess risks based on historical similar requirements."""
        risks = []

        # Extract common risk areas from metadata
        all_tags = []
        for req in similar_reqs:
            metadata = req.get("metadata", {})
            tags = metadata.get("tags", [])
            all_tags.extend(tags)

        # Map tags to known risks
        risk_mapping = {
            "concurrency": "High concurrency may cause race conditions or deadlocks",
            "idempotent": "Ensure idempotent processing for retry safety",
            "async": "Async operations require careful error handling and timeouts",
            "gateway": "Third-party integrations have retry and timeout considerations",
            "auth": "Authentication/authorization changes need comprehensive testing",
        }

        for tag, risk_desc in risk_mapping.items():
            if tag in all_tags:
                risks.append({"risk": tag, "description": risk_desc, "severity": "medium"})

        return risks[:5]

    def _estimate_complexity(
        self, similar_reqs: List[Dict], dependencies: List[Dict]
    ) -> Dict[str, Any]:
        """Estimate implementation complexity."""
        base_score = 0.5

        # Adjust based on number of similar requirements (more similar = lower complexity)
        if similar_reqs:
            base_score -= min(len(similar_reqs) * 0.1, 0.3)

        # Adjust based on dependencies
        if dependencies:
            base_score += len(dependencies) * 0.1

        # Clamp to [0, 1]
        score = max(0.0, min(1.0, base_score))

        complexity_level = "low" if score < 0.33 else ("medium" if score < 0.66 else "high")
        estimated_days = int(3 + (score * 17))  # 3-20 days estimate

        return {
            "score": round(score, 2),
            "level": complexity_level,
            "estimated_days": estimated_days,
            "rationale": f"Based on {len(similar_reqs)} similar requirements and {len(dependencies)} service dependencies",
        }

    def _calculate_quality_score(self, knowledge_package: Dict) -> float:
        """Calculate overall quality score of the knowledge package."""
        score = 0.0

        # Bonus for similar requirements found
        similar_count = len(knowledge_package.get("similar_requirements", []))
        if similar_count > 0:
            score += min(similar_count * 0.15, 0.4)

        # Bonus for suggested approach
        if knowledge_package.get("suggested_approach"):
            score += 0.2

        # Bonus for identified risks
        risks = knowledge_package.get("risks", [])
        if risks:
            score += min(len(risks) * 0.05, 0.2)

        # Bonus for dependencies
        deps = knowledge_package.get("dependencies", [])
        if deps:
            score += min(len(deps) * 0.05, 0.15)

        return round(min(score, 1.0), 3)
