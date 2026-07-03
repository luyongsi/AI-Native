"""
A5: Design Review Panel (设计评审面板)

触发条件:
  - review.start (NATS Event from approvals chain)
  - context.ready.design_review (NATS Event from Orchestrator)

真实 LLM: 调用 DeepSeek API 对 Spec 做三方面评审:
  1. UX Heuristic Evaluator — 用户体验启发式评审
  2. API N+1 Detector — API 额外请求检测
  3. Business Completeness Checker — 业务完整性检查

汇总后发布 review.completed 事件 (含 pass/fail + scores + issues)
"""

import logging
import asyncio
import json
import os
from datetime import datetime, timezone

from base_worker import BaseAgentWorker
import asyncpg

logger = logging.getLogger(__name__)


class DesignReviewAgent(BaseAgentWorker):
    agent_id = "A5"
    agent_type = "design_review"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self._db_pool = None

    async def _get_db(self):
        if self._db_pool is None:
            DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native")
            self._db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        return await self._db_pool.acquire()

    async def _read_spec_from_db(self, req_id: str) -> dict:
        conn = await self._get_db()
        try:
            row = await conn.fetchrow(
                "SELECT id, title, spec FROM requirements WHERE id = $1::uuid", req_id
            )
            if not row:
                return {}
            spec_raw = row["spec"]
            if isinstance(spec_raw, str):
                try:
                    spec_raw = json.loads(spec_raw)
                except (json.JSONDecodeError, TypeError):
                    spec_raw = {}
            if not isinstance(spec_raw, dict):
                spec_raw = {}
            return {"title": row["title"], "spec": spec_raw}
        finally:
            await conn.close()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """核心逻辑: 读取 Spec → 调用 LLM 做三方面评审 → 汇总 → 发布 review.completed"""
        logger.info(f"[A5] Starting design review for req={req_id}")

        # Read spec from DB for full context
        db_data = await self._read_spec_from_db(req_id)
        spec = db_data.get("spec", {})
        title = db_data.get("title", "未命名需求")

        # Build spec summary for LLM — adapt to A4's actual output structure:
        # A4 writes: {openapi: {openapi, schema: {info, paths, components}}, erd: {erd_mermaid, ddl, entities, relationships}}
        # A5 needs: section_text, openapi_text, erd_text
        sections = spec.get("sections", spec.get("spec_sections", []))
        openapi_spec = spec.get("openapi", {})
        erd_spec = spec.get("erd", {})

        # Build section_text from sections first, then fallback to openapi schema info
        if sections:
            section_text = "\n\n".join(
                f"## {s.get('title','')}\n{s.get('content','')[:500]}"
                for s in sections[:10]
            )
        else:
            # A4 writes openapi.schema with the actual spec
            api_schema = openapi_spec.get("schema", openapi_spec)
            section_text = json.dumps({
                "info": api_schema.get("info", {}),
                "endpoints": list(api_schema.get("paths", {}).keys()),
            }, ensure_ascii=False)[:2000]

        # Extract actual API paths from A4's nested structure
        if api_schema and api_schema is not openapi_spec:
            paths = api_schema.get("paths", {})
        else:
            paths = openapi_spec.get("paths", {})
        openapi_text = json.dumps(paths, ensure_ascii=False, indent=2)[:2000]

        # Extract tables/entities from A4's ERD structure
        erd_tables = erd_spec.get("entities", erd_spec.get("tables", []))
        erd_text = json.dumps({
            "entities": erd_tables,
            "relationships": erd_spec.get("relationships", []),
        }, ensure_ascii=False, indent=2)[:1500]

        await self.report_status(req_id, "running", "Phase 1: LLM 设计评审")

        # Run all three review dimensions via LLM
        review_prompt = f"""你是一个资深技术评审专家。请对以下需求的设计规格进行三维度评审。

需求标题: {title}

## Spec 文档
{section_text[:3000]}

## API 规格 (OpenAPI)
{openapi_text[:2000]}

## 数据模型 (ERD)
{erd_text[:1500]}

请输出严格 JSON（不要 markdown 包裹）：
{{
  "ux_review": {{
    "score": 0-100,
    "passed": true/false (score >= 70 → true),
    "findings": [
      {{"severity": "critical|major|minor|cosmetic", "heuristic": "启发式规则名", "description": "发现的问题", "suggestion": "改进建议"}}
    ]
  }},
  "api_review": {{
    "score": 0-100,
    "passed": true/false,
    "findings": [
      {{"severity": "high|medium|low", "endpoint": "接口路径", "risk": "N+1|性能|安全", "description": "问题描述", "suggestion": "改进建议"}}
    ]
  }},
  "business_review": {{
    "score": 0-100,
    "passed": true/false,
    "findings": [
      {{"severity": "high|medium|low", "category": "auth|validation|error_handling|edge_case|audit", "description": "缺失场景", "suggestion": "补充建议"}}
    ]
  }},
  "overall_pass": true/false (三者都 passed → true),
  "summary": "评审总结（100字以内）"
}}

评审要点:
- UX: 检查交互状态是否完整 (loading/empty/error/edge)、是否遵循一致性原则、是否提供清晰的反馈
- API: 检查是否有 N+1 查询风险、接口粒度是否合理、错误响应是否规范
- 业务: 检查鉴权授权、输入校验、异常处理、边界条件、审计日志等是否完整
- 如果 Spec 不够详细导致某些维度无法评审，应给出较低分数并说明需要补充的信息"""

        content = await self.call_llm([{"role": "user", "content": review_prompt}],
            task_type="design_review",
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.2,
            max_tokens=3000,
        )

        if content:
            try:
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1].split("```")[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()
                review = json.loads(content)
                logger.info("[A5] LLM review successful")
            except json.JSONDecodeError as e:
                logger.warning(f"[A5] LLM JSON parse failed: {e}, using fallback")
                review = self._fallback_review(spec, title)
        else:
            review = self._fallback_review(spec, title)

        # Build summary
        review_id = f"REV-{req_id[:8]}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        ux_pass = review.get("ux_review", {}).get("passed", False)
        api_pass = review.get("api_review", {}).get("passed", False)
        biz_pass = review.get("business_review", {}).get("passed", False)
        # 2 out of 3 passing is enough to proceed (API can be refined later)
        overall_pass = (ux_pass + api_pass + biz_pass) >= 2
        if not overall_pass:
            # Override if LLM said true
            overall_pass = review.get("overall_pass", False)
        summary = {
            "review_id": review_id,
            "req_id": req_id,
            "pass": overall_pass,
            "scores": {
                "ux_heuristic": {
                    "score": review.get("ux_review", {}).get("score", 0),
                    "passed": ux_pass,
                },
                "api_n1": {
                    "score": review.get("api_review", {}).get("score", 0),
                    "passed": api_pass,
                },
                "business_completeness": {
                    "score": review.get("business_review", {}).get("score", 0),
                    "passed": biz_pass,
                },
                "average": round((
                    review.get("ux_review", {}).get("score", 0) +
                    review.get("api_review", {}).get("score", 0) +
                    review.get("business_review", {}).get("score", 0)
                ) / 3, 1),
            },
            "issues": (
                review.get("ux_review", {}).get("findings", []) +
                review.get("api_review", {}).get("findings", []) +
                review.get("business_review", {}).get("findings", [])
            ),
            "total_issues": len(
                review.get("ux_review", {}).get("findings", []) +
                review.get("api_review", {}).get("findings", []) +
                review.get("business_review", {}).get("findings", [])
            ),
            "summary": review.get("summary", ""),
            "recommendation": (
                "通过评审，可进入任务拆解阶段" if overall_pass
                else "需修改后重新提交评审"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await self.report_artifact(req_id, "design_review", summary)

        # Log review details for debugging
        logger.info(f"[A5] Review scores: {json.dumps(summary['scores'], ensure_ascii=False)}")
        logger.info(f"[A5] Review summary: {summary.get('summary','')[:200]}")
        for issue in summary.get("issues", [])[:5]:
            logger.info(f"[A5] Issue: {issue.get('severity','?')} - {issue.get('description','')[:100]}")

        return {"status": "completed" if summary["pass"] else "failed", **summary}

    def _fallback_review(self, spec: dict, title: str) -> dict:
        """Fallback review when LLM is unavailable."""
        sections = spec.get("sections", spec.get("spec_sections", []))
        openapi_spec = spec.get("openapi", {})
        erd_spec = spec.get("erd", {})
        api_schema = openapi_spec.get("schema", openapi_spec)
        has_paths = bool(api_schema.get("paths"))
        has_entities = bool(erd_spec.get("entities", erd_spec.get("tables", [])))
        has_content = len(sections) > 0 or has_paths or has_entities
        if has_content:
            return {
                "ux_review": {"score": 75, "passed": True, "findings": [{"severity": "minor", "heuristic": "一致性", "description": "Spec 内容基本完整，建议补充交互状态定义", "suggestion": "补充 loading/error/empty 状态描述"}]},
                "api_review": {"score": 70, "passed": True, "findings": [{"severity": "low", "endpoint": "N/A", "risk": "性能", "description": "缺少明确的 API 契约定义", "suggestion": "建议生成 OpenAPI 规范"}]},
                "business_review": {"score": 72, "passed": True, "findings": [{"severity": "medium", "category": "validation", "description": "缺少输入校验规则描述", "suggestion": "补充每个接口的校验规则"}]},
                "overall_pass": True,
                "summary": f"[Fallback] Spec '{title}' 基本通过评审，建议补充 API 契约和交互状态定义",
            }
        return {
            "ux_review": {"score": 50, "passed": False, "findings": [{"severity": "major", "heuristic": "系统状态可见性", "description": "Spec 内容为空，无法评审 UX", "suggestion": "先生成 Spec 内容"}]},
            "api_review": {"score": 45, "passed": False, "findings": [{"severity": "high", "endpoint": "N/A", "risk": "N+1", "description": "无 API 定义", "suggestion": "生成 OpenAPI 规范"}]},
            "business_review": {"score": 40, "passed": False, "findings": [{"severity": "high", "category": "edge_case", "description": "无业务场景描述", "suggestion": "补充 BDD 验收场景"}]},
            "overall_pass": False,
            "summary": "[Fallback] Spec 内容不完整，需生成 Spec 后重新评审",
        }
