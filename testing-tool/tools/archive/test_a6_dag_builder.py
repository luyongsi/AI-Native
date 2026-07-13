"""
Tests for A6 DAG Builder components: DependencyAnalyzer, DAGBuilder, A6Architect

Run with: pytest test_a6_dag_builder.py -v
"""

import pytest
import json
from datetime import datetime, timezone

# Import components
import sys
sys.path.insert(0, '/d/Vibe Coding/AI Agent/repos/agent-workers')

from a6.dependency_analyzer import DependencyAnalyzer
from a6.dag_builder import DAGBuilder
from a6.complexity_estimator import ComplexityEstimator


class TestDependencyAnalyzer:
    """Test DependencyAnalyzer component."""

    def setup_method(self):
        """Set up test fixtures."""
        self.analyzer = DependencyAnalyzer()

    def test_analyze_basic(self):
        """Test basic analysis with requirement, API schema, and ERD."""
        requirement = {
            "title": "User Management System",
            "description": "Build a user management system with authentication",
            "has_ui": True,
            "has_auth": True,
            "priority": "P1"
        }

        api_schema = {
            "paths": {
                "/api/users": {"get": {}, "post": {}},
                "/api/users/{id}": {"get": {}, "put": {}, "delete": {}},
                "/api/auth/login": {"post": {}},
                "/api/auth/logout": {"post": {}},
            }
        }

        erd = {
            "ddl": "CREATE TABLE users (...)",
            "entities": [
                {"name": "users"},
                {"name": "roles"},
                {"name": "permissions"},
            ]
        }

        result = self.analyzer.analyze(requirement, api_schema, erd)

        # Verify structure
        assert "tasks" in result
        assert "shared_modules" in result
        assert "analysis_summary" in result

        tasks = result["tasks"]
        assert len(tasks) > 0

        # Verify DB tasks are first (priority 1)
        db_tasks = [t for t in tasks if t["type"] == "db_migration"]
        assert len(db_tasks) > 0
        assert all(t["priority"] <= 1.5 for t in db_tasks)

        # Verify API tasks depend on DB
        api_tasks = [t for t in tasks if t["type"] == "api_impl"]
        assert len(api_tasks) > 0
        for api_task in api_tasks:
            assert any(dep.startswith("T_DB") for dep in api_task.get("depends_on", []))

        # Verify UI tasks depend on API
        ui_tasks = [t for t in tasks if t["type"] == "frontend"]
        assert len(ui_tasks) > 0
        for ui_task in ui_tasks:
            assert any(dep.startswith("T_API") for dep in ui_task.get("depends_on", []))

        # Verify shared modules identified
        shared = result["shared_modules"]
        assert len(shared) > 0
        assert any(m["name"] == "data_models" for m in shared)

    def test_db_tasks_no_dependencies(self):
        """Verify DB migration tasks have no dependencies."""
        requirement = {"title": "Test"}
        api_schema = {"paths": {}}
        erd = {
            "ddl": "CREATE TABLE test (...)",
            "entities": [{"name": "test_entity"}]
        }

        result = self.analyzer.analyze(requirement, api_schema, erd)
        tasks = result["tasks"]

        db_tasks = [t for t in tasks if t["type"] == "db_migration"]
        assert len(db_tasks) > 0

        # First DB task (schema) should have no dependencies
        schema_task = [t for t in db_tasks if "SCHEMA" in t["id"]][0]
        assert len(schema_task["depends_on"]) == 0

    def test_api_tasks_depend_on_db(self):
        """Verify API tasks depend on DB migration tasks."""
        requirement = {"title": "Test"}
        api_schema = {
            "paths": {
                "/api/items": {"get": {}, "post": {}},
            }
        }
        erd = {"entities": [{"name": "items"}]}

        result = self.analyzer.analyze(requirement, api_schema, erd)
        tasks = result["tasks"]

        db_tasks = [t for t in tasks if t["type"] == "db_migration"]
        api_tasks = [t for t in tasks if t["type"] == "api_impl"]

        assert len(db_tasks) > 0
        assert len(api_tasks) > 0

        db_task_ids = {t["id"] for t in db_tasks}
        for api_task in api_tasks:
            deps = set(api_task["depends_on"])
            assert len(deps & db_task_ids) > 0, "API task must depend on at least one DB task"

    def test_shared_modules_identification(self):
        """Test identification of shared modules."""
        requirement = {"title": "Test", "has_auth": True}
        api_schema = {
            "paths": {"/api/test": {}},
            "components": {"schemas": {"Test": {}}}
        }
        erd = {"entities": [{"name": "test"}]}

        result = self.analyzer.analyze(requirement, api_schema, erd)
        shared = result["shared_modules"]

        # Should identify standard modules
        module_names = {m["name"] for m in shared}
        assert "common_utils" in module_names or "error_handling" in module_names
        assert any("auth" in m["name"].lower() for m in shared)

    def test_no_ui_when_has_ui_false(self):
        """Verify no UI tasks when has_ui=False."""
        requirement = {"title": "Backend API", "has_ui": False}
        api_schema = {"paths": {"/api/test": {}}}
        erd = {"entities": [{"name": "test"}]}

        result = self.analyzer.analyze(requirement, api_schema, erd)
        tasks = result["tasks"]

        ui_tasks = [t for t in tasks if t["type"] == "frontend"]
        assert len(ui_tasks) == 0


