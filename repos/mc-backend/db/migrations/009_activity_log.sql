-- Migration 009: Create activity_log table for persisting agent activity events
-- Stores progress, status, and artifact events for history queries and analytics

CREATE TABLE IF NOT EXISTS activity_log (
  id BIGSERIAL PRIMARY KEY,
  req_id UUID NOT NULL,
  agent_id VARCHAR(255) NOT NULL,
  event_type VARCHAR(50) NOT NULL,  -- 'progress', 'status', 'artifact'
  step VARCHAR(255),                -- For progress events
  status VARCHAR(50),               -- For status events
  artifact_type VARCHAR(100),       -- For artifact events
  details TEXT,                     -- Human-readable description
  progress_percent INT CHECK (progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)),
  artifact JSONB,                   -- Full artifact data for artifact events
  metadata JSONB DEFAULT '{}'::jsonb,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for efficient lookups by request ID
CREATE INDEX IF NOT EXISTS idx_activity_log_req_id
  ON activity_log (req_id DESC);

-- Index for agent-specific activity lookup
CREATE INDEX IF NOT EXISTS idx_activity_log_agent_id
  ON activity_log (agent_id DESC);

-- Composite index for req_id + timestamp for efficient history queries
CREATE INDEX IF NOT EXISTS idx_activity_log_req_id_timestamp
  ON activity_log (req_id DESC, timestamp DESC);

-- Composite index for agent + timestamp for agent activity history
CREATE INDEX IF NOT EXISTS idx_activity_log_agent_timestamp
  ON activity_log (agent_id, timestamp DESC);

-- Index for filtering by event type
CREATE INDEX IF NOT EXISTS idx_activity_log_event_type
  ON activity_log (event_type);

-- Index for filtering artifacts
CREATE INDEX IF NOT EXISTS idx_activity_log_artifact
  ON activity_log (artifact_type) WHERE artifact_type IS NOT NULL;

-- Composite index for common query pattern: req_id + event_type + timestamp
CREATE INDEX IF NOT EXISTS idx_activity_log_req_event_time
  ON activity_log (req_id, event_type, timestamp DESC);

-- Comment for documentation
COMMENT ON TABLE activity_log IS 'Persists real-time agent activity events (progress, status, artifacts) for history queries, analytics, and debugging.';
COMMENT ON COLUMN activity_log.req_id IS 'Request ID for correlating related activities';
COMMENT ON COLUMN activity_log.agent_id IS 'Agent identifier that produced the event';
COMMENT ON COLUMN activity_log.event_type IS 'Event type: progress, status, or artifact';
COMMENT ON COLUMN activity_log.step IS 'Current step/stage for progress events';
COMMENT ON COLUMN activity_log.status IS 'Status value for status events (pending, running, completed, failed)';
COMMENT ON COLUMN activity_log.artifact_type IS 'Type of artifact for artifact events';
COMMENT ON COLUMN activity_log.details IS 'Human-readable description of the activity';
COMMENT ON COLUMN activity_log.progress_percent IS 'Progress percentage for progress events (0-100)';
COMMENT ON COLUMN activity_log.artifact IS 'Full artifact content as JSONB';
COMMENT ON COLUMN activity_log.metadata IS 'Additional metadata and context';
COMMENT ON COLUMN activity_log.timestamp IS 'When the event was created by the agent';
COMMENT ON COLUMN activity_log.created_at IS 'When the event was persisted to the database';
