# A5 自动设计检查 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-13
- **参考**: [A5 开发设计文档](./A5-自动设计检查Agent-开发设计文档.md) · [A5-自动设计检查Agent完整设计](../Agent规格/A5-自动设计检查Agent完整设计.md) · [阶段二数据字典](../Agent规格/阶段二-数据字典.md)
- **测试范围**: A5 全功能验证（五维检查 → 维度级降级 → 汇总评分 → 持久化 → NATS 发布 → 非阻断语义 → A4 缺失场景）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常五维检查 + A4 缺失场景
            ├──────────────┤
            │  真实环境集成  │  5 条：LLM + NATS 真实服务
            ├──────────────┤
            │  集成测试     │  6 条：Agent + DB + NATS + Gate1 上下文联合验证
            ├──────────────┤
            │  单元测试     │  18 条：五维检查器、评分汇总、降级策略
            ├──────────────┤
            │  数据库测试   │  4 条：agent_results A5 UPSERT、artifact 结构
            └──────────────┘
```

---

## 二、数据库层测试（4 条）

**T-A5-DB-001: agent_results A5 正常 INSERT**
```
输入:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A5', 0, 'completed',
          '{"check_report":{"overall_score":0.78,"total_issues":8,"dimensions":[]},"non_blocking":true,"generated_at":"2026-07-13T10:00:00Z"}'::jsonb);

验证 SQL:
  SELECT agent_key, cycle, status,
         artifact->'check_report'->>'overall_score' as score,
         artifact->>'non_blocking' as nb
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A5';

预期结果:
  agent_key = 'A5'
  status = 'completed'
  score = '0.78'
  nb = 'true'
```

**T-A5-DB-002: artifact.check_report 五维结构完整性**
```
输入: 插入含完整五维报告的 artifact

验证 SQL:
  SELECT
    jsonb_array_length(artifact->'check_report'->'dimensions') as dim_count,
    artifact->'check_report'->>'overall_score' as overall,
    artifact->'check_report'->>'total_issues' as issues
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A5';

预期结果:
  dim_count = 5
  overall 为合法数字（可为 null）
  issues >= 0
```

**T-A5-DB-003: A5 UPSERT — ON CONFLICT 覆盖**
```
步骤 1:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A5', 0, 'completed', '{"check_report":{"overall_score":0.65}}'::jsonb);
  → 成功

步骤 2:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A5', 0, 'completed', '{"check_report":{"overall_score":0.80}}'::jsonb)
  ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
  SET artifact = EXCLUDED.artifact, status = EXCLUDED.status;

验证 SQL:
  SELECT artifact->'check_report'->>'overall_score' as score
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A5';

预期结果:
  score = '0.80'
  count(*) = 1（UPSERT 未新增行）
```

**T-A5-DB-004: skipped 维度 report 结构**
```
输入: 插入含 skipped 维度的 artifact

验证 SQL:
  -- jsonb_array_elements 展开后每行是单个维度对象，直接访问字段即可
  SELECT
    dims->>'dimension' as dim_name,
    dims->>'status' as dim_status,
    dims->>'skip_reason' as dim_reason
  FROM (
    SELECT jsonb_array_elements(artifact->'check_report'->'dimensions') as dims
    FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A5'
  ) t
  WHERE dims->>'status' IS NOT NULL;

预期结果:
  至少 1 行的 dim_status = 'skipped'
  该行的 dim_reason = 'llm_timeout' 或 'a4_missing'
  正常评分维度 dim_status 为 NULL（无此字段）
```

---

## 三、A5 Agent 单元测试（18 条）

### 3.1 API 一致性检查

**T-A5-AG-001: 正常检查 — 无问题**
```
输入:
  a4_output = {
    "openapi_schema": {
      "paths": {
        "/users": {
          "get": {"responses": {"200": {"description":"OK"},"400":{"description":"Bad Request"}}},
          "post": {"responses": {"201": {"description":"Created"},"400":{"description":"Bad Request"}}}
        }
      }
    }
  }

