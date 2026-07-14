"""
A5: Design Review Agent (自动设计检查)

Stage 2: Non-blocking automated design review.
Performs 5 independent dimensional checks on A3 prototype + A4 spec.

Trigger: context.ready.A5 (NATS from Orchestrator after A4 completes or is skipped)

Five dimensions (sequential, 3min timeout each):
  1. api_consistency — OpenAPI vs Spec endpoint alignment
  2. erd_completeness — ERD entity/field coverage
  3. state_machine_closure — state reachability and exit
  4. prototype_spec_alignment — prototype screens vs use cases
  5. security_baseline — auth schemes, PII labeling, HTTPS

Non-blocking: always produces a report, never returns pass/fail.
A4-missing mode: only prototype_spec_alignment runs, rest skipped.
Dimension-level degradation: single dim timeout → skip that dim.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

# Dimension definitions with weights
DIMENSIONS = [
    {"key": "api_consistency",        "label": "API 一致性",
     "weight": 0.25, "timeout_s": 180},
    {"key": "erd_completeness",       "label": "ERD 完整性",
     "weight": 0.25, "timeout_s": 180},
    {"key": "state_machine_closure",  "label": "状态机闭合性",
     "weight": 0.20, "timeout_s": 180},
    {"key": "prototype_spec_alignment", "label": "原型-Spec 对齐",
     "weight": 0.15, "timeout_s": 180},
    {"key": "security_baseline",      "label": "安全基线",
     "weight": 0.15, "timeout_s": 180},
]


class DesignReviewAgent(BaseAgentWorker):
    agent_id = "A5"
    agent_type = "design_review"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self._db_pool = None

    async def _get_db(self):
        if self._db_pool is None:
            DATABASE_URL = os.environ.get(
                "DATABASE_URL",
                "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
            )
            self._db_pool = await asyncpg.create_pool(
                DATABASE_URL, min_size=1, max_size=3,
            )
        return await self._db_pool.acquire()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """Five-dimension design review — non-blocking, always produces a report."""
        logger.info(f"[A5] Starting design review for req={req_id}")

        a3_output = context_package.get("a3_output", {})
        a4_output = context_package.get("a4_output", {})
        cycle = context_package.get("cycle", 0)
        a4_missing = a4_output.get("a4_missing", False)

        logger.info(f"[A5] a4_missing={a4_missing}")

        if a4_missing:
            return await self._check_prototype_only(req_id, cycle, a3_output)

        # Run all 5 dimensions sequentially (no external deps, fast enough)
        dimensions = []
        total_weight = 0.0
        weighted_sum = 0.0

        for dim in DIMENSIONS:
            try:
                result = await asyncio.wait_for(
                    self._run_dimension(dim["key"], a3_output, a4_output,
                                        context_package),
                    timeout=dim["timeout_s"],
                )
                if result.get("score") is not None:
                    weighted_sum += result["score"] * dim["weight"]
                    total_weight += dim["weight"]
                dimensions.append(result)
            except asyncio.TimeoutError:
                logger.warning(f"[A5] Dimension {dim['key']} timed out, skipping")
                dimensions.append({
                    "dimension": dim["key"],
                    "label": dim["label"],
                    "score": None,
                    "status": "skipped",
                    "skip_reason": "llm_timeout",
                    "issues": [],
                })

        overall_score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
        total_issues = sum(len(d.get("issues", [])) for d in dimensions)

        # Build report
        check_report = {
            "overall_score": overall_score,
            "total_issues": total_issues,
            "dimensions": dimensions,
            "summary": self._generate_summary(dimensions, overall_score),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist to agent_results
        await self._persist_result(req_id, cycle, check_report)

        # Report artifact
        await self.report_artifact(req_id, "design_review", {
            "check_report": check_report,
            "non_blocking": True,
        })

        logger.info(
            f"[A5] Review complete: overall={overall_score}, "
            f"issues={total_issues}, skipped={sum(1 for d in dimensions if d.get('status') == 'skipped')}"
        )

        return {
            "status": "completed",
            "check_report": check_report,
            "non_blocking": True,
        }

    # ── Dimension runners ───────────────────────────────────────────────

    async def _run_dimension(
        self, key: str, a3: dict, a4: dict, context_package: dict,
    ) -> dict:
        """Run a single dimension check via LLM."""
        runner_map = {
            "api_consistency": self._check_api_consistency,
            "erd_completeness": self._check_erd_completeness,
            "state_machine_closure": self._check_state_machine_closure,
            "prototype_spec_alignment": self._check_prototype_alignment,
            "security_baseline": self._check_security_baseline,
        }
        runner = runner_map.get(key)
        if runner is None:
            return {
                "dimension": key, "label": key, "score": None,
                "status": "skipped", "skip_reason": "unknown_dimension",
                "issues": [],
            }
        return await runner(a3, a4, context_package)

    async def _check_api_consistency(
        self, a3: dict, a4: dict, ctx: dict,
    ) -> dict:
        """Check OpenAPI alignment with Spec API endpoints."""
        spec_doc = a4.get("spec_doc", {})
        openapi_schema = a4.get("openapi_schema", {})

        spec_endpoints = json.dumps(
            spec_doc.get("api_endpoints", []), ensure_ascii=False,
        )[:2000]
        openapi_paths = json.dumps(
            list(openapi_schema.get("paths", {}).keys()),
            ensure_ascii=False,
        )[:1000]

        prompt = f"""你是 API 设计审查专家。检查 OpenAPI 规范是否与 Spec 中的接口定义一致。

