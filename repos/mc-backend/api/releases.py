"""
Mission Control Backend - Releases API
GET  /api/releases          - List all releases
GET  /api/releases/{id}     - Get single release with full detail
"""
import logging
from typing import Optional, List, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/releases", tags=["releases"])


# ── Pydantic models ──────────────────────────────────────────────────────

class ReleaseRisk(BaseModel):
    description: str
    severity: str = "medium"
    mitigated: bool = False


class ReleaseStage(BaseModel):
    name: str
    status: str = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ReleaseRequirement(BaseModel):
    req_id: str
    title: str = ""
    status: str = "pending"


class ReleaseItem(BaseModel):
    id: str
    version: str
    status: str
    release_window_start: Optional[datetime] = None
    release_window_end: Optional[datetime] = None
    total_reqs: int = 0
    completed_reqs: int = 0
    progress: float = 0.0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReleaseDetail(ReleaseItem):
    requirements: list[ReleaseRequirement] = Field(default_factory=list)
    risks: list[ReleaseRisk] = Field(default_factory=list)
    stages: list[ReleaseStage] = Field(default_factory=list)


class ReleaseListResponse(BaseModel):
    items: list[ReleaseItem]
    total: int


# ── Helpers ──────────────────────────────────────────────────────────────

async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


def _format_release(row) -> ReleaseItem:
    return ReleaseItem(
        id=str(row["id"]),
        version=row["version"],
        status=row["status"],
        release_window_start=row["release_window_start"],
        release_window_end=row["release_window_end"],
        total_reqs=row["total_reqs"] or 0,
        completed_reqs=row["completed_reqs"] or 0,
        progress=float(row["progress"]) if row["progress"] else 0.0,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _format_release_detail(row) -> ReleaseDetail:
    requirements_raw = row["requirements"] if isinstance(row["requirements"], list) else []
    risks_raw = row["risks"] if isinstance(row["risks"], list) else []
    stages_raw = row["stages"] if isinstance(row["stages"], list) else []

    return ReleaseDetail(
        id=str(row["id"]),
        version=row["version"],
        status=row["status"],
        release_window_start=row["release_window_start"],
        release_window_end=row["release_window_end"],
        total_reqs=row["total_reqs"] or 0,
        completed_reqs=row["completed_reqs"] or 0,
        progress=float(row["progress"]) if row["progress"] else 0.0,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        requirements=[ReleaseRequirement(**r) for r in requirements_raw],
        risks=[ReleaseRisk(**r) for r in risks_raw],
        stages=[ReleaseStage(**r) for r in stages_raw],
    )


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=ReleaseListResponse)
async def list_releases():
    conn = await get_db()
    try:
        rows = await conn.fetch(
            """
            SELECT id, version, status, release_window_start, release_window_end,
                   total_reqs, completed_reqs, progress, created_at, updated_at
            FROM releases
            ORDER BY created_at DESC
            """
        )
        items = [_format_release(r) for r in rows]
        return ReleaseListResponse(items=items, total=len(items))
    finally:
        await conn.close()


@router.get("/{release_id}", response_model=ReleaseDetail)
async def get_release(release_id: str):
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            """
            SELECT id, version, status, release_window_start, release_window_end,
                   total_reqs, completed_reqs, progress,
                   requirements, risks, stages,
                   created_at, updated_at
            FROM releases
            WHERE id = $1::uuid
            """,
            release_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Release not found")
        return _format_release_detail(row)
    finally:
        await conn.close()