验证:
  result = await _check_api_consistency(a3, a4)
  result.dimension = "api_consistency"
  result.score >= 0.9 (接近满分)
  len(result.issues) = 0
```

**T-A5-AG-002: 缺少 200 响应 — 检出 minor issue**
```
输入:
  openapi_schema.paths."/users".get.responses = {}（空）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "minor"
  某条 issue.description 包含 "缺少 200 响应定义"
```

**T-A5-AG-003: 缺少 4XX 响应 — 检出 minor issue**
```
输入:
  openapi_schema.paths."/users".post.responses = {"201": {"description":"Created"}}
  （缺少 4XX）

验证:
  result.issues 至少 1 条
  某条 issue.description 包含 "4XX" 或 "错误响应"
```

**T-A5-AG-004: 路径含 N+1 模式 — 检出 major issue**
```
输入:
  openapi_schema.paths 含:
    GET /users
    GET /users/{id}/roles

验证:
  调用 N1Detector.detect()
  result.issues 至少 1 条 N+1 风险
  某条 issue.severity = "major"
  某条 issue.description 包含 "N+1"
```

### 3.2 ERD 完整性检查

**T-A5-AG-005: ERD 覆盖全部 Spec 实体 — 无问题**
```
输入:
  spec_doc.data_models = [{"name":"User"},{"name":"Article"}]
  erd_diagram.entities = [{"name":"User","fields":[{"name":"id","primary_key":true}]},{"name":"Article","fields":[{"name":"id","primary_key":true}]}]

验证:
  result.score >= 0.9
  len(result.issues) = 0
```

**T-A5-AG-006: ERD 缺少 Spec 实体 — 检出 critical issue**
```
输入:
  spec_doc.data_models = [{"name":"User"},{"name":"Article"},{"name":"Comment"}]
  erd_diagram.entities = [{"name":"User"},{"name":"Article"}]
  （Comment 缺失）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "critical"
  某条 issue.description 包含 "Comment" 和 "缺失"
```

**T-A5-AG-007: 实体缺少主键 — 检出 major issue**
```
输入:
  erd_diagram.entities = [{"name":"User","fields":[{"name":"id","type":"UUID"}]}]
  （id 字段没有 primary_key:true）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "major"
  某条 issue.description 包含 "缺少主键"
```

### 3.3 状态机闭合性检查

**T-A5-AG-008: 闭合状态机 — 无问题**
```
输入:
  spec_doc.modules = [{
    "name":"订单模块",
    "state_machine":{
      "states":["pending","confirmed","shipped","completed"],
      "transitions":[
        {"from":"pending","to":"confirmed","trigger":"支付成功"},
        {"from":"confirmed","to":"shipped","trigger":"发货"},
        {"from":"shipped","to":"completed","trigger":"签收"}
      ]
    }
  }]

验证:
  result.score >= 0.9
  len(result.issues) = 0
```

**T-A5-AG-009: 状态没有入边（不可达）— 检出 major issue**
```
输入:
  states = ["pending", "confirmed", "orphan"]
  transitions = [{"from":"pending","to":"confirmed","trigger":"提交"}]
  （orphan 没有入边）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "major"
  某条 issue.description 包含 "没有入边" 或 "不可达"
```

**T-A5-AG-010: 状态没有出边（死锁）— 检出 major issue**
```
输入:
  states = ["pending", "dead_end"]
  transitions = [{"from":"pending","to":"dead_end","trigger":"提交"}]
  terminal_states = []（dead_end 不是终态也无出边）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "major"
  某条 issue.description 包含 "没有出边" 或 "死锁"
```

**T-A5-AG-011: transition 缺少 trigger — 检出 minor issue**
```
输入:
  transitions = [{"from":"pending","to":"confirmed"}]（无 trigger 字段）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "minor"
  某条 issue.description 包含 "缺少 trigger"
