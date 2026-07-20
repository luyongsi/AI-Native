# A1 需求分析 Agent - 完整设计文档

## 文档信息
- **版本**: v3.5
- **日期**: 2026-07-10
- **状态**: 完整设计文档（已对齐系统状态机 v2.4 + 阶段一数据字典 v1.3）
- **参考**: [系统状态机与信息流设计](../系统架构/系统状态机与信息流设计.md) · [阶段一数据字典](./阶段一-数据字典.md)
- **说明**: A1 负责阶段一需求分析，范围从 req_id 创建到 Gate0 审批（含打回修订）。Gate0 通过后流程交由后续 Agent，与 A1 无关。**本文档中所有数据结构、字段名、枚举值以数据字典为准。**

---

## 一、通信架构

A1 采用**双通道**模型：

```
┌──────────┐  HTTP + SSE Stream   ┌──────────────┐   NATS (统一调度)   ┌──────────────┐
│   前端    │ ◄──────────────────► │  MC Backend  │ ◄─────────────────► │ Orchestrator │
│  (用户)   │                      │   (含A1)     │                     │              │
└──────────┘                      └──────────────┘                     └──────────────┘
```

- **HTTP + SSE Stream**：面向用户的多轮对话交互
- **NATS**：接收 Orchestrator 调度（`context.ready.A1`，**仅 Gate0 打回场景**），发布完成结果（`agent.result.A1`）

---

## 二、整体业务流程

### 2.1 A1 在阶段一中的位置

```
阶段一：需求分析
┌─────────────────────────────────────────┐
│                                         │
│  A1 需求分析 ──► A2 知识分析 ──► Gate0  │
│    ↑                              │     │
│    └──── Gate0 打回后修订 ────────┘     │
│                                         │
└─────────────────────────────────────────┘
              │
              ▼ Gate0 通过后进入阶段二（A3，与 A1 无关）
```

### 2.2 核心流程概览

```
用户点击"创建需求" → POST /api/requirements → 创建 requirements (req_id)
用户进入对话 → POST /api/dialogue/chat {req_id, message} → 创建 dialogue_sessions
A1 多轮对话（HTTP+SSE） → MCP/知识库增强 → 用户确认
    → MC Backend 持久化产物到 requirements 表 + agent_results 表
    → 发布 agent.result.A1（NATS）
    → Orchestrator 查询 DB → build_context → context.ready.A2
    → A2 知识分析 → agent.result.A2
    → Orchestrator 查询 DB → build_context → context.ready.gate0
    → Gate0 产品审批
         ├── ✅ pass → 进入阶段二（A3）
         └── ❌ reject → Gate0 写入 approvals + 发布 agent.result.gate0.reject
              → Orchestrator 更新 DB + 发布 context.ready.A1（含拒绝原因）
              → A1 会话 REOPENED → 用户修订 → 确认 → agent.result.A1
              → 重新走 A2 → Gate0（cycle 递增）
```

### 2.3 关键设计原则

1. **双通道协作**：用户对话走 HTTP+SSE，编排调度走 NATS（仅打回场景）
2. **req_id 预创建**：用户点击"创建需求"按钮时生成，对话前需已有 req_id
3. **产物自持久化**：A1 确认时写入 `requirements` + `agent_results`，草案每轮快照存入 agent_results
4. **cycle 统一轮次**：`dialogue_messages`、`understanding_snapshots`、`agent_results` 均以 `cycle` 标记轮次
5. **范围收敛**：A1 只关注到 Gate0

---

## 三、A1 独立对话流程

### 3.1 用户创建需求

- API: `POST /api/requirements`
- 请求体：
```json
{
  "title": "用户管理系统（可选，可后续补充）"
}
```
- 响应：`{req_id: "uuid", status: "draft"}`

### 3.2 用户发起对话

- API: `POST /api/dialogue/chat`
- 请求体：
```json
{
  "req_id": "uuid",
  "message": "我想做一个用户管理系统",
  "session_id": null
}
```

MC Backend 处理：
- 创建 `dialogue_sessions`（关联已有 req_id）
- 写入首条 `dialogue_messages`（cycle=0）
- 调用 A1 分析函数，SSE Stream 返回

### 3.3 A1 分析处理逻辑

```
加载对话历史 → LLM分析(Stream) → 调用MCP/知识库 → 生成理解草案 → 识别待澄清点 → 保存数据 → 完成Stream
```

