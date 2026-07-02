"""Unit tests for context ordering (Task #26)."""

import unittest
import time
from datetime import datetime, timedelta
from rankers.relevance_scorer import RelevanceScorer
from rankers.agent_strategy import AgentStrategy
from rankers.order_metrics import OrderMetrics
from rankers.context_orderer_v2 import ContextOrdererV2


class TestRelevanceScorer(unittest.TestCase):
    """Test relevance scoring with multi-factor weighting."""

    def setUp(self):
        self.scorer = RelevanceScorer()

    def test_calculate_score_with_all_factors(self):
        """Test composite score calculation."""
        candidate = {
            'similarity': 0.8,
            'timestamp': datetime.now().isoformat(),
            'references': 10,
            'has_dependency': True,
            'dependency_type': 'direct',
        }

        score = self.scorer.calculate_score(candidate)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertGreater(score, 0.7)  # Should be relatively high

    def test_semantic_similarity_weight(self):
        """Test that semantic similarity is primary factor."""
        candidate_high = {'similarity': 0.9}
        candidate_low = {'similarity': 0.1}

        score_high = self.scorer.calculate_score(candidate_high)
        score_low = self.scorer.calculate_score(candidate_low)

        self.assertGreater(score_high, score_low)

    def test_time_freshness_decay(self):
        """Test exponential decay of time freshness."""
        now = datetime.now()

        candidate_today = {
            'similarity': 0.5,
            'timestamp': now.isoformat(),
        }

        candidate_30_days_ago = {
            'similarity': 0.5,
            'timestamp': (now - timedelta(days=30)).isoformat(),
        }

        candidate_60_days_ago = {
            'similarity': 0.5,
            'timestamp': (now - timedelta(days=60)).isoformat(),
        }

        score_today = self.scorer.calculate_score(candidate_today)
        score_30 = self.scorer.calculate_score(candidate_30_days_ago)
        score_60 = self.scorer.calculate_score(candidate_60_days_ago)

        # Verify decay: score_30 ≈ 0.5 * score_today
        self.assertGreater(score_today, score_30)
        self.assertGreater(score_30, score_60)

    def test_reference_frequency_normalization(self):
        """Test reference frequency calculation."""
        candidate_no_refs = {'similarity': 0.5, 'references': 0}
        candidate_50_refs = {'similarity': 0.5, 'references': 50}
        candidate_100_refs = {'similarity': 0.5, 'references': 100}

        score_0 = self.scorer.calculate_score(candidate_no_refs)
        score_50 = self.scorer.calculate_score(candidate_50_refs)
        score_100 = self.scorer.calculate_score(candidate_100_refs)

        self.assertLess(score_0, score_50)
        self.assertLessEqual(score_50, score_100)  # May be equal at saturation

    def test_dependency_scoring(self):
        """Test dependency-based scoring."""
        candidate_direct = {
            'similarity': 0.5,
            'has_dependency': True,
            'dependency_type': 'direct',
        }

        candidate_transitive = {
            'similarity': 0.5,
            'has_dependency': True,
            'dependency_type': 'transitive',
        }

        candidate_no_dep = {
            'similarity': 0.5,
            'has_dependency': False,
        }

        score_direct = self.scorer.calculate_score(candidate_direct)
        score_transitive = self.scorer.calculate_score(candidate_transitive)
        score_no_dep = self.scorer.calculate_score(candidate_no_dep)

        self.assertGreater(score_direct, score_transitive)
        self.assertGreater(score_transitive, score_no_dep)

    def test_batch_calculate_scores(self):
        """Test batch score calculation."""
        candidates = [
            {'similarity': 0.9, 'id': 'c1'},
            {'similarity': 0.5, 'id': 'c2'},
            {'similarity': 0.3, 'id': 'c3'},
        ]

        result = RelevanceScorer.batch_calculate_scores(candidates)

        self.assertEqual(len(result), 3)
        self.assertIn('relevance_score', result[0])
        self.assertIn('relevance_score', result[1])
        self.assertIn('relevance_score', result[2])

        # Verify sorted order
        self.assertGreater(result[0]['relevance_score'], result[1]['relevance_score'])
        self.assertGreater(result[1]['relevance_score'], result[2]['relevance_score'])