```

### 3.4 原型-Spec 对齐检查

**T-A5-AG-012: 原型覆盖所有状态 — 无问题**
```
输入:
  prototype_screens = [
    {"name":"列表页","state":"default"},
    {"name":"加载中","state":"loading"},
    {"name":"空数据","state":"empty"},
    {"name":"错误","state":"error"}
  ]
  spec_doc.modules = [{"name":"列表模块","states":["default","loading","empty","error"]}]

验证:
  result.score >= 0.9
  len(result.issues) = 0（或仅有 info 级别提示）
```

**T-A5-AG-013: 原型缺少必需状态 — 检出 issue**
```
输入:
  prototype_screens = [{"name":"列表页","state":"default"}]
  （缺少 loading, empty, error）

验证:
  result.issues 至少 3 条（对应 loading, empty, error）
  某条 issue.description 包含 "缺少" 和 "loading"
```

**T-A5-AG-014: 空原型 screens — 全部状态缺失**
```
输入:
  prototype_screens = []

验证:
  result.issues 至少 4 条（default, loading, empty, error 全部缺失）
  result.score < 0.5
```

### 3.5 安全基线检查

**T-A5-AG-015: 安全配置完整 — 无 critical**
```
输入:
  openapi_schema.components.securitySchemes = {"bearerAuth":{"type":"http","scheme":"bearer"}}
  openapi_schema.servers = [{"url":"https://api.example.com"}]
  paths."/users".post.security = [{"bearerAuth":[]}]

验证:
  - 无 critical severity issue
  - securitySchemes 检查通过
```

**T-A5-AG-016: 缺少 securitySchemes — 检出 critical**
```
输入:
  openapi_schema.components.securitySchemes = {}（空）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "critical"
  某条 issue.id = "sec_001"
  某条 issue.description 包含 "未定义 securitySchemes"
```

**T-A5-AG-017: 写操作缺少 security 声明 — 检出 major**
```
输入:
  openapi_schema.paths."/users".post.security = None（未声明）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "major"
  某条 issue.description 包含 "缺少 security 声明"
```

**T-A5-AG-018: spec_doc 缺少安全信号词 — 检出 major**
```
输入:
  spec_doc = {"title":"测试","modules":[]}
  （不含 auth/permission/role/rbac/audit 等安全信号词）

验证:
  result.issues 至少 1 条
  某条 issue.severity = "major"
  某条 issue.description 包含 "安全相关概念"

  注: severity 预期固定为 "major"（安全信号词缺失视为结构性缺陷，非仅 info 提示）
```

---

## 四、评分汇总测试（4 条）

**T-A5-SC-001: 五维全部通过 → 高 overall_score**
```
输入: 五个维度 score = [0.95, 0.90, 0.88, 0.92, 0.85]
      权重 = [0.25, 0.25, 0.20, 0.15, 0.15]

预期:
  overall_score = 0.95×0.25 + 0.90×0.25 + 0.88×0.20 + 0.92×0.15 + 0.85×0.15
                = 0.2375 + 0.225 + 0.176 + 0.138 + 0.1275 = 0.904
  total_issues = sum(len(d.issues))
```

**T-A5-SC-002: 部分维度 skipped → 仅计算有评分维度**
```
输入:
  api_consistency: score=0.85, weight=0.25
  erd_completeness: score=null, status='skipped', weight=0.25
  state_machine_closure: score=0.70, weight=0.20
  prototype_spec_alignment: score=null, status='skipped', weight=0.15
  security_baseline: score=0.90, weight=0.15

预期:
  total_weight = 0.25 + 0.20 + 0.15 = 0.60
  overall_score = (0.85×0.25 + 0.70×0.20 + 0.90×0.15) / 0.60
                = (0.2125 + 0.14 + 0.135) / 0.60
                = 0.4875 / 0.60 = 0.8125
  四舍五入: 0.81
```

**T-A5-SC-003: 全部维度 skipped → overall_score = null**
```
输入: 五个维度全部 score=null, status='skipped'

验证:
  overall_score = null
  total_issues = 0（或各维度 issues 之和）
  summary 包含 "全部维度跳过" 或类似提示
