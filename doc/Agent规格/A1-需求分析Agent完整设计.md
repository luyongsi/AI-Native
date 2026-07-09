# A1 需求分析 Agent - 完整设计文档

## 文档信息
- **版本**: v3.1
- **日期**: 2026-07-09
- **状态**: 完整设计文档（已整合Critical审计修复建议）
- **说明**: 整合业务流程、数据流、长期演进规划的统一文档

---

## 一、整体业务流程

### 1.1 核心流程概览

```
阶段1: 需求分析（纯A1内部）
用户发起需求 → A1独立对话 → MCP/知识库增强 → 多轮澄清 → 用户确认 → 需求入库 → 发布完成事件

阶段2: 需求设计与实施（Orchestrator接管）
Orchestrator订阅事件 → 启动workflow → 设计 → Gate1 → 实施 → Gate2 → 部署 → 完成

阶段3: Gate打回（返回A1）
Gate拒绝 → 发布打回事件 → A1恢复会话 → 展示打回原因 → 用户继续对话 → 修改需求 → 重新提交 → 返回阶段2
```

### 1.2 关键设计原则

1. **A1完全独立**：A1是独立的对话服务，不依赖Orchestrator
2. **用户主导节奏**：用户决定何时结束对话，何时确认提交
3. **会话可恢复**：Gate打回后，用户可继续原会话，所有历史都保留
4. **数据完整性**：每次交互都完整记录，支持审计和回溯

---

## 二、阶段1：A1独立对话流程

### 2.1 用户发起需求并开始对话

#### 业务流程
```
用户 → Frontend对话框 → HTTP POST /api/dialogue/chat → MC Backend → A1分析 → Stream响应 → 前端展示
```

**关键点**：
- 直接HTTP请求，不使用NATS
- 使用Fetch Readable Stream实时展示A1的分析结果
- 类似ChatGPT的对话体验

#### 数据流

**1. 用户首次提交需求**
- 输入：需求描述文本
- API: `POST /api/dialogue/chat`
- 请求体：
```json
{
  "message": "我想做一个用户管理系统",
  "session_id": null  // 首次为null，后续对话传入session_id
}
```

**2. MC Backend处理（首次）**
- 创建需求记录（status='draft'）
- 写入 `requirements` 表：
  - id (UUID)
  - status = 'draft'
  - created_at
  - creator_user_id
  - creator_name

- 创建对话会话
- 写入 `dialogue_sessions` 表：
  - id (UUID)
  - req_id
  - status = 'active'
  - iterations = 0
  - total_messages = 0
  - creator_user_id
  - creator_name
  - created_at

- 记录首条用户消息
- 写入 `dialogue_messages` 表：
  - session_id
  - role = 'human'
  - content = {text: "用户需求描述", type: "initial"}
  - sequence_number = 1
  - timestamp

**3. 调用A1分析并流式返回**
- MC Backend直接调用A1分析函数
- A1执行分析逻辑（LLM + MCP）
- 使用HTTP Streaming返回结果

**4. HTTP Stream响应**
- Response: `Content-Type: text/event-stream`
- Stream格式（SSE - Server-Sent Events）：
```
data: {"type": "analysis_start", "message": "正在分析需求..."}\n\n
data: {"type": "mcp_call", "tool": "search_similar_requirements", "status": "calling"}\n\n
data: {"type": "understanding", "draft": {...}, "partial": true}\n\n
data: {"type": "clarification", "points": [...]}\n\n
data: {"type": "done", "session_id": "uuid", "req_id": "uuid"}\n\n
```

**5. 前端接收Stream**
```javascript
const response = await fetch('/api/dialogue/chat', {
  method: 'POST',
  body: JSON.stringify({message: "...", session_id: null}),
  headers: {'Content-Type': 'application/json'}
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const {done, value} = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  // 解析SSE格式，实时更新UI
  // 显示理解草案、澄清问题等
}
```

### 2.2 A1分析处理逻辑

#### 业务流程
```
加载对话历史 → LLM分析(Stream) → 调用MCP/知识库 → 生成理解草案 → 识别待澄清点 → 保存数据 → 完成Stream
```

#### 数据流

**1. 加载对话历史**
- 查询 `dialogue_messages` 表：
  - WHERE session_id = ?
  - ORDER BY sequence_number ASC

**2. LLM Stream分析**
- 输入：对话历史 + 系统prompt
- 调用LLM API（支持MCP工具调用，支持Stream）
- 边生成边返回给前端
- 输出：需求理解草案 (JSON)

**3. 调用MCP/知识库（A1内部自动）**
- A1根据需求内容，自动调用：
  - `search_similar_requirements` - 查找相似历史需求
  - `get_domain_risks` - 获取领域风险
  - `get_tech_stack_recommendations` - 技术栈建议
  - `get_cost_baseline` - 成本估算
