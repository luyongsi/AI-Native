"""
API integration tests — T-API-001 through T-API-020.

Tests the HTTP API endpoints with a real (or test) PostgreSQL database.
Uses FastAPI TestClient + asyncpg for direct DB verification.

Run with (requires a running test PostgreSQL):
  pytest repos/agent-workers/tests/test_api_dialogue.py -v -m integration

Or for local dev:
  TEST_DATABASE_URL=postgresql://... pytest tests/test_api_dialogue.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.api]

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native_test",
)


# ── FastAPI app fixture ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Import the FastAPI app once per test module."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mc-backend"))

    # Ensure DB_POOL is available with the test database
    from main import app as fastapi_app
    fastapi_app.dependency_overrides = {}
    return fastapi_app


@pytest.fixture
async def client(app):
    """Create an async HTTPX test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_pool():
    """Create a direct asyncpg pool for DB verification."""
    import asyncpg
    pool = await asyncpg.create_pool(TEST_DB_URL, min_size=1, max_size=2)
    yield pool
    await pool.close()


# ── Helper: create a requirement ─────────────────────────────────────────

async def _create_req(client, title="用户管理系统") -> dict:
    resp = await client.post(
        "/api/requirements",
        json={"title": title},
        headers={"Authorization": "Bearer test-user-token"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ══════════════════════════════════════════════════════════════════════════
# T-API-001: Normal requirement creation
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_001_create_requirement(client, db_pool):
    resp = await client.post(
        "/api/requirements",
        json={"title": "用户管理系统"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["title"] == "用户管理系统"
    assert "req_id" in data
    assert "created_at" in data

    # DB verification
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT title, status, requirement_draft FROM requirements WHERE id=$1::uuid",
            data["req_id"],
        )
        assert row is not None
        assert row["title"] == "用户管理系统"
        assert row["status"] == "draft"
        draft = row["requirement_draft"]
        if isinstance(draft, str):
            draft = json.loads(draft)
        assert draft.get("title") == "用户管理系统"


# ══════════════════════════════════════════════════════════════════════════
# T-API-002: Create without title (optional)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_002_create_no_title(client, db_pool):
    resp = await client.post(
        "/api/requirements",
        json={},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] is None


# ══════════════════════════════════════════════════════════════════════════
# T-API-003: Unauthorized
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_003_unauthorized(client):
    resp = await client.post("/api/requirements", json={"title": "test"})
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# T-API-004: First dialogue chat → creates session + SSE stream
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_004_first_chat(client, db_pool):
    # Create requirement first
    req = await _create_req(client)
    req_id = req["req_id"]

    # Send first message
    resp = await client.post(
        "/api/dialogue/chat",
        json={"req_id": req_id, "message": "做一个用户管理系统", "session_id": None},
        headers={"Authorization": "Bearer test-token"},
    )
    # SSE stream — HTTP 200 with text/event-stream
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    # Parse SSE events from response body
    body = resp.text
    events = []
    for line in body.split("\n"):
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass

    # DB: session created
    async with db_pool.acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT * FROM dialogue_sessions WHERE req_id=$1::uuid", req_id,
        )
        assert sess is not None
        assert sess["status"] in ("active", "reopened")

        # Messages persisted
        msgs = await conn.fetch(
            "SELECT role, cycle FROM dialogue_messages WHERE session_id=$1::uuid "
            "ORDER BY sequence_number",
            sess["id"],
        )
        assert len(msgs) >= 2  # human + ai
        assert msgs[0]["role"] == "human"


# ══════════════════════════════════════════════════════════════════════════
# T-API-005: Multi-turn dialogue — same session
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_005_multi_turn(client, db_pool):
    req = await _create_req(client)
    req_id = req["req_id"]

    # First message
    r1 = await client.post(
        "/api/dialogue/chat",
        json={"req_id": req_id, "message": "做一个用户管理系统", "session_id": None},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r1.status_code == 200

    # Get session_id from events
    session_id = None
    for line in r1.text.split("\n"):
        if line.startswith("data: "):
            evt = json.loads(line[6:])
            if evt.get("session_id"):
                session_id = evt["session_id"]

    # If done event didn't carry session_id, look it up
    if not session_id:
        async with db_pool.acquire() as conn:
            session_id = str(await conn.fetchval(
                "SELECT id FROM dialogue_sessions WHERE req_id=$1::uuid", req_id,
            ))

    # Second message
    r2 = await client.post(
        "/api/dialogue/chat",
        json={"req_id": req_id, "message": "还需要支持角色管理", "session_id": session_id},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r2.status_code == 200

    # DB: sequence_number incremented
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM dialogue_messages WHERE session_id=$1::uuid AND cycle=0",
            session_id,
        )
        assert count >= 4  # 2 rounds × 2 messages each

        iterations = await conn.fetchval(
            "SELECT iterations FROM dialogue_sessions WHERE id=$1::uuid", session_id,
        )
        assert iterations >= 2


# ══════════════════════════════════════════════════════════════════════════
# T-API-006: session_id mismatch with req_id
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_006_session_mismatch(client, db_pool):
    req_a = await _create_req(client, "需求A")
    req_b = await _create_req(client, "需求B")

    # Create session for A
    await client.post(
        "/api/dialogue/chat",
        json={"req_id": req_a["req_id"], "message": "test A", "session_id": None},
        headers={"Authorization": "Bearer test-token"},
    )

    async with db_pool.acquire() as conn:
        sid_a = str(await conn.fetchval(
            "SELECT id FROM dialogue_sessions WHERE req_id=$1::uuid", req_a["req_id"],
        ))

    # Try to use session A with req B
    r = await client.post(
        "/api/dialogue/chat",
        json={"req_id": req_b["req_id"], "message": "test B", "session_id": sid_a},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code in (400, 403)


# ══════════════════════════════════════════════════════════════════════════
# T-API-007: Non-existent req_id
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_007_nonexistent_req(client):
    r = await client.post(
        "/api/dialogue/chat",
        json={"req_id": str(uuid.uuid4()), "message": "test", "session_id": None},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# T-API-008: req_id status that disallows dialogue
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_008_status_disallows_dialogue(client, db_pool):
    req = await _create_req(client)

    # Manually set status to 'analyzing_completed' (not rejected)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE requirements SET status='analyzing_completed' WHERE id=$1::uuid",
            req["req_id"],
        )

    r = await client.post(
        "/api/dialogue/chat",
        json={"req_id": req["req_id"], "message": "test", "session_id": None},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 400
