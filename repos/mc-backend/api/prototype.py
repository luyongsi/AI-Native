"""
Mission Control Backend — Prototype API (A3 UI Prototype Agent)

Stage 2: HTTP+SSE endpoints for prototype generation, annotation, and confirmation.

Endpoints:
  GET  /api/prototype/context/{req_id}  — Get prototype context + status
  POST /api/prototype/generate           — Start prototype generation (SSE Stream)
  POST /api/prototype/annotate           — Submit annotations (SSE Stream)
  POST /api/prototype/confirm            — Confirm prototype finalization
  GET  /api/prototype/history/{req_id}   — Get version history
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prototype", tags=["prototype"])

# ── Pydantic models ────────────────────────────────────────────────────


class Annotation(BaseModel):
    annotation_id: str = Field(default_factory=lambda: _new_uuid())
    element_id: str = ""
    type: str = "other"  # layout_change|content_change|style_change|add_element|remove_element|flow_change|other
    comment: str = ""
    position: dict[str, float] | None = None


class PrototypeGenerateRequest(BaseModel):
    req_id: str
    session_id: str = ""


class PrototypeAnnotateRequest(BaseModel):
    req_id: str
    session_id: str = ""
    annotations: list[Annotation] = Field(default_factory=list)


class PrototypeConfirmRequest(BaseModel):
    req_id: str
    session_id: str = ""
    final_notes: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────


def _new_uuid() -> str:
    import uuid
    return str(uuid.uuid4())


async def get_db():
    from main import DB_POOL
    return await DB_POOL.acquire()


async def _publish_nats(subject: str, payload: dict) -> None:
    """Best-effort publish to NATS JetStream."""
    try:
        from main import NATS_CLIENT
        if NATS_CLIENT and NATS_CLIENT.is_connected:
            js = NATS_CLIENT.jetstream()
            msg_id = f"prototype-{payload.get('req_id', '?')}-{payload.get('version', 0)}"
            await js.publish(
                subject,
                json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Nats-Msg-Id": msg_id},
            )
            logger.info(f"Published NATS {subject}")
    except Exception as e:
        logger.warning(f"NATS publish failed for {subject}: {e}")


async def _call_llm(messages: list, temperature: float = 0.4, max_tokens: int = 4000) -> Optional[str]:
    """Simple LLM call wrapper for prototype generation."""
    import os
    import httpx

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")

    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return None


# ── SSE formatter import ────────────────────────────────────────────────
from services.sse_formatter import format_sse_event, format_sse_error, format_sse_done
from services.s3_service import get_s3_storage

# ── Endpoints ───────────────────────────────────────────────────────────


@router.get("/context/{req_id}")
async def get_prototype_context(req_id: str):
    """Get prototype page context: requirement summary + current prototype status."""
    conn = await get_db()
    try:
        req = await conn.fetchrow(
            """SELECT id, title, requirement_draft, phase, design_status,
                      design_revision_count
               FROM requirements WHERE id = $1::uuid""",
            req_id,
        )
        if not req:
            raise HTTPException(status_code=404, detail="Requirement not found")

        # Latest prototype artifact
        proto_row = await conn.fetchrow(
            """SELECT version, status, prototype_url, screens, annotations
               FROM prototype_artifacts
               WHERE req_id = $1::uuid
               ORDER BY version DESC LIMIT 1""",
            req_id,
        )

        # Check for Gate1 rejection
        revision_context = {"is_revision": False, "gate1_rejection": None}
        design_status = req["design_status"] or ""
        revision_count = req["design_revision_count"] or 0

        if design_status == "prototyping" and revision_count > 0:
            rejection_row = await conn.fetchrow(
                """SELECT reject_reasons, revision_guidance
                   FROM approvals
                   WHERE req_id = $1::uuid AND gate_level = 1
                   AND decision = 'reject'
                   ORDER BY reviewed_at DESC LIMIT 1""",
                req_id,
            )
            if rejection_row:
                revision_context = {
                    "is_revision": True,
                    "gate1_rejection": {
                        "reject_reasons": (
                            rejection_row["reject_reasons"]
                            if isinstance(rejection_row["reject_reasons"], list)
                            else []
                        ),
                        "revision_guidance": rejection_row["revision_guidance"] or "",
                    },
                }

        draft = req["requirement_draft"] if isinstance(req["requirement_draft"], dict) else {}
        requirement_summary = {
            "title": req["title"] or draft.get("title", "未命名需求"),
            "domain": draft.get("domain", "general"),
            "acceptance_criteria": draft.get("acceptance_criteria", []),
        }

        return {
            "req_id": req_id,
            "session_id": "",  # A3 reuses A1 session
            "design_status": design_status,
            "requirement_summary": requirement_summary,
            "prototype": {
                "has_existing": proto_row is not None,
                "current_version": proto_row["version"] if proto_row else 0,
                "status": proto_row["status"] if proto_row else "draft",
                "prototype_url": proto_row["prototype_url"] if proto_row else None,
                "screens": (
                    proto_row["screens"] if proto_row and isinstance(proto_row["screens"], list)
                    else []
                ),
                "annotations": (
                    proto_row["annotations"] if proto_row and isinstance(proto_row["annotations"], list)
                    else []
                ),
            },
            "revision_context": revision_context,
        }
    finally:
        await conn.close()


@router.post("/generate")
async def generate_prototype(req: PrototypeGenerateRequest):
    """Start prototype generation via SSE streaming."""
    conn = await get_db()
    try:
        # Validate requirement state
        req_row = await conn.fetchrow(
            """SELECT id, title, requirement_draft, phase, design_status
               FROM requirements WHERE id = $1::uuid""",
            req.req_id,
        )
        if not req_row:
            raise HTTPException(status_code=404, detail="Requirement not found")

        phase = req_row["phase"] or ""
        design_status = req_row["design_status"] or ""
        if phase != "design" or design_status not in ("prototyping", "gate1_rejected"):
            raise HTTPException(
                status_code=409,
                detail=f"Prototype generation requires phase='design' and design_status='prototyping' (current: phase={phase}, design_status={design_status})",
            )

        draft = req_row["requirement_draft"] if isinstance(req_row["requirement_draft"], dict) else {}
        title = req_row["title"] or draft.get("title", "未命名需求")
        description = draft.get("description", draft.get("summary", ""))
        domain = draft.get("domain", "general")

        # Read A2 feasibility from agent_results
        a2_row = await conn.fetchrow(
            """SELECT artifact FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = 'A2'
               ORDER BY cycle DESC LIMIT 1""",
            req.req_id,
        )
        feasibility = {}
        if a2_row and isinstance(a2_row["artifact"], dict):
            feasibility = a2_row["artifact"].get("feasibility_assessment", {})

        # Determine next version
        max_version = await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM prototype_artifacts WHERE req_id = $1::uuid",
            req.req_id,
        )
        next_version = (max_version or 0) + 1
    finally:
        await conn.close()

    async def event_stream() -> AsyncIterator[str]:
        s3 = get_s3_storage()
        html_buffer: list[str] = []

        try:
            # Phase 1: thinking
            yield format_sse_event("thinking", {"message": "正在分析需求结构，匹配合适的UI模板..."})

            await asyncio.sleep(0.3)

            # Phase 2: build prompt
            entities_text = json.dumps(draft.get("entities", []), ensure_ascii=False)[:1000]
            use_cases_text = "\n".join(
                draft.get("use_cases", [])[:10]
            ) if draft.get("use_cases") else "标准CRUD操作"
            feasibility_text = json.dumps(feasibility, ensure_ascii=False)[:1000]

            prompt = f"""你是资深 UI/UX 设计师。根据需求生成一个可直接预览的高保真 HTML 原型页面。

