"""
A4: Spec Writer Agent (Spec 撰写)

Stage 2: Generates structured technical spec (Spec/OpenAPI/ERD/DDL)
from A1 draft + A2 feasibility + A3 prototype.

Trigger: context.ready.A4 (NATS from Orchestrator after A3 confirm or Gate1 reject)

Six-phase pipeline:
  1. Context parsing — extract upstream artifacts + MCP knowledge + DB introspection
  2. Spec generation — LLM produces 6-chapter structured spec document
  3. OpenAPI generation — LLM produces OpenAPI 3.1 spec with validation
  4. ERD + DDL generation — LLM produces ERD + DDL with incremental detection
  5. Quality scoring — 4-dimension scoring (spec completeness, API coverage,
     ERD coverage, DDL validity)
  6. Persist + publish — write design_specs + agent_results + requirements.spec

Three-tier degradation:
  1. Full — all MCP tools available + LLM normal (source='llm')
  2. Partial — some MCP tools failed, LLM normal (source='llm_no_mcp')
  3. Fallback — LLM unavailable, template output (source='fallback')
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from base_worker import BaseAgentWorker
from a4.api_schema_generator import APISchemaGenerator
from a4.erd_generator import ERDGenerator
from a4.spec_generator import SpecGenerator
from a4.knowledge_client import A4KnowledgeClient

logger = logging.getLogger(__name__)


class A4SpecWriter(BaseAgentWorker):
    agent_id = "A4"
    agent_type = "spec_writer"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self._db_pool = None
        self.knowledge = A4KnowledgeClient()
        self.spec_gen = SpecGenerator(llm_caller=self.call_llm)
        self.api_gen = APISchemaGenerator(llm_caller=self.call_llm)
        self.erd_gen = ERDGenerator(llm_caller=self.call_llm)

    # ── Database helpers ────────────────────────────────────────────────

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

    async def _detect_existing_tables(self) -> list[str]:
        """Query information_schema for existing table names."""
        try:
            conn = await self._get_db()
            try:
                rows = await conn.fetch(
                    """SELECT table_name FROM information_schema.tables
                       WHERE table_schema = 'public'
                       AND table_type = 'BASE TABLE'
                       ORDER BY table_name"""
                )
                return [row["table_name"] for row in rows]
            finally:
                await conn.close()
        except Exception as e:
            logger.warning(f"[A4] Failed to detect existing tables: {e}")
            return []

    # ── Main execution ──────────────────────────────────────────────────

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """Six-phase spec writing pipeline."""
        logger.info(f"[A4] Starting spec writing for req={req_id}")

        # Phase 1: Parse upstream context
        a1_output = context_package.get("a1_output", {})
        a2_output = context_package.get("a2_output", {})
        a3_output = context_package.get("a3_output", {})
        cycle = context_package.get("cycle", 0)

        draft = a1_output.get("requirement_draft", {})
        title = draft.get("title", context_package.get("title", "未命名需求"))
        domain = draft.get("domain", "general")
        description = draft.get("description", draft.get("summary", ""))
        feasibility = a2_output.get("feasibility_assessment", {})
        prototype_url = a3_output.get("prototype_url", "")
        revision_context = context_package.get("revision_context")

        await self.report_status(req_id, "running", "Phase 1: 解析上下文 + MCP 知识检索")

        # MCP knowledge fetch (parallel, non-blocking)
        mcp_results = await self.knowledge.fetch_all(domain)
        mcp_tier = mcp_results["tier"]
        logger.info(f"[A4] MCP tier={mcp_tier}, errors={len(mcp_results['errors'])}")

        # DB introspection
        existing_tables = await self._detect_existing_tables()
        logger.info(f"[A4] Detected {len(existing_tables)} existing tables")

        # Phase 2: Generate structured Spec document
        await self.report_status(req_id, "running", "Phase 2: LLM 生成技术规格文档")
        spec_doc = await self.spec_gen.generate(
            draft=draft,
            feasibility=feasibility,
            prototype_url=prototype_url,
            domain=domain,
            revision_context=revision_context,
        )

        # Phase 3: Generate OpenAPI schema
        await self.report_status(req_id, "running", "Phase 3: LLM 生成 OpenAPI 规范")
        requirement_text = description or title
        api_task = self.api_gen.generate(
            requirement_text,
            context={
                "title": title,
                "domain": domain,
                "acceptance_criteria": draft.get("acceptance_criteria", []),
                "req_id": req_id,
                "workflow_id": context_package.get("workflow_id", ""),
                "rework_feedback": self._format_revision_feedback(revision_context),
                "mcp_templates": mcp_results.get("openapi_templates", []),
            },
            max_retries=3,
        )

        # Phase 4: Generate ERD + DDL
        await self.report_status(req_id, "running", "Phase 4: LLM 生成 ERD + DDL")
        erd_task = self.erd_gen.generate(
            requirement_text,
            context={
                "title": title,
                "domain": domain,
                "req_id": req_id,
                "workflow_id": context_package.get("workflow_id", ""),
                "rework_feedback": self._format_revision_feedback(revision_context),
                "mcp_patterns": mcp_results.get("erd_patterns", []),
                "ddl_conventions": mcp_results.get("ddl_conventions"),
            },
            existing_tables=existing_tables,
            max_retries=3,
        )

        api_result, erd_result = await asyncio.gather(api_task, erd_task)

        # Phase 5: Quality scoring
        await self.report_status(req_id, "running", "Phase 5: 质量评分")
        quality_score = self._compute_quality_score(
            spec_doc, api_result, erd_result,
        )
        source = self._determine_source(mcp_tier, api_result, erd_result, spec_doc)

        # Phase 6: Persist and publish
        await self.report_status(req_id, "running", "Phase 6: 持久化产物 + 发布结果")
        await self._persist(
            req_id, cycle, spec_doc, api_result, erd_result,
            quality_score, source,
        )

        entity_count = len(erd_result.get("entities", []))
        rel_count = len(erd_result.get("relationships", []))

        # Report artifacts via base worker
        await self.report_artifact(req_id, "openapi_spec",
                                   api_result.get("schema", {}))
        await self.report_artifact(req_id, "erd", {
            "mermaid": erd_result.get("erd_mermaid", ""),
            "ddl": erd_result.get("ddl", ""),
            "entities": erd_result.get("entities", []),
            "relationships": erd_result.get("relationships", []),
        })
        await self.report_artifact(req_id, "spec_doc", spec_doc)

        result = {
            "status": "completed",
            "spec_doc": spec_doc,
            "openapi_schema": api_result.get("schema", {}),
            "erd_diagram": erd_result,
            "ddl_statements": erd_result.get("ddl", ""),
            "quality_score": quality_score,
            "source": source,
            "metadata": {
                "api_endpoint_count": len(
                    api_result.get("schema", {}).get("paths", {})
                ),
                "entity_count": entity_count,
                "new_entity_count": entity_count,
                "state_count": sum(
                    len(m.get("state_machine", {}).get("states", []))
                    for m in spec_doc.get("modules", [])
                ),
                "transition_count": sum(
                    len(m.get("state_machine", {}).get("transitions", []))
                    for m in spec_doc.get("modules", [])
                ),
                "mcp_tier": mcp_tier,
            },
        }

        return result

    # ── Persistence ─────────────────────────────────────────────────────

    async def _persist(
        self,
        req_id: str,
        cycle: int,
        spec_doc: dict,
        api_result: dict,
        erd_result: dict,
        quality_score: float,
        source: str,
    ):
        """Persist to design_specs + api_schemas + erd_designs + agent_results + requirements.spec."""
        conn = await self._get_db()
        try:
            async with conn.transaction():
                # Determine next version for design_specs
                existing = await conn.fetchval(
                    "SELECT MAX(version) FROM design_specs "
                    "WHERE req_id = $1::uuid AND cycle = $2",
                    req_id, cycle,
                )
                new_version = (existing or 0) + 1

                # 1. design_specs
                await conn.execute(
                    """INSERT INTO design_specs
                       (req_id, cycle, version, spec_doc, openapi_schema,
                        erd_diagram, ddl_statements, quality_score, source)
                       VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb,
                               $6::jsonb, $7, $8, $9)""",
                    req_id, cycle, new_version,
                    json.dumps(spec_doc),
                    json.dumps(api_result.get("schema", {})),
                    json.dumps(erd_result),
                    erd_result.get("ddl", ""),
                    quality_score,
                    source,
                )

                # 2. api_schemas (versioned)
                api_version = await conn.fetchval(
                    "SELECT MAX(version) FROM api_schemas WHERE req_id = $1::uuid",
                    req_id,
                )
                await conn.execute(
                    """INSERT INTO api_schemas
                       (req_id, schema_json, version, validation_passed,
                        validation_log, source)
                       VALUES ($1::uuid, $2::jsonb, $3, $4, $5::jsonb, $6)""",
                    req_id,
                    json.dumps(api_result.get("schema", {})),
                    (api_version or 0) + 1,
                    api_result.get("validation_passed", False),
                    json.dumps(api_result.get("validation_log", [])),
                    source,
                )

                # 3. erd_designs (versioned)
                erd_version = await conn.fetchval(
                    "SELECT MAX(version) FROM erd_designs WHERE req_id = $1::uuid",
                    req_id,
                )
                await conn.execute(
                    """INSERT INTO erd_designs
                       (req_id, erd_mermaid, ddl, entities, relationships,
                        validation_passed, validation_errors, is_incremental,
                        existing_tables, version, source)
                       VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb,
                               $6, $7::jsonb, $8, $9::jsonb, $10, $11)""",
                    req_id,
                    erd_result.get("erd_mermaid", ""),
                    erd_result.get("ddl", ""),
                    json.dumps(erd_result.get("entities", [])),
                    json.dumps(erd_result.get("relationships", [])),
                    erd_result.get("validation_passed", False),
                    json.dumps(erd_result.get("validation_log", [])),
                    erd_result.get("is_incremental", False),
                    json.dumps(erd_result.get("existing_tables", [])),
                    (erd_version or 0) + 1,
                    source,
                )

                # 4. agent_results (upsert by req_id + agent_key + cycle)
                artifact = {
                    "spec_doc": spec_doc,
                    "openapi_schema": api_result.get("schema", {}),
                    "erd_diagram": erd_result,
                    "ddl_statements": erd_result.get("ddl", ""),
                    "quality_score": quality_score,
                    "source": source,
                    "metadata": {
                        "api_endpoint_count": len(
                            api_result.get("schema", {}).get("paths", {})
                        ),
                        "entity_count": len(erd_result.get("entities", [])),
                        "mcp_tier": mcp_results_tier(api_result),
                    },
                }
                await conn.execute(
                    """INSERT INTO agent_results
                       (req_id, agent_key, cycle, status, artifact)
                       VALUES ($1::uuid, 'A4', $2, 'completed', $3::jsonb)
                       ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
                       SET artifact = EXCLUDED.artifact,
                           status = 'completed',
                           created_at = NOW()""",
                    req_id, cycle, json.dumps(artifact),
                )

                # 5. requirements.spec mirror (fallback read path)
                await conn.execute(
                    "UPDATE requirements SET spec = $1::jsonb, updated_at = NOW() "
                    "WHERE id = $2::uuid",
                    json.dumps({
                        "spec_doc": spec_doc,
                        "openapi": api_result.get("schema", {}),
                        "erd": erd_result,
                        "ddl": erd_result.get("ddl", ""),
                        "quality_score": quality_score,
                        "source": source,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }),
                    req_id,
                )

                logger.info(
                    f"[A4] Persisted: design_specs v{new_version}, "
                    f"api_schemas, erd_designs, agent_results, requirements.spec "
                    f"for req={req_id}"
                )
        finally:
            await conn.close()

    # ── Quality scoring ─────────────────────────────────────────────────

    def _compute_quality_score(
        self, spec_doc: dict, api_result: dict, erd_result: dict,
    ) -> float:
        """Compute weighted quality score across 4 dimensions.

        Weights from design doc:
          spec_completeness: 35%, api_coverage: 25%,
          erd_coverage: 20%, ddl_validity: 20%
        """
        scores = {
            "spec_completeness": self._score_spec(spec_doc),
            "api_coverage": self._score_api(api_result),
            "erd_coverage": self._score_erd(erd_result),
            "ddl_validity": self._score_ddl(erd_result),
        }
        weights = {
            "spec_completeness": 0.35,
            "api_coverage": 0.25,
            "erd_coverage": 0.20,
            "ddl_validity": 0.20,
        }
        total = sum(scores[k] * weights[k] for k in scores)
        return round(total, 2)

    def _score_spec(self, spec: dict) -> float:
        modules = spec.get("modules", [])
        has_modules = 1.0 if len(modules) >= 2 else 0.5 if modules else 0.0
        has_state_machines = all(
            m.get("state_machine", {}).get("states") for m in modules
        )
        has_data_models = 1.0 if len(spec.get("data_models", [])) >= 2 else 0.3
        has_non_func = all(
            spec.get("non_functional", {}).get(k)
            for k in ("performance", "security", "audit", "idempotency")
        )
        return round(
            has_modules * 0.3
            + (1.0 if has_state_machines else 0.3) * 0.25
            + has_data_models * 0.25
            + (1.0 if has_non_func else 0.3) * 0.2,
            2,
        )

    def _score_api(self, api_result: dict) -> float:
        schema = api_result.get("schema", {})
        paths = schema.get("paths", {})
        if not paths:
            return 0.2
        has_request_body = any(
            op.get("requestBody") for p in paths.values()
            for op in p.values()
        )
        has_error_responses = any(
            any(str(sc) in op.get("responses", {}) for sc in ("400", "401", "404"))
            for p in paths.values() for op in p.values()
        )
        validated = api_result.get("validation_passed", False)
        score = 0.5
        if has_request_body:
            score += 0.2
        if has_error_responses:
            score += 0.15
        if validated:
            score += 0.15
        return min(round(score, 2), 1.0)

    def _score_erd(self, erd_result: dict) -> float:
        entities = erd_result.get("entities", [])
        relationships = erd_result.get("relationships", [])
        if not entities:
            return 0.1
        has_rels = 1.0 if relationships else 0.3
        validated = erd_result.get("validation_passed", False)
        score = min(len(entities) / 4, 1.0) * 0.5 + has_rels * 0.3
        if validated:
            score += 0.2
        return min(round(score, 2), 1.0)

    def _score_ddl(self, erd_result: dict) -> float:
        ddl = erd_result.get("ddl", "")
        if not ddl:
            return 0.0
        has_create = "CREATE TABLE" in ddl.upper()
        has_index = "INDEX" in ddl.upper()
        has_fk = "FOREIGN KEY" in ddl.upper() or "REFERENCES" in ddl.upper()
        validated = erd_result.get("validation_passed", False)
        score = 0.3
        if has_create:
            score += 0.3
        if has_index:
            score += 0.2
        if has_fk:
            score += 0.1
        if validated:
            score += 0.1
        return min(round(score, 2), 1.0)

    def _determine_source(
        self, mcp_tier: str, api_result: dict, erd_result: dict, spec_doc: dict,
    ) -> str:
        """Determine the source label for the output."""
        if spec_doc.get("source") == "fallback":
            return "fallback"
        if api_result.get("source") == "fallback" or erd_result.get("source") == "fallback":
            return "fallback"
        if mcp_tier == "full":
            return "llm"
        if mcp_tier == "partial":
            return "llm_no_mcp"
        return "llm_no_mcp"

    def _format_revision_feedback(self, revision_context: dict | None) -> str:
        """Format Gate1 rejection feedback for injection into LLM prompts."""
        if not revision_context or not revision_context.get("is_revision"):
            return ""

        lines = []
        rejection = revision_context.get("gate1_rejection", {})
        for reason in rejection.get("reject_reasons", []):
            lines.append(
                f"- [{reason.get('category', '?')}] {reason.get('description', '')}"
            )
        guidance = rejection.get("revision_guidance", "")
        if guidance:
            lines.append(f"\n修订指引: {guidance}")

        prev_report = revision_context.get("previous_a5_report", {})
        for dim in prev_report.get("dimensions", []):
            for issue in dim.get("issues", []):
                if issue.get("severity") in ("critical", "major"):
                    lines.append(
                        f"[{issue['severity']}] {dim.get('label', '')}: "
                        f"{issue.get('description', '')}"
                    )
        return "\n".join(lines)


def mcp_results_tier(api_result: dict) -> str:
    """Extract or infer MCP tier from result metadata (for agent_results artifact)."""
    # This is a best-effort helper; the actual tier is determined upstream
    source = api_result.get("source", "")
    if source == "fallback":
        return "none"
    if source == "llm_no_mcp":
        return "partial"
    return "full"
