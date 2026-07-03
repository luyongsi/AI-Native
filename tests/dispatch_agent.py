import nats, asyncio, json, sys

# Manual agent dispatcher - triggers each agent in sequence
# REQ_ID: the requirement to work on
REQ_ID = "c35ee46d-5e93-41c2-912b-2de360b7b3c6"

AGENTS = [
    ("A4", "context.ready.spec_writer", "designing"),
    # A5 will be triggered after A4
    # A6 after A5
]

async def trigger_agent(agent_type, subject, state):
    nc = await nats.connect('nats://localhost:4222')
    envelope = {
        "event_id": f"dispatch-{agent_type}-{REQ_ID}-manual",
        "event_type": subject,
        "timestamp": "2026-07-03T03:00:00.000Z",
        "payload": {
            "req_id": REQ_ID,
            "state": state,
            "context": f"Manual dispatch to {agent_type}"
        },
        "req_id": REQ_ID
    }
    await nc.publish(subject, json.dumps(envelope, ensure_ascii=False).encode())
    print(f"Published {subject} for {agent_type}")
    await nc.close()

if __name__ == "__main__":
    agent = sys.argv[1] if len(sys.argv) > 1 else "A4"
    state = sys.argv[2] if len(sys.argv) > 2 else "designing"

    subject_map = {
        "A4": "context.ready.spec_writer",
        "A5": "context.ready.design_review",
        "A6": "context.ready.spec_decomposer",
        "A2": "context.ready.knowledge_analyst",
        "A7": "context.ready.test_case_generator",
        "A8": "context.ready.architecture_expert",
        "A9": "context.ready.dev_agent",
        "A11": "context.ready.test_agent",
        "A12": "context.ready.code_review",
    }

    subject = subject_map.get(agent, f"context.ready.{agent}")
    asyncio.run(trigger_agent(agent, subject, state))
