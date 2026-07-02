"""Unit tests for isolators package."""

import pytest
import asyncio
from isolators.risk_evaluator import RiskEvaluator
from isolators.context_isolator import ContextIsolator


class TestRiskEvaluator:
    """Test RiskEvaluator risk detection and classification."""

    def setup_method(self):
        """Setup for each test."""
        self.evaluator = RiskEvaluator()

    def test_detect_code_changes_single_file(self):
        """Test detection of single code file change."""
        context = {
            'candidates': [
                {
                    'file_path': 'src/main.py',
                    'content_type': 'code',
                    'operation': 'modify',
                }
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['code_changes']['detected'] is True
        assert evaluation['risks']['code_changes']['file_count'] == 1

    def test_detect_code_changes_multiple_files(self):
        """Test detection of multiple code file changes."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/utils.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'tests/test_main.py', 'content_type': 'code', 'operation': 'add'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['code_changes']['detected'] is True
        assert evaluation['risks']['code_changes']['file_count'] == 3

    def test_detect_dependency_changes_npm(self):
        """Test detection of npm dependency changes."""
        context = {
            'candidates': [
                {'file_path': 'package.json', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['dependency_changes']['detected'] is True
        assert evaluation['risks']['dependency_changes']['file_count'] == 1

    def test_detect_dependency_changes_python(self):
        """Test detection of Python dependency changes."""
        context = {
            'candidates': [
                {'file_path': 'requirements.txt', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['dependency_changes']['detected'] is True

    def test_detect_db_migrations(self):
        """Test detection of database migrations."""
        context = {
            'candidates': [
                {'file_path': 'migrations/0001_initial.sql', 'content_type': 'code', 'operation': 'add'},
                {'file_path': 'db/migrate/20240701_add_users.sql', 'content_type': 'code', 'operation': 'add'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['db_migrations']['detected'] is True
        assert evaluation['risks']['db_migrations']['file_count'] == 2

    def test_detect_config_changes(self):
        """Test detection of configuration file changes."""
        context = {
            'candidates': [
                {'file_path': '.env', 'content_type': 'config', 'operation': 'modify'},
                {'file_path': 'config.yaml', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['config_changes']['detected'] is True
        assert evaluation['risks']['config_changes']['file_count'] == 2

    def test_detect_infrastructure_changes(self):
        """Test detection of infrastructure changes."""
        context = {
            'candidates': [
                {'file_path': 'Dockerfile', 'content_type': 'config', 'operation': 'modify'},
                {'file_path': 'kubernetes/deployment.yaml', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['infrastructure_changes']['detected'] is True
        assert evaluation['risks']['infrastructure_changes']['file_count'] == 2

    def test_detect_multi_service_changes(self):
        """Test detection of multi-service changes."""
        context = {
            'candidates': [
                {'file_path': 'services/auth/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'services/api/handler.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risks']['multi_service_changes']['detected'] is True
        assert evaluation['risks']['multi_service_changes']['service_count'] == 2

    def test_risk_level_low_single_file(self):
        """Test low risk classification for single file change."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risk_level'] == 'low'

    def test_risk_level_medium_multiple_files(self):
        """Test medium risk classification for multiple code files."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/utils.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/helper.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risk_level'] == 'medium'

    def test_risk_level_medium_with_dependencies(self):
        """Test medium risk classification for dependency changes."""
        context = {
            'candidates': [
                {'file_path': 'package.json', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risk_level'] == 'medium'

    def test_risk_level_high_db_migrations(self):
        """Test high risk classification for database migrations."""
        context = {
            'candidates': [
                {'file_path': 'migrations/0001_initial.sql', 'content_type': 'code', 'operation': 'add'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risk_level'] == 'high'

    def test_risk_level_high_infrastructure(self):
        """Test high risk classification for infrastructure changes."""
        context = {
            'candidates': [
                {'file_path': 'Dockerfile', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risk_level'] == 'high'

    def test_risk_level_high_multi_service(self):
        """Test high risk classification for multi-service changes."""
        context = {
            'candidates': [
                {'file_path': 'services/auth/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'services/api/handler.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['risk_level'] == 'high'

    def test_isolation_mode_none_no_changes(self):
        """Test NONE isolation for read-only operations."""
        context = {'candidates': []}
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'NONE'

    def test_isolation_mode_none_documentation_only(self):
        """Test NONE isolation for documentation-only changes."""
        context = {
            'candidates': [
                {'file_path': 'README.md', 'content_type': 'doc', 'operation': 'modify'},
                {'file_path': 'docs/guide.md', 'content_type': 'doc', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'NONE'

    def test_isolation_mode_worktree_single_file(self):
        """Test WORKTREE isolation for single file code change."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'WORKTREE'

    def test_isolation_mode_worktree_few_files(self):
        """Test WORKTREE isolation for few code files."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/utils.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'WORKTREE'

    def test_isolation_mode_container_db_migrations(self):
        """Test CONTAINER isolation for database migrations."""
        context = {
            'candidates': [
                {'file_path': 'migrations/0001_initial.sql', 'content_type': 'code', 'operation': 'add'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'CONTAINER'

    def test_isolation_mode_container_infrastructure(self):
        """Test CONTAINER isolation for infrastructure changes."""
        context = {
            'candidates': [
                {'file_path': 'Dockerfile', 'content_type': 'config', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'CONTAINER'

    def test_isolation_mode_container_dependencies(self):
        """Test CONTAINER isolation for dependency changes."""
        context = {
            'candidates': [
                {'file_path': 'package.json', 'content_type': 'config', 'operation': 'modify'},
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/utils.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'src/helper.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'CONTAINER'

    def test_isolation_mode_container_multi_service(self):
        """Test CONTAINER isolation for multi-service changes."""
        context = {
            'candidates': [
                {'file_path': 'services/auth/main.py', 'content_type': 'code', 'operation': 'modify'},
                {'file_path': 'services/api/handler.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert evaluation['isolation_mode'] == 'CONTAINER'

    def test_reasoning_generated(self):
        """Test that reasoning is generated for decisions."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        evaluation = self.evaluator.evaluate(context)
        assert 'reasoning' in evaluation
        assert len(evaluation['reasoning']) > 0
        assert evaluation['isolation_mode'] in evaluation['reasoning']


class TestContextIsolator:
    """Test ContextIsolator async decision making."""

    def setup_method(self):
        """Setup for each test."""
        self.isolator = ContextIsolator()

    @pytest.mark.asyncio
    async def test_determine_isolation_async(self):
        """Test async isolation determination."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        result = await self.isolator.determine_isolation(context, 'A1')
        assert result['isolation_mode'] == 'WORKTREE'
        assert result['agent_id'] == 'A1'
        assert 'duration_ms' in result
        assert result['duration_ms'] < 100  # Should be fast

    @pytest.mark.asyncio
    async def test_determine_isolation_none(self):
        """Test NONE isolation decision."""
        context = {'candidates': []}
        result = await self.isolator.determine_isolation(context, 'A2')
        assert result['isolation_mode'] == 'NONE'

    @pytest.mark.asyncio
    async def test_determine_isolation_container(self):
        """Test CONTAINER isolation decision."""
        context = {
            'candidates': [
                {'file_path': 'migrations/0001.sql', 'content_type': 'code', 'operation': 'add'},
            ]
        }
        result = await self.isolator.determine_isolation(context, 'A3')
        assert result['isolation_mode'] == 'CONTAINER'

    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """Test that metrics are collected."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        await self.isolator.determine_isolation(context, 'A1')
        await self.isolator.determine_isolation(context, 'A2')

        metrics = self.isolator.get_metrics()
        assert metrics['total_decisions'] == 2
        assert 'by_mode' in metrics
        assert 'average_duration_ms' in metrics
        assert 'p95_duration_ms' in metrics

    @pytest.mark.asyncio
    async def test_metrics_p95_calculation(self):
        """Test P95 duration calculation."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }

        # Make multiple decisions
        for i in range(10):
            await self.isolator.determine_isolation(context, f'A{i}')

        metrics = self.isolator.get_metrics()
        assert metrics['p95_duration_ms'] >= 0
        assert metrics['p95_duration_ms'] < 100  # Should be fast

    @pytest.mark.asyncio
    async def test_metrics_reset(self):
        """Test metrics reset."""
        context = {
            'candidates': [
                {'file_path': 'src/main.py', 'content_type': 'code', 'operation': 'modify'},
            ]
        }
        await self.isolator.determine_isolation(context, 'A1')

        metrics_before = self.isolator.get_metrics()
        assert metrics_before['total_decisions'] == 1

        self.isolator.reset_metrics()

        metrics_after = self.isolator.get_metrics()
        assert metrics_after['total_decisions'] == 0


class TestPerformance:
    """Performance tests for isolation determination."""

    @pytest.mark.asyncio
    async def test_isolation_decision_latency_p95(self):
        """Test that P95 isolation decision latency is < 100ms."""
        evaluator = RiskEvaluator()
        large_context = {
            'candidates': [
                {'file_path': f'src/file_{i}.py', 'content_type': 'code', 'operation': 'modify'}
                for i in range(50)
            ]
        }

        durations = []
        for _ in range(20):
            import time
            start = time.time()
            evaluator.evaluate(large_context)
            duration = (time.time() - start) * 1000
            durations.append(duration)

        durations.sort()
        p95 = durations[int(len(durations) * 0.95)]
        assert p95 < 100, f"P95 latency {p95}ms exceeds 100ms threshold"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
