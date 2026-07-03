"""
SchemaValidator — validates event envelopes against JSON schemas.

Loads all .schema.json files from the schemas directory and maps
event_type patterns to their corresponding schemas for runtime validation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jsonschema

logger = logging.getLogger(__name__)

# Mapping from event_type patterns to schema filenames.
# Each entry is (match_type, pattern, schema_filename).
_EVENT_TYPE_SCHEMA_MAP: List[Tuple[str, str, str]] = [
    ("prefix", "gate.", "gate-event.schema.json"),
    ("exact", "agent.status.changed", "agent-status.schema.json"),
    ("prefix", "test.", "test-completed.schema.json"),
    ("exact", "artifact.produced", "artifact-produced.schema.json"),
    ("exact", "loop.tripped", "loop-tripped.schema.json"),
]


class ValidationError(Exception):
    """Raised when an event envelope fails schema validation."""

    pass


class SchemaValidator:
    """Loads JSON schemas and validates event envelopes against them.

    On init, loads all ``*.schema.json`` files from the schemas directory.
    Maps event_type strings to schemas via prefix or exact matching rules.
    """

    def __init__(self, schemas_dir: Optional[str] = None) -> None:
        self._schemas: Dict[str, dict] = {}

        if schemas_dir is None:
            schemas_dir = str(Path(__file__).parent / "schemas")

        self._schemas_dir = Path(schemas_dir)
        self._load_schemas()

    # ------------------------------------------------------------------
    # Schema loading
    # ------------------------------------------------------------------

    def _load_schemas(self) -> None:
        """Load all .schema.json files from the schemas directory.

        Files that cannot be parsed are skipped with a warning — a single
        malformed schema file will not prevent the validator from working
        with the remaining schemas.
        """
        for schema_path in sorted(self._schemas_dir.glob("*.schema.json")):
            try:
                with open(schema_path, "r", encoding="utf-8") as fh:
                    schema = json.load(fh)
                self._schemas[schema_path.name] = schema
                logger.debug("Loaded schema: %s", schema_path.name)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Failed to parse schema file %s (invalid JSON): %s",
                    schema_path.name,
                    exc,
                )
            except OSError as exc:
                logger.warning(
                    "Failed to read schema file %s: %s", schema_path.name, exc
                )

        if not self._schemas:
            logger.warning(
                "No schemas loaded from %s — validation will be a no-op",
                self._schemas_dir,
            )
        else:
            logger.info(
                "Loaded %d schema(s) from %s", len(self._schemas), self._schemas_dir
            )

    # ------------------------------------------------------------------
    # Schema lookup
    # ------------------------------------------------------------------

    def _find_schema(self, event_type: str) -> Optional[dict]:
        """Return the first schema whose pattern matches *event_type*, or ``None``."""
        for match_type, pattern, filename in _EVENT_TYPE_SCHEMA_MAP:
            if match_type == "prefix" and event_type.startswith(pattern):
                schema = self._schemas.get(filename)
                if schema is not None:
                    return schema
                # Schema file not loaded (may have failed to parse) — keep
                # looking in case a later rule also matches.
            elif match_type == "exact" and event_type == pattern:
                schema = self._schemas.get(filename)
                if schema is not None:
                    return schema
        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, event_type: str, payload: dict) -> bool:
        """Validate an event envelope against its schema.

        Args:
            event_type: The event type string (e.g. ``"gate.1.approved"``).
            payload: The flattened event envelope (event_id, event_type,
                     timestamp, and all payload fields at top level).

        Returns:
            ``True`` when validation passes or no matching schema is found.

        Raises:
            ValidationError: When the payload fails schema validation. The
                error message includes the event_type and the specific
                jsonschema violation.
        """
        schema = self._find_schema(event_type)
        if schema is None:
            logger.debug(
                "No schema matched for event_type=%r, skipping validation",
                event_type,
            )
            return True

        try:
            jsonschema.validate(instance=payload, schema=schema)
        except jsonschema.ValidationError as exc:
            raise ValidationError(
                f"Schema validation failed for event_type={event_type!r}: "
                f"{exc.message}"
            ) from exc

        logger.debug("Schema validation passed for event_type=%r", event_type)
        return True
