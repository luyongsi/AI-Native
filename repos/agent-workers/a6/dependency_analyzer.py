"""
A6 Sub-module: Dependency Analyzer

Analyzes requirements, API schemas, and ERD to identify task types
and their dependencies. Produces structured task definitions that feed
into the DAG builder.

In production, this would:
  1. Parse API Schema (OpenAPI/Swagger) to extract endpoint hierarchies.
  2. Parse ERD to identify entity relationships and migration dependencies.
  3. Extract shared modules (utils, middleware, shared UI components).
  4. Apply domain rules for dependency inference (e.g., auth before entities).
  5. Optionally use LLM to detect implicit dependencies and relationships.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class DependencyAnalyzer:
    """Analyzes requirements, schemas, and ERD to infer task dependencies."""

    def __init__(self):
        """Initialize the dependency analyzer."""
        logger.debug("DependencyAnalyzer initialized")

    def analyze(
        self,
        requirement: dict,
        api_schema: dict,
        erd: dict,
        context: Optional[dict] = None
    ) -> dict:
        """Analyze requirement, API schema, and ERD to identify tasks and dependencies.

        Args:
            requirement: Requirement dict with keys like:
                - title (str): requirement title
                - description (str): detailed description
                - has_ui (bool): whether UI is needed
                - has_auth (bool): whether auth is required
                - priority (str): requirement priority
            api_schema: OpenAPI/Swagger schema with:
                - paths (dict): API endpoints
                - components (dict): shared schemas/models
                - info (dict): API metadata
            erd: Entity-Relationship Diagram with:
                - entities (list): data entities with fields
                - relationships (list): relationships between entities
                - ddl (str): optional DDL statements
            context: Optional additional context

        Returns:
            Dict with:
                - tasks (list): identified tasks with dependencies
                - shared_modules (list): modules used by multiple tasks
                - analysis_summary (dict): statistics and insights
        """
        logger.info("Analyzing requirement, API schema, and ERD")

        # Extract components
        tasks = []
        shared_modules = []

        # Phase 1: Database migration tasks (highest priority)
        db_tasks = self._extract_db_tasks(erd, requirement)
        tasks.extend(db_tasks)
        db_task_ids = [t["id"] for t in db_tasks]

        # Phase 2: Backend API implementation tasks
        api_tasks = self._extract_api_tasks(api_schema, requirement, db_task_ids)
        tasks.extend(api_tasks)
        api_task_ids = [t["id"] for t in api_tasks]

        # Phase 3: Frontend tasks (depends on API)
        if requirement.get("has_ui", True):
            ui_tasks = self._extract_ui_tasks(api_schema, requirement, api_task_ids)
            tasks.extend(ui_tasks)

        # Phase 4: Identify shared modules
        shared_modules = self._identify_shared_modules(requirement, api_schema, erd)

        # Phase 5: Extract authentication/security tasks
        if requirement.get("has_auth", False):
            auth_tasks = self._extract_auth_tasks(requirement, db_task_ids)
            tasks.extend(auth_tasks)

        # Phase 6: Extract integration/testing tasks
        integration_tasks = self._extract_integration_tasks(tasks, requirement)
        tasks.extend(integration_tasks)

        # Validate dependencies
        self._validate_dependencies(tasks)

        analysis_summary = {
            "total_tasks": len(tasks),
            "db_tasks": len(db_tasks),
            "api_tasks": len(api_tasks),
            "ui_tasks": len([t for t in tasks if t["type"] == "frontend"]),
            "auth_tasks": len([t for t in tasks if t["type"] == "auth"]),
            "shared_modules_count": len(shared_modules),
            "has_cycles": False,  # Will be detected in DAG builder
        }

        logger.info(
            "Analysis complete: %d tasks, %d shared modules",
            len(tasks),
            len(shared_modules)
        )

        return {
            "tasks": tasks,
            "shared_modules": shared_modules,
            "analysis_summary": analysis_summary,
        }

    # ---- Task extraction methods ----

    def _extract_db_tasks(self, erd: dict, requirement: dict) -> List[Dict[str, Any]]:
        """Extract database migration tasks from ERD.

        Database tasks always have the highest priority (priority=1) and no dependencies.
        """
        tasks: List[Dict[str, Any]] = []

        # Check for DDL
        if erd.get("ddl"):
            tasks.append({
                "id": "T_DB_SCHEMA",
                "type": "db_migration",
                "title": "Database Schema Migration",
                "description": "Execute database schema creation/migration based on ERD",
                "depends_on": [],
                "priority": 1,
                "estimated_hours": 2.0,
                "agent_type": "A9",
                "tags": ["critical", "infrastructure"],
            })

        # Extract individual entity tasks from ERD
        entities = erd.get("entities", [])
        if entities:
            for entity in entities[:10]:  # Cap at 10 to keep manageable
                entity_name = entity.get("name") if isinstance(entity, dict) else str(entity)
                tasks.append({
                    "id": f"T_DB_{entity_name.upper()}",
                    "type": "db_migration",
                    "title": f"Migrate {entity_name} entity",
                    "description": f"Create/update {entity_name} table with indexes and constraints",
                    "depends_on": ["T_DB_SCHEMA"] if tasks else [],
                    "priority": 1,
                    "estimated_hours": 1.5,
                    "agent_type": "A9",
                    "entity": entity_name,
                    "tags": ["database"],
                })

        if not tasks:
            # Fallback: generic migration task
            tasks.append({
                "id": "T_DB_SCHEMA",
                "type": "db_migration",
                "title": "Database Schema Setup",
                "description": "Initialize database schema and migrations",
                "depends_on": [],
                "priority": 1,
                "estimated_hours": 2.0,
                "agent_type": "A9",
                "tags": ["critical", "infrastructure"],
            })

        logger.info("Extracted %d database tasks", len(tasks))
        return tasks

    def _extract_api_tasks(
        self,
        api_schema: dict,
        requirement: dict,
        db_task_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract API implementation tasks from OpenAPI schema.

        API tasks depend on database tasks being completed first (priority=2).
        """
        tasks: List[Dict[str, Any]] = []

        paths = api_schema.get("paths", {})
        if not paths:
            return tasks

        # Group endpoints by resource/prefix
        resource_groups: Dict[str, List[str]] = {}
        for path in paths.keys():
            # Extract resource from path (e.g., /api/users -> users)
            parts = path.strip("/").split("/")
            resource = parts[-1] if parts else "generic"
            if resource not in resource_groups:
                resource_groups[resource] = []
            resource_groups[resource].append(path)

        # Create task per resource group
        for resource, paths_in_group in resource_groups.items():
            task_id = f"T_API_{resource.upper()}"
            tasks.append({
                "id": task_id,
                "type": "api_impl",
                "title": f"Implement {resource} API endpoints",
                "description": f"Implement {len(paths_in_group)} endpoint(s) for {resource} resource",
                "depends_on": db_task_ids,  # API depends on DB
                "priority": 2,
                "estimated_hours": 3.0 + (len(paths_in_group) * 1.5),
                "agent_type": "A9",
                "endpoints": paths_in_group,
                "resource": resource,
                "tags": ["backend", "api"],
            })

        logger.info("Extracted %d API implementation tasks", len(tasks))
        return tasks

    def _extract_ui_tasks(
        self,
        api_schema: dict,
        requirement: dict,
        api_task_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract frontend UI tasks.

        UI tasks depend on API tasks (priority=3).
        """
        tasks: List[Dict[str, Any]] = []

        # Extract paths/resources for UI screens
        paths = api_schema.get("paths", {})
        if not paths:
            # Generic UI task
            tasks.append({
                "id": "T_UI_MAIN",
                "type": "frontend",
                "title": "Build Frontend UI",
                "description": "Build frontend user interface and components",
                "depends_on": api_task_ids,
                "priority": 3,
                "estimated_hours": 8.0,
                "agent_type": "A9",
                "tags": ["frontend", "ui"],
            })
            return tasks

        # Group by resource for UI pages
        resources = set()
        for path in paths.keys():
            parts = path.strip("/").split("/")
            if len(parts) > 1:
                resources.add(parts[-1])

        # Create task per major UI component
        for idx, resource in enumerate(sorted(list(resources))[:5]):
            task_id = f"T_UI_{resource.upper()}"
            tasks.append({
                "id": task_id,
                "type": "frontend",
                "title": f"Build {resource.capitalize()} UI",
                "description": f"Implement {resource} pages and components",
                "depends_on": api_task_ids,
                "priority": 3,
                "estimated_hours": 5.0,
                "agent_type": "A9",
                "page": resource,
                "tags": ["frontend", "ui"],
            })

        logger.info("Extracted %d UI tasks", len(tasks))
        return tasks

    def _extract_auth_tasks(
        self,
        requirement: dict,
        db_task_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """Extract authentication/security tasks.

        Auth tasks depend on database tasks (priority=1.5).
        """
        tasks: List[Dict[str, Any]] = []

        tasks.append({
            "id": "T_AUTH_SETUP",
            "type": "auth",
            "title": "Setup Authentication & Authorization",
            "description": "Implement authentication, authorization, and security middleware",
            "depends_on": db_task_ids,
            "priority": 1.5,
            "estimated_hours": 4.0,
            "agent_type": "A9",
            "tags": ["security", "auth", "infrastructure"],
        })

        logger.info("Extracted %d auth tasks", len(tasks))
        return tasks

    def _extract_integration_tasks(
        self,
        tasks: List[Dict[str, Any]],
        requirement: dict
    ) -> List[Dict[str, Any]]:
        """Extract integration and testing tasks.

        These depend on all development tasks being complete.
        """
        new_tasks: List[Dict[str, Any]] = []

        # Collect all dev task IDs
        dev_task_ids = [t["id"] for t in tasks if t["type"] in ("api_impl", "frontend", "auth")]
        if not dev_task_ids:
            dev_task_ids = [t["id"] for t in tasks]

        # Integration testing task
        new_tasks.append({
            "id": "T_INTEGRATION_TEST",
            "type": "testing",
            "title": "Integration Testing",
            "description": "Execute integration tests across API, frontend, and database",
            "depends_on": dev_task_ids[-3:] if len(dev_task_ids) >= 3 else dev_task_ids,
            "priority": 4,
            "estimated_hours": 6.0,
            "agent_type": "A7",
            "tags": ["testing", "qa"],
        })

        # Deployment task
        new_tasks.append({
            "id": "T_DEPLOYMENT",
            "type": "deployment",
            "title": "Deployment & Release",
            "description": "Deploy to production and verify health",
            "depends_on": ["T_INTEGRATION_TEST"],
            "priority": 5,
            "estimated_hours": 2.0,
            "agent_type": "A9",
            "tags": ["deployment", "devops"],
        })

        logger.info("Extracted %d integration/testing tasks", len(new_tasks))
        return new_tasks

    def _identify_shared_modules(
        self,
        requirement: dict,
        api_schema: dict,
        erd: dict
    ) -> List[Dict[str, Any]]:
        """Identify shared modules used by multiple tasks.

        Shared modules are reusable utilities, middleware, and base components.
        """
        modules: List[Dict[str, Any]] = []

        # Common utility modules
        modules.extend([
            {
                "name": "common_utils",
                "type": "utility",
                "description": "Common utility functions (validation, formatting, etc)",
                "used_by": ["api_impl", "frontend"],
                "priority": 1,
            },
            {
                "name": "error_handling",
                "type": "middleware",
                "description": "Error handling and logging middleware",
                "used_by": ["api_impl"],
                "priority": 1,
            },
            {
                "name": "constants",
                "type": "config",
                "description": "Global constants and configuration",
                "used_by": ["api_impl", "frontend"],
                "priority": 1,
            },
        ])

        # Auth-related shared modules
        if requirement.get("has_auth", False):
            modules.append({
                "name": "auth_middleware",
                "type": "middleware",
                "description": "Authentication middleware for API protection",
                "used_by": ["api_impl"],
                "priority": 1,
            })

        # Data models/entities
        entities = erd.get("entities", [])
        if entities:
            modules.append({
                "name": "data_models",
                "type": "model",
                "description": f"Data models for {len(entities)} entities",
                "used_by": ["api_impl", "frontend"],
                "priority": 2,
                "entity_count": len(entities),
            })

        # API contract/schema module
        if api_schema.get("components"):
            modules.append({
                "name": "api_contracts",
                "type": "schema",
                "description": "API contract definitions and request/response schemas",
                "used_by": ["api_impl", "frontend"],
                "priority": 2,
            })

        logger.info("Identified %d shared modules", len(modules))
        return modules

    def _validate_dependencies(self, tasks: List[Dict[str, Any]]) -> None:
        """Validate that all dependencies reference existing tasks."""
        task_ids = {t["id"] for t in tasks}

        for task in tasks:
            for dep_id in task.get("depends_on", []):
                if dep_id not in task_ids:
                    logger.warning(
                        "Task %s depends on non-existent task %s",
                        task["id"],
                        dep_id
                    )

        logger.debug("Dependency validation complete")
