# A9 Dev Agent — Dual-Brain Architecture Implementation

## Overview

A9 is a dual-brain code generation system with strict separation of concerns:

- **Coder Brain**: Generates code changes (uses Claude Code CLI / LLM)
- **Auditor Brain**: Reviews code independently (never sees Coder's reasoning)
- **Orchestrator**: Manages 3-iteration feedback loop until approval or escalation

The dual-brain architecture ensures code quality through adversarial review while maintaining isolation between generation and validation logic.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              A9 Dev Agent (Orchestrator)            │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Task Spec + Context Package                        │
│          │                                          │
│          ▼                                          │
│  ┌──────────────────┐    Iteration Loop (Max 3)    │
│  │  Coder Module    │    ┌────────────────┐        │
│  ├──────────────────┤    │ If Rejected:   │        │
│  │ • Worktree       │◄───┤ • Add Feedback │        │
│  │ • LLM Call       │    │ • Retry        │        │
│  │ • Code Gen       │    └────────────────┘        │
│  │ • Self Inspect   │                              │
│  │  (INTERNAL)      │                              │
│  └────────┬─────────┘                              │
│           │                                        │
│           │ Diff (ONLY)                            │
│           │ ┌──────────────────┐                   │
│           └─►  Auditor Module  │                   │
│             ├──────────────────┤                   │
│             │ • Static Analysis│                   │
│             │ • Code Review    │                   │
│             │ • Decision       │                   │
│             │ (Independent)    │                   │
│             └────────┬─────────┘                   │
│                      │                             │
│                      ▼                             │
│             approved / rejected                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## Module Structure

### 1. `a9/coder.py` — Code Generation Brain

Extends `a9_claude_code_bridge.py` with:

**Key Features:**
- Worktree isolation (git worktree via subprocess)
- LLM-based code generation (DeepSeek/Anthropic)
- Mock fallback for testing
- Self-inspection (internal reasoning, NOT sent to Auditor)

**Interface:**
```python
coder = CoderModule(enable_llm=True)
result = await coder.generate(task_spec, context_package)

# Returns:
{
    "status": "success|failed",
    "diff": {
        "files_changed": [...],
        "changes_summary": str,
        "commit_sha": str,
        "session_id": str,
        "created_at": str,
        "cost_usd": float,
        "mock": bool
    },
    "self_inspection": {  # INTERNAL, NOT sent to Auditor
        "reasoning": str,
        "confidence": float,
        "issues_identified": [...]
    },
    "metadata": {
        "files_created": int,
        "files_modified": int,
        "total_lines_added": int,
        "total_lines_removed": int,
        "worktree_path": str
    }
}
```

### 2. `a9/auditor.py` — Code Review Brain

Independent code quality validator that:

**Key Features:**
- Receives ONLY the diff (never sees Coder's reasoning)
- Static analysis via pylint/eslint
- Basic code quality checks
- Approval/rejection decision with confidence score

**Interface:**
```python
auditor = AuditorModule(enable_analysis=True)
# Auditor sees ONLY this:
diff = {
    "files_changed": [
        {
            "path": "src/routes/users.py",
            "change_type": "created",
            "lines_added": 50,
            "lines_removed": 0,
            "patch_preview": "...",
            "language": "python"
        }
    ],
    "changes_summary": "User API endpoint"
}

result = await auditor.review(diff)

# Returns:
{
    "decision": "approved|rejected",
    "issues": [{"severity": "error|warning", "message": str}],
    "suggestions": [str],
    "confidence": float,
    "analysis_detail": {
        "files_analyzed": int,
        "errors_found": int,
        "warnings_found": int
    }
}
```

### 3. `a9/a9_dev_agent.py` — Orchestrator

Main agent that coordinates Coder ↔ Auditor interaction:

**Execution Flow:**
1. **Iteration 1-3:**
   - Coder generates code → diff + self_inspection
   - Extract ONLY diff (hide self_inspection)
   - Auditor reviews diff
   - If approved: return result
   - If rejected: add feedback to task spec, loop to next iteration
2. **After 3 iterations:**
   - If not approved: escalate for human review

**Metrics:**
- Track iterations, approval rate, cycle time
- Collect Coder and Auditor confidence scores
- Record issues found per iteration

### 4. `a9/static_analyzer.py` — Static Analysis Utilities

Provides subprocess-based wrappers for:
- `pylint` for Python code
- `eslint` for JavaScript/TypeScript

### 5. `a9/metrics.py` — Prometheus Observability

Tracks:
- `a9_coder_iterations_total`: Iterations by status
- `a9_auditor_reviews_total`: Reviews by decision
- `a9_approval_rate`: Overall approval rate
- `a9_cycle_time_seconds`: Total cycle duration
- `a9_escalations_total`: Escalation count

### 6. `a9/workflow.py` — Temporal Orchestration

Defines Temporal workflow with:
- `coder_activity`: Wraps Coder module
- `auditor_activity`: Wraps Auditor module
- `a9_dual_brain_workflow`: Main workflow orchestration
- Mock fallback for testing without Temporal

## Key Design Decisions

### 1. Strict Information Separation

**Coder sees:**
- Task specification
- Previous feedback (if iteration > 1)
- Context package (OpenAPI, ERD)

**Coder produces (but NOT sent to Auditor):**
- `self_inspection`: Internal reasoning, confidence, identified issues
- `metadata`: File stats, worktree info

**Auditor sees (ONLY):**
- `files_changed`: List of files with path, type, language
- `changes_summary`: Brief description
- `patch_preview`: Code snippet preview

**Auditor NEVER sees:**
- Coder's confidence score
- Coder's internal reasoning
- Coder's identified issues
- Metadata about generation

### 2. Worktree Isolation

Coder uses git worktree for isolated code generation:
```bash
git worktree add /tmp/a9-worktrees/wt-{session_id}
```

Fallback to temp directory if worktree fails.

### 3. Iterative Feedback Loop

- Max 3 iterations to reach approval
- Feedback from Auditor → Coder (via `task_spec`)
- If rejected 3 times → escalate to human

### 4. Metrics Collection

`A9MetricsCollector` tracks:
- Per-iteration metrics (files changed, issues found, times)
- Aggregate metrics (approval rate, cycle time, confidence)
- Escalation rate for monitoring

## Usage

### Basic Usage (Mock Mode)

```python
from a9.a9_dev_agent import A9DevAgent

agent = A9DevAgent(enable_llm=False)  # Mock mode

context_package = {
    "spec_package": {
        "openapi": {
            "info": {"title": "User API"},
            "paths": {"/users": {}, "/users/{id}": {}}
        },
        "erd": {
            "tables": [{"name": "users"}, {"name": "roles"}]
        }
    },
    "task": {
        "type": "backend",
        "title": "Create User API",
        "description": "REST API for user management"
    }
}

# Run (need to mock NATS)
agent.nc = MockNATS()
result = await agent.execute("req-001", context_package)
```

### With Temporal Workflow

```python
from a9.workflow import a9_dual_brain_workflow

# Temporal client
client = await Client.connect("localhost:7233")

# Execute workflow
result = await client.execute_workflow(
    a9_dual_brain_workflow,
    "req-001",
    spec_package={...},
    task={...},
    id="workflow-001"
)
```

### With Metrics

```python
from a9.metrics import A9MetricsCollector

collector = A9MetricsCollector()
collector.start_cycle()

# Run iterations...
for iter in range(1, 4):
    # ... coder and auditor execution
    collector.record_iteration(
        iteration_num=iter,
        coder_result=coder_result,
        auditor_result=auditor_result,
        coder_duration=2.5,
        auditor_duration=1.2
    )

collector.finalize_cycle(final_status="approved")
```

## Testing

Run integration tests:

```bash
pytest test_a9_dual_brain.py -v
```

Test Coverage:
- ✅ Coder code generation in isolation
- ✅ Auditor review (independent, sees only diff)
- ✅ Information separation verification
- ✅ Full dual-brain cycle (approved in iteration 1)
- ✅ Max iterations enforcement
- ✅ Metrics collection
- ✅ Static analysis (Python, JavaScript)

## Verification Checklist

- [x] Based on existing code (`a9_claude_code_bridge.py` extended)
- [x] Coder generates code changes (LLM or mock)
- [x] Auditor runs independently (sees ONLY diff, not reasoning)
- [x] Dual-brain iteration max 3 times
- [x] Prometheus metrics implemented
- [x] Strict separation of concerns enforced
- [x] Temporal workflow orchestration provided
- [x] Integration tests included
- [x] Mock mode for offline testing
- [x] Worktree isolation for Coder

## Environment Variables

```bash
# For LLM-based code generation
export DEEPSEEK_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"

# For static analysis
export PATH="/usr/local/bin:/usr/bin:$PATH"  # pylint, eslint
```

## Dependencies

**Required:**
- Python 3.8+
- nats-py (for NATS messaging)
- pydantic (for data validation)

**Optional:**
- temporalio (for Temporal workflow)
- prometheus-client (for metrics)
- httpx (for LLM API calls)
- pylint, eslint (for static analysis)

## Future Enhancements

1. **Advanced Static Analysis**
   - SonarQube integration
   - Security scanning (bandit, safety)
   - Performance profiling

2. **Smarter Feedback Loop**
   - LLM-based feedback synthesis
   - Differential problem analysis
   - Auto-priority detection

3. **Extended Metrics**
   - Code complexity metrics
   - Test coverage tracking
   - Performance metrics (generation time, approval time)

4. **Caching**
   - Cache similar code patterns
   - Reuse previous solutions
   - Feedback history for learning

## References

- Base: `/opt/ai-native/repos/agent-workers/a9_claude_code_bridge.py` (7.1K)
- Base: `/opt/ai-native/repos/agent-workers/a9_dev_agent_stub.py` (6.2K)
- Related: `base_worker.py`, `a1_requirement_intake.py`, `a4_spec_writer.py`

---

**Status:** ✅ Implementation Complete
**Last Updated:** 2026-07-02
