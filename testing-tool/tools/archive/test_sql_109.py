import asyncio, asyncpg

async def main():
    pool = await asyncpg.create_pool(
        "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
        min_size=1, max_size=1
    )
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """UPDATE requirements
                   SET spec = jsonb_set(
                       COALESCE(spec, '{}'::jsonb),
                       '{artifacts,A1}',
                       '{"test": true}'::jsonb,
                       true
                   ),
                   updated_at = NOW()
                   WHERE id = '3b6f4767-c263-482c-9d7d-88c02f49a20d'::uuid"""
            )
            print("OK")
        except Exception as e:
            print("Error: " + str(e))

asyncio.run(main())
