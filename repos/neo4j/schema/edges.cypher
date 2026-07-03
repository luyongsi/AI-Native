// ============================================================
// Phase 6C: Neo4j Knowledge Graph — Relationship Definitions & Indexes
// ============================================================
// Defines all relationship types for the AI-Native Development Platform.
// Run this AFTER nodes.cypher.

// ---- Relationship-property indexes (where useful for traversal) ----

// DEPENDS_ON carries metadata about the dependency nature
// Usage: (a:Task)-[:DEPENDS_ON {type: "blocks", critical: true}]->(b:Task)

// GENERATES captures which agent produced which artifact
// Usage: (a:Agent)-[:GENERATES {timestamp: datetime(), version: "1.0"}]->(s:Spec)

// REVIEWS links an agent to a gate approval they reviewed
// Usage: (a:Agent)-[:REVIEWS {timestamp: datetime(), verdict: "approved"}]->(g:GateApproval)

// REFERENCES connects specs/tasks to knowledge or API docs
// Usage: (s:Spec)-[:REFERENCES {section: "auth"}]->(k:KnowledgeChunk)

// TESTED_BY links a task to its test case(s)
// Usage: (t:Task)-[:TESTED_BY {coverage: "full"}]->(tc:TestCase)

// GATED_BY links a requirement to its gate approval
// Usage: (r:Requirement)-[:GATED_BY {gate_name: "design_review"}]->(g:GateApproval)

// CONTAINS represents hierarchical nesting
// Usage: (s:Spec)-[:CONTAINS {order: 1}]->(a:APIDoc)
//        (parent:Codebase)-[:CONTAINS {type: "subpackage"}]->(child:Codebase)

// IMPACTS captures traceability from specs to tasks/code
// Usage: (s:Spec)-[:IMPACTS {severity: "high", change_type: "breaking"}]->(t:Task)

// PRODUCED_FROM links artifacts back to originating requirements
// Usage: (a:Spec)-[:PRODUCED_FROM {version: "1.0"}]->(r:Requirement)

// ---- Relationship-existence indexes (fast path traversal) ----

// (No CREATE INDEX for relationship properties in Neo4j 5 Community;
//  relationship-property indexes require Enterprise edition.
//  Instead, we rely on node-label indexes + direction filtering.)

// ---- Standard relationship patterns (documented for tooling) ----

// Pattern                              | Source Node    | Target Node     | Cardinality
// -------------------------------------|----------------|-----------------|------------
// (:Task)-[:DEPENDS_ON]->(:Task)       | Task           | Task            | many-to-many
// (:Agent)-[:DEPENDS_ON]->(:Agent)     | Agent          | Agent           | many-to-many
// (:Agent)-[:GENERATES]->(:Spec)       | Agent          | Spec            | one-to-many
// (:Agent)-[:GENERATES]->(:Task)       | Agent          | Task            | one-to-many
// (:Agent)-[:GENERATES]->(:TestCase)   | Agent          | TestCase        | one-to-many
// (:Agent)-[:REVIEWS]->(:GateApproval) | Agent          | GateApproval    | many-to-many
// (:Spec)-[:REFERENCES]->(:KnowledgeChunk) | Spec       | KnowledgeChunk  | many-to-many
// (:Task)-[:REFERENCES]->(:APIDoc)     | Task           | APIDoc          | many-to-many
// (:Task)-[:TESTED_BY]->(:TestCase)    | Task           | TestCase        | one-to-many
// (:Requirement)-[:GATED_BY]->(:GateApproval) | Req     | GateApproval    | one-to-many
// (:Spec)-[:CONTAINS]->(:APIDoc)       | Spec           | APIDoc          | one-to-many
// (:Codebase)-[:CONTAINS]->(:Codebase) | Codebase       | Codebase        | one-to-many
// (:Spec)-[:IMPACTS]->(:Task)          | Spec           | Task            | many-to-many
// (:Spec)-[:IMPACTS]->(:Codebase)      | Spec           | Codebase        | many-to-many
// (:Artifact)-[:PRODUCED_FROM]->(:Requirement) | Artifact | Requirement  | many-to-one

// ---- Helper: create a composite lookup index on Task for
//     the common "find tasks impacted by spec" pattern ----

CREATE INDEX task_id_status IF NOT EXISTS
FOR (n:Task) ON (n.id, n.status);
