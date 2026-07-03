import asyncio
import json
import nats
import sys

async def main():
    nc = await nats.connect("nats://localhost:4222")
    print("Connected to NATS. Waiting for msg_received (timeout 10s)...", flush=True)
    received = []

    async def handler(msg):
        data = json.loads(msg.data.decode())
        received.append(data)
        text = data["payload"]["text"]
        print("RECEIVED: " + text, flush=True)

    sub = await nc.subscribe("msg_received", cb=handler)
    await asyncio.sleep(10)
    await sub.unsubscribe()
    print("Done. Total messages: " + str(len(received)), flush=True)
    await nc.drain()

asyncio.run(main())
