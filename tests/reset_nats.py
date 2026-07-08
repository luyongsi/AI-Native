import asyncio, nats

async def p():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    try:
        si = await js.stream_info("AI_NATIVE_EVENTS")
        print(f"Stream AI_NATIVE_EVENTS: messages={si.state.messages}")
    except Exception as e:
        print(f"Error: {e}")

    try:
        await js.delete_stream("AI_NATIVE_EVENTS")
        print("Stream deleted")
    except:
        print("Stream not found")

    await js.add_stream(
        name="AI_NATIVE_EVENTS",
        subjects=["context.ready.>", "agent.result.>", "agent.status.changed.>", "orchestrator.>"],
        retention="interest",
        storage="file",
    )
    print("Stream recreated")
    await nc.close()

asyncio.run(p())
