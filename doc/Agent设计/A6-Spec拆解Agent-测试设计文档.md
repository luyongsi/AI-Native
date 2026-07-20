# A6 Spec 拆解 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-17
- **参考**: [A6 开发设计文档](./A6-Spec拆解Agent-开发设计文档.md) · [A6 Spec拆解Agent完整设计](../Agent规格/A6-Spec拆解Agent完整设计.md) · [阶段三数据字典](../Agent规格/阶段三-数据字典.md)
- **测试范围**: A6 全功能验证（LLM 拆解 → DAG 验证 → Fallback → task_dags 写入 → NATS 发布 → Gate2 打回修订）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常拆解流程 + Gate2 打回修订流程
            ├──────────────┤
            │  集成测试     │  4 条：task_dags 写入 + agent_results + NATS 发布 + 修订链路
            ├──────────────┤
            │  单元测试     │  8 条：DAG 验证器、Fallback 生成器、上下文解析、LLM prompt
            ├──────────────┤
            │  边界测试     │  4 条：节点数边界、自环边、空 Spec、复杂 Spec
            └──────────────┘
```

---

## 二、单元测试（8 条）

### 2.1 DAG 验证器

**TC-A6-UNIT-001: 正常 DAG 通过验证**
```
输入:
  dag = {
    "nodes": [
      {"id": "task-01", "type": "planning", "title": "技术方案设计"},
      {"id": "task-02", "type": "backend", "title": "API 开发"},
      {"id": "task-03", "type": "frontend", "title": "前端开发"},
      {"id": "task-04", "type": "db", "title": "数据库迁移"},
      {"id": "task-05", "type": "testing", "title": "测试验证"},
      {"id": "task-06", "type": "deployment", "title": "部署上线"}
    ],
    "edges": [
      {"from": "task-01", "to": "task-02"},
      {"from": "task-01", "to": "task-03"},
      {"from": "task-02", "to": "task-05"},
      {"from": "task-03", "to": "task-05"},
      {"from": "task-04", "to": "task-05"},
      {"from": "task-05", "to": "task-06"}
    ]
  }

执行: DAGValidator().validate(dag)

预期结果:
  - valid = true
  - errors = []
```

**TC-A6-UNIT-002: 节点数 < 5 拒绝**
```
输入:
  dag = {"nodes": [3 个节点], "edges": []}

执行: DAGValidator().validate(dag)

预期结果:
  - valid = false
  - errors 包含 "Node count 3 < 5"
```

**TC-A6-UNIT-003: 节点数 > 25 拒绝**
```
输入:
  dag = {"nodes": [30 个节点], "edges": [...]}

执行: DAGValidator().validate(dag)

预期结果:
  - valid = false
  - errors 包含 "Node count 30 > 25"
```

**TC-A6-UNIT-004: 自环边检测**
```
输入:
  dag = {
    "nodes": [{"id": "task-01"}, {"id": "task-02"}],
    "edges": [{"from": "task-01", "to": "task-01"}]
  }

执行: DAGValidator().validate(dag)

预期结果:
  - valid = false
  - errors 包含 "Self-loop edge"
```

**TC-A6-UNIT-005: Edge 引用无效节点**
```
输入:
  dag = {
    "nodes": [{"id": "task-01"}, {"id": "task-02"}],
    "edges": [{"from": "task-01", "to": "task-99"}]
  }

执行: DAGValidator().validate(dag)

预期结果:
  - valid = false
  - errors 包含 "Edge to 'task-99' not in nodes"
```

### 2.2 Fallback 生成器

**TC-A6-UNIT-006: Fallback 含后端+前端+DB 关键词**
```
输入:
  spec_doc = {"modules": [{"name": "用户 API"}, {"name": "管理页面"}], "data_models": [{"name": "User"}]}

执行: FallbackDecomposer().decompose(spec_doc)

预期结果:
  - nodes 包含 planning, backend, frontend, database, integration, testing, deployment
  - dag_json.source = "fallback"
  - critical_path 包含所有节点 ID 且无重复
```

**TC-A6-UNIT-007: Fallback 仅含前端关键词**
```
输入:
  spec_doc = {"modules": [{"name": "首页"}, {"name": "设置页"}]}

执行: FallbackDecomposer().decompose(spec_doc)

预期结果:
  - nodes 包含 planning, frontend, integration, testing, deployment
  - 不包含 backend 和 database 节点
```

### 2.3 上下文解析

**TC-A6-UNIT-008: 解析含修订上下文的 context.ready.A6**
```
输入:
  context_package = {
    "req_id": "uuid-1234",
    "session_id": "uuid-5678",
    "cycle": 0,
    "spec_package": {
      "spec_doc": {"title": "测试项目", "modules": [...]},
      "openapi_schema": {"openapi": "3.0.0", "paths": {...}},
      "erd_diagram": {"entities": [...]},
      "ddl_statements": "CREATE TABLE..."
    },
    "revision_context": {
      "is_revision": true,
      "gate2_rejection": {"reject_reasons": [{"category": "dag_incomplete"}]},
      "previous_a8_report": {"score": 65}
    }
  }

