"""
a12/cross_module_analyzer.py — Cross-Module Analyzer

Analyzes code diffs for cross-module impact: identifies which modules
are affected, assigns impact levels, computes a risk score, and tracks
dependency graph changes.

Real implementation pattern:
  - Parse a module dependency graph (import graph, package.json deps, etc.)
  - For each changed file, walk the graph to find downstream dependents
  - Use AST analysis to detect breaking API changes (removed exports,
    changed function signatures, etc.)
  - Integrate with language servers for precise symbol-level impact
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Module-to-dependencies mapping used for stub analysis
MODULE_DEPENDENCY_MAP = {
    "src/api": {"deps": ["src/services", "src/models", "src/middleware"], "team": "platform"},
    "src/services": {"deps": ["src/models", "src/utils", "src/db"], "team": "backend"},
    "src/models": {"deps": ["src/db", "src/config"], "team": "data"},
    "src/components": {"deps": ["src/utils", "src/hooks"], "team": "frontend"},
    "src/routes": {"deps": ["src/components", "src/services", "src/middleware"], "team": "fullstack"},
    "src/utils": {"deps": [], "team": "shared"},
    "src/middleware": {"deps": ["src/utils", "src/config"], "team": "platform"},
    "src/hooks": {"deps": ["src/utils", "src/services"], "team": "frontend"},
    "src/db": {"deps": ["src/config"], "team": "data"},
    "src/config": {"deps": [], "team": "shared"},
    "tests": {"deps": ["src/*"], "team": "qa"},
}


class CrossModuleAnalyzer:
    """Analyzes code changes for cross-module impact.

    Works with a module dependency graph to determine which downstream
    modules are affected by a given set of file changes, and computes
    an aggregate risk score.
    """

    def __init__(self, dependency_map: dict | None = None):
        self.dependency_map = dependency_map or MODULE_DEPENDENCY_MAP

    async def analyze(
        self,
        diff: dict,
        codebase_context: dict | None = None,
    ) -> dict:
        """Analyze a diff for cross-module impact.

        Args:
            diff: Change dict with a "changes" list containing
                  {"path": str, "type": "modified"|"added"|"deleted", ...}
            codebase_context: Optional context (dependency graph overrides, etc.)

        Returns:
            dict with affected_modules[], total_affected, risk_score, dependency_graph_changes[]
        """
        logger.info("Cross-module analysis starting...")

        # Simulate analysis time
        await asyncio.sleep(0.2)

        changes = diff.get("changes", []) if isinstance(diff, dict) else diff
        if not changes:
            logger.info("No changes to analyze")
            return {
                "affected_modules": [],
                "total_affected": 0,
                "risk_score": 0,
                "dependency_graph_changes": [],
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

        affected_modules: list[dict] = []
        seen_modules: set[str] = set()
        dependency_graph_changes: list[dict] = []
        total_risk = 0

        for change in changes:
            file_path = change.get("path", change) if isinstance(change, dict) else str(change)
            change_type = change.get("type", "modified") if isinstance(change, dict) else "modified"

            # Find which module the file belongs to
            owning_module = self._resolve_module(file_path)
            if owning_module is None:
                continue

            # Determine impact level based on change type and module role
            impact_level = self._assess_impact(file_path, change_type, owning_module)

            # Walk downstream dependents
            dependents = self._find_dependents(owning_module)

            if owning_module not in seen_modules:
                affected_modules.append({
                    "name": owning_module,
                    "file_paths": [file_path],
                    "impact_level": impact_level,
                    "reason": self._build_reason(file_path, change_type, owning_module, dependents),
                })
                seen_modules.add(owning_module)
            else:
                # Append file path to existing entry
                for am in affected_modules:
                    if am["name"] == owning_module:
                        am["file_paths"].append(file_path)
                        # Escalate impact if higher
                        if self._impact_rank(impact_level) > self._impact_rank(am["impact_level"]):
                            am["impact_level"] = impact_level
                        break

            # Track dependency graph changes
            for dep in dependents:
                dep_change = {
                    "source": owning_module,
                    "target": dep,
                    "change_type": change_type,
                    "file": file_path,
                }
                dependency_graph_changes.append(dep_change)

            # Accumulate risk
            risk_weights = {"low": 10, "medium": 25, "high": 50}
            total_risk += risk_weights.get(impact_level, 5)

        # Normalize risk_score to 0-100
        risk_score = min(total_risk, 100)

        result = {
            "affected_modules": affected_modules,
            "total_affected": len(affected_modules),
            "risk_score": risk_score,
            "dependency_graph_changes": dependency_graph_changes,
            "total_changes_analyzed": len(changes),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "Cross-module analysis complete: %d modules affected, risk=%d/100",
            result["total_affected"], risk_score,
        )
        return result

    def _resolve_module(self, file_path: str) -> str | None:
        """Map a file path to its owning module using prefix matching."""
        for module_name in sorted(self.dependency_map.keys(), key=len, reverse=True):
            if file_path.startswith(module_name):
                return module_name
        # Check for root-level config files
        if file_path in ("package.json", "requirements.txt", "pyproject.toml", "go.mod"):
            return "root-config"
        return None

    def _find_dependents(self, module_name: str) -> list[str]:
        """Find all modules that depend on the given module."""
        dependents = []
        for mod, info in self.dependency_map.items():
            if module_name in info.get("deps", []):
                dependents.append(mod)
        return dependents

    def _assess_impact(self, file_path: str, change_type: str, module_name: str) -> str:
        """Determine impact level: high, medium, or low."""
        # Deleted files have higher impact
        if change_type == "deleted":
            return "high"

        # Interface/signature files
        if any(kw in file_path for kw in ["interface", "types", "schema", "proto"]):
            return "high"

        # Core infrastructure
        if module_name in ("src/db", "src/middleware", "src/config"):
            return "high" if change_type != "added" else "medium"

        # Service layer
        if module_name in ("src/services", "src/routes", "src/api"):
            return "medium"

        # Utility / UI
        if module_name in ("src/utils", "src/components", "src/hooks"):
            return "low"

        # Tests
        if module_name == "tests":
            return "low"

        return "medium"

    def _build_reason(
        self,
        file_path: str,
        change_type: str,
        module_name: str,
        dependents: list[str],
    ) -> str:
        """Build a human-readable reason for the impact assessment."""
        verb = {"added": "Added", "modified": "Modified", "deleted": "Deleted"}.get(
            change_type, "Changed"
        )
        base = f"{verb} {file_path} in module '{module_name}'"
        if dependents:
            base += f"; downstream dependents: {', '.join(dependents)}"
        return base

    @staticmethod
    def _impact_rank(level: str) -> int:
        return {"low": 1, "medium": 2, "high": 3}.get(level, 0)
