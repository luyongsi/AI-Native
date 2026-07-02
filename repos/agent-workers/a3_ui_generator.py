"""
A3: UI Generator Agent (原型生成器)

Phase 5.2: 升级为真实 LLM — 调用 DeepSeek 生成 HTML 原型代码
触发: gate.0.approved (Gate 0 业务确认后)
产出: prototype HTML + artifact.produced
"""
from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")


class UIGeneratorAgent(BaseAgentWorker):
    agent_id = "A3"
    agent_type = "ui_generator"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)

    async def _call_llm(self, messages: list, temperature: float = 0.4) -> str | None:
        if not DEEPSEEK_API_KEY:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                    json={"model": DEEPSEEK_MODEL, "messages": messages, "temperature": temperature, "max_tokens": 4000},
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"[A3] LLM call failed: {e}")
            return None

    async def execute(self, req_id: str, context_package: dict) -> dict:
        requirement = context_package.get("requirement", context_package.get("requirement_draft", {}))
        title = requirement.get("title", context_package.get("title", "未命名需求"))
        description = requirement.get("description", requirement.get("summary", ""))

        logger.info(f"[A3] Generating UI prototype for req={req_id}, title='{title}'")

        await self.report_status(req_id, "running", "Phase 1: 分析需求类型")

        # Try LLM generation
        html = None
        screens = [
            {"name": "default", "description": "默认状态"},
            {"name": "hover", "description": "交互悬停态"},
            {"name": "empty", "description": "空数据状态"},
            {"name": "error", "description": "错误/异常状态"},
        ]

        prompt = f"""你是资深 UI/UX 设计师。根据需求生成一个可直接预览的 HTML 原型页面。

需求标题: {title}
需求描述: {description or title}
业务领域: {requirement.get('domain', 'general')}

要求:
1. 使用内联 CSS（无外部依赖），可直接在浏览器打开
2. 包含搜索/筛选、数据表格、操作按钮等常见后台组件
3. 响应式设计，浅色主题
4. 包含空状态占位

输出 JSON:
{{
  "html": "<完整 HTML 代码>",
  "description": "设计说明（30字）"
}}

只输出 JSON。HTML 必须是完整的独立页面。"""

        llm_content = await self._call_llm([{"role": "user", "content": prompt}], temperature=0.4)

        if llm_content:
            try:
                content = llm_content.strip()
                if content.startswith("```"): content = content.split("```")[1].split("```")[0].strip()
                if content.startswith("json"): content = content[4:].strip()
                result = json.loads(content)
                html = result.get("html", "")
                logger.info(f"[A3] LLM generated prototype HTML ({len(html)} chars)")
            except (json.JSONDecodeError, KeyError):
                logger.warning("[A3] LLM JSON parse failed, using fallback")
                html = None

        if not html:
            html = self._fallback_html(req_id, title)

        await self.report_status(req_id, "running", "Phase 2: 发布原型")
        await self._publish_prototype(req_id, html, screens)

        await self.report_artifact(req_id, "prototype", {
            "title": title,
            "html": html[:5000],
            "screens": screens,
            "source": "llm" if llm_content else "fallback",
        })

        return {"status": "completed", "prototype_size": len(html), "screens": len(screens),
                "source": "llm" if llm_content else "fallback"}

    async def _publish_prototype(self, req_id: str, html: str, screens: list):
        payload = {
            "agent_id": self.agent_id,
            "req_id": req_id,
            "html": html[:20000],
            "screens": screens,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.nc.publish(f"prototype.generated.{req_id}", json.dumps(payload, ensure_ascii=False).encode())
        logger.info(f"[A3] Published prototype.generated for req={req_id}")

    def _fallback_html(self, req_id: str, title: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f5f5f5; }}
.header {{ background:#fff; padding:16px 24px; border-bottom:1px solid #e8e8e8; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:18px; color:#333; }}
.btn {{ padding:8px 16px; border:none; border-radius:6px; cursor:pointer; font-size:13px; }}
.btn-primary {{ background:#1890ff; color:#fff; }}
.btn-success {{ background:#52c41a; color:#fff; }}
.container {{ max-width:1200px; margin:24px auto; padding:0 24px; }}
.card {{ background:#fff; border-radius:8px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.search-bar {{ display:flex; gap:12px; margin-bottom:16px; }}
.search-bar input {{ flex:1; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:13px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ background:#fafafa; padding:12px; text-align:left; font-size:12px; color:#666; border-bottom:2px solid #e8e8e8; }}
td {{ padding:12px; font-size:13px; border-bottom:1px solid #f0f0f0; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; }}
.tag-active {{ background:#e6f7ff; color:#1890ff; }}
.tag-done {{ background:#f6ffed; color:#52c41a; }}
.empty {{ text-align:center; padding:40px; color:#999; font-size:13px; }}
</style></head>
<body>
<div class="header"><h1>{title}</h1><button class="btn btn-primary">+ 新建</button></div>
<div class="container">
  <div class="card">
    <div class="search-bar">
      <input type="text" placeholder="搜索...">
      <button class="btn btn-primary">查询</button>
    </div>
    <table>
      <thead><tr><th>ID</th><th>名称</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
      <tbody>
        <tr><td>1</td><td>示例数据</td><td><span class="tag tag-active">进行中</span></td><td>2026-07-01</td><td><a href="#">编辑</a> <a href="#" style="color:#ff4d4f;">删除</a></td></tr>
      </tbody>
    </table>
    <div class="empty" style="display:none;">暂无数据</div>
  </div>
</div>
</body></html>"""
