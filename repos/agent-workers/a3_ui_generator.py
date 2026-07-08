"""
A3: UI Generator Agent (原型生成器)

Phase 5.2: 升级为真实 LLM — 调用 DeepSeek 生成 HTML 原型代码
触发: gate.0.approved (Gate 0 业务确认后)
产出: prototype HTML + artifact.produced

Phase 6: 支持标注热更新 — 监听 prototype.annotated 事件，生成增量代码
触发: prototype.annotated (前端标注原型后)
产出: incremental code patch + ui_code_patch artifact
"""
from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional
import asyncio
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)


class UIGeneratorAgent(BaseAgentWorker):
    agent_id = "A3"
    agent_type = "ui_generator"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self._original_specs: dict = {}  # Cache for original specs by req_id

    async def execute(self, req_id: str, context_package: dict) -> dict:
        # Priority: context_package.title/description → requirement_draft → requirement
        title = context_package.get("title", "")
        description = context_package.get("description", "")
        requirement = context_package.get("requirement", context_package.get("requirement_draft", {}))
        if not title and isinstance(requirement, dict):
            title = requirement.get("title", "") or requirement.get("req_title", "")
            description = requirement.get("description", requirement.get("summary", "")) or description
        if not title:
            title = "未命名需求"

        logger.info(f"[A3] Generating UI prototype for req={req_id}, title='{title}'")

        await self.report_status(req_id, "running", "Phase 1: 分析需求类型")

        # Compressed context from the 5-layer model
        context_str = await self.prepare_llm_context(context_package, state="designing")

        # Extract rework feedback from rework_context (set by Workflow)
        rework = context_package.get("rework_context") or {}
        rework_issues = rework.get("issues", [])
        if rework_issues:
            lines = ["\n\n【上一轮评审反馈 — 请重点修复以下问题】"]
            for issue in rework_issues[:10]:
                severity = issue.get("severity", "?")
                desc = issue.get("description", "")
                suggestion = issue.get("suggestion", "")
                lines.append(f"- [{severity}] {desc}")
                if suggestion:
                    lines.append(f"  修复建议: {suggestion}")
            context_str += "\n".join(lines)

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
{context_str}
要求:
1. 使用内联 CSS（无外部依赖），可直接在浏览器打开
2. 包含搜索/筛选、数据表格、操作按钮等常见后台组件
3. 响应式设计，浅色主题
4. 包含空状态占位
5. 如果提供了上一轮评审反馈，必须修复反馈中提到的 critical 和 major 级别问题

输出 JSON:
{{
  "html": "<完整 HTML 代码>",
  "description": "设计说明（30字）"
}}

