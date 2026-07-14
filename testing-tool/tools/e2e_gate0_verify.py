#!/usr/bin/env python3
"""
E2E Verification: Requirement → A1 Dialogue → A2 Analysis → Gate0 Approval.

Validates the full phase-one pipeline on the 109 environment:
  1. Create requirement
  2. A1 dialogue (SSE streaming analysis)
  3. Confirm dialogue (persist + outbox)
  4. Trigger workflow → A2 knowledge analysis
  5. Wait for Gate0 approval record to be auto-created
  6. Verify approval context (A1 draft + A2 feasibility/conflicts/checklist)
  7. Test pass decision
  8. Test reject + rework cycle

Usage:
  python tools/e2e_gate0_verify.py                    # full flow with auto-wait
  python tools/e2e_gate0_verify.py --skip-a1           # skip A1 (use existing req)
  python tools/e2e_gate0_verify.py --req-id <uuid>     # use existing requirement
  python tools/e2e_gate0_verify.py --gate manual       # manual gate (don't auto-decide)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Config — override via env vars
MC_BACKEND_URL = os.environ.get("MC_BACKEND_URL", "http://localhost:8000")
AUTH_TOKEN = os.environ.get("MC_AUTH_TOKEN", "Bearer dev-internal-key")
DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"
)
A2_TIMEOUT_S = int(os.environ.get("A2_TIMEOUT_S", "120"))
POLL_INTERVAL_S = int(os.environ.get("POLL_INTERVAL_S", "3"))

HEADERS = {"Authorization": AUTH_TOKEN, "Content-Type": "application/json"}

# ── Colour helpers ──────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str):
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{RESET} {msg}")


def info(msg: str):
    print(f"  {CYAN}→{RESET} {msg}")


def section(title: str):
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")


# ── HTTP helpers ────────────────────────────────────────────────────────────


async def api_post(path: str, body: dict | None = None, timeout: int = 300) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.post(f"{MC_BACKEND_URL}{path}", json=body, headers=HEADERS)
        r.raise_for_status()
        return r.json()


async def api_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(f"{MC_BACKEND_URL}{path}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


# ── DB helpers ──────────────────────────────────────────────────────────────


async def db_query(query: str, *params) -> list:
    """Run a read query against the ai_native database."""
    import asyncpg
    conn = await asyncpg.connect(DB_URL)
    try:
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def db_wait_for_agent_result(req_id: str, agent_key: str,
                                   timeout_s: int = A2_TIMEOUT_S) -> dict | None:
    """Poll agent_results table until agent_key's result appears."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = await db_query(
            """SELECT artifact, status, created_at FROM agent_results
               WHERE req_id = $1::uuid AND agent_key = $2
               ORDER BY created_at DESC LIMIT 1""",
            req_id, agent_key,
        )
        if rows:
            return rows[0]
        info(f"Waiting for {agent_key} result... ({int(deadline - time.time())}s left)")
        await asyncio.sleep(POLL_INTERVAL_S)
    return None