需求标题: {title}
需求描述: {description or title}
业务领域: {domain}
实体: {entities_text}
用例: {use_cases_text}
可行性: {feasibility_text}

要求:
1. 使用内联 CSS（无外部依赖），可直接在浏览器打开
2. 包含搜索/筛选、数据表格、操作按钮等常见后台组件
3. 响应式设计，浅色主题
4. 包含空状态占位和错误状态提示
5. 多状态支持: default, loading, empty, error

输出 JSON:
{{
  "html": "<完整 HTML 代码>",
  "description": "设计说明（30字以内）"
}}

只输出 JSON。HTML 必须是完整的独立页面。"""

            # Phase 3: Stream LLM
            yield format_sse_event("thinking", {"message": "正在生成原型HTML..."})

            llm_result = await _call_llm(
                [{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=8000,
            )

            if llm_result:
                try:
                    content = llm_result.strip()
                    if content.startswith("```"):
                        content = content.split("```")[1].split("```")[0].strip()
                    if content.startswith("json"):
                        content = content[4:].strip()
                    result = json.loads(content)
                    html = result.get("html", "")
                except (json.JSONDecodeError, KeyError):
                    html = _fallback_html(title, domain)
            else:
                html = _fallback_html(title, domain)

            # Stream HTML in chunks
            chunk_size = 500
            for i in range(0, len(html), chunk_size):
                chunk = html[i:i + chunk_size]
                html_buffer.append(chunk)
                progress = min(len("".join(html_buffer)) / max(len(html), 1), 0.95)
                yield format_sse_event("prototype_update", {
                    "html_chunk": chunk,
                    "progress": round(progress, 3),
                })
                await asyncio.sleep(0.02)  # Small delay for streaming feel

            full_html = "".join(html_buffer)

            # Phase 4: Upload to S3
            url, b64 = await s3.upload_html(req.req_id, next_version, full_html)

            # Phase 5: Persist to DB
            conn2 = await get_db()
            try:
                screens = [
                    {"name": f"{title}-默认状态", "state": "default",
                     "description": "主要界面"},
                    {"name": f"{title}-加载中", "state": "loading",
                     "description": "数据加载骨架屏"},
                    {"name": f"{title}-空数据", "state": "empty",
                     "description": "无数据时的占位引导"},
                    {"name": f"{title}-错误状态", "state": "error",
                     "description": "错误/异常时提示"},
                ]

                cycle = 0  # A3 runs in current cycle
                await conn2.execute(
                    """INSERT INTO prototype_artifacts
                       (req_id, cycle, version, prototype_url, html_content,
                        screens, status)
                       VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, 'draft')""",
                    req.req_id, cycle, next_version,
                    url,
                    full_html if not url else None,  # store inline if no S3
                    json.dumps(screens),
                )

                yield format_sse_event("screens", {"screens": screens})

                yield format_sse_done({
                    "prototype_url": url or f"data:text/html;base64,{b64}",
                    "version": next_version,
                    "screens": screens,
                    "upload_failed": url is None,
                })
            finally:
                await conn2.close()

        except Exception as e:
            logger.error(f"Prototype generation failed: {e}", exc_info=True)

            # Save partial HTML on failure
            if html_buffer:
                try:
                    conn2 = await get_db()
                    try:
                        await conn2.execute(
                            """INSERT INTO prototype_artifacts
                               (req_id, cycle, version, prototype_url, html_content, status)
                               VALUES ($1::uuid, 0, $2, NULL, $3, 'draft')
                               ON CONFLICT (req_id, cycle, version) DO NOTHING""",
                            req.req_id, next_version, "".join(html_buffer),
                        )
                    finally:
                        await conn2.close()
                except Exception:
                    pass

            yield format_sse_error(f"生成失败: {str(e)[:200]}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/annotate")
async def annotate_prototype(req: PrototypeAnnotateRequest):
    """Submit annotations and get updated prototype via SSE streaming."""
    if not req.annotations:
        raise HTTPException(status_code=400, detail="annotations required")

    conn = await get_db()
    try:
        # Read current prototype
        proto_row = await conn.fetchrow(
            """SELECT version, html_content, prototype_url, annotations
               FROM prototype_artifacts
               WHERE req_id = $1::uuid
               ORDER BY version DESC LIMIT 1""",
            req.req_id,
        )
        if not proto_row:
            raise HTTPException(status_code=404, detail="No prototype found. Generate one first.")

        current_version = proto_row["version"]
        current_html = proto_row["html_content"] or ""
        existing_annotations = proto_row["annotations"] if isinstance(proto_row["annotations"], list) else []

        # If HTML is stored in S3, fetch it
        if not current_html and proto_row["prototype_url"]:
            s3 = get_s3_storage()
            html_bytes = await s3.get_html(req.req_id, current_version)
            if html_bytes:
                current_html = html_bytes.decode() if isinstance(html_bytes, bytes) else html_bytes

        if not current_html:
            raise HTTPException(status_code=500, detail="Prototype HTML not available")

        next_version = current_version + 1
    finally:
        await conn.close()

    async def event_stream() -> AsyncIterator[str]:
        s3 = get_s3_storage()

        try:
            # Parse annotations
            annotations_text = "\n".join(
                f"- [{a.type}] {a.comment} (target: {a.element_id or 'N/A'})"
                for a in req.annotations
            )
            yield format_sse_event("thinking", {"message": "正在解析标注..."})
            yield format_sse_event("annotation_parsed", {
                "parsed": [
                    {"annotation_id": a.annotation_id,
                     "intent": a.comment[:80]}
                    for a in req.annotations
                ],
            })

            # Build annotation-aware prompt
            prompt = f"""你是资深前端开发者。根据用户标注修改以下 HTML 原型。

