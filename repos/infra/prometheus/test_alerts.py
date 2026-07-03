#!/usr/bin/env python3
"""
Prometheus AlertManager test script - triggers test alerts to verify Feishu integration.
"""
import httpx
import asyncio
import json
from datetime import datetime

TEST_ALERTS = [
    {
        "status": "firing",
        "labels": {
            "alertname": "HighAgentFailureRate",
            "severity": "warning",
            "component": "agent",
            "agent_id": "test-agent-1"
        },
        "annotations": {
            "summary": "Agent test-agent-1 失败率过高",
            "description": "Agent test-agent-1 在过去 5 分钟内失败率为 15.5%"
        },
        "startsAt": datetime.utcnow().isoformat() + "Z"
    },
    {
        "status": "firing",
        "labels": {
            "alertname": "HighLLMLatency",
            "severity": "warning",
            "component": "llm"
        },
        "annotations": {
            "summary": "LLM 调用延迟过高",
            "description": "P95 延迟为 35.2s，超过 30s 阈值"
        },
        "startsAt": datetime.utcnow().isoformat() + "Z"
    },
    {
        "status": "firing",
        "labels": {
            "alertname": "NATSConnectionDown",
            "severity": "critical",
            "component": "nats",
            "instance": "nats-1.local"
        },
        "annotations": {
            "summary": "NATS 连接断开",
            "description": "服务 nats-1.local 的 NATS 连接已断开"
        },
        "startsAt": datetime.utcnow().isoformat() + "Z"
    },
    {
        "status": "firing",
        "labels": {
            "alertname": "HighRedisMemory",
            "severity": "warning",
            "component": "redis"
        },
        "annotations": {
            "summary": "Redis 内存使用过高",
            "description": "内存使用率 92.5%"
        },
        "startsAt": datetime.utcnow().isoformat() + "Z"
    },
    {
        "status": "firing",
        "labels": {
            "alertname": "PostgreSQLPoolExhausted",
            "severity": "warning",
            "component": "database"
        },
        "annotations": {
            "summary": "PostgreSQL 连接池接近耗尽",
            "description": "当前使用 85% 连接"
        },
        "startsAt": datetime.utcnow().isoformat() + "Z"
    },
    {
        "status": "resolved",
        "labels": {
            "alertname": "SlowContextBuilder",
            "severity": "info",
            "component": "context_builder"
        },
        "annotations": {
            "summary": "Context Builder 耗时过长",
            "description": "P95 耗时 12.3s，可能影响用户体验"
        },
        "startsAt": "2024-01-01T00:00:00Z",
        "endsAt": datetime.utcnow().isoformat() + "Z"
    },
]


async def trigger_test_alert(alert_data: dict, endpoint: str = "http://localhost:8000/api/alerts/feishu"):
    """Send a test alert to the webhook endpoint."""
    payload = {
        "alerts": [alert_data]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(endpoint, json=payload)
            status = response.status_code
            text = response.text
            print(f"✓ Alert '{alert_data['labels']['alertname']}' sent")
            print(f"  Status: {status}")
            if status != 200:
                print(f"  Response: {text}")
            return status == 200
    except Exception as e:
        print(f"✗ Error sending alert: {e}")
        return False


async def main():
    print("=" * 60)
    print("Prometheus AlertManager - Feishu Integration Test")
    print("=" * 60)
    print()

    endpoint = "http://localhost:8000/api/alerts/feishu"
    print(f"Target endpoint: {endpoint}")
    print(f"Sending {len(TEST_ALERTS)} test alerts...\n")

    results = []
    for alert in TEST_ALERTS:
        success = await trigger_test_alert(alert, endpoint)
        results.append(success)
        await asyncio.sleep(0.5)  # Small delay between alerts

    print()
    print("=" * 60)
    print(f"Results: {sum(results)}/{len(results)} alerts sent successfully")
    print("=" * 60)

    if all(results):
        print("All test alerts sent! Check Feishu for notifications.")
        return 0
    else:
        print("Some alerts failed to send. Check the output above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