- 每个调用通过Stream通知前端进度

**4. 生成理解草案**
- 结构：
```json
{
  "domain": "业务领域",
  "summary": "需求概要",
  "entities": [
    {"name": "实体名", "attributes": [...], "description": "..."}
  ],
  "acceptance_criteria": [
    "验收标准1",
    "验收标准2"
  ],
  "constraints": ["约束条件"],
  "risks": ["潜在风险"],
  "estimated_cost": "成本估算"
}
```

**5. 识别待澄清点**
- 分析草案，识别不明确的部分
- 生成澄清问题列表：
```json
[
  {
    "id": "point_1",
    "category": "entity",
    "question": "请明确用户实体的权限属性",
    "priority": "high"
  }
]
```

**6. 保存理解快照**
- 写入 `understanding_snapshots` 表：
  - session_id
  - iteration = iterations + 1
  - draft (JSONB) = 理解草案
  - clarification_points (JSONB) = 待澄清点列表
  - confidence_score = 置信度 (0-1)
  - knowledge_sources = MCP返回的相似需求ID
  - mcp_tools_used = 使用的MCP工具列表
  - created_at

**7. 更新会话状态**
- 更新 `dialogue_sessions` 表：
  - iterations = iterations + 1
  - current_understanding = 最新草案
  - clarification_points = 最新待澄清点
  - confidence_score = 最新置信度
  - last_updated = NOW()

**8. 记录A1消息**
- 写入 `dialogue_messages` 表：
  - session_id
  - role = 'ai'
  - content = {text: "理解反馈+澄清问题", type: "understanding"}
  - understanding_snapshot_id = 快照ID
  - sequence_number = 下一个序号
  - timestamp

**9. Stream结束**
- 发送最终的done事件
- 包含session_id供后续对话使用

### 2.3 用户补充信息（多轮对话）

#### 业务流程
```
用户在对话框输入 → HTTP POST /api/dialogue/chat → MC Backend → A1分析 → Stream响应 → 前端展示
```

**关键点**：
- 与首次对话使用相同的API
- 通过session_id关联到之前的会话
- 继续使用Stream实时展示

#### 数据流

**1. 用户提交补充**
- API: `POST /api/dialogue/chat`
- 请求体：
```json
{
  "message": "用户实体需要支持多角色权限管理",
  "session_id": "uuid",  // 之前返回的session_id
  "addresses_points": ["point_1"]  // 可选：标注解决了哪些澄清点
}
```

**2. MC Backend处理**
- 验证session_id和会话状态
- 记录用户消息
- 写入 `dialogue_messages` 表：
  - session_id
  - role = 'human'
  - content = {text: "补充内容", type: "supplement", addresses_points: [...]}
  - sequence_number = 下一个序号
  - timestamp

**3. 更新会话统计**
- 更新 `dialogue_sessions` 表：
  - total_messages = total_messages + 1
  - last_updated = NOW()

**4. 触发新一轮分析**
- 调用A1分析函数
- 重复2.2的流程（加载历史 → LLM分析 → Stream返回）
- Stream包含新的理解草案和澄清问题

**5. 前端持续展示**
- 对话框中显示完整对话历史
- 实时展示A1的新一轮分析结果
- 用户可以继续补充或确认

### 2.4 用户确认完成

#### 业务流程
```
用户点击确认 → HTTP POST /api/dialogue/confirm → MC Backend → 保存最终需求 → 发布NATS完成事件 → Orchestrator
```

**关键点**：
- 用户在对话界面点击"确认提交"按钮
- 保存最终需求到requirements表
- 此时才发布NATS事件通知Orchestrator

#### 数据流

**1. 用户确认**
- API: `POST /api/dialogue/confirm`
- 请求体：
```json
{
  "session_id": "uuid",
  "confirmed": true,
  "final_notes": "用户的最终补充说明（可选）"
}
```

**2. MC Backend验证**
- 验证session_id
- 检查会话状态（必须是active）
- 获取最新理解快照

**3. 保存最终需求**
- 更新 `requirements` 表：
  - status = 'analyzing_completed'
  - requirement_draft (JSONB) = 最新理解草案
  - confidence_score = 最终置信度
  - analyzed_at = NOW()
  - analyzer_agent = 'A1'

**4. 记录确认消息**
- 写入 `dialogue_messages` 表：
  - role = 'human'
  - content = {text: "用户确认", type: "confirm", final_notes: "..."}
  - sequence_number = 下一个序号

