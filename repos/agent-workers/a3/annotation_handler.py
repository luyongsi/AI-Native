"""
annotation_handler.py — User Annotation Processor

Handles user feedback annotations on a prototype, updating the design
accordingly. Supports point, region, and text annotations. Real
implementation would parse pixel coordinates, map them to component
boundaries, and trigger targeted re-generation of affected components.

Contract:
    class AnnotationHandler
        async process_annotation(annotation: dict, current_design: dict) -> dict
        -> {updated_components: [...], diff: dict, hot_reload: bool}
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class AnnotationHandler:
    """Process user annotations on a prototype and return design updates.

    In production this would:
      1. Map annotation coordinates to the component tree.
      2. Call an LLM with the annotation text and the component's current props.
      3. Return a JSON patch (RFC 6902) that the sandbox applies for hot-reload.
    """

    async def process_annotation(self, annotation: dict,
                                 current_design: dict) -> dict:
        """Apply a single user annotation to the current design.

        Args:
            annotation:     {type: "point"|"region"|"text",
                             position?: {x, y}, region?: {x, y, w, h},
                             text?: str, author?: str, component_id?: str}
            current_design: The current prototype design tree (pages + components).

        Returns:
            {updated_components: [...], diff: dict, hot_reload: bool}
        """
        anno_type = annotation.get("type", "text")
        text = annotation.get("text", "")
        component_id = annotation.get("component_id", "")

        logger.info("Processing annotation type=%s on component=%s from author=%s",
                    anno_type, component_id, annotation.get("author", "unknown"))

        # ---------- stub logic ----------
        updated_components: list[dict] = []

        if anno_type == "text":
            # Parse simple commands from the annotation text
            if "颜色" in text or "color" in text.lower():
                updated_components.append({
                    "component_id": component_id or "auto-detected",
                    "change": "color",
                    "before": {"color": "#1890FF"},
                    "after": {"color": "#FF6B35"},
                    "reason": text,
                })
            elif "间距" in text or "spacing" in text.lower():
                updated_components.append({
                    "component_id": component_id or "auto-detected",
                    "change": "spacing",
                    "before": {"padding": "16px"},
                    "after": {"padding": "24px"},
                    "reason": text,
                })
            else:
                updated_components.append({
                    "component_id": component_id or "auto-detected",
                    "change": "generic",
                    "reason": text,
                })

        elif anno_type == "point":
            updated_components.append({
                "component_id": component_id or "point-target",
                "change": "highlight",
                "position": annotation.get("position"),
                "reason": text or "Point-and-click annotation",
            })

        elif anno_type == "region":
            updated_components.append({
                "component_id": component_id or "region-target",
                "change": "rework_region",
                "region": annotation.get("region"),
                "reason": text or "Region selected for redesign",
            })

        diff = {
            "additions": len(updated_components),
            "deletions": 0,
            "modifications": len(updated_components),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Hot-reload is true for simple cosmetic changes, false for structural ones
        hot_reload = anno_type in ("point", "text")

        return {
            "updated_components": updated_components,
            "diff": diff,
            "hot_reload": hot_reload,
        }
