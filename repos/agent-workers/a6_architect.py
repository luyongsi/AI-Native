"""
A6: Architect Agent - DAG Builder Integration

Combines DependencyAnalyzer and DAGBuilder to produce task dependency graphs
from requirements, API schemas, and ERD documents.

Flow:
  1. Receive requirement + API schema + ERD from context
  2. Run DependencyAnalyzer to extract tasks and dependencies
  3. Run DAGBuilder to construct DAG and identify parallelizable tasks
  4. Detect circular dependencies and report issues
  5. Compute critical path and effort estimates
  6. Store DAG to PostgreSQL (task_dags table)
  7. Publish dag.built event to NATS for Orchestrator consumption
  8. Return structured DAG to caller

Triggered by:
  - A5 design review completion
  - Explicit orchestration request
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False

from a6.dependency_analyzer import DependencyAnalyzer
from a6.dag_builder import DAGBuilder
from a6.complexity_estimator import ComplexityEstimator
from k14.dependency_topology import DependencyTopology

logger = logging.getLogger(__name__)

AGENT_ID = "A6"
AGENT_TYPE = "architect"

# Neo4j configuration
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://172.27.78.109:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "ai-native-2026")


class A6Architect:
    """A6 Architect agent: builds task DAGs from requirements and schemas."""

    def __init__(self, db_pool: Optional[Any] = None, nats_client: Optional[Any] = None):
        """Initialize the architect.

        Args:
            db_pool: asyncpg connection pool for PostgreSQL
            nats_client: NATS client for event publishing
        """
        self.db_pool = db_pool
        self.nats_client = nats_client

        self.analyzer = DependencyAnalyzer()
        self.dag_builder = DAGBuilder(max_parallel_agents=5, max_dag_depth=4)
        self.complexity_estimator = ComplexityEstimator()

        # Initialize K14 Dependency Topology (Neo4j integration)
        try:
            self.topology = DependencyTopology(
                uri=NEO4J_URI,
                user=NEO4J_USER,
                password=NEO4J_PASSWORD
            )
            logger.info("[A6] K14 DependencyTopology initialized successfully")
        except Exception as e:
            logger.warning(f"[A6] Failed to initialize K14: {str(e)}")
            self.topology = None

        logger.info("A6 Architect initialized")

    async def execute(
        self,
        req_id: str,
        requirement: dict,
        api_schema: dict,
        erd: dict,
        context: Optional[dict] = None
    ) -> dict:
        """Execute DAG building process.

        Args:
            req_id: Requirement ID (UUID string)
            requirement: Requirement object with title, description, has_ui, etc.
            api_schema: OpenAPI/Swagger schema with paths and components
            erd: Entity-Relationship Diagram with entities and relationships
            context: Optional additional context

        Returns:
            Dict with:
                - status: "completed" or "error"
                - dag: Full DAG structure
                - summary: Statistics and insights
                - error: If status is "error"
        """
        logger.info(
            "[A6] Starting DAG build for req_id=%s",
            req_id
        )

        try:
            # Phase 1: Analyze requirement, API schema, and ERD
            logger.info("[A6] Phase 1: Dependency analysis")
            analysis_result = self.analyzer.analyze(
                requirement=requirement,
                api_schema=api_schema,
                erd=erd,
                context=context
            )

            analyzed_tasks = analysis_result.get("tasks", [])
            shared_modules = analysis_result.get("shared_modules", [])
            analysis_summary = analysis_result.get("analysis_summary", {})

            logger.info(
                "[A6] Analysis complete: %d tasks, %d shared modules",
                len(analyzed_tasks),
                len(shared_modules)
            )

            # Phase 2: Enhance with complexity estimation
            logger.info("[A6] Phase 2: Complexity estimation")
            enhanced_tasks = self.complexity_estimator.estimate_all(analyzed_tasks)

            logger.info(
                "[A6] Complexity estimation complete: avg complexity %.1f",
                sum(t.get("complexity", 0) for t in enhanced_tasks) / max(1, len(enhanced_tasks))
            )

            # Phase 3: Build DAG structure
            logger.info("[A6] Phase 3: DAG construction")
            dag_result = self.dag_builder.build(
                spec={"entities": erd.get("entities", [])},
                analyzed_tasks=enhanced_tasks
            )

            logger.info(
                "[A6] DAG built: %d tasks, %d parallel groups, "
                "critical_path=%d tasks (%.1f h), has_cycles=%s",
                dag_result["total_tasks"],
                len(dag_result["parallel_groups"]),
                len(dag_result["critical_path"]),
                dag_result["critical_path_hours"],
                dag_result["has_cycles"]
            )

            # Phase 3.5: Build Neo4j dependency topology (K14 integration)
            if self.topology:
                logger.info("[A6] Phase 3.5: Building Neo4j topology (K14)")
                topology_result = await self.topology.build_topology(
                    req_id=req_id,
                    api_schema=api_schema,
                    erd=erd,
                    requirement_context={
                        "title": requirement.get("title", f"Requirement {req_id}"),
                        "description": requirement.get("description", ""),
                        "complexity": requirement.get("complexity", "medium"),
                        "status": "active",
                    }
                )
                logger.info(
                    "[A6] Neo4j topology built: %s (nodes=%d, edges=%d)",
                    topology_result.get("status"),
                    topology_result.get("nodes_created", 0),
                    topology_result.get("edges_created", 0)
                )
                if topology_result.get("status") != "completed":
                    logger.warning(f"[A6] Neo4j topology build incomplete: {topology_result.get('error')}")

            # Phase 4: Detect and report issues
            if dag_result["has_cycles"]:
                logger.error(
                    "[A6] Circular dependencies detected: %s",
                    dag_result["cycle_nodes"]
                )
                return {
                    "status": "error",
                    "error": "Circular dependencies detected",
                    "cycle_nodes": dag_result["cycle_nodes"],
                    "dag": dag_result,
                }

            # Phase 5: Store to database
            logger.info("[A6] Phase 4: Storing DAG to database")
            dag_id = await self._store_dag(
                req_id=req_id,
                dag=dag_result,
                shared_modules=shared_modules,
                analysis_summary=analysis_summary
            )
            logger.info("[A6] DAG stored with id=%d", dag_id)

            # Phase 6: Publish event
            logger.info("[A6] Phase 5: Publishing dag.built event")
            await self._publish_event(
                req_id=req_id,
                dag=dag_result,
                dag_id=dag_id,
                shared_modules=shared_modules
            )

            # Phase 7: Return result
            result = {
                "status": "completed",
                "req_id": req_id,
                "dag_id": dag_id,
                "dag": dag_result,
                "shared_modules": shared_modules,
                "analysis_summary": analysis_summary,
                "summary": {
                    "total_tasks": dag_result["total_tasks"],
                    "total_estimated_hours": dag_result["total_estimated_hours"],
                    "critical_path_length": len(dag_result["critical_path"]),
                    "critical_path_hours": dag_result["critical_path_hours"],
                    "parallel_groups": len(dag_result["parallel_groups"]),
                    "has_cycles": dag_result["has_cycles"],
                }
            }

            logger.info(
                "[A6] DAG build completed successfully for req_id=%s",
                req_id
            )
            return result

        except Exception as e:
            logger.error(
                "[A6] DAG build failed for req_id=%s: %s",
                req_id,
                str(e),
                exc_info=True
            )
            return {
                "status": "error",
                "req_id": req_id,
                "error": str(e),
            }
        finally:
            # Clean up Neo4j connection if needed
            if self.topology:
                try:
                    await self.topology.close()
                except Exception as e:
                    logger.warning(f"[A6] Error closing Neo4j connection: {str(e)}")

    async def _store_dag(
        self,
        req_id: str,
        dag: dict,
        shared_modules: list,
        analysis_summary: dict
    ) -> int:
        """Store DAG to PostgreSQL.

        Args:
            req_id: Requirement ID
            dag: DAG structure from DAGBuilder
            shared_modules: Shared modules from DependencyAnalyzer
            analysis_summary: Analysis summary

        Returns:
            dag_id (int) from database
        """
        if not self.db_pool:
            logger.warning("[A6] No database pool available, skipping storage")
            return -1

        if not ASYNCPG_AVAILABLE:
            logger.warning("[A6] asyncpg not available, skipping storage")
            return -1

        try:
            async with self.db_pool.acquire() as conn:
                # Insert task_dags record
                query = """
                    INSERT INTO task_dags (
                        req_id, tasks, edges, dag_json, critical_path,
                        critical_path_hours, parallelizable, total_estimated_hours,
                        analysis_source, has_cycles, cycle_nodes
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                """
                dag_id = await conn.fetchval(
                    query,
                    req_id,
                    json.dumps(dag.get("tasks", []), default=str),
                    json.dumps(dag.get("edges", []), default=str),
                    json.dumps(dag, default=str),
                    json.dumps(dag.get("critical_path", []), default=str),
                    dag.get("critical_path_hours", 0.0),
                    json.dumps(dag.get("parallel_groups", []), default=str),
                    dag.get("total_estimated_hours", 0.0),
                    "analyzer",  # analysis_source
                    dag.get("has_cycles", False),
                    json.dumps(dag.get("cycle_nodes", []), default=str) if dag.get("cycle_nodes") else None,
                )

                logger.info("[A6] Stored DAG record: dag_id=%d", dag_id)

                # Insert shared_modules records
                for module in shared_modules:
                    module_query = """
                        INSERT INTO shared_modules (
                            req_id, module_name, module_type, description,
                            used_by_tasks, priority
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                    """
                    await conn.execute(
                        module_query,
                        req_id,
                        module.get("name", "unknown"),
                        module.get("type", "utility"),
                        module.get("description", ""),
                        json.dumps(module.get("used_by", []), default=str),
                        module.get("priority", 2),
                    )

                logger.info("[A6] Stored %d shared modules", len(shared_modules))

            return dag_id

        except Exception as e:
            logger.error("[A6] Database storage failed: %s", str(e))
            raise

    async def _publish_event(
        self,
        req_id: str,
        dag: dict,
        dag_id: int,
        shared_modules: list
    ) -> None:
        """Publish dag.built event to NATS.

        Args:
            req_id: Requirement ID
            dag: DAG structure
            dag_id: Database ID of stored DAG
            shared_modules: Shared modules
        """
        if not self.nats_client:
            logger.warning("[A6] No NATS client available, skipping event publication")
            return

        try:
            event = {
                "event_id": f"dag-built-{req_id}",
                "event_type": "dag.built",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "req_id": req_id,
                "dag_id": dag_id,
                "agent_id": AGENT_ID,
                "payload": {
                    "dag": dag,
                    "shared_modules": shared_modules,
                    "total_tasks": dag.get("total_tasks", 0),
                    "total_estimated_hours": dag.get("total_estimated_hours", 0),
                    "critical_path_hours": dag.get("critical_path_hours", 0),
                }
            }

            # Publish to NATS
            subject = "architecture.dag_built"
            message = json.dumps(event, default=str).encode()
            await self.nats_client.publish(subject, message)

            logger.info(
                "[A6] Published event to %s for req_id=%s, dag_id=%d",
                subject,
                req_id,
                dag_id
            )

        except Exception as e:
            logger.error("[A6] Event publication failed: %s", str(e))
            # Don't raise - publication failure shouldn't block DAG creation


# Standalone convenience function for testing
async def build_dag(
    req_id: str,
    requirement: dict,
    api_schema: dict,
    erd: dict,
    db_pool: Optional[Any] = None,
    nats_client: Optional[Any] = None
) -> dict:
    """Convenience function to build a DAG."""
    architect = A6Architect(db_pool=db_pool, nats_client=nats_client)
    return await architect.execute(
        req_id=req_id,
        requirement=requirement,
        api_schema=api_schema,
        erd=erd
    )
