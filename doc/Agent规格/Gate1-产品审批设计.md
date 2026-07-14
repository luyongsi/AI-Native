# Gate1 产品审批 - 完整设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 完整设计文档（已通过 critical 审计）
- **参考**: [系统状态机与信息流设计](../系统状态机与信息流设计.md) · [阶段二数据字典](./阶段二-数据字典.md) · [阶段一数据字典](./阶段一-数据字典.md)
- **说明**: Gate1 是阶段二的最后节点。MC Backend 收到 `context.ready.gate1` 后预创建 approvals 记录，审批人提交后 Gate1 自行更新审批结果，通过 NATS 发布。**本文档中所有数据结构、字段名、枚举值以阶段二数据字典为准。**

---

## 一、通信架构

Gate1 是**人工审批节点**：

```
┌──────────┐   HTTP (REST)    ┌──────────────┐          NATS          ┌──────────────┐
│   前端    │ ◄──────────────► │  MC Backend  │ ◄─────────────────────► │ Orchestrator │
│ (审批人)  │                  │   (Gate1)    │  context.ready.gate1   │              │
│          │                  │              │  agent.result.gate1.*  │              │
└──────────┘                  └──────────────┘                        └──────────────┘
```

- **NATS**：接收 `context.ready.gate1`，发布 `agent.result.gate1.pass` / `agent.result.gate1.reject`
- **HTTP REST**：前端获取审批上下文、提交决策
- Gate1 **自行写入** `approvals` 表（gate_level=1），Orchestrator 只订阅结果做编排

---

## 二、Gate1 在阶段二中的位置

```
阶段二：设计
┌──────────────────────────────────────────────────────────┐
│  A3 UI原型 ──► A4 Spec撰写 ──► A5 设计检查 ──► 【Gate1】 │
│                                          ┌──────┴──────┐  │
│                                          │ 产品经理审批  │  │
│                                          └──────┬──────┘  │
│                                    ✅ pass   ❌ reject   │
│                                       │         │        │
└───────────────────────────────────────┼─────────┼────────┘
                                        ▼         ▼
                                   进入阶段三   打回 A4 修订
                                  （A6+A7 并行） (默认不返工 A3)
```

---

## 三、审批职责

| 维度 | 内容 |
|------|------|
| **审批角色** | 产品经理 / 需求负责人 |
| **审批对象** | A3 原型 + A4 Spec（含 OpenAPI/ERD/DDL）+ A5 检查报告（辅助参考） |
| **决策类型** | pass / reject |
| **审批人数** | 单人审批 |
| **A5 报告作用** | **辅助决策参考**，非绑定。审批人自行判断是否采纳 A5 建议 |

---

## 四、审批流程

### 4.1 正常流程

```
Orchestrator 查询 DB（requirements + agent_results A1/A2/A3/A4/A5 MAX cycle + design_specs）
    → 更新 requirements.design_status='design_completed'
    → build_context → context.ready.gate1（NATS）
    → MC Backend 收到 context.ready.gate1:
        → 在 approvals 表预创建一行: id=UUID, gate_level=1, status='pending', req_id, session_id, cycle
        → 返回 approval_id（用于后续 API 路由）
        → 通知审批人
    → 审批人打开页面（GET /api/approvals/{approval_id}/context?gate_level=1）
    → 查看：原型预览 + Spec 摘要 + OpenAPI 预览 + ERD + A5 检查报告
    → 决策：
        ├── ✅ 通过 → Gate1 更新 approvals: status='decided', decision='pass', reviewer_*
        │     → 发布 agent.result.gate1.pass → Orchestrator → 阶段三（A6+A7）
        └── ❌ 拒绝 → Gate1 更新 approvals: status='decided', decision='reject', reject_reasons, revision_guidance, a3_rework, reviewer_*
              → 发布 agent.result.gate1.reject → Orchestrator → 打回链路
```

### 4.2 审批页面

