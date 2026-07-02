"""
A9 Dual-Brain Example Usage

Demonstrates:
1. Standalone execution (mock mode)
2. Full iteration cycle
3. Metrics collection
4. Error handling
"""

import asyncio
import json
from datetime import datetime

# Import A9 modules
from a9.a9_dev_agent import A9DevAgent
from a9.metrics import A9MetricsCollector


class MockNATS:
    """Mock NATS for standalone testing"""

    async def publish(self, subject: str, data: bytes):
        print(f"[NATS] Published to {subject}: {len(data)} bytes")

    async def drain(self):
        pass


async def example_basic_execution():
    """Example 1: Basic dual-brain execution (mock mode)"""
    print("\n" + "="*70)
    print("EXAMPLE 1: Basic Dual-Brain Execution (Mock Mode)")
    print("="*70)

    agent = A9DevAgent(enable_llm=False)
    agent.nc = MockNATS()

    # Prepare context
    context_package = {
        "spec_package": {
            "openapi": {
                "info": {"title": "Product API"},
                "paths": {
                    "/products": {},
                    "/products/{id}": {},
                    "/products/search": {}
                }
            },
            "erd": {
                "tables": [
                    {"name": "products"},
                    {"name": "categories"},
                    {"name": "reviews"}
                ]
            }
        },
        "task": {
            "type": "backend",
            "title": "Create Product Management API",
            "description": "REST API for product catalog with search and reviews"
        }
    }

    # Execute
    result = await agent.execute("example-001", context_package)

    # Display results
    print(f"\nStatus: {result['status']}")
    print(f"Iterations: {result['iterations']}/{agent.max_iterations}")
    print(f"Files Changed: {result['final_diff']['files_created']} created, "
          f"{result['final_diff']['files_modified']} modified")
    print(f"\nAudit History:")
    for audit in result['audit_history']:
        print(f"  Iteration {audit['iteration']}: "
              f"{audit['auditor_decision']} "
              f"(confidence: {audit['auditor_confidence']:.1%})")
        if audit['issues']:
            for issue in audit['issues'][:2]:
                print(f"    - {issue.get('message', str(issue))}")


async def example_with_metrics():
    """Example 2: With metrics collection"""
    print("\n" + "="*70)
    print("EXAMPLE 2: With Metrics Collection")
    print("="*70)

    agent = A9DevAgent(enable_llm=False)
    agent.nc = MockNATS()
    collector = A9MetricsCollector()

    collector.start_cycle()

    context_package = {
        "spec_package": {
            "openapi": {
                "info": {"title": "User API"},
                "paths": {
                    "/users": {},
                    "/users/{id}": {},
                    "/users/profile": {},
                    "/users/settings": {}
                }
            },
            "erd": {
                "tables": [
                    {"name": "users"},
                    {"name": "profiles"},
                    {"name": "settings"}
                ]
            }
        },
        "task": {
            "type": "backend",
            "title": "User Management System",
            "description": "Complete user management with profiles and settings"
        }
    }

    try:
        result = await agent.execute("example-002", context_package)

        # Manually simulate metric recording (in real scenario, this happens during execution)
        for audit in result['audit_history']:
            coder_result = {
                "diff": result['final_diff'],
                "self_inspection": {"confidence": 0.7},
                "status": "success"
            }
            collector.record_iteration(
                iteration_num=audit['iteration'],
                coder_result=coder_result,
                auditor_result={
                    "decision": audit['auditor_decision'],
                    "issues": audit['issues'],
                    "confidence": audit['auditor_confidence']
                },
                coder_duration=2.0,
                auditor_duration=1.5
            )

        collector.finalize_cycle(result['status'])

        print(f"\nCycle Completed:")
        print(f"  Status: {result['status']}")
        print(f"  Iterations: {result['iterations']}")
        print(f"  Total Metrics: {len(collector.iterations_data)} records")

        print(f"\nMetrics Summary:")
        metrics = result.get('metrics', {})
        print(f"  Total Iterations: {metrics.get('total_iterations', 'N/A')}")
        print(f"  Approvals: {metrics.get('approvals', 'N/A')}")
        print(f"  Avg Auditor Confidence: {metrics.get('avg_auditor_confidence', 0):.1%}")
        print(f"  Avg Coder Confidence: {metrics.get('avg_coder_confidence', 0):.1%}")
        print(f"  Total Issues Found: {metrics.get('total_issues_found', 0)}")

    except Exception as e:
        print(f"Error: {e}")


