import nats, asyncio, json

async def main():
    nc = await nats.connect('nats://localhost:4222')
    envelope = {
        "event_id": "gate0-approved-c35ee46d",
        "event_type": "gate.0.approved",
        "timestamp": "2026-07-03T02:48:00",
        "payload": {"req_id": "c35ee46d-5e93-41c2-912b-2de360b7b3c6", "gate": 0},
        "req_id": "c35ee46d-5e93-41c2-912b-2de360b7b3c6"
    }
    await nc.publish("gate.0.approved", json.dumps(envelope, ensure_ascii=False).encode())
    print("Published gate.0.approved")
    await nc.close()
asyncio.run(main())
