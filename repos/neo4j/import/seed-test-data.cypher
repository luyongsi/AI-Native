// ============================================================
// 需求 REQ-DEMO-001：订单批量导出 的完整知识图谱
// ============================================================

// 核心节点
CREATE (:Requirement {id: "REQ-DEMO-001", title: "订单批量导出", priority: "P0", status: "active"});
CREATE (:Spec {id: "SPEC-001", title: "订单导出接口规格", version: "1.2.0"});
CREATE (:API {id: "API-001", path: "/api/orders/export", method: "POST", description: "批量导出订单为 Excel/CSV"});
CREATE (:DataModel {name: "orders", table: "orders", description: "订单主表"});

// 前端组件
CREATE (:Component {id: "COMP-001", name: "OrderDetailPage", type: "page", framework: "React", description: "订单详情页"});
CREATE (:Component {id: "COMP-002", name: "ExportButton", type: "component", framework: "React", description: "导出按钮组件"});

// 测试用例
CREATE (:TestCase {id: "TC-001", title: "导出按钮渲染测试", type: "unit", status: "passed"});
CREATE (:TestCase {id: "TC-002", title: "批量导出 API 集成测试", type: "integration", status: "passed"});

// Agent 产出
CREATE (:Agent {id: "A7", name: "qa-bot", type: "testing"});
CREATE (:Artifact {id: "ART-001", type: "test_suite", name: "orders-export-tests", created_at: "2026-06-20"});

// 关系：需求结构
MATCH (r:Requirement {id: "REQ-DEMO-001"}), (s:Spec {id: "SPEC-001"})
CREATE (r)-[:HAS_SPEC]->(s);

MATCH (s:Spec {id: "SPEC-001"}), (a:API {id: "API-001"})
CREATE (s)-[:DEFINES]->(a);

MATCH (a:API {id: "API-001"}), (d:DataModel {name: "orders"})
CREATE (a)-[:PRODUCES]->(d);

// 关系：组件调用 API
MATCH (c1:Component {id: "COMP-001"}), (a:API {id: "API-001"})
CREATE (c1)-[:CALLS]->(a);

MATCH (c2:Component {id: "COMP-002"}), (a:API {id: "API-001"})
CREATE (c2)-[:CALLS]->(a);

// 关系：测试覆盖
MATCH (t1:TestCase {id: "TC-001"}), (c2:Component {id: "COMP-002"})
CREATE (t1)-[:COVERS]->(c2);

MATCH (t2:TestCase {id: "TC-002"}), (a:API {id: "API-001"})
CREATE (t2)-[:COVERS]->(a);

// 关系：Agent 产出
MATCH (ag:Agent {id: "A7"}), (ar:Artifact {id: "ART-001"})
CREATE (ag)-[:PRODUCED]->(ar);

MATCH (ar:Artifact {id: "ART-001"}), (t1:TestCase {id: "TC-001"})
CREATE (ar)-[:CONTAINS]->(t1);

MATCH (ar:Artifact {id: "ART-001"}), (t2:TestCase {id: "TC-002"})
CREATE (ar)-[:CONTAINS]->(t2);

// 关系：变更影响传播（API 变更 → 影响下游组件）
CREATE (:Changelog {id: "CHG-001", description: "导出接口新增 status 过滤参数", date: "2026-06-28"});

MATCH (chg:Changelog {id: "CHG-001"}), (a:API {id: "API-001"})
CREATE (chg)-[:MODIFIES]->(a);

MATCH (a:API {id: "API-001"}), (c1:Component {id: "COMP-001"})
CREATE (a)-[:AFFECTS]->(c1);

MATCH (a:API {id: "API-001"}), (c2:Component {id: "COMP-002"})
CREATE (a)-[:AFFECTS]->(c2);
