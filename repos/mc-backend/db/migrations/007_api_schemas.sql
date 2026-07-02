-- Migration: Create API schemas table for A4 Spec Writer
-- Stores generated OpenAPI 3.1 specifications with versioning and metadata

CREATE TABLE IF NOT EXISTS api_schemas (
  id SERIAL PRIMARY KEY,
  req_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
  schema_json JSONB NOT NULL,
  version INT DEFAULT 1,
  validation_passed BOOLEAN DEFAULT FALSE,
  validation_errors JSONB DEFAULT '[]'::jsonb,
  source VARCHAR(50) DEFAULT 'llm',  -- 'llm' or 'fallback'
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for efficient lookups by requirement ID
CREATE INDEX IF NOT EXISTS idx_api_schemas_req_id
  ON api_schemas (req_id DESC);

-- Index for filtering by version and validation status
CREATE INDEX IF NOT EXISTS idx_api_schemas_version_valid
  ON api_schemas (req_id, version DESC, validation_passed);

-- Index for creation time based queries (recent schemas)
CREATE INDEX IF NOT EXISTS idx_api_schemas_created
  ON api_schemas (created_at DESC);

-- Comment for documentation
COMMENT ON TABLE api_schemas IS 'Stores generated OpenAPI 3.1 specifications for requirements. Supports versioning and validation tracking.';
COMMENT ON COLUMN api_schemas.req_id IS 'Foreign key reference to the requirement that this schema was generated for';
COMMENT ON COLUMN api_schemas.schema_json IS 'The complete OpenAPI 3.1 specification as JSONB';
COMMENT ON COLUMN api_schemas.version IS 'Version number for this schema (starts at 1, increments on regeneration)';
COMMENT ON COLUMN api_schemas.validation_passed IS 'Whether the schema passed OpenAPI 3.1 validation';
COMMENT ON COLUMN api_schemas.validation_errors IS 'Array of validation error messages if validation failed';
COMMENT ON COLUMN api_schemas.source IS 'Source of the schema - either LLM generated or fallback template';