当前 HTML 原型 (前 4000 字符):
{current_html[:4000]}

用户标注:
{annotations_text}

要求:
1. 根据标注修改 HTML，保持原有的完整页面结构
2. 只修改标注涉及的部分，其他部分保持不变
3. 使用内联 CSS
4. 输出完整修改后的 HTML 页面

输出 JSON:
{{
  "html": "<完整修改后的 HTML 代码>"
}}

只输出 JSON。"""

            yield format_sse_event("thinking", {"message": "正在根据标注更新原型..."})

            llm_result = await _call_llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=8000,
            )

            if llm_result:
                try:
                    content = llm_result.strip()
                    if content.startswith("```"):
                        content = content.split("```")[1].split("```")[0].strip()
                    if content.startswith("json"):
                        content = content[4:].strip()
                    result = json.loads(content)
                    new_html = result.get("html", current_html)
                except (json.JSONDecodeError, KeyError):
                    new_html = current_html
            else:
                new_html = current_html
                yield format_sse_event("thinking", {"message": "LLM 不可用，保留当前原型"})

            # Stream updated HTML
            html_buffer = []
            chunk_size = 500
            for i in range(0, len(new_html), chunk_size):
                chunk = new_html[i:i + chunk_size]
                html_buffer.append(chunk)
                progress = min(len("".join(html_buffer)) / max(len(new_html), 1), 0.95)
                yield format_sse_event("prototype_update", {
                    "html_chunk": chunk,
                    "progress": round(progress, 3),
                })
                await asyncio.sleep(0.01)

            full_html = "".join(html_buffer)

            # Upload to S3
            url, b64 = await s3.upload_html(req.req_id, next_version, full_html)

            # Persist new version
            conn2 = await get_db()
            try:
                all_annotations = existing_annotations + [
                    {
                        "annotation_id": a.annotation_id,
                        "element_id": a.element_id,
                        "type": a.type,
                        "comment": a.comment,
                        "position": a.position,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    for a in req.annotations
                ]

                await conn2.execute(
                    """INSERT INTO prototype_artifacts
                       (req_id, cycle, version, prototype_url, html_content,
                        annotations, status)
                       VALUES ($1::uuid, 0, $2, $3, $4, $5::jsonb, 'draft')""",
                    req.req_id, next_version,
                    url,
                    full_html if not url else None,
                    json.dumps(all_annotations),
                )

                yield format_sse_done({
                    "prototype_url": url or f"data:text/html;base64,{b64}",
                    "version": next_version,
                    "annotation_count": len(all_annotations),
                })
            finally:
                await conn2.close()

        except Exception as e:
            logger.error(f"Annotation processing failed: {e}", exc_info=True)
            yield format_sse_error(f"标注处理失败: {str(e)[:200]}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/confirm")
async def confirm_prototype(req: PrototypeConfirmRequest):
    """Confirm prototype finalization: persist and publish NATS agent.result.A3."""
    conn = await get_db()
    try:
        # Get current prototype
        proto_row = await conn.fetchrow(
            """SELECT id, version, status, prototype_url, screens, annotations
               FROM prototype_artifacts
               WHERE req_id = $1::uuid
               ORDER BY version DESC LIMIT 1""",
            req.req_id,
        )
        if not proto_row:
            raise HTTPException(status_code=404, detail="No prototype found")

        # Check already confirmed
        if proto_row["status"] == "confirmed":
            return {"status": "already_confirmed",
                    "version": proto_row["version"],
                    "message": "Prototype was already confirmed"}

        gate_rejection_count = await conn.fetchval(
            "SELECT COALESCE(gate_rejection_count, 0) FROM requirements WHERE id = $1::uuid",
            req.req_id,
        )
        cycle = gate_rejection_count  # cycle = gate rejection count (Gate0 reworks)

        screens = proto_row["screens"] if isinstance(proto_row["screens"], list) else []
        annotations = proto_row["annotations"] if isinstance(proto_row["annotations"], list) else []

        async with conn.transaction():
            # 1. Mark prototype as confirmed
            await conn.execute(
                """UPDATE prototype_artifacts
                   SET status = 'confirmed', updated_at = NOW()
                   WHERE req_id = $1::uuid AND version = $2""",
                req.req_id, proto_row["version"],
            )

            # 2. Write agent_results (upsert by req_id + agent_key + cycle)
            artifact = {
                "prototype_url": proto_row["prototype_url"],
                "screens": screens,
                "version": proto_row["version"],
                "annotation_count": len(annotations),
                "final_notes": req.final_notes,
            }
            await conn.execute(
                """INSERT INTO agent_results
                   (req_id, agent_key, cycle, status, artifact)
                   VALUES ($1::uuid, 'A3', $2, 'completed', $3::jsonb)
                   ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
                   SET artifact = EXCLUDED.artifact,
                       status = 'completed',
                       created_at = NOW()""",
                req.req_id, cycle, json.dumps(artifact),
            )

            # 3. Update requirements design_status
            await conn.execute(
                """UPDATE requirements
                   SET design_status = 'spec_writing', updated_at = NOW()
                   WHERE id = $1::uuid""",
                req.req_id,
            )

            # 4. Write event_log (outbox)
            payload = {
                "req_id": req.req_id,
                "session_id": req.session_id,
                "cycle": cycle,
                "prototype_url": proto_row["prototype_url"],
                "screens": screens,
                "version": proto_row["version"],
                "annotation_count": len(annotations),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await conn.execute(
                """INSERT INTO event_log
                   (req_id, session_id, cycle, event_name, direction, payload, outbox_status)
                   VALUES ($1::uuid, $2::uuid, $3, 'agent.result.A3', 'OUT', $4::jsonb, 'pending')""",
                req.req_id, req.session_id or None, cycle,
                json.dumps(payload),
            )

        # Publish NATS (non-transactional, best-effort)
        await _publish_nats("agent.result.A3", payload)

        return {
            "status": "confirmed",
            "version": proto_row["version"],
            "prototype_url": proto_row["prototype_url"],
            "screens": screens,
        }
    finally:
        await conn.close()


@router.get("/history/{req_id}")
async def get_prototype_history(req_id: str):
    """Get prototype version history with annotations."""
    conn = await get_db()
    try:
        rows = await conn.fetch(
            """SELECT version, status, prototype_url, screens, annotations,
                      created_at, updated_at
               FROM prototype_artifacts
               WHERE req_id = $1::uuid
               ORDER BY version DESC
               LIMIT 50""",
            req_id,
        )

        versions = []
        for row in rows:
            versions.append({
                "version": row["version"],
                "status": row["status"],
                "prototype_url": row["prototype_url"],
                "screens": row["screens"] if isinstance(row["screens"], list) else [],
                "annotations": row["annotations"] if isinstance(row["annotations"], list) else [],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            })

        return {"req_id": req_id, "versions": versions}
    finally:
        await conn.close()


# ── Fallback HTML template ──────────────────────────────────────────────


def _fallback_html(title: str, domain: str = "general") -> str:
    """Generate a fallback HTML template when LLM is unavailable."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f5f5f5; }}
