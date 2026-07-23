"""
Mission Control Backend — Dialogue API (A1 HTTP+SSE Interface)

Endpoints:
  POST /api/dialogue/chat       — Send message, get SSE streaming analysis
  POST /api/dialogue/confirm    — Confirm completion, persist + outbox
  GET  /api/dialogue/history/{session_id} — Load history by cycle
  GET  /api/dialogue/current/{req_id}     — Get current session status
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dialogue", tags=["dialogue"])

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "dev-internal-key")


# ── Pydantic models ──────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    req_id: str
    message: str
    session_id: Optional[str] = None


class ConfirmRequest(BaseModel):
    session_id: str
    final_notes: Optional[str] = None


class StatusUpdateRequest(BaseModel):
    status: str
    gate_rejection_count: Optional[int] = None
    last_gate_rejection: Optional[dict] = None
    # Phase 3 extensions
    tech_prep_status: Optional[str] = None
    tech_prep_revision_count: Optional[int] = None
    # Phase 2 extensions
    design_status: Optional[str] = None
    design_revision_count: Optional[int] = None


# ── DB helper ────────────────────────────────────────────────────────────

async def _get_conn(timeout: float = 10.0):
    from main import DB_POOL
    return await asyncio.wait_for(DB_POOL.acquire(), timeout=timeout)


# ── JWT helpers ──────────────────────────────────────────────────────────

def _jwt_claims(authorization: Optional[str] = Header(None)) -> dict:
    """Extract user claims from JWT Bearer token.

    In production this validates the JWT signature.
    For dev it falls back to a default user.
    """
    if not authorization or not authorization.startswith("Bearer "):
        # Dev fallback — return default dev user instead of 401
        return {"sub": "dev-user", "name": "Dev User"}

    token = authorization[7:]
    try:
        import jwt as pyjwt
        claims = pyjwt.decode(token, options={"verify_signature": False})
        return {
            "sub": claims.get("sub", "dev-user"),
            "name": claims.get("name", "Dev User"),
        }
    except Exception:
        # Dev fallback
        return {"sub": token[:50], "name": "Dev User"}


def _api_key_auth(x_api_key: Optional[str] = Header(None)):
    if not x_api_key or x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── SSE formatting ───────────────────────────────────────────────────────

def _format_sse(event: dict) -> str:
    event_type = event["type"]
    payload = {k: v for k, v in event.items() if k != "type"}
    return "event: {t}\ndata: {d}\n\n".format(
        t=event_type, d=json.dumps(payload, ensure_ascii=False),
    )


# ══════════════════════════════════════════════════════════════════════════
# POST /api/dialogue/chat  — send message, return SSE stream
# ══════════════════════════════════════════════════════════════════════════

@router.post("/chat")
async def dialogue_chat(body: ChatRequest, claims: dict = Depends(_jwt_claims)):
    """Start or continue a dialogue. Returns SSE stream."""
    return StreamingResponse(
        _stream_dialogue(body, claims),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_dialogue(body: ChatRequest, claims: dict):
    conn = await _get_conn()
    try:
        # ── 1. Validate req_id ──────────────────────────────────────────
        req = await conn.fetchrow(
            "SELECT id, status, gate_rejection_count, requirement_draft "
            "FROM requirements WHERE id = $1::uuid",
            body.req_id,
        )
        if not req:
            yield _format_sse({"type": "error", "content": "需求不存在"})
            return
        if req["status"] not in ("draft", "gate_rejected"):
            yield _format_sse({"type": "error", "content": "当前需求状态不允许对话"})
            return

        creator_id = claims.get("sub", "dev-user")
        creator_name = claims.get("name", "Dev User")
        cycle = req["gate_rejection_count"] or 0

        # ── 2. Session management + user message INSERT (atomic TX) ────
        # Wrap session creation + FOR UPDATE + sequence calc + INSERT in
        # a single transaction to prevent the duplicate-key race condition.
        async with conn.transaction():
            # Lock requirements row to prevent concurrent session creation
            await conn.execute(
                "SELECT id FROM requirements WHERE id = $1::uuid FOR UPDATE",
                body.req_id,
            )

            if not body.session_id:
                existing = await conn.fetchval(
                    "SELECT id FROM dialogue_sessions WHERE req_id = $1::uuid",
                    body.req_id,
                )
                if existing:
                    session_id = str(existing)
                    sess_status = await conn.fetchval(
                        "SELECT status FROM dialogue_sessions WHERE id = $1::uuid",
                        existing,
                    )
                else:
                    session_status = "active"
                    if req["status"] == "gate_rejected":
                        session_status = "reopened"
                    session_id = str(uuid.uuid4())
                    await conn.execute(
                        """INSERT INTO dialogue_sessions
                           (id, req_id, status, creator_user_id, creator_name)
                           VALUES ($1::uuid, $2::uuid, $3, $4, $5)""",
                        session_id, body.req_id, session_status, creator_id, creator_name,
                    )
                    sess_status = session_status
            else:
                session_id = body.session_id
                sess_row = await conn.fetchrow(
                    "SELECT id, req_id, status FROM dialogue_sessions WHERE id = $1::uuid",
                    session_id,
                )
                if not sess_row:
                    yield _format_sse({"type": "error", "content": "会话不存在"})
                    return
                if str(sess_row["req_id"]) != body.req_id:
                    yield _format_sse({"type": "error", "content": "会话不属于该需求"})
                    return
                if sess_row["status"] not in ("active", "reopened"):
                    yield _format_sse({"type": "error", "content": "会话状态不允许对话"})
                    return
                sess_status = sess_row["status"]

            # Lock session row inside transaction
            await conn.execute(
                "SELECT id FROM dialogue_sessions WHERE id = $1::uuid FOR UPDATE",
                session_id,
            )

            max_seq = await conn.fetchval(
                "SELECT COALESCE(MAX(sequence_number), 0) FROM dialogue_messages "
                "WHERE session_id = $1::uuid AND cycle = $2",
                session_id, cycle,
            )
            user_seq = (max_seq or 0) + 1

            # Insert user message — guarded by transaction lock
            await conn.execute(
                """INSERT INTO dialogue_messages
                   (session_id, role, content, cycle, sequence_number)
                   VALUES ($1::uuid, 'human', $2::jsonb, $3, $4)""",
                session_id,
                json.dumps({"text": body.message}),
                cycle,
                user_seq,
            )
            await conn.execute(
                "UPDATE dialogue_sessions SET last_updated = NOW() WHERE id = $1::uuid",
                session_id,
            )

        # ── 3. Load conversation history ─────────────────────────
        hist_rows = await conn.fetch(
            """SELECT role, content, cycle, sequence_number
               FROM dialogue_messages
               WHERE session_id = $1::uuid
               ORDER BY sequence_number""",
            session_id,
        )
        history = [dict(r) for r in hist_rows]

        current_draft = req["requirement_draft"]
        if isinstance(current_draft, str):
            try:
                current_draft = json.loads(current_draft)
            except (json.JSONDecodeError, TypeError):
                current_draft = None

        # Release DB connection before long-running LLM analysis
        # to keep the pool available for other requests.
        await conn.close()
        conn = None

        import sys
        sys.path.insert(0, "/opt/ai-native/repos/agent-workers")
        from a1.agent import A1Agent
        agent = A1Agent()

        accumulated_draft = current_draft or {}
        clarification_items = None
        wireframe_data = None
        knowledge_sources = []
        mcp_tools_used = []
        final_confidence = 0.0

        async for event in agent.analyze(
            req_id=body.req_id,
            session_id=session_id,
            user_message=body.message,
            history=history,
            current_draft=current_draft,
            cycle=cycle,
        ):
            yield _format_sse(event)

            # Collect data for snapshot
            if event["type"] == "draft_update":
                accumulated_draft = event["draft"]
            elif event["type"] == "clarification":
                clarification_items = event.get("items", [])
            elif event["type"] == "knowledge":
                knowledge_sources = event.get("sources", [])
            elif event["type"] == "wireframe":
                wireframe_data = event.get("data")
            elif event["type"] == "done":
                final_confidence = event.get("confidence_score", 0.0)
                mcp_tools_used = event.get("mcp_tools_used", [])
                # done event carries the final draft with BDD acceptance_criteria applied
                if event.get("draft"):
                    accumulated_draft = event["draft"]

        # ── 4. Persist AI message + snapshot ─────────────────────────
        # Re-acquire connection for final DB writes.
        conn = await _get_conn()
        # The insert of the AI reply message needs its own transaction
        # because the lock from step 2 was released after commit.
        ai_seq = user_seq + 1
        snapshot_id = None

        async with conn.transaction():
            # Lock session row again for the AI message insert
            await conn.execute(
                "SELECT id FROM dialogue_sessions WHERE id = $1::uuid FOR UPDATE",
                session_id,
            )

            # Re-read max_seq to be safe
            actual_max = await conn.fetchval(
                "SELECT COALESCE(MAX(sequence_number), 0) FROM dialogue_messages "
                "WHERE session_id = $1::uuid AND cycle = $2",
                session_id, cycle,
            )
            ai_seq = actual_max + 1

            if accumulated_draft:
                snapshot_id = await conn.fetchval(
                    """INSERT INTO understanding_snapshots
                       (session_id, iteration, cycle, draft, clarification_points,
                        confidence_score, knowledge_sources, mcp_tools_used, wireframe_data)
                       VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6, $7::jsonb, $8::jsonb, $9::jsonb)
                       RETURNING id""",
                    session_id,
                    (await conn.fetchval(
                        "SELECT COALESCE(MAX(iteration), 0) + 1 FROM understanding_snapshots "
                        "WHERE session_id = $1::uuid", session_id,
                    )) or 1,
                    cycle,
                    json.dumps(accumulated_draft, ensure_ascii=False),
                    json.dumps(clarification_items or [], ensure_ascii=False),
                    final_confidence,
                    json.dumps(knowledge_sources, ensure_ascii=False),
                    json.dumps(mcp_tools_used, ensure_ascii=False),
                    json.dumps(wireframe_data, ensure_ascii=False) if wireframe_data else None,
                )

            # Build AI message content (structured summary, not raw LLM output)
            ai_content = {
                "text": accumulated_draft.get("description", "")[:200] if accumulated_draft else "",
                "draft_preview": {
                    k: accumulated_draft.get(k)
                    for k in ["title", "domain"]
                    if accumulated_draft and k in accumulated_draft
                } if accumulated_draft else {},
                "clarifications": [
                    {"question": c["question"], "suggestion": c["suggestion"]}
                    for c in (clarification_items or [])
                ],
            }
            # Add counts
            if accumulated_draft:
                entities = accumulated_draft.get("entities", [])
                use_cases = accumulated_draft.get("use_cases", [])
                ac = accumulated_draft.get("acceptance_criteria", [])
                ai_content["draft_preview"]["entities_count"] = len(entities) if isinstance(entities, list) else 0
                ai_content["draft_preview"]["use_cases_count"] = len(use_cases) if isinstance(use_cases, list) else 0
                ai_content["draft_preview"]["acceptance_criteria_count"] = len(ac) if isinstance(ac, list) else 0

            await conn.execute(
                """INSERT INTO dialogue_messages
                   (session_id, role, content, cycle, sequence_number, understanding_snapshot_id)
                   VALUES ($1::uuid, 'ai', $2::jsonb, $3, $4, $5)""",
                session_id,
                json.dumps(ai_content, ensure_ascii=False),
                cycle,
                ai_seq,
                snapshot_id,
            )

            # Update session counters
            await conn.execute(
                """UPDATE dialogue_sessions
                   SET iterations = iterations + 1,
                       total_messages = total_messages + 2,
                       confidence_score = $2,
                       last_updated = NOW()
                   WHERE id = $1::uuid""",
                session_id, final_confidence,
            )

    except Exception as e:
        logger.exception("[dialogue] chat error")
        try:
            yield _format_sse({"type": "error", "content": "服务器错误: {e}".format(e=str(e)[:200])})
        except Exception:
            pass
    finally:
        if conn is not None:
            await conn.close()


# ══════════════════════════════════════════════════════════════════════════
# POST /api/dialogue/confirm  — persist + outbox
# ══════════════════════════════════════════════════════════════════════════

@router.post("/confirm")
async def dialogue_confirm(body: ConfirmRequest, claims: dict = Depends(_jwt_claims)):
    """Confirm dialogue completion. Persists to requirements + agent_results + outbox."""
    conn = await _get_conn()
    try:
        async with conn.transaction():
            # Lock session + requirements
            sess = await conn.fetchrow(
                "SELECT * FROM dialogue_sessions WHERE id = $1::uuid FOR UPDATE",
                body.session_id,
            )
            if not sess:
                raise HTTPException(status_code=404, detail="会话不存在")
            if sess["status"] not in ("active", "reopened"):
                raise HTTPException(status_code=400, detail="会话状态不允许确认")

            req = await conn.fetchrow(
                "SELECT * FROM requirements WHERE id = $1::uuid FOR UPDATE",
                sess["req_id"],
            )
            if not req:
                raise HTTPException(status_code=404, detail="需求不存在")

            cycle = req["gate_rejection_count"] or 0

            # Idempotency check
            existing = await conn.fetchval(
                "SELECT 1 FROM agent_results WHERE req_id = $1::uuid AND agent_key = 'A1' AND cycle = $2",
                sess["req_id"], cycle,
            )
            if existing:
                return {
                    "ok": True,
                    "req_id": str(sess["req_id"]),
                    "session_id": body.session_id,
                    "cycle": cycle,
                    "status": "analyzing_completed",
                    "already_confirmed": True,
                }

            # Read latest snapshot
            snap = await conn.fetchrow(
                """SELECT draft, confidence_score, wireframe_data
                   FROM understanding_snapshots
                   WHERE session_id = $1::uuid AND cycle = $2
                   ORDER BY created_at DESC LIMIT 1""",
                body.session_id, cycle,
            )

            if not snap:
                raise HTTPException(status_code=400, detail="没有可确认的分析结果")

            draft = snap["draft"]
            if isinstance(draft, str):
                draft = json.loads(draft)

            title = draft.get("title") if isinstance(draft, dict) else None
            confidence = float(snap["confidence_score"]) if snap.get("confidence_score") else float(sess.get("confidence_score") or 0)

            # Wireframe S3 upload
            wireframe_url = None
            wf_data = snap.get("wireframe_data")
            if wf_data:
                try:
                    from s3_proxy import upload_json
                    wf_key = "wireframes/{req_id}/{cycle}.json".format(
                        req_id=str(sess["req_id"]), cycle=cycle,
                    )
                    wireframe_url = await upload_json(
                        wf_data if isinstance(wf_data, dict) else json.loads(wf_data),
                        wf_key,
                    )
                except Exception:
                    logger.warning("[dialogue] S3 upload failed for wireframe, continuing")
                    wireframe_url = None

            # ── Update requirements ─────────────────────────────────────
            now = datetime.now(timezone.utc)
            update_sql = """UPDATE requirements SET
                title = $2, requirement_draft = $3::jsonb, confidence_score = $4,
                status = 'analyzing_completed', analyzed_at = $5,
                updated_at = $5"""
            params: list = [
                sess["req_id"], title,
                json.dumps(draft, ensure_ascii=False),
                confidence, now,
            ]

            if cycle > 0:
                update_sql += ", revision_count = revision_count + 1, last_revised_at = $6"
                params.append(now)
            update_sql += " WHERE id = $1::uuid"

            await conn.execute(update_sql, *params)

            # ── Insert agent_results ────────────────────────────────────
            await conn.execute(
                """INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
                   VALUES ($1::uuid, 'A1', $2, 'completed', $3::jsonb)""",
                sess["req_id"], cycle,
                json.dumps({
                    "requirement_draft": draft,
                    "wireframe_url": wireframe_url,
                }, ensure_ascii=False),
            )

            # ── Update dialogue_sessions ────────────────────────────────
            confirmation_entry = {
                "confirmed_at": now.isoformat(),
                "cycle": cycle,
                "final_notes": body.final_notes or "",
            }
            existing_confirmations = sess["human_confirmations"] or []
            if isinstance(existing_confirmations, str):
                existing_confirmations = json.loads(existing_confirmations)
            if not isinstance(existing_confirmations, list):
                existing_confirmations = []
            existing_confirmations.append(confirmation_entry)

            await conn.execute(
                """UPDATE dialogue_sessions SET
                   status = 'completed',
                   human_confirmations = $2::jsonb,
                   first_confirmed_at = COALESCE(first_confirmed_at, $3),
                   last_confirmed_at = $3,
                   last_updated = $3
                   WHERE id = $1::uuid""",
                body.session_id,
                json.dumps(existing_confirmations, ensure_ascii=False),
                now,
            )

            # ── Outbox: write event_log ─────────────────────────────────
            nats_payload = {
                "req_id": str(sess["req_id"]),
                "session_id": str(sess["id"]),
                "cycle": cycle,
                "draft": draft,
                "wireframe_url": wireframe_url,
                "confidence_score": confidence,
                "iterations": sess["iterations"] or 0,
                "total_messages": sess["total_messages"] or 0,
                "timestamp": now.isoformat(),
            }
            await conn.execute(
                """INSERT INTO event_log
                   (req_id, session_id, cycle, event_name, direction, outbox_status, payload)
                   VALUES ($1::uuid, $2::uuid, $3, 'agent.result.A1', 'OUT', 'pending', $4::jsonb)""",
                sess["req_id"], body.session_id, cycle,
                json.dumps(nats_payload, ensure_ascii=False),
            )

        return {
            "ok": True,
            "req_id": str(sess["req_id"]),
            "session_id": body.session_id,
            "cycle": cycle,
            "status": "analyzing_completed",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[dialogue] confirm error")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await conn.close()


# ══════════════════════════════════════════════════════════════════════════
# GET /api/dialogue/history/{session_id}
# ══════════════════════════════════════════════════════════════════════════

@router.get("/history/{session_id}")
async def dialogue_history(session_id: str, claims: dict = Depends(_jwt_claims)):
    """Load dialogue history, grouped by cycle."""
    conn = await _get_conn()
    try:
        sess = await conn.fetchrow(
            "SELECT * FROM dialogue_sessions WHERE id = $1::uuid",
            session_id,
        )
        if not sess:
            raise HTTPException(status_code=404, detail="会话不存在")

        # Permission: user must own the session or requirement
        creator = sess["creator_user_id"]
        req_creator = await conn.fetchval(
            "SELECT creator_user_id FROM requirements WHERE id = $1::uuid",
            sess["req_id"],
        )
        user = claims.get("sub", "dev-user")
        if user != creator and user != req_creator:
            raise HTTPException(status_code=403, detail="无权访问该会话")

        # Load messages
        msg_rows = await conn.fetch(
            """SELECT id, role, content, cycle, sequence_number, timestamp
               FROM dialogue_messages
               WHERE session_id = $1::uuid
               ORDER BY cycle, sequence_number""",
            session_id,
        )

        # Load draft snapshots per cycle from agent_results (confirmed runs)
        ar_rows = await conn.fetch(
            """SELECT cycle, artifact
               FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = 'A1'
               ORDER BY cycle""",
            sess["req_id"],
        )

        # Also load from understanding_snapshots (every chat turn, not just confirmed)
        us_rows = await conn.fetch(
            """SELECT cycle, draft, wireframe_data
               FROM understanding_snapshots
               WHERE session_id = $1::uuid
               ORDER BY cycle DESC, created_at DESC, id DESC""",
            session_id,
        )

        # Load confirmations
        confirmations = sess["human_confirmations"] or []
        if isinstance(confirmations, str):
            confirmations = json.loads(confirmations)
        conf_map = {c["cycle"]: c for c in (confirmations or [])}

        # Build cycles
        cycles_dict: dict[int, dict] = {}
        for msg in msg_rows:
            cycle = msg["cycle"]
            c = cycles_dict.setdefault(cycle, {
                "cycle": cycle,
                "status": "completed" if cycle in conf_map else "revision",
                "confirmed_at": conf_map.get(cycle, {}).get("confirmed_at"),
                "messages": [],
                "draft_snapshot": None,
            })
            content = msg["content"]
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    content = {"text": content}
            c["messages"].append({
                "id": msg["id"],
                "role": msg["role"],
                "content": content,
                "timestamp": msg["timestamp"].isoformat() if msg["timestamp"] else None,
                "sequence_number": msg["sequence_number"],
            })

        for ar in ar_rows:
            cycle = ar["cycle"]
            if cycle in cycles_dict:
                artifact = ar["artifact"]
                if isinstance(artifact, str):
                    artifact = json.loads(artifact)
                if isinstance(artifact, dict):
                    cycles_dict[cycle]["draft_snapshot"] = artifact.get("requirement_draft")

        # Fill in draft_snapshot from understanding_snapshots for un-confirmed cycles
        last_draft = None
        last_wireframe = None
        for us in us_rows:
            cycle = us["cycle"]
            if cycle in cycles_dict and not cycles_dict[cycle]["draft_snapshot"]:
                draft = us["draft"]
                if isinstance(draft, str):
                    try:
                        draft = json.loads(draft)
                    except (json.JSONDecodeError, TypeError):
                        draft = None
                if isinstance(draft, dict):
                    cycles_dict[cycle]["draft_snapshot"] = draft
            # Capture latest draft and wireframe across all cycles for
            # the response top-level, so the frontend can restore the
            # right-panel preview on page load regardless of cycle.
            if not last_draft and us.get("draft"):
                draft = us["draft"]
                if isinstance(draft, str):
                    try:
                        draft = json.loads(draft)
                    except (json.JSONDecodeError, TypeError):
                        draft = None
                if isinstance(draft, dict):
                    last_draft = draft
            if not last_wireframe and us.get("wireframe_data"):
                wf = us["wireframe_data"]
                if isinstance(wf, str):
                    try:
                        wf = json.loads(wf)
                    except (json.JSONDecodeError, TypeError):
                        wf = None
                if isinstance(wf, dict):
                    last_wireframe = wf

        cycles_list = sorted(cycles_dict.values(), key=lambda c: c["cycle"])

        return {
            "session_id": session_id,
            "req_id": str(sess["req_id"]),
            "cycles": cycles_list,
            "current_draft": last_draft,
            "current_wireframe": last_wireframe,
        }

    except HTTPException:
        raise
    finally:
        await conn.close()


# ══════════════════════════════════════════════════════════════════════════
# GET /api/dialogue/current/{req_id}
# ══════════════════════════════════════════════════════════════════════════

@router.get("/current/{req_id}")
async def dialogue_current(req_id: str, claims: dict = Depends(_jwt_claims)):
    """Get current session status for a requirement."""
    conn = await _get_conn()
    try:
        req = await conn.fetchrow(
            "SELECT id, gate_rejection_count FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not req:
            raise HTTPException(status_code=404, detail="需求不存在")

        sess = await conn.fetchrow(
            "SELECT * FROM dialogue_sessions WHERE req_id = $1::uuid",
            req_id,
        )
        if not sess:
            return {
                "req_id": req_id,
                "session_id": None,
                "status": "no_session",
                "cycle": req["gate_rejection_count"] or 0,
            }

        return {
            "req_id": req_id,
            "session_id": str(sess["id"]),
            "status": sess["status"],
            "cycle": req["gate_rejection_count"] or 0,
            "iterations": sess["iterations"] or 0,
            "total_messages": sess["total_messages"] or 0,
            "confidence_score": float(sess["confidence_score"]) if sess["confidence_score"] else None,
        }
    finally:
        await conn.close()


# ══════════════════════════════════════════════════════════════════════════
# POST /api/requirements/{req_id}/status  — Orchestrator calls this
# ══════════════════════════════════════════════════════════════════════════

_requirements_status_router = APIRouter(prefix="/api/requirements", tags=["requirements-status"])


@_requirements_status_router.post("/{req_id}/status")
async def update_req_status(
    req_id: str,
    body: StatusUpdateRequest,
    api_key: str = Depends(_api_key_auth),
):
    """Orchestrator updates requirement status (e.g. gate_rejected)."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT id, status FROM requirements WHERE id = $1::uuid FOR UPDATE",
            req_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="需求不存在")

        # White-list fields
        if body.status:
            await conn.execute(
                "UPDATE requirements SET status = $2, updated_at = NOW() WHERE id = $1::uuid",
                req_id, body.status,
            )
        if body.gate_rejection_count is not None:
            await conn.execute(
                "UPDATE requirements SET gate_rejection_count = $2, updated_at = NOW() WHERE id = $1::uuid",
                req_id, body.gate_rejection_count,
            )
        if body.last_gate_rejection is not None:
            await conn.execute(
                "UPDATE requirements SET last_gate_rejection = $2::jsonb, updated_at = NOW() WHERE id = $1::uuid",
                req_id, json.dumps(body.last_gate_rejection, ensure_ascii=False),
            )

        # Phase 2: design_status + design_revision_count
        if body.design_status is not None:
            await conn.execute(
                "UPDATE requirements SET design_status = $2, updated_at = NOW() WHERE id = $1::uuid",
                req_id, body.design_status,
            )
        if body.design_revision_count is not None:
            await conn.execute(
                "UPDATE requirements SET design_revision_count = $2, updated_at = NOW() WHERE id = $1::uuid",
                req_id, body.design_revision_count,
            )

        # Phase 3: tech_prep_status + tech_prep_revision_count
        if body.tech_prep_status is not None:
            await conn.execute(
                "UPDATE requirements SET tech_prep_status = $2, updated_at = NOW() WHERE id = $1::uuid",
                req_id, body.tech_prep_status,
            )
        if body.tech_prep_revision_count is not None:
            await conn.execute(
                "UPDATE requirements SET tech_prep_revision_count = $2, updated_at = NOW() WHERE id = $1::uuid",
                req_id, body.tech_prep_revision_count,
            )

        # Audit
        cycle = body.gate_rejection_count or 0
        await conn.execute(
            """INSERT INTO event_log (req_id, cycle, event_name, direction, payload)
               VALUES ($1::uuid, $2, 'context.ready.A1', 'IN', $3::jsonb)""",
            req_id, cycle,
            json.dumps({
                "req_id": req_id,
                "status": body.status,
                "gate_rejection_count": body.gate_rejection_count,
                "last_gate_rejection": body.last_gate_rejection,
            }, ensure_ascii=False),
        )

        return {"ok": True, "req_id": req_id, "status": body.status}
    finally:
        await conn.close()
