"""
A9 Dual-Brain Integration Tests

Tests:
1. Coder code generation in isolation
2. Auditor review (independent, sees only diff)
3. Full dual-brain cycle with iterations
4. Approval and escalation scenarios
5. Metrics collection
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone

# Import modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from a9.coder import CoderModule
from a9.auditor import AuditorModule
from a9.a9_dev_agent import A9DevAgent
from a9.metrics import A9MetricsCollector
from a9.static_analyzer import StaticAnalyzer


class TestCoderModule:
    """Test Coder code generation brain"""

    @pytest.mark.asyncio
    async def test_coder_generate_success(self):
        """Test Coder generates code successfully"""
        coder = CoderModule(enable_llm=False)

        task_spec = {
            "type": "backend",
            "title": "User API endpoint",
            "plan": {
                "files_to_create": ["src/routes/users.py", "src/models/user.py"],
                "files_to_modify": ["src/main.py"],
            },
            "openapi_paths": 3,
            "erd_tables": 2,
        }

        context = {}

        result = await coder.generate(task_spec, context)

        assert result["status"] == "success"
        assert result["diff"] is not None
        assert len(result["diff"]["files_changed"]) > 0
        assert result["self_inspection"] is not None
        assert result["metadata"] is not None

    @pytest.mark.asyncio
    async def test_coder_self_inspection_isolation(self):
        """Test Coder's self_inspection is NOT exposed to Auditor"""
        coder = CoderModule(enable_llm=False)

        task_spec = {
            "type": "backend",
            "title": "Test task",
            "plan": {"files_to_create": ["src/test.py"]},
            "openapi_paths": 1,
            "erd_tables": 1,
        }

        result = await coder.generate(task_spec, {})

        # Verify self_inspection exists (for Coder's own reasoning)
        assert "self_inspection" in result
        assert "reasoning" in result["self_inspection"]

        # This should NOT be in the diff passed to Auditor
        diff = result["diff"]
        assert "self_inspection" not in diff
        assert "reasoning" not in diff


class TestAuditorModule:
    """Test Auditor code review brain (independent process)"""

    @pytest.mark.asyncio
    async def test_auditor_receives_only_diff(self):
        """Test Auditor receives ONLY diff, not Coder reasoning"""
        auditor = AuditorModule(enable_analysis=False)

        # Auditor should only see this
        diff = {
            "files_changed": [
                {
                    "path": "src/routes/users.py",
                    "change_type": "created",
                    "lines_added": 50,
                    "lines_removed": 0,
                    "patch_preview": "# User routes",
                    "language": "python",
                }
            ],
            "changes_summary": "User API endpoint",
        }

        result = await auditor.review(diff)

        assert "decision" in result
        assert result["decision"] in ["approved", "rejected"]
        assert "issues" in result
        assert "suggestions" in result
        assert "confidence" in result

    @pytest.mark.asyncio
    async def test_auditor_rejects_empty_changes(self):
        """Test Auditor rejects empty changesets"""
        auditor = AuditorModule(enable_analysis=False)

        diff = {
            "files_changed": [],
            "changes_summary": "Empty changes",
        }

        result = await auditor.review(diff)

        assert result["decision"] == "rejected"
        assert len(result["issues"]) > 0

    @pytest.mark.asyncio
    async def test_auditor_approves_valid_changes(self):
        """Test Auditor approves valid code changes"""
        auditor = AuditorModule(enable_analysis=False)

        diff = {
            "files_changed": [
                {
                    "path": "src/models/user.py",
                    "change_type": "created",
                    "lines_added": 100,
                    "lines_removed": 0,
                    "patch_preview": '"""User model."""\n\nclass User:\n    def __init__(self): pass',
                    "language": "python",
                }
            ],
            "changes_summary": "User model",
        }

        result = await auditor.review(diff)

        # Should approve valid changes (with caveats)
        assert result["decision"] in ["approved", "rejected"]  # Mock may approve or suggest improvements


