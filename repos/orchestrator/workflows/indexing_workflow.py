"""Temporal Workflow: IndexingWorkflow

Periodically scans for new requirements/code changes and indexes them as embeddings.
Runs as a scheduled workflow to keep knowledge_embeddings table up to date.

Phases:
1. Scan new requirements (updated last hour)
2. Scan new code changes (git commits)
3. Generate embeddings via EmbeddingService
4. Store in knowledge_embeddings table
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.embedding_index import (
        scan_new_requirements,
        scan_code_changes,
        index_embeddings,
    )

logger = logging.getLogger(__name__)


class IndexingWorkflow:
    """Background workflow for semantic indexing."""

    @workflow.run
    async def run(self):
        """Execute indexing cycle."""
        logger.info("IndexingWorkflow started")

        try:
            # Scan for new requirements in last hour
            requirements = await workflow.execute_activity(
                scan_new_requirements,
                hours_back=1,
                retry_policy=RetryPolicy(max_attempts=3),
            )
            logger.info(f"Found {len(requirements)} new requirements to index")

            # Scan for code changes
            code_changes = await workflow.execute_activity(
                scan_code_changes,
                hours_back=1,
                retry_policy=RetryPolicy(max_attempts=3),
            )
            logger.info(f"Found {len(code_changes)} code changes to index")

            # Index all content
            indexed_count = await workflow.execute_activity(
                index_embeddings,
                requirements=requirements,
                code_changes=code_changes,
                retry_policy=RetryPolicy(max_attempts=3),
            )
            logger.info(f"Indexed {indexed_count} items successfully")

            return {
                "status": "success",
                "requirements_indexed": len(requirements),
                "code_changes_indexed": len(code_changes),
                "total_indexed": indexed_count,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"IndexingWorkflow failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }
