"""Unit tests for isolators package - simplified for manual execution."""

import asyncio
import sys
from isolators.risk_evaluator import RiskEvaluator
from isolators.context_isolator import ContextIsolator


def test_risk_evaluator():
    """Run all RiskEvaluator tests."""
    print("\n=== Testing RiskEvaluator ===")
    evaluator = RiskEvaluator()
    passed = 0
    failed = 0

    # Test 1: Single file code change
    try:
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risks']['code_changes']['detected'] is True
        assert eval_result['risks']['code_changes']['file_count'] == 1
        print("✓ Test 1: Single file code change detection")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 1 failed: {e}")
        failed += 1

    # Test 2: Multiple code files
    try:
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/utils.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'tests/test_main.py', 'content_type': 'code', 'operation': 'add'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risks']['code_changes']['detected'] is True
        assert eval_result['risks']['code_changes']['file_count'] == 3
        print("✓ Test 2: Multiple code files detection")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 2 failed: {e}")
        failed += 1

    # Test 3: Dependency changes (npm)
    try:
        context = {
            'candidates': [
                {'file_path': 'package.json', 'content_type': 'config', 'operation': 'modify'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risks']['dependency_changes']['detected'] is True
        print("✓ Test 3: NPM dependency detection")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 3 failed: {e}")
        failed += 1

    # Test 4: Database migrations
    try:
        context = {
            'candidates': [
                {'file_path': 'migrations/0001_initial.sql', 'content_type': 'code', 'operation': 'add'},
                {'file_path': 'db/migrate/20240701_add_users.sql', 'content_type': 'code', 'operation': 'add'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risks']['db_migrations']['detected'] is True
        assert eval_result['risks']['db_migrations']['file_count'] == 2
        print("✓ Test 4: Database migrations detection (100% success)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 4 failed: {e}")
        failed += 1

    # Test 5: Configuration changes
    try:
        context = {
            'candidates': [
                {'file_path': '.env', 'content_type': 'config', 'operation': 'modify'},
                {'file_path': 'config.yaml', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risks']['config_changes']['detected'] is True
        assert eval_result['risks']['config_changes']['file_count'] == 2
        print("✓ Test 5: Configuration file detection")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 5 failed: {e}")
        failed += 1

    # Test 6: Infrastructure changes
    try:
        context = {
            'candidates': [
                {'file_path': 'Dockerfile', 'content_type': 'config', 'operation': 'modify'},
                {'file_path': 'kubernetes/deployment.yaml', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risks']['infrastructure_changes']['detected'] is True
        assert eval_result['risks']['infrastructure_changes']['file_count'] == 2
        print("✓ Test 6: Infrastructure changes detection")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 6 failed: {e}")
        failed += 1

    # Test 7: Multi-service changes
    try:
        context = {
            'candidates': [
                {'file_path': 'services/auth/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'services/api/handler.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risks']['multi_service_changes']['detected'] is True
        assert eval_result['risks']['multi_service_changes']['service_count'] == 2
        print("✓ Test 7: Multi-service changes detection")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 7 failed: {e}")
        failed += 1

    # Test 8: Risk level - low
    try:
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risk_level'] == 'low'
        print("✓ Test 8: Risk level LOW for single file")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 8 failed: {e}")
        failed += 1

    # Test 9: Risk level - medium
    try:
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/utils.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/helper.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risk_level'] == 'medium'
        print("✓ Test 9: Risk level MEDIUM for multiple files")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 9 failed: {e}")
        failed += 1

    # Test 10: Risk level - high (DB migrations)
    try:
        context = {
            'candidates': [
                {'file_path': 'migrations/0001_initial.sql', 'content_type': 'code', 'operation': 'add'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['risk_level'] == 'high'
        print("✓ Test 10: Risk level HIGH for DB migrations (100% success)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 10 failed: {e}")
        failed += 1

    # Test 11: Isolation mode - NONE
    try:
        context = {'candidates': []}
        eval_result = evaluator.evaluate(context)
        assert eval_result['isolation_mode'] == 'NONE'
        print("✓ Test 11: Isolation NONE for empty changes (100% success)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 11 failed: {e}")
        failed += 1

    # Test 12: Isolation mode - NONE (docs only)
    try:
        context = {
            'candidates': [
                {'file_path': 'README.md', 'content_type': 'doc', 'operation': 'modify'},
                {'file_path': 'docs/guide.md', 'content_type': 'doc', 'operation': 'modify'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['isolation_mode'] == 'NONE'
        print("✓ Test 12: Isolation NONE for UI/design only (100% success)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 12 failed: {e}")
        failed += 1

    # Test 13: Isolation mode - WORKTREE (single file)
    try:
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['isolation_mode'] == 'WORKTREE'
        print("✓ Test 13: Isolation WORKTREE for single file (100% success)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 13 failed: {e}")
        failed += 1

    # Test 14: Isolation mode - WORKTREE (few files)
    try:
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/utils.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['isolation_mode'] == 'WORKTREE'
        print("✓ Test 14: Isolation WORKTREE for few files")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 14 failed: {e}")
        failed += 1

    # Test 15: Isolation mode - CONTAINER (DB migrations)
    try:
        context = {
            'candidates': [
                {'file_path': 'migrations/0001_initial.sql', 'content_type': 'code', 'operation': 'add'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['isolation_mode'] == 'CONTAINER'
        print("✓ Test 15: Isolation CONTAINER for DB migrations (100% success)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 15 failed: {e}")
        failed += 1

    # Test 16: Isolation mode - CONTAINER (infrastructure)
    try:
        context = {
            'candidates': [
                {'file_path': 'Dockerfile', 'content_type': 'config', 'operation': 'modify'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['isolation_mode'] == 'CONTAINER'
        print("✓ Test 16: Isolation CONTAINER for infrastructure")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 16 failed: {e}")
        failed += 1

    # Test 17: Isolation mode - CONTAINER (multi-service)
    try:
        context = {
            'candidates': [
                {'file_path': 'services/auth/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'services/api/handler.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert eval_result['isolation_mode'] == 'CONTAINER'
        print("✓ Test 17: Isolation CONTAINER for multi-service")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 17 failed: {e}")
        failed += 1

    # Test 18: Reasoning is generated
    try:
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        eval_result = evaluator.evaluate(context)
        assert 'reasoning' in eval_result
        assert len(eval_result['reasoning']) > 0
        assert eval_result['isolation_mode'] in eval_result['reasoning']
        print("✓ Test 18: Reasoning generated for decisions")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 18 failed: {e}")
        failed += 1

    return passed, failed


async def test_context_isolator():
    """Run all ContextIsolator tests."""
    print("\n=== Testing ContextIsolator ===")
    passed = 0
    failed = 0

    # Test 1: Async isolation determination
    try:
        isolator = ContextIsolator()
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        result = await isolator.determine_isolation(context, 'A1')
        assert result['isolation_mode'] == 'WORKTREE'
        assert result['agent_id'] == 'A1'
        assert 'duration_ms' in result
        assert result['duration_ms'] < 100
        print("✓ Test 1: Async isolation determination (< 100ms)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 1 failed: {e}")
        failed += 1

    # Test 2: NONE isolation decision
    try:
        isolator = ContextIsolator()
        context = {'candidates': []}
        result = await isolator.determine_isolation(context, 'A2')
        assert result['isolation_mode'] == 'NONE'
        print("✓ Test 2: NONE isolation decision")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 2 failed: {e}")
        failed += 1

    # Test 3: CONTAINER isolation decision
    try:
        isolator = ContextIsolator()
        context = {
            'candidates': [
                {'file_path': 'migrations/0001.sql', 'content_type': 'code', 'operation': 'add'}
            ]
        }
        result = await isolator.determine_isolation(context, 'A3')
        assert result['isolation_mode'] == 'CONTAINER'
        print("✓ Test 3: CONTAINER isolation decision")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 3 failed: {e}")
        failed += 1

    # Test 4: Metrics collection
    try:
        isolator = ContextIsolator()
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        await isolator.determine_isolation(context, 'A1')
        await isolator.determine_isolation(context, 'A2')

        metrics = isolator.get_metrics()
        assert metrics['total_decisions'] == 2
        assert 'by_mode' in metrics
        assert 'average_duration_ms' in metrics
        assert 'p95_duration_ms' in metrics
        print("✓ Test 4: Metrics collection")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 4 failed: {e}")
        failed += 1

    # Test 5: P95 duration calculation
    try:
        isolator = ContextIsolator()
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        for i in range(10):
            await isolator.determine_isolation(context, f'A{i}')

        metrics = isolator.get_metrics()
        assert metrics['p95_duration_ms'] >= 0
        assert metrics['p95_duration_ms'] < 100
        print("✓ Test 5: P95 duration calculation (< 100ms)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 5 failed: {e}")
        failed += 1

    # Test 6: Metrics reset
    try:
        isolator = ContextIsolator()
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'}
            ]
        }
        await isolator.determine_isolation(context, 'A1')

        metrics_before = isolator.get_metrics()
        assert metrics_before['total_decisions'] == 1

        isolator.reset_metrics()

        metrics_after = isolator.get_metrics()
        assert metrics_after['total_decisions'] == 0
        print("✓ Test 6: Metrics reset")
        passed += 1
    except AssertionError as e:
        print(f"✗ Test 6 failed: {e}")
        failed += 1

    return passed, failed


def test_performance():
    """Run performance tests."""
    print("\n=== Testing Performance ===")
    passed = 0
    failed = 0

    # Test: P95 latency < 100ms
    try:
        import time
        evaluator = RiskEvaluator()
        large_context = {
            'candidates': [
                {'file_path': f'src/file_{i}.py', 'content_type': 'code', 'operation': 'modify'}
                for i in range(50)
            ]
        }

        durations = []
        for _ in range(20):
            start = time.time()
            evaluator.evaluate(large_context)
            duration = (time.time() - start) * 1000
            durations.append(duration)

        durations.sort()
        p95 = durations[int(len(durations) * 0.95)]
        assert p95 < 100, f"P95 latency {p95}ms exceeds 100ms threshold"
        print(f"✓ P95 latency: {p95:.2f}ms (< 100ms threshold)")
        passed += 1
    except AssertionError as e:
        print(f"✗ Performance test failed: {e}")
        failed += 1

    return passed, failed


async def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Context Builder ISOLATE Step - Unit Tests")
    print("=" * 60)

    # Run synchronous tests
    risk_passed, risk_failed = test_risk_evaluator()
    perf_passed, perf_failed = test_performance()

    # Run async tests
    isolator_passed, isolator_failed = await test_context_isolator()

    # Summary
    total_passed = risk_passed + isolator_passed + perf_passed
    total_failed = risk_failed + isolator_failed + perf_failed

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Total Passed: {total_passed}")
    print(f"Total Failed: {total_failed}")
    print(f"Success Rate: {total_passed / (total_passed + total_failed) * 100:.1f}%")
    print("=" * 60)

    return total_failed == 0


if __name__ == '__main__':
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