**5. 更新会话状态**
- 更新 `dialogue_sessions` 表：
  - status = 'completed'
  - first_confirmed_at = NOW()（如果是首次）
  - last_confirmed_at = NOW()
  - human_confirmations = 追加确认记录

**6. 发布NATS完成事件**（通知Orchestrator）
- 主题: `requirement.draft.finalized`
- Payload:
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "draft": {...},
  "confidence_score": 0.85,
  "iterations": 5,
  "total_messages": 12
}
```

**7. 返回成功响应**
- 返回给前端：
```json
{
  "success": true,
  "req_id": "uuid",
  "message": "需求已提交，等待设计..."
}
```

---

## 三、阶段2：Orchestrator接管

### 3.1 Orchestrator启动

#### 业务流程
```
订阅完成事件 → 读取需求草案 → 启动RequirementWorkflow
```

#### 数据流

**1. 订阅事件**
- Orchestrator订阅 `requirement.draft.finalized`
- 接收Payload

**2. 读取需求**
- 查询 `requirements` 表：
  - WHERE id = req_id
  - 获取 requirement_draft

**3. 启动Workflow**
- 初始状态：**DESIGNING**（跳过ANALYZING）
- 更新 `requirements` 表：
  - status = 'designing'
  - workflow_id = Temporal workflow ID
  - designing_started_at = NOW()

**4. 后续流程**
- DESIGNING → Gate1审批 → IMPLEMENTING → Gate2审批 → DEPLOYING → COMPLETED
- 每个状态变更都更新 `requirements.status`

---

## 四、阶段3：Gate打回流程

### 4.1 Gate拒绝并通知用户

#### 业务流程
```
审批人拒绝 → MC Backend API → 更新数据库 → 发布NATS事件（通知用户） → 前端展示打回原因
```

**关键点**：
- Gate打回时，使用NATS通知前端（异步通知）
- 用户看到打回原因后，可以重新进入对话
- 对话交互仍然使用HTTP + Stream

#### 数据流

**1. 审批人拒绝**
- API: `POST /api/approvals/{approval_id}/reject`
- 请求体：
```json
{
  "gate_level": 1,
  "reject_reasons": ["需求描述不够清晰", "缺少验收标准"],
  "reviewer_feedback": "建议补充用户角色的详细说明"
}
```

**2. MC Backend处理**
- 更新 `approvals` 表（记录拒绝）
- 更新 `requirements` 表：
  - status = 'gate_rejected'
  - gate_rejection_count = gate_rejection_count + 1
  - last_gate_rejection = {gate_level, reasons, feedback, rejected_at}

**3. 查找对应的对话会话**
- 查询 `dialogue_sessions` 表：
  - WHERE req_id = ?
  - 获取session_id

**4. 重新激活会话**
- 更新 `dialogue_sessions` 表：
  - status = 'reopened'
  - reopen_count = reopen_count + 1
  - last_reopen_reason = {gate_level, reject_reasons, reviewer_feedback}
  - last_updated = NOW()

**5. 注入打回原因消息**
- 写入 `dialogue_messages` 表：
  - role = 'system'
  - content = {
      text: "Gate1审批未通过",
      type: "gate_rejection",
      gate_info: {gate_level, reject_reasons, reviewer_feedback}
    }
  - reopen_round = reopen_count
  - sequence_number = 下一个序号

**6. 发布NATS通知事件**（可选，用于实时通知）
- 主题: `requirement.gate.rejected.notify`
- Payload:
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "gate_level": 1,
  "reject_reasons": [...]
}
```
- 前端如果在线，可以实时收到通知

**7. 前端展示**
- 用户打开需求详情页，看到"已被Gate1打回"
- 显示打回原因和审批人反馈
- 提供"继续对话"按钮

### 4.2 用户重新进入对话

#### 业务流程
```
用户点击"继续对话" → 前端加载历史 → 显示打回原因 → 用户输入补充 → HTTP POST /api/dialogue/chat → Stream响应
```

**关键点**：
- 使用相同的session_id
- 前端自动展示完整历史 + 打回原因
- 对话交互与首次完全相同

#### 数据流

**1. 前端加载对话历史**
- API: `GET /api/dialogue/history/{session_id}`
- 返回：
```json
{
  "session_id": "uuid",
  "req_id": "uuid",
  "status": "reopened",
  "reopen_count": 1,
  "messages": [
    {
      "role": "human",
      "content": {...},
      "reopen_round": 0,
      "timestamp": "..."
    },
    {
      "role": "ai",
      "content": {...},
      "reopen_round": 0,
      "timestamp": "..."
    },
    {
      "role": "system",
      "content": {
        "type": "gate_rejection",
        "gate_info": {...}
      },
      "reopen_round": 1,
      "timestamp": "..."
    }
  ]
}
```

