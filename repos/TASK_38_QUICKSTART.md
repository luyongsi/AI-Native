# Task #38: OpenTelemetry + Jaeger Implementation - Quick Start Guide

## What Was Implemented

A complete distributed tracing infrastructure using OpenTelemetry and Jaeger for end-to-end visibility across your system (FastAPI backend, Temporal orchestrator, agent workers, and NATS event bus).

## Quick Start (5 minutes)

### 1. Install Dependencies

```bash
# In all service directories
pip install -r repos/infra/observability/requirements.txt
```

### 2. Start Infrastructure

```bash
cd repos/infra
docker-compose up -d

# Verify Jaeger is running
docker ps | grep jaeger
```

### 3. Start Services with Tracing

```bash
# Terminal 1: Orchestrator
cd repos/orchestrator
ENVIRONMENT=dev python worker.py

# Terminal 2: MC Backend
cd repos/mc-backend
ENVIRONMENT=dev python main.py

# Terminal 3: Agent Workers (e.g., A1)
cd repos/agent-workers/a1
python worker_launcher.py
```

### 4. Access Jaeger UI

Open browser: **http://localhost:16686**

### 5. Generate Traces

Make an API request to trigger end-to-end traces:

```bash
curl -X POST http://localhost:8000/api/requirements \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Feature", "description": "Testing OTEL tracing"}'
```

Then check Jaeger UI - you should see a trace with:
- Service: `mc-backend` (API request span)
- Service: `orchestrator` (workflow orchestration span)
- Service: `agent-a1` (agent execution span)

## Architecture

### Services with Tracing

| Service | Tracing Type | Key Spans |
|---------|--------------|-----------|
| mc-backend | Auto-instrumented | GET/POST endpoints, DB queries |
| orchestrator | Manual + auto | Workflows, activities |
| agent-* | Manual | NATS message processing, LLM calls |
| otel-collector | N/A (infrastructure) | Receives spans from services |
| jaeger | N/A (backend) | Stores and indexes traces |

### Trace Flow Example

```
1. HTTP Request
   └─ POST /api/requirements
      └─ Span: mc-backend (root trace)
         └─ Span: workflow.trigger
            └─ Span: orchestrator.handle_requirement (new trace, linked)
               └─ Span: activity.dispatch_agent
                  └─ NATS Publish (context propagated)
                     └─ Span: agent-a1.execute (traces back to root)
                        └─ Span: llm.call
                           └─ Return result
```

## Key Files

### New Files Created

- `repos/infra/observability/otel_config.py` - Main tracer initialization
- `repos/infra/observability/sampling.py` - Sampling strategies
- `repos/infra/observability/span_attributes.py` - Standard attributes
- `repos/infra/observability/requirements.txt` - Dependencies
- `repos/TASK_38_IMPLEMENTATION.md` - Full implementation details

### Modified Files

- `repos/infra/docker-compose.yml` - Added Jaeger service
- `repos/infra/otel-collector/config.yaml` - Export to Jaeger
- `repos/agent-workers/base_worker.py` - Agent tracing integration
- `repos/mc-backend/main.py` - FastAPI instrumentation
- `repos/orchestrator/worker.py` - Orchestrator initialization

## Configuration

### Environment Variables

```bash
# Optional: Override OTEL endpoint
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Optional: Override sampling rate
OTEL_TRACES_SAMPLER_ARG=1.0  # 0.0-1.0

# Service environment (affects default sampling)
ENVIRONMENT=dev              # 100% sampling
ENVIRONMENT=staging          # 50% sampling
ENVIRONMENT=prod             # 10% sampling
```

### Sampling Rates

- **Development**: 100% - capture all traces for debugging
- **Staging**: 50% - balance between visibility and overhead
- **Production**: 10% - minimal overhead for high-volume systems

To override: `export OTEL_TRACES_SAMPLER_ARG=1.0`

## Understanding Traces in Jaeger

### Service Dropdown
Shows all services sending traces:
- `mc-backend` - FastAPI application
- `orchestrator` - Temporal orchestrator
- `agent-a1`, `agent-a2`, etc. - Agent workers

### Find Traces
1. Select service (e.g., `mc-backend`)
2. Select operation (e.g., `GET /health`)
3. Click "Find Traces"
4. Click on a trace to inspect

### Trace Details

