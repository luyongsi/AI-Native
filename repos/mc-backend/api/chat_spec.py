"""
Mission Control Backend - Chat & Spec API
GET  /api/chat/{req_id}/chat  - Conversation history
POST /api/chat/{req_id}/chat  - Send message, get REAL LLM reply
GET  /api/chat/{req_id}/spec  - Get spec sections
PUT  /api/chat/{req_id}/spec  - Update spec sections
"""
import json
import logging
import os
from typing import Optional, Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat_spec"])

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")


# ── Pydantic models ──────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: Optional[datetime] = None


class ChatHistoryResponse(BaseModel):
    messages: list[dict]
    req_id: str


class ChatSendRequest(BaseModel):
    message: str
    mode: Optional[str] = "open"


class ChatSendResponse(BaseModel):
    reply: str
    options: list[str] = Field(default_factory=list)
    spec_updates: list[dict[str, Any]] = Field(default_factory=list)


class SpecSectionHistory(BaseModel):
    version: str
    content: str
    updated_at: Optional[datetime] = None


class SpecSection(BaseModel):
    id: str
    title: str
    status: str
    content: str
    history: list[dict] = Field(default_factory=list)


class SpecGetResponse(BaseModel):
    req_id: str
    sections: list[dict] = Field(default_factory=list)


class SpecUpdateSection(BaseModel):
    id: str
    title: str
    status: str
    content: str


class SpecUpdateRequest(BaseModel):
    sections: list[SpecUpdateSection]


class SpecUpdateResponse(BaseModel):
    req_id: str
    sections: list[dict] = Field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────

async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


_CHAT_MESSAGES: dict[str, list[dict]] = {}


async def _call_llm(messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000) -> str | None:
    """Call DeepSeek LLM API."""
    if not DEEPSEEK_API_KEY:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"[chat_spec] LLM call failed: {e}")
        return None


def _build_system_prompt(req_title: str, spec_text: str) -> str:
    return f"""你是一个 AI 需求分析助手（类似于产品经理）。你正在和一个用户讨论他们的软件需求。

当前需求标题: {req_title}
当前的 Spec 文档内容:
{spec_text[:3000]}

请用中文回复。根据用户的输入，你可以：
1. 回答用户关于需求的问题
2. 帮助完善/修改 Spec 文档
3. 生成验收条件（acceptance criteria）
4. 建议技术方案
5. 提出澄清性问题以确保需求清晰

核心工作方式:
- 当 Spec 中已有章节内容包含未澄清的问题时，你应当直接分析并给出合理的默认方案，然后更新该章节为确定的 Spec 内容，而不是继续保留问题。
- Spec 章节内容应该是确定的、可直接执行的功能描述，不应该包含反问句或待确认的问题列表。
- 如果用户没有给出明确答案，你就基于行业最佳实践做出合理假设，填入 Spec，并在回复中说明你做了什么假设、为什么这样做。

重要: 如果你需要用户做出选择，请在回复中用 [OPTIONS] 标签提供可点击的选项，格式如下:
[OPTIONS][{{"label": "选项A的描述", "value": "A"}}, {{"label": "选项B的描述", "value": "B"}}][OPTIONS]
选项应该是用户可以直接点击选择的简洁描述，每个选项不超过30个字。只在你需要用户决策时才提供选项。

在回复末尾，如果有更新的 Spec 内容，用 [SPEC_UPDATES] 标签包裹 JSON 数组格式的变更，例如：
[SPEC_UPDATES][{{"section_id": "s1", "title": "功能说明", "new_content": "更新后的确定内容（不要包含反问句或问题列表）"}}][SPEC_UPDATES]

如果没有要更新的 Spec，就不要加这个标签。"""


# ── Chat Endpoints ───────────────────────────────────────────────────────

