"""
A4 Sub-module: Spec Generator

LLM-driven structured technical specification document generator.
Produces a 6-chapter spec: overview, functional spec, state machine design,
API design, data model, non-functional requirements.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger(__name__)


class SpecGenerator:
    """LLM-driven structured technical spec document generator."""

    def __init__(self, llm_caller: Callable | None = None):
        self._llm = llm_caller
        self._context: Dict[str, Any] = {}

    async def generate(
        self,
        draft: dict,
        feasibility: dict,
        prototype_url: str,
        domain: str,
        revision_context: dict | None = None,
    ) -> dict:
        """Generate a 6-chapter structured spec document.

        Returns a dict matching the spec_doc JSON schema from the data dictionary.
        """
        self._context = {
            "draft": draft,
            "feasibility": feasibility,
            "prototype_url": prototype_url,
            "domain": domain,
        }

        title = draft.get("title", "未命名需求")
        logger.info(f"Generating spec doc for title={title}, domain={domain}")

        prompt = self._build_prompt(draft, feasibility, prototype_url,
                                    domain, revision_context)

        result = await self._call_llm(prompt, task_type="openapi_gen",
                                      temperature=0.3, max_tokens=6000)
        if not result:
            logger.warning("Spec LLM call failed, using fallback")
            return self._generate_fallback(draft)

        spec = self._parse_response(result)
        if spec is None:
            return self._generate_fallback(draft)

        spec.setdefault("title", title)
        spec.setdefault("version", "1.0")
        spec.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
        return spec

    def _build_prompt(
        self,
        draft: dict,
        feasibility: dict,
        prototype_url: str,
        domain: str,
        revision_context: dict | None,
    ) -> str:
        title = draft.get("title", "未命名需求")
        description = draft.get("description", draft.get("summary", ""))
        entities = draft.get("entities", [])
        use_cases = draft.get("use_cases", [])
        acceptance_criteria = draft.get("acceptance_criteria", [])
        constraints = draft.get("constraints", [])
        risks = draft.get("risks", [])

        feasibility_text = json.dumps(feasibility, ensure_ascii=False)[:1500]
        entities_text = json.dumps(entities, ensure_ascii=False)[:1500]
        use_cases_text = json.dumps(use_cases, ensure_ascii=False)[:1500]
        criteria_text = "\n".join(acceptance_criteria[:10]) if acceptance_criteria else "（待定义）"
        constraints_text = "\n".join(constraints[:10]) if constraints else "（无特殊约束）"
        risks_text = "\n".join(risks[:10]) if risks else "（未识别明显风险）"

        revision_text = ""
        if revision_context and revision_context.get("is_revision"):
            rejection = revision_context.get("gate1_rejection", {})
            revision_text = "\n\n【Gate1 打回修订要求】\n"
            for reason in rejection.get("reject_reasons", []):
                revision_text += f"- [{reason.get('category', '?')}] {reason.get('description', '')}\n"
            revision_text += f"\n修订指引: {rejection.get('revision_guidance', '')}\n"

            prev_report = revision_context.get("previous_a5_report", {})
            if prev_report:
                revision_text += "\n【A5 检查报告中需优先修复的问题】\n"
                for dim in prev_report.get("dimensions", []):
                    for issue in dim.get("issues", []):
                        if issue.get("severity") in ("critical", "major"):
                            revision_text += (
                                f"- [{issue['severity']}] {dim.get('label', '')}: "
                                f"{issue.get('description', '')}\n"
                            )
                            if issue.get("suggestion"):
                                revision_text += f"  建议: {issue['suggestion']}\n"

        prompt = f"""你是资深系统架构师。根据需求草案和可行性分析，生成一份结构化的技术规格说明书。

【需求信息】
标题: {title}
领域: {domain}
描述: {description}

实体定义: {entities_text}

用例列表: {use_cases_text}

验收标准: {criteria_text}

约束条件: {constraints_text}

风险: {risks_text}

原型参考: {prototype_url or '（无原型）'}

可行性分析: {feasibility_text}
{revision_text}

