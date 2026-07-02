"""
Dependency Analyzer — analyzes an ERD + API spec to determine required Docker services.

Real implementation would:
  - Parse ERD entities to detect database engines (PostgreSQL, MySQL, MongoDB)
  - Inspect API spec for external service references (Redis cache keys, NATS subjects)
  - Cross-reference with a service catalog for version pinning
  - Detect circular dependencies and suggest resolution order
  - Optimize port assignments to avoid conflicts with host services
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class DependencyAnalyzer:
    """Analyze project artifacts to determine the Docker services needed for a test environment."""

    # Known service presets with sensible defaults
    SERVICE_PRESETS: Dict[str, dict] = {
        "postgresql": {
            "type": "postgres",
            "default_version": "16-alpine",
            "default_port": 5432,
            "env_vars": {
                "POSTGRES_USER": "test_user",
                "POSTGRES_PASSWORD": "test_pass",
                "POSTGRES_DB": "test_db",
            },
        },
        "mysql": {
            "type": "mysql",
            "default_version": "8.0",
            "default_port": 3306,
            "env_vars": {
                "MYSQL_ROOT_PASSWORD": "root_pass",
                "MYSQL_DATABASE": "test_db",
                "MYSQL_USER": "test_user",
                "MYSQL_PASSWORD": "test_pass",
            },
        },
        "redis": {
            "type": "redis",
            "default_version": "7-alpine",
            "default_port": 6379,
            "env_vars": {},
        },
        "nats": {
            "type": "nats",
            "default_version": "2.10-alpine",
            "default_port": 4222,
            "env_vars": {},
        },
        "wiremock": {
            "type": "wiremock",
            "default_version": "3.5.4",
            "default_port": 8080,
            "env_vars": {},
        },
        "postgres": {
            "type": "postgres",
            "default_version": "16-alpine",
            "default_port": 5432,
            "env_vars": {
                "POSTGRES_USER": "test_user",
                "POSTGRES_PASSWORD": "test_pass",
                "POSTGRES_DB": "test_db",
            },
        },
    }

    def analyze(self, erd: dict, api_spec: dict) -> dict:
        """
        Analyze an ERD and API spec to produce a Docker service dependency map.

        Args:
            erd: Entity-Relationship Diagram as a dict. Expected keys:
                 entities[{name, fields[{name, type, pk, fk, nullable}]}]
            api_spec: OpenAPI 3.x spec dict.

        Returns:
            {
                services: [{name, type, version, port, env_vars{}}],
                volumes: [],
                networks: [],
            }
        """
        logger.info(
            "Analyzing dependencies — %d ERD entities, %d API paths",
            len(erd.get("entities", [])),
            len(api_spec.get("paths", {})),
        )

        services: List[Dict[str, Any]] = []
        volumes: List[Dict[str, str]] = []
        networks: List[Dict[str, str]] = []

        detected_types: set = set()

        # --- Analyse ERD for database services ---
        entities = erd.get("entities", [])
        for entity in entities:
            db_type = self._detect_db_type(entity)
            if db_type and db_type not in detected_types:
                detected_types.add(db_type)
                svc = self._build_service(db_type)
                services.append(svc)
                volumes.append({
                    "name": f"{db_type}_data",
                    "driver": "local",
                })

        # --- Analyse API spec for middleware / external services ---
        paths = api_spec.get("paths", {})
        all_operation_ids = []
        all_descriptions = []
        for path_item in paths.values():
            for method in ("get", "post", "put", "patch", "delete"):
                op = path_item.get(method)
                if op:
                    all_operation_ids.append(op.get("operationId", ""))
                    all_descriptions.append(op.get("description", op.get("summary", "")))

        combined_text = " ".join(all_operation_ids + all_descriptions).lower()

        # Detect Redis usage from operation naming conventions
        if any(kw in combined_text for kw in ("cache", "redis", "session", "rate_limit", "queue")):
            if "redis" not in detected_types:
                detected_types.add("redis")
                services.append(self._build_service("redis"))

        # Detect NATS / messaging
        if any(kw in combined_text for kw in ("nats", "publish", "subscribe", "queue", "event", "message")):
            if "nats" not in detected_types:
                detected_types.add("nats")
                services.append(self._build_service("nats"))

        # Detect external API dependencies -> WireMock
        if any(kw in combined_text for kw in ("external", "webhook", "third_party", "payment", "notification", "sms")):
            if "wiremock" not in detected_types:
                detected_types.add("wiremock")
                svc = self._build_service("wiremock")
                svc["env_vars"]["WIREMOCK_MAPPINGS"] = "/home/wiremock/mappings"
                svc["volumes"] = ["./wiremock/mappings:/home/wiremock/mappings"]
                services.append(svc)

        # --- Build networks ---
        networks.append({
            "name": "test-network",
            "driver": "bridge",
        })

        logger.info(
            "Dependency analysis complete: %d services, %d volumes, %d networks",
            len(services),
            len(volumes),
            len(networks),
        )

        return {
            "services": services,
            "volumes": volumes,
            "networks": networks,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_db_type(self, entity: dict) -> str | None:
        """
        Detect the database engine from an ERD entity.

        Heuristics:
          - entity-level "db_type" / "engine" field
          - field type conventions (SERIAL -> PostgreSQL, AUTO_INCREMENT -> MySQL)
          - entity name conventions
        """
        # Explicit field on entity
        if "db_type" in entity:
            return entity["db_type"].lower()
        if "engine" in entity:
            return entity["engine"].lower()

        # Inspect field types
        fields = entity.get("fields", entity.get("columns", []))
        field_types = " ".join(
            f.get("type", "") for f in fields
        ).lower()

        if "serial" in field_types or "uuid" in field_types or "jsonb" in field_types:
            return "postgres"
        if "auto_increment" in field_types or "mediumtext" in field_types:
            return "mysql"

        # Default assumption for typical ERDs
        name = entity.get("name", "").lower()
        if "mongo" in name or "collection" in name:
            return "mongodb"

        return "postgres"  # safe default

    def _build_service(self, svc_type: str) -> dict:
        """Build a service definition from the preset catalog."""
        preset = self.SERVICE_PRESETS.get(svc_type)
        if not preset:
            logger.warning("Unknown service type '%s' — using custom defaults", svc_type)
            return {
                "name": svc_type,
                "type": "custom",
                "version": "latest",
                "port": 9000,
                "env_vars": {},
            }

        return {
            "name": svc_type,
            "type": preset["type"],
            "version": preset["default_version"],
            "port": preset["default_port"],
            "env_vars": dict(preset["env_vars"]),
        }
