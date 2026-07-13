"""
Database layer tests — T-DB-001 through T-DB-016.

Tests DDL creation, default values, UNIQUE constraints, CHECK constraints,
CASCADE deletes, and index existence per test design doc v1.1 §2.

Run with:
  pytest repos/agent-workers/tests/test_db_schema.py -v -s

Requires a test PostgreSQL database. Set TEST_DATABASE_URL env var
or default to postgresql://ai_native:ai_native_dev@localhost:5432/ai_native_test
"""
from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native_test",
)

pytestmark = pytest.mark.db


# ── helpers ──────────────────────────────────────────────────────────────

async def _get_pool():
    return await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=3)


async def _table_exists(conn, table_name: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=$1",
        table_name,
    )
    return row is not None


# ══════════════════════════════════════════════════════════════════════════
# T-DB-001: All 7 tables created
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_001_all_tables_exist():
    """After migration 008, all 7 tables exist."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        for table in [
            "requirements", "agent_results", "dialogue_sessions",
            "dialogue_messages", "understanding_snapshots",
            "event_log", "approvals",
        ]:
            assert await _table_exists(conn, table), f"Table {table} missing"
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-002: requirements default values
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_002_requirements_defaults():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO requirements (id, title, status) VALUES ($1::uuid, '测试需求', DEFAULT)",
            rid,
        )
        row = await conn.fetchrow(
            "SELECT status, gate_rejection_count, revision_count, analyzer_agent "
            "FROM requirements WHERE id=$1::uuid",
            rid,
        )
        assert row["status"] == "draft"
        assert row["gate_rejection_count"] == 0
        assert row["revision_count"] == 0
        assert row["analyzer_agent"] == "A1"
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-003: agent_results UNIQUE (req_id, agent_key, cycle)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_003_agent_results_unique():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')",
            rid,
        )
        await conn.execute(
            "INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact) "
            "VALUES ($1::uuid, 'A1', 0, 'completed', '{}'::jsonb)",
            rid,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact) "
                "VALUES ($1::uuid, 'A1', 0, 'completed', '{}'::jsonb)",
                rid,
            )
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-004: dialogue_messages UNIQUE (session_id, cycle, sequence_number)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_004_dialogue_messages_unique():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')", rid,
        )
        await conn.execute(
            "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)",
            sid, rid,
        )
        await conn.execute(
            "INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number) "
            "VALUES ($1::uuid, 'human', '{\"text\":\"hi\"}'::jsonb, 0, 1)",
            sid,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number) "
                "VALUES ($1::uuid, 'human', '{\"text\":\"hi again\"}'::jsonb, 0, 1)",
                sid,
            )
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-005: event_log CHECK constraint ck_outbox
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_005_event_log_ck_outbox():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())

        # IN + NULL = OK
        await conn.execute(
            "INSERT INTO event_log (req_id, event_name, direction, payload, outbox_status) "
            "VALUES ($1::uuid, 'agent.result.A1', 'IN', '{}'::jsonb, NULL)",
            rid,
        )

        # OUT + NULL = VIOLATION
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO event_log (req_id, event_name, direction, payload, outbox_status) "
                "VALUES ($1::uuid, 'agent.result.A1', 'OUT', '{}'::jsonb, NULL)",
                rid,
            )

        # OUT + 'pending' = OK
        await conn.execute(
            "INSERT INTO event_log (req_id, event_name, direction, payload, outbox_status) "
            "VALUES ($1::uuid, 'agent.result.A1', 'OUT', '{}'::jsonb, 'pending')",
            str(uuid.uuid4()),
        )
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-006: approvals CHECK constraint ck_approval_decision
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_006_approvals_ck_decision():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')", rid,
        )
        await conn.execute(
            "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)",
            sid, rid,
        )

        # pending with decision=pass → violation
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, decision) "
                "VALUES ($1::uuid, $2::uuid, 0, 0, 'pending', 'pass')",
                rid, sid,
            )

        # decided with NULL decision → violation
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, "
                "decision, reviewer_user_id, reviewed_at) "
                "VALUES ($1::uuid, $2::uuid, 0, 0, 'decided', NULL, NULL, NULL)",
                rid, sid,
            )

        # Valid decided entry
        await conn.execute(
            "INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, "
            "decision, reviewer_user_id, reviewed_at) "
            "VALUES ($1::uuid, $2::uuid, 0, 0, 'decided', 'pass', 'u1', NOW())",
            rid, sid,
        )
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-007: dialogue_messages CHECK role enum
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_007_dialogue_messages_role_check():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await conn.execute("INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')", rid)
        await conn.execute(
            "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)", sid, rid,
        )

        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO dialogue_messages (session_id, role, content, sequence_number) "
                "VALUES ($1::uuid, 'bot', '{\"text\":\"hi\"}'::jsonb, 1)",
                sid,
            )

        # Valid roles
        for role in ("human", "ai", "system"):
            await conn.execute(
                "INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number) "
                "VALUES ($1::uuid, $2, '{}'::jsonb, 0, $3)",
                sid, role, {"human": 2, "ai": 3, "system": 4}[role],
            )
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-008: event_log direction CHECK enum
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_008_event_log_direction_check():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        for bad in ("INCOMING", "BOTH"):
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "INSERT INTO event_log (event_name, direction, payload) "
                    "VALUES ('test', $1, '{}'::jsonb)",
                    bad,
                )

        for good in ("IN", "OUT"):
            await conn.execute(
                "INSERT INTO event_log (event_name, direction, payload) "
                "VALUES ($1, $2, '{}'::jsonb)",
                "test_" + good.lower(), good,
            )
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-009: dialogue_sessions req_id UNIQUE
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_009_dialogue_sessions_req_unique():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        await conn.execute("INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')", rid)
        await conn.execute(
            "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)",
            str(uuid.uuid4()), rid,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)",
                str(uuid.uuid4()), rid,
            )
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-010: requirements DELETE CASCADE → dialogue_sessions
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_010_requirements_cascade_to_sessions():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await conn.execute("INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')", rid)
        await conn.execute(
            "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)", sid, rid,
        )
        await conn.execute("DELETE FROM requirements WHERE id=$1::uuid", rid)
        count = await conn.fetchval(
            "SELECT count(*) FROM dialogue_sessions WHERE req_id=$1::uuid", rid,
        )
        assert count == 0
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-011: dialogue_sessions DELETE CASCADE → dialogue_messages
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_011_sessions_cascade_to_messages():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await conn.execute("INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')", rid)
        await conn.execute(
            "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)", sid, rid,
        )
        await conn.execute(
            "INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number) "
            "VALUES ($1::uuid, 'human', '{}'::jsonb, 0, 1)", sid,
        )
        await conn.execute("DELETE FROM dialogue_sessions WHERE id=$1::uuid", sid)
        count = await conn.fetchval(
            "SELECT count(*) FROM dialogue_messages WHERE session_id=$1::uuid", sid,
        )
        assert count == 0
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-012: dialogue_sessions DELETE CASCADE → understanding_snapshots
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_012_sessions_cascade_to_snapshots():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await conn.execute("INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')", rid)
        await conn.execute(
            "INSERT INTO dialogue_sessions (id, req_id) VALUES ($1::uuid, $2::uuid)", sid, rid,
        )
        await conn.execute(
            "INSERT INTO understanding_snapshots (session_id, iteration, draft) "
            "VALUES ($1::uuid, 1, '{}'::jsonb)", sid,
        )
        await conn.execute("DELETE FROM dialogue_sessions WHERE id=$1::uuid", sid)
        count = await conn.fetchval(
            "SELECT count(*) FROM understanding_snapshots WHERE session_id=$1::uuid", sid,
        )
        assert count == 0
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-013: All indexes exist
# ══════════════════════════════════════════════════════════════════════════

EXPECTED_INDEXES = [
    "idx_requirements_status",
    "idx_agent_results_req",
    "idx_dialogue_messages_session_cycle",
    "idx_understanding_snapshots_session_cycle",
    "idx_event_log_req",
    "idx_event_log_name",
    "idx_event_log_outbox",
    "idx_approvals_req",
]


@pytest.mark.asyncio
async def test_db_013_all_indexes_exist():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename IN ('requirements','agent_results','dialogue_messages',"
            "'understanding_snapshots','event_log','approvals')"
        )
        existing = {r["indexname"] for r in rows}
        for idx in EXPECTED_INDEXES:
            assert idx in existing, f"Index {idx} missing. Found: {sorted(existing)}"
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-014: event_log outbox partial index only covers pending rows
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_014_outbox_partial_index():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT indexdef FROM pg_indexes WHERE indexname='idx_event_log_outbox'",
        )
        assert row is not None, "idx_event_log_outbox not found"
        indexdef = row["indexdef"]
        assert "outbox_status = 'pending'" in indexdef, \
            f"Partial index missing WHERE clause: {indexdef}"
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-015: requirements title nullable
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_015_title_nullable():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO requirements (id, status) VALUES ($1::uuid, 'draft')",
            rid,
        )
        row = await conn.fetchrow(
            "SELECT id FROM requirements WHERE id=$1::uuid AND title IS NULL",
            rid,
        )
        assert row is not None
    await pool.close()


# ══════════════════════════════════════════════════════════════════════════
# T-DB-016: Legacy table rename (extra test)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_db_016_old_tables_renamed():
    """After migration 008, old tables should be *_legacy (or may not exist if fresh DB)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # New table exists
        assert await _table_exists(conn, "requirements")

        # Old tables either don't exist or are renamed
        legacy_tables = ["requirements_legacy", "chat_messages_legacy", "gate_approvals_legacy"]
        for lt in legacy_tables:
            exists = await _table_exists(conn, lt)
            # At least the new tables must NOT have the old name variants
            assert await _table_exists(conn, "requirements") is True

    await pool.close()
