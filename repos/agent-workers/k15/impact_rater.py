"""
k15/impact_rater.py — K15 sub-module: Change Impact Classification

Rates the severity of a set of changes as breaking, major, minor, or patch
based on file paths, change types, and an impact heuristic.  Used by K15 to
decide whether human review is required before propagating changes.

Usage:
    rater = ImpactRater()
    result = rater.rate(changes)
    if rater.should_notify(result):
        notify_human(...)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
IMPACT_BREAKING_THRESHOLD = 50  # score > 50  → breaking
IMPACT_MAJOR_THRESHOLD = 25     # score > 25  → major
IMPACT_MINOR_THRESHOLD = 10     # score > 10  → minor; <= 10 → patch

# File patterns that signal higher impact (Phase 2 heuristic)
_HIGH_IMPACT_PATTERNS: List[str] = [
    "api/", "schema", "migration", "auth", "config/", "Dockerfile",
    "requirements", "pyproject.toml", "setup.cfg", ".env", "Makefile",
    ".github/workflows", "db/", "database/",
]
_MEDIUM_IMPACT_PATTERNS: List[str] = [
    "src/", "lib/", "core/", "models/", "services/", "handlers/",
    "controllers/", "views/", "routes/", "middleware/",
]
# Everything else is considered low impact

# Change-type weights (Phase 2 heuristic)
_CHANGE_TYPE_WEIGHTS: Dict[str, int] = {
    "deleted":   40,
    "renamed":   35,
    "modified":  20,
    "added":     10,
    "moved":     25,
}


class ImpactRater:
    """Classifies the overall impact of a set of file changes.

    Phase 2 (current): Heuristic scoring based on file paths and change types.
    Phase 3 (planned):  ML-based impact prediction from historical change data,
                        git blame heuristics, and test coverage correlation.

    Attributes:
        _breaking_threshold: Score above which impact is "breaking".
        _major_threshold:    Score above which impact is "major".
        _minor_threshold:    Score above which impact is "minor" (else "patch").
    """

    def __init__(
        self,
        breaking_threshold: int = IMPACT_BREAKING_THRESHOLD,
        major_threshold: int = IMPACT_MAJOR_THRESHOLD,
        minor_threshold: int = IMPACT_MINOR_THRESHOLD,
    ) -> None:
        self._breaking_threshold = breaking_threshold
        self._major_threshold = major_threshold
        self._minor_threshold = minor_threshold
        logger.info(
            "ImpactRater initialized (thresholds: breaking>%d, major>%d, minor>%d)",
            breaking_threshold,
            major_threshold,
            minor_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rate(self, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Rate a list of file changes and return an overall impact assessment.

        Args:
            changes: List of change dicts, each with keys:
                - ``file`` (str):         File path that changed.
                - ``change_type`` (str):  One of added, modified, deleted,
                                          renamed, moved.
                - ``reason`` (str, optional): Human-readable reason.

        Returns:
            Dict with keys:
                overall_impact (str):       "breaking" | "major" | "minor" | "patch"
                score (int):                Numeric impact score (0-100).
                changes (list):             Annotated change dicts with per-file
                                            impact and reason.
                requires_human_review (bool): True if breaking or major.
        """
        if not changes:
            logger.warning("rate called with empty changes list")
            return {
                "overall_impact": "patch",
                "score": 0,
                "changes": [],
                "requires_human_review": False,
            }

        rated_changes: List[Dict[str, Any]] = []
        total_score = 0

        for change in changes:
            file_path = change.get("file", "")
            change_type = change.get("change_type", "modified")
            user_reason = change.get("reason", "")

            # Compute per-file impact
            impact_score, impact_label, reason = self._rate_single(
                file_path, change_type
            )

            # Override reason if user provided one
            if user_reason:
                reason = user_reason

            rated_changes.append({
                "file": file_path,
                "change_type": change_type,
                "impact": impact_label,
                "score": impact_score,
                "reason": reason,
            })
            total_score += impact_score

        # Normalize score to 0-100 range (cap at 100)
        # Simple averaging with a cap — real Phase 3 would use a proper model
        avg_score = min(100, round(total_score / max(1, len(changes))))

        overall_impact = self._classify_score(avg_score)

        logger.info(
            "Impact rated: %d change(s) → score=%d → %s",
            len(changes),
            avg_score,
            overall_impact,
        )

        return {
            "overall_impact": overall_impact,
            "score": avg_score,
            "changes": rated_changes,
            "requires_human_review": overall_impact in ("breaking", "major"),
        }

    def should_notify(self, impact_result: Dict[str, Any]) -> bool:
        """Determine whether a human should be notified based on the impact rating.

        Args:
            impact_result: The dict returned by ``rate()``.

        Returns:
            True if the overall impact is "breaking" or "major".
        """
        overall = impact_result.get("overall_impact", "patch")
        should = overall in ("breaking", "major")
        logger.debug("should_notify(%s) → %s", overall, should)
        return should

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_single(
        self, file_path: str, change_type: str
    ) -> tuple:
        """Score a single file change.

        Phase 3: Replace with an ML model trained on historical
        change → test-failure correlations.

        Returns:
            (score: int, label: str, reason: str)
        """
        # Base score from change type
        base = _CHANGE_TYPE_WEIGHTS.get(change_type, 20)

        # Multiplier from file path pattern
        multiplier = 1.0
        path_category = "low-impact path"

        for pattern in _HIGH_IMPACT_PATTERNS:
            if pattern in file_path:
                multiplier = 2.5
                path_category = f"high-impact path (matches '{pattern}')"
                break
        else:
            for pattern in _MEDIUM_IMPACT_PATTERNS:
                if pattern in file_path:
                    multiplier = 1.5
                    path_category = f"medium-impact path (matches '{pattern}')"
                    break

        score = int(base * multiplier)
        score = min(100, score)  # cap per-file score

        # Determine per-file impact label
        if score > IMPACT_BREAKING_THRESHOLD:
            label = "breaking"
        elif score > IMPACT_MAJOR_THRESHOLD:
            label = "major"
        elif score > IMPACT_MINOR_THRESHOLD:
            label = "minor"
        else:
            label = "patch"

        reason = f"{change_type} in {path_category} (score={score}) → {label}"
        return score, label, reason

    def _classify_score(self, score: int) -> str:
        """Map a numeric score to an impact label."""
        if score > self._breaking_threshold:
            return "breaking"
        elif score > self._major_threshold:
            return "major"
        elif score > self._minor_threshold:
            return "minor"
        else:
            return "patch"
