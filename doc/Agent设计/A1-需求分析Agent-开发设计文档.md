# A1 需求分析 Agent — 完整开发设计文档

## 文档信息
- **版本**: v2.1
- **日期**: 2026-07-10
- **状态**: 开发设计（对齐设计规格 v3.5 + 数据字典 v1.3，通过 critical 审计）
- **参考**: [A1 完整设计规格](../Agent规格/A1-需求分析Agent完整设计.md) · [阶段一数据字典](../Agent规格/阶段一-数据字典.md) · [系统状态机 v2.4](../系统架构/系统状态机与信息流设计.md)
- **原则**: 以数据字典为唯一数据规范源；全新建设

---

## 一、开发范围

### 1.1 全链路流程

```
前端 POST /api/requirements → req_id (status='draft')
    ↓
前端 POST /api/dialogue/chat {req_id, message} → SSE Stream
    ↓
MC Backend → 创建 dialogue_sessions → MCP 知识库检索 → A1 LLM 流式分析 → SSE 返回
    ↓
多轮对话（HTTP+SSE，每轮快照存入 understanding_snapshots）
    ↓
前端 POST /api/dialogue/confirm
    ↓
MC Backend 事务: UPDATE requirements + INSERT agent_results(A1) + dialogue_sessions→completed
  + 事务内写入 event_log（outbox, direction='OUT', outbox_status='pending'）
    ↓
Outbox Publisher 读取 event_log → 发布 NATS: agent.result.A1
    ↓
Orchestrator → event_log(IN, outbox_status=NULL) → build_context → context.ready.A2
  → A2 → agent.result.A2 → context.ready.gate0 → Gate0
    ├── pass → 阶段二（A3）
    └── reject → agent.result.gate0.reject → Orchestrator
          → 更新 DB + 发布 context.ready.A1 → MC Backend 会话 REOPENED
          → 用户修订 → confirm → 重新走 A2→Gate0（cycle 递增）
```

### 1.2 A1 职责边界

- **负责**: req_id 创建 → 多轮对话分析 → 确认提交 → Gate0 打回后修订
- **不负责**: A2 调度、Gate0 审批、阶段二及之后

---

## 二、数据库设计

