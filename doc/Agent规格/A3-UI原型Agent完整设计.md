# A3 UI 原型 Agent - 完整设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 完整设计文档（已通过 critical 审计）
- **参考**: [系统状态机与信息流设计](../系统架构/系统状态机与信息流设计.md) · [阶段二数据字典](./阶段二-数据字典.md) · [阶段一数据字典](./阶段一-数据字典.md)
- **说明**: A3 负责阶段二的 UI 原型生成，范围从 Gate0 通过后启动到用户确认原型定稿。Gate1 一般拒绝不回退 A3，仅在审批人明确勾选 `a3_rework=true` 时触发返工。**本文档中所有数据结构、字段名、枚举值以阶段二数据字典为准。**

---

## 一、通信架构

A3 采用**双通道**模型（与 A1 同构）：

```
┌──────────┐  HTTP + SSE Stream   ┌──────────────┐   NATS (统一调度)   ┌──────────────┐
│   前端    │ ◄──────────────────► │  MC Backend  │ ◄─────────────────► │ Orchestrator │
│  (用户)   │                      │   (含A3)     │                     │              │
└──────────┘                      └──────────────┘                     └──────────────┘
```

- **HTTP + SSE Stream**：面向用户的多轮原型迭代交互（生成→标注→修改→确认）
- **NATS**：接收 Orchestrator 调度（`context.ready.A3`，Gate0 pass 或 Gate1 打回含 `a3_rework=true`），发布完成结果（`agent.result.A3`）

---

## 二、整体业务流程

### 2.1 A3 在阶段二中的位置

```
阶段二：设计
┌───────────────────────────────────────────────────┐
│                                                   │
│  A3 UI原型 ──► A4 Spec撰写 ──► A5 设计检查 ──► Gate1 │
│    ↑                                      │       │
│    └── Gate1 打回（仅 a3_rework=true）───┘       │
│                                                   │
└───────────────────────────────────────────────────┘
              │
              ▼ Gate1 通过后进入阶段三（A6+A7，与 A3 无关）
```

### 2.2 核心流程概览

```
Gate0 pass
  → Orchestrator 更新 requirements (phase='design', design_status='prototyping')
  → 发布 context.ready.A3（NATS）
  → MC Backend 收到调度 → 通知用户"可开始原型设计"

用户进入原型页面 → POST /api/prototype/generate {req_id}
  → A3 LLM 读取 A1 需求草案 + A2 分析 + 低保真线框图（如有）
  → 生成高保真 HTML 原型 → SSE Stream 返回

用户标注迭代（可选，多轮）
  → 用户在原型页面上标注修改意见 → POST /api/prototype/annotate
  → A3 解析标注 → 增量更新原型 → SSE Stream 返回新版本

用户确认定稿 → POST /api/prototype/confirm
  → MC Backend 持久化到 prototype_artifacts + agent_results (A3)
  → 发布 agent.result.A3（NATS）
  → Orchestrator: event_log → 更新 design_status='spec_writing' → context.ready.A4

Gate1 打回（仅当 a3_rework=true）
  → Gate1 reject + a3_rework=true → agent.result.gate1.reject
  → Orchestrator: 更新 design_status='prototyping' → context.ready.A3（含拒绝原因）
  → A3 原型页面 REOPENED → 用户修订原型 → 确认 → 重走 A4→A5→Gate1
```

### 2.3 关键设计原则

1. **双通道协作**：用户交互走 HTTP+SSE，编排调度走 NATS（首次启动 / Gate1 要求 A3 返工）
2. **多轮标注迭代**：生成 → 标注 → 增量更新 → 再标注 → 确认，用户可多轮迭代
3. **产物自持久化**：确认时写入 `prototype_artifacts` + `agent_results`，每版标注保留版本历史
4. **非必然返工**：Gate1 拒绝默认不触发 A3 返工，仅当审批人明确勾选 `a3_rework=true` 时回退
5. **范围收敛**：A3 只关注到 Gate1

---

## 三、A3 独立对话流程

### 3.1 原型生成启动

- API: `POST /api/prototype/generate`
- 请求体：
```json
{
  "req_id": "uuid",
  "session_id": "uuid"
}
```

