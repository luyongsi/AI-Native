"""
prototypes.py — Prototype annotation API endpoints

POST /api/prototypes/annotate — Receive annotations and trigger A3 code generation
GET /api/prototypes/annotations/{req_id} — Get annotation history
"""
import json
import logging
from typing import Optional
from datetime import datetime, timezone

import nats
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prototypes", tags=["prototypes"])


class AnnotationData(BaseModel):
    """Single annotation on a prototype."""
    id: str
    type: str  # component/interaction/data-binding
    x: float
    y: float
    width: float
    height: float
    label: str
    properties: dict = {}


class AnnotatePrototypeRequest(BaseModel):
    """Request to annotate a prototype."""
    req_id: str
    image_url: str
    annotations: list[AnnotationData]


async def get_db_pool():
    """Get database pool from app context."""
    from main import DB_POOL
    if DB_POOL is None:
        raise RuntimeError("Database pool not initialized")
    return DB_POOL


async def get_nats_client() -> nats.NATS:
    """Get NATS client from app context."""
    from main import NATS_CLIENT
    if NATS_CLIENT is None:
        raise RuntimeError("NATS client not initialized")
    return NATS_CLIENT


@router.post("/annotate")
async def receive_annotations(
    request: AnnotatePrototypeRequest,
    db_pool=Depends(get_db_pool),
    nc=Depends(get_nats_client),
):
    """
    Receive prototype annotations from frontend.

    Stores annotations to database and triggers A3 code generation via NATS.

    Args:
        request: Annotation request with image URL and annotations list
        db_pool: Database connection pool
        nc: NATS client

    Returns:
        Status response
    """
    try:
        # Store annotations to database
        annotations_json = json.dumps(
            [a.dict() for a in request.annotations],
            ensure_ascii=False
        )

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prototype_annotations
                (req_id, image_url, annotations, version, created_at)
                VALUES ($1, $2, $3, 1, $4)
                """,
                request.req_id,
                request.image_url,
                annotations_json,
                datetime.now(timezone.utc),
            )
            logger.info(
                f"[API] Stored {len(request.annotations)} annotations for req={request.req_id}"
            )

        # Trigger A3 via NATS event
        event_data = {
            "req_id": request.req_id,
            "image_url": request.image_url,
            "annotations": [a.dict() for a in request.annotations],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await nc.publish(
            f"prototype.annotated.{request.req_id}",
            json.dumps(event_data, ensure_ascii=False).encode("utf-8"),
        )
        logger.info(f"[API] Published prototype.annotated event for req={request.req_id}")

        return {
            "status": "success",
            "message": "Annotations received, A3 triggered",
            "annotation_count": len(request.annotations),
            "req_id": request.req_id,
        }

    except Exception as e:
        logger.error(f"[API] Error storing annotations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to store annotations: {str(e)}")


@router.get("/annotations/{req_id}")
async def get_annotation_history(
    req_id: str,
    db_pool=Depends(get_db_pool),
):
    """
    Get annotation history for a prototype.

    Args:
        req_id: Request ID to fetch annotations for
        db_pool: Database connection pool

    Returns:
        List of annotation records with versions
    """
    try:
        async with db_pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT
                    id,
                    req_id,
                    image_url,
                    annotations,
                    version,
                    created_at
                FROM prototype_annotations
                WHERE req_id = $1
                ORDER BY created_at DESC
                LIMIT 50
                """,
                req_id,
            )

        return [
            {
                "id": r["id"],
                "req_id": r["req_id"],
                "image_url": r["image_url"],
                "annotations": json.loads(r["annotations"]),
                "version": r["version"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in records
        ]

    except Exception as e:
        logger.error(f"[API] Error fetching annotations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch annotations: {str(e)}")
