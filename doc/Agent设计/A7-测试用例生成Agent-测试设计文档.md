# A7 测试用例生成 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-17
- **参考**: [A7 开发设计文档](./A7-测试用例生成Agent-开发设计文档.md) · [A7 测试用例生成Agent完整设计](../Agent规格/A7-测试用例生成Agent完整设计.md) · [阶段三数据字典](../Agent规格/阶段三-数据字典.md)
- **测试范围**: A7 全功能验证（dag_preview 双模式 → LLM 生成 → Fallback → test_assets 写入 → MC Backend → VisAgent → NATS 发布 → Gate2 打回修订）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常生成流程 + Gate2 打回修订流程
            ├──────────────┤
            │  集成测试     │  5 条：test_assets 写入 + MC Backend + VisAgent + NATS + 修订
            ├──────────────┤
            │  单元测试     │  9 条：DAG 覆盖计算、资产组织、Fallback、dag_preview 双模式
            ├──────────────┤
            │  容错测试     │  3 条：LLM 不可用、MC Backend 不可用、JSON 解析失败
            └──────────────┘
```

---

## 二、单元测试（9 条）

### 2.1 DAG 覆盖计算

**TC-A7-UNIT-001: dag_available=true 时计算覆盖**
```
输入:
  test_cases = [
    {"case_id": "TC-001", "node_id": "task-01", "title": "测试1", "type": "unit"},
    {"case_id": "TC-002", "node_id": "task-01", "title": "测试2", "type": "api"},
    {"case_id": "TC-003", "node_id": "task-02", "title": "测试3", "type": "e2e"},
    {"case_id": "TC-004", "node_id": null, "title": "测试4", "type": "unit"}
  ]
  dag_nodes = [{"id": "task-01"}, {"id": "task-02"}, {"id": "task-03"}]

执行: _calculate_dag_coverage(test_cases, dag_nodes, dag_available=True)

预期结果:
  - total_dag_nodes = 3
  - covered_nodes = 2 (task-01, task-02)
  - uncovered_nodes = ["task-03"]
  - dag_available = true
```

**TC-A7-UNIT-002: dag_available=false 时跳过覆盖计算**
```
输入:
  test_cases = [15 条用例]
  dag_nodes = []
  dag_available = False

执行: _calculate_dag_coverage(test_cases, dag_nodes, False)

预期结果:
  - total_dag_nodes = 0
  - covered_nodes = 0
  - uncovered_nodes = []
  - dag_available = false
```

### 2.2 资产组织

**TC-A7-UNIT-003: 按类型分组测试用例**
```
输入:
  test_cases = [
    {"case_id": "TC-001", "type": "unit", "priority": "P1"},
    {"case_id": "TC-002", "type": "unit", "priority": "P2"},
    {"case_id": "TC-003", "type": "integration", "priority": "P0"},
    {"case_id": "TC-004", "type": "e2e", "priority": "P0"},
    {"case_id": "TC-005", "type": "visual", "priority": "P1"},
    {"case_id": "TC-006", "type": "api", "priority": "P1"}
  ]

执行: _organize_test_assets(test_cases)

预期结果:
  - unit_tests 长度 = 2
  - integration_tests 长度 = 2 (api 类型归入 integration)
  - e2e_tests 长度 = 1
  - visual_tests 长度 = 1
  - priority_distribution = {"P0": 2, "P1": 3, "P2": 1, "P3": 0}
  - coverage_targets.overall = 0.8
```

**TC-A7-UNIT-004: 测试用例结构验证**
```
输入:
  test_cases = [{"case_id": "TC-001", "title": "正常登录", "type": "unit",
    "priority": "P1", "steps": [
      {"step_number": 1, "action": "输入正确用户名密码", "expected": "登录成功"},
      {"step_number": 2, "action": "验证 token", "expected": "返回 JWT token"}
    ]}]

执行: _organize_test_assets(test_cases) → _save_to_postgres

验证:
  - unit_tests[0].title = "正常登录"
  - unit_tests[0].steps[0].step_number = 1
  - unit_tests[0].steps[0].action 非空
  - unit_tests[0].steps[0].expected 非空
