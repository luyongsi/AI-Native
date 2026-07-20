# A8 架构评审 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-17
- **参考**: [A8 开发设计文档](./A8-架构评审Agent-开发设计文档.md) · [A8 架构评审Agent完整设计](../Agent规格/A8-架构评审Agent完整设计.md) · [阶段三数据字典](../Agent规格/阶段三-数据字典.md)
- **测试范围**: A8 全功能验证（静态分析 → LLM 评审 → 评分合并 → NATS 发布 → A6↔A8 对抗循环）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常评审 pass + A6↔A8 对抗修订
            ├──────────────┤
            │  集成测试     │  3 条：agent_results 写入 + NATS 发布 + 评审结果完整链路
            ├──────────────┤
            │  单元测试     │  11 条：循环检测、分层违规、DB 回滚、评分判定、LLM/Fallback
            ├──────────────┤
            │  边界测试     │  3 条：空 DAG、评分边界、循环+违规组合
            └──────────────┘
```

---

## 二、单元测试（11 条）

### 2.1 循环依赖检测

**TC-A8-UNIT-001: 直接互指边 — 检测到循环**
```
输入:
  nodes = [{"id": "task-01"}, {"id": "task-02"}]
  edges = [{"from": "task-01", "to": "task-02"}, {"from": "task-02", "to": "task-01"}]

执行: _check_cycles(nodes, edges)

预期结果:
  - cycle_detected = true
  - cycle_path = ["task-01", "task-02", "task-01"] 或 ["task-02", "task-01", "task-02"]
```

**TC-A8-UNIT-002: 多跳环 — 三节点环**
```
输入:
  nodes = [{"id": "task-01"}, {"id": "task-02"}, {"id": "task-03"}]
  edges = [
    {"from": "task-01", "to": "task-02"},
    {"from": "task-02", "to": "task-03"},
    {"from": "task-03", "to": "task-01"}
  ]

执行: _check_cycles(nodes, edges)

预期结果:
  - cycle_detected = true
  - cycle_path 长度 = 4（三节点 + 重复起点）
```

**TC-A8-UNIT-003: 无循环的正常 DAG**
```
输入:
  nodes = [{"id": "task-01"}, {"id": "task-02"}, {"id": "task-03"}, {"id": "task-04"}]
  edges = [
    {"from": "task-01", "to": "task-02"},
    {"from": "task-01", "to": "task-03"},
    {"from": "task-02", "to": "task-04"},
    {"from": "task-03", "to": "task-04"}
  ]

执行: _check_cycles(nodes, edges)

预期结果:
  - cycle_detected = false
  - cycle_path = []
```

**TC-A8-UNIT-004: DAG 分叉合并无环**
```
输入:
  nodes = [{"id": "task-01"}, {"id": "task-02"}, {"id": "task-03"}, {"id": "task-04"}, {"id": "task-05"}]
  edges = [
    {"from": "task-01", "to": "task-02"},
    {"from": "task-01", "to": "task-03"},
    {"from": "task-02", "to": "task-04"},
    {"from": "task-03", "to": "task-04"},
    {"from": "task-04", "to": "task-05"}
  ]

执行: _check_cycles(nodes, edges)

预期结果:
  - cycle_detected = false
```

### 2.2 分层违规检测

**TC-A8-UNIT-005: 前端直接依赖 DB → critical**
```
输入:
  nodes = [{"id": "task-01", "type": "frontend"}, {"id": "task-02", "type": "db"}]
  edges = [{"from": "task-01", "to": "task-02"}]

执行: _check_layer_violations(nodes, edges)

预期结果:
  - violations 含 LAYER-VIO-001
  - severity = "critical"
  - affected_nodes = ["task-01", "task-02"]
  - suggestion 建议通过 API 间接访问
```

**TC-A8-UNIT-006: DB 依赖前端 → warning**
```
输入:
  nodes = [{"id": "task-01", "type": "db"}, {"id": "task-02", "type": "frontend"}]
  edges = [{"from": "task-01", "to": "task-02"}]

执行: _check_layer_violations(nodes, edges)

预期结果:
  - violations 含 LAYER-VIO-002
  - severity = "warning"
  - affected_nodes = ["task-01", "task-02"]
```

**TC-A8-UNIT-007: 正常分层 frontend→backend→db → 无违规**
```
输入:
  nodes = [{"id": "task-01", "type": "frontend"}, {"id": "task-02", "type": "backend"}, {"id": "task-03", "type": "db"}]
  edges = [
    {"from": "task-01", "to": "task-02"},
    {"from": "task-02", "to": "task-03"}
  ]

执行: _check_layer_violations(nodes, edges)

