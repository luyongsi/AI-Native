# Gate2 架构审批 - 完整设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-15
- **状态**: 完整设计文档（从阶段三-完整设计 §6 + 数据字典 + PRD + 开发设计提取）
- **参考**: [系统状态机与信息流设计](../系统架构/系统状态机与信息流设计.md) · [阶段三数据字典](./阶段三-数据字典.md) · [阶段三完整设计](./阶段三-完整设计.md) · [Orchestrator完整规格](../系统架构/Orchestrator完整规格.md)
- **说明**: Gate2 是阶段三的最后节点。MC Backend 收到 `context.ready.gate2` 后预创建 approvals 记录（gate_level=2），审批人提交后 Gate2 自行更新审批结果，通过 NATS 发布。**本文档中所有数据结构、字段名、枚举值以阶段三数据字典为准。**

---

## 一、通信架构

Gate2 是**人工审批节点**（与 Gate0/Gate1 同构）：

```
┌──────────┐   HTTP (REST)    ┌──────────────┐          NATS          ┌──────────────┐
│   前端    │ ◄──────────────► │  MC Backend  │ ◄─────────────────────► │ Orchestrator │
│ (审批人)  │                  │   (Gate2)    │  context.ready.gate2   │              │
│          │                  │              │  agent.result.gate2.*  │              │
└──────────┘                  └──────────────┘                        └──────────────┘
```

- **NATS**：接收 `context.ready.gate2`，发布 `agent.result.gate2.pass` / `agent.result.gate2.reject`
- **HTTP REST**：前端获取审批上下文、提交决策（含 `a6_rework` / `a7_rework` 独立控制）
- Gate2 **自行写入** `approvals` 表（`gate_level=2`），Orchestrator 只订阅结果做编排

---

## 二、Gate2 在阶段三中的位置

```
阶段三：技术准备
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│  ┌─ A6 Spec 拆解 ─┐           ┌─ A8 架构评审 ─┐                   │
│  │  (并行执行)     │──GATHER──►│  (自动触发)    │──► 【Gate2】      │
│  └────────────────┘           └───────────────┘    ┌──────────┐   │
│  ┌─ A7 测试生成 ─┐                    │           │架构师审批│   │
│  │  (并行执行)     │                   │           └────┬─────┘   │
│  └────────────────┘                    │        ✅ pass  ❌ reject │
│                                        │           │       │      │
│  A6↔A8 对抗循环（P1）:   │◄───────────┘           ▼       ▼      │
│  score ∈ [50,70) 时     │                  进入阶段四  打回 A6+A7 │
│  ≤2 轮自动修正          │                  (A9 开始)  (同cycle修订)│
└────────────────────────────────────────────────────────────────────┘
```

### 核心流程

```
A6 + A7 都完成
  → Orchestrator GATHER → tech_prep_status='reviewing'
  → 发布 context.ready.A8
  → A8 执行架构评审 → agent.result.A8
  → Orchestrator build_context → context.ready.gate2
  → MC Backend 预创建 approvals (gate_level=2)
  → 审批人决策:
      ├── ✅ pass  → agent.result.gate2.pass
      │             → Orchestrator: phase='development' → context.ready.A9
      └── ❌ reject → agent.result.gate2.reject
                    → Orchestrator: tech_prep_revision_count += 1
                    → 根据 a6_rework/a7_rework 重发 context.ready.A6/A7
```

---

## 三、审批职责

| 维度 | 内容 |
|------|------|
| **审批角色** | 架构师 / Tech Lead |
| **审批对象** | A6 DAG（任务依赖图 + 节点详情）+ A7 测试用例（类型/优先级分布 + 详情）+ A8 评审报告（verdict + score + violations + suggestions） |
| **决策类型** | pass / reject |
| **审批人数** | 单人审批 |
| **A8 报告作用** | **辅助决策参考**，非绑定。审批人自行判断是否采纳 A8 建议 |
| **特殊场景** | A6↔A8 对抗循环结束后产生《架构分歧报告》，需审批人人工裁决 |

---

## 四、审批流程

### 4.1 正常流程

