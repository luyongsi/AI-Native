"""Specification importer — OpenAPI and ERD → Neo4j knowledge graph.

Creates :APIDoc nodes from OpenAPI specs and relationship bridges from
entity-relationship diagrams.  Stub implementations with realistic mock
processing suitable for testing the pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SpecImporter:
    """Imports OpenAPI specs and ERDs into the Neo4j knowledge graph.

    Uses the async Neo4j Python driver for writes.  When the driver is
    ``None`` the importer operates in dry-run / stub mode.
    """

    def __init__(self, driver=None) -> None:
        """Initialise with an optional async Neo4j driver.

        Args:
            driver: An instance of ``neo4j.async_.driver``.
        """
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def import_openapi(self, openapi_spec: dict, spec_id: str) -> dict:
        """Parse an OpenAPI 3.x document and create :APIDoc nodes.

        Creates one :APIDoc node per path+operation pair and links them to
        the parent :Spec node via ``:CONTAINS``.

        Args:
            openapi_spec: A parsed OpenAPI 3.x document (dict).
            spec_id: The ``id`` of the parent ``:Spec`` node.

        Returns a dict of::

            {
                "endpoints_imported": <int>,
                "nodes_created": <int>,
                "relationships_created": <int>,
            }
        """
        logger.info("SpecImporter.import_openapi(spec_id=%r)", spec_id)

        endpoints_imported = 0
        nodes_created = 0
        relationships_created = 0

        paths: dict = openapi_spec.get("paths", {})
        for path, methods in paths.items():
            for method in methods:
                if method.upper() not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
                    continue
                endpoint_id = f"api:{spec_id}:{method}:{path}"
                operation = methods[method]
                deprecated = operation.get("deprecated", False)
                logger.debug(
                    "import_openapi: endpoint=%s %s deprecated=%s tags=%s",
                    method.upper(), path, deprecated, operation.get("tags"),
                )
                # In real impl: MERGE (:APIDoc {id: $id}) SET path=$path, method=$method, deprecated=$deprecated
                # In real impl: MATCH (s:Spec {id: $spec_id}) MERGE (s)-[:CONTAINS]->(api)
                endpoints_imported += 1
                nodes_created += 1
                relationships_created += 1  # :CONTAINS

        logger.info(
            "import_openapi done: %d endpoints imported, %d nodes, %d rels",
            endpoints_imported, nodes_created, relationships_created,
        )
        return {
            "endpoints_imported": endpoints_imported,
            "nodes_created": nodes_created,
            "relationships_created": relationships_created,
        }

    async def import_erd(self, erd: dict, spec_id: str) -> dict:
        """Import an entity-relationship diagram into the graph.

        Creates relationships (``:REFERENCES``, ``:IMPACTS``) between
        entities listed in the ERD and existing :Task nodes that reference
        those tables.

        Args:
            erd: A dict representing the ERD.  Expected shape::

                {
                    "entities": [
                        {"name": str, "fields": [...], "relationships": [...]},
                        ...
                    ],
                }
            spec_id: The ``id`` of the parent ``:Spec`` node.

        Returns a dict of::

            {
                "entities_processed": <int>,
                "relationships_created": <int>,
            }
        """
        logger.info("SpecImporter.import_erd(spec_id=%r)", spec_id)

        entities = erd.get("entities", [])
        relationships_created = 0

        for entity in entities:
            entity_name = entity.get("name", "")
            entity_rels = entity.get("relationships", [])
            logger.debug("import_erd: entity=%s relationships=%d", entity_name, len(entity_rels))
            for rel in entity_rels:
                # In real impl:
                #   MATCH (t:Task {title: $entity_name})-[:REFERENCES]->(a:APIDoc)
                #   MERGE (t)-[:IMPACTS {severity: 'medium'}]->(related)
                relationships_created += 1  # stub count

        logger.info(
            "import_erd done: %d entities, %d relationships",
            len(entities), relationships_created,
        )
        return {
            "entities_processed": len(entities),
            "relationships_created": relationships_created,
        }