@router.get("/{req_id}/chat", response_model=ChatHistoryResponse)
async def get_chat_history(req_id: str):
    """Return conversation history for a requirement."""
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            "SELECT id, title, spec FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Requirement not found")

        rows = await conn.fetch(
            "SELECT id, role, content, created_at FROM chat_messages "
            "WHERE req_id = $1::uuid ORDER BY created_at",
            req_id,
        )
        messages = []
        for r in rows:
            messages.append({
                "id": str(r["id"]),
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
            })

        return ChatHistoryResponse(messages=messages, req_id=req_id)
    finally:
        await conn.close()


@router.post("/{req_id}/chat")
async def send_chat_message(req_id: str, body: ChatSendRequest):
    """Send a message and get a real LLM reply via DeepSeek. Supports streaming."""
    # Check for SSE streaming request
    import json as _json
    accept_header = ""
    return StreamingResponse(
        _stream_chat(req_id, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _stream_chat(req_id: str, body: ChatSendRequest):
    """Generator that sends SSE events as the LLM responds."""
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            "SELECT id, title, spec FROM requirements WHERE id = $1::uuid", req_id
        )
        if not row:
            yield f"data: {json.dumps({'type': 'error', 'content': 'Requirement not found'})}\n\n"
            return

        req_title = row["title"] or "未命名需求"
        spec_raw = row["spec"]
        if isinstance(spec_raw, str):
            try:
                spec_raw = json.loads(spec_raw)
            except (json.JSONDecodeError, TypeError):
                spec_raw = {}
        elif not isinstance(spec_raw, dict):
            spec_raw = {}
        spec_text = json.dumps(spec_raw, ensure_ascii=False, indent=2)

        # Persist user message
        user_msg = {
            "id": f"{req_id}-msg-{len(_CHAT_MESSAGES.get(req_id, [])) + 1}",
            "role": "user",
            "content": body.message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _CHAT_MESSAGES.setdefault(req_id, []).append(user_msg)

        # Persist user message to DB
        await conn.execute(
            "INSERT INTO chat_messages (id, req_id, role, content, created_at) VALUES ($1::uuid, $2::uuid, $3, $4, NOW())",
            user_msg["id"], req_id, "user", body.message,
        )

        # Build LLM conversation
        system_prompt = _build_system_prompt(req_title, spec_text)
        llm_messages = [{"role": "system", "content": system_prompt}]
        for msg in _CHAT_MESSAGES[req_id][-10:]:
            llm_messages.append({"role": msg["role"], "content": msg["content"]})

        # Send thinking indicator
        yield f"data: {json.dumps({'type': 'thinking', 'content': 'AI 正在思考...'})}\n\n"

        if not DEEPSEEK_API_KEY:
            yield f"data: {json.dumps({'type': 'error', 'content': 'LLM API Key not configured'})}\n\n"
            return

        # Stream from DeepSeek — accumulate and buffer tags
        full_reply = ""
        tag_buffer = ""  # buffer for [OPTIONS] and [SPEC_UPDATES] tags
        in_tag = False
        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": llm_messages,
                        "temperature": 0.7,
                        "max_tokens": 2000,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                full_reply += content
                                # Buffer tag sequences instead of streaming them
                                combined = tag_buffer + content
                                while combined:
                                    # Find tag starts: [OPTIONS] or [SPEC_UPDATES]
                                    opt_idx = combined.find("[OPTIONS]")
                                    spec_idx = combined.find("[SPEC_UPDATES]")

                                    first_tag_idx = -1
                                    tag_name = ""
                                    if opt_idx >= 0 and (spec_idx < 0 or opt_idx <= spec_idx):
                                        first_tag_idx = opt_idx
                                        tag_name = "[OPTIONS]"
                                    elif spec_idx >= 0:
                                        first_tag_idx = spec_idx
                                        tag_name = "[SPEC_UPDATES]"

                                    if first_tag_idx >= 0:
                                        # Flush text before the tag
                                        if first_tag_idx > 0:
                                            yield f"data: {json.dumps({'type': 'text', 'content': combined[:first_tag_idx]})}\n\n"
                                        # Skip the tag content until closing tag
                                        end_tag = f"[/{tag_name[1:]}"
                                        end_idx = combined.find(end_tag, first_tag_idx + len(tag_name))
                                        if end_idx >= 0:
                                            if "] ]" in combined[end_idx:] or combined[end_idx:].startswith(end_tag + "]"):
                                                actual_end = combined.find("]", end_idx) + 1
                                                tag_buffer = combined[actual_end:]
                                                combined = ""
                                            else:
                                                tag_buffer = combined[first_tag_idx:]
                                                combined = ""
                                        else:
                                            tag_buffer = combined[first_tag_idx:]
                                            combined = ""
                                    else:
                                        # No tag — check partial match
                                        partial = None
                                        for tag in ["[OPTIONS]", "[SPEC_UPDATES]"]:
                                            for k in range(1, min(len(tag), len(combined)) + 1):
                                                if combined.endswith(tag[:k]):
                                                    partial = tag[:k]
                                                    break
                                            if partial:
                                                break
                                        if partial:
                                            # Send text before partial match
                                            send_len = len(combined) - len(partial)
                                            if send_len > 0:
                                                safe = combined[:send_len]
                                                # Final check: make sure no tag inside
                                                if "[OPTIONS]" not in safe and "[SPEC_UPDATES]" not in safe:
                                                    yield f"data: {json.dumps({'type': 'text', 'content': safe})}\n\n"
                                            tag_buffer = combined[-len(partial):]
                                            combined = ""
                                        else:
                                            # Clean text — no tags
                                            yield f"data: {json.dumps({'type': 'text', 'content': combined})}\n\n"
                                            combined = ""
                                            tag_buffer = ""
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as e:
            logger.error(f"[chat_spec] LLM stream failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': f'LLM error: {e}'})}\n\n"
            return

        # Spec extraction from full reply
        options, spec_updates = _extract_spec_from_reply(full_reply, spec_raw, conn, req_id)

        # Persist assistant reply
        assistant_msg = {
            "id": f"{req_id}-msg-{len(_CHAT_MESSAGES[req_id]) + 1}",
            "role": "assistant",
            "content": full_reply,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _CHAT_MESSAGES[req_id].append(assistant_msg)

        # Persist assistant reply to DB
        await conn.execute(
            "INSERT INTO chat_messages (id, req_id, role, content, created_at) VALUES ($1::uuid, $2::uuid, $3, $4, NOW())",
            assistant_msg["id"], req_id, "assistant", full_reply,
        )

        # Send final metadata (with options from LLM reply)
        final_options, spec_updates = _extract_spec_from_reply(full_reply, spec_raw, conn, req_id)

        # Extract [OPTIONS] from full reply
        if "[OPTIONS]" in full_reply:
            try:
                opts_json = full_reply.split("[OPTIONS]")[1].split("[OPTIONS]")[0].strip()
                parsed = json.loads(opts_json)
                final_options = [{"label": o.get("label", o.get("text", str(o))), "value": o.get("value", o.get("id", str(o)))} for o in parsed]
            except (json.JSONDecodeError, ValueError, IndexError):
                pass

        yield f"data: {json.dumps({'type': 'done', 'options': final_options, 'spec_updates': spec_updates, 'spec_update_count': len(spec_updates)})}\n\n"

    finally:
        await conn.close()


def _keyword_reply(message: str) -> tuple[str, list[str], list[dict]]:
    """Fallback keyword-based reply when LLM is unavailable."""
    msg_lower = message.lower()
    if "test" in msg_lower or "测试" in msg_lower:
        return "我可以帮你基于 Spec 生成测试用例。需要覆盖单元测试、集成测试和边界条件测试。", ["生成测试用例", "补充边界条件", "查看测试覆盖率"], []
    elif "spec" in msg_lower or "需求" in msg_lower or "方案" in msg_lower:
        return "收到，我会根据你的输入更新 Spec 文档。请告诉我具体需要修改哪些部分。", ["更新功能说明", "补充验收标准", "生成技术方案"], []
    elif "auth" in msg_lower or "安全" in msg_lower:
        return "从安全角度，建议：1) Token 认证 + 刷新机制, 2) 敏感接口限流, 3) 输入校验和过滤。需要我加到 Spec 里吗？", ["添加安全章节", "检查认证流程", "生成安全清单"], []
    else:
        return f'收到你的消息："{message}"。我可以帮你完善需求、生成 Spec、编写测试用例或规划实现方案。', ["完善需求", "生成 Spec", "规划实现"], []


def _extract_spec_from_reply(full_reply: str, spec_raw: dict, conn, req_id: str):
    """Extract Spec sections from LLM reply and persist to DB."""
    options: list[str] = []
    spec_updates: list[dict] = []
    if not isinstance(spec_raw, dict):
        spec_raw = {}
    current_spec = spec_raw.get("sections", spec_raw.get("spec_sections", [])) if isinstance(spec_raw, dict) else []

    if not full_reply:
        return options, spec_updates

    if "[SPEC_UPDATES]" in full_reply:
        parts = full_reply.split("[SPEC_UPDATES]")
        if len(parts) > 1:
            try:
                spec_updates = json.loads(parts[1].split("[SPEC_UPDATES]")[0].strip())
            except (json.JSONDecodeError, ValueError):
                pass

    if not spec_updates:
        lines = [l.strip() for l in full_reply.split("\n") if l.strip()]
        headings = []
        cur = None
        cur_content = []
        for line in lines:
            is_heading = (line[0].isdigit() and ". " in line[:5]) or line.startswith("## ")
            if is_heading:
                if cur:
                    headings.append((cur, "\n".join(cur_content)))
                cur = line.lstrip("#").strip()
                cur_content = []
            else:
                if cur is not None:
                    cur_content.append(line)
        if cur:
            headings.append((cur, "\n".join(cur_content)))
        if headings:
            for i, (title, content) in enumerate(headings):
                spec_updates.append({"section_id": f"s{i+1}", "title": title, "new_content": content.strip()})

    option_lines = [l.strip() for l in full_reply.split("\n") if l.strip() and len(l.strip()) >= 2 and l.strip()[0] in "ABCD" and ". " in l.strip()[:4]]
    if option_lines:
        options = option_lines[:4]

    if spec_updates:
        # Strip markdown formatting from titles
        for update in spec_updates:
            title = update.get("title", "")
            title = title.replace("**", "").replace("*", "").strip()
            import re as _re
            title = _re.sub(r'^\d+\.\s*', '', title)
            title = title.strip()
            update["title"] = title

        # Use ensure_future with its own DB connection so writes survive after
        # the caller's conn closes.
        import asyncio as _a
        async def _update():
            _conn = await get_db()
            try:
                # Re-read current spec inside the fresh connection
                _row = await _conn.fetchrow(
                    "SELECT spec FROM requirements WHERE id = $1::uuid", req_id
                )
                _spec_raw = {}
                if _row and _row["spec"]:
                    _spec_raw = _row["spec"]
                    if isinstance(_spec_raw, str):
                        try:
                            _spec_raw = json.loads(_spec_raw)
                        except (json.JSONDecodeError, TypeError):
                            _spec_raw = {}
                    if not isinstance(_spec_raw, dict):
                        _spec_raw = {}
                _current = _spec_raw.get("sections", _spec_raw.get("spec_sections", []))

                for update in spec_updates:
                    found = False
                    for s in _current:
                        if s.get("id") == update.get("section_id") or s.get("title") == update.get("title"):
                            s["content"] = update.get("new_content", s.get("content", ""))
                            s["status"] = "done"
                            s.setdefault("history", []).append({"time": datetime.now(timezone.utc).strftime("%H:%M"), "action": "AI 对话生成"})
                            found = True
                            break
                    if not found:
                        _current.append({
                            "id": update.get("section_id", f"s{len(_current)+1}"),
                            "title": update.get("title", "新章节"),
                            "status": "done",
                            "content": update.get("new_content", ""),
                            "history": [{"time": datetime.now(timezone.utc).strftime("%H:%M"), "action": "AI 对话生成"}],
                        })
                spec_json = {
                    "sections": _current,
                    "stages": _spec_raw.get("stages", []),
                    "spec_sections": _current,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                await _conn.execute(
                    "UPDATE requirements SET spec = $1::jsonb, updated_at = NOW() WHERE id = $2::uuid",
                    json.dumps(spec_json), req_id,
                )
                # Update requirement status to designing and publish NATS event
                await _conn.execute(
                    "UPDATE requirements SET status = 'designing', updated_at = NOW() WHERE id = $1::uuid and status NOT IN ('designing','reviewing','decomposing','developing','testing','releasing','done')",
                    req_id,
                )
                logger.info(f"[chat_spec] Spec updated for req={req_id}, {len(spec_updates)} changes")
                # Publish NATS event to trigger Agent pipeline
                try:
                    import nats
                    nc = await nats.connect("nats://localhost:4222")
                    envelope = {
                        "event_id": f"spec-ready-{req_id}",
                        "event_type": "spec.ready.designing",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "payload": {"req_id": req_id, "status": "designing", "section_count": len(_current)},
                        "req_id": req_id,
                    }
                    await nc.publish("spec.ready.designing", json.dumps(envelope, ensure_ascii=False).encode())
                    await nc.close()
                    logger.info(f"[chat_spec] Published spec.ready.designing for req={req_id}")
                except Exception as e:
                    logger.warning(f"[chat_spec] Failed to publish NATS event: {e}")
            except Exception as e:
                logger.warning(f"[chat_spec] Failed to persist spec: {e}")
            finally:
                await _conn.close()
        _a.ensure_future(_update())

    return options, spec_updates


# ── Spec Endpoints ───────────────────────────────────────────────────────

@router.get("/{req_id}/spec")
async def get_spec(req_id: str):
    """Return spec sections parsed from requirements.spec JSONB."""
    conn = await get_db()
    try:
        row = await conn.fetchrow(
            "SELECT id, spec FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Requirement not found")

        spec_raw = row["spec"]
        if isinstance(spec_raw, str):
            try:
                spec_raw = json.loads(spec_raw)
            except (json.JSONDecodeError, TypeError):
                spec_raw = {}
        elif not isinstance(spec_raw, dict):
            spec_raw = {}
        sections = spec_raw.get("sections", [])

        if not sections:
            # Return empty — no mock data
            return {"req_id": req_id, "sections": []}

        return {"req_id": req_id, "sections": sections}
    finally:
        await conn.close()


@router.put("/{req_id}/spec")
async def update_spec(req_id: str, body: SpecUpdateRequest):
    """Update spec sections. Writes to requirements.spec JSONB column."""
    conn = await get_db()
    try:
        existing = await conn.fetchrow(
            "SELECT id, spec FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Requirement not found")

        now = datetime.now(timezone.utc).isoformat()
        new_sections: list[dict] = []

        for s in body.sections:
            new_sections.append({
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "content": s.content,
            })

        spec_json = {"sections": new_sections, "updated_at": now}

        await conn.execute(
            """
            UPDATE requirements
            SET spec = $1::jsonb, updated_at = NOW()
            WHERE id = $2::uuid
            """,
            spec_json,
            req_id,
        )

        logger.info(f"[chat_spec] Spec updated for req_id={req_id}, {len(new_sections)} sections")
        return {"req_id": req_id, "sections": new_sections}
    finally:
        await conn.close()
