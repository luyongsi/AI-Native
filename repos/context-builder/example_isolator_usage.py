"""Integration example: Using ContextIsolator in the pipeline."""

import asyncio
from isolators.context_isolator import ContextIsolator
from isolators.metrics import get_metrics


async def example_usage():
    """Demonstrate ContextIsolator usage."""
    print("\n=== ContextIsolator Integration Example ===\n")

    # Initialize isolator
    isolator = ContextIsolator()

    # Example 1: Simple code change
    print("Example 1: Simple code change")
    context = {
        'candidates': [
            {
                'file_path': 'src/main.py',
                'content_type': 'code',
                'operation': 'modify',
            }
        ]
    }
    result = await isolator.determine_isolation(context, 'agent-001')
    print(f"  Isolation Mode: {result['isolation_mode']}")
    print(f"  Risk Level: {result['risk_level']}")
    print(f"  Duration: {result['duration_ms']}ms")
    print()

    # Example 2: Database migration
    print("Example 2: Database migration")
    context = {
        'candidates': [
            {
                'file_path': 'migrations/0042_add_users_table.sql',
                'content_type': 'code',
                'operation': 'add',
            }
        ]
    }
    result = await isolator.determine_isolation(context, 'agent-002')
    print(f"  Isolation Mode: {result['isolation_mode']}")
    print(f"  Risk Level: {result['risk_level']}")
    print(f"  Duration: {result['duration_ms']}ms")
    print()

    # Example 3: Multi-service infrastructure change
    print("Example 3: Multi-service infrastructure change")
    context = {
        'candidates': [
            {
                'file_path': 'services/auth/Dockerfile',
                'content_type': 'config',
                'operation': 'modify',
            },
            {
                'file_path': 'services/api/deployment.yaml',
                'content_type': 'config',
                'operation': 'modify',
            }
        ]
    }
    result = await isolator.determine_isolation(context, 'agent-003')
    print(f"  Isolation Mode: {result['isolation_mode']}")
    print(f"  Risk Level: {result['risk_level']}")
    print(f"  Risks Detected: {result['risk_details']}")
    print()

    # Example 4: Documentation only
    print("Example 4: Documentation only (no isolation needed)")
    context = {
        'candidates': [
            {
                'file_path': 'docs/README.md',
                'content_type': 'doc',
                'operation': 'modify',
            }
        ]
    }
    result = await isolator.determine_isolation(context, 'agent-004')
    print(f"  Isolation Mode: {result['isolation_mode']}")
    print(f"  Risk Level: {result['risk_level']}")
    print()

    # Show metrics
    print("Collected Metrics:")
    metrics = isolator.get_metrics()
    print(f"  Total Decisions: {metrics['total_decisions']}")
    print(f"  By Mode: {metrics['by_mode']}")
    print(f"  Average Duration: {metrics['average_duration_ms']}ms")
    print(f"  P95 Duration: {metrics['p95_duration_ms']}ms")
    print()


if __name__ == '__main__':
    asyncio.run(example_usage())
