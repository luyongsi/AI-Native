"""Integration example: Using the new ORDER step with Context Builder."""

import asyncio
from datetime import datetime
from rankers.context_orderer_v2 import ContextOrdererV2
from rankers.relevance_scorer import RelevanceScorer
from rankers.agent_strategy import AgentStrategy


def example_basic_ordering():
    """Example 1: Basic candidate ordering."""
    print("=== Example 1: Basic Ordering ===\n")

    orderer = ContextOrdererV2()

    # Sample candidates (typically from COMPRESS stage)
    candidates = [
        {
            'id': 'file_auth.py',
            'similarity': 0.85,
            'token_count': 1200,
            'content_type': 'code',
            'timestamp': datetime.now().isoformat(),
            'references': 5,
            'has_dependency': True,
            'dependency_type': 'direct',
        },
        {
            'id': 'api_spec.json',
            'similarity': 0.72,
            'token_count': 800,
            'content_type': 'api_schema',
            'timestamp': datetime.now().isoformat(),
            'references': 12,
            'has_dependency': False,
        },
        {
            'id': 'architecture.md',
            'similarity': 0.65,
            'token_count': 1500,
            'content_type': 'doc',
            'timestamp': datetime.now().isoformat(),
            'references': 8,
            'has_dependency': False,
        },
    ]

    # Order for Dev Agent (A9)
    ordered, metrics = orderer.order_candidates(
        candidates,
        agent_id="A9",
        max_tokens=10000,
    )

    print(f"Ordered candidates for A9 (Dev Agent):")
    for i, candidate in enumerate(ordered, 1):
        score = candidate.get('relevance_score', 0.0)
        print(f"  {i}. {candidate['id']}: score={score:.3f}, tokens={candidate['token_count']}")

    print(f"\nMetrics: {metrics['context_builder_order_top_k_size']} items selected")
    print(f"Duration: {metrics['context_builder_order_duration_ms']:.1f}ms\n")


def example_agent_specific_ordering():
    """Example 2: Different ordering for different agents."""
    print("=== Example 2: Agent-Specific Ordering ===\n")

    orderer = ContextOrdererV2()

    candidates = [
        {
            'id': 'impl.py',
            'similarity': 0.6,
            'token_count': 1000,
            'content_type': 'code',
            'timestamp': datetime.now().isoformat(),
            'references': 3,
        },
        {
            'id': 'api_schema.yaml',
            'similarity': 0.6,
            'token_count': 500,
            'content_type': 'api_schema',
            'timestamp': datetime.now().isoformat(),
            'references': 15,
        },
        {
            'id': 'architecture.md',
            'similarity': 0.6,
            'token_count': 800,
            'content_type': 'architecture',
            'timestamp': datetime.now().isoformat(),
            'references': 10,
        },
    ]

    # Order for different agents
    for agent_id in ["A4", "A6", "A9"]:
        ordered, _ = orderer.order_candidates(
            [c.copy() for c in candidates],
            agent_id=agent_id,
            max_tokens=10000,
        )

        print(f"Agent {agent_id}:")
        for i, c in enumerate(ordered[:2], 1):  # Top 2
            print(f"  {i}. {c['id']}: score={c.get('relevance_score', 0):.3f}")
        print()


def example_token_budget_truncation():
    """Example 3: Top-K selection with token budget constraints."""
    print("=== Example 3: Token Budget Truncation ===\n")

    orderer = ContextOrdererV2()

    # Create 10 candidates
    candidates = [
        {
            'id': f'candidate_{i}',
            'similarity': 0.9 - (i * 0.05),
            'token_count': 2000,
            'content_type': 'code',
            'timestamp': datetime.now().isoformat(),
        }
        for i in range(10)
    ]

    # Order with different token limits
    for token_limit in [5000, 10000, 20000]:
        ordered, metrics = orderer.order_candidates(
            [c.copy() for c in candidates],
            agent_id="A9",
            max_tokens=token_limit,
        )
        total_tokens = sum(c['token_count'] for c in ordered)
        print(f"Token limit: {token_limit} -> {len(ordered)} items selected "
              f"({total_tokens} tokens)")

    print()


def example_relevance_scorer():
    """Example 4: Understanding relevance scoring factors."""
    print("=== Example 4: Relevance Scoring Breakdown ===\n")

    scorer = RelevanceScorer()

    candidate = {
        'similarity': 0.8,  # 40% weight: 0.8 * 0.4 = 0.32
        'timestamp': datetime.now().isoformat(),  # ~1.0 freshness * 0.2 = 0.20
        'references': 30,  # ~0.6 normalized * 0.2 = 0.12
        'has_dependency': True,
        'dependency_type': 'direct',  # 1.0 * 0.2 = 0.20
    }

    score = scorer.calculate_score(candidate)

    print(f"Candidate: {candidate['id'] if 'id' in candidate else 'unknown'}")
    print(f"Factors:")
    print(f"  - Semantic similarity (40%): 0.8")
    print(f"  - Time freshness (20%): 1.0 (today)")
    print(f"  - Reference frequency (20%): 0.6 (30 refs)")
    print(f"  - Dependency score (20%): 1.0 (direct)")
    print(f"Final composite score: {score:.3f}\n")


def example_agent_strategies():
    """Example 5: Understanding agent strategies."""
    print("=== Example 5: Agent Strategies ===\n")

    for agent_id in ["A4", "A6", "A9", "A10"]:
        info = AgentStrategy.get_agent_info(agent_id)
        print(f"{info['description']}")
        print(f"  Context limit: {info['context_limit']} tokens")
        print(f"  Content type priorities:")

        # Show top 3 boosted content types
        strategy = info['strategy']
        boosted = sorted(
            [(ct, boost) for ct, boost in strategy.items() if boost > 1.0],
            key=lambda x: x[1],
            reverse=True,
        )

        for content_type, boost in boosted[:3]:
            print(f"    - {content_type}: {boost}x boost")
        print()


def example_metrics_tracking():
    """Example 6: Metrics collection and analysis."""
    print("=== Example 6: Metrics Tracking ===\n")

    orderer = ContextOrdererV2()

    # Simulate multiple ordering operations
    for batch_num in range(3):
        candidates = [
            {
                'id': f'batch_{batch_num}_c{i}',
                'similarity': 0.8,
                'token_count': 1000,
                'content_type': 'code',
            }
            for i in range(20)
        ]

        orderer.order_candidates(
            candidates,
            agent_id="A9",
            max_tokens=50000,
        )

    # Collect metrics
    metrics = orderer.get_metrics()

    print("Aggregated Metrics:")
    print(f"  Total candidates processed: {metrics['context_builder_order_candidates_total']}")
    print(f"  Total discarded: {metrics['context_builder_order_discarded_total']}")
    print(f"  Current top-K size: {metrics['context_builder_order_top_k_size']}")
    print(f"  Average duration: {metrics['context_builder_order_duration_p50_ms']:.1f}ms (P50)")
    print(f"  P95 latency: {metrics['context_builder_order_duration_p95_ms']:.1f}ms")
    print(f"  A9 operations: {metrics.get('context_builder_order_agent_A9_total', 0)}")
    print()


if __name__ == '__main__':
    example_basic_ordering()
    example_agent_specific_ordering()
    example_token_budget_truncation()
    example_relevance_scorer()
    example_agent_strategies()
    example_metrics_tracking()

    print("=== All examples completed ===")
