"""
Mission Control Backend - Notifications API
GET /api/notifications - List notifications (optional ?unread=true filter)
"""
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ── Pydantic models ──────────────────────────────────────────────────────

class NotificationItem(BaseModel):
    id: str
    type: str
    level: str
    title: str
    description: Optional[str] = None
    read: bool = False
    link: Optional[str] = None
    created_at: Optional[datetime] = None


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    total: int


# ── Helpers ──────────────────────────────────────────────────────────────

async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


def _format_notification(row) -> NotificationItem:
    return NotificationItem(
        id=str(row["id"]),
        type=row["type"],
        level=row["level"],
        title=row["title"],
        description=row["description"],
        read=row["read"],
        link=row["link"],
        created_at=row["created_at"],
    )


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = await get_db()
    try:
        conditions: list[str] = []
        params: list = []
        idx = 1
        if unread is not None:
            conditions.append(f"read = ${idx}")
            params.append(not unread)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT id, type, level, title, description, read, link, created_at
            FROM notifications
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) as cnt FROM notifications {where}",
            *params[: idx - 1] if conditions else [],
        )
        total = total_row["cnt"] if total_row else 0

        items = [_format_notification(r) for r in rows]
        return NotificationListResponse(items=items, total=total)
    finally:
        await conn.close()