Each span shows:
- **Duration**: How long the operation took
- **Tags**: Key-value attributes (req_id, agent_id, model, tokens, etc.)
- **Logs**: Events that occurred (errors, status changes)
- **Parent-Child**: Relationship between spans

## Verifying Implementation

### Checklist

- [ ] Jaeger UI loads at http://localhost:16686
- [ ] Make API request with `curl`
- [ ] See `mc-backend` service in Jaeger dropdown
- [ ] See `GET` operations in operation dropdown
- [ ] Find and open a trace
- [ ] Inspect span attributes (should see `req_id`, durations, etc.)
- [ ] See multiple services in a single trace (mc-backend, orchestrator, agent-*)

### Expected Trace Structure

A typical requirement processing trace shows:
1. **Root span**: HTTP request (mc-backend)
2. **Child span**: Database query (if applicable)
3. **Child span**: Workflow trigger
4. **Linked span**: Orchestrator workflow (same trace or linked)
5. **Child spans**: Agent execution via NATS
6. **Child spans**: LLM calls with token counts

## Troubleshooting

### No Traces Appearing

```bash
# 1. Verify Jaeger is running
docker ps | grep jaeger

# 2. Verify OTEL Collector is running
docker ps | grep otel

# 3. Check service logs for OTEL errors
docker logs ai-jaeger
docker logs ai-otel-collector

# 4. Verify endpoint is accessible
curl http://localhost:14250  # Should timeout or connect
curl http://localhost:4317   # gRPC endpoint
```

### Traces Visible but No Detail

```bash
# 1. Check sampling isn't filtering traces
export OTEL_TRACES_SAMPLER_ARG=1.0
# Restart service

# 2. Check service logs for initialization errors
# Look for: "OpenTelemetry tracer initialized"
```

### High Memory/CPU Usage

```bash
# 1. Reduce sampling (default is 100% for dev)
export OTEL_TRACES_SAMPLER_ARG=0.1  # 10% sampling
# Restart service

# 2. Monitor trace volume
# Check Jaeger UI → System → Spans per second
```

## Performance Impact

### Expected Overhead

- **Latency**: ~1-5ms per request (batched export)
- **Memory**: ~50-100MB for tracer provider
- **Network**: ~1-5 KB per span

### For 1000 req/sec

- Spans produced: ~5,000-10,000 per second
- Data rate: ~5-50 MB/s to Jaeger
- Storage: ~1-5 GB/day (configurable retention)

## Common Use Cases

### 1. Debugging Slow Requests

```
1. Find slow trace in Jaeger (sort by duration)
2. Expand all spans
3. Identify slowest span
4. Check attributes for context (req_id, agent_id)
5. Look for errors or wait times
```

### 2. Tracing a Specific Request

```bash
# Get req_id from logs or API response
# In Jaeger UI:
# 1. Service: mc-backend
# 2. Tags: req_id = <value>
# 3. Find Traces
# 4. Click to view full trace
```

### 3. Monitoring Agent Performance

```
1. Service: agent-a1
2. Look at operation: agent-a1.execute
3. Filter by: agent.type = "intent_classifier"
4. Check average duration and error rate
```

### 4. LLM Cost Analysis

```
1. Find traces with spans containing llm.tokens.input/output
2. Multiply tokens by model cost
3. Aggregate by service/agent
4. Identify cost drivers
```

## Next Steps

### Immediate (Optional)

- Set up Jaeger storage backend (Elasticsearch) for persistence
- Configure trace retention policy
- Set up alerts on error rate or latency

### Medium-term

- Add custom instrumentation for specific business logic
- Set up trace-based metrics (derive metrics from traces)
- Configure tail-based sampling for production

### Long-term

- ML-based anomaly detection in traces
- Service dependency mapping
- Cost attribution per customer/feature

## Support & Resources

### Files to Review

1. **otel_config.py** - How tracing is initialized
2. **span_attributes.py** - What attributes are captured
3. **base_worker.py** - How agents create spans
4. **main.py (mc-backend)** - How FastAPI is instrumented

### Documentation

- [OpenTelemetry Documentation](https://opentelemetry.io/)
- [Jaeger Documentation](https://www.jaegertracing.io/)
- [Task #38 Full Implementation](./TASK_38_IMPLEMENTATION.md)

### Key Concepts

- **Trace**: A request flowing through the system
- **Span**: A single operation within a trace
- **Attributes**: Key-value metadata on spans (req_id, model, etc.)
- **Events**: Significant moments during span execution
- **Status**: OK or ERROR for span result