```

**T-A5-SC-004: 非阻断语义 — report 不含 pass/fail**
```
验证: check_report 的顶层 key 不包含 "pass", "fail", "overall_pass"
      各维度独立评分，无全局通过/不通过字段
```

---

## 五、降级策略测试（5 条）

**T-A5-DG-001: 单维度超时 — 其余维度继续**
```
模拟: _check_erd_completeness 超时（超过 180s 不返回）

验证:
  - erd_completeness 维度 score=null, status='skipped', skip_reason='llm_timeout'
  - 其余 4 个维度正常产出 score
  - overall_score 仅用 4 个维度计算
  - execute() 正常返回，不抛异常
```

**T-A5-DG-002: 全部维度超时 → 重试 1 次 → skipped**
```
模拟: 五维全部超时

验证:
  - Orchestrator 重试 1 次
  - 仍超时 → agent_results A5 status='skipped'
  - check_report 为空或仅有 metadata
```

**T-A5-DG-003: LLM 不可用 → 降级为规则检查**
```
模拟: LLM 全部不可用

验证:
  - 每维度降级为纯规则/结构比对
  - score 仍可产出（基于规则，非 LLM）
  - 各维度标注 'llm_unavailable' 或类似标记
```

**T-A5-DG-004: A4 缺失场景 — 仅检查 prototype_spec_alignment**
```
输入:
  context_package.a4_output.a4_missing = true
  a3_output = {"prototype_url":"...","screens":[{"name":"列表","state":"default"}]}

验证:
  - _check_prototype_only 被调用（非完整 execute）
  - 仅 prototype_spec_alignment 有评分（其余 4 维 status='skipped', skip_reason='a4_missing'）
  - overall_score = null（_check_prototype_only 固定返回 null，因为仅 1 个维度可评分，加权平均无意义）
  - summary 包含 "A4 Spec 未产出"
```

**T-A5-DG-005: A4 缺失 + 原型 screens 也不全 — 仍产出报告**
```
输入:
  a4_missing = true
  a3_output.screens = [{"name":"列表","state":"default"}]（仅 default，缺 loading/empty/error）

验证:
  - prototype_spec_alignment 维度检出 3 个缺失状态
  - 其余维度全部 skipped
  - execute() 正常返回
```

---

## 六、NATS 事件 + Gate1 集成测试（6 条）

**T-A5-IT-001: context.ready.A5 输入结构完整解析**
```
输入: 标准 context.ready.A5 payload（含 a3_output + a4_output）

验证:
  - a3_output.prototype_url 被正确读取
  - a3_output.screens 被正确读取
  - a4_output.spec_doc + openapi_schema + erd_diagram + ddl_statements 全部解析
  - a4_output.a4_missing 正确解析为 false
```

**T-A5-IT-002: agent.result.A5 不含 pass/fail**
```
验证 payload 结构:
  - payload 含 "req_id", "session_id", "cycle", "check_report", "timestamp"
  - payload 不含 "pass", "fail", "overall_pass"
  - check_report 含 "overall_score", "total_issues", "dimensions", "summary"
```

**T-A5-IT-003: Orchestrator 收到 agent.result.A5 → 继续进入 Gate1**
```
前置:
  - A5 执行完成，agent.result.A5 已发布
  - check_report.overall_score = 0.35（低分）

验证:
  - Orchestrator 更新 requirements.design_status = 'design_completed'
  - Orchestrator 发布 context.ready.gate1
  - 不会因低分而阻断（非阻断语义验证）
  - Gate1 审批页可读取 A5 report
```

**T-A5-IT-004: Gate1 审批上下文含 A5 report**
```
前置: agent_results A5 cycle=0 已写入

请求: GET /api/approvals/<approval_id>/context（gate_level=1）

验证:
  Response.a5_output.a5_missing = false
  Response.a5_output.check_report.dimensions 长度 = 5
  Response.a5_output.check_report.overall_score 非 null
```

**T-A5-IT-005: A5 超时 → Gate1 仍可用**
```
模拟: A5 超时, Orchestrator 写入 agent_results (A5, status='skipped')

