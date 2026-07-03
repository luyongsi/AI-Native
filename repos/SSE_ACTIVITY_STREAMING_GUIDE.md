# SSE Activity Streaming Implementation Guide

## Overview

This implementation adds real-time Server-Sent Events (SSE) streaming for agent activity tracking in the Mission Control Backend. Agents can publish progress, status, and artifact events via NATS JetStream, which are then streamed to clients via HTTP SSE.

## Components Created

### 1. ActivityRecorder (`agent-workers/activity_recorder.py`)

A NATS-based event publisher for agent activities.

**Key Methods:**
- `record_progress()` - Track execution steps and progress percentage
- `record_status()` - Track agent status changes (pending, running, completed, failed)
- `record_artifact()` - Track produced artifacts

**NATS Subjects:**
- `agent.{agent_id}.progress` - Progress events
- `agent.{agent_id}.status` - Status change events
- `agent.{agent_id}.artifact` - Artifact events

### 2. SSE Endpoint (`mc-backend/api/activity_stream.py`)

FastAPI router providing real-time event streaming.

**Endpoint:** `GET /api/activity/stream?req_id=<optional>`

**Query Parameters:**
- `req_id` (optional) - Filter events for a specific request

**Response:** Server-Sent Events stream with event data as JSON

**Event Types:**
- `agent.progress` - Progress updates
- `agent.status` - Status changes
- `agent.artifact` - Artifact events
- `heartbeat` - Periodic keepalive (30s timeout)

### 3. Database Migration (`mc-backend/db/migrations/009_activity_log.sql`)

Creates `activity_log` table for persisting activity events.

**Columns:**
- `req_id` - Request identifier
- `agent_id` - Agent identifier
- `event_type` - Type of event (progress, status, artifact)
- `step` / `status` / `artifact_type` - Event-specific fields
- `details` - Human-readable description
- `progress_percent` - Progress percentage (0-100)
- `artifact` - Full artifact data as JSONB
- `metadata` - Additional context

**Indexes:** Composite indexes for efficient queries by req_id, agent_id, event_type, and timestamp

### 4. BaseAgentWorker Integration

Three new convenience methods added to `BaseAgentWorker`:

```python
# Record progress during execution
await self.record_progress(
    req_id="abc-123",
    step="validation",
    details="Running schema validation...",
    progress_percent=50,
    metadata={"tables": 5}
)

# Record status changes
await self.record_activity_status(
    req_id="abc-123",
    status="running",
    message="Agent started processing"
)

# Record artifacts
await self.record_activity_artifact(
    req_id="abc-123",
    artifact_type="code_diff",
    artifact_data={"files": [...], "changes": ...}
)
```

## Usage Examples

### Agent Worker Implementation

```python
from base_worker import BaseAgentWorker

class MyAgent(BaseAgentWorker):
    agent_id = "A5"
    agent_type = "analyzer"
    
    async def execute(self, req_id: str, context: dict) -> dict:
        # Start execution
        await self.record_activity_status(req_id, "running", "Analysis started")
        
        # Report progress
        await self.record_progress(req_id, "step_1", "Analyzing requirements", 25)
        # ... do work ...
        
        await self.record_progress(req_id, "step_2", "Generating schema", 50)
        # ... do work ...
        
        await self.record_progress(req_id, "step_3", "Validating schema", 75)
        # ... do work ...
        
        # Report artifact
        await self.record_activity_artifact(
            req_id,
            "erd_design",
            {"mermaid": "...", "tables": [...]}
        )
        
        # Complete
        await self.record_activity_status(req_id, "completed", "Analysis done")
        return {"status": "success"}
```

### Frontend Client Usage

#### JavaScript/TypeScript

