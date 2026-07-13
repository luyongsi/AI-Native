# Gate0 产品审批 - 完整设计文档

## 文档信息
- **版本**: v3.5
- **日期**: 2026-07-10
- **状态**: 完整设计文档（对齐系统状态机 v2.4 + 阶段一数据字典 v1.3）
- **参考**: [系统状态机与信息流设计](../系统状态机与信息流设计.md) · [阶段一数据字典](./阶段一-数据字典.md)
- **说明**: Gate0 是阶段一的最后节点。MC Backend 收到 `context.ready.gate0` 后预创建 approvals 记录，审批人提交后 Gate0 自行更新审批结果，通过 NATS 发布。**本文档中所有数据结构、字段名、枚举值以数据字典为准。**

---

## 一、通信架构

Gate0 是**人工审批节点**：

```
┌──────────┐   HTTP (REST)    ┌──────────────┐          NATS          ┌──────────────┐
│   前端    │ ◄──────────────► │  MC Backend  │ ◄─────────────────────► │ Orchestrator │
│ (审批人)  │                  │   (Gate0)    │  context.ready.gate0   │              │
│          │                  │              │  agent.result.gate0.*  │              │
└──────────┘                  └──────────────┘                        └──────────────┘
```

- **NATS**：接收 `context.ready.gate0`，发布 `agent.result.gate0.pass` / `agent.result.gate0.reject`
- **HTTP REST**：前端获取审批上下文、提交决策
- Gate0 **自行写入** `approvals` 表，Orchestrator 只订阅结果做编排

---

## 二、Gate0 在阶段一中的位置

```
阶段一：需求分析
┌──────────────────────────────────────────────────┐
│  A1 需求分析 ──► A2 知识分析 ──► 【Gate0】       │
│                          ┌─────────┴─────────┐   │
│                          │   产品经理审批     │   │
│                          └─────────┬─────────┘   │
│                    ✅ pass          ❌ reject     │
│                       │                │         │
└───────────────────────┼────────────────┼─────────┘
                        ▼                ▼
                   进入阶段二      打回 A1 修订
                   （A3 开始）    （完整链路重走，cycle 递增）
```

---

## 三、审批职责

| 维度 | 内容 |
|------|------|
| **审批角色** | 产品经理 / 需求负责人 |
| **审批对象** | A1 草案（`requirements` + `agent_results` A1）+ A2 分析（`agent_results` A2） |
| **决策类型** | pass / reject |
| **审批人数** | 单人审批 |

---

## 四、审批流程

### 4.1 正常流程

```
Orchestrator 查询 DB（requirements + agent_results A1/A2 MAX cycle）
    → build_context → context.ready.gate0（NATS）
    → MC Backend 收到 context.ready.gate0:
        → 在 approvals 表预创建一行: id=UUID, status='pending', req_id, session_id, cycle
        → 返回 approval_id（用于后续 API 路由）
        → 通知审批人
    → 审批人打开页面（GET /api/approvals/{approval_id}/context）
    → 查看：需求草案 + 验收标准 + 线框图 + 可行性评估 + 待确认 + 冲突点
    → 决策：
        ├── ✅ 通过 → Gate0 更新 approvals: status='decided', decision='pass', reviewer_*
        │     → 发布 agent.result.gate0.pass → Orchestrator → 阶段二
        └── ❌ 拒绝 → Gate0 更新 approvals: status='decided', decision='reject', reject_reasons, revision_guidance, reviewer_*
              → 发布 agent.result.gate0.reject → Orchestrator → 打回链路
```

### 4.2 审批页面

```
┌─────────────────────────────────────────────────┐
│  Gate0 需求审批                    Cycle: 0     │
├─────────────────────────────────────────────────┤
│  📋 需求草案（A1 产出）    置信度：0.85         │
│  ┌─────────────────────────────────────────────┐ │
│  │ 标题/描述/实体/用例/验收标准/约束/风险       │ │
│  │ 线框图：[查看]                               │ │
│  └─────────────────────────────────────────────┘ │
│  🔍 知识分析（A2 产出）    质量评分：0.72       │
│  ┌─────────────────────────────────────────────┐ │
│  │ 技术/业务可行性  风险级别  待确认清单  冲突点 │ │
│  │ ⚠️ A2 缺失标记（a2_missing=true 时显示）    │ │
│  └─────────────────────────────────────────────┘ │
│  ─────────────────────────────────────           │
│  ○ 通过    ○ 拒绝                               │
│  拒绝原因（可多选）：□需求不清晰 □需求不完整 ... │
│  修订指引（拒绝时必填）：[______]                 │
│  [提交审批]                                      │
└─────────────────────────────────────────────────┘
```

### 4.3 拒绝原因枚举

