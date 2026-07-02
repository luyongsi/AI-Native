"""
A5 Sub-module: UX Evaluator

Evaluates UI/UX design artifact against Nielsen's 10 usability heuristics.
Returns a scored report with per-heuristic findings and accessibility checks.

In production, this would:
  1. Accept a design artifact: wireframes (Figma links, image URLs), component
     trees, interaction flows, or design-system tokens.
  2. Use a vision-capable LLM (e.g. Claude) to inspect screenshots against
     each heuristic, or parse structured design tokens for rule-based checks.
  3. Cross-reference WCAG 2.2 guidelines for color contrast, focus order,
     landmark roles, and keyboard navigation conformance.
  4. Generate prioritised fix suggestions linked to specific UI elements.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Nielsen's 10 Usability Heuristics
_NIELSEN_HEURISTICS: List[Dict[str, Any]] = [
    {"id": "H1", "name": "Visibility of system status",
     "description": "The design should always keep users informed about what is going on, through appropriate feedback within a reasonable time."},
    {"id": "H2", "name": "Match between system and the real world",
     "description": "The design should speak the users' language. Use words, phrases, and concepts familiar to the user."},
    {"id": "H3", "name": "User control and freedom",
     "description": "Users often perform actions by mistake. They need a clearly marked 'emergency exit' to leave the unwanted action."},
    {"id": "H4", "name": "Consistency and standards",
     "description": "Users should not have to wonder whether different words, situations, or actions mean the same thing. Follow platform conventions."},
    {"id": "H5", "name": "Error prevention",
     "description": "Good error messages are important, but the best designs carefully prevent problems from occurring in the first place."},
    {"id": "H6", "name": "Recognition rather than recall",
     "description": "Minimize the user's memory load by making elements, actions, and options visible."},
    {"id": "H7", "name": "Flexibility and efficiency of use",
     "description": "Shortcuts -- hidden from novice users -- may speed up the interaction for the expert user."},
    {"id": "H8", "name": "Aesthetic and minimalist design",
     "description": "Interfaces should not contain information that is irrelevant or rarely needed."},
    {"id": "H9", "name": "Help users recognize, diagnose, and recover from errors",
     "description": "Error messages should be expressed in plain language, precisely indicate the problem, and constructively suggest a solution."},
    {"id": "H10", "name": "Help and documentation",
     "description": "It is best if the system does not need any additional explanation. However, it may be necessary to provide documentation."},
]

# WCAG 2.2 accessibility check dimensions
_ACCESSIBILITY_CHECKS: List[str] = [
    "color_contrast",
    "keyboard_navigation",
    "screen_reader_compatibility",
    "focus_indicators",
    "text_resizing",
    "landmark_roles",
    "aria_labels",
    "motion_reduction",
]


class UXEvaluator:
    """Evaluates a UI/UX design against Nielsen's 10 heuristics and WCAG 2.2."""

    def __init__(self, accessibility_level: str = "AA"):
        """Args:
            accessibility_level: WCAG conformance target ('A', 'AA', 'AAA').
        """
        self.accessibility_level = accessibility_level
        logger.debug("UXEvaluator initialized with a11y_level=%s", accessibility_level)

    async def evaluate(self, design: dict) -> dict:
        """Evaluate a design artifact for UX quality.

        Args:
            design: Dict with optional keys:
                - wireframes (list): URLs or structured component data
                - components (list): component tree with states
                - interactions (list): user flow descriptions
                - design_tokens (dict): colors, typography, spacing

        Returns:
            Dict with:
                - score: 0-100 overall UX score
                - heuristics: [{id, name, passed: bool, comment}]
                - accessibility_score: 0-100
                - suggestions: list of improvement recommendations
        """
        logger.info(
            "Evaluating UX design: wireframes=%d, components=%d, interactions=%d",
            len(design.get("wireframes", [])),
            len(design.get("components", [])),
            len(design.get("interactions", [])),
        )

        # Evaluate each heuristic
        heuristics = self._evaluate_heuristics(design)

        # Accessibility assessment
        a11y_score, a11y_suggestions = self._evaluate_accessibility(design)

        # Aggregate
        passed_count = sum(1 for h in heuristics if h["passed"])
        heuristic_score = round((passed_count / len(_NIELSEN_HEURISTICS)) * 70.0)

        # Overall score: 70% heuristic + 30% accessibility
        overall_score = round(heuristic_score * 0.7 + a11y_score * 0.3, 1)

        # Generate contextual suggestions
        suggestions = self._generate_suggestions(heuristics, a11y_suggestions, design)

        result: Dict[str, Any] = {
            "score": overall_score,
            "heuristics": heuristics,
            "heuristic_score": heuristic_score,
            "heuristics_passed": passed_count,
            "heuristics_total": len(_NIELSEN_HEURISTICS),
            "accessibility_score": a11y_score,
            "accessibility_level": self.accessibility_level,
            "suggestions": suggestions,
        }

        logger.info(
            "UX evaluation complete: score=%.1f, heuristics=%d/%d, a11y=%.1f",
            overall_score,
            passed_count,
            len(_NIELSEN_HEURISTICS),
            a11y_score,
        )
        return result

    # ---- Heuristic evaluation ----

    def _evaluate_heuristics(self, design: dict) -> List[Dict[str, Any]]:
        """Mock: evaluate each heuristic against the design artifact.

        In production, this would call an LLM per heuristic or use a
        rule engine that inspects structured design tokens.
        """
        components = design.get("components", [])
        interactions = design.get("interactions", [])
        tokens = design.get("design_tokens", {})
        wireframes = design.get("wireframes", [])

        # Design richness signals (more artifacts -> better scores)
        has_wireframes = bool(wireframes)
        has_interactions = bool(interactions)
        has_tokens = bool(tokens)
        has_components = bool(components)
        richness = sum([has_wireframes, has_interactions, has_tokens, has_components])

        results: List[Dict[str, Any]] = []
        for heuristic in _NIELSEN_HEURISTICS:
            hid = heuristic["id"]
            passed, comment = self._check_heuristic(
                hid, design, richness
            )
            results.append({
                "id": hid,
                "name": heuristic["name"],
                "passed": passed,
                "comment": comment,
            })

        return results

    def _check_heuristic(
        self,
        heuristic_id: str,
        design: dict,
        richness: int,
    ) -> tuple:
        """Mock heuristic check with realistic pass/fail patterns.

        Returns:
            (passed: bool, comment: str)
        """
        # Higher richness -> more heuristics pass
        component_names = [
            c.get("name", "").lower()
            for c in design.get("components", [])
        ]
        interaction_descriptions = [
            i.get("description", "").lower()
            for i in design.get("interactions", [])
        ]
        all_text = " ".join(component_names + interaction_descriptions)

        # Deterministic pass/fail based on design signals
        if heuristic_id == "H1":  # System status
            has_loading = "loading" in all_text or "spinner" in all_text or "progress" in all_text
            return (
                has_loading or richness >= 2,
                "System status indicators found in components."
                if has_loading
                else "Missing loading, empty, and error state indicators. Add skeleton loaders and toast notifications.",
            )
        elif heuristic_id == "H2":  # Real-world match
            return (
                richness >= 2,
                "Language matches domain terminology."
                if richness >= 2
                else "Technical jargon detected; use domain-appropriate labels.",
            )
        elif heuristic_id == "H3":  # User control
            has_undo = "undo" in all_text or "cancel" in all_text or "back" in all_text
            return (
                has_undo or richness >= 1,
                "Undo/cancel mechanisms present."
                if has_undo
                else "Missing undo/cancel options for destructive actions.",
            )
        elif heuristic_id == "H4":  # Consistency
            has_tokens = bool(design.get("design_tokens"))
            return (
                has_tokens or richness >= 3,
                "Design tokens enforce visual consistency."
                if has_tokens
                else "No design tokens found; risk of inconsistent styling across components.",
            )
        elif heuristic_id == "H5":  # Error prevention
            has_validation = "validation" in all_text or "confirm" in all_text
            return (
                has_validation or richness >= 2,
                "Input validation and confirmation dialogs present."
                if has_validation
                else "No input validation patterns found for forms.",
            )
        elif heuristic_id == "H6":  # Recognition over recall
            return (
                richness >= 1,
                "Visual cues and icons reduce memory load."
                if richness >= 1
                else "Relying on user memory; add visible cues and autocomplete.",
            )
        elif heuristic_id == "H7":  # Flexibility
            has_shortcuts = "shortcut" in all_text or "keyboard" in all_text
            return (
                has_shortcuts or richness >= 3,
                "Keyboard shortcuts defined for power users."
                if has_shortcuts
                else "Consider adding keyboard shortcuts for frequent actions.",
            )
        elif heuristic_id == "H8":  # Aesthetic / minimalist
            return (
                richness >= 2,
                "Design appears clean and focused."
                if richness >= 2
                else "Interface may be cluttered; audit for unnecessary elements.",
            )
        elif heuristic_id == "H9":  # Error recovery
            has_error_states = "error" in all_text or "retry" in all_text
            return (
                has_error_states or richness >= 2,
                "Error states and recovery paths documented."
                if has_error_states
                else "No error recovery flows; add inline validation and retry mechanisms.",
            )
        elif heuristic_id == "H10":  # Help
            has_help = "help" in all_text or "tooltip" in all_text or "documentation" in all_text
            return (
                has_help or richness >= 1,
                "Inline help and tooltips present."
                if has_help
                else "Consider adding contextual help tooltips and a help center link.",
            )
        else:
            return True, "Passed general evaluation."

    # ---- Accessibility evaluation ----

    def _evaluate_accessibility(self, design: dict) -> tuple:
        """Evaluate WCAG 2.2 accessibility conformance (mock).

        Returns:
            (score 0-100, list of suggestion strings)
        """
        tokens = design.get("design_tokens", {})
        colors = tokens.get("colors", {})
        components = design.get("components", [])

        # Check for a11y signals
        has_contrast = bool(colors)  # colors defined implies contrast considered
        has_aria = any("aria" in c.get("name", "").lower() for c in components)
        has_roles = any("role" in c.get("name", "").lower() for c in components)
        has_alt_text = "alt" in str(design).lower()

        # Baseline from level (AA = 70 base, AAA = 85 base, A = 50 base)
        level_bases = {"A": 50, "AA": 70, "AAA": 85}
        base = level_bases.get(self.accessibility_level, 70)

        suggestions: List[str] = []
        score = base

        if has_contrast:
            score += 10
        else:
            suggestions.append(
                "Define color contrast ratios meeting WCAG "
                f"{self.accessibility_level} minimums (text: 4.5:1, large text: 3:1)."
            )

        if has_aria or has_roles:
            score += 10
        else:
            suggestions.append("Add ARIA labels and landmark roles to all interactive elements.")

        if has_alt_text:
            score += 5
        else:
            suggestions.append("Ensure all images and icons have descriptive alt text.")

        if "keyboard" in str(design).lower():
            score += 5
        else:
            suggestions.append("Document keyboard navigation order and focus trap behavior.")

        score = min(round(score, 1), 100.0)
        logger.debug("Accessibility score: %.1f, suggestions: %d", score, len(suggestions))
        return score, suggestions

    # ---- Suggestion generation ----

    def _generate_suggestions(
        self,
        heuristics: List[Dict[str, Any]],
        a11y_suggestions: List[str],
        design: dict,
    ) -> List[str]:
        """Aggregate and prioritize improvement suggestions."""
        suggestions: List[str] = []

        # Heuristic failures (prioritize the most critical)
        for h in heuristics:
            if not h["passed"]:
                suggestions.append(f"[{h['id']}] {h['name']}: {h['comment']}")

        # Accessibility gaps
        suggestions.extend(a11y_suggestions)

        # General improvement nudges
        if not design.get("wireframes"):
            suggestions.append(
                "Attach wireframes or mockups for more accurate UX evaluation."
            )
        if not design.get("interactions"):
            suggestions.append(
                "Document user interaction flows (happy path + error states)."
            )
        if not design.get("design_tokens"):
            suggestions.append(
                "Provide design tokens (colors, spacing, typography) for consistency validation."
            )

        return suggestions