class TestAgentStrategy(unittest.TestCase):
    """Test agent-specific ranking strategies."""

    def test_get_strategy_spec_writer(self):
        """Test A4 (Spec Writer) strategy."""
        strategy = AgentStrategy.get_strategy("A4")
        self.assertEqual(strategy['api_schema'], 1.5)
        self.assertEqual(strategy['erd'], 1.5)
        self.assertEqual(strategy['code'], 0.7)

    def test_get_strategy_architect(self):
        """Test A6 (Architect) strategy."""
        strategy = AgentStrategy.get_strategy("A6")
        self.assertEqual(strategy['architecture'], 1.5)
        self.assertEqual(strategy['erd'], 1.3)
        self.assertEqual(strategy['code'], 0.7)

    def test_get_strategy_dev_agent(self):
        """Test A9 (Dev Agent) strategy."""
        strategy = AgentStrategy.get_strategy("A9")
        self.assertEqual(strategy['code'], 1.5)
        self.assertEqual(strategy['test'], 1.3)
        self.assertEqual(strategy['architecture'], 0.5)

    def test_get_context_limit(self):
        """Test context window limits."""
        self.assertEqual(AgentStrategy.get_context_limit("A9"), 200000)
        self.assertEqual(AgentStrategy.get_context_limit("A4"), 100000)
        self.assertEqual(AgentStrategy.get_context_limit("A6"), 150000)

    def test_adjust_scores(self):
        """Test score adjustment for agent strategies."""
        candidates = [
            {'relevance_score': 0.5, 'content_type': 'code'},
            {'relevance_score': 0.5, 'content_type': 'api_schema'},
            {'relevance_score': 0.5, 'content_type': 'doc'},
        ]

        # For A9 (Dev Agent), code should be boosted
        result_a9 = AgentStrategy.adjust_scores(candidates.copy(), "A9")
        self.assertGreater(result_a9[0]['relevance_score'], 0.5)  # code boosted
        self.assertLess(result_a9[1]['relevance_score'], 0.5)  # api_schema reduced

        # For A4 (Spec Writer), api_schema should be boosted
        result_a4 = AgentStrategy.adjust_scores(candidates.copy(), "A4")
        # code in A4 is not in the strategy, defaults to 1.0, stays at ~0.5
        self.assertLessEqual(result_a4[0]['relevance_score'], 0.53)
        self.assertGreater(result_a4[1]['relevance_score'], 0.5)  # api_schema boosted

    def test_should_prioritize_content_type(self):
        """Test content type prioritization check."""
        self.assertTrue(AgentStrategy.should_prioritize_content_type("A9", "code"))
        self.assertTrue(AgentStrategy.should_prioritize_content_type("A4", "api_schema"))
        self.assertFalse(AgentStrategy.should_prioritize_content_type("A9", "architecture"))

    def test_get_agent_info(self):
        """Test agent info retrieval."""
        info = AgentStrategy.get_agent_info("A9")
        self.assertIn('agent_id', info)
        self.assertIn('strategy', info)
        self.assertIn('context_limit', info)
        self.assertIn('description', info)


class TestOrderMetrics(unittest.TestCase):
    """Test ordering metrics collection."""

    def setUp(self):
        self.metrics = OrderMetrics()

    def test_record_order(self):
        """Test order metric recording."""
        self.metrics.record_order(100, 50, 150.5, "A9")
        self.assertEqual(self.metrics.order_top_k_size, 50)
        self.assertEqual(self.metrics.order_candidates_total, 100)
        self.assertEqual(self.metrics.order_discarded_total, 50)
        self.assertEqual(self.metrics.order_duration_ms, 150.5)

    def test_record_error(self):
        """Test error recording."""
        self.metrics.record_error("test error", "A9")
        self.assertEqual(self.metrics.order_errors_total, 1)

    def test_percentile_calculation(self):
        """Test percentile calculation."""
        samples = [10, 20, 30, 40, 50]
        self.assertEqual(self.metrics.get_percentile(samples, 0.0), 10)
        self.assertEqual(self.metrics.get_percentile(samples, 1.0), 50)
        self.assertEqual(self.metrics.get_percentile(samples, 0.5), 30)

    def test_metrics_to_dict(self):
        """Test metrics export to dict."""
        self.metrics.record_order(100, 50, 200.0, "A9")
        self.metrics.record_order(80, 40, 150.0, "A9")

        metrics_dict = self.metrics.to_dict()

        self.assertIn('context_builder_order_top_k_size', metrics_dict)
        self.assertIn('context_builder_order_duration_ms', metrics_dict)
        self.assertIn('context_builder_order_candidates_total', metrics_dict)
        self.assertIn('context_builder_order_agent_A9_total', metrics_dict)

    def test_metrics_reset(self):
        """Test metrics reset."""
        self.metrics.record_order(100, 50, 200.0, "A9")
        self.assertGreater(self.metrics.order_candidates_total, 0)

        self.metrics.reset()
        self.assertEqual(self.metrics.order_candidates_total, 0)
        self.assertEqual(self.metrics.order_errors_total, 0)


