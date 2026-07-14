"""
A2: Knowledge Analyst Agent (知识检索 + LLM 分析)

Phase 5.2+: RAG-driven Knowledge Analysis with MCP 3-tier degradation.
Aligned with data dictionary §5 — returns full artifact with feasibility,
conflicts, confirmation checklist, and global routing keys (session_id + cycle).
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
    """RAG-driven Knowledge Analyst Agent with MCP + REST + fallback degradation."""

    agent_id = "A2"
    agent_type = "knowledge_analyst"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)

        # L1 — MCP Gateway client
        from a1.analyzer.mcp_client import MCPClient
        self.mcp = MCPClient()

        # L2 — RAGRetriever (direct REST to MC Backend)
        from a2.rag_retriever import RAGRetriever
        self.rag = RAGRetriever(api_base_url=MC_BACKEND_URL)

        # Feasibility assessor + conflict detector
        from a2.feasibility import FeasibilityAssessor
        from a2.conflict_detector import ConflictDetector
        self.feasibility_assessor = FeasibilityAssessor()
        self.conflict_detector = ConflictDetector()

        self.neo4j_available = bool(NEO4J_URL)

    # ── Main execute ───────────────────────────────────────────────────────

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """Execute full knowledge analysis pipeline (Phases 1-9)."""
        start_time = time.time()
        draft = context_package.get("requirement_draft", {})
        raw = context_package.get("message", draft.get("title", ""))
        domain = draft.get("domain", "general")
        title = draft.get("title", "")
        session_id = context_package.get("session_id", "")
        cycle = context_package.get("cycle", 0)

        logger.info("[A2] Analyzing req=%s, domain=%s, title=%s, cycle=%s",
                     req_id, domain, title[:50], cycle)

        try:
            # ── Phase 1: Knowledge retrieval (3 independent 3-tier chains, parallel) ──
            await self.report_status(req_id, "running", "Phase 1: MCP 知识检索")

            sim_task = asyncio.ensure_future(self._retrieve_similar_requirements(draft))
            issues_task = asyncio.ensure_future(self._retrieve_known_issues(draft))
            risks_task = asyncio.ensure_future(self._retrieve_domain_risks(domain))

            (sim_reqs, sim_level), (issues, issues_level), (risks, risks_level) = (
                await asyncio.gather(sim_task, issues_task, risks_task)
            )

            retrieval_levels = [sim_level, issues_level, risks_level]
            logger.info("[A2] Retrieval levels: sim=%s, issues=%s, risks=%s",
                        sim_level, issues_level, risks_level)

            # ── Phase 2: Neo4j dependency query ─────────────────────────────
            await self.report_status(req_id, "running", "Phase 2: 依赖拓扑查询")
            dependencies = await self.query_dependencies(req_id)

            # ── Phase 3: Related PRs/issues ─────────────────────────────────
            await self.report_status(req_id, "running", "Phase 3: 相关 PR/Issue 查询")
            related_prs = await self.query_related_prs(title or raw)

            # ── Phase 4: Feasibility assessment ─────────────────────────────
            await self.report_status(req_id, "running", "Phase 4: 可行性评估")
            from a2.mappers import build_feasibility_assessment
            feasibility = await build_feasibility_assessment(
                draft, risks, assessor=self.feasibility_assessor,
                call_llm=self.call_llm,
            )

            # ── Phase 5: Conflict detection ─────────────────────────────────
            await self.report_status(req_id, "running", "Phase 5: 冲突检测")
            from a2.mappers import build_conflicts
            conflicts = await build_conflicts(
                draft, sim_reqs, detector=self.conflict_detector,
            )

            # ── Phase 6: Confirmation checklist ─────────────────────────────
            await self.report_status(req_id, "running", "Phase 6: 生成确认清单")
            from a2.mappers import build_confirmation_checklist
            checklist = await build_confirmation_checklist(
                draft, feasibility, conflicts, call_llm=self.call_llm,
            )

            # ── Phase 7: Knowledge fusion + assemble artifact ───────────────
            await self.report_status(req_id, "running", "Phase 7: 知识融合")
            knowledge_package = await self.fuse_knowledge(
                sim_reqs, dependencies, related_prs, title or raw, req_id, context_package,
            )
            quality_score = self._calc_quality_score(retrieval_levels, knowledge_package)
            A2_KNOWLEDGE_QUALITY_SCORE.set(quality_score)

            agent_artifact = {
                "knowledge_package": knowledge_package,
                "feasibility_assessment": feasibility,
                "confirmation_checklist": checklist,
                "conflicts": conflicts,
                "quality_score": quality_score,
            }

            # ── Phase 8: Persist agent_results ──────────────────────────────
            await self.report_status(req_id, "running", "Phase 8: 持久化")
            status = self._determine_status(retrieval_levels)
            await self._persist_agent_result(req_id, session_id, cycle, status, agent_artifact)

            # ── Phase 9: Publish event ──────────────────────────────────────
            await self.report_status(req_id, "running", "Phase 9: 事件发布")
            await self.report_artifact(req_id, "knowledge_brief", agent_artifact)

            A2_EXECUTION_DURATION_SECONDS.labels(phase="total").observe(time.time() - start_time)
            logger.info("[A2] Completed req=%s quality=%.3f status=%s", req_id, quality_score, status)

            return {
                "req_id": req_id,
                "session_id": session_id,
                "cycle": cycle,
                "status": status,
                "feasibility_assessment": feasibility,
                "confirmation_checklist": checklist,
                "conflicts": conflicts,
                "quality_score": quality_score,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("[A2] Analysis failed for req=%s: %s", req_id, e, exc_info=True)
            A2_RAG_QUERIES_TOTAL.labels(query_type="execute", status="failed").inc()
            await self.report_status(req_id, "failed", f"Analysis failed: {str(e)}")
            raise

    # ── Phase 1: Three independent 3-tier degradation methods ───────────────

    async def _retrieve_similar_requirements(self, draft: dict) -> tuple[list[dict], str]:
        """L1 MCP → L2 RAGRetriever REST → L3 static fallback."""
        query = self._build_query(draft)
        # L1: MCP
        try:
            results = await self.mcp.search_similar_requirements(draft, timeout=5.0)
            if results:
                return results, "mcp"
        except Exception as e:
            logger.debug("[A2] MCP similar_reqs failed: %s", e)

        # L2: RAGRetriever (direct REST)
        try:
            results = await self.rag.search_similar_requirements(query, limit=5)
            if results:
                return results, "direct"
        except Exception as e:
            logger.debug("[A2] RAG similar_reqs failed: %s", e)

        # L3: static fallback
        try:
            results = self.rag._fallback_search(query, limit=5)
            if results:
                return results, "fallback"
        except Exception:
            pass

        return [], "empty"

    async def _retrieve_known_issues(self, draft: dict) -> tuple[list[dict], str]:
        """L1 MCP → L2 RAGRetriever REST → L3 static fallback."""
        query = self._build_query(draft)
        # L1: MCP
        try:
            results = await self.mcp.search_known_issues(draft, timeout=5.0)
            if results:
                return results, "mcp"
        except Exception as e:
            logger.debug("[A2] MCP known_issues failed: %s", e)

        # L2: RAGRetriever (direct REST) — use search_general with content_type=issue
        try:
            results = await self.rag.search_general(query, content_type="issue", limit=10)
            if results:
                return results, "direct"
        except Exception as e:
            logger.debug("[A2] RAG known_issues failed: %s", e)

        # L3: static fallback
        try:
            results = self.rag._fallback_search(query, limit=10)
            if results:
                return results, "fallback"
        except Exception:
            pass

        return [], "empty"

    async def _retrieve_domain_risks(self, domain: str) -> tuple[list[dict], str]:
        """L1 MCP → L2 RAGRetriever REST → L3 static fallback."""
        # L1: MCP
        try:
            results = await self.mcp.get_domain_risks(domain, timeout=5.0)
            if results:
                return results, "mcp"
        except Exception as e:
            logger.debug("[A2] MCP domain_risks failed: %s", e)

        # L2: RAGRetriever (direct REST)
        try:
            results = await self.rag.search_general(
                f"domain:{domain} risks", content_type="doc", limit=10,
            )
            if results:
                return results, "direct"
        except Exception as e:
            logger.debug("[A2] RAG domain_risks failed: %s", e)

        # L3: static fallback
        try:
            results = self.rag._fallback_search(f"domain:{domain} risks", limit=10)
            if results:
                return results, "fallback"
        except Exception:
            pass

        return [], "empty"

    # ── Phase 2-3: Dependency & PR queries (unchanged from original) ────────

    async def query_dependencies(self, req_id: str) -> list[dict]:
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
                    logger.info("[A2] Found %d dependencies for req=%s", len(dependencies), req_id)
                    return dependencies
        except ImportError:
            logger.debug("[A2] neo4j package not installed, skipping dependency query")
            return []
        except Exception as e:
            logger.warning("[A2] Neo4j query failed: %s, continuing without dependencies", e)
            return []

    async def query_related_prs(self, query_text: str) -> list[dict]:
        """Query PostgreSQL for related PRs/issues."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                logger.debug("[A2] Querying related PRs for: %s", query_text[:50])
                return []
        except Exception as e:
            logger.warning("[A2] Related PRs query failed: %s", e)
            return []

    # ── Phase 7: Knowledge fusion ───────────────────────────────────────────

    async def fuse_knowledge(
        self,
        similar_reqs: list[dict],
        dependencies: list[dict],
        related_prs: list[dict],
        query_text: str,
        req_id: str = "",
        context_package: dict | None = None,
    ) -> dict:
        """Fuse knowledge from multiple sources."""
        summary = await self.summarize_similar_requirements(
            similar_reqs[:5], req_id=req_id, context_package=context_package or {},
        )
        code_patterns = self._extract_code_patterns(similar_reqs)
        risks = self._assess_risks(similar_reqs)
        complexity = self._estimate_complexity(similar_reqs, dependencies)

        return {
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

    async def summarize_similar_requirements(
        self, requirements: list[dict], req_id: str = "", context_package: dict | None = None,
    ) -> str:
        """Generate LLM-based summary of similar requirements."""
        if not requirements:
            return "No similar requirements found. Consider zero-based design."

        req_text = "\n".join(
            f"{i + 1}. {r.get('content_text', r.get('title', ''))[:200]}"
            for i, r in enumerate(requirements[:5])
        )

        prompt = (
            "Analyze these similar historical requirements and extract key insights:\n\n"
            f"{req_text}\n\n"
            "Provide:\n"
            "1. Common patterns (max 50 words)\n"
            "2. Best practices (max 50 words)\n"
            "3. Pitfalls to avoid (max 50 words)\n\n"
            "Be concise and actionable."
        )

        llm_response = await self.call_llm(
            [{"role": "user", "content": prompt}],
            task_type="knowledge_analysis",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", "") if context_package else "",
            temperature=0.3,
            max_tokens=2000,
        )

        if llm_response:
            return llm_response.strip()

        return (
            f"Based on {len(requirements)} similar requirements: "
            "Apply established patterns from order/payment/auth domains. "
            "Watch for concurrency issues in inventory scenarios. "
            "Consider workflow orchestration for multi-step approvals."
        )

    def _extract_code_patterns(self, similar_reqs: list[dict]) -> list[str]:
        """Extract reusable code patterns from similar requirements."""
        patterns = []
        for req in similar_reqs[:3]:
            metadata = req.get("metadata", {})
            tags = metadata.get("tags", [])
            if tags:
                patterns.extend([f"Pattern: {tag}" for tag in tags[:2]])
        return list(set(patterns))[:5]

    def _assess_risks(self, similar_reqs: list[dict]) -> list[dict]:
        """Assess risks based on historical similar requirements."""
        all_tags = []
        for req in similar_reqs:
            metadata = req.get("metadata", {})
            tags = metadata.get("tags", [])
            all_tags.extend(tags)

        risk_mapping = {
            "concurrency": "High concurrency may cause race conditions or deadlocks",
            "idempotent": "Ensure idempotent processing for retry safety",
            "async": "Async operations require careful error handling and timeouts",
            "gateway": "Third-party integrations have retry and timeout considerations",
            "auth": "Authentication/authorization changes need comprehensive testing",
        }

        return [
            {"risk": tag, "description": desc, "severity": "medium"}
            for tag, desc in risk_mapping.items()
            if tag in all_tags
        ][:5]

    def _estimate_complexity(
        self, similar_reqs: list[dict], dependencies: list[dict],
    ) -> dict:
        """Estimate implementation complexity."""
        base_score = 0.5
        if similar_reqs:
            base_score -= min(len(similar_reqs) * 0.1, 0.3)
        if dependencies:
            base_score += len(dependencies) * 0.1

        score = max(0.0, min(1.0, base_score))
        level = "low" if score < 0.33 else ("medium" if score < 0.66 else "high")
        estimated_days = int(3 + (score * 17))

        return {
            "score": round(score, 2),
            "level": level,
            "estimated_days": estimated_days,
            "rationale": (
                f"Based on {len(similar_reqs)} similar requirements "
                f"and {len(dependencies)} service dependencies"
            ),
        }

    # ── Quality scoring (design doc §3.4.4) ─────────────────────────────────

    def _calc_quality_score(
        self, retrieval_levels: list[str], knowledge_package: dict,
    ) -> float:
        """Calculate quality score based on retrieval levels and content."""
        mcp_count = retrieval_levels.count("mcp")
        direct_count = retrieval_levels.count("direct")
        fallback_count = retrieval_levels.count("fallback")

        if mcp_count == 3:
            base = 0.6
        elif mcp_count >= 1:
            base = 0.4
        elif direct_count >= 1:
            base = 0.3
        elif fallback_count >= 1:
            base = 0.15
        else:
            base = 0.05

        # content bonuses
        base += min(len(knowledge_package.get("similar_requirements", [])) * 0.08, 0.25)
        if knowledge_package.get("suggested_approach"):
            base += 0.10
        if knowledge_package.get("risks"):
            base += min(len(knowledge_package["risks"]) * 0.03, 0.10)

        return round(min(base, 1.0), 3)

    # ── Status determination (design doc §3.4.7) ───────────────────────────

    @staticmethod
    def _determine_status(retrieval_levels: list[str]) -> str:
        """Determine agent_results.status from retrieval levels."""
        if all(lvl == "empty" for lvl in retrieval_levels):
            return "empty"
        return "completed"

    # ── Persistence (design doc §3.4.8) ────────────────────────────────────

    async def _persist_agent_result(
        self, req_id: str, session_id: str, cycle: int,
        status: str, artifact: dict,
    ) -> None:
        """Write agent_results via MC Backend API. Non-blocking on failure."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{MC_BACKEND_URL}/api/agent_results",
                    json={
                        "req_id": req_id,
                        "agent_key": "A2",
                        "cycle": cycle,
                        "status": status,
                        "artifact": artifact,
                    },
                )
                if resp.status_code in (200, 201):
                    logger.info("[A2] Persisted agent_result (cycle=%d, status=%s)", cycle, status)
                else:
                    logger.warning("[A2] Failed to persist agent_result: HTTP %d", resp.status_code)
        except Exception as e:
            logger.warning("[A2] Failed to persist agent_result: %s (non-fatal)", e)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_query(draft: dict) -> str:
        """Build a search query from the draft dict."""
        parts = []
        if draft.get("title"):
            parts.append(draft["title"])
        if draft.get("description"):
            parts.append(draft["description"])
        if draft.get("domain"):
            parts.append(draft["domain"])
        return " ".join(parts)
