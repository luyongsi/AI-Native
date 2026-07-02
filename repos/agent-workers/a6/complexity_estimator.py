"""
A6 Sub-module: Complexity Estimator

Estimates task complexity and effort using a multi-factor scoring model.

In production, this would:
  1. Accept a structured task dict with requirements, components, and context.
  2. Score across 5 dimensions:
     - code_volume: lines/modules/files affected, new vs. modified code ratio
     - data_complexity: schema changes, migration complexity, data volume
     - integration_points: external API calls, message queues, shared state
     - security_requirements: auth changes, data classification, compliance
     - testing_effort: test surface area, edge-case density, mocking difficulty
  3. Weight factors by project type (greenfield vs. brownfield, monolith vs.
     microservices).
  4. Use historical data from past sprints to calibrate hour estimates.
  5. Report confidence intervals for each estimate.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Factor weight defaults
_DEFAULT_FACTOR_WEIGHTS: Dict[str, float] = {
    "code_volume": 0.25,
    "data_complexity": 0.20,
    "integration_points": 0.20,
    "security_requirements": 0.15,
    "testing_effort": 0.20,
}

# Complexity-to-hours mapping (baseline hours by complexity level)
_COMPLEXITY_HOURS: Dict[int, float] = {
    1: 0.5,
    2: 1.0,
    3: 2.0,
    4: 4.0,
    5: 8.0,
    6: 16.0,
    7: 24.0,
    8: 40.0,
    9: 60.0,
    10: 80.0,
}


class ComplexityEstimator:
    """Estimates task complexity and effort using weighted factor analysis."""

    def __init__(self, factor_weights: Optional[Dict[str, float]] = None):
        """Args:
            factor_weights: Optional per-factor weight overrides.
                            Keys: code_volume, data_complexity, integration_points,
                            security_requirements, testing_effort.
        """
        self.weights = factor_weights or dict(_DEFAULT_FACTOR_WEIGHTS)
        # Normalize to 1.0
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}
        logger.debug("ComplexityEstimator initialized with weights=%s", self.weights)

    def estimate(self, task: dict) -> dict:
        """Estimate complexity and effort for a single task.

        Args:
            task: Task dict with at least a 'title' and optional keys:
                - description (str): detailed task description
                - type / category (str): planning, api, backend, frontend, db, testing, deployment
                - components (list): affected components/modules
                - entities (list): data entities affected
                - endpoints (list): API endpoints to implement/modify
                - pages (list): UI pages to build/modify
                - auth_required (bool): whether auth changes are needed
                - compliance (list): compliance requirements
                - existing_codebase (bool): brownfield vs. greenfield

        Returns:
            Dict with:
                - complexity: 1-10 integer
                - estimated_hours: float
                - confidence: float (0-1)
                - factors: [{name, impact (1-10), reason}]
        """
        task_title = task.get("title", "Untitled task")
        logger.info("Estimating complexity for: %s", task_title)

        # Score each factor (1-10 per factor)
        factors = self._score_factors(task)

        # Weighted composite complexity
        raw_complexity = sum(
            f["impact"] * self.weights.get(f["name"], 0.2) for f in factors
        )
        # Map to 1-10 range
        complexity = max(1, min(10, round(raw_complexity)))

        # Estimated hours from complexity mapping
        estimated_hours = self._hours_from_complexity(complexity, task)

        # Confidence based on available information
        confidence = self._compute_confidence(task, factors)

        result: Dict[str, Any] = {
            "complexity": complexity,
            "estimated_hours": estimated_hours,
            "confidence": confidence,
            "factors": factors,
        }

        if complexity >= 8:
            logger.warning(
                "High complexity (%d) for task '%s'. Consider decomposition.",
                complexity,
                task_title,
            )
        else:
            logger.info(
                "Task '%s': complexity=%d, hours=%.1f, confidence=%.2f",
                task_title,
                complexity,
                estimated_hours,
                confidence,
            )

        return result

    # ---- Factor scoring ----

    def _score_factors(self, task: dict) -> List[Dict[str, Any]]:
        """Score each complexity factor for the task.

        Returns:
            List of {name, impact (1-10), reason}.
        """
        factors: List[Dict[str, Any]] = []

        # 1. Code volume
        cv_score, cv_reason = self._score_code_volume(task)
        factors.append({"name": "code_volume", "impact": cv_score, "reason": cv_reason})

        # 2. Data complexity
        dc_score, dc_reason = self._score_data_complexity(task)
        factors.append({"name": "data_complexity", "impact": dc_score, "reason": dc_reason})

        # 3. Integration points
        ip_score, ip_reason = self._score_integration_points(task)
        factors.append({"name": "integration_points", "impact": ip_score, "reason": ip_reason})

        # 4. Security requirements
        sr_score, sr_reason = self._score_security_requirements(task)
        factors.append({"name": "security_requirements", "impact": sr_score, "reason": sr_reason})

        # 5. Testing effort
        te_score, te_reason = self._score_testing_effort(task)
        factors.append({"name": "testing_effort", "impact": te_score, "reason": te_reason})

        return factors

    def _score_code_volume(self, task: dict) -> Tuple[int, str]:
        """Estimate code volume impact (1-10)."""
        components = task.get("components", [])
        endpoints = task.get("endpoints", [])
        pages = task.get("pages", [])
        task_type = task.get("type") or task.get("category", "dev")

        signals = len(components) + len(endpoints) + len(pages)

        if task_type in ("planning", "deployment"):
            return 2, "Planning/deployment tasks involve minimal code changes."
        elif signals == 0:
            # Infer from description length as fallback
            desc = task.get("description", task.get("title", ""))
            if len(str(desc)) > 200:
                return 6, "Detailed description suggests significant code volume."
            return 4, "Moderate code volume assumed from task category."
        elif signals <= 2:
            return 3, "Small scope: few components or endpoints affected."
        elif signals <= 5:
            return 5, "Medium scope: multiple components or endpoints."
        elif signals <= 10:
            return 7, "Large scope: many components affected."
        else:
            return 9, "Very large scope: extensive code changes across many modules."

    def _score_data_complexity(self, task: dict) -> Tuple[int, str]:
        """Estimate data complexity impact (1-10)."""
        entities = task.get("entities", [])
        has_migration = any(
            kw in str(task).lower()
            for kw in ["migration", "schema", "database", "db", "migrate", "ddl"]
        )
        task_type = task.get("type") or task.get("category", "dev")

        if task_type in ("planning",):
            return 1, "No direct data changes in planning tasks."
        elif task_type in ("frontend", "ui"):
            return 2, "Frontend tasks have minimal data complexity."
        elif task_type == "db":
            if len(entities) >= 3:
                return 8, "Multiple entity schema changes with dependencies."
            return 6, "Database schema changes required."
        elif has_migration:
            if len(entities) >= 3:
                return 7, "Migration scripts span multiple entities."
            return 5, "Migration scripts required with moderate schema changes."
        elif entities:
            return 4, "Entity modifications may require schema updates."
        else:
            return 3, "Standard CRUD; no structural data changes expected."

    def _score_integration_points(self, task: dict) -> Tuple[int, str]:
        """Estimate integration complexity (1-10)."""
        task_type = task.get("type") or task.get("category", "dev")
        endpoints = task.get("endpoints", [])
        desc = str(task.get("description", task.get("title", ""))).lower()

        integration_kw = ["api", "webhook", "queue", "message", "event", "grpc", "graphql",
                          "callback", "integration", "third-party", "external", "service"]
        integration_hits = sum(1 for kw in integration_kw if kw in desc)

        if task_type == "deployment":
            return 7, "Deployment touches CI/CD pipelines, multiple environments, and monitoring."
        elif task_type == "testing":
            return 6, "Integration tests require coordinating multiple services and test data."
        elif integration_hits >= 3:
            return 8, "Heavy integration with external services and message queues."
        elif integration_hits >= 1:
            return 5, "Moderate integration with external APIs or services."
        elif len(endpoints) >= 3:
            return 4, "Multiple endpoint definitions require cross-service coordination."
        else:
            return 2, "Minimal external integration required."

    def _score_security_requirements(self, task: dict) -> Tuple[int, str]:
        """Estimate security complexity (1-10)."""
        auth_required = task.get("auth_required", False)
        compliance = task.get("compliance", [])
        desc = str(task.get("description", task.get("title", ""))).lower()

        security_kw = ["auth", "permission", "role", "rbac", "token", "oauth", "encrypt",
                       "pii", "gdpr", "hipaa", "pci", "audit", "compliance"]
        security_hits = sum(1 for kw in security_kw if kw in desc)

        if compliance:
            return 8, f"Compliance requirements: {', '.join(compliance)}."
        elif security_hits >= 3 or auth_required:
            return 6, "Authentication/authorization changes with security implications."
        elif security_hits >= 1:
            return 4, "Moderate security considerations (token handling, input validation)."
        else:
            return 2, "Standard security posture; no special requirements."

    def _score_testing_effort(self, task: dict) -> Tuple[int, str]:
        """Estimate testing effort impact (1-10)."""
        task_type = task.get("type") or task.get("category", "dev")
        components = task.get("components", [])

        if task_type == "testing":
            return 9, "This is a testing task itself; requires test planning and execution."
        elif task_type == "planning":
            return 2, "Planning tasks require review but minimal testing."
        elif task_type in ("api", "backend"):
            return 6, "Backend APIs need unit + integration + contract tests."
        elif task_type in ("frontend", "ui"):
            return 5, "UI components need unit + visual regression + E2E tests."
        elif task_type == "db":
            return 4, "DB changes need migration tests and rollback validation."
        elif task_type == "deployment":
            return 3, "Deployment needs smoke tests and canary validation."
        elif len(components) >= 5:
            return 7, "Many components increase test surface area significantly."
        else:
            return 4, "Standard testing surface; unit + integration tests."

    # ---- Estimation helpers ----

    def _hours_from_complexity(self, complexity: int, task: dict) -> float:
        """Map complexity score to estimated hours.

        In production, this would use historical velocity data and team
        calibration curves rather than a static lookup.
        """
        base_hours = _COMPLEXITY_HOURS.get(complexity, 4.0)

        # Adjust for task type
        task_type = task.get("type") or task.get("category", "dev")
        type_multipliers: Dict[str, float] = {
            "planning": 0.5,
            "api": 1.0,
            "backend": 1.2,
            "frontend": 0.9,
            "db": 0.8,
            "testing": 1.1,
            "deployment": 0.4,
        }
        multiplier = type_multipliers.get(task_type, 1.0)

        # Brownfield penalty (existing codebase adds overhead)
        if task.get("existing_codebase", False):
            multiplier *= 1.3

        hours = round(base_hours * multiplier, 1)
        return max(0.5, hours)  # minimum 0.5 hours

    def _compute_confidence(self, task: dict, factors: List[Dict[str, Any]]) -> float:
        """Compute confidence in the estimate (0.0 - 1.0).

        Confidence decreases when:
        - The task description is short/vague.
        - Many factors scored high (higher uncertainty at high complexity).
        - The task type is ambiguous (no type/category).
        """
        # Completeness of input data
        has_type = bool(task.get("type") or task.get("category"))
        has_desc = len(str(task.get("description", ""))) > 50
        has_components = bool(task.get("components") or task.get("endpoints") or task.get("pages"))
        has_entities = bool(task.get("entities"))

        completeness = sum([has_type, has_desc, has_components, has_entities]) / 4.0

        # High complexity reduces confidence
        max_factor = max(f["impact"] for f in factors)
        complexity_penalty = (max_factor - 1) / 18.0  # max 0.5 penalty at complexity 10

        confidence = completeness - complexity_penalty
        return round(max(0.1, min(1.0, confidence)), 2)

    # ---- Convenience batch estimation ----

    def estimate_all(self, tasks: List[dict]) -> List[dict]:
        """Batch-estimate complexity for a list of tasks.

        Returns the input list with complexity/effort fields added to each task.
        """
        results: List[dict] = []
        total_hours = 0.0
        for task in tasks:
            est = self.estimate(task)
            task["complexity"] = est["complexity"]
            task["estimated_hours"] = est["estimated_hours"]
            task["confidence"] = est["confidence"]
            task["complexity_factors"] = est["factors"]
            results.append(task)
            total_hours += est["estimated_hours"]

        logger.info(
            "Batch estimation complete: %d tasks, total %.1f hours",
            len(results),
            total_hours,
        )
        return results
