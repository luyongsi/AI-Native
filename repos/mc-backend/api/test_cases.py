"""
Mission Control Backend - Test Cases API
GET    /api/tests/{req_id}/cases          - List test cases for a requirement
POST   /api/tests/{req_id}/cases          - Create a new test case
GET    /api/tests/{req_id}/cases/{case_id} - Get single test case
PUT    /api/tests/{req_id}/cases/{case_id} - Update test case
DELETE /api/tests/{req_id}/cases/{case_id} - Delete test case
"""
import logging
from typing import Optional, Any
from datetime import datetime
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tests/{req_id}/cases", tags=["test_cases"])


# ── Pydantic models ──────────────────────────────────────────────────────

class TestStep(BaseModel):
    step_number: int
    action: str
    expected: str


class TestCaseCreate(BaseModel):
    title: str
    description: Optional[str] = None
    steps: Optional[list[TestStep]] = None
    preconditions: Optional[str] = None
    priority: str = "P2"
    tags: Optional[list[str]] = None


class TestCaseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[list[TestStep]] = None
    preconditions: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None


class TestCaseItem(BaseModel):
    id: str
    req_id: str
    title: str
    description: Optional[str] = None
    steps: list[TestStep] = Field(default_factory=list)
    preconditions: Optional[str] = None
    priority: str = "P2"
    status: str = "pending"
    tags: list[str] = Field(default_factory=list)
    ai_generated: bool = False
    last_run_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TestCaseListResponse(BaseModel):
    items: list[TestCaseItem]
    total: int


# ── Helpers ──────────────────────────────────────────────────────────────

async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


def _format_test_case(row) -> TestCaseItem:
    steps_raw = row["steps"] if isinstance(row["steps"], list) else []
    tags_raw = row["tags"] if isinstance(row["tags"], list) else []

    return TestCaseItem(
        id=str(row["id"]),
        req_id=str(row["req_id"]),
        title=row["title"],
        description=row["description"],
        steps=[TestStep(**s) for s in steps_raw],
        preconditions=row["preconditions"],
        priority=row["priority"],
        status=row["status"],
        tags=tags_raw,
        ai_generated=row["ai_generated"],
        last_run_at=row["last_run_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=TestCaseListResponse)
async def list_test_cases(
    req_id: str,
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = await get_db()
    try:
        # Verify requirement exists
        req = await conn.fetchrow(
            "SELECT id FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not req:
            raise HTTPException(status_code=404, detail="Requirement not found")

        conditions: list[str] = ["req_id = $1::uuid"]
        params: list = [req_id]
        idx = 2
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if priority:
            conditions.append(f"priority = ${idx}")
            params.append(priority)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}"

        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT id, req_id, title, description, steps, preconditions,
                   priority, status, tags, ai_generated, last_run_at,
                   created_at, updated_at
            FROM test_cases
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        count_where = f"WHERE {' AND '.join(conditions)}"
        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) as cnt FROM test_cases {count_where}",
            *params[: idx - 1],
        )
        total = total_row["cnt"] if total_row else 0

        items = [_format_test_case(r) for r in rows]
        return TestCaseListResponse(items=items, total=total)
    finally:
        await conn.close()


@router.post("", status_code=201, response_model=TestCaseItem)
async def create_test_case(req_id: str, body: TestCaseCreate):
    conn = await get_db()
    try:
        # Verify requirement exists
        req = await conn.fetchrow(
            "SELECT id FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not req:
            raise HTTPException(status_code=404, detail="Requirement not found")

        new_id = uuid.uuid4()
        steps_json = [s.model_dump(mode="json") for s in (body.steps or [])]
        tags_json = body.tags or []

        row = await conn.fetchrow(
            """
            INSERT INTO test_cases
                (id, req_id, title, description, steps, preconditions, priority,
                 status, tags, ai_generated)
            VALUES ($1, $2::uuid, $3, $4, $5::jsonb, $6, $7, 'pending', $8::jsonb, FALSE)
            RETURNING id, req_id, title, description, steps, preconditions,
                      priority, status, tags, ai_generated, last_run_at,
                      created_at, updated_at
            """,
            new_id,
            req_id,
            body.title,
            body.description,
            steps_json,
            body.preconditions,
            body.priority,
            tags_json,
        )

        logger.info(f"Test case created: {new_id} for req_id={req_id}")
        return _format_test_case(row)
    finally:
        await conn.close()


@router.get("/{case_id}", response_model=TestCaseItem)
async def get_test_case(req_id: str, case_id: str):
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            """
            SELECT id, req_id, title, description, steps, preconditions,
                   priority, status, tags, ai_generated, last_run_at,
                   created_at, updated_at
            FROM test_cases
            WHERE id = $1::uuid AND req_id = $2::uuid
            """,
            case_id,
            req_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Test case not found")
        return _format_test_case(row)
    finally:
        await conn.close()


@router.put("/{case_id}", response_model=TestCaseItem)
async def update_test_case(req_id: str, case_id: str, body: TestCaseUpdate):
    conn = await get_db()
    try:
        # Check existence
        existing = await conn.fetchrow(
            "SELECT id FROM test_cases WHERE id = $1::uuid AND req_id = $2::uuid",
            case_id,
            req_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Test case not found")

        # Build dynamic SET clause
        set_parts: list[str] = ["updated_at = NOW()"]
        params: list = []
        idx = 1

        if body.title is not None:
            set_parts.append(f"title = ${idx}")
            params.append(body.title)
            idx += 1
        if body.description is not None:
            set_parts.append(f"description = ${idx}")
            params.append(body.description)
            idx += 1
        if body.steps is not None:
            steps_json = [s.model_dump(mode="json") for s in body.steps]
            set_parts.append(f"steps = ${idx}::jsonb")
            params.append(steps_json)
            idx += 1
        if body.preconditions is not None:
            set_parts.append(f"preconditions = ${idx}")
            params.append(body.preconditions)
            idx += 1
        if body.priority is not None:
            set_parts.append(f"priority = ${idx}")
            params.append(body.priority)
            idx += 1
        if body.status is not None:
            set_parts.append(f"status = ${idx}")
            params.append(body.status)
            idx += 1
        if body.tags is not None:
            set_parts.append(f"tags = ${idx}::jsonb")
            params.append(body.tags)
            idx += 1

        params.extend([case_id, req_id])
        row = await conn.fetchrow(
            f"""
            UPDATE test_cases
            SET {', '.join(set_parts)}
            WHERE id = ${idx}::uuid AND req_id = ${idx + 1}::uuid
            RETURNING id, req_id, title, description, steps, preconditions,
                      priority, status, tags, ai_generated, last_run_at,
                      created_at, updated_at
            """,
            *params,
        )

        logger.info(f"Test case updated: {case_id}")
        return _format_test_case(row)
    finally:
        await conn.close()


@router.delete("/{case_id}")
async def delete_test_case(req_id: str, case_id: str):
    conn = await get_db()
    try:
        result = await conn.execute(
            """
            DELETE FROM test_cases
            WHERE id = $1::uuid AND req_id = $2::uuid
            """,
            case_id,
            req_id,
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Test case not found")

        logger.info(f"Test case deleted: {case_id}")
        return {"deleted": True, "case_id": case_id}
    finally:
        await conn.close()
