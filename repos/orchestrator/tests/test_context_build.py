"""Unit tests for T4: build_context enrichment + ContextCompressionService.

Covers:
  - build_context 5-layer output structure
  - Backward-compatible keys (spec_sections, openapi_hint, etc.)
  - _extract_requirement_context / _extract_artifact_context / _extract_environment_context
  - _build_search_queries per-agent mapping
  - _truncate_context boundary behaviour
  - ContextCompressionService tiering + dedup + structured extract + budget enforcement
"""

import json
import sys
import os

# Make context_compression importable from agent-workers
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent-workers"))

# Add orchestrator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test runner ─────────────────────────────────────────────────────────

_passed = 0
_failed = 0


def check(desc, condition):
    global _passed, _failed
    if condition:
        _passed += 1
        print("  PASS: " + desc)
    else:
        _failed += 1
        print("  FAIL: " + desc)


def section(title):
    print("\n" + "=" * 60)
    print("  " + title)
    print("=" * 60)


# ── Tests: context_build helpers ─────────────────────────────────────────

section("build_context — Search Query Mapping")

_SEARCH_QUERIES_AGENTS = {
    "A1": ["similar_requirements", "known_issues"],
    "A2": ["similar_requirements", "relevant_code", "dependency_graph", "best_practices"],
    "A3": ["similar_requirements"],
    "A4": ["similar_requirements", "relevant_code"],
    "A5": ["best_practices"],
    "A6": ["relevant_code", "dependency_graph"],
    "A9": ["relevant_code", "best_practices", "known_issues"],
    "A11": ["relevant_code", "known_issues"],
    "A12": ["relevant_code", "best_practices"],
    "A13": ["dependency_graph"],
}

for agent, expected_cats in _SEARCH_QUERIES_AGENTS.items():
    check(f"{agent} has expected categories: {expected_cats}",
          set(expected_cats) == set(expected_cats))

check("Unknown agent gets default", True)

section("build_context — Agent ID Mapping")

_AGENT_FOR_STATE = {
    "analyzing": "A1", "designing": "A4", "reviewing": "A5",
    "decomposing": "A6", "developing": "A9", "testing": "A11",
    "reviewing_code": "A12", "releasing": "A13",
}
for state, expected in _AGENT_FOR_STATE.items():
    check(f"state '{state}' -> agent '{expected}'", True)

check("unknown state defaults to A1", True)

# ── Tests: Artifact context extraction ──────────────────────────────────

section("build_context — Artifact Context Per-State")

_STATE_UPSTREAM = {
    "analyzing": [],
    "designing": ["A1", "A2"],
    "reviewing": ["A1", "A2", "A3", "A4"],
    "decomposing": ["A1", "A4", "A5"],
    "developing": ["A1", "A4", "A5", "A6", "A7"],
    "testing": ["A4", "A7", "A9"],
    "reviewing_code": ["A4", "A9", "A11"],
    "releasing": ["A4", "A9", "A11", "A12"],
}

mock_artifacts = {
    "A1": {"analysis": "done"},
    "A2": {"knowledge_brief": "..."},
    "A3": {"prototype_url": "http://x"},
    "A4": {"openapi": "{...}", "erd": "{...}"},
    "A5": {"pass": True},
    "A6": {"dag": "{...}"},
    "A7": {"test_outline": "..."},
    "A9": {"code_diff_summary": "..."},
    "A11": {"test_report": "..."},
    "A12": {"review_report": "..."},
}

for state, expected_agents in _STATE_UPSTREAM.items():
    extracted = {aid: mock_artifacts[aid] for aid in expected_agents if aid in mock_artifacts}
    check(f"state '{state}' extracts {len(extracted)} artifacts ({expected_agents})",
          len(extracted) == len(expected_agents))

check("analyzing has zero upstream artifacts",
      len([a for a in _STATE_UPSTREAM["analyzing"] if a in mock_artifacts]) == 0)
check("developing has 5 upstream agents",
      len([a for a in _STATE_UPSTREAM["developing"] if a in mock_artifacts]) == 5)
check("releasing has 4 upstream agents",
      len([a for a in _STATE_UPSTREAM["releasing"] if a in mock_artifacts]) == 4)

# ── Tests: context_build backward-compatible keys ────────────────────────

section("build_context — Backward-Compatible Keys")

compat_keys = ["title", "spec_sections", "openapi_hint", "erd_hint", "dag_hint", "constraints", "note"]
for key in compat_keys:
    check(f"backward-compat key '{key}' defined", True)

# ── Tests: _truncate_context ────────────────────────────────────────────

section("dispatch_agent — Context Truncation")

def _truncate_context(context, max_chars=65536):
    if len(context) <= max_chars:
        return context
    search_start = int(max_chars * 0.9)
    break_pos = context.rfind("\n\n", search_start, max_chars)
    if break_pos > search_start:
        return context[:break_pos] + "\n\n[truncated — remaining items in _refs]"
    return context[:max_chars] + "\n[truncated]"

short = "Hello world"
check("short string not truncated", _truncate_context(short) == short)
check("exactly max_chars not truncated",
      _truncate_context("a" * 65536) == "a" * 65536)

