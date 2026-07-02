-- A6 DAG Builder: Task DAG Storage (Migration 009)
-- Stores structured task dependency graphs (DAGs) for each requirement

CREATE TABLE IF NOT EXISTS task_dags (
    id              SERIAL PRIMARY KEY,
    req_id          UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,

    -- DAG Structure
    tasks           JSONB NOT NULL,  -- Array of task objects with id, title, dependencies, estimated_hours, etc.
    edges           JSONB NOT NULL,  -- Array of edges: [{from, to, type}, ...]
    dag_json        JSONB,            -- Full DAG structure for visualization

    -- Analysis Results
    critical_path   JSONB,            -- Array of task IDs on critical path
    critical_path_hours FLOAT,        -- Total hours on critical path
    parallelizable  JSONB,            -- Array of parallel task groups
    total_estimated_hours FLOAT,      -- Sum of all task estimated hours

    -- Metadata
    analysis_source VARCHAR(50),      -- "analyzer" | "llm" | "fallback"
    has_cycles      BOOLEAN DEFAULT FALSE,
    cycle_nodes     JSONB,            -- If has_cycles=true, list of nodes involved

    -- Versioning
    version         INT DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_dags_req_id ON task_dags(req_id DESC);
CREATE INDEX IF NOT EXISTS idx_task_dags_created ON task_dags(created_at DESC);

-- Task execution status tracking
CREATE TABLE IF NOT EXISTS task_executions (
    id              SERIAL PRIMARY KEY,
    req_id          UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    dag_id          INT NOT NULL REFERENCES task_dags(id) ON DELETE CASCADE,

    -- Task Reference
    task_id         VARCHAR(100) NOT NULL,  -- From tasks array in task_dags
    task_type       VARCHAR(50),            -- db_migration | api_impl | frontend | testing | etc.

    -- Execution State
    status          VARCHAR(30) DEFAULT 'pending',  -- pending | running | completed | failed | blocked
    assigned_agent  VARCHAR(50),            -- Agent ID handling this task

    -- Results
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_hours  FLOAT,

    -- Artifacts
    output_summary  TEXT,
    artifacts_json  JSONB,              -- Links to generated code, docs, etc.
    error_message   TEXT,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_executions_req ON task_executions(req_id);
CREATE INDEX IF NOT EXISTS idx_task_executions_status ON task_executions(status);
CREATE INDEX IF NOT EXISTS idx_task_executions_dag ON task_executions(dag_id);

-- Shared module definitions
CREATE TABLE IF NOT EXISTS shared_modules (
    id              SERIAL PRIMARY KEY,
    req_id          UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,

    module_name     VARCHAR(100) NOT NULL,
    module_type     VARCHAR(50),        -- utility | middleware | model | config | schema
    description     TEXT,

    -- Usage tracking
    used_by_tasks   JSONB,              -- Array of task IDs that use this module
    priority        INT DEFAULT 2,      -- 1=critical, 2=standard, 3=optional

    -- Implementation
    file_path       VARCHAR(500),
    status          VARCHAR(30) DEFAULT 'pending',  -- pending | implemented | tested

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shared_modules_req ON shared_modules(req_id);
CREATE INDEX IF NOT EXISTS idx_shared_modules_status ON shared_modules(status);
