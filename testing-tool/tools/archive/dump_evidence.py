"""Extract A3 failure evidence from the database."""
import asyncio, asyncpg, json, os, sys

async def main():
    pool = await asyncpg.create_pool(
        "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native",
        min_size=1, max_size=3)
    async with pool.acquire() as conn:
        # Find latest requirement with artifacts
        rows = await conn.fetch(
            "SELECT id, title, status, spec, created_at FROM requirements "
            "WHERE spec->>'artifacts' IS NOT NULL AND spec->>'artifacts' != '{}' "
            "ORDER BY created_at DESC LIMIT 5"
        )
        if not rows:
            # Fallback: find any recent requirement
            rows = await conn.fetch(
                "SELECT id, title, status, spec, created_at FROM requirements ORDER BY created_at DESC LIMIT 5"
            )

        for row in rows:
            req_id = str(row["id"])
            spec = row["spec"] if isinstance(row["spec"], dict) else json.loads(row["spec"])
            arts = spec.get("artifacts", {})
            if isinstance(arts, str):
                try: arts = json.loads(arts)
                except: arts = {}

            print(f"{'='*70}")
            print(f"req_id: {req_id}")
            print(f"title: {row['title']}")
            print(f"status: {row['status']}")
            print(f"created: {row['created_at']}")
            print()

            # A1
            a1 = arts.get("A1", {})
            if isinstance(a1, str):
                try: a1 = json.loads(a1)
                except: a1 = {"_raw": a1[:200]}
            print("--- A1 Output ---")
            print(f"  domain: {a1.get('domain', 'N/A')}")
            print(f"  source: {a1.get('source', 'N/A')}")
            print(f"  status: {a1.get('status', 'N/A')}")
            draft = a1.get("requirement_draft", {})
            print(f"  draft title: {draft.get('title', 'N/A')}")
            print(f"  acceptance_criteria: {len(draft.get('acceptance_criteria',[]))} items")
            print(f"  entities: {json.dumps(a1.get('entities',{}), ensure_ascii=False)}")
            print()

            # A2
            a2 = arts.get("A2", {})
            if isinstance(a2, str):
                try: a2 = json.loads(a2)
                except: a2 = {"_raw": str(a2)[:200]}
            print("--- A2 Output ---")
            if a2:
                print(json.dumps(a2, indent=2, ensure_ascii=False)[:800])
            else:
                print("  (not found in spec.artifacts)")
            print()

            # A3
            a3 = arts.get("A3", {})
            if isinstance(a3, str):
                try: a3 = json.loads(a3)
                except: a3 = {"_raw": str(a3)[:200]}
            print("--- A3 Output ---")
            print(f"  status: {a3.get('status', 'N/A')}")
            print(f"  error: {a3.get('error', 'no error field')}")
            print(f"  full A3 data: {json.dumps(a3, indent=2, ensure_ascii=False)[:1500]}")
            print()

            # A4
            print("--- A4 Output ---")
            openapi = spec.get("openapi", {})
            erd = spec.get("erd", {})
            if isinstance(openapi, str):
                try: openapi = json.loads(openapi)
                except: pass
            if isinstance(erd, str):
                try: erd = json.loads(erd)
                except: pass
            api_schema = openapi.get("schema", openapi) if isinstance(openapi, dict) else {}
            paths = api_schema.get("paths", {}) if isinstance(api_schema, dict) else {}
            print(f"  openapi paths: {list(paths.keys())[:10]}")
            e_entities = erd.get("entities", []) if isinstance(erd, dict) else []
            print(f"  erd entities: {len(e_entities)} tables")
            for e in e_entities[:5]:
                name = e.get("name", e.get("table_name", "?"))
                cols = e.get("columns", [])
                print(f"    - {name}: {len(cols)} columns")
            if not e_entities:
                print(f"  erd keys: {list(erd.keys()) if isinstance(erd,dict) else 'N/A'}")
            print()

            # A5
            a5 = arts.get("A5", {})
            if isinstance(a5, str):
                try: a5 = json.loads(a5)
                except: a5 = {"_raw": str(a5)[:200]}
            print("--- A5 Output ---")
            print(f"  pass: {a5.get('pass', 'N/A')}")
            print(f"  status: {a5.get('status', 'N/A')}")
            scores = a5.get("scores", {})
            if isinstance(scores, dict):
                for k, v in scores.items():
                    if isinstance(v, dict):
                        print(f"  score.{k}: {v.get('score')} (passed={v.get('passed')})")
            issues = a5.get("issues", [])
            print(f"  issues: {len(issues)}")
            for i in issues[:8]:
                sev = i.get("severity", "?")
                desc = i.get("description", "")[:180]
                cat = i.get("category", i.get("heuristic", i.get("risk", "")))
                print(f"    [{sev}] {cat}: {desc}")
            print()

            # Summary
            print("--- Root Cause Chain ---")
            print(f"  A1 → source={a1.get('source')}, domain={a1.get('domain')}")
            print(f"  A3 → status={a3.get('status')}, error={a3.get('error','none')}")
            print(f"  A4 → openapi_paths={len(paths)}, erd_entities={len(e_entities)}")
            print(f"  A5 → pass={a5.get('pass')}, avg_score={scores.get('average','N/A')}, issues={len(issues)}")
            print(f"  Outcome: {'PASS' if a5.get('pass') else 'REWORK/FALLBACK'}")
            print()

    await pool.close()

asyncio.run(main())
