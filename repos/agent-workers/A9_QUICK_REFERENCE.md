# A9 Dual-Brain - Quick Reference Card

## TL;DR

**What:** Dual-brain code generation system (Coder ↔ Auditor)  
**Where:** `/d/Vibe Coding/AI Agent/repos/agent-workers/a9/`  
**Lines:** 2,377 (code + tests)  
**Status:** ✅ COMPLETE

---

## One-Minute Overview

```
CODER (Private)              AUDITOR (Independent)
┌──────────────────┐        ┌──────────────────┐
│ • Generates code │────→   │ • Reviews ONLY   │
│ • Self-inspect   │ diff   │   diff (not code │
│ • Metadata       │        │   reasoning)     │
│                  │        │ • Static analysis│
└──────────────────┘        │ • Approves/      │
       ↑                    │   Rejects        │
       │                    └────────┬─────────┘
       └─ Feedback ◄────────────────┘
             (max 3 iterations)
```

---

## Core Classes

| Class | File | Purpose |
|-------|------|---------|
| `CoderModule` | `coder.py` | Code generation (worktree isolated) |
| `AuditorModule` | `auditor.py` | Code review (independent) |
| `A9DevAgent` | `a9_dev_agent.py` | Main orchestrator |
| `A9Metrics` | `metrics.py` | Prometheus observability |
| `StaticAnalyzer` | `static_analyzer.py` | pylint/eslint wrapper |

---

## Key Methods

### Coder
```python
coder = CoderModule(enable_llm=True)
result = await coder.generate(task_spec, context)
# Returns: status, diff, self_inspection (hidden), metadata
```

### Auditor
```python
auditor = AuditorModule(enable_analysis=True)
# See ONLY diff (not Coder reasoning)
result = await auditor.review({"files_changed": [...], "changes_summary": ""})
# Returns: decision, issues, suggestions, confidence
```

### Orchestrator
```python
agent = A9DevAgent(enable_llm=False)
agent.nc = MockNATS()  # or real NATS
result = await agent.execute("req-001", context_package)
# Returns: status (approved/escalated), diff, iterations, audit_history, metrics
```

---

## Critical Architecture: Information Separation

### ✅ What Auditor SEES
```python
diff_for_auditor = {
    "files_changed": [
        {"path": "src/app.py", "change_type": "created", "language": "python"}
    ],
    "changes_summary": "Main application module"
}
```

### ❌ What Auditor DOES NOT SEE
```python
# Coder's internal state (HIDDEN):
{
    "self_inspection": {"reasoning": "...", "confidence": 0.8},
    "metadata": {"worktree_path": "/tmp/..."},
    # ...any Coder reasoning...
}
```

**Enforcement:** `a9_dev_agent.py` lines 80-85
```python
diff_for_audit = {
    "files_changed": final_diff.get("files_changed", []),
    "changes_summary": final_diff.get("changes_summary", "")
}
# Explicitly exclude self_inspection and metadata
```

---

## Iteration Loop

```
Max 3 iterations:

Iter 1: Coder gen → Auditor review
        ├─ approved? → DONE
        └─ rejected? → add feedback → Iter 2

Iter 2: Coder gen (w/ feedback) → Auditor review
        ├─ approved? → DONE
        └─ rejected? → add feedback → Iter 3

Iter 3: Coder gen (w/ feedback) → Auditor review
        ├─ approved? → DONE
        └─ rejected? → ESCALATE (human review)
```

---

## File Checklist

### Core (a9/)
- [x] `__init__.py` - Package exports
- [x] `coder.py` (365 lines) - Code generation
- [x] `auditor.py` (315 lines) - Code review
- [x] `a9_dev_agent.py` (278 lines) - Orchestrator
- [x] `static_analyzer.py` (224 lines) - Pylint/eslint
- [x] `metrics.py` (274 lines) - Prometheus
- [x] `workflow.py` (247 lines) - Temporal

### Tests & Examples
- [x] `test_a9_dual_brain.py` (339 lines) - 13 tests
- [x] `a9_dual_brain_examples.py` (310 lines) - 4 examples

### Documentation
- [x] `A9_DUAL_BRAIN_README.md` - Full guide
- [x] `A9_IMPLEMENTATION_COMPLETE.md` - Report
- [x] `A9_FILE_INDEX.md` - Index
- [x] `A9_QUICK_REFERENCE.md` - This file

---

## Quick Start

### 1. Basic Usage (Mock Mode)
```python
from a9.a9_dev_agent import A9DevAgent

agent = A9DevAgent(enable_llm=False)  # Mock
agent.nc = MockNATS()  # Mock NATS

result = await agent.execute("req-001", {
    "spec_package": {"openapi": {...}, "erd": {...}},
    "task": {"type": "backend", "title": "..."}
})

print(result["status"])  # approved/escalated
print(result["iterations"])  # 1-3
```

### 2. With Metrics
```python
from a9.metrics import A9MetricsCollector

collector = A9MetricsCollector()
collector.start_cycle()
# ... execute ...
collector.finalize_cycle(result["status"])
```

