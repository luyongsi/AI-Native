"""
design_token_mapper.py — Design Token Mapper

Translates abstract UI component descriptions into concrete design tokens
for a given design system (enterprise, material, or custom).
Tokens cover colors, spacing, typography, shadows, and radii.

Contract:
    class DesignTokenMapper
        def map_to_tokens(components: list, token_system: str = "enterprise") -> dict
        -> {tokens: dict, component_tokens: dict}
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ---------- enterprise design token system (Ant-Design inspired) ----------

_ENTERPRISE_TOKENS: dict[str, Any] = {
    "colors": {
        "primary": "#1890FF",
        "success": "#52C41A",
        "warning": "#FAAD14",
        "danger": "#FF4D4F",
        "info": "#1890FF",
        "text_primary": "#262626",
        "text_secondary": "#8C8C8C",
        "border": "#D9D9D9",
        "background": "#F5F5F5",
        "surface": "#FFFFFF",
    },
    "spacing": {
        "xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32, "xxl": 48,
    },
    "typography": {
        "font_family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        "font_size_base": 14,
        "font_size_lg": 16,
        "font_size_sm": 12,
        "font_size_h1": 38,
        "font_size_h2": 30,
        "font_size_h3": 24,
        "font_weight_strong": 600,
    },
    "border_radius": {"sm": 2, "base": 4, "lg": 8, "round": 9999},
    "shadow": {
        "sm": "0 1px 2px 0 rgba(0,0,0,0.03)",
        "base": "0 1px 2px -2px rgba(0,0,0,0.16), 0 3px 6px 0 rgba(0,0,0,0.12)",
        "lg": "0 6px 16px -8px rgba(0,0,0,0.08), 0 9px 28px 0 rgba(0,0,0,0.05)",
    },
}

_MATERIAL_TOKENS: dict[str, Any] = {
    "colors": {
        "primary": "#1976D2",
        "secondary": "#9C27B0",
        "success": "#388E3C",
        "warning": "#F57C00",
        "danger": "#D32F2F",
        "surface": "#FAFAFA",
        "background": "#FFFFFF",
    },
    "spacing": {"unit": 8},
    "typography": {"font_family": "Roboto, sans-serif", "font_size_base": 16},
    "border_radius": {"base": 4},
    "shadow": {"1": "0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24)"},
}

# Component → token mapping (which tokens each component type consumes)
_COMPONENT_TOKEN_MAP: dict[str, list[str]] = {
    "button": ["colors.primary", "spacing.sm", "spacing.md",
               "border_radius.base", "typography.font_size_base"],
    "table": ["colors.border", "colors.surface", "colors.text_primary",
              "spacing.md", "typography.font_size_base", "shadow.base"],
    "form": ["colors.border", "colors.danger", "spacing.lg",
             "typography.font_size_base", "border_radius.base"],
    "card": ["colors.surface", "colors.border", "spacing.md",
             "border_radius.lg", "shadow.sm"],
    "input": ["colors.primary", "colors.border", "colors.danger",
              "spacing.sm", "border_radius.base"],
    "badge": ["colors.success", "colors.warning", "colors.danger", "colors.info",
              "border_radius.round"],
    "modal": ["colors.surface", "shadow.lg", "border_radius.lg", "spacing.xl"],
    "notification": ["colors.success", "colors.warning", "colors.danger",
                     "colors.info", "shadow.lg", "spacing.md"],
}


class DesignTokenMapper:
    """Map UI component patterns to concrete design token values.

    This is a synchronous method because token lookups involve no I/O.
    In production this might load a remote theme configuration at init time.
    """

    def map_to_tokens(self, components: list[dict],
                      token_system: str = "enterprise") -> dict:
        """Produce token assignments for every component in the list.

        Args:
            components: list of component dicts (from WireframeGenerator output).
                        Each dict has a ``component`` key (e.g. "data_table").
            token_system: "enterprise" (default) or "material".

        Returns:
            {tokens: <full token system dict>,
             component_tokens: {component_id: {token_path: value, ...}}}
        """
        logger.info("Mapping design tokens for %d components using system=%s",
                    len(components), token_system)

        tokens = _ENTERPRISE_TOKENS if token_system == "enterprise" else _MATERIAL_TOKENS
        component_tokens: dict[str, dict] = {}

        for comp in components:
            comp_type = comp.get("component", comp.get("type", "unknown"))
            comp_id = comp.get("page_id", "unknown") + "/" + comp.get("zone", comp_type)

            mapped = self._resolve(comp_type, tokens)
            component_tokens[comp_id] = mapped

        return {
            "tokens": tokens,
            "component_tokens": component_tokens,
            "token_system": token_system,
        }

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(comp_type: str, tokens: dict) -> dict[str, Any]:
        """Walk ``_COMPONENT_TOKEN_MAP`` to fetch concrete token values."""
        # Normalise: "data_table" -> "table", "action_button" -> "button"
        norm = comp_type.replace("data_", "").replace("action_", "").replace("search_", "input")
        paths = _COMPONENT_TOKEN_MAP.get(norm, _COMPONENT_TOKEN_MAP.get("card", []))

        resolved: dict[str, Any] = {}
        for path in paths:
            try:
                parts = path.split(".")
                value = tokens
                for p in parts:
                    value = value[p]
                resolved[path] = value
            except (KeyError, TypeError):
                logger.debug("Token path %s not found for component %s", path, norm)

        return resolved
