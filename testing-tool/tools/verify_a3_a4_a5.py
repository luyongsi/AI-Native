"""
A3 -> A4 -> A5 End-to-End Verification Script (v2).

Key insight: workers subscribe through JetStream (AI_NATIVE_EVENTS stream)
but publish results on core NATS (nc.publish).

This script:
  1. Publishes dispatch messages through JetStream (workers receive these)
  2. Subscribes to core NATS for agent.result.* (workers publish here)

Run on remote:
  cd /opt/ai-native/repos/agent-workers && PYTHONPATH=. timeout 600 python3 verify_a3_a4_a5.py
"""
import asyncio
import json
import uuid
import sys


async def main():
    # Only import after environment is set up
    import nats
    from nats.js.api import (
        PubAck,
    )

    NATS_URL = "nats://localhost:4222"
    req_id = str(uuid.uuid4())

    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()

    # Workers subscribe via JetStream on subject patterns within AI_NATIVE_EVENTS
    STREAM = "AI_NATIVE_EVENTS"

    results = {}

    # Subscribe to core NATS for agent results (workers publish via nc.publish)
    async def on_a3_result(msg):
        data = json.loads(msg.data.decode())
        if data.get("req_id") != req_id:
            return
        results["A3"] = data
        r = data.get("result", {})
        print(f"[RECEIVED] A3: status={r.get('status')}")

    async def on_a4_result(msg):
        data = json.loads(msg.data.decode())
        if data.get("req_id") != req_id:
            return
        results["A4"] = data
        r = data.get("result", {})
        print(f"[RECEIVED] A4: status={r.get('status')}, "
              f"quality_score={r.get('quality_score')}")

    async def on_a5_result(msg):
        data = json.loads(msg.data.decode())
        if data.get("req_id") != req_id:
            return
        results["A5"] = data
        r = data.get("result", {})
        cr = r.get("check_report", {})
        print(f"[RECEIVED] A5: status={r.get('status')}, "
              f"overall_score={cr.get('overall_score')}, "
              f"total_issues={cr.get('total_issues')}")

    sub_a3 = await nc.subscribe("agent.result.A3", cb=on_a3_result)
    sub_a4 = await nc.subscribe("agent.result.A4", cb=on_a4_result)
    sub_a5 = await nc.subscribe("agent.result.A5", cb=on_a5_result)

    # Mock upstream outputs for the pipeline
    a1_output = {
        "requirement_draft": {
            "title": "会议室预订系统",
            "description": "企业内部的会议室在线预订管理系统，支持会议室查询、预约、取消、审批功能",
            "domain": "办公协作",
            "entities": [
                {"name": "会议室", "attributes": ["名称", "容量", "位置", "设备"],
                 "description": "会议室资源"},
                {"name": "预订记录", "attributes": ["会议主题", "开始时间", "结束时间", "参会人"],
                 "description": "预订记录"},
            ],
            "use_cases": ["查询可用会议室", "提交预订申请", "取消预订", "管理员审批"],
            "acceptance_criteria": ["Given 用户已登录 When 选择时间段并提交 Then 预订成功"],
            "constraints": ["同一时段不可重复预订"],
            "risks": ["并发预订冲突"],
        },
        "wireframe_url": "https://s3/xxx/wireframe.png",
        "confidence_score": 0.85,
    }

    a2_output = {
        "feasibility_assessment": {
            "technical": {"feasible": True, "assessment": "标准CRUD，技术可行"},
            "business": {"feasible": True, "assessment": "符合协作需求"},
            "risk_level": "low",
        },
        "quality_score": 0.72,
    }

    # Helper to publish via JetStream (workers subscribe through JS)
    async def publish_to(subject: str, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode()
        ack: PubAck = await js.publish(subject, data, stream=STREAM)
        print(f"  [PUB] {subject} (stream={ack.stream}, seq={ack.seq})")

    # Step 1: Dispatch A3
    print(f"\n===== A3 UI Generator (req={req_id}) =====")
    event_a3 = {
        "event_id": f"vfy-a3-{uuid.uuid4().hex[:8]}",
        "event_type": "context.ready",
        "req_id": req_id,
        "agent_id": "A3",
        "payload": {
            "req_id": req_id,
            "title": a1_output["requirement_draft"]["title"],
            "description": a1_output["requirement_draft"]["description"],
            "requirement_draft": a1_output["requirement_draft"],
            "a2_output": a2_output,
            "cycle": 0,
            "session_id": f"sess-{uuid.uuid4().hex[:8]}",
            "workflow_id": "wf-verify",
        },
    }
    await publish_to("context.ready.ui_generator", event_a3)

    print("Waiting for A3 (LLM prototype generation)...")
    for i in range(90):
        if "A3" in results:
            break
        await asyncio.sleep(1)
        if i % 15 == 0 and i > 0:
            print(f"  ... {i}s")

    if "A3" not in results:
        print("FAILED: A3 no response in 90s")
        return False

    a3_r = results["A3"]["result"]
    if a3_r.get("status") != "completed":
        print(f"FAILED: A3 status={a3_r.get('status')}")
        return False

    print(f"A3 PASSED: prototype_size={a3_r.get('prototype_size')}, source={a3_r.get('source')}")

    # Step 2: Dispatch A4
    print(f"\n===== A4 Spec Writer (req={req_id}) =====")
    event_a4 = {
        "event_id": f"vfy-a4-{uuid.uuid4().hex[:8]}",
        "event_type": "context.ready",
        "req_id": req_id,
        "agent_id": "A4",
        "payload": {
            "req_id": req_id,
            "title": a1_output["requirement_draft"]["title"],
            "a1_output": a1_output,
            "a2_output": a2_output,
            "a3_output": {
                "prototype_url": f"https://s3/prototypes/{req_id}/v1.html",
                "screens": [
                    {"name": "会议室列表", "state": "default"},
                    {"name": "加载中", "state": "loading"},
                    {"name": "空数据", "state": "empty"},
                    {"name": "错误", "state": "error"},
                ],
            },
            "cycle": 0,
            "session_id": f"sess-{uuid.uuid4().hex[:8]}",
            "workflow_id": "wf-verify",
        },
    }
    await publish_to("context.ready.spec_writer", event_a4)

    print("Waiting for A4 (LLM: Spec + OpenAPI + ERD + DDL)...")
    for i in range(180):
        if "A4" in results:
            break
        await asyncio.sleep(1)
        if i % 15 == 0 and i > 0:
            print(f"  ... {i}s")

    if "A4" not in results:
        print("FAILED: A4 no response in 180s")
        return False

    a4_r = results["A4"]["result"]
    if a4_r.get("status") != "completed":
        print(f"FAILED: A4 status={a4_r.get('status')}, error={a4_r.get('error', str(a4_r)[:300])}")
        return False

    print(f"A4 PASSED: quality_score={a4_r.get('quality_score')}, "
          f"source={a4_r.get('source')}, "
          f"endpoints={a4_r.get('metadata', {}).get('api_endpoint_count', 0)}, "
          f"entities={a4_r.get('metadata', {}).get('entity_count', 0)}")

    # Step 3: Dispatch A5
    print(f"\n===== A5 Design Review (req={req_id}) =====")
    event_a5 = {
        "event_id": f"vfy-a5-{uuid.uuid4().hex[:8]}",
        "event_type": "context.ready",
        "req_id": req_id,
        "agent_id": "A5",
        "payload": {
            "req_id": req_id,
            "a3_output": {
                "prototype_url": f"https://s3/prototypes/{req_id}/v1.html",
                "screens": [
                    {"name": "会议室列表", "state": "default"},
                    {"name": "加载中", "state": "loading"},
                    {"name": "空数据", "state": "empty"},
                    {"name": "错误", "state": "error"},
                ],
            },
            "a4_output": {
                "a4_missing": False,
                "spec_doc": a4_r.get("spec_doc", {}),
                "openapi_schema": a4_r.get("openapi_schema", {}),
                "erd_diagram": a4_r.get("erd_diagram", {}),
                "ddl_statements": a4_r.get("ddl_statements", ""),
            },
            "cycle": 0,
            "session_id": f"sess-{uuid.uuid4().hex[:8]}",
            "workflow_id": "wf-verify",
        },
    }
    await publish_to("context.ready.design_review", event_a5)

    print("Waiting for A5 (5-dimension LLM review)...")
    for i in range(300):
        if "A5" in results:
            break
        await asyncio.sleep(1)
        if i % 15 == 0 and i > 0:
            print(f"  ... {i}s")

    if "A5" not in results:
        print("FAILED: A5 no response in 300s")
        return False

    a5_r = results["A5"]["result"]
    if a5_r.get("status") != "completed":
        print(f"FAILED: A5 status={a5_r.get('status')}")
        return False

    cr = a5_r.get("check_report", {})
    print(f"A5 PASSED: overall_score={cr.get('overall_score')}, "
          f"total_issues={cr.get('total_issues')}")
    for dim in cr.get("dimensions", []):
        st = dim.get("status", "ok")
        sc = dim.get("score", "N/A")
        n = len(dim.get("issues", []))
        print(f"  [{dim['label']}] score={sc}, status={st}, issues={n}")

    print(f"\n{'='*50}")
    print(f"ALL 3 AGENTS VERIFIED: A3 -> A4 -> A5 pipeline works correctly")
    print(f"  A3: prototype generated ({a3_r.get('source')}, {a3_r.get('prototype_size')} chars)")
    print(f"  A4: spec written ({a4_r.get('source')}, score={a4_r.get('quality_score')})")
    print(f"  A5: design reviewed (score={cr.get('overall_score')}, {cr.get('total_issues')} issues)")
    print(f"{'='*50}")

    await sub_a3.unsubscribe()
    await sub_a4.unsubscribe()
    await sub_a5.unsubscribe()
    await nc.close()
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