全部对齐 [数据字典 §3](../Agent规格/阶段一-数据字典.md#三数据库表)。全新建设，不修改历史表。

### 2.1 新建 `requirements` 表

```sql
CREATE TABLE requirements (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title                 VARCHAR(500),             -- 需求标题（冗余字段，与 requirement_draft.title 保持同步）
    status                VARCHAR(50) NOT NULL DEFAULT 'draft',
    -- 'draft' → 'analyzing_completed' ↔ 'gate_rejected' → 'approved'

    requirement_draft     JSONB,                    -- 最新需求草案镜像
    confidence_score      NUMERIC(3,2),             -- A1 置信度 0-1

    creator_user_id       VARCHAR(255),
    creator_name          VARCHAR(255),
    analyzer_agent        VARCHAR(50) DEFAULT 'A1',
    analyzed_at           TIMESTAMPTZ,

    gate_rejection_count  INT DEFAULT 0,            -- cycle 计数器
    last_gate_rejection   JSONB,                    -- 最新打回信息
    revision_count        INT DEFAULT 0,
    last_revised_at       TIMESTAMPTZ,

    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_requirements_status ON requirements(status);
```

> `title` 为冗余快照列，与 `requirement_draft->>'title'` 保持同步。写入时两者同时更新。查询列表直接取 `title` 列，无需解析 JSONB。

### 2.2 新建 `agent_results` 表

```sql
CREATE TABLE agent_results (
    id          BIGSERIAL PRIMARY KEY,
    req_id      UUID NOT NULL REFERENCES requirements(id),
    agent_key   VARCHAR(10) NOT NULL,       -- 'A1', 'A2', ...
    cycle       INT NOT NULL DEFAULT 0,
    status      VARCHAR(20) NOT NULL DEFAULT 'completed',
    -- 'completed': 正常完成（A1 始终用此值）
    -- 'empty':    无匹配结果（仅 A2）
    -- 'skipped':  被 Orchestrator 跳过（仅 A2 超时）
    artifact    JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (req_id, agent_key, cycle)
);

CREATE INDEX idx_agent_results_req ON agent_results(req_id, agent_key, cycle DESC);
```

### 2.3 新建 `dialogue_sessions` 表

```sql
CREATE TABLE dialogue_sessions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    req_id                UUID UNIQUE NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    status                VARCHAR(50) DEFAULT 'active',
    -- 'active' | 'completed' | 'reopened' | 'abandoned'

    iterations            INT DEFAULT 0,
    total_messages        INT DEFAULT 0,
    current_understanding JSONB,
    clarification_points  JSONB,
    confidence_score      NUMERIC(3,2),
    human_confirmations   JSONB DEFAULT '[]'::jsonb,

    creator_user_id       VARCHAR(255),
    creator_name          VARCHAR(255),

    created_at            TIMESTAMPTZ DEFAULT NOW(),
    last_updated          TIMESTAMPTZ DEFAULT NOW(),
    first_confirmed_at    TIMESTAMPTZ,
    last_confirmed_at     TIMESTAMPTZ
);
```

> `req_id` ↔ `dialogue_sessions` 为 **1:1**，一个需求一个对话会话，修订在原会话中继续。

### 2.4 新建 `dialogue_messages` 表

```sql
CREATE TABLE dialogue_messages (
    id                        BIGSERIAL PRIMARY KEY,
    session_id                UUID NOT NULL REFERENCES dialogue_sessions(id) ON DELETE CASCADE,
    role                      VARCHAR(20) NOT NULL CHECK (role IN ('human', 'ai', 'system')),
    content                   JSONB NOT NULL,
    cycle                     INT NOT NULL DEFAULT 0,
    understanding_snapshot_id BIGINT,
    timestamp                 TIMESTAMPTZ DEFAULT NOW(),
    sequence_number           INT NOT NULL,

    UNIQUE (session_id, cycle, sequence_number)
);

CREATE INDEX idx_dialogue_messages_session_cycle
    ON dialogue_messages(session_id, cycle, sequence_number);
```

`content` JSONB 结构（按 role 区分）：

| role | content 结构 |
|------|-------------|
| `human` | `{"text": "用户原始消息"}` |
| `ai` | `{"text": "A1 回复文本", "draft_preview": {...}, "clarifications": [{"question": "...", "suggestion": "..."}]}` |
| `system` | `{"type": "gate_rejection", "reject_reasons": [{"category": "...", "description": "..."}], "revision_guidance": "...", "cycle": 0}` |

`sequence_number` 在应用层按 `(session_id, cycle)` 分组自增，由 `SELECT ... FOR UPDATE` 锁保证并发安全（见 §3.2）。

### 2.5 新建 `understanding_snapshots` 表

```sql
CREATE TABLE understanding_snapshots (
    id                    BIGSERIAL PRIMARY KEY,
    session_id            UUID NOT NULL REFERENCES dialogue_sessions(id) ON DELETE CASCADE,
    iteration             INT NOT NULL,
    cycle                 INT DEFAULT 0,
    draft                 JSONB NOT NULL,
    clarification_points  JSONB,
    confidence_score      NUMERIC(3,2),
    knowledge_sources     JSONB,
    mcp_tools_used        JSONB,
    wireframe_data        JSONB,              -- 线框图原始数据（confirm 时上传 S3 用）
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_understanding_snapshots_session_cycle
    ON understanding_snapshots(session_id, cycle);
```

> `wireframe_data` 列存放 A1 分析过程中生成的线框图 JSON。确认时从最新 snapshot 读取此数据上传 S3 生成 URL，放入 `agent_results.artifact.wireframe_url`。此列解决多实例部署下 wireframe 数据在内存中丢失的问题。

### 2.6 新建 `event_log` 表（含 Outbox 功能）

```sql
CREATE TABLE event_log (
    id            BIGSERIAL PRIMARY KEY,
    req_id        UUID,
    session_id    UUID,
    cycle         INT,
    event_name    VARCHAR(100) NOT NULL,
    direction     VARCHAR(10) NOT NULL CHECK (direction IN ('IN', 'OUT')),
    payload       JSONB NOT NULL,
    outbox_status VARCHAR(20) DEFAULT NULL,
    -- NULL:   不需要发布（direction='IN' 的记录，仅审计）
    -- 'pending':   待 NATS 发布（direction='OUT'）
    -- 'published': 已发布
    -- 'failed':    发布失败（5 次重试后）
    published_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT ck_outbox CHECK (
        direction = 'IN' OR outbox_status IS NOT NULL
    )
);

CREATE INDEX idx_event_log_req ON event_log(req_id, cycle);
CREATE INDEX idx_event_log_name ON event_log(event_name);
CREATE INDEX idx_event_log_outbox ON event_log(outbox_status, created_at)
    WHERE outbox_status = 'pending';
```

**设计要点**:
- `direction='IN'` 的记录 `outbox_status` 固定为 `NULL`（Orchestrator 写入，仅审计），由 CHECK 约束保证
- `direction='OUT'` 的记录 `outbox_status` 必填（初始为 `'pending'`），由 CHECK 约束保证
- Outbox Publisher 仅轮询 `WHERE outbox_status='pending'`，不会误处理 IN 记录

**Outbox 机制**: MC Backend 的 `POST /api/dialogue/confirm` 在同一事务内写入 `event_log`。独立的 Outbox Publisher 进程每 **2 秒** 轮询 `pending` 记录，发布 NATS 后更新为 `published`。重试 5 次（指数退避 1s/2s/4s/8s/16s）后标记 `'failed'` 并发告警。`failed` 记录需人工检查后手动 `UPDATE event_log SET outbox_status='pending' WHERE id=?` 重置重试。

### 2.7 新建 `approvals` 表

```sql
CREATE TABLE approvals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    req_id              UUID NOT NULL REFERENCES requirements(id),
    session_id          UUID NOT NULL,
    gate_level          INT NOT NULL DEFAULT 0,
    cycle               INT NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',   -- 'pending' → 'decided'
    decision            VARCHAR(10) CHECK (decision IN ('pass', 'reject')),
    reject_reasons      JSONB,                                    -- [{"category": "...", "description": "..."}]
    revision_guidance   TEXT,                                     -- reject 时必填
    reviewer_user_id    VARCHAR(255),
    reviewer_name       VARCHAR(255),
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT ck_approval_decision CHECK (
        (status = 'pending' AND decision IS NULL AND reviewer_user_id IS NULL AND reviewed_at IS NULL)
        OR (status = 'decided' AND decision IS NOT NULL AND reviewer_user_id IS NOT NULL AND reviewed_at IS NOT NULL)
    )
);

CREATE INDEX idx_approvals_req ON approvals(req_id, cycle);
```

---

## 三、API 设计

### 3.0 认证与鉴权

所有面向用户的 API（§3.1-3.5）使用 **JWT Bearer Token** 认证。`creator_user_id` 和 `creator_name` 从 JWT claims 的 `sub` 和 `name` 字段提取。

内部服务 API（§3.6）使用 **API Key** 认证（HTTP header `X-Api-Key`），密钥从环境变量 `INTERNAL_API_KEY` 读取。调用方仅限 Orchestrator（`notify_mc` activity）和 Outbox Publisher。

### 3.1 `POST /api/requirements`

**职责**: 创建需求，返回 `req_id`。

**认证**: JWT。

**请求体**:
```json
{
  "title": "用户管理系统（可选，可后续补充）"
}
```

**处理逻辑**:
1. 从 JWT 提取 `creator_user_id`（`sub`）、`creator_name`（`name`）
2. `INSERT INTO requirements (title, status, creator_user_id, creator_name)` — status=`'draft'`
3. 初始化 `requirement_draft = {"title": title}`

**响应** (201):
```json
{
  "req_id": "uuid",
  "status": "draft",
  "title": "用户管理系统",
  "created_at": "ISO 8601"
}
```

### 3.2 `POST /api/dialogue/chat`

**职责**: 发起/继续对话，SSE 流式返回分析结果。

**认证**: JWT。

**请求体**:
```json
{
  "req_id": "uuid",
  "message": "我想做一个用户管理系统",
  "session_id": null
}
```

**处理逻辑**:

```
1. 验证 req_id 存在且 status in ('draft', 'gate_rejected')
2. BEGIN 事务（或异步连接上下文中获取 conn）:
3. session 管理:
   a. 锁定 requirements 行（该行一定存在，避免首次对话的并发竞态）:
      - SELECT id FROM requirements WHERE id=? FOR UPDATE
   b. session_id 为 null:
      - 验证 req_id 无已存在的 session（查 dialogue_sessions）
      - 创建 dialogue_sessions (req_id, status='active', creator_*)
      - cycle = requirements.gate_rejection_count
      - 若 requirements.status='gate_rejected' 则 session.status='reopened'
   c. session_id 非空:
      - SELECT * FROM dialogue_sessions WHERE id=? FOR UPDATE — 锁住 session 行
      - 验证 session 属于该 req_id 且 status in ('active', 'reopened')
      - cycle = requirements.gate_rejection_count
4. 计算 sequence_number（requirements 行和 session 行均已锁，无竞态）:
   - SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM dialogue_messages
     WHERE session_id=? AND cycle=?
5. 写入用户消息:
   - INSERT INTO dialogue_messages (session_id, role='human', content, cycle, sequence_number)
6. UPDATE dialogue_sessions SET last_updated=NOW()
7. COMMIT 事务
8. 加载对话历史:
   - SELECT * FROM dialogue_messages WHERE session_id=? ORDER BY sequence_number
9. 构建分析上下文:
   - 对话历史 + 当前 cycle + requirements.requirement_draft（若有）
10. MCP 知识库检索（并行，先于 LLM）:
    - search_similar_requirements / get_domain_risks / get_tech_stack_recommendations / get_cost_baseline
11. 调用 A1 LLM 流式分析（MCP 结果注入上下文）
12. SSE Stream 返回（事件格式见 §3.2.1）
13. finally（流完成或中断后执行）:
    a. INSERT INTO understanding_snapshots → 获得 snapshot_id
    b. INSERT INTO dialogue_messages (role='ai', content, cycle, sequence_number+1, understanding_snapshot_id=snapshot_id)
    c. UPDATE dialogue_sessions SET iterations=iterations+1, total_messages=total_messages+2, confidence_score=<置信度>, last_updated=NOW()
```

> **SSE 中断处理**: 步骤 13 在 generator 的 `finally` 块中执行。若 `finally` 中任一 DB 写入失败，记录错误日志 + 告警（前端已有流式返回的内容，服务端日志可用于审计）。sequence_number 已被步骤 5 消费，不会重复使用。

#### 3.2.1 SSE 事件格式

A1 Agent 的 `analyze()` 方法 yield 结构化的 Python dict，由 MC Backend 路由层统一格式化为 SSE 字符串。

```
event: thinking
data: {"type": "thinking", "content": "正在检索知识库..."}

event: knowledge
data: {"type": "knowledge", "sources": [{"name": "similar_requirements", "count": 3}]}

event: draft_update
data: {"type": "draft_update", "draft": {"title": "...", "entities": [...], ...}}

event: clarification
data: {"type": "clarification", "items": [{"question": "...", "suggestion": "推荐方案"}]}

event: done
data: {"type": "done", "draft": {...}, "confidence_score": 0.85, "session_id": "uuid", "message_id": 123}
```

SSE 事件设计要点：
- `draft_update` 事件中 `draft` 结构与 [数据字典 §4.2 requirement_draft](../Agent规格/阶段一-数据字典.md#42-需求草案结构requirement_draft) 完全对齐
- `clarification` 事件中的 `items` 对应 `understanding_snapshots.clarification_points`
- `knowledge` 事件告知前端已检索到的知识源概要
- `done` 事件**必须**携带 `session_id`，前端以此为后续请求的会话标识
- `done` 事件中的 `draft` 为最终草案，前端以此替换流式过程中的临时渲染
- **调用方获取最终 draft**：通过收集最后一个 `draft_update` 事件中的 `draft` 字段（而非依赖 generator return value）

> **错误处理**: 若 LLM/MCP 异常，yield `{"type": "error", "content": "错误描述"}` 而非中断流。

### 3.3 `POST /api/dialogue/confirm`

**职责**: 用户确认完成，事务持久化并创建 Outbox 记录。

**请求体**:
```json
{
  "session_id": "uuid",
  "final_notes": "可选补充说明"
}
```

**处理逻辑（同一 DB 事务）**:

```
1. SELECT ... FOR UPDATE 锁定 session 行 + requirements 行
2. 验证 session.status in ('active', 'reopened')
3. 幂等检查:
   - SELECT 1 FROM agent_results WHERE req_id=? AND agent_key='A1' AND cycle=?
   - 若存在 → 直接 COMMIT 返回 {"ok": true, "already_confirmed": true}
4. cycle = requirements.gate_rejection_count
5. 读取最终草案:
   - 取最新 understanding_snapshots WHERE session_id=? AND cycle=? ORDER BY created_at DESC LIMIT 1 → draft
   - 取 dialogue_sessions.confidence_score
6. UPDATE requirements:
   - title = draft.title  -- 同步冗余列
   - requirement_draft = 最终草案
   - confidence_score = 置信度
   - status = 'analyzing_completed'
   - analyzed_at = NOW()
   - revision_count += 1（仅 cycle > 0）
   - last_revised_at = NOW()（仅 cycle > 0）
7. INSERT INTO agent_results:
   - req_id, agent_key='A1', cycle, status='completed'
   - artifact = {"requirement_draft": <完整草案快照>, "wireframe_url": wireframe_url}
8. UPDATE dialogue_sessions:
   - status = 'completed'
   - human_confirmations 追加 {"confirmed_at": NOW(), "cycle": cycle, "final_notes": final_notes}
   - first_confirmed_at = NOW()（若为 NULL）
   - last_confirmed_at = NOW()
9. 组装 NATS payload（对齐数据字典 §4.4）:
   {req_id, session_id, cycle, draft: {...}, wireframe_url, confidence_score, iterations, total_messages, timestamp}
10. INSERT INTO event_log:
    - req_id, session_id, cycle
    - event_name='agent.result.A1', direction='OUT', outbox_status='pending'
    - payload = 步骤 9 的完整 payload
11. COMMIT
```

**响应** (200):
```json
{
  "ok": true,
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "status": "analyzing_completed"
}
```

**wireframe_url 生成**:
1. 确认时从最新 `understanding_snapshots` 读取 `wireframe_data`（解决了多实例部署下内存丢失问题）
2. 若有 wireframe_data → 调用 `s3_proxy.upload_json(data, key=f"wireframes/{req_id}/{cycle}.json")` 上传
3. 返回的 S3 URL 存入 `artifact.wireframe_url`
4. S3 不可用时 `wireframe_url` 为 `null`

**Outbox 发布**: 独立 `OutboxPublisher` 进程每 2 秒轮询 `event_log WHERE outbox_status='pending' ORDER BY created_at LIMIT 50`：
1. `nats_client.publish(event_name, payload)`
2. 成功 → `UPDATE event_log SET outbox_status='published', published_at=NOW()`
3. 失败 → 保留 `'pending'`，重试 5 次（指数退避 1s/2s/4s/8s/16s），全部失败标记 `'failed'` + Prometheus alert
4. `failed` 记录恢复：手动 `UPDATE event_log SET outbox_status='pending' WHERE id=?`

### 3.4 `GET /api/dialogue/history/{session_id}`

**职责**: 加载对话历史，按 cycle 分组。

**认证**: JWT。验证请求用户与 session 的 `creator_user_id` 或 `requirements.creator_user_id` 一致。

**响应**:
```json
{
  "session_id": "uuid",
  "req_id": "uuid",
  "cycles": [
    {
      "cycle": 0,
      "status": "completed",
      "messages": [
        {
          "id": 1,
          "role": "human",
          "content": {"text": "我想做一个用户管理系统"},
          "timestamp": "ISO 8601",
          "sequence_number": 1
        },
        {
          "id": 2,
          "role": "ai",
          "content": {"text": "...", "draft_preview": {...}, "clarifications": [...]},
          "timestamp": "ISO 8601",
          "sequence_number": 2
        }
      ],
      "draft_snapshot": {...},
      "confirmed_at": "ISO 8601"
    }
  ]
}
```

**数据来源**:
- `messages` → `dialogue_messages` WHERE session_id=? ORDER BY cycle, sequence_number
- `draft_snapshot` → `agent_results` WHERE req_id=? AND agent_key='A1' AND cycle=N → `artifact.requirement_draft`
- `confirmed_at` → `dialogue_sessions.human_confirmations` 中匹配 `cycle=N` 的那条记录的 `confirmed_at`
- `status` → 若 `human_confirmations` 中存在该 cycle → `"completed"`，否则 `"revision"`

### 3.5 `GET /api/dialogue/current/{req_id}`

**职责**: 获取指定需求的当前会话状态（用于前端恢复对话上下文）。

**响应**:
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "status": "active",
  "cycle": 0,
  "iterations": 3,
  "total_messages": 6,
  "confidence_score": 0.85
}
```

### 3.6 `POST /api/requirements/{req_id}/status`

**职责**: Orchestrator 调用，更新 requirements 编排字段。

**认证**: API Key（`X-Api-Key` header）。

**请求体**:
```json
{
  "status": "gate_rejected",
  "gate_rejection_count": 1,
  "last_gate_rejection": {
    "gate_level": 0,
    "reject_reasons": [{"category": "requirement_unclear", "description": "..."}],
    "revision_guidance": "...",
    "rejected_at": "ISO 8601",
    "reviewer_name": "..."
  }
}
```

**安全约束**:
- API Key 校验通过后，仅允许更新以下白名单字段：`status`、`gate_rejection_count`、`last_gate_rejection`
- 禁止更新 `requirement_draft`、`confidence_score`、`title` 等 A1 写入字段
- 每次调用记录 `event_log`（direction='IN', outbox_status=NULL）

---

## 四、A1 Agent 核心实现

### 4.0 LLM 调用与数据结构全景

#### 4.0.1 数据流总览

```
用户消息 → DraftBuilder.stream_analyze()
              │
              ├─ System Prompt（含 requirement_draft 结构约束 + 流式输出协议）
              ├─ User Prompt（对话历史 + MCP 知识库 + 当前消息）
              │
              ▼ LLM Stream (SSE chunks)
              │
              ├─ 每段 chunk 解析为 requirement_draft 字段的增量更新
              ├─ Agent yield {"type": "draft_update", "draft": <当前完整草案>}
              │
              ▼ 流结束后
              │
              ├─ ClarificationEngine 分析草案中的模糊点
              ├─ BDDDrafter 基于最终草案生成验收标准
              ├─ WireframeGenerator 可选生成线框图
              │
              ▼ 路由层持久化
              │
              ├─ understanding_snapshots.draft          ← 最终 requirement_draft
              ├─ understanding_snapshots.clarification_points
              ├─ understanding_snapshots.knowledge_sources
              ├─ understanding_snapshots.wireframe_data
              ├─ dialogue_messages.content (AI)         ← 结构化摘要
              │
用户确认 ────► requirements.requirement_draft           ← 最新镜像（覆盖）
              agent_results.artifact.requirement_draft   ← 每轮快照（追加）
              agent_results.artifact.wireframe_url       ← S3 URL
```

#### 4.0.2 核心数据结构：`requirement_draft`

这是整个 A1 系统的**唯一数据枢纽**——LLM 输出、SSE 传输、前端渲染、数据库存储全部使用同一结构。

对齐 [数据字典 §4.2](../Agent规格/阶段一-数据字典.md#42-需求草案结构requirement_draft)：

```json
{
  "title": "用户管理系统",
  "description": "构建一个企业用户管理平台，支持用户的创建、编辑、查询、删除，以及基于角色的权限控制。",
  "domain": "user_management",
  "entities": [
    {
      "name": "用户",
      "attributes": ["用户名", "邮箱", "手机号", "角色", "状态", "创建时间"],
      "description": "系统核心实体，存储所有用户账号信息"
    },
    {
      "name": "角色",
      "attributes": ["角色名", "权限列表", "描述"],
      "description": "定义用户权限组，支持多角色分配"
    }
  ],
  "use_cases": [
    "管理员创建新用户并分配角色",
    "用户自助注册并邮箱验证",
    "管理员批量导入用户",
    "用户修改个人信息",
    "管理员禁用/启用用户账号"
  ],
  "acceptance_criteria": [
    "Given 管理员已登录 When 填写用户信息并提交 Then 用户创建成功，收到确认邮件",
    "Given 用户名已存在 When 管理员提交创建 Then 返回错误提示'用户名已存在'",
    "Given 用户被禁用 When 该用户尝试登录 Then 返回'账号已禁用，请联系管理员'"
  ],
  "constraints": [
    "单租户部署，支持最多 50,000 用户",
    "密码长度至少 8 位，包含大小写字母和数字",
    "审计日志保留 90 天"
  ],
  "risks": [
    "并发角色修改可能导致权限不一致，需使用乐观锁",
    "批量导入大数据量时可能触发超时"
  ],
  "estimated_cost": "后端 2 人月 + 前端 1 人月"
}
```

**字段语义**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `title` | string | ✓ | 需求标题，≤50 字 |
| `description` | string | ✓ | 需求概述，2-5 句话描述核心目标 |
| `domain` | string | ✓ | 业务领域，枚举值见下 |
| `entities` | array | | 核心数据实体列表 |
| `entities[].name` | string | ✓ | 实体名称 |
| `entities[].attributes` | string[] | | 实体属性列表 |
| `entities[].description` | string | | 实体说明 |
| `use_cases` | string[] | | 用户用例描述 |
| `acceptance_criteria` | string[] | | GWT 格式验收标准 |
| `constraints` | string[] | | 技术/业务约束 |
| `risks` | string[] | | 已识别的风险点 |
| `estimated_cost` | string | | 成本/工时估算 |

**domain 枚举**:

| 值 | 含义 |
|----|------|
| `user_management` | 用户/账号/权限管理 |
| `order_management` | 订单/交易管理 |
| `payment` | 支付/结算 |
| `product_catalog` | 商品/内容管理 |
| `inventory` | 库存/物流 |
| `auth` | 认证/授权 |
| `notification` | 消息/通知 |
| `reporting` | 统计/报表 |
| `approval` | 审批/工作流 |
| `general` | 其他/通用 |

#### 4.0.3 DraftBuilder System Prompt（唯一模板）

`DraftBuilder._build_system_prompt()` 使用此模板。变量通过 `str.replace()` 填充（**不用 `.format()`**，因为 JSON 中的 `{` `}` 会与 format 占位符冲突）。

```
你是一个资深需求分析师。你的任务是与用户多轮对话，逐步完善一份结构化的需求草案。

## 核心原则
1. **一次输出完整草案**: 每次输出都是完整的当前状态，不是增量补丁。
2. **主动推断填充**: 用户没说清楚的地方，基于最佳实践做合理假设并填入。不要留着空字段等待用户填空——后续对话可以修正。
3. **验收标准用 GWT 格式**: Given-When-Then，确保每条可验证。至少产出 2 条，目标 5 条以上。
4. **识别业务实体**: 从用户描述中提取核心业务对象，列出关键属性。
5. **中文输出**: 所有文本用中文。

## 输出结构（严格 JSON，不要 markdown 代码块包裹）

{{
  "title": "需求标题（≤50字）",
  "description": "需求概述（2-5句话，覆盖'做什么、给谁用、核心价值'）",
  "domain": "领域枚举值之一",
  "entities": [
    {{
      "name": "实体名称",
      "attributes": ["属性1", "属性2"],
      "description": "实体的一句话描述"
    }}
  ],
  "use_cases": ["用户故事或用例描述"],
  "acceptance_criteria": ["Given <前置> When <操作> Then <结果>"],
  "constraints": ["技术约束、业务约束、合规要求"],
  "risks": ["可能的风险点和缓解思路"],
  "estimated_cost": "工时/成本估算（如无信息则为 null）"
}}

## 领域枚举
user_management | order_management | payment | product_catalog | inventory | auth | notification | reporting | approval | general

## 字段填写指南
- title: ≤50字，精准描述
- description: 2-5句话
- domain: 从上述枚举中选择最匹配的
- entities: 每个实体列出 3-8 个关键属性
- use_cases: 覆盖主要用户场景和边界场景，至少 3 条
- acceptance_criteria: GWT 格式，每条可独立验证。至少 2 条，目标 5 条以上
- constraints: 技术限制、业务规则、合规要求
- risks: 可能的风险和对应的缓解思路
- estimated_cost: 如有足够信息则给出人月估算，否则为 null

## 知识库参考
__KNOWLEDGE_CONTEXT__

## 当前草案（多轮对话时）
__CURRENT_DRAFT__

## 对话历史
__HISTORY__

## 用户最新输入
__USER_MESSAGE__

请输出当前完整的需求草案 JSON。只输出 JSON，不要 markdown 代码块包裹，不要任何解释文字。
```

**变量填充方式**（用 `str.replace()` 避免与 JSON 花括号冲突）:

```python
def _build_system_prompt(self, ctx: dict) -> str:
    knowledge_text = self._format_knowledge_context(ctx["knowledge"])
    current_draft = ctx.get("current_draft")
    draft_text = json.dumps(current_draft, ensure_ascii=False, indent=2) if current_draft else "尚无"
    history_text = self._format_history(ctx.get("history", []))

    return (SYSTEM_PROMPT_TEMPLATE
            .replace("__KNOWLEDGE_CONTEXT__", knowledge_text)
            .replace("__CURRENT_DRAFT__", draft_text)
            .replace("__HISTORY__", history_text)
            .replace("__USER_MESSAGE__", ctx.get("user_message", "")))
```

> **为什么用 `__PLACEHOLDER__` 而非 `{placeholder}`**: JSON 示例中的 `{` `}` 会被 Python `str.format()` 误解为格式占位符。用 `str.replace()` + 双下划线占位符彻底避免冲突。最终发给 LLM 的文本中 `{{` 和 `}}` 各折叠为单花括号（因为在 Python 源码字符串中 `{{` 即 `{`）。

#### 4.0.4 LLM 流式解析协议

LLM 返回的是 SSE 流式文本。`DraftBuilder.stream_analyze()` 内部缓冲区积累字符，每次尝试解析完整的 JSON 对象。**解析成功后清空已消费部分**，防止重复 yield。

```python
import json
from typing import AsyncGenerator


class DraftBuilder:
    """LLM 流式草案构建器"""

    def __init__(self):
        self.llm = ...  # 调用 BaseAgentWorker.call_llm() 或直接 HTTP streaming

    async def stream_analyze(
        self, user_message: str, ctx: dict
    ) -> AsyncGenerator[dict, None]:
        """
        ctx = {
            "history": [dialogue_messages dicts ...],
            "current_draft": requirement_draft | None,
            "knowledge": {"similar_requirements": [...], ...},
            "cycle": 0,
            "user_message": "用户最新输入",
        }
        """
        system_prompt = self._build_system_prompt(ctx)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        buffer = ""
        last_valid_draft = ctx.get("current_draft") or {}
        has_yielded = False

        async for text_chunk in self._stream_llm(messages):
            buffer += text_chunk

            # 循环消费 buffer 中所有完整 JSON（LLM 可能一次输出多个）
            while True:
                draft, consumed = self._try_parse_json(buffer)
                if draft is not None:
                    last_valid_draft = draft
                    has_yielded = True
                    yield draft
                    buffer = buffer[consumed:]    # ← 清空已消费部分，防重复
                else:
                    break

        # 流结束：确保至少有一次输出
        if not has_yielded:
            yield last_valid_draft

    def _try_parse_json(self, buffer: str) -> tuple[dict | None, int]:
        """尝试从 buffer 开头提取完整 JSON 对象。

        使用括号深度计数判断 JSON 是否闭合，避免依赖 json.loads 的隐式截断。

        Returns:
            (parsed_dict, consumed_length) — 解析成功时 consumed_length > 0
            (None, 0) — buffer 中尚无完整 JSON，等待更多 chunk
        """
        start = buffer.find("{")
        if start == -1:
            return None, 0

        depth = 0
        in_string = False
        escape = False

        for i, ch in enumerate(buffer):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    json_str = buffer[:i + 1]
                    # 跳过开头的垃圾字符（第一个 { 之前的文本）
                    clean_json = json_str[start:]
                    try:
                        parsed = json.loads(clean_json)
                    except json.JSONDecodeError:
                        return None, 0
                    # 验证是 dict（不是数组或标量）
                    if not isinstance(parsed, dict):
                        return None, 0
                    return parsed, i + 1
        return None, 0
```

**关键行为**:
- 每次 yield 的是**完整的** `requirement_draft` dict（覆盖上一个版本），前端替换草稿面板
- `while True` 循环 + `buffer = buffer[consumed:]` 确保同一 buffer 中的多个 JSON 被依次消费
- 验证 `isinstance(parsed, dict)` 防止 LLM 输出数组或字符串被当作草案
- 如果 LLM 输出的 JSON 不完整（括号未闭合），等待更多 chunk
- 流结束时若从未成功解析，用 `last_valid_draft` 做兜底

#### 4.0.5 知识库文本注入

MCP 知识库结果在注入 System Prompt 前格式化为简洁文本（不带 Markdown 标题前缀，减少 token 消耗）：

```python
def _format_knowledge_context(self, knowledge: dict) -> str:
    parts = []

    similar = knowledge.get("similar_requirements", [])
    if similar:
        items = "\n".join(
            "  • [{sim:.0%}] {title}".format(
                sim=r.get("similarity", 0), title=r.get("title", "")[:100]
            )
            for r in similar[:5]
        )
        parts.append("相似历史需求:\n" + items)

    risks = knowledge.get("domain_risks", [])
    if risks:
        items = "\n".join(
            "  • [{sev}] {risk}: {desc}".format(
                sev=r.get("severity", "?"), risk=r.get("risk", ""),
                desc=r.get("description", ""),
            )
            for r in risks
        )
        parts.append("领域常见风险:\n" + items)

    tech = knowledge.get("tech_stack", {})
    if tech:
        items = "\n".join(
            "  • {k}: {v}".format(k=k, v=v) for k, v in tech.items()
        )
        parts.append("推荐技术栈:\n" + items)

    cost = knowledge.get("cost_baseline")
    if cost:
        parts.append(
            "成本基线:\n  • 预估工时: {effort} 人月, 团队规模: {size} 人".format(
                effort=cost.get("estimated_effort_months", "N/A"),
                size=cost.get("team_size", "N/A"),
            )
        )

    return "\n\n".join(parts) if parts else "无可用的历史参考数据"

def _format_history(self, history: list[dict]) -> str:
    """将对话历史格式化为 LLM 可理解的文本。"""
    if not history:
        return "（无对话历史）"
    lines = []
    for msg in history:
        role_label = {"human": "用户", "ai": "AI助手", "system": "系统通知"}.get(
            msg.get("role", ""), msg.get("role", "")
        )
        content = msg.get("content", {})
        if isinstance(content, dict):
            text = content.get("text", json.dumps(content, ensure_ascii=False))
        else:
            text = str(content)
        lines.append("{role}: {text}".format(role=role_label, text=text[:500]))
    return "\n".join(lines[-20:])
```

#### 4.0.6 数据结构→数据库→前端 映射总表

| 数据 | 来源 | SSE 事件 | 数据库存储 |
|------|------|----------|-----------|
| 需求草案（每轮实时） | `DraftBuilder.stream_analyze()` yield 的 dict | `draft_update.draft` | `understanding_snapshots.draft`（全量 JSONB） |
| 需求草案（最终版） | 最后一个 `draft_update` 事件 | `done.draft` | `requirements.requirement_draft`（镜像，覆盖） + `agent_results.artifact.requirement_draft`（快照，按 cycle 追加） |
| 待澄清问题 | `ClarificationEngine.identify()` 返回 `list[dict]` | `clarification.items` | `understanding_snapshots.clarification_points` |
| 置信度 | `A1Agent._calculate_confidence()` | `done.confidence_score` | `requirements.confidence_score` + `understanding_snapshots.confidence_score` |
| 知识源摘要 | `_summarize_sources()` 返回 `list[dict]`（不含原始数据） | `knowledge.sources` + `done.knowledge_sources` | `understanding_snapshots.knowledge_sources` |
| MCP 工具列表 | 固定 `list[str]` | `done.mcp_tools_used` | `understanding_snapshots.mcp_tools_used` |
| 线框图数据 | `WireframeGenerator.generate()` → `dict` | `wireframe.data` | `understanding_snapshots.wireframe_data` |
| 线框图 URL | `s3_proxy.upload_json()` → `str` | — | `agent_results.artifact.wireframe_url` |
| AI 消息（对话记录） | 路由层从所有事件组装结构化摘要 | — | `dialogue_messages.content`（role='ai', JSONB） |
| 需求标题（列表冗余） | `draft["title"]` | — | `requirements.title`（confirm 时同步） |

> `knowledge_sources` 存储的是 `_summarize_sources()` 的摘要（`[{"name": "...", "count": N}]`），不是完整 MCP 原始数据。避免 JSONB 列膨胀。

**前端渲染交互流程**:

```
用户发送消息
  ↓
SSE: thinking {content: "正在检索知识库..."} → 显示进度条
SSE: knowledge {sources: [{name, count}, ...]} → 显示 badge "参考 3 条相似需求, 2 个风险提示"
  ↓
SSE: draft_update {draft: <完整 requirement_draft>}  → 完整替换草稿面板
  (可能多次，每次都是完整 draft，前端替换渲染)
  ↓
SSE: clarification {items: [{question, suggestion}]}  → 对话区插入澄清问题卡片
  ↓
SSE: wireframe {data: <wireframe JSON>}  → 草稿面板底部渲染线框图
  ↓
SSE: done {draft, confidence_score, knowledge_sources, mcp_tools_used}  → 启用确认按钮
```

#### 4.0.7 A1Agent.analyze() 完整代码（已修复所有已知问题）

```python
# agent-workers/a1/agent.py

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


class A1Agent:
    """A1 需求分析 Agent — 纯分析逻辑，不含 DB/NATS 副作用"""

    agent_id = "A1"

    def __init__(self):
        self.mcp_client = MCPClient()
        self.draft_builder = DraftBuilder()
        self.clarification = ClarificationEngine()
        self.wireframe_gen = WireframeGenerator()
        self.bdd_drafter = BDDDrafter()

    async def analyze(
        self,
        req_id: str,
        session_id: str,
        user_message: str,
        history: list[dict],
        current_draft: Optional[dict],
        cycle: int,
    ) -> AsyncGenerator[dict, None]:
        """执行一轮分析，yield 结构化事件 dict。

        调用方 MC Backend 通过遍历事件获取分析结果。
        最终草案 = 最后一个 type='draft_update' 事件的 draft 字段。
        done 事件中的 knowledge_sources 是摘要（非原始数据），用于快照存储。
        """
        try:
            # Step 1: MCP 知识库检索（并行，先于 LLM）
            yield {"type": "thinking", "content": "正在检索知识库..."}
            knowledge = await self._fetch_knowledge(current_draft)
            knowledge_summary = self._summarize_sources(knowledge)
            yield {"type": "knowledge", "sources": knowledge_summary}

            # Step 2: LLM 流式分析（知识库结果注入上下文）
            yield {"type": "thinking", "content": "正在分析需求..."}
            ctx = self._build_context(
                history, user_message, current_draft, knowledge, cycle
            )
            accumulated_draft = current_draft or {}

            async for partial in self.draft_builder.stream_analyze(user_message, ctx):
                accumulated_draft = partial
                yield {"type": "draft_update", "draft": partial}

            # Step 3: 识别待澄清点
            clarifications = await self.clarification.identify(accumulated_draft, history)
            if clarifications:
                yield {"type": "clarification", "items": clarifications}

            # Step 4: 可选 -- 生成线框图
            wireframe = None
            if self._should_generate_wireframe(accumulated_draft):
                wireframe = await self.wireframe_gen.generate(accumulated_draft)
                yield {"type": "wireframe", "data": wireframe}

            # Step 5: 基于最终草案生成验收标准（BDD GWT）
            gwt_result = await self.bdd_drafter.draft_gwt(accumulated_draft)
            accumulated_draft["acceptance_criteria"] = self._gwt_to_strings(gwt_result)

            # Step 6: 计算置信度
            confidence = self._calculate_confidence(accumulated_draft, knowledge)

            # Step 7: 完成
            # knowledge_sources 存摘要，不存原始数据
            yield {
                "type": "done",
                "draft": accumulated_draft,
                "confidence_score": confidence,
                "knowledge_sources": knowledge_summary,
                "mcp_tools_used": [
                    "search_similar_requirements",
                    "get_domain_risks",
                    "get_tech_stack_recommendations",
                    "get_cost_baseline",
                ],
            }

        except Exception as e:
            logger.exception("[A1] analyze() error")
            yield {"type": "error", "content": "分析过程出错: {detail}".format(detail=str(e)[:200])}

    # ------------------------------------------------------------------
    #  private helpers
    # ------------------------------------------------------------------

    async def _fetch_knowledge(self, draft: dict) -> dict:
        """并行调用 4 个 MCP 知识库工具，失败降级不阻塞"""
        tasks = [
            self.mcp_client.search_similar_requirements(draft, timeout=5),
            self.mcp_client.get_domain_risks(draft.get("domain", "") if draft else "", timeout=5),
            self.mcp_client.get_tech_stack_recommendations(draft, timeout=5),
            self.mcp_client.get_cost_baseline(draft, timeout=5),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            "similar_requirements": results[0] if not isinstance(results[0], Exception) else [],
            "domain_risks":        results[1] if not isinstance(results[1], Exception) else [],
            "tech_stack":          results[2] if not isinstance(results[2], Exception) else {},
            "cost_baseline":       results[3] if not isinstance(results[3], Exception) else None,
        }

    def _build_context(self, history, user_message, draft, knowledge, cycle) -> dict:
        return {
            "history": history[-20:],
            "current_draft": draft,
            "knowledge": knowledge,
            "cycle": cycle,
            "user_message": user_message,
        }

    def _should_generate_wireframe(self, draft: dict) -> bool:
        """判断是否需要生成线框图。防御 null 值。"""
        entities = draft.get("entities") if isinstance(draft.get("entities"), list) else []
        use_cases = draft.get("use_cases") if isinstance(draft.get("use_cases"), list) else []
        return len(entities) > 0 or len(use_cases) >= 2

    def _gwt_to_strings(self, gwt_result: dict) -> list[str]:
        """将 BDD 输出的 dict 列表转为 GWT 格式字符串列表。

        BDD 输出: {"scenarios": [{"given": "...", "when": "...", "then": "..."}], ...}
        acceptance_criteria 要求: ["Given ... When ... Then ...", ...]
        """
        scenarios = gwt_result.get("scenarios", [])
        if not scenarios:
            return []
        strings = []
        for s in scenarios:
            if isinstance(s, dict):
                g = s.get("given", "")
                w = s.get("when", "")
                t = s.get("then", "")
                strings.append("Given {given} When {when} Then {then}".format(given=g, when=w, then=t))
            elif isinstance(s, str):
                strings.append(s)  # 容错：如果已经是 string 就直接用
        return strings

    def _calculate_confidence(self, draft: dict, knowledge: dict) -> float:
        """基于草案完整度和知识库覆盖的启发式评分。

        初始值 0.5：单次 LLM 分析至少覆盖基础意图理解和领域分类。
        null 安全的字段检查。
        """
        score = 0.5
        if draft.get("description"):
            score += 0.10
        if isinstance(draft.get("entities"), list) and draft["entities"]:
            score += 0.10
        if isinstance(draft.get("acceptance_criteria"), list) and draft["acceptance_criteria"]:
            score += 0.15
        if knowledge.get("similar_requirements"):
            score += 0.10
        if knowledge.get("domain_risks"):
            score += 0.05
        if knowledge.get("cost_baseline"):
            score += 0.05
        if knowledge.get("tech_stack"):
            score += 0.05
        return round(min(score, 1.0), 2)

    def _summarize_sources(self, knowledge: dict) -> list[dict]:
        """将 MCP 原始结果压缩为摘要，用于 SSE 展示 + snapshot 存储。

        Returns: [{"name": "similar_requirements", "count": 3}, ...]
        不包含原始数据，避免 JSONB 膨胀。
        """
        sources = []
        if knowledge.get("similar_requirements"):
            sources.append({"name": "similar_requirements", "count": len(knowledge["similar_requirements"])})
        if knowledge.get("domain_risks"):
            sources.append({"name": "domain_risks", "count": len(knowledge["domain_risks"])})
        if knowledge.get("tech_stack"):
            sources.append({"name": "tech_stack", "available": True})
        if knowledge.get("cost_baseline"):
            sources.append({"name": "cost_baseline", "available": True})
        return sources
```

### 4.1 模块架构

```
agent-workers/a1/
├── __init__.py
├── agent.py                     # A1Agent 主类 — analyze() yield 结构化 dict（见 §4.0.7）
├── analyzer/
│   ├── __init__.py
│   ├── draft_builder.py         # LLM 流式草案构建（见 §4.0.4）
│   ├── clarification.py         # 待澄清点识别
│   └── mcp_client.py            # MCP 知识库调用封装
├── wireframe/
│   ├── __init__.py
│   └── generator.py             # 低保真线框图（LLM 驱动）
├── bdd/
│   ├── __init__.py
│   └── drafter.py               # BDD 验收标准生成（LLM 驱动）
└── dialog/
    ├── __init__.py
    └── state_machine.py         # A1 内部分析步序控制（不影响 DB 会话状态）
```

### 4.2 A1Agent 主类与子模块接口

#### 4.2.0 子模块接口契约

在实现 `A1Agent` 前，需先定义各子模块的公开接口：

```python
# agent-workers/a1/analyzer/mcp_client.py

class MCPClient:
    """MCP 知识库调用封装。MCP 服务地址从环境变量 MCP_GATEWAY_URL 读取。"""

    async def search_similar_requirements(self, draft: dict, timeout: float = 5.0) -> list[dict]:
        """检索相似历史需求。draft 为当前 requirement_draft 或 None。
        Returns: [{"id": "uuid", "title": "需求标题", "similarity": 0.92, "metadata": {...}}, ...]
        """

    async def get_domain_risks(self, domain: str, timeout: float = 5.0) -> list[dict]:
        """查询领域风险。domain 为 requirement_draft.domain，可能为空字符串。
        Returns: [{"risk": "风险名称", "description": "...", "severity": "high|medium|low"}, ...]
        """

    async def get_tech_stack_recommendations(self, draft: dict, timeout: float = 5.0) -> dict:
        """推荐技术栈。draft 为当前 requirement_draft 或 None。
        Returns: {"backend": "...", "frontend": "...", "database": "..."} | {}
        """

    async def get_cost_baseline(self, draft: dict, timeout: float = 5.0) -> dict | None:
        """成本基线评估。draft 为当前 requirement_draft 或 None。
        Returns: {"estimated_effort_months": 3.0, "team_size": 2, "breakdown": {...}} | None
        """


# agent-workers/a1/analyzer/draft_builder.py

class DraftBuilder:
    """LLM 流式草案构建器"""

    async def stream_analyze(
        self, user_message: str, ctx: dict
    ) -> AsyncGenerator[dict, None]:
        """流式分析用户消息，每次 yield 当前完整的 requirement_draft dict。

        ctx 结构:
          {"history": [dialogue_messages行...],
           "current_draft": requirement_draft | None,
           "knowledge": {"similar_requirements": [...], "domain_risks": [...],
                         "tech_stack": {...}, "cost_baseline": {...}},
           "cycle": 0}

        每次 yield 的是当前完整的 requirement_draft（非增量 patch），
        结构对齐数据字典 §4.2:
          {"title", "description", "domain", "entities": [{"name", "attributes", "description"}],
           "use_cases": [...], "acceptance_criteria": [...], "constraints": [...],
           "risks": [...], "estimated_cost": "..."}

        前端需要自行对比前后版本做增量渲染高亮。
        """


# agent-workers/a1/analyzer/clarification.py

class ClarificationEngine:
    """待澄清点识别器"""

    async def identify(
        self, draft: dict, history: list[dict]
    ) -> list[dict]:
        """分析草案中的模糊点，返回待澄清问题列表。
        Returns: [{"question": "具体问题", "suggestion": "推荐方案", "field": "entities[0].attributes"}, ...]
        若无待澄清点则返回空列表。
        """


# agent-workers/a1/wireframe/generator.py

class WireframeGenerator:
    """低保真线框图生成器（LLM 驱动）"""

    async def generate(self, draft: dict) -> dict:
        """根据 requirement_draft 生成线框图 JSON。
        Returns: {"type": "low_fidelity", "pages": [{"id", "route", "title", "zones": [...]}],
                   "components": [{"page_id", "zone", "component", "props": {...}}]}
        """


# agent-workers/a1/bdd/drafter.py

class BDDDrafter:
    """BDD 验收标准生成器（LLM 驱动）"""

    async def draft_gwt(self, draft: dict) -> dict:
        """根据 requirement_draft 生成 GWT 场景。
        Returns: {"scenarios": [{"given": "...", "when": "...", "then": "..."}],
                   "coverage_score": 0.85}
        """
```

#### 4.2.1 A1Agent 主类

`A1Agent` 完整实现见 **[§4.0.7](#407-a1agentanalyze-完整代码已修复所有已知问题)**，包含所有 null 安全防御、类型转换、knowledge 摘要存储等修复。

> **关键设计决策**: A1 Agent 不做 DB 写入、不发布 NATS、不构建 SSE 格式字符串。所有副作用和传输层关注点由 MC Backend 路由层管理。

### 4.3 MC Backend 路由层职责

```
POST /api/dialogue/chat 路由处理函数:
  1. JWT 认证
  2. BEGIN 事务
  3. session 生命周期（创建/验证，FOR UPDATE 锁定）
  4. 计算 sequence_number（锁内，无竞态）
  5. INSERT 用户消息 → dialogue_messages
  6. UPDATE dialogue_sessions.last_updated
  7. COMMIT 事务
  8. 加载对话历史
  9. 实例化 A1Agent
  10. async for event in a1.analyze(...):
        - 将结构化 dict 格式化为 SSE 字符串发送给前端
        - 记录最后一个 type='draft_update' 事件的 draft
  11. finally:
        a. INSERT INTO understanding_snapshots → snapshot_id
        b. INSERT INTO dialogue_messages (role='ai', understanding_snapshot_id=snapshot_id)
        c. UPDATE dialogue_sessions (iterations, total_messages, confidence_score)

AI 回复 content 构建:
  content = {
      "text": accumulated_draft.get("description", "")[:200],  # 草案摘要片段
      "draft_preview": {k: accumulated_draft.get(k) for k in
          ["title", "domain", "entities_count", "use_cases_count", "acceptance_criteria_count"]
          if k in accumulated_draft},
      "clarifications": [{"question": c["question"], "suggestion": c["suggestion"]}
                         for c in (clarification_items or [])],
  }
  注: AI 消息不存储 LLM 原始输出文本。分析结果通过 SSE 事件实时展示，
  dialogue_messages.ai 的 content 仅存储结构化摘要用于历史展示。

SSE 格式化函数（在路由层，不在 Agent 内）:
  def _format_sse(event: dict) -> str:
      import json
      event_type = event["type"]  # 每个 event 必有 type，不使用 pop 避免副作用
      payload = {k: v for k, v in event.items() if k != "type"}
      return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

路由层收集快照所需数据:
  - 最后一个 type='draft_update' 事件的 draft → snapshot.draft
  - 最后一个 type='done' 事件的 confidence_score → snapshot.confidence_score
  - type='clarification' 事件的 items → snapshot.clarification_points
  - type='knowledge' 事件的 sources → snapshot.knowledge_sources
  - type='wireframe' 事件的 data → snapshot.wireframe_data
  - mcp_tools_used 由 Agent 在 done 事件中返回，路由层提取
```

### 4.4 MCP 知识库接口

| MCP 工具 | 触发时机 | 超时 |
|---------|---------|:--:|
| `search_similar_requirements` | 每轮分析 | 5s |
| `get_domain_risks` | 首次分析 + 域变更时 | 5s |
| `get_tech_stack_recommendations` | 首次分析 | 5s |
| `get_cost_baseline` | 确认前（每轮分析） | 5s |

4 个调用全部并行执行，单个失败不阻塞 — `asyncio.gather(..., return_exceptions=True)`。

---

## 五、NATS 事件与 Outbox

### 5.1 `agent.result.A1` — A1 → Orchestrator

由 Outbox Publisher 从 `event_log` 读取并发布。

Payload（对齐数据字典 §4.4）:
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "draft": {
    "title": "用户管理系统",
    "description": "提供一个用户管理的完整功能...",
    "domain": "user_management",
    "entities": [
      {
        "name": "用户",
        "attributes": ["用户名", "邮箱", "角色", "状态"],
        "description": "系统用户实体"
      }
    ],
    "use_cases": ["管理员创建用户", "用户自助注册", "角色权限分配"],
    "acceptance_criteria": [
      "Given 管理员已登录 When 管理员填写用户信息并提交 Then 用户创建成功并收到通知"
    ],
    "constraints": ["单租户部署", "支持最多10000用户"],
    "risks": ["并发角色修改可能导致权限不一致"],
    "estimated_cost": "3人月"
  },
  "wireframe_url": null,
  "confidence_score": 0.85,
  "iterations": 5,
  "total_messages": 12,
  "timestamp": "2026-07-10T12:00:00Z"
}
```

### 5.2 `context.ready.A1` — Orchestrator → A1（仅 Gate0 打回）

Payload（对齐数据字典 §4.4）:
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 1,
  "action": "revise",
  "gate_rejection": {
    "gate_level": 0,
    "reject_reasons": [
      {
        "category": "requirement_unclear",
        "description": "用户角色的权限边界需进一步明确"
      }
    ],
    "revision_guidance": "建议补充用户角色权限矩阵，明确管理员和普通用户的操作边界",
    "rejected_at": "2026-07-10T13:00:00Z"
  }
}
```

### 5.3 MC Backend 的 `context.ready.A1` 订阅

**与 A2-A12 的关键差异**:

| | A2-A12（自主 Agent） | A1（人类在回路） |
|---|---|---|
| 消费者 | Agent Worker 进程 (`base_worker.subscribe_nats`) | MC Backend HTTP 服务 |
| 收到事件后 | 立即调用 `execute()`，自主完成分析 | 更新 DB 会话状态，通知前端，**等待用户操作** |
| 结果产生 | Agent 执行完毕后自动发布 `agent.result` | 用户通过 HTTP+SSE 修订后在 confirm API 中发布 `agent.result.A1` |
| 延迟 | 秒~分钟（Agent 执行耗时） | 分钟~小时（取决于人类何时完成修订） |

A2 等 Agent 的 `context.ready.A2` 是 **"请开始你的工作"**——Agent 立即执行。
A1 的 `context.ready.A1` 是 **"会话已重开，等用户回来修订"**——只做状态变更和通知。

MC Backend 启动时在后台 asyncio task 中订阅 NATS `context.ready.A1`：

```python
async def subscribe_context_ready_a1():
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()

    async def handle(msg):
        payload = json.loads(msg.data.decode())
        req_id = payload["req_id"]
        session_id = payload["session_id"]
        new_cycle = payload["cycle"]                      # 递增后的 cycle
        old_cycle = new_cycle - 1                         # 打回发生的 cycle
        rejection = payload["gate_rejection"]

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # 1. UPDATE dialogue_sessions SET status='reopened'
                await conn.execute(
                    "UPDATE dialogue_sessions SET status='reopened', last_updated=NOW() "
                    "WHERE id=$1 AND req_id=$2",
                    session_id, req_id,
                )
                # 2. 注入系统消息（使用旧 cycle = 打回发生时的 cycle）
                seq = await conn.fetchval(
                    "SELECT COALESCE(MAX(sequence_number),0)+1 FROM dialogue_messages "
                    "WHERE session_id=$1 AND cycle=$2", session_id, old_cycle,
                )
                await conn.execute(
                    "INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number) "
                    "VALUES ($1, 'system', $2::jsonb, $3, $4)",
                    session_id,
                    json.dumps({
                        "type": "gate_rejection",
                        "reject_reasons": rejection["reject_reasons"],
                        "revision_guidance": rejection["revision_guidance"],
                        "cycle": old_cycle,
                    }),
                    old_cycle,
                    seq,
                )
                # 3. 写入 event_log（审计，NA）
                await conn.execute(
                    "INSERT INTO event_log (req_id, session_id, cycle, event_name, direction, payload) "
                    "VALUES ($1, $2, $3, 'context.ready.A1', 'IN', $4::jsonb)",
                    req_id, session_id, new_cycle, json.dumps(payload),
                )

        # 4. 通知前端（事务提交后，best-effort）
        try:
            await ws_gateway.notify_session(session_id, {
                "type": "session_reopened",
                "req_id": req_id,
                "session_id": session_id,
                "cycle": new_cycle,
                "gate_rejection": rejection,
            })
        except Exception:
            logger.warning("WebSocket notify failed for session=%s, user will see on next history load", session_id)

        await msg.ack()

    await js.subscribe("context.ready.A1", cb=handle, stream="AI_NATIVE_EVENTS")
```

> **WebSocket 通知是 best-effort**: 若通知失败，用户下次加载对话历史页面时，系统消息已持久化到 `dialogue_messages`，仍然可见。前端在进入对话页时调用 `GET /api/dialogue/current/{req_id}` 检查 session status，若为 `reopened` 自动高亮打回消息。

### 5.4 前端打回通知

**双通道保障**:

1. **实时通知**（WebSocket, best-effort）: MC Backend 通过 WebSocket 向在线用户推送 `session_reopened` 事件。前端收到后根据当前页面：
   - 在对话页且 session_id 匹配 → 自动刷新对话历史，显示红色打回消息
   - 在其他页面 → 显示 Notification banner

2. **主动检查**（HTTP, 可靠）: 前端进入对话页时调用 `GET /api/dialogue/current/{req_id}`，若 `status='reopened'` → 加载 `GET /api/dialogue/history/{session_id}` 渲染红色打回消息。

**多实例部署支持**: WebSocket 通知使用 **Redis Pub/Sub** 做跨实例广播（复用 MC Backend 现有 Redis 连接，`main.py` 中 `REDIS_URL` 配置）。`ws_gateway.notify_session()` 发布到 Redis channel `session_notifications:{session_id}`，各 MC Backend 实例订阅该 channel，检查 `session_id` 是否有本地 WebSocket 连接，有则推送。

```
实例A (NATS 收到) → Redis PUBLISH session_notifications:{id}
    ├→ 实例A 本地订阅 → ws 存在 → 推送
    └→ 实例B 本地订阅 → ws 存在 → 推送
```

---

## 六、前端集成

### 6.1 页面流程

```
需求列表页 → "创建需求" → POST /api/requirements → 获取 req_id
    ↓
进入对话页 → POST /api/dialogue/chat {req_id, message}
    ↓
SSE 接收流式分析 → 实时渲染草案更新、澄清问题、知识源引用
    ↓
多轮对话（同一 API，携带 session_id）
    ↓
"确认完成" → POST /api/dialogue/confirm → 状态变为 analyzing_completed
    ↓
等待 Gate0 审批...
    ↓ (若打回)
WebSocket/HTTP 通知 → 对话页显示红色打回消息 → 用户修订 → confirm → 等待重审
```

### 6.2 SSE 事件 → UI 映射

| SSE event | 前端行为 |
|-----------|---------|
| `thinking` | 显示分析进度指示器（带文字） |
| `knowledge` | 在对话区顶部显示"参考 N 条相似需求"等知识源 badge |
| `draft_update` | **增量更新**右侧草案面板：新增/修改的 entities、use_cases、acceptance_criteria 等字段实时高亮 |
| `clarification` | 在对话区渲染澄清问题卡片，每个问题右侧带建议和输入框 |
| `wireframe` | 在草案面板底部渲染线框图预览 iframe |
| `error` | 显示错误 toast + "重试"按钮 |
| `done` | 草案面板标记为"最终版"，启用"确认提交"按钮；存储 session_id |

### 6.3 历史对话页

`GET /api/dialogue/history/{session_id}` → 按 cycle 分组渲染：

- **cycle 分组标签**: "初次分析 (cycle 0)" / "修订轮次 1 (cycle 1)" ...
- **打回消息**: 红色背景卡片，显示拒绝原因 + 修订指引
- **草案对比**: 相邻 cycle 的 `draft_snapshot` 做 diff 展示
- **确认时间**: 每个 cycle 底部显示 `confirmed_at`

### 6.4 前端 API 客户端

```typescript
// frontend/src/lib/api.ts 新增

export async function createRequirement(title: string): Promise<{req_id: string; status: string}> {
  return fetch('/api/requirements', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({title}),
  }).then(r => r.json());
}

export async function sendDialogueMessage(
  reqId: string, message: string, sessionId: string | null
): Promise<ReadableStream> {
  const resp = await fetch('/api/dialogue/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({req_id: reqId, message, session_id: sessionId}),
  });
  if (!resp.ok) throw new Error(`Dialogue error: ${resp.status}`);
  return resp.body!;
}

export async function confirmDialogue(
  sessionId: string, finalNotes?: string
): Promise<{ok: boolean; status: string; already_confirmed?: boolean}> {
  return fetch('/api/dialogue/confirm', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sessionId, final_notes: finalNotes}),
  }).then(r => r.json());
}