预期结果:
  - violations = []
```

### 2.3 DB 回滚检查

**TC-A8-UNIT-008: DB 节点无回滚步骤 → warning**
```
输入:
  nodes = [{"id": "task-01", "type": "db", "steps": ["创建 users 表", "添加索引"]}]

执行: _check_db_rollback(nodes)

预期结果:
  - issues 含 DB-ROLLBACK-001
  - severity = "warning"
  - affected_nodes = ["task-01"]
  - suggestion 建议补充反向 migration
```

**TC-A8-UNIT-009: DB 节点有回滚步骤 → 通过**
```
输入:
  nodes = [{"id": "task-01", "type": "db",
    "steps": ["创建 users 表", "回滚: DROP TABLE users"]}]

执行: _check_db_rollback(nodes)

预期结果:
  - issues = []
```

### 2.4 评分与判定

**TC-A8-UNIT-010: 评分 ≥ 70 且无循环 → pass**
```
GIVEN: score=85, cycle_detected=false, layer_violations=[], db_issues=[]
WHEN: verdict 判定逻辑执行
THEN:
  - verdict = "pass"
  - gate2_required = false
```

**TC-A8-UNIT-011: 评分 < 70 → fail**
```
GIVEN: score=65, cycle_detected=false, layer_violations=[], db_issues=[]
WHEN: verdict 判定逻辑执行
THEN:
  - verdict = "fail"
  - gate2_required = true
```

---

## 三、集成测试（3 条）

**TC-A8-INT-001: agent_results 写入验证**
```
GIVEN: A8 评审完成，verdict=pass, score=85
WHEN: _upsert_agent_results(req_id, "A8", cycle, "completed", {"review": summary})

验证 SQL:
  SELECT agent_key, status, artifact->'review'->>'verdict' as verdict,
         artifact->'review'->>'score' as score
  FROM agent_results WHERE req_id = '<req_id>' AND cycle = 0 AND agent_key = 'A8';

预期结果:
  - agent_key = 'A8'
  - status = 'completed'
  - verdict = 'pass'
  - score = '85'
```

**TC-A8-INT-002: 空 DAG 时 status='skipped'**
```
GIVEN: dag.nodes = [], dag.edges = []
WHEN: A8.execute()
THEN:
  - agent_results.status = 'skipped'
  - agent_results.artifact.reason = 'empty_dag'
  - agent.result.A8 发布 verdict='skipped', gate2_required=true
```

**TC-A8-INT-003: 循环依赖强制 fail + 扣 30 分**
```
GIVEN: DAG 含循环依赖 (task-01→task-02→task-01), LLM 评审 score=90
WHEN: 评分合并逻辑执行
THEN:
  - score = 60 (90 - 30)
  - verdict = "fail"（score < 70）
  - gate2_required = true
  - checks.cycle_dependency.passed = false
  - violations 含 DAG-CYCLE-001 (severity=critical)
```

---

## 四、边界测试（3 条）

**TC-A8-EDGE-001: 空 DAG → 跳过评审**
```
GIVEN: dag = {"nodes": [], "edges": []}
WHEN: A8.execute()
THEN:
  - status = 'skipped'
  - reason = 'empty_dag'
  - 不执行 _check_cycles / _check_layer_violations / _check_db_rollback
  - agent.result.A8 verdict='skipped', gate2_required=true
```

**TC-A8-EDGE-002: 评分恰好 70 — 边界 pass**
```
GIVEN: score=70, cycle_detected=false, 无静态违规
WHEN: verdict 判定
THEN:
  - verdict = "pass"（score ≥ 70）
  - gate2_required = false
```

**TC-A8-EDGE-003: 循环 + 分层违规 + 低分 — 组合判定**
```
GIVEN: cycle_detected=true, layer_violations=2 项, db_issues=1 项, LLM score=75
WHEN: 评分合并
THEN:
  - score = max(75 - 30, 0) = 45
  - verdict = "fail"
  - violations 共包含: DAG-CYCLE-001 + 2×LAYER-VIO + 1×DB-ROLLBACK + LLM violations
```

---

## 五、LLM 评审测试（2 条）

**TC-A8-LLM-001: LLM 评审正常返回**
```
GIVEN: DAG 正常 8 节点无循环
WHEN: _llm_review() 执行 (mock LLM 返回完整评审 JSON)
THEN:
  - review 包含 score, violations, suggestions, summary
  - score ∈ [0, 100]
  - violations 数组可空（无违规时）
  - suggestions 数组非空
