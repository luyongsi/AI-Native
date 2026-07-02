"""
Unit tests for A2 Knowledge Analyst RAG integration.

Tests cover:
- RAG retriever with API and fallback
- Knowledge fusion logic
- LLM summary generation
- Complexity estimation
- Risk assessment
- Neo4j graceful degradation
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

# Import modules to test
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from a2.rag_retriever import RAGRetriever
from a2_knowledge_analyst import A2KnowledgeAnalyst


class TestRAGRetriever:
    """Test RAG Retriever functionality."""

    @pytest.fixture
    def retriever(self):
        """Create a RAG retriever instance."""
        return RAGRetriever(api_base_url="http://localhost:8000")

    @pytest.mark.asyncio
    async def test_search_similar_requirements_success(self, retriever):
        """Test successful requirement search via API."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "results": [
                    {
                        "id": 1,
                        "content_id": "kb-001",
                        "content_type": "requirement",
                        "content_text": "Order management system",
                        "similarity": 0.92,
                        "metadata": {"tags": ["order", "CRUD"]},
                    }
                ]
            }
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            results = await retriever.search_similar_requirements("order management", limit=5)
            assert len(results) == 1
            assert results[0]["similarity"] == 0.92

    @pytest.mark.asyncio
    async def test_search_similar_requirements_fallback(self, retriever):
        """Test fallback to static KB when API fails."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("API timeout")
            )

            results = await retriever.search_similar_requirements("order", limit=5)
            assert len(results) > 0
            assert any("order" in r.get("content_text", "").lower() for r in results)

    @pytest.mark.asyncio
    async def test_search_similar_code(self, retriever):
        """Test code pattern search."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            results = await retriever.search_similar_code("async def process", limit=10)
            assert isinstance(results, list)

    def test_fallback_search_keyword_matching(self, retriever):
        """Test static KB fallback with keyword matching."""
        results = retriever._fallback_search("payment gateway", limit=5)
        assert len(results) > 0
        # Should find payment-related items
        assert any("payment" in r.get("content_text", "").lower() for r in results)

    def test_fallback_search_limits(self, retriever):
        """Test that fallback search respects limit."""
        results = retriever._fallback_search("model", limit=2)
        assert len(results) <= 2