请生成严格 JSON（不要 markdown 包裹），结构如下:
{{
  "title": "系统名称技术规格",
  "version": "1.0",
  "overview": "系统概述（200字以内）",
  "modules": [
    {{
      "name": "模块名称",
      "description": "模块功能描述",
      "states": ["state1", "state2"],
      "state_machine": {{
        "states": ["list", "detail", "edit", "create"],
        "transitions": [
          {{"from": "list", "to": "detail", "trigger": "点击行"}},
          {{"from": "list", "to": "create", "trigger": "点击新建"}}
        ]
      }}
    }}
  ],
  "data_models": [
    {{
      "name": "EntityName",
      "fields": [
        {{"name": "id", "type": "UUID", "nullable": false, "primary_key": true}},
        {{"name": "name", "type": "VARCHAR(100)", "nullable": false}}
      ]
    }}
  ],
  "api_endpoints": [
    {{
      "method": "GET",
      "path": "/api/resource",
      "summary": "查询资源列表",
      "parameters": [],
      "responses": [{{"status": 200, "description": "成功"}}]
    }}
  ],
  "non_functional": {{
    "performance": "性能要求描述",
    "security": "安全要求描述",
    "audit": "审计日志要求",
    "idempotency": "幂等性要求"
  }}
}}

要求:
1. modules 至少 2 个模块，每个模块含完整状态机（至少 3 个状态 + 3 条转换）
2. data_models 至少 2 个实体，每个实体至少 4 个字段
3. api_endpoints 至少覆盖所有 use_cases
4. non_functional 四个维度都要填写
5. 如果提供了 Gate1 修订要求，优先修复 critical 和 major 级别问题"""
        return prompt

    def _parse_response(self, response: str) -> dict | None:
        content = response.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
        if content.startswith("json"):
            content = content[4:].strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse spec LLM response: {e}")
            return None

    def _generate_fallback(self, draft: dict) -> dict:
        title = draft.get("title", "未命名需求")
        domain = draft.get("domain", "general")
        entities = draft.get("entities", [])
        use_cases = draft.get("use_cases", [])

        data_models = []
        for entity in entities[:5]:
            fields = [{"name": "id", "type": "UUID", "nullable": False,
                       "primary_key": True}]
            for attr in entity.get("attributes", [])[:8]:
                fields.append({"name": attr, "type": "VARCHAR(255)",
                               "nullable": True})
            data_models.append({"name": entity.get("name", "Record"),
                                "fields": fields})

        if not data_models:
            data_models = [{
                "name": f"{domain}_record",
                "fields": [
                    {"name": "id", "type": "UUID", "nullable": False,
                     "primary_key": True},
                    {"name": "title", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "created_at", "type": "TIMESTAMPTZ",
                     "nullable": False},
                    {"name": "updated_at", "type": "TIMESTAMPTZ",
                     "nullable": False},
                ],
            }]

        api_endpoints = []
        for uc in use_cases[:8]:
            api_endpoints.append({
                "method": "POST",
                "path": f"/api/{domain.lower()}",
                "summary": uc if isinstance(uc, str) else uc.get("name", ""),
                "parameters": [],
                "responses": [{"status": 200, "description": "成功"}],
            })

        return {
            "title": title,
            "version": "1.0",
            "overview": f"{title}系统的技术规格说明书（降级生成）",
            "modules": [{
                "name": f"{title}模块",
                "description": "核心业务模块",
                "states": ["list", "detail", "edit", "create"],
                "state_machine": {
                    "states": ["list", "detail", "edit", "create"],
                    "transitions": [
                        {"from": "list", "to": "detail", "trigger": "点击行"},
                        {"from": "list", "to": "create", "trigger": "点击新建"},
                        {"from": "detail", "to": "edit", "trigger": "点击编辑"},
                    ],
                },
            }],
            "data_models": data_models,
            "api_endpoints": api_endpoints or [{
                "method": "GET", "path": f"/api/{domain.lower()}",
                "summary": "查询列表", "parameters": [],
                "responses": [{"status": 200, "description": "成功"}],
            }],
            "non_functional": {
                "performance": "API 响应时间 < 500ms (P95)",
                "security": "所有接口需 Bearer Token 认证",
                "audit": "增删改操作记录审计日志",
                "idempotency": "写操作支持幂等键",
            },
            "source": "fallback",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _call_llm(self, prompt: str, **kwargs) -> str | None:
        if self._llm is None:
            logger.warning("No LLM caller injected, spec generation skipped")
            return None
        try:
            return await self._llm([{"role": "user", "content": prompt}], **kwargs)
        except Exception as e:
            logger.error(f"Spec LLM call failed: {e}")
            return None