```

**TC-A8-LLM-002: LLM 不可用 → Fallback 仅静态分析**
```
GIVEN: call_llm() 返回 None
WHEN: _llm_review() 返回 None → _fallback_review()
THEN:
  - review.score 基于静态分析计算
  - review.violations 仅含静态分析违规
  - review.summary 包含 "[Fallback]" 标记
  - 评分规则: 100 - 循环扣 30 - 分层违规 × 10 - DB 回滚 × 5
```

---

## 六、E2E 端到端测试（2 条）

**TC-A8-E2E-001: 完整评审 pass 流程**
```
流程:
  context.ready.A8 (dag_valid_8nodes.json)
    → 空 DAG 检查 (通过)
    → _check_cycles (无循环)
    → _check_layer_violations (无违规)
    → _check_db_rollback (无问题)
    → _llm_review (score=85, 2 suggestions)
    → 合并报告 (score=85, verdict=pass)
    → _upsert_agent_results (agent_key='A8', status='completed')
    → _publish_agent_result_a8 (NATS JetStream)
    → msg.ack()

验证点:
  - agent_results 表 1 行 (agent_key='A8', status='completed')
  - artifact.review.verdict = 'pass'
  - artifact.review.score = 85
  - artifact.review.gate2_required = false
  - NATS agent.result.A8 发布成功（含 Nats-Msg-Id header）
```

**TC-A8-E2E-002: 循环依赖 → fail → Gate2 裁决**
```
流程:
  context.ready.A8 (dag_cyclic.json)
    → _check_cycles (检测到 task-01→task-02→task-01)
    → _check_layer_violations (1 项 LAYER-VIO-001)
    → _check_db_rollback (1 项 DB-ROLLBACK-001)
    → _llm_review (score=75, 安全问题 1 项)
    → 合并报告 (score=75-30=45, verdict=fail)
    → _publish_agent_result_a8

验证点:
  - verdict = 'fail'
  - gate2_required = true
  - score = 45
  - violations 共 4 项 (DAG-CYCLE-001 + LAYER-VIO-001 + DB-ROLLBACK-001 + SEC-001)
  - checks.cycle_dependency.passed = false
  - checks.layer_violation.passed = false
  - checks.db_rollback.passed = false
  - checks.security_risk.passed = false
```

---

## 七、测试数据准备

### 7.1 fixtures 目录

```
tests/fixtures/
├── dag_valid_8nodes.json        # 合法 DAG（8 节点，10 边，无循环）
├── dag_cyclic_direct.json       # 直接互指循环 (task-01↔task-02)
├── dag_cyclic_multihop.json     # 多跳循环 (task-01→02→03→01)
├── dag_fork_merge.json          # 分叉合并 DAG（无循环）
├── dag_layer_violation.json     # 含分层违规 (frontend→db)
├── dag_no_rollback.json         # DB 节点无回滚
├── dag_with_rollback.json       # DB 节点有回滚
├── dag_empty.json               # 空 DAG
├── context_ready_a8.json        # 完整的 context.ready.A8 payload
├── context_ready_a8_cyclic.json # 含循环 DAG 的 payload
├── context_ready_a8_empty.json  # 空 DAG payload
├── llm_review_pass.json         # Mock LLM 返回 pass 评审
├── llm_review_fail.json         # Mock LLM 返回 fail 评审
└── a8_review_pass.json          # A8 pass 评审完整报告
```

### 7.2 conftest.py 核心 Fixture

```python
import pytest
import json
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_nats():
    """Mock NATS JetStream context"""
    js = AsyncMock()
    js.publish = AsyncMock()
    js.subscribe = AsyncMock()
    return js

@pytest.fixture
def mock_llm_review_pass():
    """Mock DeepSeek API 返回 pass 评审报告"""
    async def _mock(prompt, **kwargs):
        return json.dumps({
            "score": 85,
            "violations": [],
            "suggestions": ["建议增加缓存层", "考虑水平扩展方案"],
            "summary": "架构设计合理，分层清晰，无安全或性能隐患"
        })
    return _mock

@pytest.fixture
def mock_llm_review_fail():
    """Mock DeepSeek API 返回 fail 评审报告"""
    async def _mock(prompt, **kwargs):
        return json.dumps({
            "score": 55,
            "violations": [
                {"rule": "SEC-001", "severity": "critical", "title": "缺少认证机制",
                 "detail": "API 接口未包含认证/授权步骤", "suggestion": "添加 JWT 认证中间件", "affected_nodes": ["task-02"]},
                {"rule": "COUP-001", "severity": "medium", "title": "模块耦合过高",
                 "detail": "...", "suggestion": "...", "affected_nodes": ["task-02", "task-03"]}
            ],
            "suggestions": ["修复安全问题后重新提交"],
            "summary": "存在严重安全隐患，需要修订"
        })
    return _mock

