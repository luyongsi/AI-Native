import asyncio, json, sys
from temporalio.client import Client

async def main():
    c = await Client.connect("localhost:7233", namespace="ai-native")
    cnt = 0
    async for wf in c.list_workflows('ExecutionStatus="Running"'):
        h = c.get_workflow_handle(wf.id)
        try:
            s = await h.query("get_progress")
            print(f"{wf.id}: state={s['state']} rework={s['rework_count']}")
        except:
            print(f"{wf.id}: ERROR querying state")
        cnt += 1
    if cnt == 0:
        print("No running workflows")

asyncio.run(main())