class TestDAGBuilder:
    """Test DAGBuilder component."""

    def setup_method(self):
        """Set up test fixtures."""
        self.builder = DAGBuilder(max_parallel_agents=5, max_dag_depth=4)

    def test_topological_sort_no_cycles(self):
        """Test topological sorting with valid DAG."""
        tasks = [
            {"id": "T1", "estimated_hours": 2},
            {"id": "T2", "estimated_hours": 3, "depends_on": ["T1"]},
            {"id": "T3", "estimated_hours": 4, "depends_on": ["T1"]},
            {"id": "T4", "estimated_hours": 5, "depends_on": ["T2", "T3"]},
        ]

        spec = {}
        dag = self.builder.build(spec, analyzed_tasks=tasks)

        assert dag["has_cycles"] is False
        assert len(dag["cycle_nodes"]) == 0
        assert len(dag["tasks"]) == 4

    def test_critical_path_computation(self):
        """Test critical path calculation."""
        tasks = [
            {"id": "T1", "estimated_hours": 2},
            {"id": "T2", "estimated_hours": 10, "depends_on": ["T1"]},
            {"id": "T3", "estimated_hours": 1, "depends_on": ["T1"]},
            {"id": "T4", "estimated_hours": 2, "depends_on": ["T2", "T3"]},
        ]

        spec = {}
        dag = self.builder.build(spec, analyzed_tasks=tasks)

        critical_path = dag["critical_path"]
        # T1 -> T2 -> T4 is the longest path
        assert "T1" in critical_path
        assert "T2" in critical_path
        assert "T4" in critical_path
        assert dag["critical_path_hours"] == 2 + 10 + 2

    def test_parallel_groups_identification(self):
        """Test parallel group identification."""
        tasks = [
            {"id": "T1", "estimated_hours": 2},
            {"id": "T2", "estimated_hours": 3, "depends_on": ["T1"]},
            {"id": "T3", "estimated_hours": 3, "depends_on": ["T1"]},
            {"id": "T4", "estimated_hours": 5, "depends_on": ["T2", "T3"]},
        ]

        spec = {}
        dag = self.builder.build(spec, analyzed_tasks=tasks)

        parallel_groups = dag["parallel_groups"]
        assert len(parallel_groups) > 0

        # T2 and T3 should be in same level and groupable as parallel
        t2_group = None
        t3_group = None
        for group in parallel_groups:
            if "T2" in group["tasks"]:
                t2_group = group
            if "T3" in group["tasks"]:
                t3_group = group

        # Both should exist and be at same level
        assert t2_group is not None
        assert t3_group is not None

    def test_cycle_detection(self):
        """Test cycle detection."""
        # Create a cycle: T1 -> T2 -> T3 -> T1
        tasks = [
            {"id": "T1", "estimated_hours": 2, "depends_on": ["T3"]},
            {"id": "T2", "estimated_hours": 3, "depends_on": ["T1"]},
            {"id": "T3", "estimated_hours": 4, "depends_on": ["T2"]},
        ]

        spec = {}
        dag = self.builder.build(spec, analyzed_tasks=tasks)

        assert dag["has_cycles"] is True
        assert len(dag["cycle_nodes"]) > 0

    def test_missing_dependency_reference(self):
        """Test handling of missing dependency references."""
        tasks = [
            {"id": "T1", "estimated_hours": 2},
            {"id": "T2", "estimated_hours": 3, "depends_on": ["T_NONEXISTENT"]},
        ]

        spec = {}
        # Should not crash, but may include invalid edge
        dag = self.builder.build(spec, analyzed_tasks=tasks)

        assert "tasks" in dag
        assert len(dag["tasks"]) == 2

    def test_dag_with_analyzed_tasks(self):
        """Test building DAG with pre-analyzed tasks."""
        tasks = [
            {
                "id": "T_DB_MIGRATION",
                "type": "db_migration",
                "title": "Database Migration",
                "depends_on": [],
                "priority": 1,
                "estimated_hours": 2.0,
                "agent_type": "A9",
            },
            {
                "id": "T_API_USERS",
                "type": "api_impl",
                "title": "Implement Users API",
                "depends_on": ["T_DB_MIGRATION"],
                "priority": 2,
                "estimated_hours": 4.0,
                "agent_type": "A9",
            },
        ]

        spec = {}
        dag = self.builder.build(spec, analyzed_tasks=tasks)

        assert dag["total_tasks"] == 2
        assert dag["total_estimated_hours"] == 6.0
        assert dag["has_cycles"] is False