**2. 前端展示**
- 对话框按reopen_round分组显示：
  - 第0轮：首次对话（灰色背景）
  - 系统消息：Gate1打回原因（红色高亮）
  - 第1轮：当前对话（正常背景）

**3. 用户继续对话**
- 用户在对话框输入补充信息
- API: `POST /api/dialogue/chat`
- 请求体：
```json
{
  "message": "已补充用户角色详细说明...",
  "session_id": "uuid"
}
```

**4. 数据库记录**
- 写入 `dialogue_messages` 表：
  - role = 'human'
  - content = {text: "补充内容", type: "supplement"}
  - reopen_round = reopen_count（当前为1）
  - sequence_number = 下一个序号

**5. A1重新分析**
- 加载完整对话历史（包括打回原因）
- LLM分析并通过Stream返回
- 生成新的理解草案
- 保存新的understanding_snapshot

**6. 多轮对话继续**
- 用户可以继续补充多轮
- 所有消息的reopen_round都为当前reopen_count
- 直到用户再次点击"确认提交"

### 4.3 重新提交

#### 业务流程
```
用户确认修订 → HTTP POST /api/dialogue/confirm → 保存修订需求 → 发布NATS修订事件 → Orchestrator恢复
```

**关键点**：
- 与首次确认使用相同的API
- 发布不同的NATS事件（draft.revised而非draft.finalized）

#### 数据流

**1. 用户确认（同2.4）**
- API: `POST /api/dialogue/confirm`
- 请求体相同

**2. 保存修订需求**
- 更新 `requirements` 表：
  - requirement_draft = 最新修订草案
  - status = 'analyzing_completed'
  - revision_count = revision_count + 1
  - last_revised_at = NOW()

**3. 更新会话状态**
- 更新 `dialogue_sessions` 表：
  - status = 'completed'（保持）
  - last_confirmed_at = NOW()
  - 追加确认记录到 human_confirmations

**4. 发布修订完成事件**（通知Orchestrator）
- 主题: `requirement.draft.revised`
- Payload:
```json
{
  "req_id": "uuid",
  "gate_level": 1,
  "draft": {...},
  "revision_count": 2,
  "confidence_score": 0.88
}
```

**5. Orchestrator恢复workflow**
- 订阅 `requirement.draft.revised`
- 发送Signal到运行中的workflow
- Workflow从Gate1重新开始审批
- 更新 `requirements.status` = 'designing'

---

## 五、数据库表设计

### 5.1 核心表关系

```
requirements (需求主表)
  ↓ 1:1
dialogue_sessions (对话会话)
  ↓ 1:N
dialogue_messages (对话消息)

dialogue_sessions (对话会话)
  ↓ 1:N
understanding_snapshots (理解快照)
```

### 5.2 requirements 表（需求主表）

#### 核心字段
```sql
CREATE TABLE requirements (
    id UUID PRIMARY KEY,
    
    -- 状态流转
    status VARCHAR(50) NOT NULL,
    -- 'draft' -> 'analyzing_completed' -> 'designing' -> 'gate_rejected' -> ...
    
    -- 需求内容
    requirement_draft JSONB,  -- A1生成的结构化需求
    confidence_score NUMERIC(3,2),
    
    -- 创建者
    creator_user_id VARCHAR(255),
    creator_name VARCHAR(255),
    
    -- 分析信息
    analyzer_agent VARCHAR(50),  -- 'A1'
    analyzed_at TIMESTAMPTZ,
    
    -- Gate打回信息
    gate_rejection_count INT DEFAULT 0,
    last_gate_rejection JSONB,
    
    -- 修订信息
    revision_count INT DEFAULT 0,
    last_revised_at TIMESTAMPTZ,
    
    -- Workflow信息
    workflow_id VARCHAR(255),
    
    -- 时间戳
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 5.3 dialogue_sessions 表（对话会话）

```sql
CREATE TABLE dialogue_sessions (
    id UUID PRIMARY KEY,
    req_id UUID REFERENCES requirements(id) ON DELETE CASCADE,
    
    -- 状态管理
    status VARCHAR(50) DEFAULT 'active',
    -- 'active' | 'completed' | 'reopened' | 'abandoned'
    
    -- 重开记录
    reopen_count INT DEFAULT 0,
    last_reopen_reason JSONB,
    
    -- 统计
    iterations INT DEFAULT 0,
    total_messages INT DEFAULT 0,
    
    -- 当前理解
    current_understanding JSONB,
    clarification_points JSONB,
    confidence_score NUMERIC(3,2),
    
    -- 确认记录
    human_confirmations JSONB DEFAULT '[]'::jsonb,
    
    -- 创建者
    creator_user_id VARCHAR(255),
    creator_name VARCHAR(255),
    
    -- 时间戳
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    first_confirmed_at TIMESTAMPTZ,
    last_confirmed_at TIMESTAMPTZ
);

