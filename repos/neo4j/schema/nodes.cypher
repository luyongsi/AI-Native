// ============================================================
// Phase 6C: Neo4j Knowledge Graph — Node Definitions & Constraints
// ============================================================
// Defines all node types for the AI-Native Development Platform
// knowledge graph schema. Run this before edges.cypher.

// ---- Constraints (uniqueness) ----

CREATE CONSTRAINT agent_id_unique IF NOT EXISTS
FOR (n:Agent) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT requirement_id_unique IF NOT EXISTS
FOR (n:Requirement) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT spec_id_unique IF NOT EXISTS
FOR (n:Spec) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT task_id_unique IF NOT EXISTS
FOR (n:Task) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT codebase_id_unique IF NOT EXISTS
FOR (n:Codebase) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT apidoc_id_unique IF NOT EXISTS
FOR (n:APIDoc) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT testcase_id_unique IF NOT EXISTS
FOR (n:TestCase) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT gateapproval_id_unique IF NOT EXISTS
FOR (n:GateApproval) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT knowledgechunk_id_unique IF NOT EXISTS
FOR (n:KnowledgeChunk) REQUIRE n.id IS UNIQUE;

// ---- Indexes (lookup performance) ----

CREATE INDEX agent_type_idx IF NOT EXISTS FOR (n:Agent) ON (n.type);
CREATE INDEX agent_name_idx IF NOT EXISTS FOR (n:Agent) ON (n.name);

CREATE INDEX requirement_status_idx IF NOT EXISTS FOR (n:Requirement) ON (n.status);
CREATE INDEX requirement_priority_idx IF NOT EXISTS FOR (n:Requirement) ON (n.priority);

CREATE INDEX spec_version_idx IF NOT EXISTS FOR (n:Spec) ON (n.version);
CREATE INDEX spec_type_idx IF NOT EXISTS FOR (n:Spec) ON (n.type);

CREATE INDEX task_status_idx IF NOT EXISTS FOR (n:Task) ON (n.status);
CREATE INDEX task_agent_type_idx IF NOT EXISTS FOR (n:Task) ON (n.agent_type);

CREATE INDEX codebase_language_idx IF NOT EXISTS FOR (n:Codebase) ON (n.language);
CREATE INDEX codebase_repo_path_idx IF NOT EXISTS FOR (n:Codebase) ON (n.repo_path);
CREATE INDEX codebase_module_idx IF NOT EXISTS FOR (n:Codebase) ON (n.module);

CREATE INDEX apidoc_path_idx IF NOT EXISTS FOR (n:APIDoc) ON (n.path);
CREATE INDEX apidoc_method_idx IF NOT EXISTS FOR (n:APIDoc) ON (n.method);
CREATE INDEX apidoc_deprecated_idx IF NOT EXISTS FOR (n:APIDoc) ON (n.deprecated);

CREATE INDEX testcase_status_idx IF NOT EXISTS FOR (n:TestCase) ON (n.status);
CREATE INDEX testcase_priority_idx IF NOT EXISTS FOR (n:TestCase) ON (n.priority);

CREATE INDEX gateapproval_status_idx IF NOT EXISTS FOR (n:GateApproval) ON (n.status);
CREATE INDEX gateapproval_level_idx IF NOT EXISTS FOR (n:GateApproval) ON (n.gate_level);

CREATE INDEX knowledgechunk_project_idx IF NOT EXISTS FOR (n:KnowledgeChunk) ON (n.project);
CREATE INDEX knowledgechunk_doc_id_idx IF NOT EXISTS FOR (n:KnowledgeChunk) ON (n.doc_id);

// ---- Composite indexes for common query patterns ----

CREATE INDEX task_status_agent IF NOT EXISTS
FOR (n:Task) ON (n.status, n.agent_type);

CREATE INDEX codebase_lang_module IF NOT EXISTS
FOR (n:Codebase) ON (n.language, n.module);
