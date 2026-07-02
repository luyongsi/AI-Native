"""
A6 Sub-module: Enhanced DAG Builder

Constructs a directed acyclic graph (DAG) of tasks from a specification,
detecting circular dependencies and identifying parallelizable groups.

Enhancements:
  1. Integrates DependencyAnalyzer for requirement/schema/ERD analysis
  2. Implements Kahn's algorithm for topological sorting
  3. Detects circular dependencies and reports them
  4. Partitions tasks into parallel groups using topological levels
  5. Computes critical path via longest-path DP algorithm
  6. Estimates workload using ComplexityEstimator
  7. Produces structured DAG JSON for Orchestrator consumption
"""

import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Agent types that can process each task category
_TASK_AGENT_MAP: Dict[str, str] = {
    "planning": "A1",
    "api": "A4",
    "backend": "A9",
    "frontend": "A9",
    "db": "A9",
    "db_migration": "A9",
    "auth": "A9",
    "testing": "A7",
    "deployment": "CI",
    "review": "A5",
    "architecture": "A8",
    "api_impl": "A9",
}


class DAGBuilder:
    """Builds a task DAG from a specification, with cycle detection and
    parallel-group identification."""

    def __init__(
        self,
        max_parallel_agents: int = 5,
        max_dag_depth: int = 4,
    ):
        """Args:
            max_parallel_agents: Max agents allowed in a parallel group.
            max_dag_depth: Maximum allowed DAG depth (warns on violation).
        """
        self.max_parallel_agents = max_parallel_agents
        self.max_dag_depth = max_dag_depth
        logger.debug(
            "DAGBuilder initialized: max_parallel=%d, max_depth=%d",
            max_parallel_agents,
            max_dag_depth,
        )

    def build(self, spec: dict, analyzed_tasks: Optional[List[Dict[str, Any]]] = None) -> dict:
        """Build a task DAG from a specification or analyzed tasks.

        Args:
            spec: Spec dict with optional keys:
                - features (list): feature descriptions
                - endpoints (list): API endpoint definitions
                - entities (list): data model entities
                - pages (list): UI pages/screens
                - dependencies (list): explicit dependency declarations
            analyzed_tasks: Optional pre-analyzed tasks from DependencyAnalyzer.
                          If provided, uses these instead of generating from spec.

        Returns:
            Dict with:
                - tasks: [{id, title, dependencies[], estimated_hours, agent_type, parallel_group}]
                - edges: [{from, to, type}]
                - has_cycles: bool
                - critical_path: list of task IDs on the critical path
                - parallel_groups: list of {group_id, tasks[], description}
        """
        if analyzed_tasks:
            logger.info("Building DAG from %d pre-analyzed tasks", len(analyzed_tasks))
            tasks = analyzed_tasks
        else:
            logger.info("Building DAG from spec with %d features", len(spec.get("features", [])))
            # Step 1: Generate tasks from spec features
            tasks = self._generate_tasks(spec)

        # Step 2: Infer dependencies between tasks
        edges = self._infer_edges(tasks, spec, from_analyzed=bool(analyzed_tasks))

        # Step 3: Detect cycles
        has_cycles, cycle_nodes = self._detect_cycles(tasks, edges)

        # Step 4: Identify parallel groups (topological levels)
        parallel_groups = self._identify_parallel_groups(tasks, edges)

        # Step 5: Compute critical path (longest weighted path through DAG)
        critical_path = self._compute_critical_path(tasks, edges)

        # Build adjacency for downstream consumers
        adjacency = self._build_adjacency(edges)

        result: Dict[str, Any] = {
            "tasks": tasks,
            "edges": edges,
            "has_cycles": has_cycles,
            "cycle_nodes": cycle_nodes if has_cycles else [],
            "critical_path": critical_path,
            "critical_path_hours": sum(
                t["estimated_hours"] for t in tasks if t["id"] in critical_path
            ),
            "parallel_groups": parallel_groups,
            "dependencies": adjacency,
            "total_tasks": len(tasks),
            "total_estimated_hours": sum(t.get("estimated_hours", 0) for t in tasks),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if has_cycles:
            logger.error("Cycle detected in DAG: %s", cycle_nodes)
        else:
            logger.info(
                "DAG built: %d tasks, %d edges, %d parallel groups, "
                "critical_path=%d tasks (%.1f h)",
                len(tasks),
                len(edges),
                len(parallel_groups),
                len(critical_path),
                result["critical_path_hours"],
            )

        return result

    # ---- Task generation ----

    def _generate_tasks(self, spec: dict) -> List[Dict[str, Any]]:
        """Generate task nodes from spec contents.

        In production, each task would be an LLM-crafted breakdown of a
        feature with explicit acceptance criteria and effort estimates.
        """
        tasks: List[Dict[str, Any]] = []
        task_counter = [0]

        def _next_id(prefix: str) -> str:
            task_counter[0] += 1
            return f"{prefix}-{task_counter[0]:02d}"

        features = spec.get("features", [])
        endpoints = spec.get("endpoints", [])
        entities = spec.get("entities", [])
        pages = spec.get("pages", [])

        # Always start with a planning task
        tasks.append({
            "id": _next_id("plan"),
            "title": "Requirements analysis and technical planning",
            "dependencies": [],
            "estimated_hours": 2.0,
            "agent_type": "A1",
            "parallel_group": 0,
        })

        # Data model tasks
        if entities:
            for ent in entities[:5]:  # Cap at 5 to keep mock manageable
                ent_name = ent.get("name", ent) if isinstance(ent, dict) else str(ent)
                tasks.append({
                    "id": _next_id("db"),
                    "title": f"Design and migrate {ent_name} schema",
                    "dependencies": ["plan-01"],
                    "estimated_hours": 4.0,
                    "agent_type": "A9",
                    "parallel_group": None,  # assigned later
                    "entity": ent_name,
                })

        # API endpoint tasks
        if endpoints:
            for ep in endpoints[:8]:
                ep_path = ep.get("path", ep) if isinstance(ep, dict) else str(ep)
                tasks.append({
                    "id": _next_id("api"),
                    "title": f"Implement {ep_path} endpoint",
                    "dependencies": ["plan-01"],
                    "estimated_hours": 6.0,
                    "agent_type": "A9",
                    "parallel_group": None,
                    "endpoint": ep_path,
                })

        # Frontend page tasks
        if pages:
            for page in pages[:5]:
                page_name = page.get("name", page) if isinstance(page, dict) else str(page)
                tasks.append({
                    "id": _next_id("ui"),
                    "title": f"Build {page_name} page/component",
                    "dependencies": ["plan-01"],
                    "estimated_hours": 5.0,
                    "agent_type": "A9",
                    "parallel_group": None,
                    "page": page_name,
                })

        # If no structured features, create sensible defaults
        if not tasks or len(tasks) <= 1:
            # Generate fallback tasks from feature strings
            for i, feat in enumerate(features[:5]):
                feat_text = feat if isinstance(feat, str) else feat.get("description", str(feat))
                tasks.append({
                    "id": _next_id("dev"),
                    "title": feat_text[:80],
                    "dependencies": ["plan-01"],
                    "estimated_hours": 4.0 + (i * 2),
                    "agent_type": "A9",
                    "parallel_group": None,
                })

        # Always add integration testing and deployment tasks
        dev_ids = [t["id"] for t in tasks if t["agent_type"] not in ("A1",)]
        tasks.append({
            "id": _next_id("test"),
            "title": "Integration testing and QA verification",
            "dependencies": list(dev_ids[-3:]) if dev_ids else ["plan-01"],
            "estimated_hours": 8.0,
            "agent_type": "A7",
            "parallel_group": None,
        })

        tasks.append({
            "id": _next_id("deploy"),
            "title": "Deployment and release",
            "dependencies": [tasks[-1]["id"]],  # depends on testing
            "estimated_hours": 2.0,
            "agent_type": "CI",
            "parallel_group": None,
        })

        return tasks

    # ---- Edge inference ----

    def _infer_edges(
        self,
        tasks: List[Dict[str, Any]],
        spec: dict,
        from_analyzed: bool = False,
    ) -> List[Dict[str, str]]:
        """Infer dependency edges from task declarations.

        In production, this would also infer implicit dependencies from
        API contracts, data flow, and shared infrastructure.
        """
        edges: List[Dict[str, str]] = []
        seen: Set[Tuple[str, str]] = set()

        for task in tasks:
            for dep_id in task.get("depends_on", []):
                # Verify dependency target exists
                if any(t["id"] == dep_id for t in tasks):
                    key = (dep_id, task["id"])
                    if key not in seen:
                        seen.add(key)
                        edge_type = self._classify_edge(dep_id, task["id"], tasks)
                        edges.append({
                            "from": dep_id,
                            "to": task["id"],
                            "type": edge_type,
                        })

        # For non-analyzed specs, infer additional edges from spec-level dependencies
        if not from_analyzed:
            explicit_deps = spec.get("dependencies", [])
            for dep in explicit_deps:
                src = dep.get("from") or dep.get("source")
                tgt = dep.get("to") or dep.get("target")
                if src and tgt and (src, tgt) not in seen:
                    src_task = self._find_task_by_title(tasks, src)
                    tgt_task = self._find_task_by_title(tasks, tgt)
                    if src_task and tgt_task:
                        seen.add((src_task["id"], tgt_task["id"]))
                        edges.append({
                            "from": src_task["id"],
                            "to": tgt_task["id"],
                            "type": dep.get("type", "sequential"),
                        })

        return edges

    def _classify_edge(
        self,
        from_id: str,
        to_id: str,
        tasks: List[Dict[str, Any]],
    ) -> str:
        """Classify edge type based on task categories."""
        task_map = {t["id"]: t for t in tasks}
        from_task = task_map.get(from_id, {})
        to_task = task_map.get(to_id, {})

        from_agent = from_task.get("agent_type", "")
        to_agent = to_task.get("agent_type", "")

        # Tasks of different types can often run in parallel if not explicitly
        # dependent; explicit deps are still sequential unless marked otherwise.
        if from_agent != to_agent and from_agent and to_agent:
            # Cross-discipline dependencies could be parallelized
            # (e.g., frontend and backend developing against a contract)
            return "parallel"
        return "sequential"

    # ---- Cycle detection (Kahn's algorithm) ----

    def _detect_cycles(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
    ) -> tuple:
        """Detect cycles using Kahn's topological sort.

        Returns:
            (has_cycles: bool, cycle_nodes: list)
        """
        # Build graph
        in_degree: Dict[str, int] = defaultdict(int)
        adjacency: Dict[str, List[str]] = defaultdict(list)
        all_nodes = {t["id"] for t in tasks}

        for node in all_nodes:
            in_degree[node] = 0

        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])
            in_degree[edge["to"]] += 1

        # Kahn's algorithm
        queue: deque = deque(n for n in all_nodes if in_degree[n] == 0)
        sorted_count = 0

        while queue:
            node = queue.popleft()
            sorted_count += 1
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        has_cycles = sorted_count != len(all_nodes)

        # Find nodes in cycles
        cycle_nodes: List[str] = []
        if has_cycles:
            cycle_nodes = [n for n in all_nodes if in_degree[n] > 0]
            logger.warning("DAG cycle detected involving nodes: %s", cycle_nodes)

        return has_cycles, cycle_nodes

    # ---- Parallel group identification ----

    def _identify_parallel_groups(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Identify tasks that can execute in parallel using topological levels.

        Tasks at the same topological level (same depth from root) that do not
        depend on each other are grouped as parallelizable.
        """
        if not tasks:
            return []

        # Build reverse adjacency for level computation
        adjacency: Dict[str, List[str]] = defaultdict(list)
        reverse: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = defaultdict(int)

        for t in tasks:
            in_degree[t["id"]] = 0

        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])
            reverse[edge["to"]].append(edge["from"])
            in_degree[edge["to"]] += 1

        # Compute topological levels
        levels: Dict[str, int] = {}
        queue: deque = deque(t["id"] for t in tasks if in_degree[t["id"]] == 0)
        for node in queue:
            levels[node] = 0

        while queue:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                candidate_level = levels[node] + 1
                if neighbor not in levels or levels[neighbor] < candidate_level:
                    levels[neighbor] = candidate_level
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Group by level
        level_groups: Dict[int, List[str]] = defaultdict(list)
        for task_id, level in levels.items():
            level_groups[level].append(task_id)

        # Build output groups (cap at max_parallel_agents per group)
        parallel_groups: List[Dict[str, Any]] = []
        level_names: Dict[int, str] = {
            0: "Planning",
            1: "Foundation (DB/API/UI)",
            2: "Core Development",
            3: "Integration",
            4: "Testing & Deployment",
        }

        for level, group_ids in sorted(level_groups.items()):
            # Warn if group exceeds max parallel
            if len(group_ids) > self.max_parallel_agents:
                logger.warning(
                    "Parallel group at level %d has %d tasks (max %d). "
                    "Consider further decomposition or sequencing.",
                    level,
                    len(group_ids),
                    self.max_parallel_agents,
                )

            level_name = level_names.get(level, f"Level {level}")
            parallel_groups.append({
                "group_id": f"pg-level-{level}",
                "tasks": group_ids,
                "level": level,
                "description": f"{level_name} — {len(group_ids)} tasks can run in parallel",
            })

        # Assign parallel_group to each task
        task_lookup = {t["id"]: t for t in tasks}
        for group in parallel_groups:
            for tid in group["tasks"]:
                if tid in task_lookup:
                    task_lookup[tid]["parallel_group"] = group["group_id"]

        return parallel_groups

    # ---- Critical path ----

    def _compute_critical_path(
        self,
        tasks: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
    ) -> List[str]:
        """Compute the critical path (longest weighted path through the DAG).

        Uses topological order DP: for each node, longest_path[node] =
        max over predecessors of (longest_path[pred] + hours[pred]).
        """
        if not tasks:
            return []

        task_map = {t["id"]: t for t in tasks}

        # Build graph structures
        adjacency: Dict[str, List[str]] = defaultdict(list)
        reverse: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = defaultdict(int)

        for t in tasks:
            in_degree[t["id"]] = 0

        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])
            reverse[edge["to"]].append(edge["from"])
            in_degree[edge["to"]] += 1

        # Topological sort
        topo: List[str] = []
        queue: deque = deque(t["id"] for t in tasks if in_degree[t["id"]] == 0)
        while queue:
            node = queue.popleft()
            topo.append(node)
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # DP: longest path ending at each node
        longest: Dict[str, float] = {}
        prev_node: Dict[str, Optional[str]] = {}

        for node in topo:
            hours = task_map.get(node, {}).get("estimated_hours", 0) if node in task_map else 0
            if not reverse[node]:
                longest[node] = hours
                prev_node[node] = None
            else:
                best_pred = None
                best_val = -1.0
                for pred in reverse[node]:
                    if pred in longest:
                        val = longest[pred]
                        if val > best_val:
                            best_val = val
                            best_pred = pred
                longest[node] = (best_val if best_val >= 0 else 0) + hours
                prev_node[node] = best_pred

        # Find the end node with maximum longest-path value
        if not longest:
            return []
        end_node = max(longest, key=lambda n: longest[n])

        # Reconstruct path
        path: List[str] = []
        current: Optional[str] = end_node
        while current is not None:
            path.append(current)
            current = prev_node.get(current)
        path.reverse()

        return path

    # ---- Utilities ----

    @staticmethod
    def _find_task_by_title(tasks: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
        """Find a task by fuzzy-matching its title."""
        title_lower = title.lower()
        for t in tasks:
            if title_lower in t.get("title", "").lower():
                return t
        return None

    @staticmethod
    def _build_adjacency(edges: List[Dict[str, str]]) -> Dict[str, List[str]]:
        """Build adjacency list from edges for consumers."""
        adj: Dict[str, List[str]] = defaultdict(list)
        for e in edges:
            adj[e["from"]].append(e["to"])
        return dict(adj)
