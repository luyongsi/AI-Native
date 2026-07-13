# Phase 6 End-to-End Integration Tests

This directory contains comprehensive end-to-end (E2E) integration tests for the AI-native platform's complete pipeline, from requirement intake through GitHub PR generation.

## Overview

The Phase 6 E2E test suite validates the entire system flow across three scenarios of increasing complexity:

### Scenario 1: Simple Requirement (< 2h)
**Add email_verified field to users table**

- Database migration: Add BOOLEAN field with default false
- API interface: PATCH /api/users/:id/verify-email
- Unit tests: Field defaults and update logic
- **Acceptance Criteria**: Complete within 2 hours, code quality >= 4/5, test pass rate >= 80%

### Scenario 2: Medium Requirement (< 8h)
**Implement user login functionality**

- API schema: POST /auth/login (username, password)
- ERD: Sessions table design with proper relationships
- Backend: JWT token generation and validation
- Frontend: Login form + secure token storage
- Testing: Unit + integration tests
- **Acceptance Criteria**: Complete within 8 hours, code quality >= 4/5, test coverage >= 70%

### Scenario 3: Complex Requirement (Reference Benchmark)
**Multi-tenant RBAC permission system**

- Database: tenants, roles, permissions, user_roles tables
- API: RBAC permission check middleware
- Backend: Permission management CRUD + permission tree
- Testing: Boundary tests + performance tests
- **Acceptance Criteria**: Process completeness, all events fire correctly

## Architecture

### Components

1. **E2ETestFramework** (`e2e_test_framework.py`)
   - Manages NATS, PostgreSQL, and Redis connections
   - Submits requirements and polls for completion
   - Tracks requirement status and outputs
   - Handles test data cleanup

2. **EventTracker** (`event_tracker.py`)
   - Subscribes to all NATS event subjects
   - Captures and indexes events by requirement ID
   - Verifies event sequences and timing
   - Generates event statistics

3. **QualityValidator** (`quality_validator.py`)
   - Validates API schemas (OpenAPI 3.x compliance)
   - Checks ERD structure (tables, relationships)
   - Validates DAG structure (acyclic, nodes, edges)
   - Analyzes code quality using heuristics
   - Queries test coverage from database

4. **ReportGenerator** (`report_generator.py`)
   - Generates formatted text reports
   - Outputs JSON and CSV formats
   - Calculates summary statistics
   - Tracks pass rates and timing metrics

### Test Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. Submit Requirement via Framework                     │
│    - Create requirement in DB                           │
│    - Publish requirement.intake event                   │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ 2. EventTracker Subscribes & Captures Events            │
│    - Listens on 15+ event subjects                      │
│    - Indexes events by req_id                           │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ 3. Pipeline Executes (A1-A11)                           │
│    - Knowledge analysis → API schema → ERD → DAG        │
│    - Code generation → Testing → Gate approval          │
│    - Each agent publishes completion events             │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ 4. Framework Polls Requirement Status                   │
│    - Waits for target_gate (default: 7)                 │
│    - Timeout after specified duration                   │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ 5. Verify Outputs & Quality                             │
│    - Check API schema, ERD, DAG existence               │
│    - Query test results and coverage                    │
│    - Validate with QualityValidator                     │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ 6. Generate Report & Cleanup                            │
│    - Format results as text/JSON/CSV                    │
│    - Clean test data from DB                            │
│    - Assert acceptance criteria                         │
└─────────────────────────────────────────────────────────┘
```

## Running Tests

### Prerequisites

- Python 3.10+
- PostgreSQL 14+ with pgvector extension
- NATS server (with JetStream enabled)
- Redis (optional, for caching)

### Local Setup

1. **Start services:**

```bash
# PostgreSQL
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=ai_native \
  -p 5432:5432 \
  pgvector/pgvector:pg15-latest

# NATS
docker run -d --name nats \
  -p 4222:4222 \
  nats:latest

# Redis (optional)
docker run -d --name redis \
  -p 6379:6379 \
  redis:latest
```

2. **Initialize database:**

```bash
psql -h localhost -U postgres -d ai_native < repos/infra/init-db.sql
```

3. **Install test dependencies:**

```bash
pip install pytest pytest-asyncio asyncpg nats-py pydantic
```

### Run Tests

```bash
# Run all tests
pytest tests/integration/ -v

# Run specific scenario
pytest tests/integration/test_e2e_phase6.py::TestE2EPhase6::test_scenario_1_simple_requirement -v

# Run with detailed output
pytest tests/integration/ -v -s --tb=short

# Run with timeout
pytest tests/integration/ --timeout=3600
```

### Configuration

Environment variables:

```bash
export NATS_URL=nats://localhost:4222
export DB_URL=postgresql://user:pass@localhost:5432/ai_native
export REDIS_URL=redis://localhost:6379
export LOG_LEVEL=DEBUG
```

## Expected Event Sequence

### Scenario 1 (Simple)
```
requirement.intake
  ↓
knowledge.analyzed
  ↓