CREATE INDEX idx_dialogue_sessions_req_id ON dialogue_sessions(req_id);
CREATE INDEX idx_dialogue_sessions_status ON dialogue_sessions(status);
```

### 5.4 dialogue_messages 表（对话消息）

```sql
CREATE TABLE dialogue_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES dialogue_sessions(id) ON DELETE CASCADE,
    
    role VARCHAR(20) CHECK (role IN ('human', 'ai', 'system')),
    
    content JSONB NOT NULL,
    -- {
    --   text: string,
    --   type: 'initial' | 'supplement' | 'understanding' | 'confirm' | 'gate_rejection',
    --   addresses_points?: string[],
    --   gate_info?: {...}
    -- }
    
    understanding_snapshot_id BIGINT,
    reopen_round INT DEFAULT 0,  -- 第几轮重开
    
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    sequence_number INT NOT NULL
);

CREATE INDEX idx_dialogue_messages_session ON dialogue_messages(session_id, sequence_number);
CREATE INDEX idx_dialogue_messages_reopen ON dialogue_messages(session_id, reopen_round);
```

### 5.5 understanding_snapshots 表（理解快照）

```sql
CREATE TABLE understanding_snapshots (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES dialogue_sessions(id) ON DELETE CASCADE,
    
    iteration INT NOT NULL,
    
    draft JSONB NOT NULL,  -- 需求理解草案
    clarification_points JSONB,
    confidence_score NUMERIC(3,2),
    
    -- MCP增强
    knowledge_sources JSONB,  -- 相似需求ID列表
    mcp_tools_used JSONB,     -- 使用的MCP工具记录
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_understanding_snapshots_session ON understanding_snapshots(session_id, iteration DESC);
```

---

## 六、NATS事件协议

### 6.1 事件列表

**说明**：用户与A1的对话交互使用HTTP + Stream，不使用NATS。NATS仅用于跨服务通知。

| 事件主题 | 方向 | 触发时机 | Payload关键字段 |
|---------|------|---------|----------------|
| requirement.draft.finalized | MC Backend → Orchestrator | A1对话完成，用户首次确认 | req_id, session_id, draft, confidence_score |
| requirement.draft.revised | MC Backend → Orchestrator | Gate打回后修订完成 | req_id, gate_level, draft, revision_count |
| requirement.gate.rejected.notify | MC Backend → 前端(可选) | Gate打回实时通知 | req_id, session_id, gate_level, reject_reasons |

### 6.2 事件详细定义

#### requirement.draft.finalized（首次完成）

**发布时机**：用户在A1对话中点击"确认提交"

**Payload**：
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "draft": {
    "domain": "...",
    "summary": "...",
    "entities": [...],
    "acceptance_criteria": [...],
    "constraints": [...],
    "risks": [...]
  },
  "confidence_score": 0.85,
  "iterations": 5,
  "total_messages": 12,
  "finalized_at": "2026-07-08T10:00:00Z"
}
```

**订阅者**：Orchestrator

**处理逻辑**：
- 读取需求草案
- 启动RequirementWorkflow
- 初始状态：DESIGNING

#### requirement.draft.revised（修订完成）

**发布时机**：Gate打回后，用户完成修订并再次确认

**Payload**：
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "gate_level": 1,
  "draft": {...},
  "revision_count": 2,
  "confidence_score": 0.88,
  "revised_at": "2026-07-08T12:00:00Z"
}
```

**订阅者**：Orchestrator

**处理逻辑**：
- 发送Signal到运行中的workflow
- Workflow从指定Gate重新开始

#### requirement.gate.rejected.notify（打回通知，可选）

**发布时机**：Gate审批拒绝时

**Payload**：
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "gate_level": 1,
  "reject_reasons": ["需求描述不够清晰", "缺少验收标准"],
  "reviewer_feedback": "建议补充用户角色的详细说明",
  "rejected_at": "2026-07-08T11:00:00Z"
}
```

**订阅者**：前端WebSocket Gateway（可选）

**处理逻辑**：
- 如果用户在线，实时推送通知
- 用户看到"需求被打回"提醒

### 6.3 事件数据流

#### 正常流程（无NATS用于对话）
```
用户发起 → HTTP POST /api/dialogue/chat → Stream响应
  ↓ (用户继续对话)
用户补充 → HTTP POST /api/dialogue/chat → Stream响应
  ↓ (多轮循环)
用户确认 → HTTP POST /api/dialogue/confirm
  ↓
MC Backend发布NATS: requirement.draft.finalized
  ↓
Orchestrator订阅并启动workflow
  ↓
(进入设计实施流程)
```

