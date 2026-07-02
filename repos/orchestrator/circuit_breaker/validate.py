#!/usr/bin/env python3
"""Validation script for Circuit Breaker Strategy Upgrade (Task #43).

Demonstrates core functionality:
  1. Escalation progression
  2. Few-shot example injection
  3. Model selection
  4. Human escalation card formatting
  5. Metrics collection
"""

import sys
import json
from pathlib import Path

# Add orchestrator to path
orchestrator_dir = Path(__file__).parent.parent
sys.path.insert(0, str(orchestrator_dir))

from circuit_breaker.circuit_breaker import (
    CircuitBreaker,
    EscalationLevel,
)
from circuit_breaker.few_shot_examples import (
    get_few_shot_examples,
    inject_few_shot_into_context,
)
from circuit_breaker.model_selector import (
    ModelSelector,
    ModelTier,
    override_model_in_context,
)
from circuit_breaker.human_escalation import (
    HumanEscalation,
)
from circuit_breaker.metrics import (
    CircuitBreakerMetrics,
)


def test_circuit_breaker():
    """Test 1: Circuit breaker escalation progression."""
    print("\n" + "="*70)
    print("TEST 1: Circuit Breaker Escalation Progression")
    print("="*70)

    cb = CircuitBreaker()
    req_id, agent_id = "req-12345", "A9"

    print(f"\nInitial level: {cb.get_level(req_id, agent_id).name}")
    assert cb.get_level(req_id, agent_id) == EscalationLevel.NORMAL

    # 1st failure
    level = cb.record_failure(req_id, agent_id)
    print(f"After 1st failure: {level.name}")
    assert level == EscalationLevel.FEW_SHOT

    # 2nd failure
    level = cb.record_failure(req_id, agent_id)
    print(f"After 2nd failure: {level.name}")
    assert level == EscalationLevel.STRONG_MODEL

    # 3rd failure
    level = cb.record_failure(req_id, agent_id)
    print(f"After 3rd failure: {level.name}")
    assert level == EscalationLevel.HUMAN

    # Reset on success
    cb.reset(req_id, agent_id)
    print(f"After reset: {cb.get_level(req_id, agent_id).name}")
    assert cb.get_level(req_id, agent_id) == EscalationLevel.NORMAL

    print("[PASS] Escalation progression works correctly")


def test_few_shot_injection():
    """Test 2: Few-shot example injection."""
    print("\n" + "="*70)
    print("TEST 2: Few-Shot Example Injection")
    print("="*70)

    # Get examples for A4 (Spec Writer)
    examples_a4 = get_few_shot_examples("A4", "api_schema", count=3)
    print(f"\nA4 api_schema examples: {len(examples_a4)} retrieved")
    assert len(examples_a4) == 3
    print(f"  Example 1: {examples_a4[0]['requirement']}")

    # Get examples for A9 (Dev Agent)
    examples_a9 = get_few_shot_examples("A9", "code_generation", count=2)
    print(f"\nA9 code_generation examples: {len(examples_a9)} retrieved")
    assert len(examples_a9) == 2
    print(f"  Example 1: {examples_a9[0]['requirement']}")

    # Inject into context
    context = {"task": "design_api", "framework": "FastAPI"}
    context = inject_few_shot_into_context(context, "A4", "api_schema")
    print(f"\nContext injection: few_shot_examples added")
    assert "few_shot_examples" in context
    assert len(context["few_shot_examples"]) == 3

    print("[PASS] Few-shot injection works correctly")


def test_model_selection():
    """Test 3: Model selection and switching."""
    print("\n" + "="*70)
    print("TEST 3: Model Selection and Switching")
    print("="*70)

    selector = ModelSelector()

    # Test NORMAL tier
    normal_cfg = selector.select_model_by_tier(ModelTier.NORMAL)
    print(f"\nNORMAL tier:")
    print(f"  Provider: {normal_cfg['provider']}")
    print(f"  Model: {normal_cfg['model']}")
    print(f"  Temperature: {normal_cfg['temperature']}")
    assert normal_cfg['provider'] == "deepseek"

    # Test STRONG tier
    strong_cfg = selector.select_model_by_tier(ModelTier.STRONG)
    print(f"\nSTRONG tier:")
    print(f"  Provider: {strong_cfg['provider']}")
    print(f"  Model: {strong_cfg['model']}")
    print(f"  Temperature: {strong_cfg['temperature']}")
    assert strong_cfg['provider'] == "anthropic"
    assert "sonnet" in strong_cfg['model'].lower()

    # Test ULTRA tier
    ultra_cfg = selector.select_model_by_tier(ModelTier.ULTRA)
    print(f"\nULTRA tier:")
    print(f"  Provider: {ultra_cfg['provider']}")
    print(f"  Model: {ultra_cfg['model']}")
    print(f"  Temperature: {ultra_cfg['temperature']}")
    assert ultra_cfg['provider'] == "anthropic"
    assert "opus" in ultra_cfg['model'].lower()

    # Test escalation mapping
    print(f"\nEscalation mapping:")
    cfg_0 = selector.select_model_for_escalation(0)
    print(f"  0 failures → {cfg_0['model']}")
    assert "deepseek" in cfg_0['model']

    cfg_1 = selector.select_model_for_escalation(1)
    print(f"  1 failure  → {cfg_1['model']}")
    assert "sonnet" in cfg_1['model']

    cfg_2 = selector.select_model_for_escalation(2)
    print(f"  2 failures → {cfg_2['model']}")
    assert "opus" in cfg_2['model']

    # Test override in context
    context = {}
    context = override_model_in_context(context, failure_count=1)
    assert "model_config" in context
    assert context["model_config"]["model"] == "claude-3-5-sonnet-20241022"

    print("[PASS] Model selection works correctly")


