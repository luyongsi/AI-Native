"""
A8 Sub-module: Architecture Checker

Validates a task DAG against architectural rules and best practices.
Detects violations such as circular dependencies, excessive parallelism,
deep DAG structures, and missing dependency declarations.

In production, this would:
  1. Accept a DAG and a configurable ruleset (YAML/JSON policy file).
  2. Run structural checks: cycle detection, depth limits, fan-out limits.
  3. Run semantic checks: cross-layer coupling, missing integration tests,
     data ownership boundaries, CQRS/event-sourcing consistency.
  4. Run domain-specific checks from the architecture decision records (ADRs).
  5. Assign severity levels (error = blocks pipeline, warning = advisory).
  6. Generate a pass/fail verdict with actionable fix suggestions.
"""

import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Default architectural rules
_DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "rule": "no_circular_deps",
        "description": "DAG must not contain circular dependencies.",
        "severity": "error",
    },
    {
        "rule": "max_parallel_agents",
        "description": "No parallel group may exceed the maximum agent count.",
        "severity": "warning",
        "params": {"max_agents": 5},
    },
    {
        "rule": "max_dag_depth",
        "description": "DAG depth (longest chain) must not exceed maximum.",
        "severity": "warning",
        "params": {"max_depth": 4},
    },
    {
        "rule": "no_missing_dependencies",
        "description": "All task dependencies must reference valid existing tasks.",
        "severity": "error",
    },
    {
        "rule": "no_orphan_tasks",
        "description": "Every task must have at least one incoming or outgoing edge (except plan/deploy).",
        "severity": "warning",
    },
    {
        "rule": "gate_ordering",
        "description": "Deployment tasks must come after testing tasks in the DAG.",
        "severity": "warning",
    },
]