执行: _parse_context(context_package)

预期结果:
  - spec_doc.title = "测试项目"
  - openapi_schema.openapi = "3.0.0"
  - revision_context.is_revision = true
  - revision_context.gate2_rejection.reject_reasons[0].category = "dag_incomplete"
```

---

## 三、集成测试（4 条）

### 3.1 task_dags 写入

**TC-A6-INT-001: 首次写入 task_dags（version=1）**
```
GIVEN: req_id 无历史 DAG 记录
WHEN: A6.execute() → _save_task_dags()
THEN:
  - task_dags 表插入一行
  - version = 1
  - dag_json 非空
  - source = 'llm' 或 'fallback'
  - node_count = len(dag.nodes)

验证 SQL:
  SELECT version, node_count, source FROM task_dags
  WHERE req_id = '<req_id>' AND cycle = 0 ORDER BY version DESC LIMIT 1;
```

**TC-A6-INT-002: Gate2 打回后 version 递增**
```
GIVEN: 已有 task_dags version=1, revision_context.is_revision=true
WHEN: A6.execute() → _save_task_dags()
THEN:
  - task_dags 表插入新行
  - version = 2
  - 旧行 (version=1) 保留

验证 SQL:
  SELECT version FROM task_dags
  WHERE req_id = '<req_id>' AND cycle = 0 ORDER BY version;
  → [1, 2]
```

### 3.2 agent_results UPSERT

**TC-A6-INT-003: 首次写入 agent_results (A6)**
```
GIVEN: req_id 无 A6 记录
WHEN: A6.execute()
THEN:
  - agent_results 表插入一行
  - agent_key = 'A6'
  - status = 'completed'
  - artifact 含 node_count, version, source, critical_path_length

验证 SQL:
  SELECT agent_key, status, artifact->>'node_count' as node_count
  FROM agent_results WHERE req_id = '<req_id>' AND cycle = 0 AND agent_key = 'A6';
```

**TC-A6-INT-004: 同 cycle 修订时 UPSERT 覆盖**
```
步骤 1: A6 首次执行 → agent_results INSERT (cycle=0)
步骤 2: Gate2 reject → A6 再次执行 (同 cycle=0)
THEN:
  - agent_results 仅 1 行（非 2 行）
  - artifact.version = 2
  - updated_at > created_at

验证 SQL:
  SELECT COUNT(*) FROM agent_results WHERE req_id = '<req_id>' AND cycle = 0 AND agent_key = 'A6';
  → 1
```

---

## 四、边界测试（4 条）

**TC-A6-EDGE-001: 空 Spec → Fallback**
```
GIVEN: spec_doc = {"title": "测试项目"}（无 modules, 无 data_models）
WHEN: A6.execute() with LLM returning None
THEN:
  - dag.source = "fallback"
  - nodes 长度 ≥ 5
  - 包含 planning, integration, testing, deployment 基础模板
```

**TC-A6-EDGE-002: LLM 不可用 → Fallback**
```
GIVEN: spec_complete.json, call_llm() 抛出 ConnectionError
WHEN: A6.execute()
THEN:
  - dag.source = "fallback"
  - agent_results.status = 'completed'（不是 'empty'）
  - task_dags 成功写入
```

**TC-A6-EDGE-003: 复杂 Spec (15 模块) → 节点数限制**
```
GIVEN: spec_large.json（15 个模块 + 20+ API 端点 + 12 个实体）
WHEN: A6.execute() → LLM 拆解 → 验证
THEN:
  - nodes ≤ 25
  - edges 数量合理（≤ nodes × 2）
  - 无孤岛节点
  - critical_path 不包含重复节点
```

**TC-A6-EDGE-004: DAG 验证失败 → 自动 Fallback**
```
GIVEN: Mock LLM 返回只有 3 个节点的 DAG
WHEN: _validate_dag() → validation.valid = false
THEN:
  - 自动回退到 _fallback_decompose()
  - dag.source = "fallback"
  - 不写入非法 DAG
  - 最终 task_dags 含 fallback 产出的 5+ 节点 DAG
```

---

## 五、E2E 端到端测试（2 条）

**TC-A6-E2E-001: 完整拆解流程**
```
流程:
  context.ready.A6 (spec_complete.json)
    → _parse_context (spec_package 解析)
    → _decompose_with_llm (DeepSeek API)
    → _validate_dag (通过)
    → _save_task_dags (version=1)
    → _upsert_agent_results (status='completed')
    → _publish_agent_result_a6 (NATS JetStream)
    → _publish_dag_created (NATS JetStream)
    → msg.ack()

验证点:
  - task_dags 表 1 行 (version=1, source='llm')
  - agent_results 表 1 行 (agent_key='A6', status='completed')
  - NATS agent.result.A6 发布成功（含 Nats-Msg-Id header）
  - NATS dag.created 发布成功（含 Nats-Msg-Id header）
  - 消息被 ack（非 nak/term）
