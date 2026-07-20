# A2 知识分析 Agent - 完整设计文档

## 文档信息
- **版本**: v3.5
- **日期**: 2026-07-10
- **状态**: 完整设计文档（已对齐系统状态机 v2.4 + 阶段一数据字典 v1.3）
- **参考**: [系统状态机与信息流设计](../系统架构/系统状态机与信息流设计.md) · [阶段一数据字典](./阶段一-数据字典.md)
- **说明**: A2 负责阶段一的知识分析，在 A1 产出需求草案后执行，为 Gate0 产品审批提供决策依据。**本文档中所有数据结构、字段名、枚举值以数据字典为准。**

---

## 一、通信架构

A2 采用**纯 NATS 调度**模型：

```
┌──────────────┐        NATS         ┌──────────────┐
│ Orchestrator │ ◄─────────────────► │    A2 Agent   │
│              │  context.ready.A2   │              │
│              │  agent.result.A2    │              │
└──────────────┘                     └──────┬───────┘
                                            │
                                     MCP 调用（内部）
                                            │
                                     ┌──────┴───────┐
                                     │  知识库 MCP   │
                                     └──────────────┘
```

- **NATS**：接收 Orchestrator 调度（`context.ready.A2`），发布完成结果（`agent.result.A2`）
- **MCP**：A2 内部通过 MCP 协议调用知识库服务
- A2 不与用户直接交互，无 HTTP 接口

---

## 二、A2 在阶段一中的位置

```
阶段一：需求分析
┌─────────────────────────────────────────┐
│                                         │
│  A1 需求分析 ──► A2 知识分析 ──► Gate0  │
│                                       │
│  A1 产出需求草案（requirements + agent_results A1）
│  A2 产出（agent_results A2）
│  Gate0 综合审批 A1+A2 产出              │
└─────────────────────────────────────────┘
              │
              ▼ Gate0 通过后进入阶段二（A3，与 A2 无关）
```

### 核心流程

```
Orchestrator 收到 agent.result.A1
    → 写入 event_log → 查询 DB: requirements + agent_results (A1, MAX cycle)
    → build_context → context.ready.A2
    → A2 执行分析 → 持久化 agent_results (A2, cycle) → agent.result.A2
    → Orchestrator: event_log → 查询 DB → context.ready.gate0
```

---

## 三、职责与设计理念

### 3.1 核心职责

1. **语义搜索** — 通过知识库 MCP 检索相似历史需求和已知问题
2. **可行性评估** — 评估需求的技术可行性与业务可行性，给出风险级别
3. **冲突识别** — 识别需求与现有系统的冲突点
4. **待确认清单** — 生成需产品经理进一步确认的事项列表

### 3.2 关键设计原则

1. **NATS 驱动**：完全由 Orchestrator 调度
2. **MCP 增强**：通过知识库 MCP 检索历史数据
3. **产物自持久化**：执行完成后写入 `agent_results` (agent_key='A2')
4. **优雅降级**：MCP/LLM 不可用时产出降级知识包，`status='empty'`（若完全无数据）
5. **A2 不设 `a2_missing`**：此标记仅由 Orchestrator 在跳过 A2 时注入到 `context.ready.gate0`
6. **范围收敛**：A2 只到 Gate0

---

## 四、核心处理流程

### 4.1 执行阶段

```
阶段 1: 语义搜索     → 通过 MCP 检索相似需求、已知问题、领域风险
阶段 2: 可行性评估   → 评估技术可行性、业务可行性、风险级别
阶段 3: 冲突检测     → 识别与现有系统的冲突点
阶段 4: 生成待确认   → 汇总需产品经理确认的事项清单
阶段 5: 持久化+发布  → 写入 agent_results (A2, cycle) + 发布 agent.result.A2
```

### 4.2 各阶段详情

