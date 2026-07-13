import asyncio, asyncpg, json
REQ_ID = '370c09e9-9f2e-4401-9559-b3a76ee99b56'

async def main():
    pool = await asyncpg.create_pool("postgresql://ai_native:ai_native_dev@localhost:5432/ai_native", min_size=1, max_size=1)
    async with pool.acquire() as conn:
        # 1. FULL spec JSONB
        row = await conn.fetchrow("SELECT spec FROM requirements WHERE id = $1::uuid", REQ_ID)
        spec_raw = row['spec']
        print("=== RAW spec type:", type(spec_raw).__name__, "===")
        if isinstance(spec_raw, str):
            print("RAW (first 200):", spec_raw[:200])
            spec = json.loads(spec_raw)
        else:
            spec = spec_raw or {}
            print("RAW (first 200):", json.dumps(spec, ensure_ascii=False)[:200])

        print()

        # 2. ALL api_schemas versions
        schemas = await conn.fetch("SELECT version, schema_json, validation_passed, created_at FROM api_schemas WHERE req_id = $1::uuid ORDER BY version", REQ_ID)
        for s in schemas:
            sj = s['schema_json']
            if isinstance(sj, str):
                sj = json.loads(sj)
            print(f"=== API_SCHEMA v{s['version']} valid={s['validation_passed']} created={s['created_at']} ===")
            print(json.dumps(sj, indent=2, ensure_ascii=False))
            print()

        # 3. ALL erd_designs versions
        erds = await conn.fetchrow("SELECT version, erd_mermaid, ddl, entities, relationships FROM erd_designs WHERE req_id = $1::uuid ORDER BY version DESC LIMIT 1", REQ_ID)
        if erds:
            ents = erds['entities']
            if isinstance(ents, str):
                ents = json.loads(ents)
            rels = erds['relationships']
            if isinstance(rels, str):
                rels = json.loads(rels)
            print(f"=== ERD v{erds['version']} ===")
            print("DDL:")
            print(erds['ddl'][:5000] if erds['ddl'] else '(empty)')
            print()
            print("MERMAID:")
            print(erds['erd_mermaid'][:3000] if erds['erd_mermaid'] else '(empty)')
            print()
            print("ENTITIES:")
            print(json.dumps(ents, indent=2, ensure_ascii=False)[:3000])
            print()
            print("RELATIONSHIPS:")
            print(json.dumps(rels, indent=2, ensure_ascii=False)[:2000])

        # 4. A1 artifact (if exists)
        arts = spec.get('artifacts', {})
        if isinstance(arts, dict) and arts:
            for k, v in arts.items():
                print(f"\n=== ARTIFACT {k} ({len(json.dumps(v, ensure_ascii=False))} chars) ===")
                print(json.dumps(v, indent=2, ensure_ascii=False)[:3000])

asyncio.run(main())
