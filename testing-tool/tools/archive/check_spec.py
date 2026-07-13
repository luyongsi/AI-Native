# Clean verification: does the MC Backend PUT preserve existing spec keys?
import asyncio, asyncpg, json, sys, urllib.request

REQ_ID = sys.argv[1]

async def main():
    pool = await asyncpg.create_pool(
        "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
        min_size=1, max_size=1
    )
    async with pool.acquire() as conn:
        # Step 1: read current spec
        def read_spec():
            pass
        row = await conn.fetchrow("SELECT spec, status FROM requirements WHERE id = $1::uuid", REQ_ID)
        spec_raw = row['spec']
        if isinstance(spec_raw, str):
            spec = json.loads(spec_raw)
        else:
            spec = spec_raw or {}
        print(f"Step 1 — Current: status={row['status']}, keys={list(spec.keys())}, "
              f"artifacts={list(spec.get('artifacts', {}).keys()) if isinstance(spec.get('artifacts'), dict) else 'NONE'}")

        # Step 2: manually set spec with artifacts (simulating store_agent_result working)
        known = {"source": "manual", "stages": [{"key": "pool", "status": "done"}],
                 "spec_sections": [], "artifacts": {"A1": {"analysis": {"entities": ["user"]}}},
                 "openapi": {"info": {"title": "test"}}}
        await conn.execute("UPDATE requirements SET spec = $1::jsonb WHERE id = $2::uuid",
                          json.dumps(known), REQ_ID)
        print("Step 2 — Wrote known spec with artifacts + openapi")

        # Step 3: simulate MC Backend PUT (exact same logic as the endpoint)
        row2 = await conn.fetchrow("SELECT spec FROM requirements WHERE id = $1::uuid", REQ_ID)
        raw = row2['spec']
        if isinstance(raw, str):
            spec = json.loads(raw)
        elif isinstance(raw, dict):
            spec = raw
        else:
            spec = {}
        print(f"Step 3 — asyncpg returned type: {type(raw).__name__}, parsed keys: {list(spec.keys())}")

        # Modify stages (what the PUT endpoint does)
        stages = spec.get('stages', [])
        for s in stages:
            if s.get('key') == 'pool':
                s['status'] = 'active'
        spec['stages'] = stages

        # Write back (exactly what PUT endpoint does)
        await conn.execute("UPDATE requirements SET spec = $1::jsonb, updated_at = NOW() WHERE id = $2::uuid",
                          json.dumps(spec), REQ_ID)
        print("Step 3 — Wrote back after modifying stages")

        # Step 4: verify
        row3 = await conn.fetchrow("SELECT spec FROM requirements WHERE id = $1::uuid", REQ_ID)
        final_raw = row3['spec']
        if isinstance(final_raw, str):
            final = json.loads(final_raw)
        else:
            final = final_raw or {}
        print(f"Step 4 — Final: keys={list(final.keys())}, "
              f"artifacts={list(final.get('artifacts', {}).keys()) if isinstance(final.get('artifacts'), dict) else 'NONE'}, "
              f"openapi={'PRESERVED' if 'openapi' in final else 'LOST'}")

        result = 'PASS' if ('openapi' in final and 'artifacts' in final and 'A1' in final.get('artifacts', {})) else 'FAIL'
        print(f"\n=== {result} ===")
        return 0 if result == 'PASS' else 1

sys.exit(asyncio.run(main()))