### 3. Temporal Workflow
```python
from a9.workflow import a9_dual_brain_workflow
from temporalio.client import Client

client = await Client.connect("localhost:7233")
result = await client.execute_workflow(a9_dual_brain_workflow, ...)
```

### 4. Run Examples
```bash
python a9_dual_brain_examples.py
```

### 5. Run Tests
```bash
pytest test_a9_dual_brain.py -v
```

---

## Metrics

### Prometheus Counters
- `a9_coder_iterations_total` - Coder iterations by status
- `a9_auditor_reviews_total` - Reviews by decision
- `a9_escalations_total` - Escalations

### Gauges
- `a9_approval_rate` - (0-1)
- `a9_coder_confidence` - (0-1)
- `a9_auditor_confidence` - (0-1)

### Histograms
- `a9_coder_generation_seconds` - Generation time
- `a9_auditor_review_seconds` - Review time
- `a9_cycle_time_seconds` - Total cycle time

---

## Environment Setup

```bash
# Install core
pip install nats-py pydantic

# Optional: Full features
pip install temporalio prometheus-client httpx pytest-asyncio

# Optional: Static analysis
pip install pylint
npm install -g eslint

# Optional: API keys for LLM
export DEEPSEEK_API_KEY="..."
export ANTHROPIC_API_KEY="..."
```

---

## Verification Checklist

| ✅ | Requirement |
|---|---|
| ✅ | Based on existing code (extended a9_claude_code_bridge.py) |
| ✅ | Coder generates code (LLM + mock mode) |
| ✅ | Auditor independent (strict separation) |
| ✅ | Max 3 iterations |
| ✅ | Prometheus metrics |
| ✅ | Worktree isolation |
| ✅ | Integration tests (13 tests) |
| ✅ | Temporal workflow |
| ✅ | Mock mode for offline testing |
| ✅ | Documentation complete |

---

## Separation Verification Test

```python
# Prove Auditor doesn't see Coder reasoning:
from a9.coder import CoderModule
from a9.auditor import AuditorModule

coder = CoderModule(enable_llm=False)
coder_result = await coder.generate(task_spec, {})

# What Auditor sees (ONLY):
diff = {
    "files_changed": coder_result["diff"]["files_changed"],
    "changes_summary": coder_result["diff"]["changes_summary"]
}

# Verify Auditor input doesn't have:
assert "self_inspection" not in diff  # ✓
assert "metadata" not in diff  # ✓
assert "reasoning" not in str(diff)  # ✓

auditor = AuditorModule()
result = await auditor.review(diff)  # Auditor sees ONLY diff
```

---

## Common Patterns

### Pattern 1: Generate and Review
```python
coder = CoderModule()
auditor = AuditorModule()

# Generate
coder_result = await coder.generate(task_spec, context)

# Review (separation enforced)
diff = {"files_changed": ..., "changes_summary": ...}
audit_result = await auditor.review(diff)
```

### Pattern 2: Full Cycle with Feedback
```python
agent = A9DevAgent()
for iteration in range(1, 4):
    result = await agent.execute("req", context)
    if result["status"] == "approved":
        break
```

### Pattern 3: With Metrics
```python
collector = A9MetricsCollector()
collector.start_cycle()
# ... do work ...
collector.record_iteration(iter, coder_result, audit_result, 2.5, 1.2)
collector.finalize_cycle("approved")
```

---

## Debug Tips

### Issue: "Auditor sees Coder reasoning"
**Fix:** Check `a9_dev_agent.py` lines 80-85 (diff extraction)
```python
# Must exclude self_inspection and metadata
diff_for_audit = {
    "files_changed": final_diff.get("files_changed", []),
    "changes_summary": final_diff.get("changes_summary", "")
}
```

### Issue: "Iteration doesn't loop"
**Fix:** Check `max_iterations = 3` and feedback loop in `a9_dev_agent.py`

### Issue: "Metrics not recorded"
**Fix:** Call `collector.record_iteration()` after each iteration

### Issue: "Worktree not created"
**Fix:** Check git installed and `/tmp/a9-worktrees` writable

---

## File References

**Read First:** `A9_DUAL_BRAIN_README.md`  
**Implementation:** `a9/` (7 Python modules)  
**Tests:** `test_a9_dual_brain.py` (13 tests)  
**Examples:** `a9_dual_brain_examples.py` (4 examples)  
**Index:** `A9_FILE_INDEX.md` (detailed breakdown)

---

## Contact & Support

- **Architecture:** See `A9_DUAL_BRAIN_README.md` → Design Decisions
- **API:** See module docstrings in `a9/` files
- **Tests:** Run `pytest test_a9_dual_brain.py -v`
- **Examples:** Run `python a9_dual_brain_examples.py`

---

**Status:** ✅ Complete  
**Date:** 2026-07-02  
**Lines:** 2,377  
**Tests:** 13  
**Examples:** 4
