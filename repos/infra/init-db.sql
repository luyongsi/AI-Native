-- AI Native 初始表结构

CREATE EXTENSION IF NOT EXISTS vector;

-- 需求主表
CREATE TABLE IF NOT EXISTS requirements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     VARCHAR(50) UNIQUE,
    title           VARCHAR(500) NOT NULL,
    status          VARCHAR(30) NOT NULL DEFAULT 'draft',
    priority        VARCHAR(5) NOT NULL DEFAULT 'P2',
    current_gate    SMALLINT,
    spec            JSONB,
    tasks           JSONB,
    ai_completion   SMALLINT DEFAULT 0,
    human_interventions INT DEFAULT 0,
    blocked         BOOLEAN DEFAULT FALSE,
    block_reason    TEXT,
    version         VARCHAR(20),
    source_type     VARCHAR(30),
    source_payload  JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Agent 活动表
CREATE TABLE IF NOT EXISTS agent_activities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        VARCHAR(50) NOT NULL,
    agent_type      VARCHAR(30) NOT NULL,
    req_id          UUID REFERENCES requirements(id),
    task_id         VARCHAR(50),
    status          VARCHAR(30) NOT NULL,
    current_action  TEXT,
    tool_calls_json JSONB,
    code_added      INT DEFAULT 0,
    code_removed    INT DEFAULT 0,
    anomaly         VARCHAR(30),
    inner_loop      JSONB,
    session_id      VARCHAR(100),
    cost_usd        NUMERIC(10,6),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activities_req ON agent_activities(req_id);
CREATE INDEX IF NOT EXISTS idx_activities_status ON agent_activities(status);

-- Gate 审批表
CREATE TABLE IF NOT EXISTS gate_approvals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    req_id          UUID REFERENCES requirements(id) NOT NULL,
    gate            SMALLINT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    approver        VARCHAR(100),
    sla_deadline    TIMESTAMPTZ NOT NULL,
    agent_reviews   JSONB,
    reject_reasons  JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_gate_req ON gate_approvals(req_id);

-- 测试执行表
CREATE TABLE IF NOT EXISTS test_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    req_id          UUID REFERENCES requirements(id) NOT NULL,
    task_id         VARCHAR(50),
    round           INT NOT NULL DEFAULT 1,
    total_cases     INT DEFAULT 0,
    passed          INT DEFAULT 0,
    failed          INT DEFAULT 0,
    skipped         INT DEFAULT 0,
    coverage        NUMERIC(5,2),
    ai_generated_ratio NUMERIC(5,2),
    quality_score   JSONB,
    failed_cases    JSONB,
    traces          JSONB,
    visual_diffs    JSONB,
    vis_task_id     VARCHAR(50),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_test_req ON test_executions(req_id);

-- 熔断日志
CREATE TABLE IF NOT EXISTS loop_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    req_id          UUID REFERENCES requirements(id) NOT NULL,
    scope           VARCHAR(20) NOT NULL,
    participants    JSONB,
    round           INT NOT NULL,
    max_round       INT NOT NULL,
    escalation      VARCHAR(30),
    tripped         BOOLEAN DEFAULT FALSE,
    fallback_action TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 向量存储
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          VARCHAR(100) NOT NULL,
    title           VARCHAR(500),
    content         TEXT NOT NULL,
    doc_type        VARCHAR(30),
    file_path       VARCHAR(500),
    repo_path       VARCHAR(300),
    embedding       vector(1024),
    search_vector   tsvector,
    project         VARCHAR(100),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_chunks_search ON knowledge_chunks USING GIN (search_vector);
