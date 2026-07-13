"""
A1 Wireframe — WireframeGenerator: Low-fidelity wireframe generation.

LLM-driven with heuristic fallback when API key is unavailable.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")

WIREFRAME_PROMPT = """你是一个UI/UX设计师。请基于以下需求草案，生成低保真线框图的JSON描述。

线框图应该包含：
1. pages：页面列表，每个页面有 id, route, title, zones(功能区域列表)
2. components：组件列表，每个组件有 page_id, zone, component(组件类型), props(属性)

支持的组件类型：table, input, button, form, card, badge

需求草案:
__DRAFT__

请只输出 JSON，不要 markdown 代码块包裹:
{"type": "low_fidelity", "pages": [{"id": "...", "route": "/...", "title": "...", "zones": ["..."]}], "components": [{"page_id": "...", "zone": "...", "component": "...", "props": {...}}]}"""

# ---------- heuristic templates ----------
COMPONENT_TEMPLATES = {
    "data_table": {"type": "table", "props": {"columns": 4, "sortable": True, "paginated": True, "selectable": True}},
    "search_bar": {"type": "input", "props": {"placeholder": "搜索...", "debounce": 300, "clearable": True}},
    "action_button": {"type": "button", "props": {"variant": "primary", "label": "操作", "icon": "plus"}},
    "form_group": {"type": "form", "props": {"fields": 3, "layout": "horizontal", "submit_label": "提交"}},
    "detail_card": {"type": "card", "props": {"title": "详情", "collapsible": True, "bordered": True}},
    "status_badge": {"type": "badge", "props": {"colors": ["success", "warning", "error", "info"], "animated": False}},
}

PAGE_TEMPLATES = {
    "list": {"route": "/list", "title": "列表页", "zones": ["toolbar", "filter", "table", "pagination"]},
    "detail": {"route": "/detail/:id", "title": "详情页", "zones": ["header", "content", "sidebar"]},
    "form": {"route": "/form", "title": "表单页", "zones": ["steps", "fields", "actions"]},
    "dashboard": {"route": "/dashboard", "title": "仪表盘", "zones": ["stats", "charts", "feeds"]},
}


class WireframeGenerator:
    """Generates low-fidelity wireframe JSON from a requirement draft."""

    def __init__(self):
        self.model = DEEPSEEK_MODEL
        self.base_url = DEEPSEEK_BASE_URL
        self.api_key = DEEPSEEK_API_KEY

    async def generate(self, draft: dict) -> dict:
        """Generate wireframe JSON.

        Returns:
            {"type": "low_fidelity", "pages": [...], "components": [...]}
        """
        if not self.api_key:
            return self._heuristic_generate(draft)

        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        prompt = WIREFRAME_PROMPT.replace("__DRAFT__", draft_text)

        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "system", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 2048,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return self._parse_response(content, draft)
        except Exception:
            logger.exception("WireframeGenerator LLM call failed")
            return self._heuristic_generate(draft)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_response(content: str, _draft: dict) -> dict:
        try:
            result = json.loads(content.strip())
            if isinstance(result, dict) and "pages" in result:
                return {"type": "low_fidelity", **result}
        except json.JSONDecodeError:
            pass
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, dict) and "pages" in result:
                    return {"type": "low_fidelity", **result}
            except json.JSONDecodeError:
                pass
        return {"type": "low_fidelity", "pages": [], "components": []}

    @staticmethod
    def _heuristic_generate(draft: dict) -> dict:
        title = draft.get("title", "")
        entities = draft.get("entities", [])

        pages = []
        pages.append({**PAGE_TEMPLATES["list"], "id": str(uuid.uuid4())[:8]})
        if any(kw in title for kw in ("详情", "查看", "明细")):
            pages.append({**PAGE_TEMPLATES["detail"], "id": str(uuid.uuid4())[:8]})
        if any(kw in title for kw in ("创建", "新建", "编辑", "修改")):
            pages.append({**PAGE_TEMPLATES["form"], "id": str(uuid.uuid4())[:8]})
        if any(kw in title for kw in ("仪表盘", "统计", "报表", "概览")):
            pages.append({**PAGE_TEMPLATES["dashboard"], "id": str(uuid.uuid4())[:8]})

        components = []
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

        return {
            "type": "low_fidelity",
            "pages": pages,
            "components": components,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