验证:
  - context.ready.gate1 仍被发布
  - Gate1 审批上下文 a5_output.a5_missing = true
  - Gate1 审批页展示 "设计检查报告不可用" 提示
```

**T-A5-IT-006: Gate1 拒绝 → A4 修订 → A5 重检**
```
前置: Gate1 reject → A4 修订完成 → context.ready.A5 (同一 cycle)

验证:
  - A5 重新执行五维检查
  - agent_results A5 UPSERT 覆盖写入（同 cycle）
  - check_report.overall_score 可能与首次不同
  - Gate1 审批页展示最新 A5 报告
```

---

## 七、并发与边界测试（3 条）

**T-A5-CC-001: 空 openapi_schema → 不崩溃**
```
输入:
  a4_output.openapi_schema = {}

验证:
  - api_consistency 维度 score 为低分（非 null）
  - 不抛异常
  - 其余维度正常执行
```

**T-A5-CC-002: 空 spec_doc → 不崩溃**
```
输入:
  a4_output.spec_doc = {}

验证:
  - erd_completeness 维度 score 为低分
  - state_machine_closure 维度 score 为满分（无模块=无状态机=无问题可检出）
  - 不抛异常
```

**T-A5-CC-003: prototype_screens 含 null/空 state → 防御处理**
```
输入:
  a3_output.screens = [{"name":"无状态页"}]
  （元素无 state 字段、state 为 null 或空字符串）

验证:
  - screen_states 集合正确构建（None 被 skip 或被识别为特殊值）
  - 不抛 TypeError
  - 正常产出 issues
```

---

## 八、端到端测试（2 条）

### 8.1 正常五维检查全流程

**T-A5-E2E-001: A4 completed → A5 → Gate1 正常链路**

```
Step 1: 准备数据（模拟 A4 已完成）
  - requirements: phase='design', design_status='design_checking'
  - agent_results: A1, A2, A3, A4 全部 cycle=0, completed
  - design_specs: version=1, 含完整 spec_doc + openapi_schema + erd_diagram + ddl_statements
  - prototype_artifacts: status='confirmed', screens 含 4 个必需状态

Step 2: Orchestrator 发布 context.ready.A5
  验证点:
    ✓ a3_output.prototype_url 非空
    ✓ a3_output.screens 数组非空
    ✓ a4_output.a4_missing = false
    ✓ a4_output.spec_doc 非空

Step 3: A5 执行
  验证点:
    ✓ 五维全部执行（无 skipped 维度）
    ✓ api_consistency 得分 > 0
    ✓ erd_completeness 得分 > 0
    ✓ state_machine_closure 得分 > 0
    ✓ prototype_spec_alignment 得分 > 0
    ✓ security_baseline 得分 > 0
    ✓ overall_score 计算正确（加权平均）
    ✓ check_report.summary 非空
    ✓ agent_results A5 cycle=0 status='completed'

Step 4: agent.result.A5 发布
  验证点:
    ✓ NATS 消息已发布
    ✓ payload 不含 pass/fail
    ✓ Orchestrator 收到 → design_status='design_completed'
    ✓ Orchestrator 发布 context.ready.gate1

Step 5: Gate1 审批页读取 A5 report
  验证点:
    ✓ GET /api/approvals/<id>/context → a5_output.check_report 完整
    ✓ 前端可渲染五维评分面板

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                      │ 预期行数 │ 关键字段        │
  ├─────────────────────────────────────────────────────┤
  │ agent_results           │ 5       │ A1/A2/A3/A4/A5 +0 │
  │ requirements            │ 1       │ design_status='design_completed' │
  │ event_log               │ >=3     │ agent.result.A4 + A5 + context.ready.gate1 │
  └─────────────────────────────────────────────────────┘
```

### 8.2 A4 缺失 → A5 降级检查 → Gate1

**T-A5-E2E-002: A4 超时跳过 → A5 仅检查原型 → Gate1 仍可用**

```
Step 1: 准备数据
  - requirements: design_status='design_checking'
  - agent_results: A1, A2, A3 completed, A4 status='skipped'
  - design_specs: 无记录