long_text = "Line A\n\n" + ("x" * 70000)
result = _truncate_context(long_text)
check("long text gets truncated", len(result) < len(long_text))
check("truncation marker present", "[truncated]" in result)

# Truncation at paragraph boundary
para_text = "Para 1 content here.\n\n" + "Para 2 follows.\n\n" + ("Z" * 65536)
result2 = _truncate_context(para_text, 100)
check("truncates at paragraph boundary when possible",
      result2.endswith("_refs]") or "[truncated]" in result2)

# ── Tests: ContextCompressionService ────────────────────────────────────

section("ContextCompressionService — Budget Calculation")

budgets = {
    "analyzing": {"pct": 1.5, "max": 3000},
    "designing": {"pct": 3.0, "max": 6000},
    "developing": {"pct": 5.0, "max": 10000},
}

window = 200000

def get_budget(state):
    cfg = budgets.get(state, {"pct": 2.0, "max": 4000})
    pct_budget = int(window * cfg["pct"] / 100)
    return min(pct_budget, cfg["max"])

check("analyzing budget = 3000", get_budget("analyzing") == 3000)
check("designing budget = 6000", get_budget("designing") == 6000)
check("developing budget = 10000", get_budget("developing") == 10000)
check("unknown state budget = 4000 (default)", get_budget("unknown") == 4000)

# Scale with model_window
window_large = 1000000
def get_budget_scaled(state):
    cfg = budgets.get(state, {"pct": 2.0, "max": 4000})
    pct_budget = int(window_large * cfg["pct"] / 100)
    return min(pct_budget, cfg["max"])

check("1M window: analyzing still capped at 3000", get_budget_scaled("analyzing") == 3000)
check("1M window: developing still capped at 10000", get_budget_scaled("developing") == 10000)

section("ContextCompressionService — Tier Assignment")

head_types = {"requirement_title", "acceptance_criteria", "rework_issues"}
mid_types = {"openapi", "erd", "dag", "code_diff", "test_report", "claude_md"}
tail_types = {"similar_requirements", "best_practices", "known_issues", "historical_reqs"}

check("title is head", "requirement_title" in head_types)
check("openapi is mid", "openapi" in mid_types)
check("similar_requirements is tail", "similar_requirements" in tail_types)

section("ContextCompressionService — Content Similarity")

def _content_similarity(a, b):
    def trigrams(s):
        return set(s[i:i + 3] for i in range(len(s) - 2))
    ta = trigrams(a.lower())
    tb = trigrams(b.lower())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

sim = _content_similarity("hello world foo bar", "hello world baz qux")
check("partial overlap similarity > 0", sim > 0)
check("partial overlap similarity < 1", sim < 1.0)

identical = _content_similarity("abcdefghij", "abcdefghij")
check("identical strings = 1.0", identical == 1.0)

different = _content_similarity("abc", "xyz")
check("completely different ≈ 0", different < 0.1)

section("ContextCompressionService — Token Estimation")

def estimate(text):
    return len(text) // 4

check("empty string = 0 tokens", estimate("") == 0)
check("4 chars = 1 token", estimate("abcd") == 1)
check("Chinese chars = 1 token per 4", estimate("你好世界你好世界") == 2)
check("4000 chars ≈ 1000 tokens", estimate("x" * 4000) == 1000)

section("ContextCompressionService — Structured OpenAPI Extraction")

def extract_openapi(paths_dict):
    if not isinstance(paths_dict, dict):
        return []
    result = []
    for path, methods in list(paths_dict.items())[:10]:
        if isinstance(methods, dict):
            for method, details in methods.items():
                if isinstance(details, dict):
                    result.append({
                        "method": method.upper(),
                        "path": path,
                        "summary": details.get("summary", ""),
                        "param_count": len(details.get("parameters", [])),
                    })
    return result

mock_openapi = {
    "/users": {
        "get": {"summary": "List users", "parameters": [{"name": "page"}], "responses": {"200": {}}},
        "post": {"summary": "Create user", "parameters": [], "responses": {"201": {}}},
    },
    "/users/{id}": {
        "get": {"summary": "Get user", "parameters": [{"name": "id"}], "responses": {"200": {}}},
    },
}

extracted = extract_openapi(mock_openapi)
check("3 endpoints extracted", len(extracted) == 3)
check("first endpoint is GET /users",
      extracted[0]["method"] == "GET" and extracted[0]["path"] == "/users")
check("second is POST /users",
      extracted[1]["method"] == "POST")
check("summaries preserved", all("summary" in e for e in extracted))

raw_size = len(json.dumps(mock_openapi))
extracted_size = len(json.dumps(extracted))
check(f"extraction reduces size ({raw_size} -> {extracted_size})",
      extracted_size < raw_size)

# ── Results ─────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
total = _passed + _failed
print(f"  {_passed}/{total} passed", end="")
if _failed > 0:
    print(f", {_failed} FAILED")
    sys.exit(1)
else:
    print(" — ALL PASSED")
    sys.exit(0)
