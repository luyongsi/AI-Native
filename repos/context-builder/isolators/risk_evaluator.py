"""Risk evaluator for determining Agent isolation requirements.

Detects multiple change types (code, dependencies, DB migrations, config)
and calculates risk levels to determine isolation mode.
"""

import re
from typing import Dict, List, Any, Optional


class RiskEvaluator:
    """Evaluate risk level and determine isolation mode for Agent execution."""

    # File patterns for different change types
    DEPENDENCY_FILES = {
        'package.json', 'package-lock.json', 'yarn.lock',
        'requirements.txt', 'setup.py', 'setup.cfg', 'pyproject.toml',
        'go.mod', 'go.sum',
        'Gemfile', 'Gemfile.lock',
        'pom.xml',
        'build.gradle', 'build.gradle.kts',
        'Cargo.toml', 'Cargo.lock',
    }

    DB_MIGRATION_PATTERNS = {
        'migrations/', 'db/migrate/', 'flyway/', 'liquibase/',
        '.sql', '.migration'
    }

    CONFIG_FILES = {
        '.env', '.env.local', '.env.example',
        'config.yaml', 'config.yml', 'config.json', 'config.toml',
        'application.properties', 'application.yml',
        '.config', 'settings.json', 'settings.local.json',
    }

    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.tsx', '.jsx',
        '.java', '.go', '.rs', '.rb', '.php',
        '.cpp', '.c', '.h', '.swift', '.kt'
    }

    def __init__(self):
        """Initialize the risk evaluator."""
        self._evaluation_cache = {}

    def evaluate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate context and determine isolation requirements.

        Args:
            context: Context dict with 'candidates' (list of files/changes)
                    Each candidate should have:
                    - 'file_path': str (file path)
                    - 'content_type': str (e.g., 'code', 'doc')
                    - 'operation': str (e.g., 'add', 'modify', 'delete')

        Returns:
            Dict with keys:
            - 'risks': Dict of detected risks by category
            - 'risk_level': 'low', 'medium', or 'high'
            - 'isolation_mode': 'NONE', 'WORKTREE', or 'CONTAINER'
            - 'reasoning': str explaining the decision
        """
        candidates = context.get('candidates', [])

        # Detect various change types
        risks = {
            'code_changes': self._detect_code_changes(candidates),
            'dependency_changes': self._detect_dependency_changes(candidates),
            'db_migrations': self._detect_db_migrations(candidates),
            'config_changes': self._detect_config_changes(candidates),
            'infrastructure_changes': self._detect_infrastructure_changes(candidates),
            'multi_service_changes': self._detect_multi_service_changes(candidates),
        }

        # Calculate risk level
        risk_level = self._calculate_risk_level(risks, candidates)

        # Determine isolation mode
        isolation_mode = self._determine_isolation_mode(risk_level, risks)

        # Generate reasoning
        reasoning = self._generate_reasoning(risk_level, risks, isolation_mode)

        result = {
            'risks': risks,
            'risk_level': risk_level,
            'isolation_mode': isolation_mode,
            'reasoning': reasoning,
        }

        return result

    def _detect_code_changes(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect code file changes (adds, modifies, deletes)."""
        code_changes = []

        for candidate in candidates:
            file_path = candidate.get('file_path', '').lower()
            content_type = candidate.get('content_type', '')

            # Match by extension or content type
            is_code = (
                content_type == 'code' or
                any(file_path.endswith(ext) for ext in self.CODE_EXTENSIONS)
            )

            if is_code and file_path not in ('node_modules', '.git'):
                code_changes.append({
                    'file': candidate.get('file_path'),
                    'operation': candidate.get('operation', 'modify'),
                })

        return {
            'detected': len(code_changes) > 0,
            'file_count': len(code_changes),
            'files': code_changes,
        }

    def _detect_dependency_changes(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect package/dependency file changes."""
        dep_files = []

        for candidate in candidates:
            file_path = candidate.get('file_path', '')
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path

            if file_name in self.DEPENDENCY_FILES:
                dep_files.append({
                    'file': file_path,
                    'operation': candidate.get('operation', 'modify'),
                })

        return {
            'detected': len(dep_files) > 0,
            'file_count': len(dep_files),
            'files': dep_files,
        }

    def _detect_db_migrations(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect database migration files."""
        migrations = []

        for candidate in candidates:
            file_path = candidate.get('file_path', '').lower()

            # Check for migration patterns
            is_migration = (
                any(pattern in file_path for pattern in self.DB_MIGRATION_PATTERNS) or
                'migration' in file_path or
                file_path.endswith('.sql')
            )

            if is_migration:
                migrations.append({
                    'file': candidate.get('file_path'),
                    'operation': candidate.get('operation', 'modify'),
                })

        return {
            'detected': len(migrations) > 0,
            'file_count': len(migrations),
            'files': migrations,
        }

    def _detect_config_changes(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect configuration file changes."""
        configs = []

        for candidate in candidates:
            file_path = candidate.get('file_path', '')
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path

            # Check exact names or patterns
            is_config = (
                file_name in self.CONFIG_FILES or
                file_name.startswith('.env') or
                file_name.startswith('config')
            )

            if is_config:
                configs.append({
                    'file': file_path,
                    'operation': candidate.get('operation', 'modify'),
                })

        return {
            'detected': len(configs) > 0,
            'file_count': len(configs),
            'files': configs,
        }

    def _detect_infrastructure_changes(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect infrastructure/devops related changes (Dockerfile, k8s, terraform, etc)."""
        infra_files = {
            'dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
            'makefile', 'jenkinsfile', '.gitlab-ci.yml', '.github',
        }

        infra_patterns = {
            'terraform', 'ansible', 'kubernetes', 'helm',
        }

        infra_changes = []

        for candidate in candidates:
            file_path = candidate.get('file_path', '').lower()
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path

            # Check exact file names
            is_infra = file_name in infra_files

            # Check for pattern matches in path
            if not is_infra:
                is_infra = any(pattern in file_path for pattern in infra_patterns)

            if is_infra:
                infra_changes.append({
                    'file': candidate.get('file_path'),
                    'operation': candidate.get('operation', 'modify'),
                })

        return {
            'detected': len(infra_changes) > 0,
            'file_count': len(infra_changes),
            'files': infra_changes,
        }

    def _detect_multi_service_changes(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect changes across multiple services.

        Only counts as multi-service if there are actually distinct service
        directories (services/, apps/, src/ with named subdirs).
        """
        services = set()

        for candidate in candidates:
            file_path = candidate.get('file_path', '')
            parts = file_path.split('/')

            # Only recognize if explicitly in a services/ or apps/ directory
            if len(parts) >= 3:
                if parts[0] in ('services', 'apps'):
                    # Extract service name from second level
                    service_name = parts[1]
                    if service_name and not service_name.startswith('.'):
                        services.add(service_name)

        return {
            'detected': len(services) > 1,
            'service_count': len(services),
            'services': list(services),
        }

    def _calculate_risk_level(self, risks: Dict[str, Any],
                              candidates: List[Dict[str, Any]]) -> str:
        """Calculate overall risk level: low, medium, or high.

        Risk scoring:
        - HIGH: DB migrations, infra changes, multi-service, or 10+ files
        - MEDIUM: Dependencies or 3+ code files
        - LOW: 1-2 code files, doc/ui only
        """
        if (risks['db_migrations']['detected'] or
            risks['infrastructure_changes']['detected'] or
            risks['multi_service_changes']['detected']):
            return 'high'

        code_count = risks['code_changes']['file_count']
        if risks['dependency_changes']['detected'] or code_count >= 3:
            return 'medium'

        if risks['config_changes']['detected']:
            return 'medium'

        if code_count > 0:
            return 'low'

        # Check if only docs/ui
        if all(c.get('content_type') in ('doc', 'ui', 'design')
               for c in candidates if c):
            return 'low'

        return 'low'

    def _determine_isolation_mode(self, risk_level: str,
                                  risks: Dict[str, Any]) -> str:
        """Determine isolation mode based on risk level and change types.

        Modes:
        - NONE: Read-only, doc/design only
        - WORKTREE: Code changes, single/few files, test changes
        - CONTAINER: Deps, DB migrations, infra changes, or high risk
        """
        # CONTAINER: High-risk changes
        if (risks['db_migrations']['detected'] or
            risks['infrastructure_changes']['detected'] or
            risks['multi_service_changes']['detected'] or
            risk_level == 'high'):
            return 'CONTAINER'

        # WORKTREE: Medium risk code/dep/config changes
        if (risks['code_changes']['detected'] or
            risks['dependency_changes']['detected'] or
            (risks['config_changes']['detected'] and
             risks['code_changes']['file_count'] <= 3)):
            return 'WORKTREE'

        # NONE: No code changes detected
        if not risks['code_changes']['detected']:
            return 'NONE'

        return 'WORKTREE'  # default

    def _generate_reasoning(self, risk_level: str, risks: Dict[str, Any],
                            isolation_mode: str) -> str:
        """Generate human-readable reasoning for the decision."""
        reasons = []

        if risks['db_migrations']['detected']:
            reasons.append(
                f"Database migrations detected ({risks['db_migrations']['file_count']} files)"
            )

        if risks['infrastructure_changes']['detected']:
            reasons.append(
                f"Infrastructure changes detected ({risks['infrastructure_changes']['file_count']} files)"
            )

        if risks['dependency_changes']['detected']:
            reasons.append(
                f"Dependency changes detected ({risks['dependency_changes']['file_count']} files)"
            )

        if risks['code_changes']['detected']:
            reasons.append(
                f"Code changes detected ({risks['code_changes']['file_count']} files)"
            )

        if risks['config_changes']['detected']:
            reasons.append(
                f"Configuration changes detected ({risks['config_changes']['file_count']} files)"
            )

        if risks['multi_service_changes']['detected']:
            services = risks['multi_service_changes']['service_count']
            reasons.append(f"Multi-service changes ({services} services affected)")

        reasoning = f"Risk level: {risk_level}. " + "; ".join(reasons) if reasons else "No risks detected"
        reasoning += f". Isolation mode: {isolation_mode}"

        return reasoning