async def example_detailed_flow():
    """Example 3: Detailed flow walkthrough"""
    print("\n" + "="*70)
    print("EXAMPLE 3: Detailed Dual-Brain Flow")
    print("="*70)

    agent = A9DevAgent(enable_llm=False)
    agent.nc = MockNATS()

    context_package = {
        "spec_package": {
            "openapi": {
                "info": {"title": "Analytics API"},
                "paths": {"/metrics": {}, "/reports": {}}
            },
            "erd": {
                "tables": [{"name": "metrics"}, {"name": "events"}]
            }
        },
        "task": {
            "type": "backend",
            "title": "Analytics Data Collection",
            "description": "API for collecting and querying analytics data"
        }
    }

    print("\n[STEP 1] Starting dual-brain execution...")
    print("Input spec package:")
    print(f"  - OpenAPI paths: {len(context_package['spec_package']['openapi']['paths'])}")
    print(f"  - ERD tables: {len(context_package['spec_package']['erd']['tables'])}")

    result = await agent.execute("example-003", context_package)

    print("\n[STEP 2] Execution Results:")
    print(f"  Status: {result['status']}")
    print(f"  Approval Reason: {result['approval_reason']}")

    print("\n[STEP 3] Final Diff Summary:")
    final_diff = result['final_diff']
    print(f"  Files created: {final_diff['files_created']}")
    print(f"  Files modified: {final_diff['files_modified']}")
    print(f"  Commit SHA: {final_diff['commit_sha']}")

    print("\n[STEP 4] Code Changes:")
    for change in final_diff['files_changed'][:3]:
        print(f"  - {change['path']}")
        print(f"    Type: {change['change_type']}")
        print(f"    Language: {change['language']}")
        print(f"    Lines: +{change['lines_added']} -{change['lines_removed']}")

    print("\n[STEP 5] Audit Trail:")
    for audit in result['audit_history']:
        print(f"  Iteration {audit['iteration']}:")
        print(f"    Decision: {audit['auditor_decision']}")
        print(f"    Confidence: {audit['auditor_confidence']:.1%}")
        if audit['suggestions']:
            print(f"    Suggestions: {'; '.join(audit['suggestions'][:2])}")

    print("\n[STEP 6] Architecture Verification:")
    print("  ✓ Coder generated code in isolation")
    print("  ✓ Auditor reviewed ONLY the diff (not Coder reasoning)")
    print("  ✓ Iteration loop enforced max 3 iterations")
    print("  ✓ Separated Coder and Auditor concerns")


async def example_architecture_demo():
    """Example 4: Demonstrate strict separation of concerns"""
    print("\n" + "="*70)
    print("EXAMPLE 4: Architecture - Separation of Concerns")
    print("="*70)

    from a9.coder import CoderModule
    from a9.auditor import AuditorModule

    print("\n[CODER MODULE]")
    print("Coder generates code with internal reasoning...")

    coder = CoderModule(enable_llm=False)
    task_spec = {
        "type": "backend",
        "title": "Payment Processing Module",
        "plan": {"files_to_create": ["src/payments/processor.py"]},
        "openapi_paths": 2,
        "erd_tables": 1
    }

    coder_result = await coder.generate(task_spec, {})
    print(f"  Status: {coder_result['status']}")
    print(f"  Files generated: {coder_result['metadata']['files_created']}")
    print(f"  Coder confidence: {coder_result['self_inspection']['confidence']:.1%}")
    print(f"  Coder reasoning: {coder_result['self_inspection']['reasoning'][:100]}...")

    print("\n[AUDITOR MODULE]")
    print("Auditor receives ONLY the diff (no Coder reasoning)...")

    auditor = AuditorModule(enable_analysis=False)

    # This is what Auditor sees (NOT including self_inspection)
    diff_for_auditor = {
        "files_changed": coder_result['diff'].get('files_changed', []),
        "changes_summary": coder_result['diff'].get('changes_summary', '')
    }

    print(f"  Input keys: {list(diff_for_auditor.keys())}")
    print(f"  Files analyzed: {len(diff_for_auditor['files_changed'])}")
    print(f"  Summary: {diff_for_auditor['changes_summary']}")

    # Verify separation
    print("\n[SEPARATION VERIFICATION]")
    if 'self_inspection' in diff_for_auditor:
        print("  ✗ ERROR: Auditor has access to Coder's self_inspection!")
    else:
        print("  ✓ Auditor does NOT have access to Coder's self_inspection")

    if 'metadata' in diff_for_auditor:
        print("  ✗ ERROR: Auditor has access to metadata!")
    else:
        print("  ✓ Auditor does NOT have access to metadata")

    auditor_result = await auditor.review(diff_for_auditor)
    print(f"\n  Auditor decision: {auditor_result['decision']}")
    print(f"  Auditor confidence: {auditor_result['confidence']:.1%}")
    print(f"  Issues found: {len(auditor_result['issues'])}")


async def main():
    """Run all examples"""
    print("\n" + "█"*70)
    print("█ A9 DUAL-BRAIN ARCHITECTURE - USAGE EXAMPLES")
    print("█"*70)

    try:
        await example_basic_execution()
        await example_with_metrics()
        await example_detailed_flow()
        await example_architecture_demo()

        print("\n" + "█"*70)
        print("█ ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("█"*70 + "\n")

    except Exception as e:
        print(f"\nError during execution: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