MC Backend 处理：
- 校验 `requirements.phase='design'` 且 `design_status='prototyping'`
- 读取 A1 草案 + A2 分析产物（从 `requirements` + `agent_results`）
- 调用 A3 原型生成函数，SSE Stream 返回

### 3.2 A3 原型生成逻辑

```
读取上游产物 → LLM分析(Stream) → 生成高保真原型HTML → 上传S3/OSS → SSE Stream结束
```

**1. 读取上游产物**
- A1 需求草案：`requirements.requirement_draft` — title, description, domain, entities, use_cases, acceptance_criteria, constraints, risks
- A2 分析：`agent_results` WHERE agent_key='A2', MAX cycle — feasibility_assessment, conflicts
- A1 低保真线框图（如有）：`agent_results` WHERE agent_key='A1' → artifact.wireframe_url

**2. 调用 MCP/知识库（并行，5 秒超时）**
- `get_ui_templates(domain)` — 获取领域 UI 模板库（后台管理/移动端/数据看板等）
- `get_design_system(platform)` — 获取设计系统组件规范（按钮/表格/表单/导航等）

**3. LLM Stream 生成**
- System Prompt 注入需求上下文 + 知识库检索结果
- 生成完整的高保真 HTML 原型（内联 CSS，可独立渲染）
- SSE Stream 逐步返回 HTML 片段

**4. 上传原型到 S3/OSS**
- HTML 内容上传到 S3
- 生成多状态截图（default/loading/empty/error/hover/active）
- 写入 `prototype_artifacts`：`version=1`, `status='draft'`

**5. Stream 结束** → `done` 事件

### 3.3 SSE 事件类型

| 事件类型 | 含义 | payload |
|---------|------|---------|
| `thinking` | A3 分析中 | `{"message": "正在分析需求，匹配合适的UI模板..."}` |
| `knowledge` | 知识库检索结果 | `{"templates": [...], "components": [...]}` |
| `prototype_update` | 原型 HTML 增量 | `{"html_chunk": "<div>...", "progress": 0.5}` — progress 范围 0-1，为已输出字节数/预估总字节数的比值 |
| `screens` | 多状态截图 | `{"screens": [{"name": "列表页", "state": "default", "url": "https://s3/xxx/screen_default.png"}]}` |
| `done` | 生成完成 | `{"prototype_url": "...", "version": 1, "screens": [...]}` |
| `error` | 异常 | `{"message": "生成失败，已降级到模板"}` |

### 3.4 用户标注迭代