.header {{ background:#fff; padding:16px 24px; border-bottom:1px solid #e8e8e8; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:18px; color:#333; }}
.btn {{ padding:8px 16px; border:none; border-radius:6px; cursor:pointer; font-size:13px; }}
.btn-primary {{ background:#1890ff; color:#fff; }}
.btn-success {{ background:#52c41a; color:#fff; }}
.btn-danger {{ background:#ff4d4f; color:#fff; }}
.container {{ max-width:1200px; margin:24px auto; padding:0 24px; }}
.card {{ background:#fff; border-radius:8px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,.08); margin-bottom:16px; }}
.search-bar {{ display:flex; gap:12px; margin-bottom:16px; }}
.search-bar input {{ flex:1; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:13px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ background:#fafafa; padding:12px; text-align:left; font-size:12px; color:#666; border-bottom:2px solid #e8e8e8; }}
td {{ padding:12px; font-size:13px; border-bottom:1px solid #f0f0f0; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; }}
.tag-active {{ background:#e6f7ff; color:#1890ff; }}
.tag-done {{ background:#f6ffed; color:#52c41a; }}
.empty {{ text-align:center; padding:40px; color:#999; font-size:13px; }}
.error-box {{ text-align:center; padding:40px; color:#ff4d4f; font-size:13px; background:#fff2f0; border-radius:6px; }}
.loading {{ text-align:center; padding:40px; color:#999; }}
.loading-spinner {{ display:inline-block; width:24px; height:24px; border:3px solid #f0f0f0; border-top-color:#1890ff; border-radius:50%; animation:spin .8s linear infinite; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style></head>
<body>
<div class="header">
  <h1>{title}</h1>
  <div>
    <button class="btn btn-primary" onclick="showState('default')">默认</button>
    <button class="btn" onclick="showState('loading')">加载中</button>
    <button class="btn" onclick="showState('empty')">空数据</button>
    <button class="btn" onclick="showState('error')">错误</button>
  </div>
</div>
<div class="container">
  <div id="state-default" class="card">
    <div class="search-bar">
      <input type="text" placeholder="搜索...">
      <button class="btn btn-primary">查询</button>
      <button class="btn btn-success">+ 新建</button>
    </div>
    <table>
      <thead><tr><th>ID</th><th>名称</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
      <tbody>
        <tr><td>1</td><td>示例数据</td><td><span class="tag tag-active">进行中</span></td><td>2026-07-13</td><td><a href="#">编辑</a> <a href="#" style="color:#ff4d4f;">删除</a></td></tr>
      </tbody>
    </table>
  </div>
  <div id="state-loading" class="card" style="display:none;">
    <div class="loading"><div class="loading-spinner"></div><p style="margin-top:12px;">数据加载中...</p></div>
  </div>
  <div id="state-empty" class="card" style="display:none;">
    <div class="empty"><p>暂无数据</p><button class="btn btn-primary" style="margin-top:12px;">+ 新建第一条</button></div>
  </div>
  <div id="state-error" class="card" style="display:none;">
    <div class="error-box"><p>⚠ 数据加载失败</p><p style="font-size:12px;margin-top:8px;">请检查网络连接后重试</p><button class="btn btn-primary" style="margin-top:12px;">重新加载</button></div>
  </div>
</div>
<script>
function showState(state) {{
  ['default','loading','empty','error'].forEach(s => {{
    document.getElementById('state-'+s).style.display = s===state ? '' : 'none';
  }});
}}
</script>
</body></html>"""