```
Orchestrator 收到 agent.result.A8
  → 检查 A6↔A8 对抗循环条件
  ├── 需对抗 (score ∈ [50,70) 且 revision_count < 2):
  │     → 调度 A6 修正 → A8 复评审 → 重复直至上限
  │     → 上限/score < 50 → 生成分歧报告 → build_context → Gate2
  └── 不需对抗 (score ≥ 70 或循环依赖):
        → build_context → context.ready.gate2 (NATS)

MC Backend 收到 context.ready.gate2:
  → 在 approvals 表预创建: id=UUID, gate_level=2, status='pending'
  → 返回 approval_id (用于后续 API)
  → 通知审批人 (飞书/邮件)

审批人打开页面 (GET /api/approvals/{approval_id}/context?gate_level=2):
  → 查看: A6 DAG + A7 测试用例 + A8 评审报告 + 安全红线 + 降级提示
  → 决策:
      ├── ✅ 通过 → Gate2 更新 approvals: decision='pass'
      │     → 发布 agent.result.gate2.pass
      │     → Orchestrator: phase='development', tech_prep_status='tech_prep_completed'
      └── ❌ 拒绝 → Gate2 更新 approvals: decision='reject', reject_reasons, revision_guidance, a6_rework, a7_rework
            → 发布 agent.result.gate2.reject
            → Orchestrator: tech_prep_revision_count += 1, tech_prep_status='revising'
            → 打回 A6 + A7 (根据 a6_rework/a7_rework 独立控制)
```

### 4.2 审批页面

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Gate2 架构审批                               Cycle: 0  修订轮次: 1/∞   │
├──────────────────────────────────────────────────────────────────────────┤
│  📋 基本信息                                                              │
│  req_id: xxx | 需求标题: 用户管理系统 v3 | tech_prep_revision_count: 0    │
├──────────────────────────────────────────────────────────────────────────┤
│  📐 A6 任务 DAG                              节点: 12  预估工时: 45h      │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  [task-01] 用户认证模块  ◄── [task-02] 权限管理  ◄── [task-03] ...  │  │
│  │  complexity: high  ⚠️需人工审核     complexity: medium               │  │
│  │  关键路径: task-01 → task-04 → task-08 → task-12                    │  │
│  │  并行组: [task-02, task-03], [task-06, task-07]                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────────────┤
│  🧪 A7 测试用例                              总计: 24 条                  │
│  P0: 10 | P1: 8 | P2: 6                                                  │
│  unit: 8 | integration: 6 | e2e: 4 | visual: 3 | api: 3                  │
│  [展开查看详情]                                                            │
├──────────────────────────────────────────────────────────────────────────┤
│  📊 A8 架构评审报告                          verdict: ⚠️ fail  score: 62  │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ 🔴 critical: 缺少认证授权模块 (节点 task-01 steps 无 auth handler)  │  │
│  │ 🟠 warning:  前端直连数据库 (task-06 引用 db 但无 API 中间层)       │  │
│  │ 🟡 info:     建议为 task-08 添加缓存层                                │  │
│  │ 建议: 在 task-01 中增加 security_setup 子任务，task-06 改为 API 调用  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────────────────┤
│  🛡️ 安全红线独立展示（必审）                                              │
│  ├── 认证/授权: ✅ 已覆盖                                                  │
│  ├── SQL 注入: ✅ 已检查                                                  │
│  ├── 敏感数据暴露: ⚠️ User 表含 password_hash 但无加密步骤标注            │
│  └── 硬编码密钥: ✅ 未检出                                                 │
├──────────────────────────────────────────────────────────────────────────┤
│  ⚠️ 降级提示 (若有): a6_missing / a7_missing / a8_missing                  │
├──────────────────────────────────────────────────────────────────────────┤
│  SLA: 剩余 3h30min | 已预警: 否                                          │
├──────────────────────────────────────────────────────────────────────────┤
│  审批操作:                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                          [✅ 通过]  [❌ 拒绝]                         │  │
│  │  拒绝时 (可选独立控制):                                               │  │
│  │  ☑ 要求 A6 重新拆解 (a6_rework)   ☑ 要求 A7 重新生成 (a7_rework)   │  │
│  │  拒绝原因: ____________________________________________             │  │
│  │  修订指引: ____________________________________________             │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 五、审批数据结构

