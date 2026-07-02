-- Migration: Enable pgvector and create knowledge_embeddings table
-- Provides semantic search capability for requirements, code, specs, and docs

CREATE EXTENSION IF NOT EXISTS vector;

-- Knowledge embeddings table for semantic search
-- Stores vectorized content with metadata for retrieval
CREATE TABLE knowledge_embeddings (
  id SERIAL PRIMARY KEY,
  content_type VARCHAR(50),              -- 'requirement', 'code', 'spec', 'doc'
  content_id VARCHAR(255),               -- reference to source (requirement_id, file_path, etc.)
  content_text TEXT,                     -- original text for display
  embedding vector(1536),                -- 1536-dim vector (OpenAI/DeepSeek standard)
  metadata JSONB,                        -- flexible storage for tags, source, author, etc.
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for cosine similarity search (IVFFlat for scalability)
-- Supports efficient vector searches via <=> operator
CREATE INDEX idx_knowledge_embeddings_vector
  ON knowledge_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Index for filtering by content_type and creation time
CREATE INDEX idx_knowledge_embeddings_type_created
  ON knowledge_embeddings (content_type, created_at DESC);

-- Index for content_id lookups (to avoid duplicate embeddings)
CREATE INDEX idx_knowledge_embeddings_content_id
  ON knowledge_embeddings (content_type, content_id);

-- Create a view for recent embeddings (convenience)
CREATE VIEW v_recent_embeddings AS
SELECT
  id,
  content_type,
  content_id,
  content_text,
  embedding,
  metadata,
  created_at
FROM knowledge_embeddings
WHERE created_at > NOW() - INTERVAL '30 days'
ORDER BY created_at DESC;

COMMENT ON TABLE knowledge_embeddings IS 'Stores vector embeddings for semantic search across requirements, code, specs, and documentation';
COMMENT ON COLUMN knowledge_embeddings.embedding IS 'Vector embedding (1536-dim) generated from content_text via DeepSeek embedding API';
COMMENT ON COLUMN knowledge_embeddings.metadata IS 'JSONB for flexible metadata: {source_repo, author, tags, source_url, etc.}';
