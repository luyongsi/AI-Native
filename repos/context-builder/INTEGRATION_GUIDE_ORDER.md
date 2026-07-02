"""Quick Integration Guide: Adding ORDER Step to Context Builder Pipeline

## Current Pipeline Flow

The existing pipeline.py uses this flow:

    build_context()
      ├─ Stage 1: Select (from selector.py)
      ├─ Stage 2: Order (from order.py - BASIC)
      ├─ Stage 3: Compress (from compress.py)
      ├─ Stage 4: Isolate (from isolate.py)
      └─ Stage 5: Sanitize (from sanitize.py)

## What's New (Task #26)

We've created an ENHANCED Order implementation (ContextOrdererV2) that replaces
the basic ContextOrderer with:

  - Multi-factor relevance scoring
  - Agent-specific strategies
  - Better metrics tracking

## Integration Options

### Option A: Drop-in Replacement (Recommended)

Replace the existing ContextOrderer with ContextOrdererV2 in pipeline.py:

    # OLD (existing code)
    from order import ContextOrderer
    self.orderer = orderer or ContextOrderer()

    # NEW (Task #26)
    from rankers.context_orderer_v2 import ContextOrdererV2
    self.orderer = orderer or ContextOrdererV2()

Then update the order stage:

    # OLD stage code
    items = self.orderer.order(items, max_tokens=max_tokens)

    # NEW stage code - convert ContextItem to dict, order, convert back
    candidates = [
        {
            'id': f"{it.file}:{it.type}",
            'content': it.content,
            'similarity': it.relevance,
            'token_count': it.tokens,
            'content_type': it.type,
            'timestamp': datetime.now().isoformat(),
        }
        for it in items
    ]

    ordered_candidates, metrics = self.orderer.order_candidates(
        candidates,
        agent_id=target_agent,
        max_tokens=max_tokens,
    )

    # Convert back to ContextItem
    items = [
        ContextItem(
            type=c['content_type'],
            content=c['content'],
            relevance=c.get('relevance_score', c['similarity']),
            position='head',  # Will be set by subsequent stages
            tokens=c['token_count'],
            file=c.get('id', '').split(':')[0] if ':' in c.get('id', '') else c.get('id'),
        )
        for c in ordered_candidates
    ]

### Option B: Side-by-Side (Testing)

Keep both implementations temporarily for A/B testing:

    from order import ContextOrderer as ContextOrdererV1
    from rankers.context_orderer_v2 import ContextOrdererV2

    orderer_v1 = ContextOrdererV1()
    orderer_v2 = ContextOrdererV2()

    # Compare results
    items_v1 = orderer_v1.order(items, max_tokens=max_tokens)
    items_v2 = orderer_v2.order_candidates(candidates, target_agent, max_tokens)

## Data Flow Changes

### Input Format

Previous ContextOrderer expects:
    items: List[ContextItem]

New ContextOrdererV2 expects:
    candidates: List[Dict] with keys:
      - similarity (float): semantic similarity score
      - token_count (int): estimated tokens
      - content_type (str): 'code', 'doc', 'api_schema', etc.
      - timestamp (str, optional): ISO format or Unix timestamp
      - references (int, optional): reference count
      - has_dependency (bool, optional): direct dependency flag

### Output Format

Previous ContextOrderer returns:
    items: List[ContextItem] with position='head'|'mid'|'tail'|'discard'

New ContextOrdererV2 returns:
    (ordered_candidates: List[Dict], metrics: Dict)

Need to map back to ContextItem after ordering.

## Metrics Integration

The new ORDER step produces Prometheus metrics:

    context_builder_order_top_k_size
    context_builder_order_duration_ms
    context_builder_order_duration_seconds
    context_builder_order_candidates_total
    context_builder_order_discarded_total
    context_builder_order_errors_total
    context_builder_order_duration_p50_ms
    context_builder_order_duration_p95_ms
    context_builder_order_duration_p99_ms
    context_builder_order_agent_{agent_id}_total

Add to metrics collection in pipeline._build_response():

    metrics_collection = {
        **selector_metrics,
        **orderer_metrics,
        **compressor_metrics,
        **isolate_metrics,
    }

## Testing the Integration

1. Unit tests (already pass):
    python -m unittest test_order -v

2. Integration test with real pipeline:
    python integration_test.py

3. Performance benchmarking:
    - Run with 100+ candidates
    - Verify P95 latency < 300ms
    - Monitor memory usage

## Backward Compatibility

The old ContextOrderer in order.py remains unchanged. The new ContextOrdererV2
is in rankers/context_orderer_v2.py and doesn't conflict.

To keep backward compatibility, you can:
    1. Keep ContextOrderer as default
    2. Use ContextOrdererV2 for new deployments
    3. Add feature flag to switch between versions

## Configuration Options

### Adjusting Weights

Edit rankers/relevance_scorer.py:

    SEMANTIC_WEIGHT = 0.4      # Increase for higher similarity emphasis
    TIME_WEIGHT = 0.2
    REFERENCE_WEIGHT = 0.2
    DEPENDENCY_WEIGHT = 0.2
    TIME_DECAY_HALF_LIFE = 30  # Days until score reaches 0.5

### Adjusting Agent Strategies

Edit rankers/agent_strategy.py:

    STRATEGIES = {
        "A4": {"api_schema": 1.5, ...},  # Adjust boosts
        ...
    }

    CONTEXT_LIMITS = {
        "A9": 200000,  # Increase for more generous token allocation
        ...
    }

## Troubleshooting

Q: Candidates not appearing in top-K?
A: Check relevance_score calculation. Use examples_order.py to debug scoring.

Q: Agent ordering looks wrong?
A: Verify agent_id is being passed correctly. Check agent strategy in agent_strategy.py.

Q: Performance slow?
A: Profile with time.time(). Check if sorting is bottleneck (unlikely).
   More likely: input candidate processing before ORDER stage.

Q: Metrics not appearing?
A: Ensure metrics dict is merged in pipeline._build_response().
   Check metric names match Prometheus conventions.

## Next Steps

1. Integrate into pipeline.py (Stage 2: Order)
2. Update integration_test.py to test new ORDER behavior
3. Load test with production-scale candidate sets
4. Monitor metrics in staging environment
5. Run A/B test vs old OrdererV1 if needed
"""

print(__doc__)