只输出 JSON。HTML 必须是完整的独立页面。"""

        llm_content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="ui_prototype",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.4,
            max_tokens=4000,
        )

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

        return {
            "status": "completed",
            "prototype_size": len(html),
            "screens": len(screens),
            "source": "llm" if llm_content else "fallback",
            "html_preview": html[:5000],
        }

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

    async def init(self):
        """Initialize agent worker — connect to NATS, setup listeners."""
        await super().init()

        # Subscribe to annotation events
        try:
            if self.nc:
                await self.nc.subscribe("prototype.annotated.*", cb=self._on_annotation_event)
                logger.info("[A3] Subscribed to prototype.annotated.* events")
        except Exception as e:
            logger.warning(f"[A3] Failed to subscribe to annotation events: {e}")

    async def _on_annotation_event(self, msg):
        """Handle incoming annotation events from frontend."""
        try:
            data = json.loads(msg.data.decode())
            req_id = data.get("req_id")
            annotations = data.get("annotations", [])

            logger.info(f"[A3] Received annotation event for req={req_id} with {len(annotations)} annotations")

            if req_id:
                # Run annotation handling in background
                asyncio.create_task(self.handle_annotation_update(req_id, annotations))
        except Exception as e:
            logger.error(f"[A3] Error handling annotation event: {e}")

    async def handle_annotation_update(self, req_id: str, annotations: list) -> dict:
        """
        Process annotation updates and generate incremental UI code.

        Flow:
        1. Parse annotations to extract UI requirements
        2. Generate incremental code via LLM
        3. Publish code artifact via activity stream
        """
        await self.report_status(req_id, "running", "Phase 1: 解析标注")

        try:
            # Parse annotations
            ui_requirements = self._parse_annotations(annotations)
            logger.info(f"[A3] Parsed annotations: {len(ui_requirements['components'])} components, "
                       f"{len(ui_requirements['interactions'])} interactions, "
                       f"{len(ui_requirements['data_bindings'])} data bindings")

            await self.report_progress(req_id, "parsing_annotations", 0.3)

            # Generate code from annotations
            await self.report_status(req_id, "running", "Phase 2: 生成代码")
            code = await self._generate_from_annotations(ui_requirements, req_id)

            await self.report_progress(req_id, "generating_code", 0.7)

            # Publish code artifact
            await self.report_artifact(req_id, "ui_code_patch", {
                "code": code,
                "type": "tsx",
                "components_count": len(ui_requirements['components']),
                "generated_from_annotations": True,
            })

            await self.report_status(req_id, "completed", "标注代码生成完成")
            logger.info(f"[A3] Completed code generation for req={req_id}")

            return {"status": "completed", "code_length": len(code)}

        except Exception as e:
            logger.error(f"[A3] Error handling annotation update: {e}", exc_info=True)
            await self.report_status(req_id, "failed", f"标注处理失败: {str(e)}")
            return {"status": "failed", "error": str(e)}

    def _parse_annotations(self, annotations: list) -> dict:
        """Parse annotations into structured UI requirements."""
        ui_requirements = {
            'components': [],
            'interactions': [],
            'data_bindings': []
        }

        for ann in annotations:
            if ann.get('type') == 'component':
                ui_requirements['components'].append({
                    'id': ann.get('id'),
                    'name': ann.get('label', 'Untitled'),
                    'position': {'x': ann.get('x', 0), 'y': ann.get('y', 0)},
                    'size': {'width': ann.get('width', 100), 'height': ann.get('height', 50)},
                    'properties': ann.get('properties', {}),
                })
            elif ann.get('type') == 'interaction':
                ui_requirements['interactions'].append(ann)
            elif ann.get('type') == 'data-binding':
                ui_requirements['data_bindings'].append(ann)

        return ui_requirements

    async def _generate_from_annotations(self, ui_requirements: dict, req_id: str) -> str:
        """Generate React component code from parsed annotations."""
        components_desc = "\n".join([
            f"- {c['name']} at ({c['position']['x']}, {c['position']['y']}), "
            f"size {c['size']['width']}x{c['size']['height']}"
            for c in ui_requirements['components']
        ])

        prompt = f"""你是资深 React 开发者。根据以下 UI 标注生成 React 组件代码。

标注的组件:
{components_desc}

交互: {len(ui_requirements['interactions'])} 个
数据绑定: {len(ui_requirements['data_bindings'])} 个

要求:
1. 生成完整的 React .tsx 代码
2. 使用 TypeScript + React Hooks
3. 包含所有标注的组件
4. 使用 Tailwind CSS 样式
5. 添加必要的交互逻辑

输出只需要 React 组件代码，不需要 JSON 包装。"""

        # Try LLM generation
        llm_content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="ui_prototype",
            req_id=req_id,
            workflow_id="",
            temperature=0.4,
            max_tokens=4000,
        )

        if llm_content:
            try:
                code = llm_content.strip()
                if code.startswith("```"):
                    code = code.split("```")[1]
                    if code.startswith("tsx") or code.startswith("typescript"):
                        code = code.split("\n", 1)[1] if "\n" in code else code
                    code = code.rsplit("```", 1)[0]
                logger.info(f"[A3] Generated code from annotations ({len(code)} chars)")
                return code
            except Exception as e:
                logger.warning(f"[A3] Failed to parse LLM code response: {e}")

        # Fallback code
        return self._fallback_component_code()

    def _fallback_component_code(self) -> str:
        """Generate fallback component code."""
        return '''import React, { useState } from 'react';

interface ComponentProps {
  // Props from annotations
}

export default function GeneratedComponent(props: ComponentProps) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);

  const handleLoad = async () => {
    setLoading(true);
    try {
      // Data loading logic
      setData([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full h-full p-6 bg-white rounded-lg shadow">
      <h1 className="text-2xl font-bold mb-4">Generated Component</h1>

      <div className="mb-4">
        <button
          onClick={handleLoad}
          disabled={loading}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Load Data'}
        </button>
      </div>

      {/* Components from annotations would render here */}
      <div className="space-y-2">
        {data.map((item: any) => (
          <div key={item.id} className="p-2 border border-gray-200 rounded">
            {JSON.stringify(item)}
          </div>
        ))}
      </div>
    </div>
  );
}
'''

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