遵循 [数据字典 §6.3](./阶段一-数据字典.md#63-拒绝原因--枚举规范)，含 UI 标签到 `category` 枚举值的映射。

> 审批页 mockup 中的中文标签（"需求不清晰"等）仅用于 UI 展示，提交 API 时 `reject_reasons[].category` 使用英文枚举值。

### 4.4 通过后

- Gate0 写入 approvals → 发布 `agent.result.gate0.pass`
- Orchestrator → event_log → `requirements.status = 'approved'` → 启动阶段二（A3）
- Gate0 不参与后续流程

---

## 五、产出物

Gate0 **自行写入** approvals 表（MC Backend 预创建 + 审批人提交后更新），结构见 [数据字典 §6.2](./阶段一-数据字典.md#62-审批记录结构)。

| 字段 | 说明 |
|------|------|
| `id` | 审批 UUID |
| `req_id`, `session_id`, `gate_level`, `cycle` | 路由信息 |
| `decision` | `"pass"` / `"reject"` |
| `reject_reasons` | `[{category, description}]`（拒绝时） |
| `revision_guidance` | 修订指引文本（拒绝时必填） |
| `reviewer_user_id`, `reviewer_name` | 审批人 |
| `reviewed_at` | 审批时间 |

> `approvals` 由 Gate0 写入，是 Gate0 的产物。Orchestrator 仅订阅 NATS 事件获取结果。

---

## 六、NATS 事件协议

完整定义见 [数据字典 §6.4](./阶段一-数据字典.md#64-nats-事件)。

| 事件 | 方向 | 触发时机 |
|------|------|---------|
| `context.ready.gate0` | Orchestrator → Gate0 | Orchestrator 查询 DB 后 build_context |
| `agent.result.gate0.pass` | Gate0 → Orchestrator | 审批通过 + approvals 已写入 |
| `agent.result.gate0.reject` | Gate0 → Orchestrator | 审批拒绝 + approvals 已写入 |

---

## 七、SLA 与超时策略

| 维度 | 内容 |
|------|------|
| **SLA** | 1 小时 |
| **超时行为** | 通知审批人，**不自动通过** |
| **审批提醒** | 超时前 15 分钟提醒 |

---

## 八、与 A1/A2 的协作关系

| 维度 | A1 | A2 | Gate0 |
|------|----|----|-------|
| **类型** | Agent | Agent | Gate（人工审批） |
| **输入** | 用户 HTTP / `context.ready.A1`（仅打回） | `context.ready.A2` | `context.ready.gate0` |
| **产物存储** | `requirements` + `agent_results` (A1) | `agent_results` (A2) | `approvals` 表（自写入） |
| **发布事件** | `agent.result.A1` | `agent.result.A2` | `agent.result.gate0.pass` / `agent.result.gate0.reject` |
| **自动化** | AI | AI | **人工** |

### Gate0 拒绝后链路

```
Gate0 写入 approvals (decision='reject') + 发布 agent.result.gate0.reject
Orchestrator:
  → event_log (IN)
  → requirements: gate_rejection_count += 1, status='gate_rejected'
  → dialogue_sessions: status='reopened'
  → dialogue_messages: 注入 gate_rejection
  → 发布 context.ready.A1 (cycle = 新 gate_rejection_count)
  → event_log (OUT)
→ A1 修订 → agent.result.A1 → A2 → Gate0 重新审批（完整重走）
```

---

## 九、前端交互

### 9.1 审批 API

**获取审批上下文** — `GET /api/approvals/{approval_id}/context`

返回结构见 [数据字典 §6.4](./阶段一-数据字典.md#contextreadygate0orchestrator--gate0) 中 `context.ready.gate0` 的 `a1_output` + `a2_output`（MC Backend 从 DB 读取组装）。

**提交决策** — `POST /api/approvals/{approval_id}/decide`

通过：
```json
{ "decision": "pass" }
```

拒绝（遵循 [数据字典 §6.4](./阶段一-数据字典.md#agentresultgate0rejectgate0--orchestrator)）：
```json
{
  "decision": "reject",
  "reject_reasons": [
    {"category": "requirement_unclear", "description": "需求描述不够清晰"}
  ],
  "revision_guidance": "建议补充用户角色权限矩阵"
}
```

### 9.2 审批列表

```
┌──────────────────────────────────────────────────┐
│  Gate0 待审批                                     │
│ 需求                  Cycle  提交时间    SLA    操作 │
│ 用户管理系统 v3        0      10:00    剩45min  [审批] │
│ 订单通知功能           2      09:30    剩15min  [审批] │
└──────────────────────────────────────────────────┘
```

---

## 十、异常处理

| 场景 | 策略 |
|------|------|
| Gate0 审批超时（1h） | 通知不自动通过 |
| A2 缺失（a2_missing=true） | 审批页标记 ⚠️ |
| NATS 投递失败 | Outbox 重试，5 次入死信队列 |
| 重复提交 | 幂等，同一 approval_id 只允许一次决策 |

---

## 十一、实施建议

### Phase 1: 基础审批（3 天）
- `approvals` 表 migration + API + 前端审批页 + NATS 事件

### Phase 2: SLA + 通知（2 天）
- 站内通知 + SLA 倒计时 + 审批列表

### Phase 3: 打回链路联调（2 天）
- Gate0 写 approvals → reject 事件 → Orchestrator 打回 → A1→A2→Gate0 全链路多轮

---

## 十二、总结

- **入口**：`context.ready.gate0`（Orchestrator 查询 DB 构建）
- **决策**：审批人通过/拒绝
- **产物**：Gate0 **自行写入** `approvals` 表
- **通过出口**：`agent.result.gate0.pass` → Orchestrator → 阶段二
- **拒绝出口**：`agent.result.gate0.reject` → Orchestrator → `gate_rejection_count+=1` → `context.ready.A1` → 全链路重走

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-10
**版本**: v3.5（对齐阶段一数据字典 v1.3）
**数据规范**: [阶段一数据字典](./阶段一-数据字典.md)