```

### 2.3 Fallback 生成

**TC-A7-UNIT-005: Fallback 按 DAG 节点类型生成**
```
输入:
  dag_nodes = [
    {"id": "task-01", "type": "backend", "title": "API 开发"},
    {"id": "task-02", "type": "frontend", "title": "前端开发"},
    {"id": "task-03", "type": "db", "title": "数据库迁移"}
  ]

执行: _fallback_generate(dag_nodes)

预期结果:
  - 总用例数 = 6（每个节点 2 条）
  - backend 节点 → unit + api 类型
  - frontend 节点 → e2e + visual 类型
  - db 节点 → integration + unit 类型
  - 每条用例 source = "fallback"
  - 每条用例 node_id 对应 dag node
```

**TC-A7-UNIT-006: Fallback 无 DAG 节点时生成基础用例**
```
输入:
  dag_nodes = []

执行: _fallback_generate([])

预期结果:
  - 总用例数 ≥ 6（基础 backend + frontend + db 模板 × 2）
  - 所有用例 node_id 对应自动生成的模板节点
```

### 2.4 dag_preview 双模式

**TC-A7-UNIT-007: DAG 可用时在 prompt 中注入 DAG 节点**
```
GIVEN: dag_available=true, dag_nodes=[8 个节点]
WHEN: _generate_with_llm() 构建 prompt
THEN:
  - prompt 包含 "DAG 任务节点"
  - prompt 包含 "每个 DAG 节点至少 2 条测试用例"
  - prompt 包含 "node_id 字段填写对应的 DAG 节点 ID"
```

**TC-A7-UNIT-008: DAG 不可用时 prompt 指示独立生成**
```
GIVEN: dag_available=false, dag_nodes=[]
WHEN: _generate_with_llm() 构建 prompt
THEN:
  - prompt 包含 "DAG 尚未生成"
  - prompt 包含 "不需要填写 node_id 字段"
  - prompt 包含 "生成覆盖核心功能的基础用例集"
```

### 2.5 修订上下文

**TC-A7-UNIT-009: 修订模式下 prompt 包含 Gate2 拒绝原因**
```
GIVEN: revision_context = {
  "is_revision": true,
  "gate2_rejection": {
    "reject_reasons": [{"category": "test_insufficient", "description": "测试覆盖不足"}],
    "revision_guidance": "请增加边界测试和异常用例"
  }
}
WHEN: _generate_with_llm() 构建 prompt
THEN:
  - prompt 包含 "修正指引"
  - prompt 包含 "test_insufficient"
  - prompt 包含 "请增加边界测试和异常用例"
```

---

## 三、集成测试（5 条）

### 3.1 test_assets 写入

**TC-A7-INT-001: 首次写入 test_assets（version=1）**
```
GIVEN: req_id 无历史 test_assets 记录
WHEN: A7.execute() → _save_to_postgres()
THEN:
  - test_assets 表插入一行
  - version = 1
  - unit_tests/integration_tests/e2e_tests/visual_tests 均为 JSONB 非空
  - total_cases = sum of all type arrays
  - priority_distribution 总和 = total_cases

验证 SQL:
  SELECT version, total_cases,
    jsonb_array_length(unit_tests) as ut_count,
    jsonb_array_length(integration_tests) as it_count,
    jsonb_array_length(e2e_tests) as e2e_count,
    jsonb_array_length(visual_tests) as vt_count
  FROM test_assets WHERE req_id = '<req_id>' ORDER BY version DESC LIMIT 1;
```

**TC-A7-INT-002: 版本递增（同 req 两次执行）**
```
步骤 1: A7 首次执行 → test_assets version=1
步骤 2: A7 再次执行（同一 req）

验证 SQL:
  SELECT version FROM test_assets WHERE req_id = '<req_id>' ORDER BY version;
  → [1, 2]

THEN: 旧版本保留，两行数据完整
```

### 3.2 MC Backend + VisAgent

**TC-A7-INT-003: MC Backend 写入成功**
```
GIVEN: MC Backend API 正常（返回 200）
WHEN: A7.execute()
THEN:
  - saved_to_mc = 总测试用例数
  - artifact.test_plan.saved_to_mc > 0
