"""
A4 Sub-module: OpenAPI Generator

Generates a realistic OpenAPI 3.1 specification from requirement entities.
In production, this would use an LLM to draft endpoints, schemas, and examples
from structured requirement documents and knowledge-graph entities.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Real implementation pattern (comment):
#
# 1. Parse the requirement dict for functional stories, acceptance criteria,
#    and entity definitions extracted by A2 (Knowledge Analyst).
# 2. For each entity, infer RESTful CRUD paths + any custom action routes
#    mentioned in the requirement text (e.g. "batch import", "bulk delete").
# 3. Build JSON Schema components for request/response bodies using the
#    entity attribute map from the knowledge brief.
# 4. Optionally call an LLM (e.g. Claude via the Anthropic SDK) with a
#    structured prompt to fill in descriptions, examples, and error schemas.
# ---------------------------------------------------------------------------


class OpenAPIGenerator:
    """Generates OpenAPI 3.1 specs from requirements and entity lists."""

    # Default CRUD operations per entity
    _CRUD_OPS = [
        {"method": "get", "suffix": "", "summary_tpl": "List all {entity} records"},
        {"method": "post", "suffix": "", "summary_tpl": "Create a new {entity}"},
        {"method": "get", "suffix": "/{id}", "summary_tpl": "Get a single {entity} by ID"},
        {"method": "put", "suffix": "/{id}", "summary_tpl": "Update an existing {entity}"},
        {"method": "delete", "suffix": "/{id}", "summary_tpl": "Delete a {entity}"},
    ]

    # Default JSON Schema types for common attribute names
    _TYPE_HINTS: Dict[str, str] = {
        "id": "string",
        "name": "string",
        "title": "string",
        "description": "string",
        "email": "string",
        "status": "string",
        "type": "string",
        "url": "string",
        "created_at": "string",
        "updated_at": "string",
        "price": "number",
        "amount": "number",
        "total": "number",
        "quantity": "integer",
        "count": "integer",
        "age": "integer",
        "is_active": "boolean",
        "enabled": "boolean",
        "deleted": "boolean",
    }

    async def generate(
        self,
        requirement: dict,
        entities: list,
        *,
        title: Optional[str] = None,
        version: str = "0.1.0",
    ) -> dict:
        """Generate a mock OpenAPI 3.1 specification.

        Args:
            requirement: Requirement dict with title, description, domain.
            entities: List of entity dicts, each with at least a 'name' key
                      and optionally 'attributes' (list of {name, type}).

        Returns:
            An OpenAPI 3.1 spec dict with openapi, info, paths, and components.
        """
        api_title = title or f"{requirement.get('title', 'Generated')} API"
        api_description = requirement.get(
            "description",
            f"Auto-generated OpenAPI 3.1 specification for {api_title}.",
        )
        domain = requirement.get("domain", "general")

        entity_names = self._extract_entity_names(entities)
        entity_attrs = self._extract_entity_attributes(entities)

        logger.info(
            "Generating OpenAPI 3.1 spec for domain=%r, entities=%d",
            domain,
            len(entity_names),
        )

        paths = self._build_paths(entity_names, entity_attrs)
        schemas = self._build_schemas(entity_names, entity_attrs)

        spec: Dict[str, Any] = {
            "openapi": "3.1.0",
            "info": {
                "title": api_title,
                "version": version,
                "description": api_description,
                "contact": {
                    "name": requirement.get("author", "Platform Team"),
                },
            },
            "servers": [
                {
                    "url": f"https://api.{domain}.example.com/v1",
                    "description": f"{domain.title()} API v1",
                },
            ],
            "paths": paths,
            "components": {
                "schemas": schemas,
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                    },
                },
            },
            "security": [{"bearerAuth": []}],
            "tags": [{"name": en, "description": f"Operations for {en}"} for en in entity_names],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("OpenAPI 3.1 spec generated: %d paths, %d schemas", len(paths), len(schemas))
        return spec

    # ---- Internal helpers ----

    def _extract_entity_names(self, entities: list) -> List[str]:
        """Pull entity names from structured or flat entity list."""
        names: List[str] = []
        for ent in entities:
            if isinstance(ent, dict):
                name = ent.get("name") or ent.get("entity") or ent.get("table")
                if name:
                    names.append(str(name))
            elif isinstance(ent, str):
                names.append(ent)
        return names or ["items"]

    def _extract_entity_attributes(self, entities: list) -> Dict[str, List[Dict[str, str]]]:
        """Build a map of entity_name -> list of {name, type} attributes."""
        attrs: Dict[str, List[Dict[str, str]]] = {}
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            name = ent.get("name") or ent.get("entity") or ent.get("table")
            if not name:
                continue
            name = str(name)
            fields = ent.get("attributes") or ent.get("fields") or ent.get("columns") or []
            if fields:
                attrs[name] = [
                    {"name": str(f.get("name", f"field_{i}")),
                     "type": str(f.get("type", "string"))}
                    for i, f in enumerate(fields)
                ]
            else:
                # Generate sensible defaults
                attrs[name] = [
                    {"name": "id", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "status", "type": "string"},
                    {"name": "created_at", "type": "string"},
                    {"name": "updated_at", "type": "string"},
                ]
        return attrs

    def _build_paths(
        self,
        entity_names: List[str],
        entity_attrs: Dict[str, List[Dict[str, str]]],
    ) -> dict:
        """Build OpenAPI paths for each entity with standard CRUD operations."""
        paths: Dict[str, Any] = {}
        for entity in entity_names:
            base = self._entity_to_path(entity)
            for op in self._CRUD_OPS:
                path_key = f"{base}{op['suffix']}"
                method = op["method"]
                summary = op["summary_tpl"].format(entity=entity)

                operation: Dict[str, Any] = {
                    "tags": [entity],
                    "summary": summary,
                    "operationId": f"{method}{entity.title().replace('_', '')}{op['suffix'].replace('/{id}', 'ById').replace('{id}', 'ById')}",
                }

                # Path parameters for single-resource routes
                if "{id}" in op["suffix"]:
                    operation["parameters"] = [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": f"The {entity} ID",
                        },
                    ]

                # Request body for mutation methods
                if method in ("post", "put"):
                    schema_ref = f"#/components/schemas/{entity.title().replace('_', '')}"
                    if method == "post":
                        schema_ref = f"#/components/schemas/{entity.title().replace('_', '')}Create"
                    operation["requestBody"] = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": schema_ref},
                            },
                        },
                    }

                # Responses
                if method == "get" and "{id}" not in op["suffix"]:
                    # List endpoint
                    operation["responses"] = {
                        "200": {
                            "description": f"Paginated list of {entity}",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "type": "array",
                                                "items": {
                                                    "$ref": f"#/components/schemas/{entity.title().replace('_', '')}",
                                                },
                                            },
                                            "total": {"type": "integer"},
                                            "page": {"type": "integer"},
                                            "page_size": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                    }
                elif method == "get":
                    operation["responses"] = {
                        "200": {
                            "description": f"{entity} details",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": f"#/components/schemas/{entity.title().replace('_', '')}",
                                    },
                                },
                            },
                        },
                        "404": {"description": f"{entity} not found"},
                    }
                elif method == "post":
                    operation["responses"] = {
                        "201": {
                            "description": f"{entity} created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": f"#/components/schemas/{entity.title().replace('_', '')}",
                                    },
                                },
                            },
                        },
                        "400": {"description": "Invalid input"},
                    }
                elif method == "put":
                    operation["responses"] = {
                        "200": {
                            "description": f"{entity} updated",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": f"#/components/schemas/{entity.title().replace('_', '')}",
                                    },
                                },
                            },
                        },
                    }
                elif method == "delete":
                    operation["responses"] = {
                        "204": {"description": f"{entity} deleted"},
                        "404": {"description": f"{entity} not found"},
                    }

                paths.setdefault(path_key, {})[method] = operation

        # Add health-check endpoint
        paths["/health"] = {
            "get": {
                "tags": ["system"],
                "summary": "Health check",
                "operationId": "healthCheck",
                "responses": {
                    "200": {
                        "description": "Service is healthy",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "example": "ok"},
                                        "version": {"type": "string", "example": "0.1.0"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }

        return paths

    def _build_schemas(
        self,
        entity_names: List[str],
        entity_attrs: Dict[str, List[Dict[str, str]]],
    ) -> dict:
        """Build JSON Schema components for each entity (read + create variants)."""
        schemas: Dict[str, Any] = {}
        for entity in entity_names:
            pascal = entity.title().replace("_", "")
            fields = entity_attrs.get(entity, [
                {"name": "id", "type": "string"},
                {"name": "name", "type": "string"},
            ])

            props: Dict[str, Any] = {}
            required: List[str] = []
            for f in fields:
                fname = f["name"]
                ftype = f.get("type", "string")
                schema_type = self._TYPE_HINTS.get(fname, ftype) if ftype == "string" else ftype
                if schema_type == "string":
                    props[fname] = {"type": "string",
                                    "example": f"example-{fname}-{entity}"}
                elif schema_type == "integer":
                    props[fname] = {"type": "integer", "example": 1}
                elif schema_type == "number":
                    props[fname] = {"type": "number", "format": "float", "example": 99.99}
                elif schema_type == "boolean":
                    props[fname] = {"type": "boolean", "example": True}
                else:
                    props[fname] = {"type": schema_type}

                if fname == "id":
                    props[fname]["format"] = "uuid"
                    props[fname]["example"] = "550e8400-e29b-41d4-a716-446655440000"
                    required.append(fname)
                elif fname == "created_at":
                    props[fname]["format"] = "date-time"
                elif fname == "updated_at":
                    props[fname]["format"] = "date-time"

            schemas[pascal] = {
                "type": "object",
                "required": required,
                "properties": props,
                "description": f"{entity.title().replace('_', ' ')} resource",
            }

            # Create variant (no id, different required fields)
            create_props = {k: v for k, v in props.items() if k not in ("id", "created_at", "updated_at")}
            create_required = [r for r in required if r != "id"]
            schemas[f"{pascal}Create"] = {
                "type": "object",
                "required": create_required,
                "properties": create_props,
                "description": f"Payload for creating a new {entity}",
            }

        # Pagination helper schema
        schemas["Pagination"] = {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "default": 1, "minimum": 1},
                "page_size": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
        }

        # Error schema
        schemas["Error"] = {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"type": "string", "example": "VALIDATION_ERROR"},
                "message": {"type": "string", "example": "The request was invalid."},
                "details": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "message": {"type": "string"},
                        },
                    },
                },
            },
        }

        return schemas

    @staticmethod
    def _entity_to_path(entity_name: str) -> str:
        """Convert entity name to a RESTful path segment.

        Examples: 'order_items' -> '/order-items', 'users' -> '/users'
        """
        return "/" + entity_name.replace("_", "-").lower()