- API: `POST /api/prototype/annotate`
- 请求体：
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "annotations": [
    {
      "annotation_id": "uuid",
      "element_id": "#user-table-header",
      "type": "layout_change",
      "comment": "表格列宽需要调整为三列等宽",
      "position": {"x": 120, "y": 45}
    }
  ]
}
```

MC Backend 处理：
- 保存标注到 `prototype_artifacts.annotations`（append，`created_at` 由服务端生成）
- 调用 A3 标注处理函数
- A3 解析标注 → 基于当前 HTML + 标注上下文**重新生成完整 HTML**（非增量 delta） → SSE Stream 返回
- 新版本写入 `prototype_artifacts`：`version += 1`

**标注处理逻辑：**
```
解析标注列表 → 按 type 分类 → 注入 System Prompt（含当前原型HTML + 标注）→ LLM 增量生成 → 更新原型 → SSE Stream
```

### 3.5 用户确认定稿

- API: `POST /api/prototype/confirm`
- `cycle` = `requirements.gate_rejection_count`
- **持久化**（在同一数据库事务中）：
  - `prototype_artifacts`：当前版本 `status='confirmed'`，`updated_at=NOW()`
  - `agent_results` INSERT：`agent_key='A3'`, `cycle`, `status='completed'`, `artifact` = `{prototype_url, screens, version, annotation_count}`
  - `requirements.design_status` = `'spec_writing'`
- **发布 NATS**：`agent.result.A3`（payload 见 [数据字典 §4.4](./阶段二-数据字典.md#agentresulta3a3--orchestrator)）

---

## 四、A3 发布后：A4 与 Gate1

A3 不调用 A4/Gate1，仅了解流转路径：

1. Orchestrator 收到 `agent.result.A3` → 写入 event_log → 查询 DB → build_context → `context.ready.A4`
2. A4 执行 Spec 撰写 → 持久化到 `design_specs` + `agent_results` (A4) → `agent.result.A4`
3. Orchestrator → `context.ready.A5` → A5 设计检查 → `agent.result.A5`
4. Orchestrator → `context.ready.gate1` → Gate1 审批 → pass/reject

**A4 异常处理**：A4 超时 → 重试 1 次 → 仍失败 → Orchestrator 写入 `agent_results` (A4, status='skipped')，`context.ready.A5` 中 `a4_missing=true`。

---

## 五、Gate1 打回流程（A3 返工场景）

### 5.1 Gate1 拒绝含 A3 返工标记

A3 返工仅在 Gate1 审批人明确勾选 `a3_rework=true` 时触发。Orchestrator 收到 `agent.result.gate1.reject` 后：

1. 写入 event_log (IN)
2. 更新 `requirements`：`design_status='gate1_rejected'`, `design_revision_count+=1`
3. 判断 `a3_rework`：
   - 若 `a3_rework=true`：更新 `design_status='prototyping'` → 发布 `context.ready.A3`（含 gate1_rejection）
   - 若 `a3_rework=false`（默认）：发布 `context.ready.A4`（A4 修订，A3 不动）

### 5.2 A3 返工修订

- `GET /api/prototype/history/{req_id}` → 前端按版本展示原型历史 + Gate1 拒绝原因
- `POST /api/prototype/annotate` → 新标注版本递增，继续使用当前 cycle
- 修订完成后 `POST /api/prototype/confirm` → 同 3.5

### 5.3 返工后流转

```
agent.result.A3 → Orchestrator → 重走 A4 → A5 → Gate1（cycle 不变，design_revision_count 递增）
```

---

## 六、数据库表设计

### 6.1 核心表

- `prototype_artifacts` — 原型产物表（A3 管理），见 [数据字典 §3.1](./阶段二-数据字典.md#31-prototype_artifacts-表a3-管理)
- `agent_results` — Agent 产物表（A3 写入），见 [阶段一数据字典 §3.2](./阶段一-数据字典.md#32-agent_results-表agent-产物独立表)
- `dialogue_sessions` — A3 复用 A1 的会话（同一 req_id），通过 `dialogue_messages.content.context_type='prototype'` 区分
- `dialogue_messages` — 对话消息（A3 原型消息含 `context_type='prototype'`）
- `requirements` — 需求主表（A3 确认时更新 `design_status`）

### 6.2 prototype_artifacts 表

```sql
CREATE TABLE prototype_artifacts (
    id              BIGSERIAL PRIMARY KEY,
    req_id          UUID NOT NULL REFERENCES requirements(id),
    cycle           INT NOT NULL DEFAULT 0,
    version         INT NOT NULL DEFAULT 1,
    prototype_url   TEXT,
    html_content    TEXT,
    screens         JSONB,
    annotations     JSONB DEFAULT '[]'::jsonb,
    status          VARCHAR(20) DEFAULT 'draft',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_prototype_artifacts_req ON prototype_artifacts(req_id, cycle, version DESC);
```

### 6.3 A3 写入 agent_results

```sql
INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
VALUES (?, 'A3', ?, 'completed', ?);
-- artifact = {"prototype_url": "...", "screens": [...], "version": 3, "annotation_count": 5}
```

### 6.4 dialogue_messages 扩展

A3 原型对话消息复用 `dialogue_messages` 表，在 `content` JSONB 中增加 `context_type` 字段：

```json
// A3 原型消息 content 结构
{
  "text": "A3 回复文本",
  "context_type": "prototype",
  "prototype_preview": {"url": "...", "version": 2},
  "annotation_highlights": ["#user-table-header", "#search-bar"]
}
```

---

## 七、NATS 事件协议

A3 涉及两个事件，完整定义见 [数据字典 §4.4](./阶段二-数据字典.md#44-nats-事件)。

| 事件 | 方向 | 触发时机 |
|------|------|---------|
| `context.ready.A3` | Orchestrator → A3 | Gate0 pass（首次）/ Gate1 打回含 `a3_rework=true` |
| `agent.result.A3` | A3 → Orchestrator | 用户确认原型定稿 |

### context.ready.A3 完整 payload

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "a1_output": {
    "requirement_draft": {
      "title": "用户管理系统",
      "description": "...",
      "domain": "企业后台",
      "entities": [{"name": "User", "attributes": ["name", "email", "role"], "description": "..."}],
      "use_cases": ["创建用户", "编辑用户", "删除用户", "搜索用户"],
      "acceptance_criteria": ["Given 管理员登录 When 点击新建用户 Then 弹出用户表单"],
      "constraints": ["需要支持RBAC权限"],
      "risks": ["大数据量下列表性能"]
    },
    "wireframe_url": "https://s3/xxx/wireframe.png",
    "confidence_score": 0.85
  },
  "a2_output": {
    "feasibility_assessment": {
      "technical": {"feasible": true, "assessment": "...", "concerns": []},
      "business": {"feasible": true, "assessment": "...", "concerns": []},
      "risk_level": "medium",
      "risk_rationale": "..."
    },
    "confirmation_checklist": [],
    "conflicts": [],
    "quality_score": 0.72
  },
  "revision_context": {
    "is_revision": false,
    "gate1_rejection": null
  }
}
```

**Gate1 打回场景时，`revision_context` 结构：**

```json
{
  "revision_context": {
    "is_revision": true,
    "gate1_rejection": {
      "gate_level": 1,
      "reject_reasons": [
        {"category": "prototype_change_needed", "description": "列表页缺少批量操作功能"}
      ],
      "revision_guidance": "请在列表页增加批量选择和批量删除功能",
      "rejected_at": "ISO 8601"
    }
  }
}
```

### agent.result.A3 完整 payload

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "prototype_url": "https://s3/xxx/prototype_v3.html",
  "screens": [
    {"name": "列表页-默认状态", "description": "用户列表含搜索和分页", "url": "https://s3/xxx/screen_list_default.png", "state": "default"},
    {"name": "列表页-加载中", "description": "数据加载骨架屏", "url": "https://s3/xxx/screen_list_loading.png", "state": "loading"},
    {"name": "列表页-空数据", "description": "无数据时的占位引导", "url": "https://s3/xxx/screen_list_empty.png", "state": "empty"},
    {"name": "编辑弹窗", "description": "用户编辑表单弹窗", "url": "https://s3/xxx/screen_edit_active.png", "state": "active"}
  ],
  "version": 3,
  "annotation_count": 5,
  "timestamp": "ISO 8601"
}
```

---

## 八、关键业务规则

### 8.1 原型状态流转

```
draft → (标注迭代) → draft → confirmed
                            → (A3返工时) 新版本从 draft 开始