```

**TC-A7-INT-004: VisAgent 推送（visual + e2e 类型）**
```
GIVEN: test_cases 含 3 条 visual + 2 条 e2e + 10 条 unit
WHEN: _push_to_visagent()
THEN:
  - 实际推送数 = 5（仅 visual + e2e）
  - 每一条发送 POST 到 VisAgent API
  - pushed_to_visagent = 5
```

### 3.3 NATS 发布

**TC-A7-INT-005: agent.result.A7 + test.assets_ready 发布**
```
WHEN: A7.execute() 完成
THEN:
  - js.publish("agent.result.A7", ...) 被调用，含 Nats-Msg-Id header
  - js.publish("test.assets_ready", ...) 被调用，含 Nats-Msg-Id header
  - agent.result.A7 payload 含 dag_coverage
  - test.assets_ready payload 含 test_asset_id
  - 消息被 ack
```

---

## 四、容错测试（3 条）

**TC-A7-ROBUST-001: LLM 不可用 → Fallback**
```
GIVEN: DeepSeek API 连接超时
WHEN: A7.execute()
THEN:
  - 回退到 _fallback_generate()
  - test_cases 非空（≥ 6 条）
  - status = 'completed'（不是 'empty'）
  - test_assets 成功写入
  - agent.result.A7 正常发布
```

**TC-A7-ROBUST-002: MC Backend 不可用不影响主流程**
```
GIVEN: MC Backend API 返回 500
WHEN: A7.execute()
THEN:
  - saved_to_mc = 0
  - test_assets PostgreSQL 写入成功
  - agent.result.A7 仍正常发布（saved_to_mc=0）
  - 不抛出异常
  - status = 'completed'
```

**TC-A7-ROBUST-003: LLM JSON 解析失败 → Fallback**
```
GIVEN: Mock LLM 返回 "好的，以下是测试用例..."（无 JSON）
WHEN: json.loads() 抛出 JSONDecodeError
THEN:
  - 回退到 fallback 规则生成
  - 不崩溃
  - 返回有效 test_cases 列表
```

---

## 五、E2E 端到端测试（2 条）

**TC-A7-E2E-001: DAG 可用时的完整生成流程**
```
流程:
  context.ready.A7 (dag_preview.dag_available=true, 8 DAG 节点)
    → _generate_with_llm (含 DAG 节点注入)
    → _organize_test_assets (按类型分组)
    → _save_to_postgres (version=1, test_assets 表)
    → _save_to_backend (MC Backend API)
    → _push_to_visagent (visual/e2e 推送)
    → _calculate_dag_coverage (覆盖率计算)
    → _upsert_agent_results (agent_key='A7')
    → _publish_agent_result_a7 (NATS)
    → _publish_test_assets_ready (NATS)
    → msg.ack()

验证点:
  - test_assets 表 1 行 (version=1)
  - agent_results 表 1 行 (agent_key='A7', status='completed')
  - dag_coverage.dag_available = true
  - dag_coverage.covered_nodes > 0
  - NATS agent.result.A7 + test.assets_ready 发布成功
```

**TC-A7-E2E-002: Gate2 打回修订流程**
```
流程:
  Gate2 reject (a7_rework=true, reject_reasons=[{"category":"test_insufficient"}])
    → context.ready.A7 (revision_context.is_revision=true)
    → _generate_with_llm (注入 revision_context)
    → _save_to_postgres (version=2)
    → _upsert_agent_results (同 cycle UPSERT 覆盖)

验证点:
  - test_assets version = 2
  - agent_results 同 cycle 仅 1 行
  - LLM prompt 包含 "修正指引" 和 "test_insufficient"
  - 新用例优先覆盖拒绝原因指出的不足
