"""Codebase structure and dependency importer for the Neo4j knowledge graph.

Walks a repository's file tree to create :Codebase nodes with :CONTAINS
hierarchies and parses import/dependency edges across modules.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported languages / file extensions for dependency parsing
# ---------------------------------------------------------------------------
IMPORT_PATTERNS: Dict[str, str] = {
    ".py": r"^(?:from\s+(\S+)\s+)?import\s+(\S+)",
    ".ts": r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
    ".tsx": r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
    ".js": r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
    ".jsx": r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\))",
    ".go": r"^\s*\"([^\"]+)\"",
}

# Extensions that count as "files to index" (non-binary, non-vendor)
INDEXABLE_EXTENSIONS: Set[str] = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
    ".kt", ".swift", ".rb", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".cypher", ".sql", ".yaml", ".yml", ".json", ".toml", ".sh",
    ".ps1", ".dockerfile", ".md",
}

SKIP_DIRS: Set[str] = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "target",
}


class CodebaseImporter:
    """Imports repository file structure and dependency relationships.

    Uses the async Neo4j Python driver to batch-create nodes and edges.
    Stub implementation with realistic directory traversal — no actual
    DB connection required to exercise the import logic.
    """

    def __init__(self, driver=None) -> None:
        """Initialise with an optional async Neo4j driver.

        Args:
            driver: An instance of ``neo4j.async_.driver``.  When ``None``
                the importer runs in dry-run / stub mode.
        """
        self._driver = driver  # neo4j.async_.driver | None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def import_structure(self, repo_path: str) -> dict:
        """Walk *repo_path* and create :Codebase nodes and :CONTAINS edges.

        Returns a dict of::

            {
                "nodes_created": <int>,
                "relationships_created": <int>,
                "files_indexed": <int>,
            }
        """
        logger.info("CodebaseImporter.import_structure(repo_path=%r)", repo_path)
        root = Path(repo_path).resolve()
        if not root.exists() or not root.is_dir():
            logger.error("Repository path does not exist: %s", root)
            return {"nodes_created": 0, "relationships_created": 0, "files_indexed": 0, "error": "path_not_found"}

        nodes: List[dict] = []
        relationships: List[Tuple[str, str, str]] = []  # (parent_id, child_id, relationship_type)
        files_indexed = 0

        for entry in root.rglob("*"):
            if self._should_skip(entry):
                continue

            rel = entry.relative_to(root)
            node_id = f"cb:{rel.as_posix()}"
            language = self._infer_language(entry)
            module = rel.parts[0] if len(rel.parts) > 1 else "root"

            is_file = entry.is_file()
            nodes.append({
                "id": node_id,
                "repo_path": str(rel),
                "language": language,
                "module": module,
                "is_file": is_file,
                "size_bytes": entry.stat().st_size if is_file else 0,
            })

            # Link to parent directory
            if str(rel) != ".":
                parent_rel = rel.parent
                parent_id = f"cb:{parent_rel.as_posix()}" if str(parent_rel) != "." else "cb:root"
                relationships.append((parent_id, node_id, "CONTAINS"))

            if is_file and entry.suffix in INDEXABLE_EXTENSIONS:
                files_indexed += 1

        # Add the root node itself
        nodes.append({
            "id": "cb:root",
            "repo_path": root.name,
            "language": "",
            "module": "root",
            "is_file": False,
            "size_bytes": 0,
        })

        logger.info(
            "Codebase import complete: %d nodes, %d relationships, %d indexable files",
            len(nodes), len(relationships), files_indexed,
        )
        return {
            "nodes_created": len(nodes),
            "relationships_created": len(relationships),
            "files_indexed": files_indexed,
        }

    async def import_dependencies(self, repo_path: str) -> dict:
        """Parse import/dependency edges between codebase modules.

        Stub: walks the tree and where a file contains recognised import
        statements, records a ``:DEPENDS_ON`` edge candidate.

        Returns a dict of::

            {
                "dependencies_found": <int>,
                "nodes_created": <int>,
                "relationships_created": <int>,
                "errors": [<str>, ...],
            }
        """
        logger.info("CodebaseImporter.import_dependencies(repo_path=%r)", repo_path)
        root = Path(repo_path).resolve()
        if not root.exists():
            return {"dependencies_found": 0, "nodes_created": 0, "relationships_created": 0, "errors": ["path_not_found"]}

        dependencies_found = 0
        relationships: List[Tuple[str, str]] = []
        errors: List[str] = []

        for entry in root.rglob("*"):
            if self._should_skip(entry) or not entry.is_file():
                continue
            ext = entry.suffix
            if ext not in IMPORT_PATTERNS:
                continue

            try:
                content = entry.read_text(encoding="utf-8", errors="ignore")
                pattern = IMPORT_PATTERNS[ext]
                for match in re.finditer(pattern, content, re.MULTILINE):
                    imported = self._extract_import_target(match, ext)
                    if imported:
                        source_id = f"cb:{entry.relative_to(root).as_posix()}"
                        # Best-effort target resolution
                        target_path = self._resolve_import_target(root, imported, ext)
                        if target_path:
                            target_id = f"cb:{target_path.as_posix()}"
                            relationships.append((source_id, target_id))
                            dependencies_found += 1
            except Exception as exc:
                err = f"{entry.relative_to(root)}: {exc}"
                errors.append(err)
                logger.debug("Dependency parse error: %s", err)

        logger.info(
            "Dependency import complete: %d dependencies, %d errors",
            dependencies_found, len(errors),
        )
        return {
            "dependencies_found": dependencies_found,
            "nodes_created": 0,  # no new nodes beyond what import_structure creates
            "relationships_created": len(relationships),
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _should_skip(entry: Path) -> bool:
        """Return True if the path should be skipped during traversal."""
        for part in entry.parts:
            if part in SKIP_DIRS:
                return True
        return False

    @staticmethod
    def _infer_language(entry: Path) -> str:
        """Infer language from file extension."""
        ext_map: Dict[str, str] = {
            ".py": "python",
            ".ts": "typescript", ".tsx": "typescript",
            ".js": "javascript", ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".kt": "kotlin",
            ".swift": "swift",
            ".rb": "ruby",
            ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
            ".cs": "csharp",
        }
        return ext_map.get(entry.suffix, "")

    @staticmethod
    def _extract_import_target(match: re.Match, ext: str) -> Optional[str]:
        """Extract the import target string from a regex match."""
        # Python: group 1 (from … import) or group 2 (import …)
        # JS/TS: group 1 (import from) or group 2 (require)
        groups = [g for g in match.groups() if g is not None]
        return groups[0] if groups else None

    @staticmethod
    def _resolve_import_target(root: Path, imported: str, ext: str) -> Optional[Path]:
        """Resolve an import string to a relative path under *root*.

        Stub: tries common resolution patterns.  A production implementation
        would consult package manifests (package.json, pyproject.toml, etc.).
        """
        # Try as-is
        candidate = root / imported
        if candidate.is_file():
            return candidate.relative_to(root)
        # Try with extension
        candidate = root / f"{imported}{ext}"
        if candidate.is_file():
            return candidate.relative_to(root)
        # Python: dotted path → filesystem
        if ext == ".py":
            candidate = root / imported.replace(".", os.sep)
            if candidate.is_dir() or candidate.with_suffix(".py").is_file():
                return candidate.relative_to(root).with_suffix(".py")
        return None