spec.api_schema_ready
  ↓
spec.erd_ready
  ↓
code.generated
  ↓
test.executed
  ↓
requirement.completed
```

### Scenario 2 (Medium)
```
requirement.intake
  ↓
knowledge.analyzed
  ↓
spec.api_schema_ready
  ↓
spec.erd_ready
  ↓
architecture.dag_built
  ↓
code.generated
  ↓
test.executed
  ↓
requirement.completed
```

### Scenario 3 (Complex)
```
requirement.intake
  ↓
knowledge.analyzed
  ↓
spec.api_schema_ready, spec.erd_ready, architecture.dag_built (parallel)
  ↓
code.generated
  ↓
test.generated
  ↓
test.executed
  ↓
gate.submitted
  ↓
gate.approved
  ↓
pr.created
  ↓
requirement.completed
```

## Acceptance Criteria

### Scenario 1: Simple Requirement
- ✅ Requirement completes within 2 hours
- ✅ API schema is generated
- ✅ ERD is generated
- ✅ Code generated (> 0 files changed)
- ✅ Tests pass with >= 80% pass rate
- ✅ Code quality score >= 4.0/5

### Scenario 2: Medium Requirement
- ✅ Requirement completes within 8 hours
- ✅ API schema is generated and valid (OpenAPI 3.x)
- ✅ ERD is generated with relationships
- ✅ Code generated for backend + frontend
- ✅ Tests pass with >= 80% pass rate
- ✅ Code quality score >= 4.0/5
- ✅ Test coverage >= 70%

### Scenario 3: Complex Requirement
- ✅ Process completes (any duration)
- ✅ All major event types are published
- ✅ Minimum 5 different event types
- ✅ No blocking errors
- ✅ Output artifacts generated

## Troubleshooting

### Connection Issues

```bash
# Test NATS connection
nats-cli --server nats://localhost:4222 ping

# Test PostgreSQL connection
psql -h localhost -U postgres -d ai_native -c "SELECT 1"

# Test Redis connection
redis-cli ping
```

### Database Issues

```bash
# Reset database
dropdb -h localhost -U postgres ai_native
createdb -h localhost -U postgres ai_native
psql -h localhost -U postgres -d ai_native < repos/infra/init-db.sql
```

### Test Timeouts

- Scenario 1: Set timeout > 7200s (2h)
- Scenario 2: Set timeout > 28800s (8h)
- Scenario 3: Set timeout > 86400s (24h)

### Event Tracking

Enable debug logging to see event flow:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Output Examples

### Test Report (Text)

```
================================================================================
Phase 6 End-to-End Integration Test Report
================================================================================

Generated: 2024-07-02 15:30:45

EXECUTIVE SUMMARY
----------------================================================================
Total Tests: 3
Passed: 3 (100.0%)
Failed: 0
Timeout: 0

Total Duration: 12345.67s (3.43h)
Average Duration: 4115.22s
Average Code Quality: 4.5/5
Average Test Coverage: 75.3%

SCENARIO RESULTS
--------------------------------------------------------------------------------
✅ Scenario 1: Add email_verified field
   Requirement ID: 550e8400-e29b-41d4-a716-446655440000
   Status: PASSED
   Duration: 1234.56s
   Code Quality: 4.5/5
   Test Pass Rate: 95.0%
   Test Coverage: 85.0%

...
```

### JSON Output

```json
{
  "timestamp": "2024-07-02T15:30:45.123456",
  "total_tests": 3,
  "passed": 3,
  "failed": 0,
  "timeout": 0,
  "results": [
    {
      "scenario_id": "scenario_1",
      "scenario_name": "Add email_verified field",
      "req_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "passed",
      "duration_seconds": 1234.56,
      ...
    }
  ]
}
```

## CI/CD Integration

Tests run automatically on:
- Push to main/develop branches
- Pull requests to main
- Daily schedule (2 AM UTC)

See `.github/workflows/e2e_test.yml` for GitHub Actions configuration.

## Development

### Adding New Test Scenarios

1. Create scenario definition in `test_e2e_phase6.py`
2. Add test method following existing patterns
3. Define expected events and quality thresholds
4. Update acceptance criteria
5. Add to CI/CD workflow if needed

### Extending Validators

- Add validation methods to `QualityValidator`
- Implement artifact-specific checks
- Return score (0-5) and detailed issues

### Custom Reports

- Extend `ReportGenerator` with custom formatting
- Add metrics to `TestResult` as needed
- Implement domain-specific report templates

## Files

```
tests/integration/
├── __init__.py                    # Package initialization
├── conftest.py                    # Pytest configuration
├── e2e_test_framework.py          # Main E2E framework
├── event_tracker.py               # NATS event tracking
├── quality_validator.py           # Artifact validation
├── report_generator.py            # Report generation
├── test_e2e_phase6.py             # Test scenarios
└── README.md                      # This file

.github/workflows/
└── e2e_test.yml                   # CI/CD workflow
```

## License

MIT