```

---

## 六、测试数据准备

### 6.1 fixtures 目录

```
tests/fixtures/
├── spec_complete.json           # 完整 Spec（5 模块 + 8 API + 4 实体）
├── dag_valid_8nodes.json        # 合法 DAG（8 节点）
├── context_ready_a7_dag.json    # context.ready.A7（dag_available=true）
├── context_ready_a7_nodag.json  # context.ready.A7（dag_available=false）
├── context_ready_a7_revision.json  # 含 revision_context
├── llm_test_cases_valid.json    # Mock LLM 返回的合法测试用例
├── llm_test_cases_malformed.json # Mock LLM 返回的非 JSON 文本
└── gate2_reject_test.json       # Gate2 拒绝 payload（test_insufficient）
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
def mock_llm_return_test_cases():
    """Mock DeepSeek API 返回合法测试用例 JSON"""
    async def _mock(prompt, **kwargs):
        with open("tests/fixtures/llm_test_cases_valid.json") as f:
            cases = json.load(f)
        return json.dumps(cases)
    return _mock

@pytest.fixture
def mock_llm_return_non_json():
    """Mock DeepSeek API 返回非 JSON 文本"""
    return AsyncMock(return_value="好的，以下是您需要的测试用例：\n1. 正常登录测试\n2. 异常登录测试\n...")

@pytest.fixture
def mock_llm_failure():
    """Mock DeepSeek API 返回失败"""
    return AsyncMock(return_value=None)

@pytest.fixture
def mock_mc_backend_success():
    """Mock MC Backend API 返回 200"""
    mock = AsyncMock()
    mock.post = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"saved": 16}))
    return mock

@pytest.fixture
def mock_mc_backend_failure():
    """Mock MC Backend API 返回 500"""
    mock = AsyncMock()
    mock.post = AsyncMock(return_value=MagicMock(status_code=500))
    return mock

@pytest.fixture
def context_ready_a7_dag():
    """加载含 DAG 的 context.ready.A7"""
    with open("tests/fixtures/context_ready_a7_dag.json") as f:
        return json.load(f)

@pytest.fixture
def context_ready_a7_nodag():
    """加载无 DAG 的 context.ready.A7"""
    with open("tests/fixtures/context_ready_a7_nodag.json") as f:
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

| 编号 | 分类 | 描述 | 关键验证点 |
|------|------|------|-----------|
| TC-A7-UNIT-001 | 单元-覆盖 | dag_available=true 覆盖计算 | 2/3 覆盖 |
| TC-A7-UNIT-002 | 单元-覆盖 | dag_available=false 跳过 | 全 0 |
| TC-A7-UNIT-003 | 单元-组织 | 按类型分组 | 5 分组正确 |
| TC-A7-UNIT-004 | 单元-组织 | 用例结构验证 | steps 含 step_number/action/expected |
| TC-A7-UNIT-005 | 单元-Fallback | 按 DAG 节点类型生成 | 6 条, 类型映射正确 |
| TC-A7-UNIT-006 | 单元-Fallback | 无 DAG 节点生成基础用例 | ≥6 条 |
| TC-A7-UNIT-007 | 单元-dag_preview | DAG 可用 prompt 注入 | prompt 含 node_id 指令 |
| TC-A7-UNIT-008 | 单元-dag_preview | DAG 不可用 prompt | prompt 含独立生成指令 |
| TC-A7-UNIT-009 | 单元-修订 | 修订 prompt 注入 | prompt 含 Gate2 拒绝原因 |
| TC-A7-INT-001 | 集成-DB | 首次写入 test_assets | version=1 |
| TC-A7-INT-002 | 集成-DB | 版本递增 | version=1,2 双行 |
| TC-A7-INT-003 | 集成-MC | MC Backend 写入成功 | saved_to_mc=16 |
| TC-A7-INT-004 | 集成-VisAgent | VisAgent 推送 | pushed_to_visagent=5 |
| TC-A7-INT-005 | 集成-NATS | 双事件发布 | agent.result.A7 + test.assets_ready |
| TC-A7-ROBUST-001 | 容错 | LLM 不可用 | fallback, 不崩溃 |
| TC-A7-ROBUST-002 | 容错 | MC Backend 不可用 | saved_to_mc=0, 不阻塞 |
| TC-A7-ROBUST-003 | 容错 | JSON 解析失败 | fallback, 不崩溃 |
| TC-A7-E2E-001 | E2E | 完整生成流程 | test_assets + agent_results + NATS |
| TC-A7-E2E-002 | E2E | Gate2 打回修订 | version=2, prompt 注入 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-17
**版本**: v1.0
