"""
conflict_detector.py — Cross-Spec Conflict Detector

Detects conflicts between a new requirement and existing specifications
by comparing entity fields, business rules, and constraints.
Real implementation would query a structured spec store (e.g. PostgreSQL
with JSONB specs) and use an LLM to reason about semantic conflicts.

Contract:
    class ConflictDetector
        async detect(new_requirement: dict, existing_specs: list[dict]) -> dict
        -> {conflicts: [{entity, field, existing_value, new_value, severity}],
            has_conflicts: bool}
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ConflictDetector:
    """Detect conflicts between a new requirement and existing specifications.

    The stub performs exact field comparison on a handful of known field names.
    A production implementation would:
      1. Normalize both specs into a canonical JSON schema.
      2. Compare field types, constraints, and business rules.
      3. Use an LLM judge to classify severity for ambiguous cases.
    """

    # Fields that are conflict-sensitive and should be compared
    _SENSITIVE_FIELDS = frozenset({
        "status", "type", "max_length", "min_value", "max_value",
        "required", "unique", "format", "default", "nullable",
        "precision", "scale", "enum_values",
    })

    async def detect(self, new_requirement: dict, existing_specs: list[dict]) -> dict:
        """Compare *new_requirement* against every entry in *existing_specs*.

        Args:
            new_requirement: dict with at least ``entities`` (list of
                             {name, fields: [{name, type, ...constraints}]}).
            existing_specs:  list of previously approved specs in the same shape.

        Returns:
            {conflicts: [...], has_conflicts: bool}
        """
        logger.info("Detecting conflicts against %d existing specs", len(existing_specs))

        conflicts: list[dict] = []

        new_entities = new_requirement.get("entities", [])
        if not new_entities:
            logger.debug("No entities in new requirement — skipping conflict check")
            return {"conflicts": [], "has_conflicts": False}

        for existing_spec in existing_specs:
            existing_entities = existing_spec.get("entities", [])
            for new_ent in new_entities:
                ent_name = new_ent.get("name", "")
                for exist_ent in existing_entities:
                    if exist_ent.get("name") != ent_name:
                        continue
                    # Same entity name — compare fields
                    new_fields = {f["name"]: f for f in new_ent.get("fields", [])}
                    exist_fields = {f["name"]: f for f in exist_ent.get("fields", [])}
                    for fname, nf in new_fields.items():
                        ef = exist_fields.get(fname)
                        if not ef:
                            continue
                        # Compare sensitive attributes
                        for attr in self._SENSITIVE_FIELDS:
                            nv = nf.get(attr)
                            ev = ef.get(attr)
                            if nv is not None and ev is not None and nv != ev:
                                severity = self._classify_severity(attr, ev, nv)
                                conflicts.append({
                                    "entity": ent_name,
                                    "field": fname,
                                    "attribute": attr,
                                    "existing_value": ev,
                                    "new_value": nv,
                                    "severity": severity,
                                    "existing_spec_id": existing_spec.get("id", "unknown"),
                                })
                                logger.warning(
                                    "Conflict: %s.%s.%s (%s → %s) [%s]",
                                    ent_name, fname, attr, ev, nv, severity,
                                )

        return {
            "conflicts": conflicts,
            "has_conflicts": len(conflicts) > 0,
        }

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_severity(attr: str, existing_val: Any, new_val: Any) -> str:
        """Assign severity based on the attribute and magnitude of change."""
        high_risk_attrs = {"type", "format", "precision", "scale"}
        if attr in high_risk_attrs:
            return "high"
        if attr in ("max_length", "min_value", "max_value"):
            return "medium"
        return "low"