Step 2: Orchestrator build_context → context.ready.A5
  验证点:
    ✓ a4_output.a4_missing = true
    ✓ a4_output.spec_doc 为空
    ✓ a3_output 含原型信息

Step 3: A5 执行（A4 缺失模式）
  验证点:
    ✓ _check_prototype_only 被调用
    ✓ 仅 prototype_spec_alignment 维度有评分
    ✓ 其余 4 维 status='skipped', skip_reason='a4_missing'
    ✓ overall_score = null（多数维度跳过）
    ✓ summary = "A4 Spec 未产出，仅检查了原型状态覆盖"
    ✓ agent_results A5 status='completed'

Step 4: Gate1 审批页仍可用
  验证点:
    ✓ a5_output.a5_missing = false（A5 执行了，只是多数维度 skipped）
    ✓ check_report 可渲染（一维有数据，其余标注 "不可用"）
    ✓ 审批人可基于原型做判断

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                      │ 预期行数 │ 关键字段        │
  ├─────────────────────────────────────────────────────┤
  │ agent_results           │ 5       │ A4 skipped, A5 completed │
  │ requirements            │ 1       │ design_status='design_completed' │
  └─────────────────────────────────────────────────────┘
```

---

## 九、真实环境集成测试（5 条）

> 以下用例依赖真实外部服务，标记为 `@pytest.mark.integration`。

### 9.1 测试环境要求

| 组件 | 要求 |
|------|------|
| **PostgreSQL** | 真实 DB（test 库），含 agent_results 表 |
| **LLM (DeepSeek)** | 真实 API，用于各维度语义检查 |
| **NATS** | 嵌入式 nats-server -js |

### 9.2 LLM 真实调用（4 条）

**T-A5-RL-001: 完整五维真实 LLM 检查**
```
输入:
  a3_output = (真实原型数据: prototype_url + 4 状态 screens)
  a4_output = (真实 Spec 四件套)

验证:
  - 五维全部执行（无 skipped）
  - overall_score 在 0-1 之间
  - total_issues >= 0
  - 每个维度至少产出 1 条 issue 或为空
  - 执行总时长 ≤ 600s（10 分钟）
  - agent_results A5 写入成功

标记: @pytest.mark.integration @pytest.mark.llm @pytest.mark.slow
```

**T-A5-RL-002: 单维度 LLM 超时降级**
```
输入: 同上
模拟: 通过较小超时值或真实 LLM 延迟触发单维度超时

验证:
  - 超时维度 score=null, status='skipped'
  - 其余维度正常产出
  - overall_score 仅用非 skipped 维度计算
  - 无 unhandled exception

标记: @pytest.mark.integration @pytest.mark.llm @pytest.mark.resilience
```

**T-A5-RL-003: A4 产出有已知缺陷 → A5 检出**
```
输入:
  - openapi_schema.paths 中某个 POST endpoint 缺少 security
  - erd_diagram.entities 中某实体缺少主键
  - spec_doc.modules 中某状态机缺少出边

验证:
  - api_consistency 检出 security 缺失 issue
  - erd_completeness 检出缺少主键 issue
  - state_machine_closure 检出死锁状态 issue
  - 所有 issue 的 suggestion 非空

标记: @pytest.mark.integration @pytest.mark.llm
```

**T-A5-RL-004: 原型状态不全 → A5 检出**
```
输入:
  prototype_screens 仅有 default 和 loading（缺 empty 和 error）

验证:
  - prototype_spec_alignment 维度检出至少 2 条 missing state issue
  - 每条 issue 含具体的状态名

标记: @pytest.mark.integration @pytest.mark.llm @pytest.mark.edge_case
```

### 9.3 NATS 真实集成（1 条）

**T-A5-RL-005: context.ready.A5 → A5 → agent.result.A5 → Gate1 全链路**
```
前置:
  - 嵌入式 nats-server -js
  - A5 Worker 订阅就绪
  - DB 含 A1/A2/A3/A4 产物
  - Gate1 审批服务就绪