#### Gate打回流程
```
Gate审批拒绝
  ↓
MC Backend更新数据库
  ↓ (可选)
发布NATS: requirement.gate.rejected.notify
  ↓ (可选实时通知)
前端WebSocket推送
  ↓
用户看到打回通知，点击"继续对话"
  ↓
HTTP GET /api/dialogue/history/{session_id}
  ↓
前端展示完整历史 + 打回原因
  ↓
用户继续对话 → HTTP POST /api/dialogue/chat → Stream响应
  ↓ (多轮循环)
用户确认修订 → HTTP POST /api/dialogue/confirm
  ↓
MC Backend发布NATS: requirement.draft.revised
  ↓
Orchestrator订阅并恢复workflow
```

---

## 七、关键业务规则

### 7.1 会话状态流转

```
active (进行中)
  ↓ 用户首次确认
completed (首次完成)
  ↓ Gate打回
reopened (重新激活)
  ↓ 用户确认修订
completed (保持)
  ↓ Gate再次打回
reopened (再次激活)
  ↓ ...循环
```

### 7.2 需求状态流转

```
draft (草稿)
  ↓ A1首次确认
analyzing_completed (分析完成)
  ↓ Orchestrator接管
designing (设计中)
  ↓ Gate1打回
gate_rejected (Gate拒绝)
  ↓ A1修订确认
analyzing_completed (再次分析完成)
  ↓ Orchestrator恢复
designing (再次设计中)
  ↓ Gate1通过
implementing (实施中)
  ↓ ...
```

### 7.3 数据完整性规则

1. **对话历史完整保留**
   - 所有消息追加，不删除
   - 通过 reopen_round 区分不同轮次
   - 支持完整审计

2. **快照版本管理**
   - 每次迭代创建新快照
   - iteration 单调递增
   - 支持版本回溯

3. **确认记录追踪**
   - human_confirmations 记录每次确认
   - 包含时间戳和确认内容
   - 支持多次确认历史

4. **Gate打回追踪**
   - gate_rejection_count 记录打回次数
   - last_gate_rejection 记录最新打回信息
   - 支持打回原因分析

---

## 八、前端交互模式

### 8.1 对话界面（HTTP + Stream）

**交互方式**：类似ChatGPT的对话框体验

#### 发起对话

**API**: `POST /api/dialogue/chat`

**请求**：
```javascript
const response = await fetch('/api/dialogue/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer <token>'
  },
  body: JSON.stringify({
    message: "我想做一个用户管理系统",
    session_id: null  // 首次为null
  })
});
```

**响应**：Server-Sent Events (SSE) Stream
```javascript
const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const {done, value} = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = JSON.parse(line.slice(6));
      
      switch (data.type) {
        case 'analysis_start':
          // 显示"正在分析..."
          break;
        case 'mcp_call':
          // 显示"正在调用知识库..."
          break;
        case 'understanding':
          // 实时更新理解草案
          updateDraft(data.draft);
          break;
        case 'clarification':
          // 显示澄清问题
          showQuestions(data.points);
          break;
        case 'done':
          // 完成，保存session_id
          sessionId = data.session_id;
          reqId = data.req_id;
          break;
      }
    }
  }
}
```

#### 继续对话

```javascript
// 用户输入补充信息
const response = await fetch('/api/dialogue/chat', {
  method: 'POST',
  body: JSON.stringify({
    message: "用户需要支持多角色权限",
    session_id: sessionId,  // 使用之前保存的session_id
    addresses_points: ["point_1"]
  })
});

// 同样处理Stream响应
```

#### 确认提交

```javascript
const result = await fetch('/api/dialogue/confirm', {
  method: 'POST',
  body: JSON.stringify({
    session_id: sessionId,
    confirmed: true,
    final_notes: "需求已确认"
  })
});

const data = await result.json();
// { success: true, req_id: "...", message: "需求已提交" }
```

### 8.2 历史对话展示

**加载历史**：

**API**: `GET /api/dialogue/history/{session_id}`

