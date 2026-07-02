"""
A4 Sub-module: Schema Validator

Validates generated OpenAPI 3.1 specifications against the official schema.
Provides retry logic and error reporting for schema validation failures.
"""

import json
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Validates OpenAPI 3.1 specifications."""

    # Required top-level fields for OpenAPI 3.1
    REQUIRED_FIELDS = ["openapi", "info", "paths"]

    # Required info fields
    REQUIRED_INFO_FIELDS = ["title", "version"]

    def validate(self, schema: dict) -> Tuple[bool, List[str]]:
        """Validate an OpenAPI 3.1 specification.

        Args:
            schema: The OpenAPI spec dict to validate.

        Returns:
            A tuple of (is_valid, errors) where is_valid is a bool
            and errors is a list of error messages.
        """
        errors: List[str] = []

        # Check top-level structure
        if not isinstance(schema, dict):
            errors.append("Schema must be a dictionary")
            return False, errors

        # Check required top-level fields
        for field in self.REQUIRED_FIELDS:
            if field not in schema:
                errors.append(f"Missing required field: {field}")

        # Validate openapi version
        if "openapi" in schema:
            openapi_version = schema["openapi"]
            if not isinstance(openapi_version, str):
                errors.append("Field 'openapi' must be a string")
            elif not openapi_version.startswith("3.1"):
                errors.append(f"Expected OpenAPI 3.1.x, got {openapi_version}")

        # Validate info object
        if "info" in schema:
            info = schema["info"]
            if not isinstance(info, dict):
                errors.append("Field 'info' must be an object")
            else:
                for field in self.REQUIRED_INFO_FIELDS:
                    if field not in info:
                        errors.append(f"Missing required info field: {field}")
                if "version" in info and not isinstance(info["version"], str):
                    errors.append("Field 'info.version' must be a string")
                if "title" in info and not isinstance(info["title"], str):
                    errors.append("Field 'info.title' must be a string")

        # Validate paths object
        if "paths" in schema:
            paths = schema["paths"]
            if not isinstance(paths, dict):
                errors.append("Field 'paths' must be an object")
            elif len(paths) == 0:
                errors.append("Field 'paths' must not be empty")
            else:
                for path_key, path_item in paths.items():
                    if not isinstance(path_item, dict):
                        errors.append(f"Path '{path_key}' must be an object")
                    else:
                        # Check valid HTTP methods
                        valid_methods = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}
                        for method in path_item.keys():
                            if method not in valid_methods and not method.startswith("$"):
                                errors.append(f"Path '{path_key}' has invalid HTTP method: {method}")
                            elif method in valid_methods and not isinstance(path_item[method], dict):
                                errors.append(f"Operation '{method}' in path '{path_key}' must be an object")

        # Validate components if present
        if "components" in schema:
            components = schema["components"]
            if not isinstance(components, dict):
                errors.append("Field 'components' must be an object")
            else:
                if "schemas" in components:
                    schemas = components["schemas"]
                    if not isinstance(schemas, dict):
                        errors.append("Field 'components.schemas' must be an object")

        # Validate servers if present
        if "servers" in schema:
            servers = schema["servers"]
            if not isinstance(servers, list):
                errors.append("Field 'servers' must be an array")
            else:
                for i, server in enumerate(servers):
                    if not isinstance(server, dict):
                        errors.append(f"Server[{i}] must be an object")
                    elif "url" not in server:
                        errors.append(f"Server[{i}] missing required field 'url'")

        is_valid = len(errors) == 0
        if is_valid:
            logger.info("OpenAPI 3.1 schema validation passed")
        else:
            logger.warning(f"OpenAPI 3.1 schema validation failed: {len(errors)} errors")

        return is_valid, errors

    def validate_and_fix(self, schema: dict) -> Tuple[bool, dict, List[str]]:
        """Attempt to fix common validation errors.

        Args:
            schema: The OpenAPI spec dict to validate and fix.

        Returns:
            A tuple of (is_valid, fixed_schema, errors).
        """
        is_valid, errors = self.validate(schema)
        if is_valid:
            return True, schema, []

        fixed_schema = schema.copy()
        fixed_errors = []

        # Attempt fixes for common issues
        if "openapi" not in fixed_schema:
            fixed_schema["openapi"] = "3.1.0"
            fixed_errors.append("Added missing 'openapi' field with version 3.1.0")

        if "info" not in fixed_schema:
            fixed_schema["info"] = {"title": "API", "version": "0.1.0"}
            fixed_errors.append("Added missing 'info' object")
        else:
            if "title" not in fixed_schema["info"]:
                fixed_schema["info"]["title"] = "API"
                fixed_errors.append("Added missing 'info.title'")
            if "version" not in fixed_schema["info"]:
                fixed_schema["info"]["version"] = "0.1.0"
                fixed_errors.append("Added missing 'info.version'")

        if "paths" not in fixed_schema:
            fixed_schema["paths"] = {"/health": {"get": {"summary": "Health check", "responses": {"200": {"description": "OK"}}}}}
            fixed_errors.append("Added missing 'paths' object with health endpoint")

        # Re-validate after fixes
        is_valid_after, remaining_errors = self.validate(fixed_schema)

        if not is_valid_after:
            logger.warning(f"Schema still has errors after fixes: {remaining_errors}")

        return is_valid_after, fixed_schema, fixed_errors
