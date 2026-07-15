"""
MC Backend — NATS subscriber for context.ready.A1 (Gate0 rejection) and
context.ready.gate0/gate1/gate2 (Gate approval creation).

Design:
  - context.ready.A1: Gate0 rejected → reopen session, inject system message
  - context.ready.gate0: Orchestrator reached Gate0 → pre-create approval record
  - context.ready.gate1: Orchestrator reached Gate1 → pre-create approval record
  - context.ready.gate2: Orchestrator reached Gate2 → pre-create approval record
"""
from __future__ import annotations

import json
import logging

import nats

logger = logging.getLogger(__name__)


async def subscribe_context_ready_gate0(db_pool, nats_url: str):
    """Subscribe to context.ready.gate0 — pre-create approval record on arrival."""
    while True:
        try:
            nc = await nats.connect(nats_url)
            js = nc.jetstream()
            await js.subscribe("context.ready.gate0", cb=_make_gate0_handler(db_pool),
                               stream="AI_NATIVE_EVENTS", durable="mc_backend_gate0")
            logger.info("[nats-sub] Subscribed to context.ready.gate0")
            try:
                while nc.is_connected:
                    await __import__("asyncio").sleep(60)
            except Exception:
                pass
            finally:
                if nc.is_connected:
                    await nc.drain()
        except Exception as e:
            logger.error("[nats-sub] context.ready.gate0 connection error: %s — retrying in 5s", e)
            await __import__("asyncio").sleep(5)


async def subscribe_context_ready_gate1(db_pool, nats_url: str):
    """Subscribe to context.ready.gate1 — pre-create Gate1 approval record."""
    while True:
        try:
            nc = await nats.connect(nats_url)
            js = nc.jetstream()
            await js.subscribe("context.ready.gate1", cb=_make_gate_handler(db_pool, gate_level=1),
                               stream="AI_NATIVE_EVENTS", durable="mc_backend_gate1")
            logger.info("[nats-sub] Subscribed to context.ready.gate1")
            try:
                while nc.is_connected:
                    await __import__("asyncio").sleep(60)
            except Exception:
                pass
            finally:
                if nc.is_connected:
                    await nc.drain()
        except Exception as e:
            logger.error("[nats-sub] context.ready.gate1 connection error: %s — retrying in 5s", e)
            await __import__("asyncio").sleep(5)


async def subscribe_context_ready_a1(db_pool, nats_url: str):
    """Start a background asyncio task that subscribes to context.ready.A1.

    Called once at MC Backend startup. Runs forever (reconnects on disconnect).
    """
    while True:
        try:
            nc = await nats.connect(nats_url)
            js = nc.jetstream()
            await js.subscribe("context.ready.A1", cb=_make_handler(db_pool),
                               stream="AI_NATIVE_EVENTS", durable="mc_backend_a1")
            logger.info("[nats-sub] Subscribed to context.ready.A1")
            try:
                while nc.is_connected:
                    await __import__("asyncio").sleep(60)
            except Exception:
                pass
            finally:
                if nc.is_connected:
                    await nc.drain()
        except Exception as e:
            logger.error("[nats-sub] Connection error: %s — retrying in 5s", e)
            await __import__("asyncio").sleep(5)


async def subscribe_context_ready_gate2(db_pool, nats_url: str):
    """Subscribe to context.ready.gate2 — pre-create Gate2 approval record."""
    while True:
        try:
            nc = await nats.connect(nats_url)
            js = nc.jetstream()
            await js.subscribe("context.ready.gate2", cb=_make_gate_handler(db_pool, gate_level=2),
                               stream="AI_NATIVE_EVENTS", durable="mc_backend_gate2")
            logger.info("[nats-sub] Subscribed to context.ready.gate2")
            try:
                while nc.is_connected:
                    await __import__("asyncio").sleep(60)
            except Exception:
                pass
            finally:
                if nc.is_connected:
                    await nc.drain()
        except Exception as e:
            logger.error("[nats-sub] context.ready.gate2 connection error: %s — retrying in 5s", e)
            await __import__("asyncio").sleep(5)


# ── context.ready.gate0 handler ───────────────────────────────────────────


def _make_gate0_handler(db_pool):
    async def handle(msg):
        payload = json.loads(msg.data.decode())
        req_id = payload.get("req_id")
        session_id = payload.get("session_id", "")
        cycle = payload.get("cycle", 0)

        if not req_id:
            logger.warning("[nats-sub] context.ready.gate0 missing req_id")
            await msg.ack()
            return

        conn = await db_pool.acquire()
        try:
            # Idempotent pre-create
            existing = await conn.fetchrow(
                """SELECT id FROM approvals
                   WHERE req_id = $1::uuid AND gate_level = 0 AND cycle = $2 AND status = 'pending'""",
                req_id, cycle,
            )

            if not existing:
                import datetime
                now = datetime.datetime.now(datetime.timezone.utc)
                await conn.execute(
                    """INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, created_at)
                       VALUES ($1::uuid, $2::uuid, 0, $3, 'pending', $4)""",
                    req_id, session_id or None, cycle, now,
                )
                logger.info("[nats-sub] Pre-created Gate0 approval for req=%s cycle=%d", req_id, cycle)

                # Audit
                await conn.execute(
                    """INSERT INTO event_log
                       (req_id, session_id, cycle, event_name, direction, payload)
                       VALUES ($1::uuid, $2::uuid, $3, 'context.ready.gate0', 'IN', $4::jsonb)""",
                    req_id, session_id or None, cycle,
                    json.dumps(payload, ensure_ascii=False),
                )

                # WebSocket notify (best-effort)
                try:
                    from ws.ws_gateway import notify_session
                    await notify_session(session_id, {
                        "type": "gate0_ready",
                        "req_id": req_id,
                        "session_id": session_id,
                        "cycle": cycle,
                    })
                except Exception:
                    logger.debug("[nats-sub] WebSocket notify skipped for gate0")
            else:
                logger.debug("[nats-sub] Gate0 approval already exists for req=%s cycle=%d", req_id, cycle)

        except Exception as e:
            logger.exception("[nats-sub] Failed to handle context.ready.gate0: %s", e)
        finally:
            await conn.close()

        await msg.ack()

    return handle