```

### 8.2 需求阶段状态（A3 范围内）

```
Gate0 pass → phase='design', design_status='prototyping'
A3 确认 → design_status='spec_writing'
Gate1 打回含 a3_rework → design_status='prototyping'（重新）
```

### 8.3 版本管理

- 每次 `POST /api/prototype/annotate` → `version += 1`，旧版保留
- 确认时仅标记最新版本 `status='confirmed'`
- 历史版本通过 `prototype_artifacts` WHERE req_id=? ORDER BY version DESC 查询

### 8.4 数据一致性

- prototype_artifacts + agent_results + requirements.design_status 的确认操作在**同一数据库事务**中
- annotations 每次标注追加，不覆盖

### 8.5 降级策略

| 场景 | 策略 |
|------|------|
| LLM API 不可用 | 使用预设 HTML 模板（按 domain 匹配，如后台管理模板） |
| MCP 知识库不可用 | 跳过知识增强，直接用需求草案生成 |
| S3/OSS 上传失败 | 降级为 Base64 inline HTML，标记 `upload_failed=true` |

---

## 九、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| A3 原型生成 LLM 超时 | 5min | 降级到模板生成，通知用户"模板模式" |
| A3 标注处理超时 | 3min | 返回错误，建议用户简化标注 |
| A3 原型页面无活动 | 24h | 标记 abandoned，不清除已确认的原型 |
| MCP 知识库超时 | 5s | 跳过，仅用需求上下文 |
| S3 上传失败 | 10s | Base64 inline，标注 `upload_failed` |
| A4 Spec撰写超时 | 10min | 重试 1 次，仍失败 Orchestrator 写入 agent_results (A4, status='skipped') |
| Agent 执行超时 | 30min | 重试 1 次，连续 2 次超时通知升级 |
| NATS 投递失败 | 30s | Outbox 重试，5 次入死信队列 |

---

## 十、前端交互

### 10.1 原型页面入口

- `GET /api/prototype/context/{req_id}` → 获取原型上下文（需求草案摘要 + 当前原型状态）
- 若 `prototype_artifacts` 已有记录 → 加载最新版本
- 若首次进入 → 展示"开始生成原型"按钮 → `POST /api/prototype/generate`

### 10.2 原型查看与标注

- `POST /api/prototype/generate` — 启动/重新生成原型（SSE Stream）
- `POST /api/prototype/annotate` — 提交标注，获取更新后的原型（SSE Stream）
- `GET /api/prototype/history/{req_id}` — 查看原型版本历史 + 标注记录
- `POST /api/prototype/confirm` — 确认定稿

### 10.3 原型预览页面布局

```
┌──────────────────────────────────────────────────────────────┐
│  阶段二：UI原型设计                              确认定稿 [→]  │
├──────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐  ┌────────────────────────────┐ │
│  │                         │  │  标注工具面板               │ │
│  │                         │  │  ○ layout_change 布局调整   │ │
│  │   高保真原型预览区       │  │  ○ content_change 内容修改 │ │
│  │   (iframe 嵌入 S3 URL)  │  │  ○ style_change 样式调整   │ │
│  │                         │  │  ○ add_element 新增元素    │ │
│  │   用户可点击元素→       │  │  ○ remove_element 删除元素 │ │
│  │   弹出标注气泡          │  │  ○ flow_change 交互流程    │ │
│  │                         │  │  ○ other 其他              │ │
│  │                         │  │  ──────────────────────      │ │
│  │                         │  │  标注历史（按版本折叠）       │ │
│  │                         │  │  v3: 调整表格列宽            │ │
│  │                         │  │  v2: 新增批量操作按钮        │ │
│  │                         │  │  v1: 初始生成                │ │
│  └─────────────────────────┘  └────────────────────────────┘ │
│                                                              │
│  状态切换：[default] [loading] [empty] [error] [active]      │
└──────────────────────────────────────────────────────────────┘
```

### 10.4 前端 API 总览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/prototype/context/{req_id}` | GET | 获取原型上下文 |
| `/api/prototype/generate` | POST | 启动原型生成（SSE） |
| `/api/prototype/annotate` | POST | 提交标注（SSE） |
| `/api/prototype/confirm` | POST | 确认定稿 |
| `/api/prototype/history/{req_id}` | GET | 版本历史 + 标注记录 |

