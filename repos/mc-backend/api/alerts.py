"""
Mission Control Backend - Alerts API
GET  /api/alerts          - List all alerts
PUT  /api/alerts/{id}     - Acknowledge an alert
POST /api/alerts/feishu   - Prometheus AlertManager webhook for Feishu
"""
import logging
import os
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Feishu webhook configuration
FEISHU_WEBHOOK = os.getenv("FEISHU_ALERT_WEBHOOK", "")

SEVERITY_COLORS = {
    "critical": "red",
    "warning": "orange",
    "info": "blue"
}

SEVERITY_EMOJIS = {
    "critical": "🔴",
    "warning": "🟠",
    "info": "🔵"
}


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


async def send_feishu_notification(alert_data: dict):
    """Send alert notification to Feishu via webhook."""
    if not FEISHU_WEBHOOK:
        logger.warning("FEISHU_ALERT_WEBHOOK not configured, skipping notification")
        return

    status = alert_data.get('status')  # firing or resolved
    labels = alert_data.get('labels', {})
    annotations = alert_data.get('annotations', {})

    severity = labels.get('severity', 'info')
    alertname = labels.get('alertname', 'Unknown')
    component = labels.get('component', 'N/A')

    # Build Feishu message
    if status == 'firing':
        title = f"{SEVERITY_EMOJIS.get(severity, '')} 告警触发 - {alertname}"
        color = SEVERITY_COLORS.get(severity, 'blue')
    else:
        title = f"✅ 告警恢复 - {alertname}"
        color = "green"

    message = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"content": title, "tag": "plain_text"},
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": (
                            f"**描述**: {annotations.get('description', 'N/A')}\n"
                            f"**组件**: {component}\n"
                            f"**严重程度**: {severity}\n"
                            f"**时间**: {alert_data.get('startsAt', 'N/A')}"
                        ),
                        "tag": "lark_md"
                    }
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看 Grafana"},
                            "url": "http://172.27.78.109:3000"
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看 Prometheus"},
                            "url": "http://172.27.78.109:9090"
                        }
                    ]
                }
            ]
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(FEISHU_WEBHOOK, json=message, timeout=10.0)
            if response.status_code == 200:
                logger.info(f"Feishu notification sent for alert: {alertname}")
            else:
                logger.error(f"Feishu notification failed: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error sending Feishu notification: {e}")


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


@router.post("/feishu")
async def handle_prometheus_alert(request: Request):
    """
    Prometheus AlertManager webhook endpoint for Feishu notifications.
    Receives alerts from AlertManager and forwards them to Feishu.
    """
    try:
        payload = await request.json()
        alerts = payload.get('alerts', [])

        logger.info(f"Received {len(alerts)} alert(s) from Prometheus AlertManager")

        for alert in alerts:
            try:
                await send_feishu_notification(alert)
            except Exception as e:
                logger.error(f"Error processing alert: {e}")

        return {"status": "ok", "processed": len(alerts)}
    except Exception as e:
        logger.error(f"Error in Feishu webhook handler: {e}")
        return {"status": "error", "detail": str(e)}
