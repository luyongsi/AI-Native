-- Create missing Stage 2 tables (design_specs + prototype_artifacts)
DO
$$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'design_specs') THEN
        CREATE TABLE design_specs (
            id BIGSERIAL PRIMARY KEY,
            req_id UUID NOT NULL,
            cycle INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            spec_doc JSONB,
            openapi_schema JSONB,
            erd_diagram JSONB,
            ddl_statements TEXT,
            quality_score NUMERIC(3,2),
            source VARCHAR(20) DEFAULT 'llm',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_design_specs_req_cycle_version UNIQUE (req_id, cycle, version),
            CONSTRAINT ck_design_specs_quality_score CHECK (quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1))
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'prototype_artifacts') THEN
        CREATE TABLE prototype_artifacts (
            id BIGSERIAL PRIMARY KEY,
            req_id UUID NOT NULL,
            cycle INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            prototype_url TEXT,
            html_content TEXT,
            screens JSONB DEFAULT '[]'::jsonb,
            annotations JSONB DEFAULT '[]'::jsonb,
            status VARCHAR(20) DEFAULT 'draft',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_prototype_artifacts_req_cycle_version UNIQUE (req_id, cycle, version),
            CONSTRAINT ck_prototype_artifacts_status CHECK (status IN ('draft', 'confirmed'))
        );
    END IF;
END
$$;
