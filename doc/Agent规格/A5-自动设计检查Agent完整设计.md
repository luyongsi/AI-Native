# A5 自动设计检查 Agent - 完整设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 完整设计文档（已通过 critical 审计）
- **参考**: [系统状态机与信息流设计](../系统架构/系统状态机与信息流设计.md) · [阶段二数据字典](./阶段二-数据字典.md) · [阶段一数据字典](./阶段一-数据字典.md)
- **说明**: A5 负责阶段二的设计自动化检查，在 A4 产出 Spec/OpenAPI/ERD/DDL 后执行。A5 是**非阻断节点**——无论检查结果如何，流程都继续进入 Gate1。检查报告仅作为 Gate1 审批人的决策参考。**本文档中所有数据结构、字段名、枚举值以阶段二数据字典为准。**

---

## 一、通信架构

A5 采用**纯 NATS 调度**模型（与 A2/A4 同构）：

```
┌──────────────┐        NATS         ┌──────────────┐
│ Orchestrator │ ◄─────────────────► │    A5 Agent   │
│              │  context.ready.A5   │              │
│              │  agent.result.A5    │              │
└──────────────┘                     └──────────────┘
```

- **NATS**：接收 Orchestrator 调度（`context.ready.A5`），发布检查报告（`agent.result.A5`）
- A5 不与用户直接交互，无 HTTP 接口
- **无 MCP 依赖**：A5 仅对已有产物做结构化校验，不检索外部知识库

---

## 二、A5 在阶段二中的位置

```
阶段二：设计
┌──────────────────────────────────────────────────────┐
│                                                      │
│  A3 UI原型 ──► A4 Spec撰写 ──► A5 设计检查 ──► Gate1 │
│                                                      │
│  ⚠️ A5 是非阻断节点：不管检查结果如何，一定进入 Gate1   │
│  A5 只出报告，不做通过/不通过判断                      │
└──────────────────────────────────────────────────────┘
```

### 核心流程

```
Orchestrator 收到 agent.result.A4
    → 写入 event_log → 更新 requirements.design_status='design_checking'
    → 查询 DB: a3_output + a4_output (design_specs)
    → build_context → context.ready.A5
    → A5 执行五维检查 → 持久化 agent_results (A5, cycle)
    → 发布 agent.result.A5
    → Orchestrator: event_log → 更新 design_status='design_completed' → context.ready.gate1

⚠️ 无论 A5 报告中有多少 critical issue，Orchestrator 始终继续进入 Gate1
```

---

## 三、检查维度

A5 执行**五项自动化检查**，每项独立打分，汇总为检查报告。

### 3.1 API 一致性（`api_consistency`）

**检查目标**：OpenAPI Schema 与 Spec 文档中的接口定义是否一致。

| 检查项 | 方法 | 权重 |
|--------|------|:----:|
| Endpoint 覆盖 | Spec 中定义的 API → OpenAPI paths 中是否都有对应 | 30% |
| 参数完整性 | OpenAPI path 的 parameters 是否覆盖 Spec 中描述的所有入参 | 25% |
| 响应定义 | 每个 endpoint 是否定义了成功和错误响应 schema | 25% |
| 错误码规范 | 是否使用了统一的错误码格式 | 20% |

### 3.2 ERD 完整性（`erd_completeness`）

**检查目标**：ERD 是否覆盖 Spec 数据模型中所有业务实体，字段定义是否完整。

| 检查项 | 方法 | 权重 |
|--------|------|:----:|
| 实体覆盖 | Spec data_models 中的实体 → ERD entities 是否都有 | 35% |
| 字段完整性 | 每个实体的所有字段是否都有类型/约束定义 | 30% |
| 主键定义 | 每个实体是否定义了主键 | 15% |
| 关系完整 | 实体间的引用关系是否在 relations 中声明 | 20% |

### 3.3 状态机闭合性（`state_machine_closure`）

**检查目标**：Spec 中的状态机是否所有状态都有入口和出口。

| 检查项 | 方法 | 权重 |
|--------|------|:----:|
| 状态可达 | 每个状态是否至少有一条入边（初始状态除外） | 30% |
| 状态可出 | 每个非终态是否至少有一条出边 | 30% |
| 终态声明 | 终态是否正确标记 | 20% |
| 触发事件 | 每条 transition 是否定义了 trigger | 20% |

