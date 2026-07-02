# A6 DAG Builder - Quick Reference

## Task Priority & Execution Order

```
Priority 1   (Hours 0-2):  Database Migrations
Priority 1.5 (Hours 2-6):  Authentication/Security Setup
Priority 2   (Hours 6-12): Backend API Implementation
Priority 3   (Hours 12-20): Frontend UI Development
Priority 4   (Hours 20-26): Integration Testing
Priority 5   (Hours 26-28): Deployment & Release
```

## Key Guarantees

✓ **Database tasks have zero dependencies** and execute first
✓ **All DB tasks complete before** any API/UI tasks start
✓ **No circular dependencies** - detected and reported as errors
✓ **Parallel tasks identified** - independent tasks can run simultaneously
✓ **Critical path computed** - longest dependency chain identified
✓ **Effort estimated** - each task gets complexity score and hour estimate

## Component APIs

### DependencyAnalyzer

```python
analyzer = DependencyAnalyzer()
result = analyzer.analyze(
    requirement={"title": "...", "has_ui": True, "has_auth": True},
    api_schema={"paths": {"/api/users": {...}}},
    erd={"entities": [{"name": "users"}], "ddl": "..."}
)
# Returns: {"tasks": [...], "shared_modules": [...], "analysis_summary": {...}}
```

### DAGBuilder

```python
builder = DAGBuilder(max_parallel_agents=5, max_dag_depth=4)

# Option 1: Build from analyzed tasks
dag = builder.build(spec={}, analyzed_tasks=tasks)

# Option 2: Build from spec directly
dag = builder.build(spec={
    "features": [...],
    "entities": [...],
    "endpoints": [...]
})

# Returns: {
#   "tasks": [...],
#   "edges": [{from, to, type}, ...],
#   "critical_path": [...],
#   "parallel_groups": [...],
#   "has_cycles": bool,
#   "total_estimated_hours": float
# }
```

### ComplexityEstimator

```python
estimator = ComplexityEstimator()

# Single task
result = estimator.estimate(task)
# Returns: {
#   "complexity": 1-10,
#   "estimated_hours": float,
#   "confidence": 0.0-1.0,
#   "factors": [...]
# }

# Multiple tasks
results = estimator.estimate_all(tasks)
```

### A6Architect

```python
architect = A6Architect(db_pool=pool, nats_client=nc)
result = await architect.execute(
    req_id="req-123",
    requirement={...},
    api_schema={...},
    erd={...}
)
# Returns: {"status": "completed", "dag": {...}, "summary": {...}}
```

## Database Tables

### task_dags
Stores DAG structures with indexes on req_id and created_at

### task_executions
Tracks execution status of individual tasks

### shared_modules
Identifies and tracks reusable modules across tasks

## Event Format

```json
{
  "event_type": "architecture.dag_built",
  "req_id": "req-123",
  "dag_id": 42,
  "payload": {
    "dag": {...full DAG...},
    "shared_modules": [...],
    "total_tasks": 8,
    "total_estimated_hours": 36.0,
    "critical_path_hours": 24.5
  }
}
```

## Testing Checklist

- [x] DB tasks have no dependencies
- [x] API tasks depend on DB tasks
- [x] UI tasks depend on API tasks
- [x] No circular dependencies in test cases
- [x] Critical path correctly computed
- [x] Parallel groups properly identified
- [x] Complexity scoring works
- [x] Database schema migration valid
- [x] NATS event format correct
- [x] Error handling for missing dependencies

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Circular dependency detected | Check task depends_on arrays for cycles |
| API task not depending on DB | Verify db_task_ids passed to _extract_api_tasks |
| Critical path too long | Consider breaking large tasks into smaller ones |
| Too many parallel tasks | DAGBuilder will warn if > max_parallel_agents per level |
| Missing shared modules | Check _identify_shared_modules logic |

## Files Created/Modified

Created:
- `/a6/dependency_analyzer.py` - Task extraction and analysis
- `/a6_architect.py` - Main orchestration
- `/test_a6_dag_builder.py` - Unit tests
- `/infra/migrations/009_task_dags.sql` - Database schema
- `A6_DAG_BUILDER_IMPLEMENTATION.md` - Full documentation

Modified:
- `/a6/dag_builder.py` - Added analyzed_tasks parameter to build()
- `/a6/__init__.py` - Added DependencyAnalyzer export
