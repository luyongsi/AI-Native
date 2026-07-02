"""
A5 Sub-module: N+1 Query Detector

Scans OpenAPI specifications for N+1 query anti-patterns: API endpoints that,
when called in sequence, cause a cascade of downstream requests proportional
to the result set size.

In production, this would:
  1. Parse the OpenAPI spec (paths, parameters, response schemas).
  2. Build a call-graph of endpoint dependencies by tracing $ref relationships
     in response schemas and matching path parameter names.
  3. Flag patterns like:
     - GET /items returns N results, then GET /items/{id}/detail is called
       N times (classic N+1).
     - List endpoints whose responses embed only IDs, forcing N detail fetches.
     - Paginated endpoints where the consumer fetches all pages sequentially
       without batching.
  4. Suggest fixes: eager loading (include/expand params), batch endpoints,
     DataLoader patterns, GraphQL federation, or denormalized views.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Endpoint pairs that commonly exhibit N+1 patterns
_N1_PATTERNS: List[Dict[str, Any]] = [
    {
        "list_pattern": "/{resource}",
        "detail_pattern": "/{resource}/{id}",
        "description": "List endpoint returns IDs; consumer iterates to fetch each detail.",
    },
    {
        "list_pattern": "/{resource}",
        "detail_pattern": "/{resource}/{id}/related",
        "description": "Each list item triggers a related-resource fetch.",
    },
    {
        "list_pattern": "/{resource}",
        "detail_pattern": "/{resource}/{id}/permissions",
        "description": "RBAC permission checks called per-item after listing.",
    },
    {
        "list_pattern": "/orders",
        "detail_pattern": "/orders/{id}/items",
        "description": "Order detail with line items fetched per order.",
    },
    {
        "list_pattern": "/users",
        "detail_pattern": "/users/{id}/roles",
        "description": "User roles fetched individually after user listing.",
    },
]


class N1Detector:
    """Detects N+1 query patterns in OpenAPI specifications."""

    # Severity thresholds
    _SEVERITY_HIGH_THRESHOLD = 5    # estimated_queries >= 5 per parent -> high
    _SEVERITY_MEDIUM_THRESHOLD = 2  # estimated_queries >= 2 -> medium

    def __init__(self, max_list_size: int = 100):
        """Args:
            max_list_size: Assumed max items per list response for estimation.
        """
        self.max_list_size = max_list_size
        logger.debug("N1Detector initialized with max_list_size=%d", max_list_size)

    async def detect(self, api_spec: dict) -> dict:
        """Scan an OpenAPI spec for N+1 query patterns.

        Args:
            api_spec: OpenAPI 3.x spec dict with 'paths' key.

        Returns:
            Dict with:
                - n1_queries: [{path, method, estimated_queries, severity, suggestion}]
                - total_detected: int count of N+1 patterns found
                - risk_score: 0-100 overall N+1 risk
        """
        paths = api_spec.get("paths", {})
        if not paths:
            logger.warning("No paths found in API spec; returning empty detection.")
            return {
                "n1_queries": [],
                "total_detected": 0,
                "risk_score": 0,
            }

        logger.info("Detecting N+1 patterns across %d API paths", len(paths))

        detections: List[Dict[str, Any]] = []

        # 1. Pattern-based detection: list + detail pairs
        pattern_detections = self._detect_by_pattern(paths)
        detections.extend(pattern_detections)

        # 2. Structural detection: nested resource paths with ID params
        structural_detections = self._detect_by_structure(paths)
        detections.extend(structural_detections)

        # 3. De-duplicate by (path, method)
        seen: set = set()
        unique_detections: List[Dict[str, Any]] = []
        for d in detections:
            key = (d["path"], d["method"])
            if key not in seen:
                seen.add(key)
                unique_detections.append(d)

        # Determine severity for each detection
        for d in unique_detections:
            est = d.get("estimated_queries", 1)
            if est >= self._SEVERITY_HIGH_THRESHOLD:
                d["severity"] = "high"
            elif est >= self._SEVERITY_MEDIUM_THRESHOLD:
                d["severity"] = "medium"
            else:
                d["severity"] = "low"

        # Risk score: weighted by severity count
        high_count = sum(1 for d in unique_detections if d["severity"] == "high")
        medium_count = sum(1 for d in unique_detections if d["severity"] == "medium")
        low_count = sum(1 for d in unique_detections if d["severity"] == "low")

        risk_score = min(
            round(high_count * 25 + medium_count * 15 + low_count * 5, 1),
            100,
        )

        result: Dict[str, Any] = {
            "n1_queries": unique_detections,
            "total_detected": len(unique_detections),
            "risk_score": risk_score,
        }

        if risk_score >= 50:
            logger.warning(
                "High N+1 risk detected: score=%.1f, patterns=%d",
                risk_score,
                len(unique_detections),
            )
        else:
            logger.info(
                "N+1 detection complete: score=%.1f, patterns=%d",
                risk_score,
                len(unique_detections),
            )

        return result

    # ---- Pattern-based detection ----

    def _detect_by_pattern(self, paths: dict) -> List[Dict[str, Any]]:
        """Match known N+1 path patterns against the spec."""
        detections: List[Dict[str, Any]] = []
        path_list = list(paths.keys())

        for pattern in _N1_PATTERNS:
            list_tpl = pattern["list_pattern"]
            detail_tpl = pattern["detail_pattern"]

            # Extract resource name from template
            resource = list_tpl.strip("/{}")
            if resource not in str(path_list):
                continue

            list_path = f"/{resource}"
            detail_path = f"/{resource}/{{id}}"
            nested_path = detail_tpl.replace(f"/{resource}/{{id}}", detail_path)

            has_list = list_path in paths
            has_detail = detail_path in paths
            has_nested = nested_path in paths

            if has_list and (has_detail or has_nested):
                target_path = nested_path if has_nested else detail_path
                target_methods = list((paths.get(target_path) or {}).keys())
                method = target_methods[0] if target_methods else "get"

                detections.append({
                    "path": target_path,
                    "method": method,
                    "estimated_queries": self.max_list_size,
                    "parent_path": list_path,
                    "pattern_type": "list_to_detail",
                    "suggestion": (
                        f"Use eager loading with ?include={resource.split('/')[-1]} "
                        f"parameter on {list_path}, or provide a batch endpoint "
                        f"POST {resource}/batch."
                    ),
                })

        return detections

    # ---- Structural detection ----

    def _detect_by_structure(self, paths: dict) -> List[Dict[str, Any]]:
        """Detect N+1 candidates from path structure alone.

        Flags any endpoint matching /{resource}/{id}/{sub_resource} as a
        potential N+1 if the parent /{resource} also exists.
        """
        detections: List[Dict[str, Any]] = []
        path_entries = sorted(paths.keys())

        for path in path_entries:
            segments = [s for s in path.split("/") if s]
            # Looking for /resource/{id}/sub_resource pattern (3+ segments)
            if len(segments) < 3:
                continue
            if "{id}" not in segments:
                continue

            # Reconstruct parent list path
            id_idx = segments.index("{id}")
            if id_idx < 1:
                continue
            parent_path = "/" + "/".join(segments[:id_idx])
            sub_resource = "/".join(segments[id_idx + 1:])

            if parent_path in paths and sub_resource:
                methods = list((paths[path] or {}).keys())
                method = "get" if "get" in methods else methods[0] if methods else "get"

                suggestion = (
                    f"Consider adding ?expand={sub_resource} to {parent_path} "
                    f"list endpoint to avoid N+1 fetches for each item's {sub_resource}."
                )

                detections.append({
                    "path": path,
                    "method": method,
                    "estimated_queries": self.max_list_size,
                    "parent_path": parent_path,
                    "pattern_type": "nested_resource",
                    "suggestion": suggestion,
                })

        return detections

    # ---- Convenience scoring ----

    @classmethod
    async def quick_risk(cls, api_spec: dict) -> float:
        """Convenience: return just the risk score 0-100."""
        detector = cls()
        result = await detector.detect(api_spec)
        return float(result["risk_score"])

    @classmethod
    async def has_critical(
        cls, api_spec: dict, threshold: float = 50.0
    ) -> bool:
        """Convenience: return True if N+1 risk exceeds threshold."""
        risk = await cls.quick_risk(api_spec)
        return risk >= threshold
