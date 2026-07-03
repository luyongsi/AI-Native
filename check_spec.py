import json, asyncio, asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://ai_native:ai_native_dev@localhost:5432/ai_native")
    row = await conn.fetchrow(
        "SELECT spec FROM requirements WHERE id = $1::uuid",
        "91ba906c-13bb-437d-a0dd-68d9b35512fb"
    )
    spec = row["spec"]
    if isinstance(spec, str):
        spec = json.loads(spec)
    sections = spec.get("sections", [])
    for s in sections:
        print(f"### {s['id']}: {s['title']}")
        print(s.get("content", "")[:400])
        print()
    await conn.close()

asyncio.run(main())