步骤:
  1. NATS 发布 context.ready.A5
  2. 等待 agent.result.A5（超时 120s）
  3. 验证 context.ready.gate1 是否发布

验证:
  - agent.result.A5 在 ≤ 60s 发布
  - payload.check_report 含完整五维数据
  - context.ready.gate1 在 agent.result.A5 后被发布
  - Gate1 审批页可渲染 A5 report

标记: @pytest.mark.integration @pytest.mark.nats @pytest.mark.slow
```

---

## 十、测试环境与 Mock 策略

### 10.1 依赖隔离

| 组件 | 测试策略 |
|------|---------|
| **PostgreSQL** | 真实 DB（test 库），每个测试函数用事务回滚 |
| **LLM (DeepSeek)** | 全部 mock：每个维度检查函数返回预定义结果或抛 TimeoutError |
| **NATS** | 集成测试用嵌入式 NATS（`nats-server -js`），单元测试 mock |

### 10.2 数据夹具（Fixtures）

```python
# 标准 context.ready.A5 payload
MOCK_CONTEXT_A5 = {
    "req_id": "test-req-a5-001",
    "session_id": "test-sid-001",
    "cycle": 0,
    "a3_output": {
        "prototype_url": "https://s3/xxx/prototype_v1.html",
        "screens": [
            {"name": "用户列表-默认", "state": "default", "url": "https://s3/xxx/s1.png"},
            {"name": "用户列表-加载中", "state": "loading", "url": "https://s3/xxx/s2.png"},
            {"name": "用户列表-空数据", "state": "empty", "url": "https://s3/xxx/s3.png"},
            {"name": "用户列表-错误", "state": "error", "url": "https://s3/xxx/s4.png"},
        ],
    },
    "a4_output": {
        "a4_missing": False,
        "spec_doc": {
            "title": "用户管理系统",
            "overview": "企业用户管理平台",
            "modules": [
                {
                    "name": "用户管理",
                    "states": ["list", "detail", "edit", "create"],
                    "state_machine": {
                        "states": ["list", "detail", "edit", "create"],
                        "transitions": [
                            {"from": "list", "to": "detail", "trigger": "点击行"},
                            {"from": "list", "to": "create", "trigger": "点击新建"},
                            {"from": "detail", "to": "edit", "trigger": "点击编辑"},
                            {"from": "edit", "to": "detail", "trigger": "保存成功"},
                            {"from": "create", "to": "detail", "trigger": "创建成功"},
                        ],
                    },
                },
            ],
            "data_models": [
                {"name": "User", "fields": [
                    {"name": "id", "type": "UUID", "nullable": False, "primary_key": True},
                    {"name": "name", "type": "VARCHAR(100)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "role", "type": "VARCHAR(50)", "nullable": False},
                ]},
            ],
        },
        "openapi_schema": {
            "openapi": "3.0.0",
            "info": {"title": "User API", "version": "1.0.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/users": {
                    "get": {"summary": "获取用户列表", "responses": {"200": {"description": "OK"}, "400": {"description": "Bad Request"}}},
                    "post": {"summary": "创建用户", "responses": {"201": {"description": "Created"}, "400": {"description": "Bad Request"}}, "security": [{"bearerAuth": []}]},
                },
                "/users/{id}": {
                    "get": {"summary": "获取用户详情", "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}}},
                    "put": {"summary": "更新用户", "responses": {"200": {"description": "OK"}, "400": {"description": "Bad Request"}}, "security": [{"bearerAuth": []}]},
                    "delete": {"summary": "删除用户", "responses": {"204": {"description": "No Content"}}, "security": [{"bearerAuth": []}]},
                },
            },
            "components": {
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
                "schemas": {"User": {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}}},
            },
        },
        "erd_diagram": {
            "entities": [
                {"name": "User", "fields": [
                    {"name": "id", "type": "UUID", "primary_key": True},
                    {"name": "name", "type": "VARCHAR(100)", "nullable": False},
                    {"name": "email", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "role", "type": "VARCHAR(50)", "nullable": False},
                ]},
            ],
        },
        "ddl_statements": "CREATE TABLE users (\n  id UUID PRIMARY KEY,\n  name VARCHAR(100) NOT NULL,\n  email VARCHAR(255) NOT NULL,\n  role VARCHAR(50) NOT NULL\n);",
    },
}

# 标准五维全通过 mock
MOCK_DIMENSION_CLEAN = {
    "dimension": "api_consistency",
    "label": "API 一致性",
    "score": 1.0,
    "issues": [],
}

# 标准带 issues mock
MOCK_DIMENSION_WITH_ISSUES = {
    "dimension": "api_consistency",
    "label": "API 一致性",
    "score": 0.75,
    "issues": [
        {"id": "api_001", "severity": "minor", "description": "GET /users/{id} 缺少 404 响应定义",
         "suggestion": "补充 404 响应", "location": "openapi_schema.paths./users/{id}.get.responses"},
        {"id": "api_002", "severity": "major", "description": "N+1 风险: GET /users → GET /users/{id}/roles",
         "suggestion": "使用批量端点", "location": "/users/{id}/roles"},
    ],
}

# 标准 skipped mock
MOCK_DIMENSION_SKIPPED = {
    "dimension": "state_machine_closure",
    "label": "状态机闭合性",
    "score": None,
    "status": "skipped",
    "issues": [],
    "skip_reason": "llm_timeout",
}

# context.ready.A5 (A4 缺失场景)
MOCK_CONTEXT_A5_A4_MISSING = {
    "req_id": "test-req-a5-002",
    "session_id": "test-sid-002",
    "cycle": 0,
    "a3_output": {
        "prototype_url": "https://s3/xxx/prototype_v1.html",
        "screens": [{"name": "列表", "state": "default", "url": "https://s3/xxx/s1.png"}],
    },
    "a4_output": {
        "a4_missing": True,
        "spec_doc": {},
        "openapi_schema": {},
        "erd_diagram": {},
        "ddl_statements": "",
    },
}
```

---

## 十一、测试执行清单

### 按 Phase 分配

| Phase | 测试编号 | 测试数 | 关键依赖 |
|-------|---------|:-----:|---------|
| **Phase 1** (DB) | T-A5-DB-001 → T-A5-DB-004 | 4 | PostgreSQL 就绪 |
| **Phase 2** (Unit: 五维检查) | T-A5-AG-001 → T-A5-AG-018 | 18 | LLM mock 就绪 |
| **Phase 3** (Score+Degradation) | T-A5-SC-001 → T-A5-SC-004, T-A5-DG-001 → T-A5-DG-005 | 9 | LLM mock + NATS mock |
| **Phase 4** (Integration+Edge) | T-A5-IT-001 → T-A5-IT-006, T-A5-CC-001 → T-A5-CC-003 | 9 | NATS 就绪 |
| **Phase 5** (E2E) | T-A5-E2E-001 → T-A5-E2E-002 | 2 | 全链路环境就绪 |
| **Phase 6** (Real Env) | T-A5-RL-001 → T-A5-RL-005 | 5 | LLM/NATS 真实服务 |

### 测试通过标准

- **Phase 1**: 4/4 通过 → agent_results A5 写入正确，UPSERT 行为正确，artifact 结构完整
- **Phase 2**: 18/18 通过 → 五维检查器各自正确，API/ERD/状态机/原型/安全五项全部覆盖
- **Phase 3**: 9/9 通过 → 评分汇总公式正确，降级策略全部生效，非阻断语义验证
- **Phase 4**: 9/9 通过 → NATS 事件链路完整，Gate1 上下文含 A5 report，并发安全，边界覆盖
- **Phase 5**: 2/2 通过 → E2E 全链路正确，A4 缺失降级链路正确
- **Phase 6**: 5/5 通过 → 真实 LLM/NATS 环境下行为正确

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
**总测试数**: 47 条（数据库 4 + Agent 五维 18 + 评分 4 + 降级 5 + 集成 6 + 并发 3 + E2E 2 + 真实环境集成 5）