- **阶段 1 — 语义搜索**：调用 MCP `search_similar_requirements` / `search_known_issues` / `search_domain_risks`
- **阶段 2 — 可行性评估**：结构见 [数据字典 §5.2-5.3](./阶段一-数据字典.md#52-产物结构)
- **阶段 3 — 冲突检测**：枚举见 [数据字典 §5.5](./阶段一-数据字典.md#55-冲突点--枚举规范)
- **阶段 4 — 生成待确认清单**：枚举见 [数据字典 §5.4](./阶段一-数据字典.md#54-待确认清单--枚举规范)
- **阶段 5 — 发布**：持久化 `agent_results` (`agent_key='A2'`, `cycle`, `status`) → 发布 `agent.result.A2`

---

## 五、产出物

A2 产出存入 `agent_results` 表，结构遵循 [数据字典 §5](./阶段一-数据字典.md#五a2-数据规范)。

| 产物 | 说明 |
|------|------|
| `feasibility_assessment` | 技术可行性、业务可行性、风险级别、风险理由 |
| `confirmation_checklist` | 待确认事项列表 |
| `conflicts` | 冲突点列表 |
| `quality_score` | 质量评分 0-1 |

> `agent.result.A2` **不含** `a2_missing`。

---

## 六、输入/输出接口

### 6.1 输入：context.ready.A2

完整结构见 [数据字典 §5.6](./阶段一-数据字典.md#contextreadya2orchestrator--a2)。

关键字段：`req_id`, `session_id`, `cycle`, `requirement_draft`, `wireframe_url`, `confidence_score`

### 6.2 输出：agent.result.A2

完整结构见 [数据字典 §5.6](./阶段一-数据字典.md#agentresulta2a2--orchestrator)。

发布前必须持久化到 `agent_results`，payload 与持久化产物结构一致。

---

## 七、依赖与集成

### 7.1 MCP 依赖

| MCP 工具 | 用途 | 降级行为 |
|----------|------|----------|
| `search_similar_requirements` | 语义搜索相似历史需求 | 返回空列表 |
| `search_known_issues` | 检索已知问题/Bug | 返回空列表 |
| `get_domain_risks` | 获取领域风险信息 | 使用通用风险模板 |

### 7.2 降级策略

- MCP 不可用 → 启发式分析，`quality_score` < 0.4
- LLM 不可用 → 模板生成可行性评估
- 全部降级 → 仍产出最小知识包，`status='empty'`
- A2 **被跳过**（超时）→ Orchestrator 写入 `agent_results` (A2, status='skipped')，`context.ready.gate0` 中 `a2_missing=true`

---

## 八、NATS 事件协议

完整定义见 [数据字典 §5.6](./阶段一-数据字典.md#56-nats-事件)。

| 事件 | 方向 | 触发时机 |
|------|------|---------|
| `context.ready.A2` | Orchestrator → A2 | Orchestrator 查询 DB 后 build_context |
| `agent.result.A2` | A2 → Orchestrator | A2 分析完成并持久化后 |

---

## 九、异常处理

| 场景 | 策略 |
|------|------|
| A2 执行超时（10 分钟） | Orchestrator 重试 1 次 |
| A2 重试仍超时 | Orchestrator 写入 agent_results (status='skipped')，`context.ready.gate0` 中 `a2_missing=true` |
| 知识库 MCP 不可用 | 降级分析，`quality_score` < 0.4（A2 正常执行，写 agent_results） |
| 通用 Agent 超时（30 分钟） | 重试 1 次，连续 2 次超时通知升级 |
| NATS 投递失败 | Outbox 重试，5 次入死信队列 |

---

## 十、质量评分

| 分数 | 含义 | 条件 |
|------|------|------|
| > 0.7 | 完整知识包 | MCP 全部成功 + 可行性完整 + 冲突检测完整 |
| 0.4-0.7 | 可用知识包 | 至少可行性评估完成 |
| < 0.4 | 降级知识包 | MCP 不可用，启发式分析 |

---

## 十一、与 A1 的协作边界

| 维度 | A1 | A2 |
|------|----|----|
| **输入** | 用户 HTTP / `context.ready.A1`（仅打回） | `context.ready.A2`（Orchestrator 查询 DB） |
| **通信** | HTTP+SSE + NATS | NATS + MCP |
| **产物存储** | `requirements` + `agent_results` (A1) | `agent_results` (A2) |
| **发布事件** | `agent.result.A1` | `agent.result.A2` |
| **cycle** | 从 `gate_rejection_count` 获取 | 从 `context.ready.A2` 透传 |

---

## 十二、总结

- **入口**：`context.ready.A2`（Orchestrator 查询 DB 构建，含 cycle）
- **出口**：持久化 `agent_results` (A2, cycle) + 发布 `agent.result.A2`
- **循环**：Gate0 打回 → A1 修订 → `context.ready.A2`（cycle 递增）→ 重新分析
- **审计**：每轮产物通过 `agent_results WHERE agent_key='A2' AND cycle=?` 查询

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-10
**版本**: v3.5（对齐阶段一数据字典 v1.3）
**数据规范**: [阶段一数据字典](./阶段一-数据字典.md)