# ── Generic gate handler (for Gate1, Gate2, Gate3) ──────────────────────────


def _make_gate_handler(db_pool, gate_level: int):
    async def handle(msg):
        payload = json.loads(msg.data.decode())
        req_id = payload.get("req_id")
        session_id = payload.get("session_id", "")
        cycle = payload.get("cycle", 0)

        if not req_id:
            logger.warning("[nats-sub] context.ready.gate%d missing req_id", gate_level)
            await msg.ack()
            return

        conn = await db_pool.acquire()
        try:
            existing = await conn.fetchrow(
                """SELECT id FROM approvals
                   WHERE req_id = $1::uuid AND gate_level = $2 AND cycle = $3 AND status = 'pending'""",
                req_id, gate_level, cycle,
            )

            if not existing:
                import datetime
                now = datetime.datetime.now(datetime.timezone.utc)
                await conn.execute(
                    """INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, created_at)
                       VALUES ($1::uuid, $2::uuid, $3, $4, 'pending', $5)""",
                    req_id, session_id or None, gate_level, cycle, now,
                )
                logger.info("[nats-sub] Pre-created Gate%d approval for req=%s cycle=%d", gate_level, req_id, cycle)

                await conn.execute(
                    """INSERT INTO event_log
                       (req_id, session_id, cycle, event_name, direction, payload)
                       VALUES ($1::uuid, $2::uuid, $3, $4, 'IN', $5::jsonb)""",
                    req_id, session_id or None, cycle,
                    f"context.ready.gate{gate_level}",
                    json.dumps(payload, ensure_ascii=False),
                )

                try:
                    from ws.ws_gateway import notify_session
                    await notify_session(session_id, {
                        "type": f"gate{gate_level}_ready",
                        "req_id": req_id,
                        "session_id": session_id,
                        "cycle": cycle,
                    })
                except Exception:
                    logger.debug("[nats-sub] WebSocket notify skipped for gate%d", gate_level)
            else:
                logger.debug("[nats-sub] Gate%d approval already exists for req=%s cycle=%d", gate_level, req_id, cycle)

        except Exception as e:
            logger.exception("[nats-sub] Failed to handle context.ready.gate%d: %s", gate_level, e)
        finally:
            await conn.close()

        await msg.ack()

    return handle


# ── context.ready.A1 handler (Gate0 rejection → reopen session) ────────────


def _make_handler(db_pool):
    async def handle(msg):
        payload = json.loads(msg.data.decode())
        req_id = payload.get("req_id")
        session_id = payload.get("session_id")
        new_cycle = payload.get("cycle", 0)
        old_cycle = new_cycle - 1
        rejection = payload.get("gate_rejection", {})

        if not req_id or not session_id:
            logger.warning("[nats-sub] context.ready.A1 missing req_id/session_id")
            await msg.ack()
            return

        conn = await db_pool.acquire()
        try:
            async with conn.transaction():
                # 1. Reopen session
                await conn.execute(
                    "UPDATE dialogue_sessions SET status = 'reopened', "
                    "last_updated = NOW() WHERE id = $1::uuid AND req_id = $2::uuid",
                    session_id, req_id,
                )

                # 2. Inject system message
                seq_raw = await conn.fetchval(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 "
                    "FROM dialogue_messages WHERE session_id = $1::uuid AND cycle = $2",
                    session_id, old_cycle,
                )
                seq = (seq_raw or 0) + 1 if seq_raw == 0 else seq_raw

                await conn.execute(
                    "INSERT INTO dialogue_messages "
                    "(session_id, role, content, cycle, sequence_number) "
                    "VALUES ($1::uuid, 'system', $2::jsonb, $3, $4)",
                    session_id,
                    json.dumps({
                        "type": "gate_rejection",
                        "reject_reasons": rejection.get("reject_reasons", []),
                        "revision_guidance": rejection.get("revision_guidance", ""),
                        "cycle": old_cycle,
                    }, ensure_ascii=False),
                    old_cycle,
                    seq,
                )

                # 3. Audit
                await conn.execute(
                    "INSERT INTO event_log "
                    "(req_id, session_id, cycle, event_name, direction, payload) "
                    "VALUES ($1::uuid, $2::uuid, $3, 'context.ready.A1', 'IN', $4::jsonb)",
                    req_id, session_id, new_cycle,
                    json.dumps(payload, ensure_ascii=False),
                )

            # 4. WebSocket notify (best-effort, after transaction commit)
            try:
                from ws.ws_gateway import notify_session
                await notify_session(session_id, {
                    "type": "session_reopened",
                    "req_id": req_id,
                    "session_id": session_id,
                    "cycle": new_cycle,
                    "gate_rejection": rejection,
                })
            except Exception:
                logger.warning(
                    "[nats-sub] WebSocket notify failed for session=%s, "
                    "user will see on next history load",
                    session_id,
                )

        except Exception as e:
            logger.exception("[nats-sub] Failed to handle context.ready.A1: %s", e)
        finally:
            await conn.close()

        await msg.ack()

    return handle