---

## 十一、实施建议

### Phase 1（基础流程，~5 天）
- A3 MC Backend 路由层：prototype/generate、prototype/annotate、prototype/confirm 端点
- A3 原型生成核心：LLM Stream + S3 上传 + prototype_artifacts 写入
- 前端原型预览页面（iframe 嵌入 + 状态切换）
- Fallback 模板（按 domain 提供 3-5 套基础模板）

### Phase 2（标注迭代，~4 天）
- 前端标注工具面板（点击元素 → 弹出标注气泡 → 选择类型 → 填写意见）
- A3 标注解析 + 增量更新逻辑
- 原型版本管理（历史版本浏览 + diff 对比）
- SSE 增量更新事件

### Phase 3（MCP 增强 + Gate1 集成，~3 天）
- MCP 知识库工具集成：`get_ui_templates`、`get_design_system`
- Gate1 打回 A3 返工流程（`a3_rework=true` 分支）
- 多状态截图自动生成（default/loading/empty/error/hover/active）
- E2E 全链路测试

---

## 十二、总结

| 维度 | 内容 |
|------|------|
| **入口** | `context.ready.A3`（Gate0 pass / Gate1 打回含 `a3_rework=true`） |
| **出口** | `agent.result.A3`（用户确认原型定稿） |
| **核心产物** | 高保真 HTML 原型（S3 URL）+ 多状态 screens + 标注历史 |
| **产物存储** | `prototype_artifacts`（版本化管理）+ `agent_results`（A3, cycle 快照） |
| **交互模式** | HTTP+SSE 多轮标注迭代，类 A1 双通道模型 |
| **返工机制** | Gate1 拒绝默认不触发 A3 返工，仅当审批人明确勾选 `a3_rework=true` |
| **降级策略** | LLM 不可用→预设模板；MCP 不可用→跳过知识增强；S3 不可用→inline Base64 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