Spec 中定义的 API 端点:
{spec_endpoints}

OpenAPI paths:
{openapi_paths}

请输出严格 JSON:
{{
  "score": 0-100,
  "issues": [
    {{"severity": "critical|major|minor|info", "description": "问题描述",
      "suggestion": "改进建议", "location": "openapi_schema.paths./xxx"}}
  ]
}}

检查要点:
- Spec 中定义的 API 在 OpenAPI paths 中是否都有对应（Endpoint 覆盖）
- 每个 endpoint 是否定义了成功和错误响应 schema（响应定义）
- 是否使用了统一的错误码格式（错误码规范）
- 是否有 N+1 查询风险（批量接口 vs 单条循环调用）
- POST/PUT 操作是否有 requestBody 定义"""
        return await self._llm_check("api_consistency", "API 一致性", prompt, ctx)

    async def _check_erd_completeness(
        self, a3: dict, a4: dict, ctx: dict,
    ) -> dict:
        """Check ERD coverage of Spec data models."""
        spec_doc = a4.get("spec_doc", {})
        erd = a4.get("erd_diagram", {})

        data_models = json.dumps(
            spec_doc.get("data_models", []), ensure_ascii=False,
        )[:2000]
        entities = json.dumps(
            erd.get("entities", []), ensure_ascii=False,
        )[:1500]
        relationships = json.dumps(
            erd.get("relationships", []), ensure_ascii=False,
        )[:1000]

        prompt = f"""你是数据库设计审查专家。检查 ERD 是否覆盖 Spec 数据模型中的所有业务实体。

Spec 数据模型:
{data_models}

ERD 实体:
{entities}

ERD 关系:
{relationships}

请输出严格 JSON:
{{
  "score": 0-100,
  "issues": [
    {{"severity": "critical|major|minor|info", "description": "问题描述",
      "suggestion": "改进建议", "location": "erd.entities"}}
  ]
}}

检查要点:
- Spec data_models 中的实体在 ERD entities 中是否都有对应
- 每个实体的所有字段是否都有类型/约束定义
- 每个实体是否定义了主键
- 实体间的引用关系是否在 relations 中声明"""
        return await self._llm_check("erd_completeness", "ERD 完整性", prompt, ctx)

    async def _check_state_machine_closure(
        self, a3: dict, a4: dict, ctx: dict,
    ) -> dict:
        """Check state machine closure — all states reachable and exit-able."""
        spec_doc = a4.get("spec_doc", {})

        state_machines = []
        for mod in spec_doc.get("modules", []):
            sm = mod.get("state_machine", {})
            if sm:
                state_machines.append({
                    "module": mod.get("name", "unknown"),
                    "states": sm.get("states", []),
                    "transitions": sm.get("transitions", []),
                })

        if not state_machines:
            return {
                "dimension": "state_machine_closure",
                "label": "状态机闭合性",
                "score": None,
                "status": "skipped",
                "skip_reason": "no_state_machines",
                "issues": [],
            }

        sm_text = json.dumps(state_machines, ensure_ascii=False)[:2500]

        prompt = f"""你是状态机设计审查专家。检查 Spec 中的状态机设计是否完整。

状态机定义:
{sm_text}

请输出严格 JSON:
{{
  "score": 0-100,
  "issues": [
    {{"severity": "critical|major|minor|info", "description": "问题描述",
      "suggestion": "改进建议", "location": "spec.modules[].state_machine"}}
  ]
}}

