"""Isolation rules configuration for ContextIsolator.

Defines conditions and thresholds for determining isolation modes.
"""

# Isolation rules configuration
ISOLATION_RULES = {
    'NONE': {
        'description': 'No isolation required - read-only operations',
        'conditions': [
            'no_code_changes',
            'ui_design_only',
            'documentation_only',
            'no_infrastructure_changes',
        ],
        'max_files': 20,
        'max_risk_level': 'low',
    },

    'WORKTREE': {
        'description': 'Git worktree isolation - for code and test changes',
        'conditions': [
            'single_file_modification',
            'code_changes_without_deps',
            'test_file_changes',
            'small_refactoring',
        ],
        'max_files': 10,
        'max_risk_level': 'medium',
        'allows_dependencies': False,
        'allows_db_migrations': False,
        'allows_infra_changes': False,
    },

    'CONTAINER': {
        'description': 'Container isolation - for risky operations',
        'conditions': [
            'database_migrations',
            'dependency_changes',
            'multi_service_changes',
            'infrastructure_changes',
            'large_refactoring',
        ],
        'max_files': None,  # No limit
        'min_risk_level': 'medium',
        'allows_any_changes': True,
    },
}

# Risk level thresholds
RISK_THRESHOLDS = {
    'low': {
        'max_code_files': 2,
        'max_total_files': 5,
        'allows_dependencies': False,
        'allows_db_migrations': False,
        'allows_infra_changes': False,
    },
    'medium': {
        'max_code_files': 10,
        'max_total_files': 20,
        'allows_dependencies': True,
        'allows_db_migrations': False,
        'allows_infra_changes': False,
    },
    'high': {
        'max_code_files': None,  # No limit
        'max_total_files': None,
        'allows_dependencies': True,
        'allows_db_migrations': True,
        'allows_infra_changes': True,
    },
}

# File patterns for categorization
FILE_PATTERNS = {
    'test_files': [
        'test_', '_test.', 'spec_', '.spec.',
        '/tests/', '/test/', '__tests__', '.test.js',
    ],
    'ui_files': [
        '.tsx', '.jsx', '.vue', '.svelte',
        '/components/', '/ui/', '/pages/',
    ],
    'doc_files': [
        '.md', '.rst', '.txt', '.adoc',
        '/docs/', '/documentation/',
    ],
    'config_files': [
        '.env', '.config', 'config.', 'settings.',
    ],
    'dependency_files': [
        'package.json', 'requirements.txt', 'go.mod',
        'Gemfile', 'pom.xml', 'build.gradle',
    ],
}

# Decision logic helpers
def should_isolate_worktree(code_files: int, has_deps: bool,
                            has_db: bool, has_infra: bool) -> bool:
    """Check if changes should use worktree isolation."""
    if has_db or has_infra:
        return False  # Need CONTAINER
    if has_deps and code_files > 3:
        return False  # Need CONTAINER
    return code_files > 0 and code_files <= 10


def should_isolate_container(has_db: bool, has_deps: bool,
                              has_infra: bool, multi_service: bool,
                              total_files: int) -> bool:
    """Check if changes should use container isolation."""
    return (has_db or has_infra or multi_service or
            (has_deps and total_files > 20) or
            total_files > 50)


def classify_risk_level(code_files: int, dep_files: int, total_files: int,
                        has_db: bool, has_infra: bool,
                        multi_service: bool) -> str:
    """Classify risk level based on change characteristics."""
    if has_db or has_infra or multi_service:
        return 'high'

    if dep_files > 0 or (code_files > 5):
        return 'medium'

    if code_files > 0:
        return 'medium' if code_files > 2 else 'low'

    return 'low'