```

**TC-A6-E2E-002: Gate2 打回修订流程**
```
流程:
  Gate2 reject (a6_rework=true)
    → context.ready.A6 (revision_context.is_revision=true)
    → _decompose_with_llm (注入 revision_context 到 prompt)
    → _validate_dag (通过)
    → _save_task_dags (version=2, 同一 cycle)
    → _upsert_agent_results (同 cycle UPSERT 覆盖)
    → agent.result.A6 (同 cycle)

验证点:
  - cycle 始终为 0（不递增）
  - tech_prep_revision_count 从 0 → 1
  - task_dags version = 2
  - agent_results 同 cycle 仅 1 行，artifact.version=2
  - LLM prompt 包含 "修正指引" 和 gate2_rejection
```

---

## 六、测试数据准备

### 6.1 fixtures 目录

```
tests/fixtures/
├── spec_complete.json           # 完整 Spec（5 模块 + 8 API + 4 实体）
├── spec_empty.json              # 空 Spec（仅标题）
├── spec_large.json              # 复杂 Spec（15 模块 + 20 API + 12 实体）
├── dag_valid_10nodes.json       # 合法 DAG（10 节点，12 边）
├── dag_cyclic.json              # 含循环依赖的 DAG
├── dag_3nodes.json              # 仅 3 节点（边界-少）
├── dag_30nodes.json             # 30 节点（边界-多）
├── dag_self_loop.json           # 含自环边
├── dag_invalid_ref.json         # Edge 引用不存在节点
├── context_ready_a6.json        # 完整的 context.ready.A6 payload
├── context_ready_a6_revision.json  # 含 revision_context 的 payload
└── a8_review_fail.json          # A8 fail 评审报告（用于修订上下文）
```

### 6.2 conftest.py 核心 Fixture

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
def mock_llm_return_dag():
    """Mock DeepSeek API 返回合法 DAG JSON"""
    async def _mock(prompt, **kwargs):
        with open("tests/fixtures/dag_valid_10nodes.json") as f:
            dag = json.load(f)
        return json.dumps(dag)
    return _mock

@pytest.fixture
def mock_llm_return_none():
    """Mock DeepSeek API 返回 None（不可用）"""
    return AsyncMock(return_value=None)

@pytest.fixture
def mock_llm_return_3nodes():
    """Mock DeepSeek API 返回 3 节点 DAG（验证失败边界）"""
    async def _mock(prompt, **kwargs):
        with open("tests/fixtures/dag_3nodes.json") as f:
            dag = json.load(f)
        return json.dumps(dag)
    return _mock

@pytest.fixture
def spec_complete():
    """加载完整 Spec fixture"""
    with open("tests/fixtures/spec_complete.json") as f:
        return json.load(f)

@pytest.fixture
def spec_empty():
    """加载空 Spec fixture"""
    with open("tests/fixtures/spec_empty.json") as f:
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

## 七、测试用例索引

| 编号 | 分类 | 描述 | 预期 |
|------|------|------|------|
| TC-A6-UNIT-001 | 单元-DAG验证 | 正常 DAG 通过验证 | valid=true |
| TC-A6-UNIT-002 | 单元-DAG验证 | 节点数 < 5 拒绝 | valid=false, "Node count 3 < 5" |
| TC-A6-UNIT-003 | 单元-DAG验证 | 节点数 > 25 拒绝 | valid=false, "Node count 30 > 25" |
| TC-A6-UNIT-004 | 单元-DAG验证 | 自环边检测 | valid=false, "Self-loop edge" |
| TC-A6-UNIT-005 | 单元-DAG验证 | Edge 引用无效节点 | valid=false |
| TC-A6-UNIT-006 | 单元-Fallback | Fallback 含全类型关键词 | 7 种节点类型 |
| TC-A6-UNIT-007 | 单元-Fallback | Fallback 仅前端关键词 | 5 种节点类型，不含 backend/db |
| TC-A6-UNIT-008 | 单元-上下文 | 修订上下文解析 | is_revision=true |
| TC-A6-INT-001 | 集成-DB | 首次写入 task_dags | version=1 |
| TC-A6-INT-002 | 集成-DB | Gate2 打回 version 递增 | version=2 |
| TC-A6-INT-003 | 集成-DB | agent_results UPSERT | agent_key='A6', status='completed' |
| TC-A6-INT-004 | 集成-DB | 同 cycle UPSERT 覆盖 | 1 行, version=2 |
| TC-A6-EDGE-001 | 边界 | 空 Spec → Fallback | source=fallback, nodes≥5 |
| TC-A6-EDGE-002 | 边界 | LLM 不可用 → Fallback | source=fallback, 不崩溃 |
| TC-A6-EDGE-003 | 边界 | 复杂 Spec 节点数限制 | nodes≤25, 无孤岛 |
| TC-A6-EDGE-004 | 边界 | DAG 验证失败自动 Fallback | 不写入非法 DAG |
| TC-A6-E2E-001 | E2E | 完整拆解流程 | task_dags + agent_results + NATS |
| TC-A6-E2E-002 | E2E | Gate2 打回修订 | version=2, cycle 不变 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-17
**版本**: v1.0
