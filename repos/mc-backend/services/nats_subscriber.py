"""
MC Backend — NATS subscriber for context.ready.A1 (Gate0 rejection).

Handles the case where Gate0 rejects a requirement:
  1. Updates dialogue_sessions status to 'reopened'
  2. Injects a system message with rejection details
  3. Writes event_log audit record
  4. Notifies frontend via WebSocket (best-effort, through Redis Pub/Sub)

Design: A1's context.ready.A1 is "session reopened, waiting for user to revise"
(not "start working now" like A2-A12 dispatched agents).
"""
from __future__ import annotations

import json
import logging

import nats

logger = logging.getLogger(__name__)


async def subscribe_context_ready_a1(db_pool, nats_url: str):
    """Start a background asyncio task that subscribes to context.ready.A1.

    Called once at MC Backend startup. Runs forever (reconnects on disconnect).
    """
    while True:
        try:
            nc = await nats.connect(nats_url)
            js = nc.jetstream()
            await js.subscribe("context.ready.A1", cb=_make_handler(db_pool))
            logger.info("[nats-sub] Subscribed to context.ready.A1")
            # Keep the subscription alive
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

                # 2. Inject system message (old cycle = gate rejection happened in that cycle)
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