```javascript
// Connect to activity stream
const eventSource = new EventSource('/api/activity/stream?req_id=abc-123');

eventSource.addEventListener('agent.progress', (event) => {
  const data = JSON.parse(event.data);
  console.log(`${data.step}: ${data.details} (${data.progress_percent}%)`);
  updateProgressBar(data.progress_percent);
});

eventSource.addEventListener('agent.status', (event) => {
  const data = JSON.parse(event.data);
  console.log(`Status: ${data.status}`);
  updateStatusDisplay(data.status, data.message);
});

eventSource.addEventListener('agent.artifact', (event) => {
  const data = JSON.parse(event.data);
  console.log(`Artifact produced: ${data.artifact_type}`);
  displayArtifact(data.artifact);
});

eventSource.addEventListener('heartbeat', () => {
  console.log('Connection alive');
});

eventSource.onerror = () => {
  console.error('Stream connection lost');
  eventSource.close();
};
```

## Architecture

```
Agent Worker (executing)
    ↓ (record_progress/status/artifact)
ActivityRecorder
    ↓ (NATS JetStream publish)
NATS (AI_NATIVE_EVENTS stream)
    ↓ (subscribed to agent.*.*)
SSE Endpoint
    ↓ (EventSourceResponse)
Client (SSE EventSource)
```

## Event Flow

1. Agent records event: `await agent.record_progress(req_id, step, details, progress_percent)`
2. ActivityRecorder publishes: Event sent to NATS subject `agent.{agent_id}.progress`
3. SSE endpoint subscribes: Receives message from JetStream
4. Filter by req_id: If specified, only forward matching events
5. Stream to client: Event sent as SSE with event type
6. Client displays: JavaScript EventSource listener handles event

## Database Persistence

To persist activity events to PostgreSQL, add a listener in `main.py`:

```python
async def persist_activity_event(msg):
    try:
        data = json.loads(msg.data.decode())
        async with DB_POOL.acquire() as conn:
            await conn.execute("""
                INSERT INTO activity_log (
                    req_id, agent_id, event_type, step, status, artifact_type,
                    details, progress_percent, artifact, metadata, timestamp
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """, 
            data.get('req_id'),
            data.get('agent_id'),
            data.get('event_type'),
            data.get('step'),
            data.get('status'),
            data.get('artifact_type'),
            data.get('details'),
            data.get('progress_percent'),
            json.dumps(data.get('artifact', {})),
            json.dumps(data.get('metadata', {})),
            data.get('timestamp')
            )
    except Exception as e:
        logger.error(f"Failed to persist activity event: {e}")
```

## Performance Considerations

- Memory: Ephemeral subscriptions (no durable consumers) to reduce state
- Timeouts: 30-second client timeout with heartbeat to detect disconnections
- Filtering: req_id filtering done in-memory before forwarding
- Scalability: Each client has independent subscription, leveraging NATS fan-out

## Error Handling

- Connection failures: Gracefully degrade when ActivityRecorder unavailable
- NATS disconnect: SSE endpoint catches and closes stream
- Message parsing: Invalid JSON logged but doesn't crash stream
- Client disconnect: Task cancellation handled automatically

## Dependencies

- nats-py>=0.2.7 - Already in requirements
- sse-starlette>=1.6.0 - Added to requirements.txt

## Testing

```bash
# Start agent and trigger execution
# In another terminal, connect to stream:

curl -N "http://localhost:8000/api/activity/stream?req_id=test-123"

# Should see:
# data: {"agent_id":"A5","req_id":"test-123","event_type":"agent.progress",...}
# data: {"agent_id":"A5","req_id":"test-123","event_type":"agent.status",...}
```

## Files Modified/Created

- Created: `agent-workers/activity_recorder.py`
- Created: `mc-backend/api/activity_stream.py`
- Created: `mc-backend/db/migrations/009_activity_log.sql`
- Modified: `agent-workers/base_worker.py` (added ActivityRecorder integration)
- Modified: `mc-backend/requirements.txt` (added sse-starlette)
- Modified: `mc-backend/main.py` (mounted activity_stream router)