检查要点:
- 每个状态是否至少有一条入边（初始状态除外，状态可达性）
- 每个非终态是否至少有一条出边（状态可出性）
- 终态是否正确标记
- 每条 transition 是否定义了 trigger（触发事件）
- 是否存在孤立状态（无入边无出边）"""
        return await self._llm_check(
            "state_machine_closure", "状态机闭合性", prompt, ctx,
        )

    async def _check_prototype_alignment(
        self, a3: dict, a4: dict, ctx: dict,
    ) -> dict:
        """Check prototype screen coverage vs Spec use cases and states."""
        spec_doc = a4.get("spec_doc", {})
        screens = a3.get("screens", [])

        use_cases = json.dumps(
            spec_doc.get("api_endpoints", []), ensure_ascii=False,
        )[:1500]
        modules = json.dumps([
            {"name": m.get("name"), "states": m.get("states", [])}
            for m in spec_doc.get("modules", [])
        ], ensure_ascii=False)[:1500]
        screens_text = json.dumps([
            {"name": s.get("name"), "state": s.get("state")}
            for s in screens
        ], ensure_ascii=False)[:1000]

        prompt = f"""你是 UI/UX 审查专家。检查原型页面是否覆盖 Spec 中定义的交互路径和状态。

Spec 模块和状态:
{modules}

Spec 用例 (API):
{use_cases}

原型截图:
{screens_text}

请输出严格 JSON:
{{
  "score": 0-100,
  "issues": [
    {{"severity": "critical|major|minor|info", "description": "问题描述",
      "suggestion": "改进建议", "location": "prototype.screens"}}
  ]
}}

检查要点:
- Spec 中定义的每个状态（default/loading/empty/error/hover/active）是否在原型截图中有体现
- 是否存在断头路（原型中的页面找不到对应的 Spec 入口）
- 用户体验启发式检查：一致性、反馈清晰度、错误预防"""
        return await self._llm_check(
            "prototype_spec_alignment", "原型-Spec 对齐", prompt, ctx,
        )

    async def _check_security_baseline(
        self, a3: dict, a4: dict, ctx: dict,
    ) -> dict:
        """Check API security baseline."""
        openapi_schema = a4.get("openapi_schema", {})
        spec_doc = a4.get("spec_doc", {})

        security_info = json.dumps({
            "security": openapi_schema.get("security", []),
            "components": {
                "securitySchemes": openapi_schema.get("components", {}).get(
                    "securitySchemes", {},
                ),
            },
        }, ensure_ascii=False)[:1500]
        paths = json.dumps(
            list(openapi_schema.get("paths", {}).keys()), ensure_ascii=False,
        )[:1000]

        prompt = f"""你是安全审查专家。检查 API 设计是否满足基本安全要求。

OpenAPI 安全定义:
{security_info}

API 路径:
{paths}

请输出严格 JSON:
{{
  "score": 0-100,
  "issues": [
    {{"severity": "critical|major|minor|info", "description": "问题描述",
      "suggestion": "改进建议", "location": "openapi_schema"}}
  ]
}}

检查要点:
- OpenAPI 中是否定义了 securitySchemes（认证定义）
- 敏感 endpoint（增删改）是否标注了 required scopes（授权标注）
- 敏感字段（name/email/phone/id_card）是否标注了 PII 分类
- 是否有全局 scheme=https 声明（HTTPS 强制）"""
        return await self._llm_check("security_baseline", "安全基线", prompt, ctx)

    # ── LLM helper ──────────────────────────────────────────────────────

    async def _llm_check(
        self, key: str, label: str, prompt: str, ctx: dict,
    ) -> dict:
        """Call LLM for a single dimension check. Returns dimension result."""
        content = await self.call_llm(
            [{"role": "user", "content": prompt}],
            task_type="design_review",
            req_id=ctx.get("req_id", ""),
            workflow_id=ctx.get("workflow_id", ""),
            temperature=0.1,
            max_tokens=2000,
        )

        if content:
            try:
                text = content.strip()
                if text.startswith("```"):
                    text = text.split("```")[1].split("```")[0].strip()
                if text.startswith("json"):
                    text = text[4:].strip()
                result = json.loads(text)
                return {
                    "dimension": key,
                    "label": label,
                    "score": result.get("score", 0) / 100.0,
                    "issues": result.get("issues", []),
                }
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"[A5] LLM parse failed for {key}: {e}")

        # Fallback: rule-based pass
        return {
            "dimension": key,
            "label": label,
            "score": 0.6,
            "issues": [{
                "severity": "info",
                "description": f"{label}检查使用降级规则评分（LLM 不可用）",
                "suggestion": "建议人工复核",
            }],
        }

    # ── A4-missing mode ─────────────────────────────────────────────────

    async def _check_prototype_only(
        self, req_id: str, cycle: int, a3_output: dict,
    ) -> dict:
        """Degraded mode: only prototype_spec_alignment when A4 is missing."""
        logger.info(f"[A5] A4 missing — running prototype-only check for req={req_id}")

        screens = a3_output.get("screens", [])
        screens_text = json.dumps([
            {"name": s.get("name"), "state": s.get("state")}
            for s in screens
        ], ensure_ascii=False)[:1500]

        prompt = f"""你是 UI 审查专家。A4 Spec 尚未生成，仅基于原型截图做初步检查。

