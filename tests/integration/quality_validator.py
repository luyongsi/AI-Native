"""
Quality Validator for Phase 6 E2E tests.

Validates API schemas, code quality, test coverage, and other artifacts.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


class QualityValidator:
    """Validates the quality of generated artifacts."""

    def __init__(self, db_pool: Optional[asyncpg.Pool] = None):
        self.db_pool = db_pool

    async def validate_api_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate API schema structure.

        Returns dict with:
        - valid: bool
        - score: 0-5
        - errors: list of issues
        """
        errors = []
        score = 5

        # Check basic structure
        if not isinstance(schema, dict):
            errors.append("Schema is not a dictionary")
            return {"valid": False, "score": 0, "errors": errors}

        # Check required fields
        required_fields = ["openapi", "info", "paths"]
        for field in required_fields:
            if field not in schema:
                errors.append(f"Missing required field: {field}")
                score -= 1

        # Validate OpenAPI version
        if "openapi" in schema:
            openapi_version = schema["openapi"]
            if not re.match(r"^3\.\d\.\d$", str(openapi_version)):
                errors.append(f"Invalid OpenAPI version: {openapi_version}")
                score -= 1

        # Validate paths
        if "paths" in schema and isinstance(schema["paths"], dict):
            for path, methods in schema["paths"].items():
                if not isinstance(methods, dict):
                    errors.append(f"Path {path} methods are not a dictionary")
                    score -= 1
                    continue

                for method, details in methods.items():
                    if method not in ["get", "post", "put", "patch", "delete", "head", "options"]:
                        continue

                    if not isinstance(details, dict):
                        errors.append(f"Path {path} method {method} is not a dictionary")
                        score -= 1

        # Validate info section
        if "info" in schema and isinstance(schema["info"], dict):
            info = schema["info"]
            if "title" not in info:
                errors.append("Missing info.title")
                score -= 1
            if "version" not in info:
                errors.append("Missing info.version")
                score -= 1

        score = max(0, score)
        return {
            "valid": len(errors) == 0,
            "score": score,
            "errors": errors,
        }

    async def validate_code_quality(self, code_content: str) -> Dict[str, Any]:
        """
        Validate code quality using basic heuristics.

        Returns dict with:
        - score: 0-5
        - issues: list of quality issues
        """
        issues = []
        score = 5

        # Check for basic structure
        if not code_content or len(code_content.strip()) == 0:
            return {"score": 0, "issues": ["Code is empty"]}

        lines = code_content.split("\n")

        # Check line length (max 100 characters)
        long_lines = sum(1 for line in lines if len(line) > 100)
        if long_lines > len(lines) * 0.1:
            issues.append(f"Many long lines ({long_lines}/{len(lines)})")
            score -= 1

        # Check for code comments
        comment_lines = sum(
            1 for line in lines
            if line.strip().startswith("#") or line.strip().startswith("//")
        )
        if comment_lines < len(lines) * 0.05:
            issues.append("Insufficient comments")
            score -= 1

        # Check for proper indentation (Python)
        indent_issues = 0
        for line in lines:
            if line and not line[0].isspace() and not line[0] == "#":
                if len(line.lstrip()) > 0 and line[0] == " " * 4:
                    indent_issues += 1

        if indent_issues > len(lines) * 0.1:
            issues.append("Inconsistent indentation")
            score -= 1

        # Check for function/class definitions
        has_functions = any("def " in line for line in lines)
        if not has_functions:
            issues.append("No function definitions found")
            score -= 1

        score = max(0, score)
        return {
            "score": score,
            "issues": issues,
            "lines": len(lines),
        }

    async def validate_test_coverage(self, req_id: str) -> Dict[str, Any]:
        """
        Validate test coverage metrics from database.

        Returns dict with:
        - coverage: percentage
        - passed: count
        - failed: count
        - pass_rate: percentage
        - quality_score: 0-5
        """
        if not self.db_pool:
            return {
                "coverage": 0,
                "passed": 0,
                "failed": 0,
                "pass_rate": 0,
                "quality_score": 0,
            }

        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    SELECT
                        passed, failed, coverage,
                        quality_score
                    FROM test_executions
                    WHERE req_id = $1
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    req_id,
                )

            if not result:
                return {
                    "coverage": 0,
                    "passed": 0,
                    "failed": 0,
                    "pass_rate": 0,
                    "quality_score": 0,
                }

            passed = result["passed"] or 0
            failed = result["failed"] or 0
            coverage = result["coverage"] or 0
            quality_score = result["quality_score"] or 0

            total = passed + failed
            pass_rate = (passed / total * 100) if total > 0 else 0

            return {
                "coverage": float(coverage),
                "passed": passed,
                "failed": failed,
                "pass_rate": float(pass_rate),
                "quality_score": float(quality_score),
            }

        except Exception as e:
            logger.error(f"Error validating test coverage: {e}")
            return {
                "coverage": 0,
                "passed": 0,
                "failed": 0,
                "pass_rate": 0,
                "quality_score": 0,
            }

    async def validate_erd(self, erd_content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate ERD (Entity Relationship Diagram) structure.

        Returns dict with:
        - valid: bool
        - score: 0-5
        - errors: list
        - table_count: int
        - relationship_count: int
        """
        errors = []
        score = 5

        if not isinstance(erd_content, dict):
            errors.append("ERD content is not a dictionary")
            return {
                "valid": False,
                "score": 0,
                "errors": errors,
                "table_count": 0,
                "relationship_count": 0,
            }

        # Check for tables
        tables = erd_content.get("tables", [])
        if not tables:
            errors.append("No tables defined in ERD")
            score -= 2
        elif len(tables) < 2:
            errors.append("ERD should have at least 2 tables")
            score -= 1

        # Check for relationships
        relationships = erd_content.get("relationships", [])
        if len(tables) > 1 and not relationships:
            errors.append("No relationships defined between tables")
            score -= 1

        # Validate table structure
        for table in tables:
            if not isinstance(table, dict):
                errors.append("Invalid table structure")
                score -= 1
                continue

            if "name" not in table:
                errors.append("Table missing name")
                score -= 1

            if "columns" not in table or not table["columns"]:
                errors.append(f"Table {table.get('name', 'unknown')} has no columns")
                score -= 1

        score = max(0, score)
        return {
            "valid": len(errors) == 0,
            "score": score,
            "errors": errors,
            "table_count": len(tables),
            "relationship_count": len(relationships),
        }

    async def validate_dag(self, dag_content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate DAG (Directed Acyclic Graph) structure.

        Returns dict with:
        - valid: bool
        - score: 0-5
        - errors: list
        - node_count: int
        - edge_count: int
        - has_cycles: bool
        """
        errors = []
        score = 5

        if not isinstance(dag_content, dict):
            errors.append("DAG content is not a dictionary")
            return {
                "valid": False,
                "score": 0,
                "errors": errors,
                "node_count": 0,
                "edge_count": 0,
                "has_cycles": False,
            }

        # Check for nodes
        nodes = dag_content.get("nodes", [])
        if not nodes:
            errors.append("DAG has no nodes")
            score -= 2
        elif len(nodes) < 2:
            errors.append("DAG should have at least 2 nodes")
            score -= 1

        # Check for edges
        edges = dag_content.get("edges", [])
        if nodes and not edges:
            errors.append("DAG has no edges")
            score -= 1

        # Basic cycle detection
        has_cycles = self._detect_cycles(nodes, edges)
        if has_cycles:
            errors.append("DAG contains cycles (should be acyclic)")
            score -= 2

        # Validate node structure
        for node in nodes:
            if not isinstance(node, dict):
                errors.append("Invalid node structure")
                score -= 1
                continue

            if "id" not in node:
                errors.append("Node missing id")
                score -= 1

            if "type" not in node:
                errors.append("Node missing type")
                score -= 1

        score = max(0, score)
        return {
            "valid": len(errors) == 0 and not has_cycles,
            "score": score,
            "errors": errors,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "has_cycles": has_cycles,
        }

    def _detect_cycles(self, nodes: List[Dict], edges: List[Dict]) -> bool:
        """Simple cycle detection using DFS."""
        if not edges:
            return False

        # Build adjacency list
        graph = {}
        for node in nodes:
            graph[node.get("id")] = []

        for edge in edges:
            src = edge.get("source")
            dst = edge.get("target")
            if src in graph and dst in graph:
                graph[src].append(dst)

        # DFS to detect cycles
        visited = set()
        rec_stack = set()

        def has_cycle(node):
            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in graph:
            if node not in visited:
                if has_cycle(node):
                    return True

        return False

    async def validate_all(
        self,
        req_id: str,
        api_schema: Optional[Dict[str, Any]] = None,
        erd: Optional[Dict[str, Any]] = None,
        dag: Optional[Dict[str, Any]] = None,
        code_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run all validations and return comprehensive results.

        Returns dict with overall score and individual validation results.
        """
        results = {}

        if api_schema:
            results["api_schema"] = await self.validate_api_schema(api_schema)
        else:
            results["api_schema"] = None

        if erd:
            results["erd"] = await self.validate_erd(erd)
        else:
            results["erd"] = None

        if dag:
            results["dag"] = await self.validate_dag(dag)
        else:
            results["dag"] = None

        if code_content:
            results["code"] = await self.validate_code_quality(code_content)
        else:
            results["code"] = None

        results["tests"] = await self.validate_test_coverage(req_id)

        # Calculate overall score
        scores = []
        for key in ["api_schema", "erd", "dag", "code"]:
            if results[key]:
                scores.append(results[key].get("score", 0))

        if results["tests"]:
            scores.append(results["tests"].get("quality_score", 0))

        overall_score = (sum(scores) / len(scores)) if scores else 0

        return {
            "overall_score": overall_score,
            "validations": results,
        }