@pytest.fixture
def mock_llm_failure():
    """Mock DeepSeek API 返回失败"""
    return AsyncMock(return_value=None)

@pytest.fixture
def dag_valid():
    """加载合法 DAG fixture"""
    with open("tests/fixtures/dag_valid_8nodes.json") as f:
        return json.load(f)

@pytest.fixture
def dag_cyclic():
    """加载循环 DAG fixture"""
    with open("tests/fixtures/dag_cyclic_direct.json") as f:
        return json.load(f)

@pytest.fixture
def dag_empty():
    """加载空 DAG fixture"""
    with open("tests/fixtures/dag_empty.json") as f:
        return json.load(f)

@pytest.fixture
async def test_db():
    """测试数据库连接（事务回滚）"""
    import asyncpg
    conn = await asyncpg.connect(
        host="localhost", port=5432,
        database="ai_native_test",
        user="ai_native_test",
        password="ai_native_test",
    )
    await conn.execute("BEGIN")
    yield conn
    await conn.execute("ROLLBACK")
    await conn.close()
```

---

## 八、违规规则测试覆盖矩阵

| 规则 ID | 测试用例 | 来源 | 覆盖状态 |
|---------|---------|------|---------|
| `DAG-CYCLE-001` | TC-A8-UNIT-001, 002, E2E-002 | 静态分析 | ✅ |
| `LAYER-VIO-001` | TC-A8-UNIT-005 | 静态分析 | ✅ |
| `LAYER-VIO-002` | TC-A8-UNIT-006 | 静态分析 | ✅ |
| `DB-ROLLBACK-001` | TC-A8-UNIT-008, E2E-002 | 静态分析 | ✅ |
| `SEC-001` | TC-A8-LLM-001, E2E-002 | LLM 评审 (P1) | ✅ |
| `SEC-002` | TC-A8-LLM-001 | LLM 评审 (P1) | 间接覆盖 |
| `PERF-001` | TC-A8-LLM-001 | LLM 评审 (P1) | 间接覆盖 |
| `COUP-001` | TC-A8-LLM-001 | LLM 评审 (P1) | 间接覆盖 |

---

## 九、测试用例索引

| 编号 | 分类 | 描述 | 关键验证点 |
|------|------|------|-----------|
| TC-A8-UNIT-001 | 单元-循环 | 直接互指边检测 | cycle_detected=true |
| TC-A8-UNIT-002 | 单元-循环 | 三节点多跳环 | cycle_path 长度=4 |
| TC-A8-UNIT-003 | 单元-循环 | 正常 DAG 无环 | cycle_detected=false |
| TC-A8-UNIT-004 | 单元-循环 | 分叉合并 DAG 无环 | cycle_detected=false |
| TC-A8-UNIT-005 | 单元-分层 | frontend→db 跨层 | LAYER-VIO-001, critical |
| TC-A8-UNIT-006 | 单元-分层 | db→frontend 反向 | LAYER-VIO-002, warning |
| TC-A8-UNIT-007 | 单元-分层 | 正常分层无违规 | violations=[] |
| TC-A8-UNIT-008 | 单元-DB | 无回滚步骤 | DB-ROLLBACK-001, warning |
| TC-A8-UNIT-009 | 单元-DB | 有回滚步骤 | issues=[] |
| TC-A8-UNIT-010 | 单元-评分 | score≥70 无循环→pass | gate2_required=false |
| TC-A8-UNIT-011 | 单元-评分 | score<70→fail | gate2_required=true |
| TC-A8-INT-001 | 集成-DB | agent_results 写入 | verdict=pass, score=85 |
| TC-A8-INT-002 | 集成-DB | 空 DAG skipped | status=skipped |
| TC-A8-INT-003 | 集成-评分 | 循环扣 30 分 | score=60, verdict=fail |
| TC-A8-EDGE-001 | 边界 | 空 DAG | 跳过评审 |
| TC-A8-EDGE-002 | 边界 | 评分=70 边界 | verdict=pass |
| TC-A8-EDGE-003 | 边界 | 循环+分层+低分组合 | score=45, 4 violations |
| TC-A8-LLM-001 | LLM | LLM 正常返回 | score∈[0,100] |
| TC-A8-LLM-002 | LLM | LLM 不可用 fallback | [Fallback] 标记 |
| TC-A8-E2E-001 | E2E | 完整评审 pass | agent.result.A8, gate2_required=false |
| TC-A8-E2E-002 | E2E | 循环→fail→Gate2 | verdict=fail, gate2_required=true |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-17
**版本**: v1.0
