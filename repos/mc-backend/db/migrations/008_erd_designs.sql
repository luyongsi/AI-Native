-- Migration: Create ERD designs table for A4 Spec Writer
-- Stores generated Entity-Relationship Diagrams and DDL statements with versioning

CREATE TABLE IF NOT EXISTS erd_designs (
  id SERIAL PRIMARY KEY,
  req_id UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
  erd_mermaid TEXT NOT NULL,
  ddl TEXT NOT NULL,
  entities JSONB NOT NULL DEFAULT '[]'::jsonb,
  relationships JSONB NOT NULL DEFAULT '[]'::jsonb,
  validation_passed BOOLEAN DEFAULT FALSE,
  validation_errors JSONB DEFAULT '[]'::jsonb,
  is_incremental BOOLEAN DEFAULT false,
  existing_tables JSONB DEFAULT '[]'::jsonb,
  version INT DEFAULT 1,
  source VARCHAR(50) DEFAULT 'llm',  -- 'llm' or 'fallback'
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for efficient lookups by requirement ID
CREATE INDEX IF NOT EXISTS idx_erd_designs_req_id
  ON erd_designs (req_id DESC);

-- Index for filtering by version and validation status
CREATE INDEX IF NOT EXISTS idx_erd_designs_version_valid
  ON erd_designs (req_id, version DESC, validation_passed);

-- Index for creation time based queries (recent designs)
CREATE INDEX IF NOT EXISTS idx_erd_designs_created
  ON erd_designs (created_at DESC);

-- Index for incremental schema detection
CREATE INDEX IF NOT EXISTS idx_erd_designs_incremental
  ON erd_designs (req_id, is_incremental, created_at DESC);

-- Comment for documentation
COMMENT ON TABLE erd_designs IS 'Stores generated Entity-Relationship Diagrams and DDL statements for requirements. Supports versioning, validation tracking, and incremental schema updates.';
COMMENT ON COLUMN erd_designs.req_id IS 'Foreign key reference to the requirement that this ERD was generated for';
COMMENT ON COLUMN erd_designs.erd_mermaid IS 'Mermaid erDiagram syntax for visualization';
COMMENT ON COLUMN erd_designs.ddl IS 'PostgreSQL DDL statements (CREATE TABLE or ALTER TABLE)';
COMMENT ON COLUMN erd_designs.entities IS 'JSON array of entity definitions with names and primary keys';
COMMENT ON COLUMN erd_designs.relationships IS 'JSON array of relationship definitions (from, to, type, foreign_key)';
COMMENT ON COLUMN erd_designs.validation_passed IS 'Whether the DDL passed validation';
COMMENT ON COLUMN erd_designs.validation_errors IS 'Array of validation error messages if validation failed';
COMMENT ON COLUMN erd_designs.is_incremental IS 'Whether this is an incremental schema update for existing tables';
COMMENT ON COLUMN erd_designs.existing_tables IS 'JSON array of table names that existed before this update';
COMMENT ON COLUMN erd_designs.version IS 'Version number for this design (starts at 1, increments on regeneration)';
COMMENT ON COLUMN erd_designs.source IS 'Source of the ERD - either LLM generated or fallback template';
