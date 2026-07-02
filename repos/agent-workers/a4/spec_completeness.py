"""
A4 Sub-module: Spec Completeness Scorer

Scores a specification document across five dimensions and identifies
missing sections with actionable recommendations.

In production, this would:
  1. Accept a structured spec dict from the main A4 Spec Writer pipeline.
  2. Evaluate each section against a checklist of required fields:
     - API: endpoints documented, auth scheme defined, error codes listed
     - Data Model: ERD present, DDL included, indexes & constraints defined
     - UI: wireframes attached, state transitions documented, a11y considered
     - Testing: test strategy, BDD scenarios, edge-case coverage, perf targets
     - Security: authN/Z, data classification, threat model, compliance reqs
  3. Weight scores by the requirement's risk tier and compliance domain.
  4. Surface a prioritized list of gaps with suggested fixes.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Baseline weights for each section (sum to 100)
_SECTION_WEIGHTS: Dict[str, float] = {
    "api": 25.0,
    "data_model": 25.0,
    "ui": 20.0,
    "testing": 15.0,
    "security": 15.0,
}

# Checklist of "must-have" keys per section
_SECTION_CHECKLIST: Dict[str, List[str]] = {
    "api": [
        "openapi_spec",
        "endpoints",
        "auth_scheme",
        "error_codes",
        "rate_limiting",
    ],
    "data_model": [
        "erd",
        "ddl",
        "entities",
        "relationships",
        "indexes",
        "migrations",
    ],
    "ui": [
        "wireframes",
        "components",
        "state_transitions",
        "accessibility",
        "responsive_design",
    ],
    "testing": [
        "test_strategy",
        "bdd_scenarios",
        "unit_test_plan",
        "integration_test_plan",
        "performance_targets",
    ],
    "security": [
        "auth_model",
        "data_classification",
        "threat_model",
        "compliance_requirements",
        "vulnerability_scan_plan",
    ],
}


class SpecCompleteness:
    """Scores specification completeness and identifies gaps."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """Args:
            weights: Optional per-section weight overrides (keys: api, data_model, ui, testing, security).
        """
        self.weights = weights or dict(_SECTION_WEIGHTS)
        logger.debug(
            "SpecCompleteness initialized with weights=%s",
            {k: round(v, 1) for k, v in self.weights.items()},
        )

    def score(self, spec: dict) -> dict:
        """Score a specification document for completeness.

        Args:
            spec: A dict containing the spec, with optional sub-keys like
                  'openapi', 'erd', 'ui_design', 'test_plan', 'security_plan'.
                  Also accepts nested 'spec_package' wrapper.

        Returns:
            Dict with:
                - total_score: 0-100 weighted score
                - sections: dict of {section_name: 0-100} per-section scores
                - missing_sections: list of section names scoring below threshold
                - recommendations: list of actionable suggestion strings
        """
        # Unwrap nested spec_package if present
        inner = spec.get("spec_package", spec)

        logger.info("Scoring spec completeness across %d dimensions", len(self.weights))

        section_scores: Dict[str, float] = {}
        all_missing: List[str] = []
        all_recommendations: List[str] = []

        for section, checklist in _SECTION_CHECKLIST.items():
            section_data = self._extract_section(inner, section)
            score, missing, recommendations = self._evaluate_section(
                section, section_data, checklist
            )
            section_scores[section] = score
            all_missing.extend(missing)
            all_recommendations.extend(recommendations)

        # Weighted total
        total_score = 0.0
        for section, weight in self.weights.items():
            total_score += (section_scores.get(section, 0.0) / 100.0) * weight

        total_score = round(total_score, 1)

        # Identify missing sections (below 50 threshold)
        missing_sections = [
            sec for sec, sc in section_scores.items() if sc < 50
        ]

        # Deduplicate recommendations
        seen: set = set()
        deduped_recs: List[str] = []
        for rec in all_recommendations:
            if rec not in seen:
                seen.add(rec)
                deduped_recs.append(rec)

        result: Dict[str, Any] = {
            "total_score": total_score,
            "sections": section_scores,
            "missing_sections": missing_sections,
            "recommendations": deduped_recs,
        }

        logger.info(
            "Spec completeness scored: total=%.1f, missing=%d, recommendations=%d",
            total_score,
            len(missing_sections),
            len(deduped_recs),
        )

        if total_score < 50:
            logger.warning(
                "Spec completeness critically low (%.1f). Consider re-drafting before proceeding.",
                total_score,
            )

        return result

    # ---- Internal helpers ----

    def _extract_section(self, spec: dict, section: str) -> dict:
        """Extract section-specific data from the spec with fallback lookups.

        Maps logical section names to possible keys in the spec dict.
        """
        key_map: Dict[str, List[str]] = {
            "api": ["openapi", "openapi_spec", "api_spec", "api"],
            "data_model": ["erd", "data_model", "database", "schema"],
            "ui": ["ui_design", "ui", "frontend", "wireframes"],
            "testing": ["test_plan", "testing", "qa", "test_strategy"],
            "security": ["security_plan", "security", "auth", "compliance"],
        }

        for candidate in key_map.get(section, [section]):
            if candidate in spec and spec[candidate]:
                data = spec[candidate]
                if isinstance(data, dict):
                    return data
        return {}

    def _evaluate_section(
        self,
        section_name: str,
        section_data: dict,
        checklist: List[str],
    ) -> tuple:
        """Score a single section against its checklist.

        Returns:
            (score 0-100, list of missing item descriptions, list of recommendations)
        """
        if not section_data:
            # Section entirely absent
            recommendations = [
                f"[{section_name}] Section is completely missing. "
                f"Add at minimum: {', '.join(checklist[:3])}."
            ]
            return 0.0, [section_name], recommendations

        items_found = 0
        missing: List[str] = []
        recommendations: List[str] = []

        for item in checklist:
            if self._has_item(section_data, item):
                items_found += 1
            else:
                missing.append(f"{section_name}.{item}")
                recommendations.append(
                    f"[{section_name}] Missing '{item}'. "
                    f"Provide the {item.replace('_', ' ')} definition."
                )

        # Score: percentage of checklist items found, plus a completeness bonus
        # for sections that have extra detail beyond the checklist
        base = (items_found / max(len(checklist), 1)) * 90.0
        bonus = min(10.0, len(section_data) * 2.0)  # up to 10 bonus points for detail
        score = round(min(base + bonus, 100.0), 1)

        return score, missing, recommendations

    @staticmethod
    def _has_item(data: dict, key: str) -> bool:
        """Check if a checklist item is present and non-empty in the section data.

        Handles nested keys separated by dots (e.g. 'openapi.paths').
        """
        parts = key.split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                # If we have a list, check if any element has this key
                if any(isinstance(el, dict) and part in el for el in current):
                    continue
                return False
            else:
                return False
            if current is None:
                return False
        # Found and non-empty
        if isinstance(current, (list, dict)):
            return len(current) > 0
        if isinstance(current, str):
            return len(current.strip()) > 0
        return current is not None and current != 0

    # ---- Convenience wrappers ----

    @classmethod
    def quick_score(cls, spec: dict) -> float:
        """Convenience: return just the total_score.

        >>> SpecCompleteness.quick_score({"openapi": {"paths": {"/health": {}}}})
        20.0  # only API section partially filled
        """
        instance = cls()
        return instance.score(spec)["total_score"]

    @classmethod
    def is_ready(cls, spec: dict, threshold: float = 70.0) -> bool:
        """Convenience: return True if spec is ready for Gate 1 review."""
        instance = cls()
        result = instance.score(spec)
        return result["total_score"] >= threshold