- **1. 加载对话历史** → `dialogue_messages` WHERE session_id=? ORDER BY sequence_number
- **2. LLM Stream 分析** → 对话历史 + 系统 prompt，调用 LLM API
- **3. 调用 MCP/知识库**：`search_similar_requirements` / `get_domain_risks` / `get_tech_stack_recommendations` / `get_cost_baseline`
- **4. 生成理解草案** → 结构见 [数据字典 §4.2](./阶段一-数据字典.md#42-需求草案结构requirement_draft)
- **5. 识别待澄清点**
- **6. 保存理解快照** → `understanding_snapshots`（含 `cycle`）
- **7. 更新会话状态** → `dialogue_sessions`
- **8. 记录 A1 消息** → `dialogue_messages`（含 `cycle`）
- **9. Stream 结束** → done 事件

### 3.4 多轮对话

与首次相同 API，通过 session_id 关联。全部走 HTTP+SSE，使用当前 cycle。

### 3.5 用户确认完成

- API: `POST /api/dialogue/confirm`
- `cycle` = `requirements.gate_rejection_count`
- **持久化**（在同一数据库事务中）：
  - `requirements.requirement_draft` = 最终草案（最新镜像）
  - `requirements.confidence_score` = 置信度
  - `requirements.status` = `'analyzing_completed'`
  - `requirements.analyzed_at` = NOW()
  - `requirements.revision_count += 1`（修订时）
  - `requirements.last_revised_at` = NOW()（修订时）
  - `agent_results` INSERT: `agent_key='A1'`, `cycle`, `status='completed'`, `artifact` = `{requirement_draft: <该轮完整草案快照>, wireframe_url}`
  - `dialogue_sessions.status` = `'completed'`
  - `dialogue_sessions.human_confirmations` 追加一条 `{confirmed_at, cycle, final_notes}`
- **发布 NATS**：`agent.result.A1`（payload 见 [数据字典 §4.4](./阶段一-数据字典.md#agentresulta1a1--orchestrator)）

---

## 四、A1 发布后：A2 与 Gate0

A1 不调用 A2/Gate0，仅了解流转路径：

1. Orchestrator 收到 `agent.result.A1` → 写入 event_log → 查询 DB → build_context → `context.ready.A2`
2. A2 执行分析 → 持久化到 `agent_results` (A2) → `agent.result.A2`
3. Orchestrator 查询 DB → build_context → `context.ready.gate0`
4. Gate0 审批 → **自行写入 approvals** → 发布 pass/reject

**A2 异常处理**：A2 超时 → 重试 1 次 → 仍失败 → Orchestrator 写入 `agent_results` (A2, status='skipped')，`context.ready.gate0` 中 `a2_missing = true`。

---

## 五、Gate0 打回流程

### 5.1 Gate0 拒绝

Gate0 自行写入 approvals 后发布 `agent.result.gate0.reject`。Orchestrator 收到后：

1. 写入 event_log (IN)
2. 更新 `requirements`：`status='gate_rejected'`, `gate_rejection_count+=1`, `last_gate_rejection`
3. 更新 `dialogue_sessions`：`status='reopened'`
4. 注入 `dialogue_messages`：`role='system'`, `type='gate_rejection'`, `cycle` = 旧 cycle
5. 发布 `context.ready.A1`（`cycle` = 递增后的 `gate_rejection_count`，payload 见 [数据字典 §4.4](./阶段一-数据字典.md#contextreadya1orchestrator--a1仅-gate0-打回场景)）
6. 写入 event_log (OUT)

### 5.2 用户修订

- `GET /api/dialogue/history/{session_id}` → 前端按 cycle 分组展示
- `POST /api/dialogue/chat` → 新消息 `cycle` = 当前 `gate_rejection_count`
- 修订完成后 `POST /api/dialogue/confirm` → 同 3.5

### 5.3 打回后流转

```
agent.result.A1 → Orchestrator → 完整重走 A2 → Gate0（cycle 递增）
```

---

## 六、数据库表设计

### 6.1 核心表

- `requirements` — 需求主表，见 [数据字典 §3.1](./阶段一-数据字典.md#31-requirements-表需求主表)
- `agent_results` — Agent 产物表，见 [数据字典 §3.2](./阶段一-数据字典.md#32-agent_results-表agent-产物独立表)
- `dialogue_sessions` — 对话会话，A1 管理
- `dialogue_messages` — 对话消息（含 `cycle`），A1 管理
- `understanding_snapshots` — 理解快照（含 `cycle`），A1 管理

### 6.2 dialogue_sessions 表

```sql
CREATE TABLE dialogue_sessions (
    id                  UUID PRIMARY KEY,
    req_id              UUID UNIQUE REFERENCES requirements(id) ON DELETE CASCADE,
    status              VARCHAR(50) DEFAULT 'active',
    iterations          INT DEFAULT 0,
    total_messages      INT DEFAULT 0,
    current_understanding JSONB,
    clarification_points  JSONB,
    confidence_score    NUMERIC(3,2),
    human_confirmations JSONB DEFAULT '[]'::jsonb,
    creator_user_id     VARCHAR(255),
    creator_name        VARCHAR(255),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    last_updated        TIMESTAMPTZ DEFAULT NOW(),
    first_confirmed_at  TIMESTAMPTZ,
    last_confirmed_at   TIMESTAMPTZ
);
```

### 6.3 dialogue_messages 表

```sql
CREATE TABLE dialogue_messages (
    id                      BIGSERIAL PRIMARY KEY,
    session_id              UUID REFERENCES dialogue_sessions(id) ON DELETE CASCADE,
    role                    VARCHAR(20) CHECK (role IN ('human', 'ai', 'system')),
    content                 JSONB NOT NULL,
    cycle                   INT DEFAULT 0,
    understanding_snapshot_id BIGINT,
    timestamp               TIMESTAMPTZ DEFAULT NOW(),
    sequence_number         INT NOT NULL
);
```

`content` 结构见 [数据字典 §3.6](./阶段一-数据字典.md#36-dialogue_messages-表a1-管理)。

### 6.4 understanding_snapshots 表

```sql
CREATE TABLE understanding_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID REFERENCES dialogue_sessions(id) ON DELETE CASCADE,
    iteration           INT NOT NULL,
    cycle               INT DEFAULT 0,
    draft               JSONB NOT NULL,
    clarification_points JSONB,
    confidence_score    NUMERIC(3,2),
    knowledge_sources   JSONB,
    mcp_tools_used      JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.5 A1 写入 agent_results

```sql
INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
VALUES (?, 'A1', ?, 'completed', ?);
-- artifact = {"requirement_draft": {...}, "wireframe_url": "..."}
```

---

## 七、NATS 事件协议

A1 涉及两个事件，完整定义见 [数据字典 §4.4](./阶段一-数据字典.md#44-nats-事件)。

| 事件 | 方向 | 触发时机 |
|------|------|---------|
| `agent.result.A1` | A1 → Orchestrator | 用户点击确认提交 |
| `context.ready.A1` | Orchestrator → A1 | **仅 Gate0 打回时**（首次不触发） |

---

## 八、关键业务规则

### 8.1 会话状态流转

```
active → completed → reopened → completed → ...
```

### 8.2 需求状态流转（A1 范围内）

```
draft → analyzing_completed ↔ gate_rejected → approved (Gate0 通过后)
```

### 8.3 cycle 管理

- `cycle` = `requirements.gate_rejection_count`，首次 = 0
- 每次 Gate0 拒绝后 Orchestrator 递增 `gate_rejection_count`
- A1 新消息和快照使用当前 `cycle`
- `agent_results` 通过 `(req_id, agent_key, cycle)` 保留每轮完整草案快照
- 修订前后草案改动通过比较相邻 cycle 的 `agent_results` A1 artifact 获取

### 8.4 数据一致性

- `requirements` + `agent_results` + `dialogue_sessions` 的确认操作在同一数据库事务中
- `human_confirmations` 每次确认追加一条

---

## 九、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| A1 会话无活动 | 24h | 标记 abandoned |
| A2 知识分析超时 | 10min | 重试 1 次，仍失败 Orchestrator 写入 agent_results (status='skipped') |
| Agent 执行超时 | 30min | 重试 1 次，连续 2 次超时通知升级 |
| Gate0 审批超时 | 1h | 通知不自动通过 |
| NATS 投递失败 | 30s | Outbox 重试，5 次入死信队列 |

---

## 十、前端交互

### 10.1 创建需求

- `POST /api/requirements` → 获取 req_id → 进入对话页面

### 10.2 对话界面

- `POST /api/dialogue/chat {req_id, message}` — SSE Stream
- `POST /api/dialogue/confirm` — 确认提交
- `GET /api/dialogue/history/{session_id}` — 加载历史

### 10.3 历史对话展示

按 cycle 分组：cycle=0（灰色）→ Gate0 打回消息（红色高亮）→ cycle=1（正常）→ ...

---

## 十一、实施建议

### Phase 1: 基础流程（1周）
- 数据库 migration + API: `POST /api/requirements` + `POST /api/dialogue/chat`（SSE）+ `POST /api/dialogue/confirm`
- A1 分析模块（LLM + MCP）+ 前端

### Phase 2: MCP 知识增强（1周）
- knowledge-base-mcp 部署 + MCP 调用进度通知

### Phase 3: Orchestrator + Gate0 集成（1周）
- Orchestrator 订阅/发布 + event_log
- Gate0 审批 + 打回全链路（含 cycle 管理）

---

## 十二、总结

- **入口**: `POST /api/requirements` → req_id → `POST /api/dialogue/chat`
- **出口**: `agent.result.A1`（payload 以数据字典为准）
- **草案快照**: `agent_results` A1 → `artifact.requirement_draft`（每轮保留）
- **最新镜像**: `requirements.requirement_draft`
- **循环**: `context.ready.A1`（仅打回）→ 恢复会话 → `agent.result.A1`（cycle 递增）

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-10
**版本**: v3.5（对齐阶段一数据字典 v1.3）
**数据规范**: [阶段一数据字典](./阶段一-数据字典.md)
