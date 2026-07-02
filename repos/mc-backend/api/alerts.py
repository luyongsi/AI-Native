"""
Mission Control Backend - Alerts API
GET  /api/alerts          - List all alerts
PUT  /api/alerts/{id}     - Acknowledge an alert
"""
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ── Pydantic models ──────────────────────────────────────────────────────

class AlertItem(BaseModel):
    id: str
    level: str
    title: str
    description: Optional[str] = None
    source: Optional[str] = None
    affected: Optional[str] = None
    root_cause: Optional[str] = None
    ai_suggestion: Optional[str] = None
    acknowledged: bool = False
    created_at: Optional[datetime] = None


class AlertListResponse(BaseModel):
    items: list[AlertItem]
    total: int


class AlertAcknowledgeRequest(BaseModel):
    acknowledged: bool


# ── Helpers ──────────────────────────────────────────────────────────────

async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


def _format_alert(row) -> AlertItem:
    return AlertItem(
        id=str(row["id"]),
        level=row["level"],
        title=row["title"],
        description=row["description"],
        source=row["source"],
        affected=row["affected"],
        root_cause=row["root_cause"],
        ai_suggestion=row["ai_suggestion"],
        acknowledged=row["acknowledged"],
        created_at=row["created_at"],
    )


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=AlertListResponse)
async def list_alerts(
    level: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = await get_db()
    try:
        conditions: list[str] = []
        params: list = []
        idx = 1
        if level:
            conditions.append(f"level = ${idx}")
            params.append(level)
            idx += 1
        if acknowledged is not None:
            conditions.append(f"acknowledged = ${idx}")
            params.append(acknowledged)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT id, level, title, description, source, affected,
                   root_cause, ai_suggestion, acknowledged, created_at
            FROM alerts
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) as cnt FROM alerts {where}",
            *params[: idx - 1] if conditions else [],
        )
        total = total_row["cnt"] if total_row else 0

        items = [_format_alert(r) for r in rows]
        return AlertListResponse(items=items, total=total)
    finally:
        await conn.close()


@router.put("/{alert_id}", response_model=AlertItem)
async def acknowledge_alert(alert_id: str, body: AlertAcknowledgeRequest):
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            """
            UPDATE alerts
            SET acknowledged = $1
            WHERE id = $2::uuid
            RETURNING id, level, title, description, source, affected,
                      root_cause, ai_suggestion, acknowledged, created_at
            """,
            body.acknowledged,
            alert_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        return _format_alert(row)
    finally:
        await conn.close()
