"""
wireframe/generator.py — Low-Fidelity Wireframe Generator

Produces a tree of pages and components from a structured requirement dict.
Real implementation would call a design-to-code LLM (e.g. Claude with
structured output / tool-use) and render via a sandbox preview endpoint.

Contract:
    class WireframeGenerator
        async generate(requirement: dict) -> dict
        -> {type: "low_fidelity", pages: [...], components: [...]}
"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------- component catalogue (mock) ----------

COMPONENT_TEMPLATES = {
    "data_table": {
        "type": "table",
        "props": {"columns": 4, "sortable": True, "paginated": True, "selectable": True},
    },
    "search_bar": {
        "type": "input",
        "props": {"placeholder": "搜索...", "debounce": 300, "clearable": True},
    },
    "action_button": {
        "type": "button",
        "props": {"variant": "primary", "label": "操作", "icon": "plus"},
    },
    "form_group": {
        "type": "form",
        "props": {"fields": 3, "layout": "horizontal", "submit_label": "提交"},
    },
    "detail_card": {
        "type": "card",
        "props": {"title": "详情", "collapsible": True, "bordered": True},
    },
    "status_badge": {
        "type": "badge",
        "props": {"colors": ["success", "warning", "error", "info"], "animated": False},
    },
}

PAGE_TEMPLATES = {
    "list": {"route": "/list", "title": "列表页", "zones": ["toolbar", "filter", "table", "pagination"]},
    "detail": {"route": "/detail/:id", "title": "详情页", "zones": ["header", "content", "sidebar"]},
    "form": {"route": "/form", "title": "表单页", "zones": ["steps", "fields", "actions"]},
    "dashboard": {"route": "/dashboard", "title": "仪表盘", "zones": ["stats", "charts", "feeds"]},
}


class WireframeGenerator:
    """Generate a low-fidelity wireframe from a structured requirement.

    The output is a declarative JSON tree that the A3 UI Generator can
    consume to produce real React/Vue code.
    """

    async def generate(self, requirement: dict) -> dict:
        """Build wireframe pages and component assignments.

        Args:
            requirement: dict with at least ``title`` and ``domain`` keys.

        Returns:
            dict with ``type``, ``pages``, and ``components``.
        """
        logger.info("Generating wireframe for '%s'", requirement.get("title", "")[:60])

        domain = requirement.get("domain", "general")
        title = requirement.get("title", "")
        entities = requirement.get("entities", {})

        pages = self._infer_pages(title, domain)
        components = self._assign_components(pages, entities)

        return {
            "type": "low_fidelity",
            "pages": pages,
            "components": components,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------

    def _infer_pages(self, title: str, domain: str) -> list[dict]:
        """Heuristic page inference from title keywords."""
        pages: list[dict] = []

        # Every wireframe gets at least a list page
        pages.append({**PAGE_TEMPLATES["list"], "id": str(uuid.uuid4())[:8]})

        if any(kw in title for kw in ("详情", "查看", "明细")):
            pages.append({**PAGE_TEMPLATES["detail"], "id": str(uuid.uuid4())[:8]})
        if any(kw in title for kw in ("创建", "新建", "编辑", "修改")):
            pages.append({**PAGE_TEMPLATES["form"], "id": str(uuid.uuid4())[:8]})
        if any(kw in title for kw in ("仪表盘", "统计", "报表", "概览")):
            pages.append({**PAGE_TEMPLATES["dashboard"], "id": str(uuid.uuid4())[:8]})

        return pages

    def _assign_components(self, pages: list, entities: dict) -> list[dict]:
        """Map each page zone to appropriate mock components."""
        components: list[dict] = []
        for page in pages:
            for zone in page.get("zones", []):
                comp_ref = None
                if zone in ("table", "pagination"):
                    comp_ref = "data_table"
                elif zone == "filter":
                    comp_ref = "search_bar"
                elif zone == "toolbar":
                    comp_ref = "action_button"
                elif zone == "fields":
                    comp_ref = "form_group"
                elif zone in ("content", "header", "sidebar"):
                    comp_ref = "detail_card"
                elif zone == "stats":
                    comp_ref = "status_badge"
                if comp_ref:
                    components.append({
                        "page_id": page["id"],
                        "zone": zone,
                        "component": comp_ref,
                        **COMPONENT_TEMPLATES[comp_ref],
                    })
        return components