export async function getDialogueHistory(sessionId: string): Promise<DialogueHistory> {
  return fetch(`/api/dialogue/history/${sessionId}`).then(r => r.json());
}

export async function getDialogueCurrent(reqId: string): Promise<DialogueCurrent> {
  return fetch(`/api/dialogue/current/${reqId}`).then(r => r.json());
}
```

### 6.5 前端改动清单

| 文件 | 改动内容 |
|------|---------|
| `frontend/src/app/requirements/[id]/page.tsx` | SSE 对接、cycle 分组展示、WebSocket 打回通知监听、页面加载时调用 `getDialogueCurrent()` |
| `frontend/src/lib/api.ts` | 新增 5 个对话 API 方法 |
| `frontend/src/components/DraftPanel.tsx` | 新增：结构化草案实时渲染组件 |
| `frontend/src/components/ClarificationCard.tsx` | 新增：澄清问题卡片组件 |
| `frontend/src/components/CycleTimeline.tsx` | 新增：cycle 分组时间线组件 |
| `frontend/src/lib/ws.ts` | 扩展：监听 `session_reopened` WebSocket 事件 |
| `frontend/src/stores/dialogueStore.ts` | 新增：对话状态管理（session_id, cycle, draft） |

---

## 七、Orchestrator 对接

### 7.1 阶段一状态机调整

当前（需调整）:
```
ANALYZING (A1) → Gate 0 → DESIGNING (A3+A4)
```

调整为（对齐数据字典 §7.1）:
```
DRAFT → ANALYZING (A1)
    → KNOWLEDGE_ANALYSIS (A2)
    → Gate 0
        ├── pass → DESIGNING (A3+A4)
        └── reject → ANALYZING (A1 修订，cycle++)