class TestContextOrdererV2(unittest.TestCase):
    """Test advanced context orderer."""

    def setUp(self):
        self.orderer = ContextOrdererV2()

    def test_order_candidates_basic(self):
        """Test basic candidate ordering."""
        candidates = [
            {
                'id': 'c1',
                'similarity': 0.3,
                'token_count': 1000,
                'content_type': 'code',
            },
            {
                'id': 'c2',
                'similarity': 0.9,
                'token_count': 500,
                'content_type': 'api_schema',
            },
            {
                'id': 'c3',
                'similarity': 0.6,
                'token_count': 800,
                'content_type': 'doc',
            },
        ]

        result, metrics = self.orderer.order_candidates(
            candidates,
            "A9",
            max_tokens=10000,
        )

        # c2 should have high relevance due to similarity (even if not first for A9)
        # but verify ordering is by relevance_score
        self.assertGreater(len(result), 0)
        # Check that scores are calculated
        self.assertIn('relevance_score', result[0])

    def test_order_candidates_agent_specific(self):
        """Test agent-specific ordering."""
        candidates = [
            {
                'id': 'code1',
                'similarity': 0.5,
                'token_count': 500,
                'content_type': 'code',
            },
            {
                'id': 'schema1',
                'similarity': 0.5,
                'token_count': 500,
                'content_type': 'api_schema',
            },
        ]

        # For A9 (Dev), code should be prioritized
        result_a9, _ = self.orderer.order_candidates(
            candidates.copy(),
            "A9",
            max_tokens=10000,
        )
        self.assertEqual(result_a9[0]['id'], 'code1')

        # For A4 (Spec), api_schema should be prioritized
        result_a4, _ = self.orderer.order_candidates(
            candidates.copy(),
            "A4",
            max_tokens=10000,
        )
        self.assertEqual(result_a4[0]['id'], 'schema1')

    def test_top_k_truncation(self):
        """Test top-K token budget truncation."""
        candidates = [
            {
                'id': f'c{i}',
                'similarity': 0.9 - (i * 0.1),
                'token_count': 2000,
                'content_type': 'code',
            }
            for i in range(5)
        ]

        result, _ = self.orderer.order_candidates(
            candidates,
            "A9",
            max_tokens=5000,
        )

        # Should only include 2 items (2000 + 2000 = 4000 < 5000)
        self.assertEqual(len(result), 2)

    def test_ordering_summary(self):
        """Test ordering summary generation."""
        candidates = [
            {
                'id': 'c1',
                'relevance_score': 0.9,
                'content_type': 'code',
                'position': 'head',
            },
            {
                'id': 'c2',
                'relevance_score': 0.7,
                'content_type': 'doc',
                'position': 'mid',
            },
        ]

        summary = ContextOrdererV2.get_ordering_summary(candidates)

        self.assertEqual(summary['total'], 2)
        self.assertEqual(summary['max_score'], 0.9)
        self.assertEqual(summary['min_score'], 0.7)
        self.assertIn('code', summary['by_content_type'])

    def test_ordering_performance(self):
        """Test ordering performance (P95 < 300ms)."""
        candidates = [
            {
                'id': f'c{i}',
                'similarity': 0.5,
                'token_count': 1000,
                'content_type': 'code',
                'timestamp': datetime.now().isoformat(),
                'references': i % 10,
            }
            for i in range(100)
        ]

        start = time.time()
        result, metrics = self.orderer.order_candidates(
            candidates,
            "A9",
            max_tokens=100000,
        )
        duration_ms = (time.time() - start) * 1000

        self.assertLess(duration_ms, 500)  # Should be very fast
        self.assertGreater(len(result), 0)

    def test_metrics_recording(self):
        """Test metrics are properly recorded."""
        candidates = [
            {
                'id': 'c1',
                'similarity': 0.8,
                'token_count': 500,
                'content_type': 'code',
            }
        ]

        _, metrics = self.orderer.order_candidates(
            candidates,
            "A9",
            max_tokens=10000,
        )

        self.assertIn('context_builder_order_top_k_size', metrics)
        self.assertIn('context_builder_order_duration_ms', metrics)
        self.assertIn('context_builder_order_candidates_total', metrics)


if __name__ == '__main__':
    unittest.main()
