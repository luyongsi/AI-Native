-- 010_prototype_annotations.sql
-- Prototype annotation storage and versioning

CREATE TABLE IF NOT EXISTS prototype_annotations (
    id SERIAL PRIMARY KEY,
    req_id UUID NOT NULL,
    image_url TEXT NOT NULL,
    annotations JSONB NOT NULL,
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast req_id lookups
CREATE INDEX IF NOT EXISTS idx_prototype_annotations_req_id
    ON prototype_annotations(req_id DESC);

-- Index for timeline queries
CREATE INDEX IF NOT EXISTS idx_prototype_annotations_created_at
    ON prototype_annotations(created_at DESC);

-- COMMENT on table
COMMENT ON TABLE prototype_annotations IS 'Stores UI prototype annotations for code generation';
COMMENT ON COLUMN prototype_annotations.req_id IS 'Reference to requirement request';
COMMENT ON COLUMN prototype_annotations.image_url IS 'URL to prototype image/screenshot';
COMMENT ON COLUMN prototype_annotations.annotations IS 'JSONB array of annotation objects';
COMMENT ON COLUMN prototype_annotations.version IS 'Version number for multi-iteration support';
