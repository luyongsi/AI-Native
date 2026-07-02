"""Integration test for Context Builder pipeline."""
import json
from pipeline import ContextBuilder
from embedder import Embedder

db_config = {
    "host": "localhost",
    "port": 5432,
    "database": "ai_native",
    "user": "ai_native",
    "password": "ai_native_dev",
}

builder = ContextBuilder(db_config=db_config)

# Test 1: A9 agent (expects code docs)
print("=" * 60)
print("TEST 1: A9 agent (code generation)")
result = builder.build_context(target_agent="A9", req_id="req-001", task_id="task-build-api", max_tokens=2000)
print(f"  tokens_used: {result['tokens_used']}")
print(f"  tokens_discarded: {result['tokens_discarded']}")
print(f"  fill_rate: {result['fill_rate']}")
print(f"  head items: {len(result['head'])}")
print(f"  mid items:  {len(result['mid'])}")
print(f"  tail items: {len(result['tail'])}")
print(f"  discarded:  {len(result['discarded'])}")
for item in result["head"]:
    print(f"    HEAD [{item['type']}] {item['file'] or '-'}: relevance={item['relevance']:.3f}, tokens={item['tokens']}")

# Test 2: A2 agent
print()
print("=" * 60)
print("TEST 2: A2 agent (knowledge/docs)")
result2 = builder.build_context(target_agent="A2", req_id="req-002", max_tokens=1500)
for item in result2["head"]:
    print(f"    HEAD [{item['type']}] {item['file'] or '-'}: relevance={item['relevance']:.3f}, tokens={item['tokens']}")

# Test 3: A4 agent
print()
print("=" * 60)
print("TEST 3: A4 agent (prototype/spec/docs)")
result3 = builder.build_context(target_agent="A4", req_id="req-003", max_tokens=1500)
for item in result3["head"]:
    print(f"    HEAD [{item['type']}] {item['file'] or '-'}: relevance={item['relevance']:.3f}, tokens={item['tokens']}")

# Test 4: Sanitizer flow
print()
print("=" * 60)
print("TEST 4: Sanitizer flow (3 consecutive failures -> flush)")
builder2 = ContextBuilder(db_config=db_config)
for i in range(3):
    r = builder2.build_context(target_agent="A9", req_id="req-fail", max_tokens=1)
sanitize_events = [e for e in r["pipeline_events"] if e.get("stage") == "sanitize"]
print(f"  Sanitize events: {sanitize_events}")
print(f"  contaminated: {r['contaminated']}")

# Test 5: Compression
print()
print("=" * 60)
print("TEST 5: Compression check")
result5 = builder.build_context(target_agent="A9", req_id="req-005", max_tokens=3000)
all_items = result5["head"] + result5["mid"] + result5["tail"] + result5["discarded"]
compressed = [it for it in result5["head"] + result5["mid"] + result5["tail"] if it["compressed"]]
print(f"  Total items: {len(all_items)}")
print(f"  Compressed items: {len(compressed)}")
print(f"  Fill rate: {result5['fill_rate']}")

builder.close()
print()
print("=== All integration tests passed ===")
