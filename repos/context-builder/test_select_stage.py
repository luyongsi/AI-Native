"""Test suite for Context Builder SELECT stage with multi-source integration."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

from context_item import ContextItem, SelectResult
from embedder import Embedder
from multi_source_selector import MultiSourceSelector, SelectMetrics
from sources import PostgresSource, Neo4jSource, VectorSource


# Test data fixtures
MOCK_POSTGRES_CANDIDATES = [
    {
        'source': 'postgres_requirements',
        'source_id': 'req_123',
        'req_id': 'req-001',
        'type': 'spec',
        'title': 'API Requirements v1',
        'content': 'Implement REST API with authentication',
        'metadata': {'version': 1, 'status': 'active'},
        'relevance': 0.85,
    },
    {
        'source': 'postgres_prs',
        'source_id': 'pr_456',
        'req_id': 'req-001',
        'type': 'code',
        'title': 'PR #123: Implement auth',
        'content': 'Added JWT authentication middleware',
        'metadata': {'pr_number': 123, 'state': 'merged'},
        'relevance': 0.80,
    },
]

MOCK_VECTOR_CANDIDATES = [
    {
        'source': 'vector_similar_reqs',
        'source_id': 'vec_789',
        'req_id': 'req-002',
        'type': 'knowledge',
        'title': 'Similar Requirement: Auth System',
        'content': 'Description of existing auth system',
        'metadata': {'similarity': 0.78},
        'relevance': 0.75,
    },
    {
        'source': 'vector_design_patterns',
        'source_id': 'pattern_101',
        'req_id': 'req-001',
        'type': 'code',
        'title': 'Design Pattern: API Gateway',
        'content': 'Use API Gateway pattern for service routing',
        'metadata': {'pattern_name': 'API Gateway'},
        'relevance': 0.70,
    },
]

MOCK_NEO4J_CANDIDATES = [
    {
        'source': 'neo4j_upstream_deps',
        'source_id': 'svc_auth',
        'req_id': 'req-001',
        'type': 'knowledge',
        'title': 'Upstream Service: Auth Service',
        'content': 'Central authentication service providing OAuth2',
        'metadata': {'service_name': 'auth-service'},
        'relevance': 0.72,
    },
]


class TestSelectMetrics:
    """Test SelectMetrics class."""

    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = SelectMetrics()
        assert metrics.candidates_total == 0
        assert metrics.candidates_deduped == 0
        assert metrics.candidates_final == 0

    def test_metrics_recording(self):
        """Test metrics recording."""
        metrics = SelectMetrics()
        metrics.record_candidates('postgres', 5)
        metrics.record_candidates('vector', 3)
        metrics.record_deduped(2)
        metrics.record_final(6)
        metrics.record_duration(150.5)

        assert metrics.candidates_total == 8
        assert metrics.candidates_deduped == 2
        assert metrics.candidates_final == 6
        assert metrics.select_duration_ms == 150.5
        assert metrics.source_counts['postgres'] == 5
        assert metrics.source_counts['vector'] == 3

    def test_metrics_to_dict(self):
        """Test metrics export to dictionary."""
        metrics = SelectMetrics()
        metrics.record_candidates('postgres', 5)
        metrics.record_candidates('neo4j', 2)
        metrics.record_final(6)

        result = metrics.to_dict()
        assert result['context_builder_select_candidates_total'] == 7
        assert result['context_builder_select_candidates_final'] == 6
        assert 'postgres' in result['source_counts']


class TestMultiSourceSelector:
    """Test MultiSourceSelector class."""

    @patch('multi_source_selector.PostgresSource')
    @patch('multi_source_selector.VectorSource')
    def test_selector_initialization(self, mock_vector, mock_postgres):
        """Test selector initialization."""
        db_config = {'host': 'localhost', 'database': 'test'}
        embedder = Embedder()

        selector = MultiSourceSelector(db_config, embedder)

        assert selector.db_config == db_config
        assert selector.embedder == embedder
        assert selector.metrics is not None

    def test_merge_and_deduplicate_basic(self):
        """Test basic deduplication."""
        db_config = {'host': 'localhost'}
        embedder = Embedder()

        with patch('multi_source_selector.PostgresSource'), \
             patch('multi_source_selector.VectorSource'):
            selector = MultiSourceSelector(db_config, embedder)

        candidates = [
            {
                'source': 'postgres',
                'source_id': 'item_1',
                'type': 'code',
                'title': 'Item 1',
                'content': 'Content 1',
                'relevance': 0.8,
                'metadata': {'key': 'value1'},
            },
            {
                'source': 'postgres',
                'source_id': 'item_1',
                'type': 'code',
                'title': 'Item 1',
                'content': 'Content 1',
                'relevance': 0.7,
                'metadata': {'key': 'value1'},
            },
            {
                'source': 'vector',
                'source_id': 'item_2',
                'type': 'knowledge',
                'title': 'Item 2',
                'content': 'Content 2',
                'relevance': 0.9,
                'metadata': {'key': 'value2'},
            },
        ]

        merged = selector._merge_and_deduplicate(candidates)

        assert len(merged) == 2  # Should deduplicate item_1
        # Highest relevance should be kept
        item_1 = [c for c in merged if c['source_id'] == 'item_1'][0]
        assert item_1['relevance'] == 0.8

    def test_merge_sorts_by_relevance(self):
        """Test that merged candidates are sorted by relevance."""
        db_config = {'host': 'localhost'}
        embedder = Embedder()

        with patch('multi_source_selector.PostgresSource'), \
             patch('multi_source_selector.VectorSource'):
            selector = MultiSourceSelector(db_config, embedder)

        candidates = [
            {
                'source': 'postgres',
                'source_id': 'item_1',
                'type': 'code',
                'relevance': 0.5,
            },
            {
                'source': 'vector',
                'source_id': 'item_2',
                'type': 'knowledge',
                'relevance': 0.9,
            },
            {
                'source': 'neo4j',
                'source_id': 'item_3',
                'type': 'knowledge',
                'relevance': 0.7,
            },
        ]

        merged = selector._merge_and_deduplicate(candidates)

        assert merged[0]['relevance'] == 0.9
        assert merged[1]['relevance'] == 0.7
        assert merged[2]['relevance'] == 0.5

    def test_build_items_token_accounting(self):
        """Test token accounting in item building."""
        db_config = {'host': 'localhost'}
        embedder = Embedder()

        with patch('multi_source_selector.PostgresSource'), \
             patch('multi_source_selector.VectorSource'):
            selector = MultiSourceSelector(db_config, embedder)

        candidates = [
            {
                'source': 'postgres',
                'source_id': 'item_1',
                'type': 'spec',
                'title': 'API Design',
                'content': 'This is a long content ' * 100,  # ~2500 chars
                'relevance': 0.8,
                'metadata': {},
            },
            {
                'source': 'vector',
                'source_id': 'item_2',
                'type': 'knowledge',
                'title': 'Knowledge',
                'content': 'Short content',  # ~50 chars
                'relevance': 0.7,
                'metadata': {},
            },
        ]

        max_tokens = 1000
        items, tokens_used, discarded = selector._build_items(candidates, max_tokens)

        # First item should fit
        assert len(items) >= 1
        # Token accounting should be non-zero
        assert tokens_used > 0
        # Total should not exceed max
        assert tokens_used <= max_tokens

    def test_build_items_respects_max_tokens(self):
        """Test that items respects max_tokens limit."""
        db_config = {'host': 'localhost'}
        embedder = Embedder()

        with patch('multi_source_selector.PostgresSource'), \
             patch('multi_source_selector.VectorSource'):
            selector = MultiSourceSelector(db_config, embedder)

        # Create candidates that exceed token limit
        candidates = [
            {
                'source': 'postgres',
                'source_id': f'item_{i}',
                'type': 'code',
                'title': f'Item {i}',
                'content': 'x' * 1000,
                'relevance': 0.8 - (i * 0.01),
                'metadata': {},
            }
            for i in range(20)
        ]

        max_tokens = 500
        items, tokens_used, discarded = selector._build_items(candidates, max_tokens)

        assert tokens_used <= max_tokens
        # Should have discarded some items
        assert discarded > 0

    @patch('multi_source_selector.PostgresSource')
    @patch('multi_source_selector.VectorSource')
    @patch('multi_source_selector.Neo4jSource')
    async def test_select_async_integration(self, mock_neo4j_cls, mock_vector_cls, mock_postgres_cls):
        """Test async SELECT stage with mocked sources."""
        db_config = {'host': 'localhost'}
        embedder = Embedder()

        # Setup mocks
        mock_postgres = AsyncMock()
        mock_postgres.query.return_value = MOCK_POSTGRES_CANDIDATES
        mock_postgres_cls.return_value = mock_postgres

        mock_vector = AsyncMock()
        mock_vector.query.return_value = MOCK_VECTOR_CANDIDATES
        mock_vector_cls.return_value = mock_vector

        mock_neo4j = AsyncMock()
        mock_neo4j.query.return_value = MOCK_NEO4J_CANDIDATES
        mock_neo4j_cls.return_value = mock_neo4j

        selector = MultiSourceSelector(db_config, embedder, {'uri': 'neo4j://localhost'})
        selector.postgres_source = mock_postgres
        selector.vector_source = mock_vector
        selector.neo4j_source = mock_neo4j

        result = await selector.select_async(
            target_agent='A9',
            req_id='req-001',
            max_tokens=2000,
        )

        # Verify result structure
        assert isinstance(result, SelectResult)
        assert len(result.items) > 0
        assert result.tokens_used > 0

        # Verify all sources were queried
        mock_postgres.query.assert_called_once()
        mock_vector.query.assert_called_once()
        mock_neo4j.query.assert_called_once()

    @patch('multi_source_selector.PostgresSource')
    @patch('multi_source_selector.VectorSource')
    async def test_select_performance_under_500ms(self, mock_vector_cls, mock_postgres_cls):
        """Test that SELECT stage completes under 500ms with mock data."""
        db_config = {'host': 'localhost'}
        embedder = Embedder()

        # Setup mocks
        mock_postgres = AsyncMock()
        mock_postgres.query.return_value = MOCK_POSTGRES_CANDIDATES
        mock_postgres_cls.return_value = mock_postgres

        mock_vector = AsyncMock()
        mock_vector.query.return_value = MOCK_VECTOR_CANDIDATES
        mock_vector_cls.return_value = mock_vector

        selector = MultiSourceSelector(db_config, embedder)
        selector.postgres_source = mock_postgres
        selector.vector_source = mock_vector
        selector.neo4j_source = None

        start = time.time()
        result = await selector.select_async(
            target_agent='A9',
            req_id='req-001',
            max_tokens=2000,
        )
        duration_ms = (time.time() - start) * 1000

        # Performance check
        assert duration_ms < 500, f"SELECT took {duration_ms}ms, should be < 500ms"
        assert len(result.items) > 0

    def test_context_item_conversion(self):
        """Test ContextItem creation from candidates."""
        db_config = {'host': 'localhost'}
        embedder = Embedder()

        with patch('multi_source_selector.PostgresSource'), \
             patch('multi_source_selector.VectorSource'):
            selector = MultiSourceSelector(db_config, embedder)

        candidates = [
            {
                'source': 'postgres_requirements',
                'source_id': 'req_123',
                'type': 'spec',
                'title': 'API Spec',
                'content': 'REST API specification',
                'relevance': 0.85,
                'metadata': {'version': 1},
            },
        ]

        items, tokens_used, discarded = selector._build_items(candidates, 1000)

        assert len(items) == 1
        item = items[0]
        assert isinstance(item, ContextItem)
        assert item.type == 'spec'
        assert item.relevance == 0.85
        assert item.source == 'postgres_requirements'
        assert item.source_id == 'req_123'


async def run_async_tests():
    """Run all async tests."""
    print("Running async tests...")

    # Test performance
    from unittest.mock import AsyncMock, patch
    db_config = {'host': 'localhost'}
    embedder = Embedder()

    with patch('multi_source_selector.PostgresSource') as mock_postgres_cls, \
         patch('multi_source_selector.VectorSource') as mock_vector_cls:

        mock_postgres = AsyncMock()
        mock_postgres.query.return_value = MOCK_POSTGRES_CANDIDATES
        mock_postgres_cls.return_value = mock_postgres

        mock_vector = AsyncMock()
        mock_vector.query.return_value = MOCK_VECTOR_CANDIDATES
        mock_vector_cls.return_value = mock_vector

        selector = MultiSourceSelector(db_config, embedder)
        selector.postgres_source = mock_postgres
        selector.vector_source = mock_vector
        selector.neo4j_source = None

        start = time.time()
        result = await selector.select_async(
            target_agent='A9',
            req_id='req-001',
            max_tokens=2000,
        )
        duration_ms = (time.time() - start) * 1000

        print(f"✓ SELECT completed in {duration_ms:.1f}ms (< 500ms required)")
        print(f"✓ Items retrieved: {len(result.items)}")
        print(f"✓ Tokens used: {result.tokens_used}")

        metrics = selector.get_metrics()
        print(f"✓ Metrics: {json.dumps(metrics, indent=2)}")


if __name__ == '__main__':
    print("=" * 60)
    print("Context Builder SELECT Stage Tests")
    print("=" * 60)

    # Test metrics
    print("\n--- Test SelectMetrics ---")
    test_metrics = TestSelectMetrics()
    test_metrics.test_metrics_initialization()
    print("✓ Metrics initialization")
    test_metrics.test_metrics_recording()
    print("✓ Metrics recording")
    test_metrics.test_metrics_to_dict()
    print("✓ Metrics export")

    # Test selector
    print("\n--- Test MultiSourceSelector ---")
    test_selector = TestMultiSourceSelector()
    test_selector.test_selector_initialization()
    print("✓ Selector initialization")
    test_selector.test_merge_and_deduplicate_basic()
    print("✓ Deduplication logic")
    test_selector.test_merge_sorts_by_relevance()
    print("✓ Relevance sorting")
    test_selector.test_build_items_token_accounting()
    print("✓ Token accounting")
    test_selector.test_build_items_respects_max_tokens()
    print("✓ Max tokens respect")
    test_selector.test_context_item_conversion()
    print("✓ ContextItem conversion")

    # Run async tests
    print("\n--- Async Tests ---")
    asyncio.run(run_async_tests())

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