### 3.4 原型-Spec 对齐（`prototype_spec_alignment`）

**检查目标**：原型页面是否覆盖 Spec 中所有用例的交互路径。

| 检查项 | 方法 | 权重 |
|--------|------|:----:|
| 用例覆盖 | use_cases 中每个用例是否在原型中有对应页面/交互 | 40% |
| 状态覆盖 | Spec 中定义的状态（default/loading/empty/error）是否在原型中都有体现 | 30% |
| 导航完整 | 原型中是否存在断头路（无法返回的页面） | 30% |

### 3.5 安全基线（`security_baseline`）

**检查目标**：API 设计是否满足基本安全要求。

| 检查项 | 方法 | 权重 |
|--------|------|:----:|
| 认证定义 | OpenAPI 中是否定义了 securitySchemes | 30% |
| 授权标注 | 敏感 endpoint（增删改）是否标注了 required scopes | 25% |
| PII 标注 | 敏感字段（name/email/phone/id_card）是否标注了 PII 分类 | 25% |
| HTTPS 强制 | 是否有全局 scheme=https 声明 | 20% |

---

## 四、核心处理流程

```
Phase 1: 加载产物    → 从 context.ready.A5 中提取 A3 原型信息 + A4 四件套
Phase 2: 五维检查    → 依次（或并行）执行五项检查
Phase 3: 汇总评分    → 计算 overall_score，生成 summary
Phase 4: 持久化+发布 → 写入 agent_results (A5) + 发布 agent.result.A5
```

### 检查执行策略

- 五个维度**顺序执行**（非并行，因为不依赖外部服务，总耗时短）
- 每个维度内部可调用 LLM 做语义分析（temperature=0.1，追求一致性）
- LLM prompt 中明确要求**只输出 JSON 格式的检查结果**
- 每个维度超时 **180s**（3 分钟），总体超时 **600s**（10 分钟）

### 汇总评分

```
overall_score = Σ(dimension.score × 维度权重) / Σ(维度权重)
有评分的维度参与计算，skipped 维度不计入。

维度权重: api_consistency=25%, erd_completeness=25%, state_machine_closure=20%, 
          prototype_spec_alignment=15%, security_baseline=15%

total_issues = Σ(len(dimension.issues))
```

---

## 五、产出物

### 5.1 产物存储

| 产物 | 存储位置 | 说明 |
|------|---------|------|
| 设计检查报告 | `agent_results` WHERE agent_key='A5' → `artifact.check_report` | 按维度分组的完整报告 |

### 5.2 检查报告结构

```json
{
  "check_report": {
    "overall_score": 0.78,
    "total_issues": 8,
    "dimensions": [
      {
        "dimension": "api_consistency",
        "label": "API 一致性",
        "score": 0.85,
        "issues": [
          {
            "id": "api_001",
            "severity": "major",
            "description": "Spec 定义的 GET /users/{id} 但 OpenAPI 中缺少 404 响应定义",
            "suggestion": "在 paths./users/{id}.get.responses 中补充 '404': {...}",
            "location": "openapi_schema.paths./users/{id}.get.responses"
          }
        ]
      },
      {
        "dimension": "erd_completeness",
        "label": "ERD 完整性",
        "score": 0.70,
        "issues": []
      },
      {
        "dimension": "state_machine_closure",
        "label": "状态机闭合性",
        "score": null,
        "status": "skipped",
        "issues": [],
        "skip_reason": "llm_timeout"
      }
    ],
    "summary": "整体设计质量良好。API 一致性和 ERD 完整性通过，状态机闭合性检查因 LLM 超时跳过。建议在 Gate1 审批前人工复核。",
    "generated_at": "ISO 8601"
  }
}
```

> 每个维度的 `score` 为 0-1 浮点数（Gate1 审批页展示时转为百分制）。`score=null, status='skipped'` 表示该维度未执行（超时/A4缺失），不计入 overall_score。`status` 可能值：已评分维度省略此字段（等同于 `checked`），skipped 维度显式标注。**不输出 pass/fail**——各维度独立评定，供 Gate1 审批人参考。

### 5.3 agent_results.A5 artifact