```
┌──────────────────────────────────────────────────────────────────┐
│  Gate1 设计审批                                      Cycle: 0     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  🎨 UI 原型（A3 产出）                           [全屏预览]       │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  ┌─────────────────────────────────────────────────────┐     ││
│  │  │                                                     │     ││
│  │  │          原型预览（iframe 嵌入 S3 URL）              │     ││
│  │  │                                                     │     ││
│  │  │  状态切换：[default] [loading] [empty] [error] [hover] [active] ││
│  │  │                                                     │     ││
│  │  └─────────────────────────────────────────────────────┘     ││
│  │  版本：v3（3 次标注迭代）  标注数：5                           ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  📋 技术规格（A4 产出）                           质量分：0.85    │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  ▸ Spec 文档：用户管理系统技术规格 v1.0                       ││
│  │    概述 / 功能规格（3 个模块）/ 状态机（8 状态 15 转移）/      ││
│  │    接口设计（12 endpoints）/ 数据模型（5 实体）/ 非功能需求    ││
│  │  ▸ OpenAPI 3.0：[展开查看] — 12 paths, 8 schemas             ││
│  │  ▸ ERD：[展开查看] — 5 entities, 7 relationships             ││
│  │  ▸ DDL：[展开查看] — 156 lines, 3 new tables                 ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  🔍 设计检查报告（A5 产出）                    [非绑定，仅供参考]  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │  总体评分：78/100                 总问题数：8                 ││
│  │  ┌─────────────────────────────────────────────────────┐     ││
│  │  │ ✅ API 一致性         85/100    2 issues             │     ││
│  │  │ ✅ ERD 完整性          70/100    3 issues ⚠️          │     ││
│  │  │ ⚠️ 状态机闭合性        68/100    2 issues             │     ││
│  │  │ ✅ 原型-Spec 对齐     85/100    1 issue              │     ││
│  │  │ ✅ 安全基线            82/100    0 issues             │     ││
│  │  └─────────────────────────────────────────────────────┘     ││
│  │  [展开查看详细问题列表]                                       ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ─────────────────────────────────────────────────────────────── │
│  审批决策：                                                      │
│  ○ ✅ 通过     ○ ❌ 拒绝                                        │
│                                                                  │
│  拒绝原因（可多选）：                                            │
│  □ 原型与需求不符    □ Spec 不完整      □ API 设计问题           │
│  □ ERD 不完整        □ 验收标准遗漏      □ 需要原型修改           │
│  □ 其他                                                          │
│                                                                  │
│  ☐ 要求 A3 原型返工（默认仅返工 A4 Spec）                        │
│                                                                  │
│  修订指引（拒绝时必填）：                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [提交审批]                                                      │
└──────────────────────────────────────────────────────────────────┘
```

### 4.3 拒绝原因枚举

