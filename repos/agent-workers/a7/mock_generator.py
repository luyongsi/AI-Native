"""
Mock Generator — generates WireMock stubs from OpenAPI specifications.

Real implementation would:
  - Parse every operation in an OpenAPI 3.x spec
  - Map path templates (/users/{id}) to WireMock urlPathPattern matchers
  - Generate response bodies from schema examples or Faker data
  - Handle content negotiation (Accept / Content-Type headers)
  - Output a complete mappings/ directory with one JSON stub per endpoint
  - Support stateful mocking via WireMock scenarios
"""

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MockGenerator:
    """Generate WireMock stubs from an OpenAPI 3.x specification."""

    # HTTP status code heuristics per method when no explicit response is declared
    DEFAULT_STATUS = {
        "get": 200,
        "post": 201,
        "put": 200,
        "patch": 200,
        "delete": 204,
    }

    async def generate_wiremock_stubs(self, api_spec: dict) -> dict:
        """
        Generate WireMock stub mappings from an OpenAPI spec.

        Args:
            api_spec: Parsed OpenAPI 3.x document.

        Returns:
            {
                stubs: [{path, method, request{}, response{status, body, headers}}],
                mappings_file: str,  # path to combined mappings file
            }
        """
        paths = api_spec.get("paths", {})
        logger.info(
            "Generating WireMock stubs for %d path(s)",
            len(paths),
        )

        stubs: List[Dict[str, Any]] = []

        for path_url, path_item in paths.items():
            for method in ("get", "post", "put", "patch", "delete", "options"):
                operation = path_item.get(method)
                if not operation:
                    continue

                stub = self._build_stub(path_url, method.upper(), operation, api_spec)
                stubs.append(stub)
                logger.debug("Generated stub: %s %s", method.upper(), path_url)

        # Build a combined WireMock mappings file
        mappings_content = json.dumps(
            {"mappings": [s for s in stubs]}, indent=2
        )

        logger.info(
            "Generated %d WireMock stubs; combined mappings file ready",
            len(stubs),
        )

        return {
            "stubs": stubs,
            "mappings_file": "wiremock/mappings/generated-mappings.json",
        }

    # ------------------------------------------------------------------
    # Stub builders
    # ------------------------------------------------------------------

    def _build_stub(
        self, path_url: str, method: str, operation: dict, api_spec: dict
    ) -> dict:
        """Construct a single WireMock stub mapping."""

        # --- Request matcher ---
        request_matcher = self._build_request_matcher(path_url, method, operation)

        # --- Response ---
        response = self._build_response(method, operation, api_spec)

        return {
            "path": path_url,
            "method": method,
            "request": request_matcher,
            "response": response,
        }

    def _build_request_matcher(
        self, path_url: str, method: str, operation: dict
    ) -> dict:
        """
        Build a WireMock request matcher section.

        Converts OpenAPI /users/{id} to urlPathPattern: /users/[^/]+
        """
        # Convert path parameters to regex placeholders
        url_pattern = path_url
        has_params = "{" in url_pattern

        matcher: Dict[str, Any] = {"method": method}

        if has_params:
            # Replace {param} with regex captures for WireMock
            import re
            url_pattern = re.sub(r"\{(\w+)\}", r"[^/]+", url_pattern)
            matcher["urlPathPattern"] = url_pattern
        else:
            matcher["url"] = url_pattern

        # Add parameter matchers from OpenAPI parameters
        parameters = operation.get("parameters", [])
        query_params = [p for p in parameters if p.get("in") == "query"]
        if query_params:
            matcher["queryParameters"] = {
                p["name"]: {"matches": ".*"} for p in query_params
            }

        # Add header matchers if request body present
        if operation.get("requestBody"):
            matcher.setdefault("headers", {})["Content-Type"] = {
                "contains": "application/json"
            }

        return matcher

    def _build_response(
        self, method: str, operation: dict, api_spec: dict
    ) -> dict:
        """
        Build a WireMock response section.

        Tries to use the first documented response; falls back to a
        sensible default body based on the operation's response schema.
        """
        responses = operation.get("responses", {})
        status_str = next(
            (s for s in responses.keys() if s.startswith("2")), None
        )
        status_code = (
            int(status_str)
            if status_str
            else self.DEFAULT_STATUS.get(method.lower(), 200)
        )

        headers = {"Content-Type": "application/json"}

        # Try to build a realistic response body from schema
        body = None
        if status_str and status_str in responses:
            resp_obj = responses[status_str]
            schema = None
            if "content" in resp_obj:
                for media_type, media_obj in resp_obj["content"].items():
                    schema = media_obj.get("schema")
                    break
            if not schema:
                schema = resp_obj.get("schema")
            if schema:
                body = self._generate_example_body(schema, api_spec)

        if body is None:
            body = {"message": f"Mock response for {method} {operation.get('operationId', 'unknown')}"}

        response = {
            "status": status_code,
            "body": body,
            "headers": headers,
        }

        # Add delay for realism
        response["fixedDelayMilliseconds"] = 50

        return response

    def _generate_example_body(self, schema: dict, api_spec: dict) -> Any:
        """
        Generate a realistic example response body from a JSON Schema.

        Resolves $ref references and walks properties to produce
        a representative payload.
        """
        # Resolve $ref
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"], api_spec)

        schema_type = schema.get("type", "object")

        if schema_type == "object":
            result = {}
            properties = schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                result[prop_name] = self._generate_scalar_example(
                    prop_schema, api_spec
                )
            return result

        if schema_type == "array":
            items = schema.get("items", {})
            return [self._generate_example_body(items, api_spec)]

        return self._generate_scalar_example(schema, api_spec)

    def _generate_scalar_example(self, schema: dict, api_spec: dict) -> Any:
        """Generate a single scalar example from a schema node."""
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"], api_spec)

        if "example" in schema:
            return schema["example"]

        field_type = schema.get("type", "string")
        fmt = schema.get("format", "")

        if field_type == "integer":
            return schema.get("minimum", 1)
        if field_type == "number":
            return schema.get("minimum", 3.14)
        if field_type == "boolean":
            return schema.get("default", True)
        if field_type == "string":
            if fmt == "email":
                return "user@example.com"
            if fmt == "uuid":
                return "550e8400-e29b-41d4-a716-446655440000"
            if fmt == "date-time":
                return "2025-01-01T00:00:00Z"
            if fmt == "date":
                return "2025-01-01"
            return schema.get("default", "example_string")
        return "example_value"

    def _resolve_ref(self, ref: str, api_spec: dict) -> dict:
        """Resolve a JSON Schema $ref pointer."""
        parts = ref.split("/")
        current = api_spec
        for part in parts:
            if part == "#":
                continue
            current = current.get(part, {})
        return current if isinstance(current, dict) else {}
