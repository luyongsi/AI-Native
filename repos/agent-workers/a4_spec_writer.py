"""
A4: Spec Writer Agent (Spec 编写)

Real LLM: 调用 DeepSeek API 生成 OpenAPI + ERD
Fallback: 硬编码模板

触发条件:
  - context.ready.spec_writer (NATS Event from Orchestrator)
  - spec.ready.designing (NATS Event from Chat Spec process)
"""
from __future__ import annotations

import json
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Tuple, Optional, List
from base_worker import BaseAgentWorker
from a4 import APISchemaGenerator, ERDGenerator
import asyncpg

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")


class A4SpecWriter(BaseAgentWorker):
    agent_id = "A4"
    agent_type = "spec_writer"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self._db_pool = None
        self.api_schema_gen = APISchemaGenerator()
        self.erd_gen = ERDGenerator()

    async def _get_db(self):
        if self._db_pool is None:
            DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native")
            self._db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        return await self._db_pool.acquire()

    async def _read_spec_from_db(self, req_id: str) -> dict:
        conn = await self._get_db()
        try:
            row = await conn.fetchrow("SELECT id, title, spec FROM requirements WHERE id = $1::uuid", req_id)
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

    async def _write_spec_to_db(self, req_id: str, openapi: dict, erd: dict):
        conn = await self._get_db()
        try:
            row = await conn.fetchrow("SELECT spec FROM requirements WHERE id = $1::uuid", req_id)
            spec_raw = {}
            if row and row["spec"]:
                spec_raw = row["spec"]
                if isinstance(spec_raw, str):
                    try:
                        spec_raw = json.loads(spec_raw)
                    except (json.JSONDecodeError, TypeError):
                        spec_raw = {}
                if not isinstance(spec_raw, dict):
                    spec_raw = {}
            spec_raw["openapi"] = openapi
            spec_raw["erd"] = erd
            spec_raw["updated_at"] = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                "UPDATE requirements SET spec = $1::jsonb, updated_at = NOW() WHERE id = $2::uuid",
                json.dumps(spec_raw), req_id,
            )
            logger.info(f"[A4] OpenAPI/ERD written to DB for req={req_id}")
        finally:
            await conn.close()

    async def _save_api_schema(self, req_id: str, api_schema_result: dict):
        """Save generated API schema to api_schemas table."""
        conn = await self._get_db()
        try:
            # Check if schema already exists for this req_id
            existing = await conn.fetchval(
                "SELECT MAX(version) FROM api_schemas WHERE req_id = $1::uuid",
                req_id
            )
            new_version = (existing or 0) + 1

            await conn.execute(
                """INSERT INTO api_schemas (req_id, schema_json, version, validation_passed, source)
                   VALUES ($1::uuid, $2::jsonb, $3, $4, $5)""",
                req_id,
                json.dumps(api_schema_result.get("schema", {})),
                new_version,
                api_schema_result.get("validation_passed", False),
                api_schema_result.get("source", "llm"),
            )
            logger.info(f"[A4] API schema saved to DB for req={req_id}, version={new_version}")
        except Exception as e:
            logger.error(f"[A4] Failed to save API schema: {e}")
        finally:
            await conn.close()

    async def _detect_existing_tables(self, db_pool) -> List[str]:
        """Query information_schema to detect existing tables."""
        if db_pool is None:
            return []
        conn = await db_pool.acquire()
        try:
            rows = await conn.fetch(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                   ORDER BY table_name"""
            )
            return [row['table_name'] for row in rows]
        except Exception as e:
            logger.warning(f"[A4] Failed to detect existing tables: {e}")
            return []
        finally:
            await conn.close()

    async def _save_erd_design(self, req_id: str, erd_result: dict):
        """Save generated ERD design to erd_designs table."""
        conn = await self._get_db()
        try:
            # Check if design already exists for this req_id to determine version
            existing = await conn.fetchval(
                "SELECT MAX(version) FROM erd_designs WHERE req_id = $1::uuid",
                req_id
            )
            new_version = (existing or 0) + 1

            await conn.execute(
                """INSERT INTO erd_designs
                   (req_id, erd_mermaid, ddl, entities, relationships,
                    validation_passed, validation_errors, is_incremental,
                    existing_tables, version, source)
                   VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6, $7::jsonb, $8, $9::jsonb, $10, $11)""",
                req_id,
                erd_result.get("erd_mermaid", ""),
                erd_result.get("ddl", ""),
                json.dumps(erd_result.get("entities", [])),
                json.dumps(erd_result.get("relationships", [])),
                erd_result.get("validation_passed", False),
                json.dumps(erd_result.get("validation_log", [])),
                erd_result.get("is_incremental", False),
                json.dumps(erd_result.get("existing_tables", [])),
                new_version,
                erd_result.get("source", "llm"),
            )
            logger.info(f"[A4] ERD design saved to DB for req={req_id}, version={new_version}")
        except Exception as e:
            logger.error(f"[A4] Failed to save ERD design: {e}")
        finally:
            await conn.close()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        draft = context_package.get("requirement_draft", {})
        title = draft.get("title", context_package.get("message", "未命名需求"))
        domain = draft.get("domain", "general")

        # If triggered by spec.ready.designing, read spec from DB
        if context_package.get("event_type") == "spec.ready.designing" or not draft:
            db_data = await self._read_spec_from_db(req_id)
            if db_data:
                title = db_data.get("title", title)
                sections = db_data.get("spec", {}).get("sections", [])
                if sections:
                    draft["title"] = title
                    draft["domain"] = domain
                    draft["summary"] = "\n".join(
                        f"{s.get('title','')}: {s.get('content','')[:200]}"
                        for s in sections[:5]
                    )

        logger.info(f"[A4] Writing specs for domain={domain}, req={req_id}")

        await self.report_status(req_id, "running", "Phase 1: LLM 生成技术规格")

        requirement_text = draft.get("summary", draft.get("title", ""))

        # Detect existing tables for incremental schema
        existing_tables = await self._detect_existing_tables(self._db_pool)

        # Generate API Schema and ERD in parallel
        api_schema_task = self.api_schema_gen.generate(
            requirement_text,
            context={
                "title": title,
                "domain": domain,
                "acceptance_criteria": draft.get("acceptance_criteria", []),
            },
            max_retries=3,
        )

        erd_task = self.erd_gen.generate(
            requirement_text,
            context={
                "title": title,
                "domain": domain,
            },
            existing_tables=existing_tables,
            max_retries=3,
        )

        # Wait for both tasks to complete
        api_schema_result, erd_result = await asyncio.gather(api_schema_task, erd_task)

        # Save both to database
        await self._save_api_schema(req_id, api_schema_result)
        await self._save_erd_design(req_id, erd_result)

        # Report as artifacts
        await self.report_artifact(req_id, "openapi_spec", api_schema_result.get("schema", {}))
        await self.report_artifact(req_id, "erd", {
            "mermaid": erd_result.get("erd_mermaid", ""),
            "ddl": erd_result.get("ddl", ""),
            "entities": erd_result.get("entities", []),
            "relationships": erd_result.get("relationships", []),
        })

        result = {
            "status": "completed",
            "api_schema": api_schema_result,
            "erd": erd_result,
            "erd_tables": len(erd_result.get("entities", [])),
            "erd_relationships": len(erd_result.get("relationships", [])),
            "api_schema_valid": api_schema_result.get("validation_passed", False),
            "api_schema_source": api_schema_result.get("source", "unknown"),
            "erd_valid": erd_result.get("validation_passed", False),
            "erd_source": erd_result.get("source", "unknown"),
            "is_incremental_schema": erd_result.get("is_incremental", False),
        }

        # After A4 completes, trigger A5 design review
        review_envelope = {
            "event_id": f"review-start-{req_id}",
            "event_type": "review.start",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "req_id": req_id,
                "gate": 1,
                "spec_package": {
                    "openapi": api_schema_result.get("schema", {}),
                    "erd": {
                        "mermaid": erd_result.get("erd_mermaid", ""),
                        "ddl": erd_result.get("ddl", ""),
                        "entities": erd_result.get("entities", []),
                        "relationships": erd_result.get("relationships", []),
                    }
                }
            },
            "req_id": req_id,
        }
        await self.nc.publish("review.start", json.dumps(review_envelope, ensure_ascii=False).encode())
        logger.info(f"[A4] Triggered review.start for req={req_id}")

        return result

    def _generate_fallback_erd(self, domain: str, draft: dict) -> Tuple[dict, str]:
        """Generate fallback ERD when LLM fails (legacy - now handled by ERDGenerator)."""
        erd = {
            "tables": [
                {
                    "name": f"{domain}_records",
                    "columns": [
                        {"name": "id", "type": "UUID", "primary_key": True},
                        {"name": "title", "type": "VARCHAR(255)"},
                        {"name": "created_at", "type": "TIMESTAMP"}
                    ]
                },
            ],
            "relationships": [],
        }
        architecture_notes = f"[Fallback] Standard CRUD architecture for {domain}"
        return erd, architecture_notes