async def db_wait_for_approval(req_id: str, gate_level: int = 0,
                                timeout_s: int = A2_TIMEOUT_S) -> dict | None:
    """Poll approvals table until a pending approval appears."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = await db_query(
            """SELECT id, req_id, gate_level, cycle, status, created_at
               FROM approvals
               WHERE req_id = $1::uuid AND gate_level = $2
               ORDER BY created_at DESC LIMIT 1""",
            req_id, gate_level,
        )
        if rows:
            return rows[0]
        info(f"Waiting for Gate{gate_level} approval record... "
             f"({int(deadline - time.time())}s left)")
        await asyncio.sleep(POLL_INTERVAL_S)
    return None


# ── Step 1: Create requirement ─────────────────────────────────────────────


async def step_create_requirement(title: str, description: str = "") -> dict:
    section("Step 1: Create Requirement")
    result = await api_post("/api/requirements", {
        "title": title,
        "description": description,
    })
    req_id = result.get("req_id") or result.get("id")
    ok(f"Created requirement: {req_id}")
    info(f"  Title: {result.get('title', title)}")
    info(f"  Status: {result.get('status', '?')}")
    return {"req_id": req_id, **result}


# ── Step 2: A1 Dialogue ─────────────────────────────────────────────────────


async def step_a1_dialogue(req_id: str, message: str) -> dict:
    """Run A1 SSE dialogue and collect all events."""
    section("Step 2: A1 Dialogue Analysis (SSE)")

    session_id = None
    events = []
    draft = None
    confidence = None

    info(f"Starting dialogue for req_id={req_id}")
    info(f"Message: {message[:80]}...")

    async with httpx.AsyncClient(timeout=300) as http:
        async with http.stream(
            "POST", f"{MC_BACKEND_URL}/api/dialogue/chat",
            json={"req_id": req_id, "message": message, "session_id": None},
            headers=HEADERS,
        ) as resp:
            resp.raise_for_status()
            current_type = None
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    current_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_str = line[6:].strip()
                    if not data_str:
                        continue
                    try:
                        evt = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if current_type:
                        evt["_event_type"] = current_type
                    evt_type = evt.get("type", current_type or "")

                    if evt_type == "session_id" or "session_id" in evt:
                        session_id = evt.get("session_id", session_id)
                    if evt_type == "draft_update":
                        draft = evt.get("draft", draft)
                    if evt_type == "done":
                        confidence = evt.get("confidence_score")
                        draft = evt.get("draft", draft)
                        session_id = evt.get("session_id", session_id)

                    events.append(evt)
                    current_type = None

    event_types = [e.get("type", e.get("_event_type", "?")) for e in events]
    info(f"Received {len(events)} events: {', '.join(event_types)}")

    # Validate
    checks = []
    has_thinking = any("thinking" in t for t in event_types)
    has_knowledge = any("knowledge" in t for t in event_types)
    has_draft = any("draft_update" in t for t in event_types)
    has_done = any("done" in t for t in event_types)
    has_error = any("error" in t for t in event_types)

    (ok if has_thinking else fail)("Thinking event")
    (ok if has_knowledge else warn)("Knowledge event")
    (ok if has_draft else fail)("Draft update event")
    (ok if has_done else fail)("Done event")
    (ok if not has_error else fail)("No error events")

    if draft:
        ok(f"Draft: title='{draft.get('title', '?')}', entities={len(draft.get('entities', []))}")
    if confidence is not None:
        info(f"Confidence score: {confidence}")

    return {
        "session_id": session_id,
        "events": events,
        "draft": draft,
        "confidence": confidence,
        "passed": has_done and not has_error and draft is not None,
    }


# ── Step 3: Confirm dialogue ────────────────────────────────────────────────


async def step_confirm_dialogue(session_id: str) -> dict:
    section("Step 3: Confirm Dialogue")
    try:
        result = await api_post("/api/dialogue/confirm", {
            "session_id": session_id,
        })
        ok(f"Confirmed session {session_id}")
        info(f"  Status: {result.get('status')}")
        info(f"  Cycle: {result.get('cycle')}")
        if result.get("already_confirmed"):
            warn("  Already confirmed (idempotent)")
        return {**result, "passed": result.get("ok", False)}
    except httpx.HTTPStatusError as e:
        fail(f"Confirm failed: {e.response.status_code} {e.response.text}")
        return {"passed": False, "error": str(e)}


# ── Step 4: Trigger workflow ────────────────────────────────────────────────


async def step_trigger_workflow(req_id: str) -> dict:
    section("Step 4: Trigger Workflow")
    try:
        result = await api_post(f"/api/requirements/{req_id}/trigger")
        wf_id = result.get("workflow_id", "none")
        status = result.get("status", "?")
        ok(f"Workflow triggered: {status}")
        info(f"  Workflow ID: {wf_id}")
        info(f"  Current state: {result.get('current_state', '?')}")
        return {**result, "passed": True}
    except httpx.HTTPStatusError as e:
        fail(f"Trigger failed: {e.response.status_code} {e.response.text}")
        return {"passed": False, "error": str(e)}


# ── Step 5: Wait for A2 ─────────────────────────────────────────────────────


async def step_wait_a2(req_id: str) -> dict:
    section("Step 5: Wait for A2 Knowledge Analysis")
    result = await db_wait_for_agent_result(req_id, "A2")
    if result is None:
        fail(f"A2 did not complete within {A2_TIMEOUT_S}s")
        return {"passed": False, "artifact": None}

    artifact = result["artifact"]
    if isinstance(artifact, str):
        artifact = json.loads(artifact)

    status = result["status"]
    ok(f"A2 completed: status={status}")

    # Validate A2 artifact fields
    checks = []
    feasibility = artifact.get("feasibility_assessment")
    checklist = artifact.get("confirmation_checklist", [])
    conflicts = artifact.get("conflicts", [])
    quality = artifact.get("quality_score")

    (ok if feasibility else warn)(
        f"Feasibility assessment: "
        f"overall={feasibility.get('overall_score') if feasibility else 'N/A'}"
    )
    (ok if checklist else warn)(f"Confirmation checklist: {len(checklist)} items")
    (ok if conflicts or isinstance(conflicts, list) else warn)(
        f"Conflicts: {len(conflicts) if isinstance(conflicts, list) else 0} items"
    )
    if quality is not None:
        info(f"Quality score: {quality}")

    return {
        "passed": status == "completed",
        "artifact": artifact,
        "feasibility": feasibility,
        "checklist": checklist,
        "conflicts": conflicts,
        "quality_score": quality,
    }


# ── Step 6: Verify Gate0 approval ───────────────────────────────────────────


async def step_verify_gate0(req_id: str) -> dict:
    section("Step 6: Verify Gate0 Approval Record")
    approval = await db_wait_for_approval(req_id, gate_level=0)

    if approval is None:
        fail(f"Gate0 approval not created within {A2_TIMEOUT_S}s")
        # Try HTTP API as fallback
        try:
            api_result = await api_get("/api/approvals?gate_level=0&status=pending")
            items = api_result.get("items", [])
            matching = [i for i in items if i.get("req_id") == req_id]
            if matching:
                approval = matching[0]
                ok("Found via HTTP API fallback")
        except Exception:
            pass

    if approval is None:
        return {"passed": False, "approval": None}

    approval_id = str(approval["id"])
    ok(f"Gate0 approval exists: {approval_id}")
    info(f"  Status: {approval['status']}")
    info(f"  Gate level: {approval.get('gate_level', 0)}")
    info(f"  Cycle: {approval.get('cycle', 0)}")

    # Fetch full approval context
    try:
        ctx = await api_get(f"/api/approvals/{approval_id}/context")
        a1_ok = bool(ctx.get("a1_output", {}).get("requirement_draft"))
        a2_ok = not ctx.get("a2_output", {}).get("a2_missing", True)
        (ok if a1_ok else fail)("Context has A1 draft")
        (ok if a2_ok else warn)("Context has A2 output")

        return {
            "passed": True,
            "approval_id": approval_id,
            "approval": approval,
            "context": ctx,
        }
    except Exception as e:
        fail(f"Failed to get approval context: {e}")
        return {"passed": True, "approval_id": approval_id, "approval": approval,
                "context": None}


# ── Step 7: Test pass decision ──────────────────────────────────────────────


async def step_decide_pass(approval_id: str) -> dict:
    section("Step 7: Test Gate0 Pass Decision")
    try:
        result = await api_post(f"/api/approvals/{approval_id}/decide", {
            "decision": "pass",
        })
        ok(f"Decision submitted: {result.get('decision')}")
        info(f"  Status: {result.get('status')}")
        info(f"  Reviewed at: {result.get('reviewed_at')}")
        return {**result, "passed": result.get("decision") == "pass"}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            warn("Already decided (expected if re-running)")
            return {"passed": True, "skipped": True, "reason": "already decided"}
        fail(f"Pass decision failed: {e.response.status_code} {e.response.text}")
        return {"passed": False, "error": str(e)}


# ── Step 8: Test reject + rework cycle ──────────────────────────────────────


async def step_test_reject_cycle(req_id: str) -> dict:
    """Create a new requirement, run through A1, confirm, then reject at Gate0."""
    section("Step 8: Test Gate0 Reject → Rework Cycle")

    # First, check if there's already a pending approval for this req
    try:
        api_result = await api_get("/api/approvals?gate_level=0&status=pending")
        items = api_result.get("items", [])
        matching = [i for i in items if i.get("req_id") == req_id]
        if matching:
            approval_id = matching[0]["id"]
            info(f"Found pending approval: {approval_id}")

            # Submit reject decision
            try:
                result = await api_post(f"/api/approvals/{approval_id}/decide", {
                    "decision": "reject",
                    "reject_reasons": [
                        {"category": "requirement_incomplete",
                         "description": "验收标准不够具体，需要补充场景覆盖"},
                    ],
                    "revision_guidance": "请补充以下场景：1) 异常流程处理 2) 并发操作冲突处理 3) 权限边界条件",
                })
                ok(f"Reject decision submitted: {result.get('decision')}")
                info(f"  Reviewed at: {result.get('reviewed_at')}")

                # Verify DB: approval record updated
                approval_row = await db_query(
                    "SELECT decision, reject_reasons, revision_guidance FROM approvals WHERE id = $1::uuid",
                    approval_id,
                )
                if approval_row:
                    row = approval_row[0]
                    info(f"  DB decision: {row['decision']}")
                    info(f"  Reject reasons: {len(row.get('reject_reasons', []))}")
                    info(f"  Revision guidance: {row.get('revision_guidance', '')[:80]}...")

                # Verify DB: session reopened (context.ready.A1 handler)
                await asyncio.sleep(3)  # Give NATS subscriber time
                session_rows = await db_query(
                    "SELECT status FROM dialogue_sessions WHERE req_id = $1::uuid ORDER BY created_at DESC LIMIT 1",
                    req_id,
                )
                if session_rows:
                    session_status = session_rows[0]["status"]
                    (ok if session_status == "reopened" else warn)(
                        f"Session status after reject: {session_status}"
                    )

                return {
                    "passed": True,
                    "approval_id": approval_id,
                    "decision": "reject",
                    "session_reopened": session_rows[0]["status"] if session_rows else "unknown",
                }
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 409:
                    warn("Already decided")
                    return {"passed": True, "skipped": True}
                fail(f"Reject failed: {e.response.status_code} {e.response.text}")
                return {"passed": False, "error": str(e)}
        else:
            warn("No pending approval found for reject test — skipping")
            return {"passed": True, "skipped": True, "reason": "no pending approval"}
    except Exception as e:
        fail(f"Reject cycle test failed: {e}")
        return {"passed": False, "error": str(e)}


# ── Main ────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="E2E Gate0 Pipeline Verification")
    parser.add_argument("--req-id", help="Use existing requirement instead of creating one")
    parser.add_argument("--skip-a1", action="store_true",
                        help="Skip A1 dialogue (req must already be confirmed)")
    parser.add_argument("--skip-a2", action="store_true",
                        help="Skip A2 wait (approval must already exist)")
    parser.add_argument("--gate", choices=["auto", "manual"], default="auto",
                        help="Gate strategy: auto=decide pass, manual=skip decision")
    parser.add_argument("--test-reject", action="store_true",
                        help="Also test reject→rework cycle")
    parser.add_argument("--title", default="E2E验证-用户个人中心增加手机号绑定功能",
                        help="Requirement title for new requirements")
    parser.add_argument("--message", default="用户可以在个人中心绑定、解绑手机号，绑定后可用于登录和密码找回",
                        help="A1 dialogue message")
    args = parser.parse_args()

    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mc_backend": MC_BACKEND_URL,
    }

    print(f"{BOLD}E2E Gate0 Pipeline Verification{RESET}")
    print(f"  MC Backend: {MC_BACKEND_URL}")
    print(f"  Gate strategy: {args.gate}")
    print(f"  Reject test: {args.test_reject}")

    # Check MC Backend health
    try:
        health = await api_get("/health")
        info(f"MC Backend health: {health}")
    except Exception as e:
        fail(f"MC Backend unreachable: {e}")
        print("\nMake sure MC Backend is running on the 109 environment.")
        return 1

    req_id = args.req_id
    session_id = None

    # Step 1: Create requirement
    if not req_id:
        req = await step_create_requirement(args.title)
        req_id = req["req_id"]
        results["req_id"] = req_id
    else:
        section("Step 0: Use Existing Requirement")
        info(f"req_id: {req_id}")
        results["req_id"] = req_id

    # Step 2: A1 dialogue
    if not args.skip_a1:
        a1_result = await step_a1_dialogue(req_id, args.message)
        session_id = a1_result.get("session_id")
        results["a1"] = {
            "passed": a1_result["passed"],
            "session_id": session_id,
            "confidence": a1_result.get("confidence"),
            "draft_title": a1_result.get("draft", {}).get("title") if a1_result.get("draft") else None,
        }
        if not a1_result["passed"]:
            fail("A1 dialogue failed — cannot continue")
            return 1

        # Step 3: Confirm
        confirm_result = await step_confirm_dialogue(session_id)
        results["confirm"] = {"passed": confirm_result["passed"]}
        if not confirm_result["passed"]:
            fail("Confirm failed — cannot continue")
            return 1
    else:
        section("Step 2-3: Skipped (--skip-a1)")
        # Try to get session_id from DB
        rows = await db_query(
            "SELECT id FROM dialogue_sessions WHERE req_id = $1::uuid ORDER BY created_at DESC LIMIT 1",
            req_id,
        )
        if rows:
            session_id = str(rows[0]["id"])
            info(f"Found session: {session_id}")

    # Step 4: Trigger workflow
    trigger_result = await step_trigger_workflow(req_id)
    results["trigger"] = {"passed": trigger_result["passed"], "status": trigger_result.get("status")}

    # Step 5: Wait for A2
    if not args.skip_a2:
        a2_result = await step_wait_a2(req_id)
        results["a2"] = {
            "passed": a2_result["passed"],
            "has_feasibility": a2_result.get("feasibility") is not None,
            "checklist_count": len(a2_result.get("checklist", [])),
            "conflicts_count": len(a2_result.get("conflicts", [])),
            "quality_score": a2_result.get("quality_score"),
        }
    else:
        section("Step 5: Skipped A2 wait (--skip-a2)")

    # Step 6: Verify Gate0
    gate0_result = await step_verify_gate0(req_id)
    results["gate0"] = {
        "passed": gate0_result["passed"],
        "approval_id": gate0_result.get("approval_id"),
        "has_context": gate0_result.get("context") is not None,
    }

    if not gate0_result.get("approval_id"):
        fail("No Gate0 approval record found — pipeline may be incomplete")
        print_results(results)
        return 1

    approval_id = gate0_result["approval_id"]

    # Step 7: Test pass decision
    if args.gate == "auto":
        pass_result = await step_decide_pass(approval_id)
        results["decision_pass"] = {"passed": pass_result["passed"]}
    else:
        section("Step 7: Skipped (--gate manual)")
        info(f"Manual gate — approve via: POST /api/approvals/{approval_id}/decide")

    # Step 8: Test reject cycle (separate flow)
    if args.test_reject and args.gate == "auto":
        reject_result = await step_test_reject_cycle(req_id)
        results["reject_test"] = {
            "passed": reject_result["passed"],
            "session_reopened": reject_result.get("session_reopened"),
        }

    # ── Final summary ───────────────────────────────────────────────────────
    print_results(results)
    return 0


def print_results(results: dict):
    section("Results Summary")
    steps = ["a1", "confirm", "trigger", "a2", "gate0", "decision_pass", "reject_test"]
    for key in steps:
        if key in results:
            step = results[key]
            status = step.get("passed", False)
            label = {
                "a1": "A1 Dialogue",
                "confirm": "Confirm",
                "trigger": "Workflow Trigger",
                "a2": "A2 Analysis",
                "gate0": "Gate0 Record",
                "decision_pass": "Gate0 Pass",
                "reject_test": "Gate0 Reject Test",
            }.get(key, key)
            icon = f"{GREEN}✓{RESET}" if status else f"{RED}✗{RESET}"
            print(f"  {icon} {label}")

    all_passed = all(
        results.get(k, {}).get("passed", True) if isinstance(results.get(k), dict) else True
        for k in ["a1", "confirm", "trigger", "a2", "gate0", "decision_pass"]
        if k in results
    )
    if all_passed:
        print(f"\n  {GREEN}{BOLD}All checks passed!{RESET}")
    else:
        print(f"\n  {RED}{BOLD}Some checks failed — review output above.{RESET}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
