import asyncio, asyncpg, json, sys, urllib.request

REQ_ID = sys.argv[1]

async def main():
    pool = await asyncpg.create_pool(
        "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
        min_size=1, max_size=1
    )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM gate_approvals WHERE req_id = $1::uuid AND gate = $2 AND status = $3 ORDER BY created_at DESC LIMIT 1",
            REQ_ID, int(sys.argv[2]) if len(sys.argv) > 2 else 1, "pending"
        )
        gate_id = row['id'] if row else None
        print(f"Gate {sys.argv[2] if len(sys.argv) > 2 else 1}: {gate_id}")

        if gate_id:
            url = f"http://localhost:8000/api/approvals/{gate_id}/approve"
            req = urllib.request.Request(url, data=b'{"comment":"pass"}',
                headers={'Content-Type': 'application/json'}, method='POST')
            resp = urllib.request.urlopen(req)
            print(f"Approve: {resp.status}")

asyncio.run(main())
