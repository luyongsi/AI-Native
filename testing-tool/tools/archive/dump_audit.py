import json, os, sys

target_req = '39e8b5cc-57aa-491c-ada2-7dbc2161b354'

# ── 1. LLM Audit — FULL prompt + response dump ──────────────────────
print("█" * 100)
print("█ 1. LLM AUDIT LOG (every prompt + every response)")
print("█" * 100)

with open('/opt/ai-native/logs/llm_audit.jsonl', 'r', encoding='utf-8') as f:
    lines = f.readlines()

entries = []
for line in lines:
    try:
        e = json.loads(line.strip())
        if e.get('req_id', '') == target_req:
            entries.append(e)
    except:
        pass

print(f"\nTotal audit lines in file: {len(lines)}")
print(f"Matching entries for this workflow: {len(entries)}")
print()

for i, e in enumerate(entries):
    print("=" * 100)
    print(f"LLM CALL #{i+1}  |  Agent: {e.get('agent_id','?')}  |  Task: {e.get('task_type','?')}")
    print(f"Model: {e.get('model','?')}  |  Status: {e.get('status','?')}")
    print(f"Tokens: prompt={e.get('prompt_tokens','?')} completion={e.get('completion_tokens','?')} total={e.get('total_tokens','?')}")
    print(f"Duration: {e.get('duration_ms','?')}ms  |  Error: {e.get('error','N/A')}")
    print("-" * 100)

    # Check where the prompt is stored — various field names
    prompt_field = None
    for key in ['messages', 'prompt', 'input', 'request_body']:
        if key in e and e[key]:
            prompt_field = key
            break

    if not prompt_field:
        # Dump ALL keys so we can see structure
        print("  RAW ENTRY KEYS: " + str(list(e.keys())))
        for k, v in e.items():
            if isinstance(v, str):
                print(f"  [{k}] ({len(v)} chars): {v[:500]}")
        print()
        continue

    raw = e[prompt_field]
    if isinstance(raw, str):
        # String prompt
        print(f"  PROMPT ({len(raw)} chars):")
        print(raw)
        print()

    elif isinstance(raw, list):
        # Chat messages
        print(f"  PROMPT ({len(raw)} messages, ~{sum(len(m.get('content','') or '') for m in raw)} chars):")
        for j, msg in enumerate(raw):
            role = msg.get('role', '?')
            content = msg.get('content', '') or ''
            print(f"  [{j}] {role} ({len(content)} chars):")
            print(content)
            print()
    else:
        print(f"  PROMPT (type={type(raw).__name__}): {str(raw)[:2000]}")
        print()

    # Response
    resp = e.get('response', e.get('completion', e.get('content', e.get('output', ''))))
    if isinstance(resp, str) and resp:
        print(f"  RESPONSE ({len(resp)} chars):")
        print(resp)
        print()
    elif isinstance(resp, dict):
        print(f"  RESPONSE (dict, {len(json.dumps(resp, ensure_ascii=False))} chars):")
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        print()
    else:
        print(f"  RESPONSE: EMPTY or unreadable format")
        print()

print()
print("█" * 100)
print("█ 2. ORCHESTRATOR LOGS (full trace)")
print("█" * 100)
print()

os.system(f"strings /var/log/orchestrator-worker.log | grep '{target_req}'")

print()
print("█" * 100)
print("█ 3. AGENT WORKER LOGS (full trace)")
print("█" * 100)
print()

os.system(f"strings /var/log/agent-workers.log | grep '{target_req}'")