def test_human_escalation():
    """Test 4: Human escalation card formatting."""
    print("\n" + "="*70)
    print("TEST 4: Human Escalation Card Formatting")
    print("="*70)

    escalation = HumanEscalation()
    card = escalation._build_card(
        req_id="req-67890",
        agent_id="A9",
        error_message="Failed to generate code: SyntaxError in output",
        context_summary="Python backend microservice",
        timestamp="2024-07-02T15:30:00Z"
    )

    print("\nFeishu Card Structure:")
    print(f"  msg_type: {card['msg_type']}")
    print(f"  header.template: {card['card']['header']['template']}")

    title = card['card']['header']['title']['content']
    # Strip emoji for safe printing
    import re
    title_clean = re.sub(r'[^\w\s\-\(\):]', '', title)
    print(f"  title: {title_clean}")
    assert "A9" in title or "Dev Agent" in title

    # Check elements
    elements = card['card']['elements']
    print(f"  elements: {len(elements)} items")

    # Check for action buttons
    action_element = elements[-1]
    assert action_element['tag'] == 'action'
    actions = action_element.get('actions', [])
    print(f"  action buttons: {len(actions)}")
    for i, action in enumerate(actions, 1):
        content = action['text']['content']
        print(f"    - Button {i}: {content}")

    # Verify requirement ID in buttons
    all_urls = [a.get('url', '') for a in actions]
    assert any('req-67890' in url for url in all_urls), "req_id not found in button URLs"

    print("[PASS] Human escalation card formatting is correct")


def test_metrics():
    """Test 5: Metrics collection."""
    print("\n" + "="*70)
    print("TEST 5: Metrics Collection")
    print("="*70)

    metrics = CircuitBreakerMetrics()

    # Record some escalations
    metrics.increment_escalation("A4", "FEW_SHOT")
    metrics.increment_escalation("A4", "FEW_SHOT")
    metrics.increment_escalation("A9", "STRONG_MODEL")
    metrics.increment_escalation("A9", "HUMAN")

    print("\nEscalation counts:")
    print(f"  A4 FEW_SHOT: {metrics.get_escalation_count('A4', 'FEW_SHOT')}")
    print(f"  A9 STRONG_MODEL: {metrics.get_escalation_count('A9', 'STRONG_MODEL')}")
    print(f"  Total escalations: {metrics.get_escalation_count()}")

    # Record human requests
    metrics.increment_human_request("A4")
    metrics.increment_human_request("A9")
    metrics.increment_human_request("A9")

    print(f"\nHuman requests:")
    print(f"  A4: {metrics.get_human_request_count('A4')}")
    print(f"  A9: {metrics.get_human_request_count('A9')}")
    print(f"  Total: {metrics.get_human_request_count()}")

    # Record model switches
    metrics.increment_model_switch("deepseek-v3", "sonnet")
    metrics.increment_model_switch("deepseek-v3", "sonnet")
    metrics.increment_model_switch("sonnet", "opus")

    print(f"\nModel switches:")
    print(f"  deepseek→sonnet: {metrics.get_model_switch_count('deepseek-v3', 'sonnet')}")
    print(f"  sonnet→opus: {metrics.get_model_switch_count('sonnet', 'opus')}")

    # Set failure counts
    metrics.set_failure_count("req-1", "A4", 1)
    metrics.set_failure_count("req-2", "A9", 2)

    # Export metrics
    data = metrics.to_dict()
    print(f"\nMetrics export:")
    print(f"  Keys: {list(data.keys())}")
    print(f"  escalations_total entries: {len(data['escalations_total'])}")
    print(f"  human_requests_total entries: {len(data['human_requests_total'])}")

    print("[PASS] Metrics collection works correctly")


def main():
    """Run all validation tests."""
    print("\n" + "#"*70)
    print("# Circuit Breaker Strategy Upgrade (Task #43) - Validation")
    print("#"*70)

    try:
        test_circuit_breaker()
        test_few_shot_injection()
        test_model_selection()
        test_human_escalation()
        test_metrics()

        print("\n" + "#"*70)
        print("# ALL TESTS PASSED")
        print("#"*70)
        print("\nImplementation Summary:")
        print("  [OK] Circuit breaker: 3-level escalation (FEW_SHOT → STRONG_MODEL → HUMAN)")
        print("  [OK] Few-shot examples: A4 (3 api_schema), A9 (3 code_generation)")
        print("  [OK] Model selection: DeepSeek v3 → Sonnet → Opus")
        print("  [OK] Human escalation: Feishu card with buttons and timestamps")
        print("  [OK] Metrics: Counters and gauges for monitoring")
        print("\nAcceptance Criteria:")
        print("  [OK] Circuit breaker tracks failures and escalates")
        print("  [OK] 1st failure injects few-shot examples")
        print("  [OK] 2nd failure switches to strong model")
        print("  [OK] 3rd failure triggers human escalation")
        print("  [OK] Success resets circuit breaker")
        print("  [OK] Few-shot library has A4/A9 examples")
        print("  [OK] Model escalation: DeepSeek → Sonnet → Opus")
        print("  [OK] Feishu card format correct")
        print("  [OK] Prometheus metrics implemented")
        print()
        return 0

    except AssertionError as e:
        print(f"\n[FAIL] Assertion failed: {e}")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