class TestComplexityEstimator:
    """Test ComplexityEstimator component."""

    def setup_method(self):
        """Set up test fixtures."""
        self.estimator = ComplexityEstimator()

    def test_estimate_simple_task(self):
        """Test complexity estimation for simple task."""
        task = {
            "title": "Simple UI page",
            "type": "frontend",
            "components": ["LoginPage"],
        }

        result = self.estimator.estimate(task)

        assert "complexity" in result
        assert "estimated_hours" in result
        assert "confidence" in result
        assert 1 <= result["complexity"] <= 10
        assert result["estimated_hours"] > 0
        assert 0 <= result["confidence"] <= 1.0

    def test_estimate_complex_task(self):
        """Test complexity estimation for complex task."""
        task = {
            "title": "Implement user authentication",
            "type": "backend",
            "description": "Implement OAuth2 authentication with RBAC, token management, and audit logging",
            "auth_required": True,
            "compliance": ["GDPR", "HIPAA"],
            "entities": ["users", "roles", "permissions", "audit_log"],
            "endpoints": [
                "/api/auth/login",
                "/api/auth/logout",
                "/api/auth/refresh",
                "/api/auth/verify",
            ],
            "existing_codebase": True,
        }

        result = self.estimator.estimate(task)

        # Should be high complexity due to auth, compliance, multiple endpoints
        assert result["complexity"] >= 6
        assert result["estimated_hours"] >= 8

    def test_batch_estimation(self):
        """Test batch estimation of multiple tasks."""
        tasks = [
            {"title": "Simple task", "type": "frontend"},
            {"title": "Complex task", "type": "backend", "auth_required": True},
            {"title": "Database migration", "type": "db"},
        ]

        results = self.estimator.estimate_all(tasks)

        assert len(results) == 3
        for task in results:
            assert "complexity" in task
            assert "estimated_hours" in task
            assert "confidence" in task
            assert "complexity_factors" in task


class TestA6Integration:
    """Integration tests for full A6 Architect workflow."""

    @pytest.mark.asyncio
    async def test_end_to_end_dag_building(self):
        """Test complete DAG building pipeline."""
        from a6_architect import A6Architect

        architect = A6Architect()

        requirement = {
            "title": "E-commerce Platform",
            "description": "Build an e-commerce platform with user management and product catalog",
            "has_ui": True,
            "has_auth": True,
        }

        api_schema = {
            "paths": {
                "/api/products": {"get": {}, "post": {}},
                "/api/products/{id}": {"get": {}, "put": {}, "delete": {}},
                "/api/orders": {"get": {}, "post": {}},
                "/api/users": {"get": {}, "post": {}},
            }
        }

        erd = {
            "ddl": "CREATE TABLE...",
            "entities": [
                {"name": "products"},
                {"name": "orders"},
                {"name": "users"},
                {"name": "order_items"},
            ]
        }

        result = await architect.execute(
            req_id="test-req-001",
            requirement=requirement,
            api_schema=api_schema,
            erd=erd,
        )

        # Verify result structure
        assert result["status"] == "completed"
        assert "dag" in result
        assert "summary" in result

        dag = result["dag"]
        summary = result["summary"]

        # Verify DAG properties
        assert dag["total_tasks"] > 0
        assert dag["total_estimated_hours"] > 0
        assert len(dag["critical_path"]) > 0
        assert len(dag["parallel_groups"]) > 0
        assert dag["has_cycles"] is False

        # Verify summary
        assert summary["total_tasks"] > 0
        assert summary["total_estimated_hours"] > 0
        assert summary["critical_path_hours"] > 0

        # Verify tasks are properly structured
        tasks = dag["tasks"]
        assert len(tasks) > 0

        # DB tasks should come first
        db_tasks = [t for t in tasks if t["type"] == "db_migration"]
        assert len(db_tasks) > 0

        # All DB tasks should have priority <= 1.5
        assert all(t["priority"] <= 1.5 for t in db_tasks)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