```json
{
  "check_report": {},
  "non_blocking": true,
  "generated_at": "ISO 8601"
}
```

> `non_blocking: true` 是语义标记，Orchestrator 读取此字段确认 A5 不阻断流程。

---

## 六、输入/输出接口

### context.ready.A5 输入结构

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "a3_output": {
    "prototype_url": "string",
    "screens": [
      {"name": "列表页", "state": "default", "url": "..."}
    ]
  },
  "a4_output": {
    "spec_doc": {},
    "openapi_schema": {},
    "erd_diagram": {},
    "ddl_statements": "string"
  },
  "a4_missing": false
}
```

### agent.result.A5 输出结构

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "check_report": {},
  "timestamp": "ISO 8601"
}
```

---

## 七、NATS 事件协议

| 事件 | 方向 | 触发时机 |
|------|------|---------|
| `context.ready.A5` | Orchestrator → A5 | A4 Spec 完成后 / A4 超时跳过后 |
| `agent.result.A5` | A5 → Orchestrator | 五维检查全部完成 |

### A4 缺失场景

```
Orchestrator 跳过 A4（超时降级）:
  → context.ready.A5 中 a4_missing=true
  → 仅基于 A3 原型执行 prototype_spec_alignment 维度
  → 其他维度标注为 'skipped'，原因为 'a4_missing'
  → agent.result.A5 正常发布，Orchestrator 继续进入 Gate1
```

---

## 八、异常处理

| 场景 | 策略 |
|------|------|
| LLM 不可用 | 逐维度降级为规则检查（正则/结构比对），准确性降低但不阻断 |
| 某维度 LLM 超时（3min） | 该维度 score=null，标注 `status='skipped'`，原因 `'llm_timeout'` |
| 全部维度超时（10min） | 重试 1 次，仍失败 → Orchestrator 写入 agent_results (A5, status='skipped')，Gate1 无检查报告 |
| A4 产物缺失（a4_missing） | 仅检查 prototype_spec_alignment 维度，其余标记 skipped |
| 产物格式异常（JSON 解析失败） | 记录 parse_error，继续检查其余可读部分 |
| NATS 投递失败 | Outbox 重试，5 次入死信队列 |

---

## 九、总结

| 维度 | 内容 |
|------|------|
| **入口** | `context.ready.A5`（A4 完成 / A4 超时跳过） |
| **出口** | `agent.result.A5`（五维检查全部完成或部分 skipped） |
| **核心产物** | 设计检查报告（五个维度 × 独立评分 × issues 列表） |
| **产物存储** | `agent_results`（A5, cycle 快照） |
| **交互模式** | 纯 NATS 调度，无用户交互 |
| **阻断性** | **非阻断**——无论结果如何，Orchestrator 始终继续进入 Gate1 |
| **返工机制** | A5 不接受返工调度（Gate1 拒绝后仅 A4/A3 返工，A5 随 A4 修订后自动重新执行） |

---

## 十、实施建议

### Phase 1：五维核心（~3 天）
- A5 Agent 核心流水线：五维顺序检查 → 汇总评分 → agent_results 持久化
- 每维度独立 LLM 调用（temperature=0.1），LLM 不可用时降级为规则检查

### Phase 2：降级 + 集成（~2 天）
- A4 缺失场景（仅检查 prototype_spec_alignment）
- 维度级超时降级（3min/维度，10min 总体）
- 与 Gate1 审批页集成（A5 报告面板）

### Phase 3：全链路联调（~2 天）
- A4 → A5 → Gate1 完整链路
- Gate1 拒绝 → A4 修订 → A5 重新检查

---

## 十一、与 A4/Gate1 的协作边界

| 维度 | A4 Spec撰写 | A5 设计检查 | Gate1 审批 |
|------|-----------|-----------|----------|
| **类型** | Agent | Agent | Gate（人工） |
| **输入** | context.ready.A4 | context.ready.A5 | context.ready.gate1 |
| **输出** | agent.result.A4 | agent.result.A5 | agent.result.gate1.* |
| **阻断性** | — | **非阻断** | **阻断**（pass/reject） |
| **Gate1 打回** | 默认回退目标 | 不接受返工（随 A4 重跑） | — |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.1