class ArchChecker:
    """Validates a DAG against architectural rules."""

    def __init__(self, arch_rules: Optional[List[Dict[str, Any]]] = None):
        """Args:
            arch_rules: Optional list of rule dicts. Each rule has:
                - rule (str): rule identifier
                - description (str): human-readable description
                - severity (str): 'error' or 'warning'
                - params (dict, optional): rule-specific configuration
        """
        self.rules = arch_rules or _DEFAULT_RULES
        logger.debug("ArchChecker initialized with %d rules", len(self.rules))

    def check(self, dag: dict, arch_rules: Optional[List[Dict[str, Any]]] = None) -> dict:
        """Check a DAG against architectural rules.

        Args:
            dag: DAG dict with:
                - tasks (list): [{id, title, dependencies[], ...}]
                - edges (list): [{from, to, type}, ...]  (optional; derived from tasks if absent)
                - has_cycles (bool, optional): pre-computed cycle flag
            arch_rules: Optional rule override list (merged with instance rules).

        Returns:
            Dict with:
                - violations: [{rule, task_id, severity, description, suggestion}]
                - passed: bool (True if no 'error'-severity violations)
                - score: 0-100 architectural quality score
        """
        rules = arch_rules or self.rules
        tasks = dag.get("tasks", [])
        edges = dag.get("edges", [])

        logger.info(
            "Checking architecture: %d tasks, %d edges, %d rules",
            len(tasks),
            len(edges),
            len(rules),
        )

        # If edges not explicitly provided, derive from task dependencies
        if not edges and tasks:
            edges = self._derive_edges_from_tasks(tasks)

        violations: List[Dict[str, Any]] = []
        checks_passed = 0
        checks_total = 0

        # Run each rule
        for rule_def in rules:
            rule_name = rule_def["rule"]
            severity = rule_def.get("severity", "warning")
            params = rule_def.get("params", {})

            checks_total += 1
            rule_violations = []

            if rule_name == "no_circular_deps":
                rule_violations = self._check_circular_deps(tasks, edges, dag, params)
            elif rule_name == "max_parallel_agents":
                rule_violations = self._check_max_parallel(tasks, edges, params)
            elif rule_name == "max_dag_depth":
                rule_violations = self._check_max_depth(tasks, edges, params)
            elif rule_name == "no_missing_dependencies":
                rule_violations = self._check_missing_deps(tasks, params)
            elif rule_name == "no_orphan_tasks":
                rule_violations = self._check_orphan_tasks(tasks, edges, params)
            elif rule_name == "gate_ordering":
                rule_violations = self._check_gate_ordering(tasks, edges, params)

            if not rule_violations:
                checks_passed += 1
            else:
                for v in rule_violations:
                    v.setdefault("severity", severity)
                    v.setdefault("rule", rule_name)
                    v.setdefault("description", rule_def.get("description", ""))
                    v["suggestion"] = v.get("suggestion", self._default_suggestion(rule_name))
            violations.extend(rule_violations)

        # Determine pass/fail: any 'error' violation -> fail
        has_errors = any(v.get("severity") == "error" for v in violations)
        passed = not has_errors

        # Score: deduct points per violation, weighted by severity
        score = self._compute_score(checks_total, violations)

        result: Dict[str, Any] = {
            "violations": violations,
            "passed": passed,
            "score": score,
            "checks_passed": checks_passed,
            "checks_total": checks_total,
        }

        if not passed:
            error_count = sum(1 for v in violations if v.get("severity") == "error")
            logger.error(
                "Architecture check FAILED: %d errors, %d warnings, score=%.1f",
                error_count,
                len(violations) - error_count,
                score,
            )
        else:
            logger.info(
                "Architecture check PASSED: %d warnings, score=%.1f",
                len(violations),
                score,
            )

        return result

    # ---- Rule: no_circular_deps ----

    def _check_circular_deps(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
        dag: dict,
        params: dict,
    ) -> List[Dict[str, Any]]:
        """Check for circular dependencies using Kahn's algorithm."""
        if dag.get("has_cycles") is False:
            return []  # Pre-computed as no cycles

        all_nodes = {t["id"] for t in tasks}
        in_degree: Dict[str, int] = defaultdict(int)
        adjacency: Dict[str, List[str]] = defaultdict(list)

        for node in all_nodes:
            in_degree[node] = 0

        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])
            in_degree[edge["to"]] += 1

        queue: deque = deque(n for n in all_nodes if in_degree[n] == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited == len(all_nodes):
            return []

        cycle_nodes = [n for n in all_nodes if in_degree[n] > 0]
        violations: List[Dict[str, Any]] = []
        for node in cycle_nodes:
            violations.append({
                "rule": "no_circular_deps",
                "task_id": node,
                "severity": "error",
                "description": f"Task '{node}' is part of a circular dependency chain.",
                "suggestion": (
                    "Break the cycle by refactoring dependencies: "
                    "merge cyclic nodes, introduce a shared interface, "
                    "or decompose into uni-directional edges."
                ),
            })
        return violations

    # ---- Rule: max_parallel_agents ----

    def _check_max_parallel(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
        params: dict,
    ) -> List[Dict[str, Any]]:
        """Check that no parallel group exceeds max agent count."""
        max_agents = params.get("max_agents", 5)

        # Group tasks by parallel_group
        groups: Dict[str, List[str]] = defaultdict(list)
        for t in tasks:
            pg = t.get("parallel_group")
            if pg:
                groups[pg].append(t["id"])

        violations: List[Dict[str, Any]] = []
        for group_id, task_ids in groups.items():
            if len(task_ids) > max_agents:
                violations.append({
                    "rule": "max_parallel_agents",
                    "task_id": group_id,
                    "severity": "warning",
                    "description": (
                        f"Parallel group '{group_id}' has {len(task_ids)} tasks "
                        f"(max {max_agents})."
                    ),
                    "suggestion": (
                        f"Split this group into smaller batches of at most "
                        f"{max_agents} tasks each, or sequence some tasks."
                    ),
                })
        return violations

    # ---- Rule: max_dag_depth ----

    def _check_max_depth(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
        params: dict,
    ) -> List[Dict[str, Any]]:
        """Check that DAG depth does not exceed maximum."""
        max_depth = params.get("max_depth", 4)

        if not tasks:
            return []

        # Compute topological levels
        in_degree: Dict[str, int] = defaultdict(int)
        adjacency: Dict[str, List[str]] = defaultdict(list)

        for t in tasks:
            in_degree[t["id"]] = 0

        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])
            in_degree[edge["to"]] += 1

        levels: Dict[str, int] = {}
        queue: deque = deque(t["id"] for t in tasks if in_degree[t["id"]] == 0)
        for node in queue:
            levels[node] = 0

        while queue:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                candidate = levels[node] + 1
                if neighbor not in levels or levels[neighbor] < candidate:
                    levels[neighbor] = candidate
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        actual_depth = max(levels.values()) + 1 if levels else 0

        if actual_depth > max_depth:
            deepest = max(levels, key=lambda n: levels[n]) if levels else "unknown"
            return [{
                "rule": "max_dag_depth",
                "task_id": deepest,
                "severity": "warning",
                "description": (
                    f"DAG depth is {actual_depth} (max {max_depth}). "
                    f"Deep DAGs increase lead time and reduce parallelism."
                ),
                "suggestion": (
                    "Reduce depth by identifying tasks that can be merged, "
                    "removing unnecessary sequential dependencies, or splitting "
                    "the spec into multiple smaller, shallower DAGs."
                ),
            }]
        return []

    # ---- Rule: no_missing_dependencies ----

    def _check_missing_deps(
        self,
        tasks: List[Dict[str, Any]],
        params: dict,
    ) -> List[Dict[str, Any]]:
        """Check that all declared dependencies reference existing tasks."""
        task_ids = {t["id"] for t in tasks}
        violations: List[Dict[str, Any]] = []

        for task in tasks:
            for dep_id in task.get("dependencies", []):
                if dep_id not in task_ids:
                    violations.append({
                        "rule": "no_missing_dependencies",
                        "task_id": task["id"],
                        "severity": "error",
                        "description": (
                            f"Task '{task['id']}' declares dependency on "
                            f"'{dep_id}', which does not exist."
                        ),
                        "suggestion": (
                            f"Either create task '{dep_id}' or remove it from "
                            f"the dependency list of '{task['id']}'."
                        ),
                    })
        return violations

    # ---- Rule: no_orphan_tasks ----

    def _check_orphan_tasks(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
        params: dict,
    ) -> List[Dict[str, Any]]:
        """Check for tasks with no connections (except plan/deploy)."""
        incoming: Dict[str, int] = defaultdict(int)
        outgoing: Dict[str, int] = defaultdict(int)

        for edge in edges:
            incoming[edge["to"]] += 1
            outgoing[edge["from"]] += 1

        # Ensure all task IDs are in the dicts
        for t in tasks:
            incoming.setdefault(t["id"], 0)
            outgoing.setdefault(t["id"], 0)

        violations: List[Dict[str, Any]] = []
        for t in tasks:
            tid = t["id"]
            task_type = t.get("type") or t.get("category", "")
            if task_type in ("planning", "deployment"):
                continue  # Expected to be root or leaf
            if incoming[tid] == 0 and outgoing[tid] == 0:
                violations.append({
                    "rule": "no_orphan_tasks",
                    "task_id": tid,
                    "severity": "warning",
                    "description": (
                        f"Task '{tid}' ({t.get('title', '')}) has no incoming "
                        "or outgoing dependencies -- it is orphaned."
                    ),
                    "suggestion": (
                        "Connect this task to the DAG by adding appropriate "
                        "dependencies, or remove it if it is not needed."
                    ),
                })
        return violations

    # ---- Rule: gate_ordering ----

    def _check_gate_ordering(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
        params: dict,
    ) -> List[Dict[str, Any]]:
        """Verify that deployment tasks follow testing tasks."""
        deploy_ids = {t["id"] for t in tasks if t.get("type") == "deployment" or "deploy" in t.get("id", "").lower()}
        test_ids = {t["id"] for t in tasks if t.get("type") == "testing" or "test" in t.get("id", "").lower()}

        if not deploy_ids or not test_ids:
            return []

        # Check if any deployment task precedes a testing task
        violations: List[Dict[str, Any]] = []
        adjacency: Dict[str, List[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])

        for did in deploy_ids:
            # BFS from deployment node; if we reach a test node, that's backwards
            visited: Set[str] = set()
            queue: deque = deque([did])
            while queue:
                node = queue.popleft()
                if node in visited:
                    continue
                visited.add(node)
                if node in test_ids and node != did:
                    violations.append({
                        "rule": "gate_ordering",
                        "task_id": did,
                        "severity": "warning",
                        "description": (
                            f"Deployment task '{did}' appears before testing task "
                            f"'{node}' in the DAG -- testing should gate deployment."
                        ),
                        "suggestion": (
                            "Reorder dependencies so all testing tasks complete "
                            "before deployment tasks begin."
                        ),
                    })
                    break
                for neighbor in adjacency.get(node, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

        return violations

    # ---- Scoring ----

    def _compute_score(
        self,
        checks_total: int,
        violations: List[Dict[str, Any]],
    ) -> float:
        """Compute architectural quality score (0-100).

        Each check starts with equal weight. Error violations deduct 100% of
        that check's weight; warnings deduct 50%.
        """
        if checks_total == 0:
            return 100.0

        weight_per_check = 100.0 / checks_total
        deductions = 0.0

        for v in violations:
            if v.get("severity") == "error":
                deductions += weight_per_check
            else:
                deductions += weight_per_check * 0.5

        return round(max(0.0, 100.0 - deductions), 1)

    # ---- Helpers ----

    def _derive_edges_from_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Derive edge list from tasks' dependencies field."""
        edges: List[Dict[str, str]] = []
        seen: Set[Tuple[str, str]] = set()
        for task in tasks:
            for dep_id in task.get("dependencies", []):
                key = (dep_id, task["id"])
                if key not in seen:
                    seen.add(key)
                    edges.append({"from": dep_id, "to": task["id"], "type": "sequential"})
        return edges

    @staticmethod
    def _default_suggestion(rule_name: str) -> str:
        """Return a generic suggestion for a rule when none is provided."""
        suggestions: Dict[str, str] = {
            "no_circular_deps": "Resolve circular dependency by refactoring or merging tasks.",
            "max_parallel_agents": "Reduce parallel group size or increase agent pool.",
            "max_dag_depth": "Flatten the DAG by reducing unnecessary sequential dependencies.",
            "no_missing_dependencies": "Add the missing task or remove the broken dependency.",
            "no_orphan_tasks": "Connect the task to the DAG or remove it.",
            "gate_ordering": "Ensure testing gates deployment in dependency order.",
        }
        return suggestions.get(rule_name, "Review and adjust the architecture to satisfy this rule.")

    # ---- Convenience ----

    @classmethod
    def quick_check(cls, dag: dict) -> bool:
        """Convenience: return True if DAG passes all error-level rules."""
        checker = cls()
        result = checker.check(dag)
        return result["passed"]

    @classmethod
    def score_only(cls, dag: dict) -> float:
        """Convenience: return just the score 0-100."""
        checker = cls()
        result = checker.check(dag)
        return float(result["score"])
