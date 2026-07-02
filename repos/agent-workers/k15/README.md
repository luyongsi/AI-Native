# K15 Change Propagation Analysis

K15 provides Neo4j-based change impact analysis for the AI-Native development system.

## Overview

When code changes are made, K15 analyzes the dependency graph to determine:
- Which components are affected by the change
- The propagation paths of the impact
- Risk level based on affected node count
- Recommendations for testing and deployment

## Architecture

### Core Components

1. **change_propagation.py** (22K) - Main impact analyzer
   - `analyze_impact()`: Single entity impact analysis
   - `analyze_batch_impact()`: Multiple entities (parallel)
   - `trace_propagation_paths()`: Forward/reverse dependency paths
   
2. **dependency_traverser.py** (7.4K) - Graph traversal logic
   - BFS/DFS traversal of Neo4j dependency graph
   - Cycle detection
   - Path finding with max depth limits

3. **impact_rater.py** (8K) - Risk scoring
   - Calculate risk level (LOW/MEDIUM/HIGH/CRITICAL)
   - Based on affected node count and types
   - Component criticality assessment

4. **event_debouncer.py** (9.8K) - Event batching
   - Debounce rapid change events
   - Batch processing for performance
   - Configurable time windows

## Usage

### Basic Impact Analysis

```python
from k15.change_propagation import ChangePropagation

# Initialize
k15 = ChangePropagation(
    uri="neo4j://172.27.78.109:7687",
    user="neo4j",
    password="password123"
)

# Analyze single file change
result = await k15.analyze_impact(
    changed_entity="src/users/user_service.py",
    max_depth=3
)

print(f"Risk Level: {result['risk_level']}")
print(f"Affected Nodes: {len(result['affected_nodes'])}")
print(f"Recommendations: {result['recommendations']}")
```

### Batch Analysis

```python
# Multiple files changed
changes = [
    "src/auth/jwt.py",
    "src/models/user.py",
    "src/api/auth_routes.py"
]

batch_result = await k15.analyze_batch_impact(changes, max_depth=2)
print(f"Total affected: {batch_result['total_affected']}")
print(f"Max risk: {batch_result['max_risk_level']}")
```

### Propagation Paths

```python
# Trace how changes propagate
paths = await k15.trace_propagation_paths(
    changed_entity="database/users_table",
    max_depth=4
)

print("Forward dependencies:")
for path in paths['forward_paths']:
    print(f"  {' -> '.join(path)}")

print("Reverse dependencies:")
for path in paths['reverse_paths']:
    print(f"  {' -> '.join(path)}")
```

## Risk Levels

| Level | Affected Nodes | Action |
|-------|---------------|--------|
| **LOW** | 0-5 | Standard deployment |
| **MEDIUM** | 6-15 | Enhanced testing |
| **HIGH** | 16-30 | Full regression suite |
| **CRITICAL** | 30+ | Gradual rollout + monitoring |

## Integration

### A12 Impact Analyzer

K15 is integrated into A12 for automatic impact analysis on code changes:

```python
from k15.change_propagation import ChangePropagation

class A12ImpactAnalyzer(BaseAgentWorker):
    async def execute(self, req_id: str, context: dict):
        changed_files = context.get('changed_files', [])
        
        # K15 change propagation
        impact = await self.k15.analyze_batch_impact(changed_files)
        
        # Publish event
        await self.publish_event('impact.analyzed', {
            'req_id': req_id,
            'risk_level': impact['max_risk_level'],
            'affected_count': impact['total_affected']
        })
```

### API Endpoints

```
GET /api/topology/impact/{entity_name}
```

Returns impact analysis for a specific entity.

## Neo4j Schema Requirements

K15 requires the following Neo4j schema (initialized in Task #39):

**Node Types**:
- `Requirement`, `Service`, `Module`, `APIEndpoint`, `Database`, `Function`

**Relationships**:
- `DEFINES`, `CREATES`, `DEPENDS_ON` (with optional metadata)

**Constraints**:
- Unique: `req_id`, `service_name`, `module_path`, `api_endpoint`

**Indexes**:
- `created_at`, `service_type`, `module_lang`

## Configuration

```python
# Default settings
MAX_DEPTH = 3           # Maximum traversal depth
TIMEOUT = 30            # Query timeout (seconds)
BATCH_SIZE = 100        # Batch processing size
DEBOUNCE_WINDOW = 5     # Event debouncing (seconds)
```

## Metrics

K15 exposes Prometheus metrics:

- `k15_impact_analyses_total`: Counter of analyses performed
- `k15_affected_nodes_count`: Histogram of affected node counts
- `k15_analysis_duration_seconds`: Analysis execution time
- `k15_risk_level`: Gauge of current risk levels by entity

## Performance

- **Single analysis**: ~50-200ms (depends on graph size)
- **Batch analysis**: Parallel execution, ~100-500ms for 10 entities
- **Path tracing**: ~100-300ms for depth=4

## Error Handling

- **Entity not found**: Returns empty impact (0 affected nodes)
- **Neo4j unavailable**: Graceful degradation, logs warning
- **Timeout**: Returns partial results with warning
- **Cycle detection**: Prevents infinite loops in graph traversal

## Status

✅ **Production Ready**
- Implemented in Task #39
- Fully integrated with Neo4j
- Comprehensive error handling
- Performance optimized
- Documentation complete

## Related

- **K14**: Dependency topology building (upstream)
- **A12**: Impact analyzer integration (consumer)
- **Task #39**: Neo4j knowledge graph implementation