class TestA2KnowledgeAnalyst:
    """Test A2 Knowledge Analyst core functionality."""

    @pytest.fixture
    def analyst(self):
        """Create an A2 Knowledge Analyst instance."""
        with patch("base_worker.nats.connect", new_callable=AsyncMock):
            return A2KnowledgeAnalyst(nats_url="nats://localhost:4222")

    def test_extract_code_patterns(self, analyst):
        """Test code pattern extraction from similar requirements."""
        similar_reqs = [
            {
                "id": "kb-001",
                "content_text": "Order management",
                "metadata": {"tags": ["order", "CRUD", "batch"]},
            },
            {
                "id": "kb-002",
                "content_text": "Payment gateway",
                "metadata": {"tags": ["payment", "gateway", "idempotent"]},
            },
        ]

        patterns = analyst._extract_code_patterns(similar_reqs)
        assert len(patterns) > 0
        assert any("order" in p.lower() or "CRUD" in p for p in patterns)

    def test_assess_risks(self, analyst):
        """Test risk assessment based on similar requirements."""
        similar_reqs = [
            {"metadata": {"tags": ["concurrency", "redis"]}},
            {"metadata": {"tags": ["idempotent", "payment"]}},
        ]

        risks = analyst._assess_risks(similar_reqs)
        assert len(risks) > 0
        assert any(r["risk"] == "concurrency" for r in risks)
        assert any(r["risk"] == "idempotent" for r in risks)

    def test_estimate_complexity_low(self, analyst):
        """Test complexity estimation with many similar requirements."""
        similar_reqs = [
            {"metadata": {"tags": ["order"]}},
            {"metadata": {"tags": ["order"]}},
            {"metadata": {"tags": ["order"]}},
        ]
        dependencies = []

        complexity = analyst._estimate_complexity(similar_reqs, dependencies)
        assert complexity["level"] == "low"
        assert complexity["score"] < 0.5
        assert complexity["estimated_days"] <= 10

    def test_estimate_complexity_high(self, analyst):
        """Test complexity estimation with many dependencies."""
        similar_reqs = []
        dependencies = [
            {"service": "svc1", "downstream": ["svc2", "svc3"]},
            {"service": "svc2", "downstream": ["svc4"]},
            {"service": "svc3", "downstream": ["svc5"]},
        ]

        complexity = analyst._estimate_complexity(similar_reqs, dependencies)
        assert complexity["level"] == "high"
        assert complexity["score"] > 0.5
        assert complexity["estimated_days"] > 10

    def test_calculate_quality_score_high(self, analyst):
        """Test quality score calculation with rich knowledge package."""
        knowledge_package = {
            "similar_requirements": [
                {"id": "kb-001", "title": "Order management", "similarity": 0.92},
                {"id": "kb-002", "title": "Payment gateway", "similarity": 0.87},
            ],
            "suggested_approach": "Apply existing RBAC and workflow patterns",
            "risks": [
                {"risk": "concurrency", "description": "High concurrency issues"},
            ],
            "dependencies": [
                {"service": "auth", "downstream": []},
            ],
        }

        score = analyst._calculate_quality_score(knowledge_package)
        assert 0 <= score <= 1
        assert score > 0.4  # Should be high quality

    def test_calculate_quality_score_low(self, analyst):
        """Test quality score calculation with minimal knowledge package."""
        knowledge_package = {
            "similar_requirements": [],
            "suggested_approach": None,
            "risks": [],
            "dependencies": [],
        }

        score = analyst._calculate_quality_score(knowledge_package)
        assert 0 <= score <= 1
        assert score < 0.1  # Should be low quality

    @pytest.mark.asyncio
    async def test_summarize_similar_requirements_with_llm(self, analyst):
        """Test LLM-based summary generation."""
        similar_reqs = [
            {
                "content_text": "Order management system with CRUD operations"
            },
            {
                "content_text": "Payment gateway integration for multiple providers"
            },
        ]

        with patch.object(analyst, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Apply established patterns for order management and payment integration"

            summary = await analyst.summarize_similar_requirements(similar_reqs)
            assert "established patterns" in summary or len(summary) > 0

    @pytest.mark.asyncio
    async def test_summarize_similar_requirements_fallback(self, analyst):
        """Test fallback summary generation without LLM."""
        similar_reqs = [
            {"content_text": "Order management system"},
            {"content_text": "Payment gateway integration"},
        ]

        with patch.object(analyst, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = None  # LLM fails

            summary = await analyst.summarize_similar_requirements(similar_reqs)
            assert len(summary) > 0
            assert "similar requirements" in summary.lower()

    @pytest.mark.asyncio
    async def test_query_dependencies_unavailable(self, analyst):
        """Test Neo4j graceful fallback when unavailable."""
        result = await analyst.query_dependencies("req-123")
        assert result == []

    @pytest.mark.asyncio
    async def test_query_related_prs(self, analyst):
        """Test related PRs query."""
        result = await analyst.query_related_prs("order management system")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_fuse_knowledge(self, analyst):
        """Test knowledge fusion logic."""
        similar_reqs = [
            {
                "content_id": "kb-001",
                "content_text": "Order management module",
                "similarity": 0.92,
                "metadata": {"tags": ["order", "CRUD"]},
            }
        ]
        dependencies = [{"service": "auth", "downstream": []}]
        related_prs = []

        with patch.object(
            analyst, "summarize_similar_requirements", new_callable=AsyncMock
        ) as mock_summary:
            mock_summary.return_value = "Reuse existing patterns"

            package = await analyst.fuse_knowledge(
                similar_reqs, dependencies, related_prs, "order management"
            )

            assert "similar_requirements" in package
            assert "dependencies" in package
            assert "suggested_approach" in package
            assert "estimated_complexity" in package
            assert len(package["similar_requirements"]) == 1
            assert len(package["dependencies"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
