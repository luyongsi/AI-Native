#!/usr/bin/env python3
"""LLM Audit Viewer — browse full prompt/response for a workflow.

Usage:
  python view_llm_calls.py <req_id>              # list all calls
  python view_llm_calls.py <req_id> --agent A4   # filter by agent
  python view_llm_calls.py <req_id> --full       # show full prompt+response

Reads from /opt/ai-native/logs/llm_calls/<req_id[:8]>/*.json
"""
import json, os, sys

LLM_CALLS_DIR = "/opt/ai-native/logs/llm_calls"


def print_sep(char="=", width=100):
    print(char * width)


def show_call(filepath, full=False):
    with open(filepath, encoding="utf-8") as f:
        d = json.load(f)

    print_sep()
    print(f"Agent: {d['agent_id']}  |  Task: {d['task_type']}  |  Status: {d['status']}")
    print(f"Tokens: prompt={d['tokens']['prompt']} completion={d['tokens']['completion']} total={d['tokens']['total']}")
    print(f"Duration: {d['duration_ms']}ms  |  Timestamp: {d['timestamp']}")
    print_sep("-")

    prompt = d.get("prompt", "")
    resp = d.get("response", "")

    if full:
        print("[PROMPT]")
        print(prompt)
        print()
        print_sep("-")
        print("[RESPONSE]")
        print(resp)
        print()
    else:
        if isinstance(prompt, str):
            try:
                msgs = json.loads(prompt)
                if isinstance(msgs, list):
                    for m in msgs:
                        content = m.get("content", "")[:300]
                        print(f"[{m.get('role','?')}] ({len(m.get('content',''))} chars): {content}")
                elif isinstance(msgs, str):
                    print(f"[PROMPT] ({len(prompt)} chars):", prompt[:300])
            except:
                print(f"[PROMPT] ({len(prompt)} chars):", prompt[:300])
        print()
        print(f"[RESPONSE] ({len(resp)} chars):")
        print(resp[:500] if len(resp) > 500 else resp)
        if len(resp) > 500:
            print(f"... (truncated, total {len(resp)} chars, use --full to see all)")

    # Filesize hint
    fsize = os.path.getsize(filepath)
    print(f"\nFile: {filepath} ({fsize:,} bytes)")


def main():
    req_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not req_id:
        # List all available req dirs
        dirs = sorted(os.listdir(LLM_CALLS_DIR)) if os.path.isdir(LLM_CALLS_DIR) else []
        for d in dirs:
            path = os.path.join(LLM_CALLS_DIR, d)
            if os.path.isdir(path):
                files = os.listdir(path)
                print(f"  {d}/ — {len(files)} calls")
        return

    req_short = req_id[:8]
    req_dir = os.path.join(LLM_CALLS_DIR, req_short)
    if not os.path.isdir(req_dir):
        # Try full req_id
        req_dir = os.path.join(LLM_CALLS_DIR, req_id)
    if not os.path.isdir(req_dir):
        print(f"No calls found for {req_id} (tried {req_short} and {req_id})")
        print(f"Available dirs: {os.listdir(LLM_CALLS_DIR) if os.path.isdir(LLM_CALLS_DIR) else 'none'}")
        sys.exit(1)

    full = "--full" in sys.argv
    agent_filter = None
    if "--agent" in sys.argv:
        idx = sys.argv.index("--agent")
        if idx + 1 < len(sys.argv):
            agent_filter = sys.argv[idx + 1]

    files = sorted(os.listdir(req_dir))
    for fname in files:
        if fname.endswith(".json"):
            fpath = os.path.join(req_dir, fname)
            if agent_filter:
                with open(fpath, encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("agent_id") != agent_filter:
                    continue
            show_call(fpath, full=full)
            print()


if __name__ == "__main__":
    main()
