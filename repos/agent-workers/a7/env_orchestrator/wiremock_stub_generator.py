"""
WireMock Stub Generator — generates WireMock stub mappings per endpoint.

Real implementation would:
  - Accept a list of endpoint descriptors (method, path, expected request/response)
  - Generate urlPathPattern matchers for parameterized paths
  - Support priority-based stub ordering (more specific matches first)
  - Generate response templating for dynamic responses (dates, UUIDs)
  - Support fault simulation stubs (delays, timeouts, 5xx errors)
  - Write individual JSON files to wiremock/mappings/
"""

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class WiremockStubGenerator:
    """Generate WireMock stub definitions for a list of API endpoints."""

    # Response templates for common status codes
    STATUS_BODIES: Dict[int, Any] = {
        200: {"status": "ok", "data": {}},
        201: {"status": "created", "id": "generated-id"},
        204: None,
        400: {"error": "Bad Request", "message": "Invalid input"},
        401: {"error": "Unauthorized", "message": "Missing or invalid token"},
        403: {"error": "Forbidden", "message": "Insufficient permissions"},
        404: {"error": "Not Found", "message": "Resource does not exist"},
        409: {"error": "Conflict", "message": "Resource already exists"},
        422: {"error": "Unprocessable Entity", "message": "Validation failed"},
        500: {"error": "Internal Server Error", "message": "Unexpected server error"},
        503: {"error": "Service Unavailable", "message": "Temporarily overloaded"},
    }

    def generate_for_endpoints(
        self, endpoints: list, base_url: str
    ) -> dict:
        """
        Generate WireMock stubs for a list of endpoint descriptors.

        Args:
            endpoints: List of endpoint dicts, each with:
                       {method, path, request_body_schema(optional), expected_status(optional)}
            base_url: Base URL of the service being mocked (for documentation).

        Returns:
            {
                stubs: [{request{match}, response{status, body}}],
                mappings_count: int,
            }
        """
        logger.info(
            "Generating WireMock stubs for %d endpoints (base: %s)",
            len(endpoints),
            base_url,
        )

        stubs: List[Dict[str, Any]] = []

        for ep in endpoints:
            method = ep.get("method", "GET").upper()
            path = ep.get("path", "/")
            expected_status = ep.get("expected_status", self._default_status(method))
            request_body_schema = ep.get("request_body_schema")
            response_body_override = ep.get("response_body")
            delay_ms = ep.get("delay_ms", 0)
            priority = ep.get("priority", 5)

            stub = self._build_stub(
                method=method,
                path=path,
                expected_status=expected_status,
                request_body_schema=request_body_schema,
                response_body_override=response_body_override,
                delay_ms=delay_ms,
                priority=priority,
            )
            stubs.append(stub)
            logger.debug("Stub: %s %s -> %d", method, path, expected_status)

        logger.info("Generated %d WireMock stub(s)", len(stubs))

        return {
            "stubs": stubs,
            "mappings_count": len(stubs),
        }

    # ------------------------------------------------------------------
    # Stub builders
    # ------------------------------------------------------------------

    def _build_stub(
        self,
        method: str,
        path: str,
        expected_status: int,
        request_body_schema: dict | None,
        response_body_override: Any,
        delay_ms: int,
        priority: int,
    ) -> dict:
        """Build a complete WireMock stub mapping."""

        # --- Request matcher ---
        request_matcher = self._build_request_matcher(
            method, path, request_body_schema
        )

        # --- Response ---
        response = self._build_response(
            expected_status,
            response_body_override,
            delay_ms,
        )

        stub = {
            "request": request_matcher,
            "response": response,
        }

        if priority != 5:
            stub["priority"] = priority

        return stub

    def _build_request_matcher(
        self,
        method: str,
        path: str,
        request_body_schema: dict | None,
    ) -> dict:
        """
        Build the WireMock request matching section.

        Static paths use `url`; parameterized paths use `urlPathPattern`.
        """
        matcher: Dict[str, Any] = {
            "method": method,
        }

        if "{" in path:
            # Parameterized path — convert to WireMock regex
            url_pattern = re.sub(r"\{(\w+)\}", r"[^/]+", path)
            matcher["urlPathPattern"] = url_pattern
        else:
            matcher["url"] = path

        # Headers
        if method in ("POST", "PUT", "PATCH"):
            matcher.setdefault("headers", {})["Content-Type"] = {
                "equalTo": "application/json"
            }

        # Body matcher from schema
        if request_body_schema and method in ("POST", "PUT", "PATCH"):
            matcher["bodyPatterns"] = [
                {"matchesJsonPath": "$"}  # at minimum, valid JSON
            ]
            # If the schema specifies required fields, add matchers
            required = request_body_schema.get("required", [])
            for field in required[:3]:  # limit to 3 for brevity
                matcher["bodyPatterns"].append({
                    "matchesJsonPath": f"$..{field}"
                })

        return matcher

    def _build_response(
        self,
        status_code: int,
        body_override: Any,
        delay_ms: int,
    ) -> dict:
        """Build the WireMock response section."""
        # Determine body
        if body_override is not None:
            body = body_override
        else:
            body = self.STATUS_BODIES.get(
                status_code,
                {"message": f"Mock response (status {status_code})"},
            )

        response: Dict[str, Any] = {
            "status": status_code,
            "headers": {
                "Content-Type": "application/json",
                "X-Mock-Server": "WireMock",
            },
        }

        if body is not None:
            response["jsonBody"] = body

        if delay_ms > 0:
            response["fixedDelayMilliseconds"] = delay_ms

        return response

    @staticmethod
    def _default_status(method: str) -> int:
        """Get the default success status code for an HTTP method."""
        method_upper = method.upper()
        if method_upper == "POST":
            return 201
        if method_upper == "DELETE":
            return 204
        return 200