```

### 7.2 Orchestrator 侧具体改动

#### 7.2.1 状态枚举

```python
# state_machine/states.py
class RequirementState(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"                    # A1 需求分析
    KNOWLEDGE_ANALYSIS = "knowledge_analysis"  # A2 知识分析（新增）
    DESIGNING = "designing"
    # ... 后续状态不变
```

#### 7.2.2 流转表

```python
# state_machine/transitions.py
TRANSITION_TABLE = {
    RS.DRAFT:               [RS.ANALYZING, RS.BLOCKED],
    RS.ANALYZING:           [RS.KNOWLEDGE_ANALYSIS, RS.BLOCKED],
    RS.KNOWLEDGE_ANALYSIS:  [RS.DESIGNING, RS.ANALYZING, RS.BLOCKED],
    # Gate 0 在 KNOWLEDGE_ANALYSIS → DESIGNING（pass）/ ANALYZING（reject） 之间
    # ...
}
```

**Gate 处理模式**: Gate 在两个状态之间，不表示为独立状态。`_GATED_STATES` 中：
```python
_GATED_STATES = {
    RS.KNOWLEDGE_ANALYSIS: 0,   # Gate 0 在 A2 完成后
    RS.DESIGNING:          1,   # Gate 1
    # ...
}
```

原来的 `RS.ANALYZING: 0` 移除。A1 完成 → A2 → **Gate 0** → 分流。

#### 7.2.3 Workflow 改动点

**A1 调度模型说明**: A1 不是 NATS-dispatched Worker。用户通过 HTTP+SSE 直接与 MC Backend（内嵌 A1）交互，确认后 MC Backend 通过 Outbox 发布 `agent.result.A1`。Orchestrator **不 dispatch A1**，僅在 ANALYZING 状态下等待 `agent.result.A1` 经由 NATS-Temporal Bridge 转换的 `agent_completed` Signal。

```
首次分析:
  User → HTTP/SSE → MC Backend (A1) → confirm
    → event_log(outbox) → NATS agent.result.A1
    → NATS-Temporal Bridge → Temporal Signal agent_completed("A1", result)
    → Workflow: ANALYZING → KNOWLEDGE_ANALYSIS

Gate0 打回修订:
  Gate0 reject → Orchestrator 发布 context.ready.A1 (NATS)
    → MC Backend 订阅 → session REOPENED + 系统消息注入
    → User 在浏览器中重新打开会话 → HTTP/SSE 继续对话 → confirm
    → event_log(outbox) → NATS agent.result.A1 (cycle 递增)
    → NATS-Temporal Bridge → agent_completed Signal
    → Workflow: ANALYZING → KNOWLEDGE_ANALYSIS (完整重走 A2→Gate0)
```

**ANALYZING 状态特殊处理**:

```python
# 在 _run_agent_stage 中，A1 不 dispatch，直接等待 Signal
async def _run_agent_stage(self, req_id, initial_msg):
    if self._state == RS.ANALYZING:
        # A1 通过 HTTP+SSE 运行，不走 NATS dispatch。
        # Workflow 仅等待 NATS-Temporal Bridge 传来的 agent_completed Signal。
        workflow.logger.info("Waiting for A1 (HTTP/SSE) to complete req=%s", req_id)
        deadline = workflow.now() + _AGENT_TIMEOUTS.get(RS.ANALYZING, timedelta(minutes=30))
        await workflow.wait_condition(
            lambda: self._agent_result is not None or workflow.now() >= deadline
        )
        if self._agent_result is None:
            workflow.logger.error("A1 timeout req=%s", req_id)
            # A1 超时不自动推进，人工介入
            await self._transition(req_id, RS.BLOCKED, {"reason": "A1_timeout"})
        return

    # A2-A12: 正常 NATS dispatch
    # ... 原有逻辑 ...
```

**Agent 执行状态集合调整**（ANALYZING 从 `_AGENT_STATES` 中移除，因为它不 dispatch）:

```python
_AGENT_STATES: set[RS] = {
    RS.KNOWLEDGE_ANALYSIS,  # A2
    RS.DESIGNING,           # A3+A4
    RS.REVIEWING,           # A5
    RS.DECOMPOSING,         # A6
    RS.DEVELOPING,          # A9
    RS.TESTING,             # A11
    RS.REVIEWING_CODE,      # A12
    RS.RELEASING,           # A13
}
# ANALYZING 不在 _AGENT_STATES 中——Workflow 在 ANALYZING 时走特殊路径
```

1. **A1 完成后进 A2**: NATS-Temporal Bridge 收到 `agent.result.A1` → `agent_completed("A1", result)` Signal → Workflow 被唤醒 → `_transition(KNOWLEDGE_ANALYSIS)` → dispatch A2 → 等待 `agent.result.A2`
2. **A2 完成后进 Gate 0**: `_run_gate_stage(gate_level=0)` → pass → `DESIGNING` / reject → `ANALYZING`
3. **A2 超时**: 10min 超时 → 重试 1 次 → 仍失败 `agent_results(A2, status='skipped')` → 仍进 Gate 0（`a2_missing=true`）
4. **Gate0 打回**: `reject_gate` Signal 触发 → `event_log(IN)` → `notify_mc` 更新 `requirements` → 发布 `context.ready.A1`（NATS）→ MC Backend 收到后 session REOPENED → 用户修订
5. **修订后重新确认**: 用户 confirm → Outbox → NATS `agent.result.A1`（cycle 递增）→ Bridge → `agent_completed` Signal → Workflow 再次从 `ANALYZING` 进入 `KNOWLEDGE_ANALYSIS`
6. **NATS-Temporal Bridge** (`nats_temporal_bridge.py`): NATS `agent.result.A1`/`agent.result.A2` → Temporal `agent_completed` Signal。`agent.result.gate0.*` → `approve_gate`/`reject_gate` Signal。`req_id → workflow_id` 映射通过查询 Temporal workflow search attributes（在创建 Workflow 时将 req_id 设为 search attribute）。

**首次流程启动时机**: MC Backend 在 `POST /api/requirements` 时调用 Temporal Client 创建 RequirementWorkflow（`req_id`，`status=DRAFT`），Workflow 自动进入 `ANALYZING` 状态等待 `agent.result.A1` Signal。

#### 7.2.4 reject_gate Signal 扩展

```python
@workflow.signal
async def reject_gate(self, gate_name: str, reason: str = "",
                      reject_reasons: list | None = None,
                      revision_guidance: str = ""):
    self._gate_approved = gate_name  # unblock wait_condition
    self._gate_decision = "reject"
    self._gate_reject_reasons = reject_reasons or []
    self._gate_revision_guidance = revision_guidance
```

---

## 八、异常处理

### 8.1 超时处理

| 场景 | 超时 | 处理 |
|------|------|------|
| 会话无活动 | 24h | `dialogue_sessions.last_updated` 超过 24h 未更新 → 定时任务（每 15min）设 `status='abandoned'`。实现: Temporal Schedule 或 cron job 调用 MC Backend API |
| A1 LLM 单次分析 | 5min | SSE 流中 yield `error` 事件，前端允许用户重试 |
| MCP 知识库调用 | 5s/个 | 并行调用，单个超时降级（asyncio.wait_for + return_exceptions） |
| A2 知识分析 | 10min | Orchestrator 重试 1 次，仍失败跳过（status='skipped'） |
| Gate0 审批 | 1h | Orchestrator 通知，不自动通过 |
| NATS Outbox 发布 | 30s/次 | 5 次指数退避重试，全部失败标记 'failed' + Prometheus `a1_outbox_failed_total` alert |

### 8.2 错误恢复

| 场景 | 恢复策略 |
|------|---------|
| SSE 流中断 | finally 块持久化已完成的 AI 回复 + snapshot |
| confirm 事务失败 | 返回 500，前端保持未确认状态，用户重新点击（幂等） |
| UNIQUE 冲突（重复确认） | 捕获 PG 23505 → 返回 `{"ok": true, "already_confirmed": true}` |
| Outbox NATS 发布无限失败 | Prometheus alert → 人工 `UPDATE event_log SET outbox_status='pending'` |
| 并发 chat 请求 | `SELECT ... FOR UPDATE` 串行化，第二个请求等待锁释放 |
| session REOPENED 后用户不在线 | 系统消息持久化到 DB → 下次加载 history 可见 |

### 8.3 并发控制

同一 session 的并发 chat 请求：
- 步骤 3 已通过 `SELECT ... FOR UPDATE` 锁定 session 行
- 第二个并发请求阻塞等待锁释放
- 锁释放后看到更新过的数据，正常执行
- 无需 409 Conflict（串行化优于拒绝）

---

## 九、实施计划

### Phase 1: 数据库 + 核心 API（4 天）

| 任务 | 产出 | 说明 |
|------|------|------|
| Migration 008 | `repos/infra/alembic/versions/008_phase_one_schema.py` | 7 张新表全量创建，含索引和约束 |
| 旧表处理 | migration 后 cleanup 脚本 | 重命名旧 `requirements` → `requirements_legacy`，旧 `chat_messages` → `chat_messages_legacy` |
| Outbox Publisher | `repos/mc-backend/services/outbox_publisher.py` | 每 2s 轮询 `event_log`，发布 NATS + 5 次重试逻辑 |
| `/api/requirements` | `repos/mc-backend/api/requirements.py` | 改造成新表，初始化 `requirement_draft` |
| `/api/dialogue/chat` | `repos/mc-backend/api/dialogue.py` | SSE + session 管理 + FOR UPDATE + A1 集成 |
| `/api/dialogue/confirm` + history + current | 同上 | 事务 + outbox + 幂等 + wireframe S3 上传 |
| `context.ready.A1` 订阅 | `repos/mc-backend/services/nats_subscriber.py` | 后台 task + Redis Pub/Sub WebSocket 通知 |

### Phase 2: A1 Agent + 前端（3 天）

| 任务 | 产出 |
|------|------|
| A1 Agent 主类 | `agent-workers/a1/agent.py` — yield 结构化 dict |
| Draft Builder | `agent-workers/a1/analyzer/draft_builder.py` — LLM 流式 + 4 个 MCP 工具 |
| MCP Client | `agent-workers/a1/analyzer/mcp_client.py` — 4 工具封装 |
| 线框图 + BDD 升级 | `wireframe/generator.py` + `bdd/drafter.py` LLM 化 |
| 前端对话页 | DraftPanel、ClarificationCard、CycleTimeline 组件 |
| 前端 SSE + Zustand | SSE dict → UI 映射 + dialogueStore |

### Phase 3: Orchestrator + Gate0 全链路（2 天）

| 任务 | 产出 |
|------|------|
| Orchestrator 插入 A2 | `states.py` 新增 `KNOWLEDGE_ANALYSIS`，`transitions.py` 调整，workflow 插入 A2 阶段 |
| Gate0 打回链路 | `reject_gate` Signal 扩展 + `context.ready.A1` NATS 发布 |
| MC Backend NATS 订阅 | `subscribe_context_ready_a1()` 完整实现 + Redis Pub/Sub |
| Outbox 接入 Orchestrator | Orchestrator 的 NATS 发布也走 event_log outbox |
| 端到端测试 | 全链路：创建 → 对话 → 确认 → A2 → Gate0 → 打回 → 修订 → 重新确认 |

---

## 十、关键设计决策

### 10.1 A1 是"在线服务"，NATS 仅用于编排

- HTTP+SSE 对话 → MC Backend 直接 import A1 Agent 模块（低延迟流式）
- NATS 仅用于：Outbox 发布的 `agent.result.A1` + 打回通知的 `context.ready.A1`
- 废弃现有 `a1_requirement_intake.py`（异步 Worker）和 `a1_upgrade.py`（飞书 Bot）

### 10.2 全新建设，旧表重命名保留

新 `requirements`、`agent_results`、`dialogue_sessions`、`dialogue_messages`、`understanding_snapshots`、`event_log`、`approvals` 全部按数据字典规格新建。旧表重命名为 `*_legacy` 保留，过渡期后手动删除。

### 10.3 Outbox 保证 NATS 投递可靠性

`event_log` 表双重职责：事件审计 + Outbox。`direction='OUT'` 且 `outbox_status='pending'` 的记录由 Publisher 进程发布。DB 事务与 NATS 发布之间的一致性由 Outbox 模式保证。`direction='IN'` 的记录 `outbox_status=NULL`，仅审计。

### 10.4 A1 Agent 无副作用 + SSE 格式化在路由层

Agent 的 `analyze()` yield 结构化 dict，不读写 DB、不发布消息、不构建 SSE 格式字符串。路由层负责格式化 SSE 和管理所有持久化。Agent 可独立测试、可在非 SSE 场景复用。

### 10.5 分析流程顺序：知识在前，LLM 在后

对齐设计规格 §3.3：**先 MCP 知识库并行检索 → 再 LLM 流式分析**。4 个 MCP 工具齐全（`search_similar_requirements`、`get_domain_risks`、`get_tech_stack_recommendations`、`get_cost_baseline`）。

### 10.6 `dialogue_messages` 使用 JSONB content + UNIQUE 防竞态

`UNIQUE(session_id, cycle, sequence_number)` + `SELECT ... FOR UPDATE` 保证并发 chat 请求不会产生重复 sequence_number。

### 10.7 WebSocket 通知双通道保障（实时推送 + 主动检查）

打回通知有两条路径：
1. WebSocket 实时推送（通过 Redis Pub/Sub 跨实例，best-effort）
2. 前端进入对话页时主动调用 `GET /api/dialogue/current/{req_id}` 检查 `status='reopened'`（可靠）

第二条路径确保即使 WebSocket 推送失败，用户下次进入页面仍可见打回信息。

---

## 十一、测试要点

| 测试场景 | 验证点 |
|---------|--------|
| 创建需求 | req_id + status='draft' + title + creator 从 JWT 提取 |
| 首次对话 | session 创建，`SELECT ... FOR UPDATE` 持锁，SSE 返回完整事件序列 |
| SSE done 含 session_id | 前端从 done 事件获取 session_id 并在确认按钮逻辑中使用 |
| 多轮对话 | sequence_number 递增无重复，历史加载完整 |
| 并发 chat 请求 | 第二个请求等待锁释放后正常执行，sequence_number 不冲突 |
| MCP 全部超时 | 4 个调用并行超时，knowledge source 为空，confidence 降低，不阻塞 |
| LLM 异常 | yield error 事件，非中断流 |
| 用户确认 | 事务持久化 6 个操作，outbox 记录 direction='OUT' |
| 重复确认 | UNIQUE 约束捕获，返回 `already_confirmed: true` |
| Outbox 发布 | pending → published；5 次失败后 failed + alert |
| `event_log` IN 记录 | `outbox_status=NULL`，Outbox Publisher 不过滤到 |
| WebSocket 实时打回通知 | 在线用户收到 `session_reopened` |
| HTTP 主动检查打回 | `GET /api/dialogue/current/{req_id}` 返回 `status='reopened'` |
| 离线打回通知 | 下次加载 history 看到红色 system 消息 |
| Cycle 递增确认 | `agent_results` 中 cycle=0 和 cycle=1 各有 A1 记录 |
| SSE 流中断 | finally 块持久化 AI 回复 + snapshot |
| 会话 24h 无活动 | 定时任务标记 `abandoned` |
| wireframe S3 上传 | 确认时调用 `s3_proxy.upload_json()`，URL 写入 artifact |
| S3 不可用 | `wireframe_url` 为 null，确认不阻塞 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-10
**版本**: v2.1（critical 审计修复版）
**审计记录**: 修复 C1-C5（5 个严重）、M1-M7（7 个中等）、L1-L12（12 个遗漏）
**参考规格**: A1 设计 v3.5 · 数据字典 v1.3 · 状态机 v2.4