审批记录存储在 `approvals` 表（复用阶段一/二已有表结构），通过 `gate_level=2` 区分。Gate2 特有字段见 [阶段三数据字典 §2.3](./阶段三-数据字典.md#23-approvals-表扩展)。

| 字段 | 说明 |
|------|------|
| `id` | 审批 UUID |
| `req_id`, `session_id`, `gate_level=2`, `cycle` | 路由信息 |
| `decision` | `"pass"` / `"reject"` |
| `reject_reasons` | `[{category, description}]`（拒绝时必填） |
| `revision_guidance` | 修订指引文本（拒绝时必填） |
| `a6_rework` | Gate2 特有：是否要求 A6 返工（默认 true） |
| `a7_rework` | Gate2 特有：是否要求 A7 返工（默认 true） |
| `reviewer_user_id`, `reviewer_name` | 审批人 |
| `reviewed_at` | 审批时间 |

> `approvals` 由 Gate2 写入，是 Gate2 的产物。Orchestrator 仅订阅 NATS 事件获取结果。

---

## 六、NATS 事件协议

完整定义见 [阶段三数据字典 §6](./阶段三-数据字典.md)。

| 事件 | 方向 | 触发时机 | Nats-Msg-Id 格式 |
|------|------|---------|-----------------|
| `context.ready.gate2` | Orchestrator → Gate2 | A8 评审完成（或对抗循环结束）后 build_context | `{req_id}-context.ready.gate2-{cycle}` |
| `agent.result.gate2.pass` | Gate2 → Orchestrator | 审批通过 + `approvals` 已写入 | `{req_id}-agent.result.gate2.pass-{cycle}` |
| `agent.result.gate2.reject` | Gate2 → Orchestrator | 审批拒绝 + `approvals` 已写入 | `{req_id}-agent.result.gate2.reject-{cycle}` |

### Consumer 配置

| Consumer | 订阅 Subject | 交付策略 | ack_wait |
|----------|-------------|---------|----------|
| `gate2_consumer` | `context.ready.gate2` | All, 按 req_id 有序 | 60s |

---

## 七、SLA 与超时策略

| 时间点 | 动作 | 实现方式 |
|--------|------|---------|
| 审批创建 | 系统发送通知（飞书/邮件） | MC Backend API → 消息服务 |
| 2h | 预警通知（提醒审批人 + 抄送直属上级） | Orchestrator Gate SLA Activity (T1) |
| 4h | 超时升级通知（通知技术总监） | Orchestrator Gate SLA Activity (T1) |
| 4h+ | 持续等待人工审批（**不自动通过**） | Orchestrator 无限等待 Gate signal |

> **关键原则**：Gate2 是阶段三最关键的人控节点，审批人不响应时持续等待，不自动放行。可手动指派替代审批人。

---

## 八、Gate2 特有的打回逻辑

### 8.1 a6_rework / a7_rework 独立控制

Gate2 与 Gate1 的关键区别：Gate2 允许审批人独立控制 A6 和 A7 的返工范围。

| a6_rework | a7_rework | 场景 | 说明 |
|-----------|-----------|------|------|
| true | true | 完整打回 | DAG 和测试用例都需要修订（默认） |
| true | false | 仅 DAG 修订 | 测试用例覆盖足够，只需修正 DAG 结构 |
| false | true | 仅测试修订 | DAG 结构合理，但测试覆盖不足 |
| false | false | 无效打回 | 前端应阻止此组合（至少一项为 true） |

### 8.2 打回后链路

```
Gate2 reject
  → Gate2 写入 approvals (decision='reject', a6_rework, a7_rework)
  → 发布 agent.result.gate2.reject
  → Orchestrator:
      ├── tech_prep_revision_count += 1
      ├── tech_prep_status = 'revising'
      ├── tech_prep_status = 'decomposing' (重新进入调度)
      ├── 若 a6_rework=true → 发布 context.ready.A6 (含 revision_context)
      │     revision_context 包含: gate2_rejection (reject_reasons + revision_guidance) + A8 报告
      ├── 若 a7_rework=true → 发布 context.ready.A7 (含 revision_context)
      └── cycle 不变（不触发需求层面的重新理解）
  → A6 (若触发) 接收 revision_context，重新拆解 DAG，同一 cycle UPSERT
  → A7 (若触发) 接收 revision_context，重新生成测试用例，同一 cycle UPSERT
  → A6+A7 完成后 → GATHER → context.ready.A8 → A8 重新评审 → Gate2 重新审批
```

### 8.3 与 Gate1 打回的区别

| 维度 | Gate1 打回 | Gate2 打回 |
|------|-----------|-----------|
| **计数器** | `design_revision_count += 1` | `tech_prep_revision_count += 1` |
| **cycle 变化** | 不变 | 不变 |
| **打回目标** | A4（默认）/ A3（若 a3_rework=true） | A6 (若 a6_rework=true) / A7 (若 a7_rework=true) |
| **独立控制** | `a3_rework` 单字段 | `a6_rework` + `a7_rework` 双字段 |
| **附带上下文** | rejection reasons + guidance | rejection reasons + guidance + A8 报告 |
| **重走范围** | A4 (或 A3→A4→A5→Gate1) | A6 (或 A7) → A8 → Gate2 |

---

## 九、前端交互

### 9.1 审批 API

**获取审批上下文** — `GET /api/approvals/{approval_id}/context?gate_level=2`

返回结构：MC Backend 从 DB 组装 `context.ready.gate2` 的完整 payload，包含：
- A6 DAG 产物（从 `task_dags` 最新版本 + `agent_results.A6`）
- A7 测试用例（从 `test_assets` + `agent_results.A7`）
- A8 评审报告（从 `agent_results.A8`）
- 安全红线检查结果（从 `agent_results.A8`.review.violations 中 severity=critical 项）
- 降级标记（a6_missing / a7_missing / a8_missing）
- 分歧报告（若 A6↔A8 对抗循环已触发）

**提交决策** — `POST /api/approvals/{approval_id}/decide`

通过：
```json
{ "decision": "pass" }
```

拒绝（遵循 [阶段三数据字典 §7.3](./阶段三-数据字典.md#73-agentresultgate2rejectgate2--orchestrator)）：
```json
{
  "decision": "reject",
  "reject_reasons": [
    {"category": "dag_incomplete", "description": "DAG 缺少数据库迁移任务节点"},
    {"category": "architecture_violation", "description": "前端直连数据库违反分层架构"}
  ],
  "revision_guidance": "请补充独立的 DB migration 任务节点，并将 task-06 改为通过 API 层调用数据库",
  "a6_rework": true,
  "a7_rework": false
}
```

### 9.2 审批列表

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Gate2 待审批                                                             │
│ 需求                  Cycle  修订轮次  A8评分  提交时间    SLA      操作    │
│ 用户管理系统 v3         0       0       78/100   10:00    剩3h30min [审批] │
│ 订单通知功能            0       1       62/100   09:30    剩1h15min [审批] │
│ 支付网关重构            1       0       55/100   09:00     ⚠️超时    [审批] │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 十、异常处理

| 场景 | 策略 |
|------|------|
| Gate2 审批超时（2h 预警 / 4h 升级） | 通知升级不自动通过，持续等待 |
| A6 缺失（a6_missing=true） | 审批页标记 ⚠️"A6 DAG 未产出"，审批人仅看 A7 + 空 DAG 提示 |
| A7 缺失（a7_missing=true） | 审批页标记 ⚠️"A7 测试用例未产出"，审批人仅看 DAG + A8 报告 |
| A8 缺失（a8_missing=true） | 审批页无评审报告区，标记"A8 架构评审未执行"，审批人仅看 DAG + 测试用例 |
| NATS 投递失败 | Outbox 重试，5 次入死信队列 |
| 重复提交 | 幂等，同一 approval_id 只允许一次决策 |
| 前端未阻断 a6_rework=false + a7_rework=false | MC Backend 拒绝此组合 → 400 Bad Request |
| 分歧报告场景（对抗循环结束） | 审批页展示分歧报告全文，审批人人工裁决 |

---

## 十一、实施建议

### Phase 1：基础审批（Day 1-2）
- `approvals` 表 gate_level=2 行管理 + a6_rework/a7_rework 字段
- GET/POST Gate2 审批 API
- 前端 Gate2 审批页（DAG 依赖图展示 + 测试用例折叠面板 + A8 报告可视化）

### Phase 2：A8 报告 + 安全红线（Day 2-3）
- A8 评审报告五维度折叠面板（颜色标记 pass/warn/fail）
- Violations 内联展开 + 链接到对应 DAG 节点
- 安全红线独立展示区块（4 项必查）

### Phase 3：SLA + 打回（Day 3-4）
- SLA 倒计时 + 站内通知 + 超时升级
- a6_rework / a7_rework 复选框联动逻辑
- Gate2 拒绝 → A6/A7 修订全链路联调
- 分歧报告展示 + 人工裁决流程

---

## 十二、总结

| 维度 | 内容 |
|------|------|
| **入口** | `context.ready.gate2`（Orchestrator 在 A8 评审完成/对抗循环结束后 build_context） |
| **决策** | 架构师/Tech Lead 通过 / 拒绝 |
| **产物** | Gate2 **自行写入** `approvals` 表（gate_level=2） |
| **通过出口** | `agent.result.gate2.pass` → Orchestrator → `phase='development'` → `context.ready.A9` |
| **拒绝出口** | `agent.result.gate2.reject` → Orchestrator → `tech_prep_revision_count+=1` → 根据 a6_rework/a7_rework 重发 context.ready.A6/A7 |
| **SLA** | 2 小时预警 + 4 小时升级，不自动通过 |
| **特有功能** | a6_rework/a7_rework 独立控制、A8 评审报告嵌入、安全红线独立展示、分歧报告人工裁决 |
| **打回范围** | A6 + A7 + A8 完整重走（可根据 a6_rework/a7_rework 独立控制），同一 cycle 内修订 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-15
**版本**: v1.0
**数据规范**: [阶段三数据字典](./阶段三-数据字典.md)
