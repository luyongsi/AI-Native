"""
A5 Sub-module: Business Completeness Checker

Validates that a requirement and its derived specification cover all necessary
business rules, edge cases, and compliance constraints.

In production, this would:
  1. Cross-reference the requirement's BDD scenarios (Given-When-Then) against
     the generated spec's endpoints and data model.
  2. Check for missing business rules: validation constraints, state transitions,
     idempotency guarantees, authorization rules, audit trail requirements.
  3. Detect ambiguous or conflicting rules (e.g., two rules that prescribe
     different behaviour for the same trigger condition).
  4. Validate against domain-specific compliance checklists (PCI-DSS, GDPR, SOX,
     HIPAA) stored in the knowledge base or provided as config.
  5. Call an LLM with a structured rubric to score business rule coverage.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Common business rule categories to validate
_BUSINESS_RULE_CATEGORIES: List[str] = [
    "data_validation",
    "state_machine",
    "authorization",
    "audit_trail",
    "idempotency",
    "error_handling",
    "rate_limiting",
    "data_retention",
    "notification",
    "rollback_compensation",
]

# Domain-specific compliance checklists (stub)
_COMPLIANCE_CHECKLISTS: Dict[str, List[str]] = {
    "payment": [
        "PCI-DSS cardholder data handling",
        "idempotency_key for charge/refund",
        "double-spend prevention",
        "reconciliation with payment gateway",
    ],
    "healthcare": [
        "HIPAA data de-identification",
        "audit log immutability",
        "patient consent tracking",
        "BA agreement enforcement",
    ],
    "finance": [
        "SOX segregation of duties",
        "immutable ledger entries",
        "reconciliation reports",
        "approval thresholds",
    ],
    "ecommerce": [
        "inventory reservation timeout",
        "cart abandonment recovery",
        "promotion overlap rules",
        "tax calculation by jurisdiction",
    ],
}


class BusinessChecker:
    """Checks business rule completeness of a requirement + spec pair."""

    def __init__(self, compliance_domain: Optional[str] = None):
        """Args:
            compliance_domain: Optional domain for domain-specific checks
                              (payment, healthcare, finance, ecommerce).
        """
        self.compliance_domain = compliance_domain
        logger.debug(
            "BusinessChecker initialized with domain=%s", compliance_domain
        )

    async def check(self, requirement: dict, spec: dict) -> dict:
        """Check business rule coverage against a requirement and its spec.

        Args:
            requirement: Requirement dict with at least 'title', 'description'.
                         May include 'bdd_scenarios', 'acceptance_criteria',
                         'business_rules', 'constraints'.
            spec: Derived specification dict (OpenAPI, ERD, etc.).

        Returns:
            Dict with:
                - completeness: 0-100 overall business rule coverage
                - missing_rules: list of business rule gaps found
                - ambiguous_rules: list of potentially conflicting rules
                - validation_gaps: list of validation gaps identified
                - recommendation: summary recommendation string
        """
        logger.info(
            "Checking business completeness for '%s'",
            requirement.get("title", "Untitled"),
        )

        # Extract business rules from requirement
        explicit_rules: List[str] = requirement.get("business_rules", [])
        bdd_scenarios = requirement.get("bdd_scenarios", [])
        acceptance_criteria = requirement.get("acceptance_criteria", [])
        constraints = requirement.get("constraints", [])

        # Check coverage of each category
        missing_rules, covered_categories = self._check_rule_categories(
            requirement, spec, explicit_rules
        )

        # Detect ambiguous rules
        ambiguous = self._detect_ambiguities(explicit_rules, bdd_scenarios)

        # Identify validation gaps
        validation_gaps = self._find_validation_gaps(requirement, spec)

        # Domain-specific compliance check
        if self.compliance_domain:
            domain_gaps = self._check_compliance(self.compliance_domain, spec)
            missing_rules.extend(domain_gaps)

        # Compute completeness score
        total_categories = len(_BUSINESS_RULE_CATEGORIES)
        compliance_extras = len(
            _COMPLIANCE_CHECKLISTS.get(self.compliance_domain, [])
        )
        denominator = total_categories + compliance_extras
        completeness = round((covered_categories / max(denominator, 1)) * 100, 1)
        completeness = min(completeness, 100.0)

        # Build recommendation
        recommendation = self._build_recommendation(
            completeness, missing_rules, ambiguous, validation_gaps
        )

        result: Dict[str, Any] = {
            "completeness": completeness,
            "missing_rules": missing_rules,
            "ambiguous_rules": ambiguous,
            "validation_gaps": validation_gaps,
            "recommendation": recommendation,
        }

        logger.info(
            "Business check: completeness=%.1f%%, missing=%d, ambiguous=%d, gaps=%d",
            completeness,
            len(missing_rules),
            len(ambiguous),
            len(validation_gaps),
        )
        return result

    # ---- Rule category coverage ----

    def _check_rule_categories(
        self,
        requirement: dict,
        spec: dict,
        explicit_rules: List[str],
    ) -> tuple:
        """Check how many business rule categories are covered.

        Returns:
            (missing_rules list, covered_count int)
        """
        requirement_text = (
            requirement.get("title", "")
            + " "
            + requirement.get("description", "")
        ).lower()

        # Gather all rule text
        all_rule_text = " ".join(
            [str(r) for r in explicit_rules]
            + [str(requirement.get("constraints", []))]
            + [str(requirement.get("acceptance_criteria", []))]
            + [str(spec.get("openapi", {}))]
        ).lower()

        missing: List[str] = []
        covered = 0

        category_signals: Dict[str, List[str]] = {
            "data_validation": ["valid", "required", "format", "range", "pattern", "max", "min"],
            "state_machine": ["state", "status", "transition", "workflow", "lifecycle"],
            "authorization": ["role", "permission", "auth", "access", "rbac", "policy"],
            "audit_trail": ["audit", "log", "trace", "history", "immutable"],
            "idempotency": ["idempotent", "idempotency", "dedup", "exactly-once"],
            "error_handling": ["error", "exception", "fallback", "retry", "circuit"],
            "rate_limiting": ["rate limit", "throttl", "quota", "burst"],
            "data_retention": ["retention", "purge", "archive", "delete", "GDPR"],
            "notification": ["notify", "email", "webhook", "alert", "push"],
            "rollback_compensation": ["rollback", "compensat", "saga", "undo", "reverse"],
        }

        for category in _BUSINESS_RULE_CATEGORIES:
            signals = category_signals.get(category, [])
            if any(sig in all_rule_text for sig in signals):
                covered += 1
            else:
                missing.append(
                    f"Business rule category '{category}' is not addressed. "
                    f"Consider adding rules for: {', '.join(signals[:3])}."
                )

        return missing, covered

    # ---- Ambiguity detection ----

    def _detect_ambiguities(
        self,
        explicit_rules: List[str],
        bdd_scenarios: list,
    ) -> List[str]:
        """Detect potentially ambiguous or conflicting business rules.

        In production, this would use an LLM to compare rule semantics,
        not just keyword overlap.
        """
        ambiguous: List[str] = []

        # Check for contradictory keywords in rule text
        contradictions = [
            (("always", "never"), "Rule contains both 'always' and 'never' -- may be contradictory."),
            (("must", "optional"), "Rule uses both 'must' and 'optional' -- ambiguous obligation."),
            (("immediately", "delayed"), "Conflicting timing: 'immediately' vs 'delayed'."),
            (("synchronous", "asynchronous"), "Conflicting execution mode: sync vs async."),
            (("approve", "auto-approve"), "Approval flow may conflict with auto-approval rule."),
        ]

        for i, rule in enumerate(explicit_rules):
            rule_lower = str(rule).lower()
            for (kw1, kw2), msg in contradictions:
                if kw1 in rule_lower and kw2 in rule_lower:
                    ambiguous.append(f"Rule #{i}: {msg} -- '{rule[:80]}...'")

        # Check for BDD scenarios without corresponding business rules
        if bdd_scenarios and not explicit_rules:
            ambiguous.append(
                "BDD scenarios are defined but no explicit business rules found. "
                "Scenarios may embed implicit rules that should be formalized."
            )

        return ambiguous

    # ---- Validation gaps ----

    def _find_validation_gaps(self, requirement: dict, spec: dict) -> List[str]:
        """Identify gaps in input/output validation coverage."""
        gaps: List[str] = []

        openapi = spec.get("openapi", {})
        paths = openapi.get("paths", {})
        schemas = openapi.get("components", {}).get("schemas", {})

        # Check if POST/PUT endpoints have request body schemas
        for path, methods in paths.items():
            for method_name, method_def in (methods or {}).items():
                if method_name in ("post", "put", "patch"):
                    req_body = method_def.get("requestBody", {})
                    if not req_body:
                        gaps.append(
                            f"{method_name.upper()} {path} has no request body schema "
                            f"-- input validation rules are undefined."
                        )
                    else:
                        content = req_body.get("content", {}).get("application/json", {})
                        schema_ref = content.get("schema", {}).get("$ref", "")
                        if schema_ref and not schema_ref.split("/")[-1] in schemas:
                            gaps.append(
                                f"{method_name.upper()} {path} references undefined schema "
                                f"'{schema_ref}'."
                            )

        # Check for error response standardization
        has_error_schema = "Error" in schemas or "error" in str(schemas).lower()
        if not has_error_schema:
            gaps.append(
                "No standard error response schema defined. "
                "Define a common Error schema for validation errors."
            )

        return gaps

    # ---- Domain compliance stub ----

    def _check_compliance(self, domain: str, spec: dict) -> List[str]:
        """Check domain-specific compliance requirements."""
        checklist = _COMPLIANCE_CHECKLISTS.get(domain, [])
        spec_text = str(spec).lower()
        gaps: List[str] = []
        for item in checklist:
            # Weak keyword match; in production this would be an LLM-driven check
            keywords = item.lower().split()
            if not any(kw in spec_text for kw in keywords if len(kw) > 3):
                gaps.append(f"[{domain.upper()} Compliance] {item} -- not addressed in spec.")
        return gaps

    # ---- Recommendation ----

    def _build_recommendation(
        self,
        completeness: float,
        missing_rules: List[str],
        ambiguous: List[str],
        validation_gaps: List[str],
    ) -> str:
        """Generate a human-readable recommendation."""
        if completeness >= 90:
            recommendation = (
                "Excellent business rule coverage. Proceed to design review "
                "with confidence. Minor suggestions in the report."
            )
        elif completeness >= 70:
            recommendation = (
                f"Good coverage but {len(missing_rules)} categories need attention. "
                "Address the missing rules before entering development."
            )
        elif completeness >= 50:
            recommendation = (
                "Moderate business rule gaps detected. Schedule a business analyst "
                "review to fill in the missing categories before Gate 2."
            )
        else:
            recommendation = (
                "Critical business rule gaps. The requirement needs substantial "
                "rework. Engage product owner to define missing rules before "
                "proceeding."
            )

        if ambiguous:
            recommendation += (
                f" Also resolve {len(ambiguous)} ambiguous rule(s) to avoid "
                "implementation conflicts."
            )

        return recommendation