**响应**：
```json
{
  "session_id": "uuid",
  "req_id": "uuid",
  "status": "reopened",
  "reopen_count": 1,
  "current_understanding": {...},
  "messages": [
    {
      "id": 1,
      "role": "human",
      "content": {
        "text": "我想做一个用户管理系统",
        "type": "initial"
      },
      "reopen_round": 0,
      "timestamp": "2026-07-08T10:00:00Z"
    },
    {
      "id": 2,
      "role": "ai",
      "content": {
        "text": "我理解您需要...",
        "type": "understanding"
      },
      "understanding_snapshot_id": 123,
      "reopen_round": 0,
      "timestamp": "2026-07-08T10:00:05Z"
    },
    {
      "id": 10,
      "role": "system",
      "content": {
        "text": "Gate1审批未通过",
        "type": "gate_rejection",
        "gate_info": {
          "gate_level": 1,
          "reject_reasons": ["需求描述不够清晰"],
          "reviewer_feedback": "建议补充..."
        }
      },
      "reopen_round": 1,
      "timestamp": "2026-07-08T11:00:00Z"
    },
    {
      "id": 11,
      "role": "human",
      "content": {
        "text": "已补充用户角色详细说明",
        "type": "supplement"
      },
      "reopen_round": 1,
      "timestamp": "2026-07-08T11:30:00Z"
    }
  ]
}
```

**前端展示**：

```
┌─────────────────────────────────────┐
│  需求分析对话                          │
├─────────────────────────────────────┤
│ 【第1轮对话】                  [灰色背景] │
│                                      │
│ 👤 用户: 我想做一个用户管理系统        │
│                                      │
│ 🤖 A1: 我理解您需要一个包含用户增删改  │
│        查功能的系统...                │
│        待澄清点：                      │
│        1. 用户角色权限如何设计？       │
│                                      │
│ 👤 用户: 需要管理员和普通用户两种角色  │
│                                      │
│ 🤖 A1: 理解已更新...                 │
│                                      │
│ [用户点击"确认提交"]                   │
├─────────────────────────────────────┤
│ ⚠️  Gate1审批未通过          [红色高亮] │
│     原因：需求描述不够清晰             │
│     反馈：建议补充用户角色的详细说明    │
├─────────────────────────────────────┤
│ 【第2轮对话 - 修订中】         [正常背景] │
│                                      │
│ 👤 用户: 已补充用户角色详细说明...     │
│                                      │
│ 🤖 A1: 理解已更新...                 │
│                                      │
│ [输入框] ___________________  [发送]  │
│                                      │
│ [取消]  [确认提交]                    │
└─────────────────────────────────────┘
```

**分组逻辑**：
- 按 `reopen_round` 分组
- 第0轮：首次对话（灰色背景表示历史）
- 系统消息：Gate打回（红色高亮）
- 第N轮：当前修订轮次（正常背景）

### 8.3 实时通知（可选）

**WebSocket连接**：`ws://host/ws/notifications`

**接收消息**：
```javascript
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  if (msg.type === 'gate_rejected') {
    // 显示通知："您的需求{req_id}被Gate{level}打回"
    showNotification({
      title: '需求被打回',
      message: `Gate${msg.gate_level}审批未通过`,
      action: {
        label: '查看详情',
        url: `/requirements/${msg.req_id}`
      }
    });
  }
};
```

### 8.4 UI状态管理

**对话状态**：
```javascript
const dialogueState = {
  sessionId: null,      // 会话ID
  reqId: null,          // 需求ID
  status: 'active',     // active | completed | reopened
  reopenCount: 0,       // 重开次数
  messages: [],         // 消息列表
  currentDraft: null,   // 当前理解草案
  clarificationPoints: [], // 待澄清点
  isStreaming: false,   // 是否正在接收Stream
};
```

**交互流程**：
1. 用户输入 → 禁用输入框，显示"发送中..."
2. 开始接收Stream → 显示"分析中..."
3. 实时更新理解草案 → 动态展示
4. Stream结束 → 启用输入框，显示"可以继续对话"
5. 用户可以继续补充或点击"确认提交"

---

## 九、实施建议

### 9.1 Phase 1: 基础对话流程（1周）

**数据库**:
- 创建4张表：requirements, dialogue_sessions, dialogue_messages, understanding_snapshots
- 执行migration

**MC Backend**:
- POST /api/dialogue/chat (对话接口，支持SSE Stream)
  - 首次调用：创建需求和会话
  - 后续调用：记录消息并触发A1分析
  - 返回SSE Stream
- POST /api/dialogue/confirm (确认提交)
  - 保存最终需求
  - 发布NATS事件：requirement.draft.finalized
- GET /api/dialogue/history/{session_id} (获取历史)

**A1分析模块**:
- 作为MC Backend的内部模块（或独立微服务）
- 输入：session_id
- 处理：加载历史 → LLM分析 → 生成草案 → 识别澄清点
- 输出：通过SSE Stream返回分析过程

**前端**:
- 对话界面组件
- Fetch Readable Stream处理
- 实时展示分析过程

**验收**:
- ✅ 用户可以发起对话
- ✅ A1可以实时Stream分析结果
- ✅ 用户可以多轮补充信息
- ✅ 用户可以确认提交