原型截图:
{screens_text}

请输出严格 JSON:
{{
  "score": 0-100,
  "issues": [
    {{"severity": "critical|major|minor|info", "description": "问题描述",
      "suggestion": "改进建议"}}
  ]
}}

检查要点:
- 原型中是否包含了 default/loading/empty/error 等必要状态
- 页面交互流是否完整（无明显断头路）"""

        content = await self.call_llm(
            [{"role": "user", "content": prompt}],
            task_type="design_review",
            req_id=req_id,
            workflow_id="",
            temperature=0.1,
            max_tokens=1500,
        )

        proto_dim = {
            "dimension": "prototype_spec_alignment",
            "label": "原型-Spec 对齐",
            "score": 0.5,
            "issues": [],
        }

        if content:
            try:
                text = content.strip()
                if text.startswith("```"):
                    text = text.split("```")[1].split("```")[0].strip()
                if text.startswith("json"):
                    text = text[4:].strip()
                result = json.loads(text)
                proto_dim["score"] = result.get("score", 50) / 100.0
                proto_dim["issues"] = result.get("issues", [])
            except (json.JSONDecodeError, KeyError):
                pass

        skipped_dims = [
            {"dimension": d["key"], "label": d["label"],
             "score": None, "status": "skipped", "skip_reason": "a4_missing",
             "issues": []}
            for d in DIMENSIONS if d["key"] != "prototype_spec_alignment"
        ]

        dimensions = skipped_dims + [proto_dim]
        check_report = {
            "overall_score": proto_dim["score"],
            "total_issues": len(proto_dim.get("issues", [])),
            "dimensions": dimensions,
            "summary": "A4 Spec 未生成，仅对原型截图做了初步检查。建议在 A4 完成后重新检查。",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        await self._persist_result(req_id, cycle, check_report)
        await self.report_artifact(req_id, "design_review", {
            "check_report": check_report,
            "non_blocking": True,
        })

        return {"status": "completed", "check_report": check_report,
                "non_blocking": True}

    # ── Persistence ─────────────────────────────────────────────────────

    async def _persist_result(
        self, req_id: str, cycle: int, check_report: dict,
    ):
        """Write design review result to agent_results."""
        conn = await self._get_db()
        try:
            artifact = {
                "check_report": check_report,
                "non_blocking": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            await conn.execute(
                """INSERT INTO agent_results
                   (req_id, agent_key, cycle, status, artifact)
                   VALUES ($1::uuid, 'A5', $2, 'completed', $3::jsonb)
                   ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
                   SET artifact = EXCLUDED.artifact,
                       status = 'completed',
                       created_at = NOW()""",
                req_id, cycle, json.dumps(artifact),
            )
            logger.info(f"[A5] Result persisted for req={req_id}")
        finally:
            await conn.close()

    # ── Summary generation ──────────────────────────────────────────────

    def _generate_summary(self, dimensions: list, overall: float) -> str:
        """Generate a human-readable summary from dimension results."""
        skipped = [d for d in dimensions if d.get("status") == "skipped"]
        critical = sum(
            1 for d in dimensions
            for i in d.get("issues", [])
            if i.get("severity") == "critical"
        )
        major = sum(
            1 for d in dimensions
            for i in d.get("issues", [])
            if i.get("severity") == "major"
        )

        parts = []
        if overall >= 0.8:
            parts.append("整体设计质量良好")
        elif overall >= 0.6:
            parts.append("整体设计质量一般，建议重点修复 major 级别问题")
        else:
            parts.append("整体设计质量偏低，建议全面复核后再提交 Gate1")

        if critical > 0:
            parts.append(f"发现 {critical} 个 critical 问题")
        if major > 0:
            parts.append(f"发现 {major} 个 major 问题")
        if skipped:
            skipped_names = [d["label"] for d in skipped]
            parts.append(f"跳过维度: {', '.join(skipped_names)}")

        return "。".join(parts) + "。"