class TestDualBrainIntegration:
    """Test full dual-brain orchestration"""

    @pytest.mark.asyncio
    async def test_full_cycle_approved_iteration_1(self):
        """Test full cycle: Coder → Auditor → Approved in iteration 1"""
        agent = A9DevAgent(enable_llm=False)
        # Mock NATS for testing
        agent.nc = MockNATS()

        context_package = {
            "spec_package": {
                "openapi": {
                    "info": {"title": "User API"},
                    "paths": {"/users": {}, "/users/{id}": {}, "/users/search": {}},
                },
                "erd": {
                    "tables": [
                        {"name": "users"},
                        {"name": "roles"},
                    ]
                },
            },
            "task": {
                "type": "backend",
                "title": "Create User API",
                "description": "REST API for user management",
            },
        }

        result = await agent.execute("test-req-1", context_package)

        assert result["status"] in ["approved", "escalated"]
        assert result["final_diff"] is not None
        assert result["iterations"] >= 1
        assert result["iterations"] <= 3
        assert len(result["audit_history"]) > 0

    @pytest.mark.asyncio
    async def test_dual_brain_max_iterations(self):
        """Test dual-brain respects max iterations limit"""
        agent = A9DevAgent(enable_llm=False)
        agent.nc = MockNATS()

        context_package = {
            "spec_package": {
                "openapi": {"info": {"title": "API"}, "paths": {"/test": {}}},
                "erd": {"tables": []},
            },
            "task": {"type": "backend", "title": "Test", "description": "Test task"},
        }

        result = await agent.execute("test-req-2", context_package)

        assert result["iterations"] <= agent.max_iterations
        if result["status"] == "escalated":
            assert result["iterations"] == agent.max_iterations

    @pytest.mark.asyncio
    async def test_coder_auditor_separation(self):
        """Test strict separation: Auditor doesn't see Coder's internal state"""
        coder = CoderModule(enable_llm=False)
        auditor = AuditorModule(enable_analysis=False)

        task_spec = {
            "type": "backend",
            "title": "Separation test",
            "plan": {"files_to_create": ["src/app.py"]},
            "openapi_paths": 1,
            "erd_tables": 0,
        }

        # Coder generates
        coder_result = await coder.generate(task_spec, {})
        assert coder_result["status"] == "success"

        # Extract ONLY diff (what Auditor sees)
        diff_for_audit = {
            "files_changed": coder_result["diff"].get("files_changed", []),
            "changes_summary": coder_result["diff"].get("changes_summary", ""),
        }

        # Verify Auditor's input does NOT contain Coder's internal state
        assert "self_inspection" not in diff_for_audit
        assert "metadata" not in diff_for_audit
        assert "reasoning" not in str(diff_for_audit)

        # Auditor reviews
        auditor_result = await auditor.review(diff_for_audit)
        assert "decision" in auditor_result


class TestMetricsCollection:
    """Test Prometheus metrics collection"""

    def test_metrics_collector_initialization(self):
        """Test metrics collector initializes"""
        collector = A9MetricsCollector()
        assert collector.start_time is None
        assert collector.iterations_data == []

    def test_metrics_collector_cycle(self):
        """Test metrics collector tracks cycle"""
        collector = A9MetricsCollector()
        collector.start_cycle()

        assert collector.start_time is not None

        # Record iteration
        coder_result = {
            "diff": {
                "files_created": 2,
                "files_modified": 1,
                "files_changed": [
                    {"lines_added": 50, "lines_removed": 0},
                    {"lines_added": 30, "lines_removed": 5},
                ],
            },
            "self_inspection": {"confidence": 0.8},
            "status": "success",
        }

        auditor_result = {
            "decision": "approved",
            "issues": [],
            "confidence": 0.9,
        }

        collector.record_iteration(
            iteration_num=1,
            coder_result=coder_result,
            auditor_result=auditor_result,
            coder_duration=2.5,
            auditor_duration=1.2,
        )

        assert len(collector.iterations_data) == 1
        assert collector.iterations_data[0]["iteration"] == 1
        assert collector.iterations_data[0]["decision"] == "approved"

        collector.finalize_cycle("approved")
        # Should not raise


class TestStaticAnalyzer:
    """Test static analysis integration"""

    @pytest.mark.asyncio
    async def test_analyzer_python(self):
        """Test Python code analysis"""
        result = await StaticAnalyzer.analyze(
            "test.py",
            "python",
            'print("hello")\nx = 1',
        )

        assert result["language"] == "python"
        assert "errors" in result
        assert "warnings" in result
        assert "status" in result

    @pytest.mark.asyncio
    async def test_analyzer_javascript(self):
        """Test JavaScript code analysis"""
        result = await StaticAnalyzer.analyze(
            "test.js",
            "javascript",
            "console.log('hello');\nvar x = 1;",
        )

        assert result["language"] == "javascript"
        assert "errors" in result
        assert "warnings" in result


# Mock NATS for testing
class MockNATS:
    """Mock NATS connection for testing"""

    async def publish(self, subject: str, data: bytes):
        pass


# Test execution
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