### 9.2 Phase 2: MCP知识增强（1周）

**MCP集成**:
- 部署knowledge-base-mcp服务
- A1分析时调用MCP工具
- 记录knowledge_sources和mcp_tools_used到understanding_snapshots

**Stream增强**:
- 调用MCP时通过Stream通知前端
- 显示"正在查询历史需求..."等进度

**验收**:
- ✅ A1能自动搜索相似需求
- ✅ 能提供技术栈建议
- ✅ 能识别领域风险
- ✅ 前端能看到MCP调用进度

### 9.3 Phase 3: Orchestrator集成（3天）

**Orchestrator**:
- 订阅NATS事件：requirement.draft.finalized
- 启动RequirementWorkflow（初始状态DESIGNING）
- 订阅NATS事件：requirement.draft.revised
- 发送Signal恢复workflow

**MC Backend**:
- 在dialogue/confirm接口中发布NATS事件

**验收**:
- ✅ A1完成后自动触发Orchestrator
- ✅ Workflow从DESIGNING开始
- ✅ 状态正确流转到requirements表

### 9.4 Phase 4: Gate打回流程（1周）

**Gate打回API**:
- POST /api/approvals/{id}/reject
  - 更新数据库
  - 重新激活dialogue_sessions
  - 注入打回原因到dialogue_messages
  - 可选：发布NATS通知事件

**前端增强**:
- 展示完整历史（按reopen_round分组）
- 高亮显示打回原因
- "继续对话"按钮

**修订确认**:
- 使用相同的dialogue/confirm接口
- 发布不同的NATS事件：requirement.draft.revised

**验收**:
- ✅ Gate打回后会话自动恢复
- ✅ 用户可以看到完整历史和打回原因
- ✅ 打回原因清晰展示
- ✅ 修订后可以重新提交
- ✅ Orchestrator能恢复workflow

### 9.5 技术栈建议

**MC Backend**:
- FastAPI (Python) 或 Express (Node.js)
- SSE Stream支持（原生支持）

**A1分析模块**:
- LangChain/LlamaIndex（支持MCP）
- OpenAI/Claude API（支持Stream）

**前端**:
- React/Vue
- Fetch API + ReadableStream
- EventSource (SSE客户端)

**数据库**:
- PostgreSQL（支持JSONB）

**消息队列**:
- NATS（仅用于跨服务通知）

### 9.6 关键技术点

**1. SSE Stream实现（MC Backend）**

Python FastAPI示例：
```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

@app.post("/api/dialogue/chat")
async def chat(request: ChatRequest):
    async def event_generator():
        # 分析开始
        yield f"data: {json.dumps({'type': 'analysis_start'})}\n\n"
        
        # 调用A1分析（支持Stream）
        async for chunk in a1_service.analyze_stream(session_id):
            yield f"data: {json.dumps(chunk)}\n\n"
        
        # 分析完成
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**2. 前端Stream处理**

```javascript
async function chat(message, sessionId) {
  const response = await fetch('/api/dialogue/chat', {
    method: 'POST',
    body: JSON.stringify({message, session_id: sessionId})
  });
  
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    
    const text = decoder.decode(value);
    const lines = text.split('\n\n');
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        handleStreamData(data);
      }
    }
  }
}
```

**3. 数据库并发处理**

- 使用事务确保数据一致性
- dialogue_messages使用sequence_number保证顺序
- dialogue_sessions的iterations递增

**4. NATS事件发布**

- 仅在用户确认时发布
- 包含完整的draft数据
- Orchestrator订阅并启动workflow

---

## 十、总结

### 核心特点

1. **A1完全独立** - 不依赖Orchestrator，纯对话服务
2. **用户主导** - 用户决定节奏，何时确认
3. **数据完整** - 所有交互完整记录，支持审计
4. **可恢复** - Gate打回后无缝恢复会话
5. **知识增强** - MCP/知识库自动增强分析
6. **事件驱动** - 松耦合，易扩展

### 关键数据流

- **入口**: 用户消息 → dialogue_messages
- **处理**: LLM+MCP → understanding_snapshots
- **出口**: 需求草案 → requirements.requirement_draft
- **循环**: Gate打回 → 恢复会话 → 继续对话

### 文档定位

本文档专注于：
- ✅ 业务流程清晰
- ✅ 数据流完整
- ✅ 表结构明确
- ✅ 事件协议清晰
- ❌ 不包含代码实现细节
- ❌ 不包含部署配置
- ❌ 不包含性能优化

---

**文档维护**: AI-Native团队  
**最后更新**: 2026-07-08  
**版本**: v3.0 (业务流程设计)
