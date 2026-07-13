"""
A1 Agent — Requirement Analysis Agent

Main entry point. Orchestrates:
  1. MCP knowledge base retrieval (parallel, 4 tools)
  2. LLM streaming draft building
  3. Clarification point identification
  4. Wireframe generation (optional)
  5. BDD acceptance criteria drafting
  6. Confidence scoring

Pure analysis logic — no DB writes, no NATS, no SSE formatting.
All side effects are managed by the MC Backend route layer.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Optional

from .analyzer.mcp_client import MCPClient
from .analyzer.draft_builder import DraftBuilder
from .analyzer.clarification import ClarificationEngine
from .wireframe.generator import WireframeGenerator
from .bdd.drafter import BDDDrafter

logger = logging.getLogger(__name__)


class A1Agent:
    """A1 Requirement Analysis Agent — pure analysis, no DB/NATS side effects."""

    agent_id = "A1"

    def __init__(self):
        self.mcp_client = MCPClient()
        self.draft_builder = DraftBuilder()
        self.clarification = ClarificationEngine()
        self.wireframe_gen = WireframeGenerator()
        self.bdd_drafter = BDDDrafter()

    async def analyze(
        self,
        req_id: str,
        session_id: str,
        user_message: str,
        history: list[dict],
        current_draft: Optional[dict],
        cycle: int,
    ) -> AsyncGenerator[dict, None]:
        """Perform one round of analysis, yielding structured event dicts.

        The caller (MC Backend route layer) iterates over events and formats
        them as SSE strings for the frontend. The last draft_update event
        holds the final draft.
        """
        try:
            # Step 1: MCP knowledge retrieval (parallel, before LLM)
            yield {"type": "thinking", "content": "正在检索知识库..."}
            knowledge = await self._fetch_knowledge(current_draft)
            knowledge_summary = self._summarize_sources(knowledge)
            yield {"type": "knowledge", "sources": knowledge_summary}

            # Step 2: LLM streaming analysis
            yield {"type": "thinking", "content": "正在分析需求..."}
            ctx = self._build_context(
                history, user_message, current_draft, knowledge, cycle,
            )
            accumulated_draft = current_draft or {}

            async for partial in self.draft_builder.stream_analyze(user_message, ctx):
                accumulated_draft = partial
                yield {"type": "draft_update", "draft": partial}

            # Step 3: Identify clarification points
            clarifications = await self.clarification.identify(accumulated_draft, history)
            if clarifications:
                yield {"type": "clarification", "items": clarifications}

            # Step 4: Optional wireframe generation
            wireframe = None
            if self._should_generate_wireframe(accumulated_draft):
                try:
                    wireframe = await self.wireframe_gen.generate(accumulated_draft)
                    yield {"type": "wireframe", "data": wireframe}
                except Exception:
                    logger.exception("Wireframe generation failed, continuing")

            # Step 5: BDD acceptance criteria
            gwt_result = await self.bdd_drafter.draft_gwt(accumulated_draft)
            accumulated_draft["acceptance_criteria"] = self._gwt_to_strings(gwt_result)

            # Step 6: Confidence scoring
            confidence = self._calculate_confidence(accumulated_draft, knowledge)

            # Step 7: Done
            yield {
                "type": "done",
                "draft": accumulated_draft,
                "confidence_score": confidence,
                "knowledge_sources": knowledge_summary,
                "mcp_tools_used": [
                    "search_similar_requirements",
                    "get_domain_risks",
                    "get_tech_stack_recommendations",
                    "get_cost_baseline",
                ],
            }

        except Exception as e:
            logger.exception("[A1] analyze() error")
            yield {
                "type": "error",
                "content": "分析过程出错: {detail}".format(detail=str(e)[:200]),
            }

    # ------------------------------------------------------------------
    async def _fetch_knowledge(self, draft: dict | None) -> dict:
        """Parallel MCP calls, individual failure does not block."""
        tasks = [
            self.mcp_client.search_similar_requirements(draft, timeout=5),
            self.mcp_client.get_domain_risks(
                draft.get("domain", "") if draft else "", timeout=5,
            ),
            self.mcp_client.get_tech_stack_recommendations(draft, timeout=5),
            self.mcp_client.get_cost_baseline(draft, timeout=5),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            "similar_requirements": results[0] if not isinstance(results[0], Exception) else [],
            "domain_risks": results[1] if not isinstance(results[1], Exception) else [],
            "tech_stack": results[2] if not isinstance(results[2], Exception) else {},
            "cost_baseline": results[3] if not isinstance(results[3], Exception) else None,
        }

    @staticmethod
    def _build_context(history, user_message, draft, knowledge, cycle) -> dict:
        return {
            "history": history[-20:],
            "current_draft": draft,
            "knowledge": knowledge,
            "cycle": cycle,
            "user_message": user_message,
        }

    @staticmethod
    def _should_generate_wireframe(draft: dict) -> bool:
        entities = draft.get("entities") if isinstance(draft.get("entities"), list) else []
        use_cases = draft.get("use_cases") if isinstance(draft.get("use_cases"), list) else []
        return len(entities) > 0 or len(use_cases) >= 2

    @staticmethod
    def _gwt_to_strings(gwt_result: dict) -> list[str]:
        scenarios = gwt_result.get("scenarios", [])
        if not scenarios:
            return []
        strings = []
        for s in scenarios:
            if isinstance(s, dict):
                g = s.get("given", "")
                w = s.get("when", "")
                t = s.get("then", "")
                strings.append(
                    "Given {given} When {when} Then {then}".format(given=g, when=w, then=t),
                )
            elif isinstance(s, str):
                strings.append(s)
        return strings

    @staticmethod
    def _calculate_confidence(draft: dict, knowledge: dict) -> float:
        score = 0.5
        if draft.get("description"):
            score += 0.10
        if isinstance(draft.get("entities"), list) and draft["entities"]:
            score += 0.10
        if isinstance(draft.get("acceptance_criteria"), list) and draft["acceptance_criteria"]:
            score += 0.15
        if knowledge.get("similar_requirements"):
            score += 0.10
        if knowledge.get("domain_risks"):
            score += 0.05
        if knowledge.get("cost_baseline"):
            score += 0.05
        if knowledge.get("tech_stack"):
            score += 0.05
        return round(min(score, 1.0), 2)

    @staticmethod
    def _summarize_sources(knowledge: dict) -> list[dict]:
        sources = []
        if knowledge.get("similar_requirements"):
            sources.append({"name": "similar_requirements", "count": len(knowledge["similar_requirements"])})
        if knowledge.get("domain_risks"):
            sources.append({"name": "domain_risks", "count": len(knowledge["domain_risks"])})
        if knowledge.get("tech_stack"):
            sources.append({"name": "tech_stack", "available": True})
        if knowledge.get("cost_baseline"):
            sources.append({"name": "cost_baseline", "available": True})
        return sources