遵循 [数据字典 §7.3](./阶段二-数据字典.md#73-拒绝原因枚举)，含 UI 标签到 `category` 枚举值的映射。

| UI 标签（前端展示） | `category` 枚举值 | 含义 |
|-------------------|-------------------|------|
| 原型与需求不符 | `prototype_not_aligned` | 原型界面与需求草案描述不一致 |
| Spec 不完整 | `spec_incomplete` | 技术规格缺少关键模块、流程或场景 |
| API 设计问题 | `api_design_issue` | API 接口、参数或响应设计存在缺陷 |
| ERD 不完整 | `erd_incomplete` | 实体关系图缺少关键实体或字段定义 |
| 验收标准遗漏 | `acceptance_criteria_mismatch` | 设计未覆盖全部验收标准 |
| 需要原型修改 | `prototype_change_needed` | 原型需要修改——勾选此项时自动标记 `a3_rework=true` |
| 其他 | `other` | 其他未列出的问题 |

> 审批页 mockup 中的中文标签仅用于 UI 展示，提交 API 时 `reject_reasons[].category` 使用英文枚举值。

**`prototype_change_needed` 的特殊处理**：审批人勾选此项时，`a3_rework` 自动设为 `true`。Orchestrator 收到后发布 `context.ready.A3`（而非默认的 `context.ready.A4`），A3 返工确认后重新走 A4→A5→Gate1 全链路。

### 4.4 通过后

- Gate1 写入 approvals（gate_level=1, decision='pass'）→ 发布 `agent.result.gate1.pass`
- Orchestrator → event_log → `requirements.phase='tech_prep'`, `design_status=NULL` → 启动阶段三（A6+A7 并行）
- Gate1 不参与后续流程

### 4.5 拒绝后

- Gate1 写入 approvals（gate_level=1, decision='reject', reject_reasons, revision_guidance, a3_rework）→ 发布 `agent.result.gate1.reject`
- Orchestrator → event_log → `requirements.design_status='gate1_rejected'`, `design_revision_count+=1`
- 判断 `a3_rework` 标记：
  - `a3_rework=false`（默认）→ 发布 `context.ready.A4`（A4 修订，含 A5 报告 + Gate1 拒绝原因）
  - `a3_rework=true` → 发布 `context.ready.A3`（A3 返工，含 Gate1 拒绝原因）
- **cycle 不变**（阶段内迭代，仅 `design_revision_count` 递增）

---

## 五、产出物

Gate1 **自行写入** approvals 表（MC Backend 预创建 + 审批人提交后更新），结构见 [数据字典 §7.2](./阶段二-数据字典.md#72-审批记录结构)。

| 字段 | 说明 |
|------|------|
| `id` | 审批 UUID |
| `req_id`, `session_id`, `gate_level=1`, `cycle` | 路由信息 |
| `decision` | `"pass"` / `"reject"` |
| `reject_reasons` | `[{category, description}]`（拒绝时） |
| `revision_guidance` | 修订指引文本（拒绝时必填） |
| `a3_rework` | 是否要求 A3 原型返工（默认 `false`） |
| `reviewer_user_id`, `reviewer_name` | 审批人 |
| `reviewed_at` | 审批时间 |

> `approvals` 由 Gate1 写入，是 Gate1 的产物。Orchestrator 仅订阅 NATS 事件获取结果。

---

## 六、NATS 事件协议

完整定义见 [数据字典 §7.4](./阶段二-数据字典.md#74-nats-事件)。

| 事件 | 方向 | 触发时机 |
|------|------|---------|
| `context.ready.gate1` | Orchestrator → Gate1 | A5 完成后 Orchestrator 查询 DB 后 build_context |
| `agent.result.gate1.pass` | Gate1 → Orchestrator | 审批通过 + approvals 已写入 |
| `agent.result.gate1.reject` | Gate1 → Orchestrator | 审批拒绝 + approvals 已写入 |

### context.ready.gate1 payload 要点

Orchestrator 从 DB 组装的全量上下文，包含：

- `a1_output`：需求草案 + 验收标准 + 低保真线框图 + 置信度
- `a2_output`：可行性评估 + 待确认清单 + 冲突点 + 质量评分
- `a3_output`：原型 URL + 多状态 screens
- `a4_output`：Spec 文档 + OpenAPI + ERD + DDL + 质量评分
- `a5_output`：设计检查报告（五维度 + issues + 总体评分）

### agent.result.gate1.reject payload 要点

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "gate_level": 1,
  "decision": "reject",
  "reject_reasons": [
    {"category": "spec_incomplete", "description": "Spec 缺少权限校验流程"}
  ],
  "revision_guidance": "请补充权限校验相关的状态机流转和 API 定义",
  "a3_rework": false,
  "reviewer_user_id": "string",
  "reviewer_name": "string",
  "reviewed_at": "ISO 8601"
}
```

---

## 七、SLA 与超时策略

| 维度 | 内容 |
|------|------|
| **SLA** | 4 小时 |
| **宽限期** | SLA 超期后 +1 小时 |
| **超时行为** | 通知审批人；宽限期后发升级通知；**不自动通过** |
| **审批提醒** | 超时前 1 小时提醒；超时前 15 分钟再次提醒 |

> Gate1 的 SLA 比 Gate0（1 小时）更长，因为审批人需要审查原型、Spec、API 设计、ERD、DDL 和检查报告等更丰富的内容。

---

## 八、与 A3/A4/A5 的协作关系

| 维度 | A3 | A4 | A5 | Gate1 |
|------|----|----|----|-------|
| **类型** | Agent | Agent | Agent | Gate（人工审批） |
| **输入** | `context.ready.A3` | `context.ready.A4` | `context.ready.A5` | `context.ready.gate1` |
| **产物存储** | prototype_artifacts + agent_results (A3) | design_specs + agent_results (A4) | agent_results (A5) | approvals 表（自写入，gate_level=1） |
| **发布事件** | agent.result.A3 | agent.result.A4 | agent.result.A5 | agent.result.gate1.pass / .reject |
| **自动化** | AI + 人机标注 | AI | AI | **人工** |
| **Gate1 打回** | 仅 a3_rework=true | 默认打回目标 | 不返工 | — |

### Gate1 拒绝后链路

```
Gate1 写入 approvals (gate_level=1, decision='reject') + 发布 agent.result.gate1.reject
Orchestrator:
  → event_log (IN)
  → requirements: design_status='gate1_rejected', design_revision_count += 1
  → 判断 a3_rework:
      ├── a3_rework = false（默认）:
      │     发布 context.ready.A4（含 revision_context: A5 报告 + Gate1 拒绝原因）
      │     → A4 修订 → agent.result.A4 → A5 → Gate1 重新审批
      └── a3_rework = true:
            发布 context.ready.A3（含 gate1_rejection）
            → A3 返工 → 用户修订 → 确认 → agent.result.A3
            → A4 → A5 → Gate1 重新审批
            （cycle 不变，design_revision_count 递增）
```

---

## 九、前端交互

### 9.1 审批 API

**获取审批上下文** — `GET /api/approvals/{approval_id}/context?gate_level=1`

返回结构：MC Backend 从 DB 组装 `context.ready.gate1` 的完整 payload（见 [数据字典 §7.4](./阶段二-数据字典.md#contextreadygate1orchestrator--gate1)）。

**提交决策** — `POST /api/approvals/{approval_id}/decide`

通过：
```json
{ "decision": "pass" }
```

拒绝（遵循 [数据字典 §7.4](./阶段二-数据字典.md#agentresultgate1rejectgate1--orchestrator)）：
```json
{
  "decision": "reject",
  "reject_reasons": [
    {"category": "spec_incomplete", "description": "Spec 缺少权限校验流程"},
    {"category": "erd_incomplete", "description": "User 实体缺少 role 关联表"}
  ],
  "revision_guidance": "请补充权限校验的状态机流转和 role 关联表定义",
  "a3_rework": false
}
```

### 9.2 审批列表

```
┌───────────────────────────────────────────────────────────────────┐
│  Gate1 待审批                                                      │
│ 需求                  Cycle  A5评分   提交时间      SLA      操作   │
│ 用户管理系统 v3         0     78/100   10:00      剩3h30min [审批]  │
│ 订单通知功能            1     65/100   09:30      剩2h45min [审批]  │
└───────────────────────────────────────────────────────────────────┘
```

---

## 十、异常处理

| 场景 | 策略 |
|------|------|
| Gate1 审批超时（4h + 1h 宽限） | 通知不自动通过 |
| A4 缺失（a4_missing=true） | 审批页标记 ⚠️"A4 Spec 未产出"，审批人仅基于原型判断 |
| A5 缺失（a5_missing=true） | 审批页无检查报告区，标注"检查未执行" |
| NATS 投递失败 | Outbox 重试，5 次入死信队列 |
| 重复提交 | 幂等，同一 approval_id 只允许一次决策 |
| A3 原型不可访问 | 审批页标注"原型链接失效"，审批人可选择等待修复或凭 Spec 决策 |

---

## 十一、实施建议

### Phase 1：基础审批（3 天）
- `approvals` 表 gate_level=1 行管理 + GET/POST API
- 前端审批页（原型 iframe 嵌入 + Spec 摘要 + 决策表单）
- NATS 事件（context.ready.gate1、agent.result.gate1.pass/reject）

### Phase 2：A5 报告可视化（2 天）
- 检查报告五维度折叠面板（颜色标记 pass/warn/fail）
- Issues 内联展开 + 链接到 Spec 对应位置
- a3_rework 复选框联动逻辑

### Phase 3：SLA + 打回联调（2 天）
- SLA 倒计时 + 站内通知 + 超时升级
- Gate1 拒绝 → A4 修订（默认）全链路
- Gate1 拒绝含 a3_rework → A3 返工 → A4/A5/Gate1 全链路

---

## 十二、总结

| 维度 | 内容 |
|------|------|
| **入口** | `context.ready.gate1`（Orchestrator 查询 DB 构建全量上下文） |
| **决策** | 审批人通过 / 拒绝 |
| **产物** | Gate1 **自行写入** `approvals` 表（gate_level=1） |
| **通过出口** | `agent.result.gate1.pass` → Orchestrator → `requirements.phase='tech_prep'` → 阶段三（A6+A7） |
| **拒绝出口** | `agent.result.gate1.reject` → Orchestrator → `design_revision_count+=1` → `context.ready.A4`（默认）/ `context.ready.A3`（若 `a3_rework=true`） |
| **SLA** | 4 小时 + 1 小时宽限期 |
| **A3 返工触发** | 仅审批人明确勾选 `a3_rework=true`；cycle 不变，design_revision_count 递增 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
**数据规范**: [阶段二数据字典](./阶段二-数据字典.md)
