# AI-Native Agent 协作架构与数据流说明

> 面向技术负责人，涵盖 Agent 协作关系、信息传递、LLM 调用链路。

---

## 一、完整状态机与数据流（12 状态 + 4 Gate）

### 1.1 状态机全景图

```
DRAFT（初始状态）
  │
  ▼
ANALYZING [A1] ──→ 产物持久化到 spec.artifacts.A1
  │                └─ notify_mc("A1 完成分析")
  ▼
Gate 0（业务确认，SLA 1h，无 grace period）
  │ 人工审批通过
  ▼
DESIGNING [A3 ∥ A4] ──→ A3/A4 产物持久化
  │                     ├─ A3 → spec.artifacts.A3
  │                     └─ A4 → spec.openapi + spec.erd（自持久化）
  │                     └─ notify_mc("设计完成，等待评审")
  ▼
Gate 1（设计方案确认，SLA 4h，grace 1h）
  │ 人工审批通过
  ▼
REVIEWING [A5] ──→ A5 评审结果持久化到 spec.artifacts.A5
  │                 └─ notify_mc(评分详情 + pass/fail 状态)
  │
  ├─ pass=false + rework_count<2 ─┐
  │   └─ 回到 DESIGNING            │  Rework Loop（最多 2 轮）
  │      注入 rework_context ────┘
  │
  ├─ pass=true 或 rework_count≥2
  │   └─ 强制推进
  ▼
DECOMPOSING [A6] ──→ DAG 持久化到 spec.artifacts.A6
  │                   └─ notify_mc("任务拆解完成，共 N 个节点")
  ▼
Gate 2（任务计划确认，SLA 4h，grace 1h）
  │ 人工审批通过
  ▼
DEVELOPING [A9] ──→ 代码 diff 持久化到 spec.artifacts.A9
  │                 ├─ commit_sha 记录
  │                 ├─ audit 报告
  │                 └─ notify_mc("开发完成，提交 commit {sha}")
  ▼
TESTING [A11] ──→ 测试报告持久化到 spec.artifacts.A11
  │               ├─ total, passed, failed
  │               └─ notify_mc(测试通过率)
  │
  ├─ passed=false + inner_loop<2 ─┐
  │   └─ 回到 DEVELOPING            │  Inner Loop（最多 2 轮）
  │      注入 TEST_FAILURE ───────┘
  │
  ├─ passed=true
  │   └─ 继续
  ▼
REVIEWING_CODE [A12] ──→ 审查结果持久化到 spec.artifacts.A12
  │                       ├─ verdict: pass/fail
  │                       ├─ score: 0-100
  │                       ├─ issues: [{severity, file, line, description}]
  │                       └─ notify_mc(审查结论 + 得分)
  ▼
Gate 3（代码审查确认，SLA 2h，无 grace period）
  │ 人工审批通过
  ▼
RELEASING [A13] ──→ 发布记录持久化到 spec.artifacts.A13
  │                 ├─ 金丝雀阶段: 5% → 20% → 50% → 100%
  │                 ├─ 监控回滚逻辑
  │                 └─ notify_mc(发布进度)
  ▼
DONE（终态）

特殊状态:
  BLOCKED ──→ Agent 主动请求阻塞（如发现无法解决的依赖）
             └─ notify_mc("需求已阻塞，原因: ...")
```

### 1.2 关键设计决策

**当前实现**：
- A2（知识检索）、A7（测试用例生成）、A8（架构评审）不在主线调度中
- A3（UI 原型）和 A4（技术规格）在 DESIGNING 阶段**并行执行**
- A5 设计评审触发 rework 循环（最多 2 轮）
- A11 测试触发 inner loop（最多 2 轮）

**数据持久化机制**：
- **A4 例外**：自持久化到 `spec.openapi` / `spec.erd`，不走 `store_agent_result`
- **其他 Agent**：通过 `store_agent_result` Activity 写入 `spec.artifacts.{agent_id}`
- **Gate 决策**：通过 `store_gate_decision` Activity 写入 `spec.decisions`

**notify_mc 双写**：
- **NATS 事件**：`state.changed.{req_id}` → 前端实时订阅
- **DB 写入**：`requirements.current_state` + `state_metadata.last_notify_at`

### 1.3 Gate 三阶段机制（SLA → Grace → Escalate）

| Gate | 触发位置 | SLA | Grace Period | 超时行为 |
|------|---------|-----|-------------|---------|
| Gate 0 | ANALYZING → DESIGNING | 1h | 无 | SLA 到期 → notify_mc → 无限等待人工 |
| Gate 1 | DESIGNING → REVIEWING | 4h | 1h | SLA 到期 → notify_mc → grace 1h → escalate → 无限等待 |
| Gate 2 | DECOMPOSING → DEVELOPING | 4h | 1h | 同 Gate 1 |
| Gate 3 | REVIEWING_CODE → RELEASING | 2h | 无 | 同 Gate 0 |

**三阶段详解**：
```
Phase 1: SLA 窗口（等待人工审批）
  ├─ Workflow: await workflow.wait_condition(_gate_approved == gate_name, timeout=SLA)
  └─ 超时后 → Phase 2

Phase 2: notify_mc + Grace Period（仅 Gate 1/2）
  ├─ notify_mc(event="gate.sla_expired", gate=gate_name)
  ├─ Workflow: await workflow.wait_condition(_gate_approved == gate_name, timeout=grace_period)
  └─ 超时后 → Phase 3

Phase 3: escalate（永久等待）
  ├─ notify_mc(event="gate.escalated", gate=gate_name)
  ├─ Workflow: await workflow.wait_condition(_gate_approved == gate_name)  # 无超时
  └─ 人工必须处理（approve/reject/force_timeout）
```

**Gate 决策持久化**：
```python
# store_gate_decision Activity
spec.decisions = {
    "resolved": {
        "gate_0": "approved",
        "gate_1": "approved",
        "gate_2": "rejected"  # 人工拒绝
    },
    "source_gates": ["gate_0", "gate_1", "gate_2"],
    "gate_0_approved_at": "2026-07-08T10:00:00Z",
    "gate_0_approver": "user@example.com",
    "gate_1_approved_at": "2026-07-08T14:30:00Z",
    "gate_2_rejected_at": "2026-07-08T18:00:00Z",
    "gate_2_reject_reason": "数据库设计需修改"
}
```

### 1.4 Context Build 五层模型与数据流

每次 dispatch Agent 前，Orchestrator 调用 `build_context(req_id, state)` 组装上下文包，严格按阶段选择性暴露上游产物。

**五层结构**：
```python
context = {
    # Layer 1: 需求上下文（所有阶段都有）
    "requirement_context": {
        "title": "用户认证系统",
        "description": "实现用户注册、登录、Token 刷新",
        "acceptance_criteria": ["验收条件1", "验收条件2"],
        "analysis": {},  # A1 分析结果（首轮 ANALYZING 为空）
        "source_type": "llm"
    },
    
    # Layer 2: 产物上下文（按状态选择性暴露）
    "artifact_context": {
        "A1": {...},  # DESIGNING 及之后包含
        "A2": {...},  # DESIGNING 及之后包含（当前为空，A2 未调度）
        "A3": {...},  # REVIEWING 及之后包含
        "A4": {...},  # REVIEWING 及之后包含（从 spec.openapi/erd 读取）
        "A5": {...},  # DECOMPOSING 及之后包含
        "A6": {...},  # DEVELOPING 及之后包含
        "A7": {...},  # DEVELOPING 及之后包含（当前为空，A7 未调度）
        "A9": {...},  # TESTING 及之后包含
        "A11": {...}, # REVIEWING_CODE 及之后包含
        "A12": {...}  # RELEASING 及之后包含
    },
    
    # Layer 3: 知识上下文（pgvector 检索 + 分层）
    "knowledge_context": {
        "head": [{"chunk": "...", "relevance": 0.92}],  # ≥0.8
        "mid":  [{"chunk": "...", "relevance": 0.65}],  # 0.5-0.8
        "tail": [{"chunk": "...", "relevance": 0.45}]   # <0.5
    },
    
    # Layer 4: 环境上下文（项目配置）
    "environment_context": {
        "project": {
            "name": "AI-Native Platform",
            "tech_stack": ["Python", "React", "PostgreSQL"],
            "claude_md_content": "...(前 2000 字符)..."
        },
        "deployment": {
            "dev_url": "http://dev.example.com",
            "staging_url": "http://staging.example.com"
        }
    },
    
    # Layer 5: 决策上下文（仅 developing 及之后包含）
    "decisions_context": {
        "resolved": {"gate_0": "approved", "gate_1": "approved"},
        "source_gates": ["gate_0", "gate_1"]
    },
    
    # Layer 6: Rework 上下文（仅 rework 时非空）
    "rework_context": {
        "round_number": 1,
        "issues": [{"severity": "critical", "description": "...", "suggestion": "..."}],
        "scores": {"ux": 10, "api": 5, "business": 5},
        "suggestion": "请重点修复 critical 和 major 级别问题"
    }
}
```

**按状态的选择性暴露规则**：

| 当前状态 | artifact_context 包含 | 理由 |
|---------|---------------------|------|
| `analyzing` | 无 | A1 是起点，无上游产物 |
| `designing` | A1, A2 | A3/A4 需要 A1 需求 + A2 知识检索 |
| `reviewing` | A1, A2, A3, A4 | A5 需要评审 A3 原型 + A4 规格 |
| `decomposing` | A1, A4, A5 | A6 需要需求 + 规格 + 评审结果拆任务 |
| `developing` | A1, A4, A5, A6, A7 | A9 需要需求 + API/ERD + DAG + 测试用例 |
| `testing` | A4, A7, A9 | A11 需要 API/ERD + 测试用例 + 代码 diff |
| `reviewing_code` | A4, A9, A11 | A12 需要 API/ERD + 代码 + 测试结果 |
| `releasing` | A4, A9, A11, A12 | A13 需要完整交付物 |

**A4 特殊处理**：A4 不在 `spec.artifacts`，从 `spec.openapi` / `spec.erd` 读取后转为标准结构：
```python
artifact_context["A4"] = {
    "openapi": {
        "paths": {"/auth/login": ["post"], "/users/me": ["get"]},
        "info": {"title": "...", "version": "1.0.0"},
        "has_schema": True
    },
    "erd": {
        "tables": ["users", "sessions"],
        "relationships": [{"from": "users", "to": "sessions", "type": "one_to_many"}],
        "has_entities": True
    }
}
```

---

## 二、各阶段 Agent 的协作与数据传递

### 阶段 1：需求分析 — A1

```
触发方式：用户提交需求文本
输入来源：用户原始消息（"做一个用户登录功能"）
```

**A1 做什么：**

调用 LLM 将自然语言需求转化为结构化需求草案。

| 维度 | 内容 |
|------|------|
| LLM 入参来源 | 用户原始消息文本 |
| LLM 出参结构 | `{ title, domain, summary, entities, acceptance_criteria, tech_stack_suggestion, risk_points, priority_suggestion }` |
| 非 LLM 兜底 | 关键词匹配（"登录"→auth, "订单"→order_management） |
| 写入 DB 位置 | `requirements.spec.artifacts.A1` |
| 下游谁会读 | A3（取 title, domain）、A4（取 title, domain, acceptance_criteria）、A5（取 analysis） |

**A1 产出的具体内容示例：**

```json
{
  "title": "用户认证系统",
  "domain": "auth",
  "summary": "实现用户注册、登录、Token 刷新功能，支持 JWT 认证",
  "entities": { "user_role": ["end_user"], "entity_name": ["user", "login_attempt"] },
  "acceptance_criteria": [
    "用户可通过邮箱+密码注册账号",
    "用户可通过邮箱+密码登录获取 JWT Token",
    "Token 过期后可使用 Refresh Token 刷新"
  ],
  "tech_stack_suggestion": { "backend": "FastAPI", "frontend": "React", "database": "PostgreSQL" },
  "risk_points": ["密码存储需加盐哈希", "Token 泄露风险"],
  "priority_suggestion": "P1"
}
```

---

### 阶段 2：并行设计 — A3（UI 原型）+ A4（技术规格）

```
触发方式：Gate0 人工通过后，Orchestrator 同时 dispatch A3 和 A4
输入来源：A1 的原求草案 + knowledge_context（历史相似需求）
```

**两个 Agent 并行运行，互不依赖。**

#### A3 — UI 原型生成

| 维度 | 内容 |
|------|------|
| 从哪里取数据 | `context_package.requirement_draft`（即 A1 产物）→ 取 `title`, `domain` |
| LLM 入参 | 需求标题 + 需求描述 + 业务领域 + 知识上下文 + 评审反馈（如果是 rework） |
| LLM 出参 | `{ html: "完整 HTML 代码", description: "设计说明" }` |
| 产物 | 一个可浏览器直接打开的内联 CSS HTML 原型页面（含 default/hover/empty/error 四种状态） |
| 写入 DB 位置 | `requirements.spec.artifacts.A3` |
| 下游谁会读 | A5（评审时检查 UX 维度）、前端开发者（预览效果） |

**LLM Prompt 关键信息：**
```
你是资深 UI/UX 设计师。根据需求生成一个可直接预览的 HTML 原型页面。
需求标题: {来自 A1 的 title}
需求描述: {来自 A1 的 summary}
业务领域: {来自 A1 的 domain}
要求: 内联 CSS、搜索/筛选、数据表格、操作按钮、空状态占位
```

#### A4 — 技术规格编写

| 维度 | 内容 |
|------|------|
| 从哪里取数据 | `context_package.requirement_draft`（A1 产物）→ 取 `title`, `domain`, `acceptance_criteria`, `summary` |
| 两个子模块 | `APISchemaGenerator` 生成 OpenAPI 3.0 + `ERDGenerator` 生成数据库 ER 图 |
| LLM 入参 | 需求文本 + domain + acceptance_criteria + 重试时的 rework 反馈 |
| LLM 出参 | OpenAPI Schema（paths, components, schemas）+ ERD（entities 含 columns, relationships, DDL） |
| 写入 DB 位置 | `requirements.spec.openapi` + `requirements.spec.erd`（A4 自持久化，不走通用 store） |
| 版本化存储 | 同时写入 `api_schemas` 和 `erd_designs` 独立表，支持版本追溯 |
| 下游谁会读 | A5（评审 API 和数据结构）、A6（拆解开发任务）、A9（编码时参考 API 契约） |

**A4 产出的具体内容示例：**

```json
// spec.openapi — API 定义
{
  "info": { "title": "用户认证 API", "version": "1.0.0" },
  "paths": {
    "/auth/login":      { "post": { "summary": "用户登录", "requestBody": {...}, "responses": {...} } },
    "/auth/register":   { "post": { "summary": "用户注册", ... } },
    "/auth/refresh":    { "post": { "summary": "刷新 Token", ... } },
    "/users/me":        { "get":  { "summary": "获取当前用户信息", ... } }
  }
}

// spec.erd — 数据库设计
{
  "entities": [
    { "name": "users", "columns": [
        {"name": "id", "type": "UUID", "primary_key": true},
        {"name": "email", "type": "VARCHAR(255)", "unique": true, "not_null": true},
        {"name": "password_hash", "type": "VARCHAR(255)", "not_null": true},
        {"name": "created_at", "type": "TIMESTAMP"}
      ]
    },
    { "name": "sessions", "columns": [
        {"name": "id", "type": "UUID", "primary_key": true},
        {"name": "user_id", "type": "UUID", "foreign_key": "users.id"},
        {"name": "refresh_token", "type": "VARCHAR(512)"},
        {"name": "expires_at", "type": "TIMESTAMP"}
      ]
    }
  ],
  "relationships": [
    { "from": "users", "to": "sessions", "type": "one_to_many", "foreign_key": "user_id" }
  ]
}
```

---

### 阶段 3：设计评审 — A5

```
触发方式：Gate1 人工通过后
输入来源：直接从 DB 读 A4 写入的 spec.openapi + spec.erd
```

| 维度 | 内容 |
|------|------|
| 数据来源 | 直接从 DB 的 `requirements` 表读 `spec` 列（含 A4 写的 openapi + erd）— **不从 context_package 读 A4** |
| 评审维度 | **UX 启发式评审**（交互状态、一致性、反馈） + **API 评审**（N+1 风险、粒度、错误码） + **业务完整性**（鉴权、校验、边界条件、审计） |
| 评分标准 | 每维度 0-100 分，≥70 为通过 |
| 通过条件 | **3 个维度中 ≥2 个通过即为通过**（API 可后续优化） |
| LLM 入参 | 需求标题 + A1 分析 + A3 原型 + A4 的 OpenAPI/ERD（压缩后） |
| LLM 出参 | 三维度评分 + findings（每条含 severity、description、suggestion） + overall_pass |

**A5 评审结果示例：**

```json
{
  "pass": false,
  "scores": {
    "ux_heuristic":          { "score": 10, "passed": false },
    "api_n1":                { "score": 5,  "passed": false },
    "business_completeness": { "score": 5,  "passed": false },
    "average": 6.7
  },
  "issues": [
    { "severity": "critical", "heuristic": "系统状态可见性", "description": "未定义 loading/error/empty 状态", "suggestion": "为每个页面补充三种状态的 UI 描述" },
    { "severity": "high", "endpoint": "/auth/login", "risk": "N+1", "description": "用户信息查询可能与 session 查询产生 N+1", "suggestion": "使用 JOIN 或批量查询" },
    { "severity": "high", "category": "validation", "description": "缺少输入校验规则", "suggestion": "定义邮箱格式、密码强度、Token 过期策略" }
  ],
  "summary": "Spec 不完整，缺少 UI 交互状态和 API 错误处理定义"
}
```

**Rework 机制：**
- 若 `pass == false` 且 rework 次数 < 2 → Orchestrator **回退到 DESIGNING 阶段**
- A3 和 A4 重新 dispatch，**context 中注入 A5 的 issues 作为 rework_context**
- A3 和 A4 的 LLM prompt 中会追加 `【上一轮评审反馈 — 请重点修复以下问题】` 段
- 第 2 次 rework 后仍不过 → 强制进入下一阶段（不阻塞流水线）

---

### 阶段 4：任务拆解 — A6

```
触发方式：A5 评审通过（或 rework 耗尽）
输入来源：A1 需求草案 + A4 技术规格 + A5 评审结果
```

| 维度 | 内容 |
|------|------|
| LLM 入参 | 需求标题 + 压缩后的 spec 信息（OpenAPI paths, ERD entities） + knowledge_context |
| LLM 出参 | `{ nodes, edges, critical_path, parallel_groups, total_estimated_hours }` |
| 规则 | ≥5 个任务节点，标注并行关系，high complexity 的标为需人工审核 |
| 写入 DB 位置 | `requirements.spec.artifacts.A6` |
| 下游谁会读 | A9（编码时根据 DAG 节点逐个实现）、A7（按 DAG 节点生成测试用例）、A8（架构评审） |

**A6 产出的 DAG 示例：**

```json
{
  "dag_id": "dag-3ab93964-20260708143052",
  "nodes": [
    { "id": "task-01", "type": "db",       "title": "用户表与会话表设计",   "complexity": "medium", "estimated_hours": 4 },
    { "id": "task-02", "type": "backend",  "title": "注册接口开发",         "complexity": "medium", "estimated_hours": 6 },
    { "id": "task-03", "type": "backend",  "title": "登录与 JWT 签发",      "complexity": "high",   "estimated_hours": 8 },
    { "id": "task-04", "type": "backend",  "title": "Token 刷新接口",       "complexity": "low",    "estimated_hours": 3 },
    { "id": "task-05", "type": "frontend", "title": "登录/注册页面",        "complexity": "medium", "estimated_hours": 8 },
    { "id": "task-06", "type": "testing",  "title": "认证流程集成测试",     "complexity": "medium", "estimated_hours": 6 },
    { "id": "task-07", "type": "deployment","title": "部署与金丝雀发布",    "complexity": "low",    "estimated_hours": 2 }
  ],
  "edges": [
    { "from": "task-01", "to": "task-02", "type": "sequential" },
    { "from": "task-01", "to": "task-03", "type": "sequential" },
    { "from": "task-02", "to": "task-04", "type": "sequential" },
    { "from": "task-03", "to": "task-04", "type": "sequential" },
    { "from": "task-02", "to": "task-05", "type": "parallel" },
    { "from": "task-03", "to": "task-05", "type": "parallel" },
    { "from": "task-04", "to": "task-06", "type": "sequential" },
    { "from": "task-05", "to": "task-06", "type": "sequential" },
    { "from": "task-06", "to": "task-07", "type": "sequential" }
  ],
  "critical_path": ["task-01", "task-03", "task-04", "task-06", "task-07"],
  "parallel_groups": [
    { "name": "前后端并行开发", "tasks": ["task-02", "task-05"] },
    { "name": "认证核心",       "tasks": ["task-03", "task-04"] }
  ],
  "total_estimated_hours": 37
}
```

---

### 阶段 5：编码实现 — A9（双脑架构）

```
触发方式：Gate2 人工通过后
输入来源：A1 需求 + A4 OpenAPI/ERD + A5 评审 + A6 DAG + A7 测试用例
```

这是最复杂的 Agent，采用 **Coder ↔ Auditor 双脑架构**：

```
Coder 生成代码 ──→ Lint ──→ Build ──→ Unit Test ──→ Smoke Test ──→ Docker Build
                                                                          │
                                                                          ▼
                                                                   Auditor 审查 diff
                                                                          │
                                                          ┌───────────────┤
                                                          │ 通过          │ 不通过
                                                          ▼               ▼
                                                     提交代码      反馈给 Coder 重写（最多 3 轮）
```

**A9 输入的完整上下文（由 build_context 组装）：**

| 信息层 | 具体内容 | 来源 |
|--------|---------|------|
| 需求信息 | 标题、描述、验收条件 | A1 `requirement_draft` |
| API 契约 | `/auth/login` POST, `/users/me` GET 等 | A4 `openapi_hint.paths` |
| 数据模型 | `users` 表 4 列, `sessions` 表 5 列 | A4 `erd_hint.tables` |
| 任务拆分 | 7 个节点的 DAG，含并行组和关键路径 | A6 `dag_hint.nodes/edges` |
| 编码规范 | CLAUDE.md 内容（前 2000 字符） | 项目仓库根目录 |
| 技术栈 | FastAPI + React + PostgreSQL | 项目配置 `.ai-native/project-config.yaml` |
| 部署地址 | dev/staging/production URL | 同上 |
| Gate 决策 | Gate 0/1/2 的人工审批记录 | `spec.decisions` |
| 历史知识 | 相似代码、最佳实践、已知 Bug | knowledge_chunks 向量搜索 |
| 测试用例 | A7 生成的测试用例（如果有） | `spec.artifacts.A7` |
| 约束规则 | 不修改数据库迁移、遵循现有规范 | 硬编码 |

**A9 产出的内容：**

```json
{
  "status": "completed",
  "code_diff": "diff --git a/src/auth/login.py ...",
  "files_changed": 5,
  "commit_sha": "a1b2c3d4",
  "session_id": "session-xxx",
  "engine": "claude-code",
  "iterations": 2,
  "audit": {
    "score": 85,
    "issues": [
      { "severity": "minor", "file": "auth.py:42", "description": "密码哈希未加盐", "suggestion": "使用 bcrypt" }
    ]
  },
  "self_test": { "passed": 12, "failed": 0, "coverage": 0.85 }
}
```

**Inner Loop（A9 ↔ A11）：**
- A11 测试不通过 → Orchestrator 回退到 DEVELOPING 阶段
- A9 收到 `[TEST_FAILURE_FEEDBACK]` 段，含具体失败用例和错误信息
- A9 根据失败信息修复代码 → A11 重新测试
- 最多 2 轮，超过后强制推进

---

### 阶段 6：代码审查 — A12

```
触发方式：A11 测试通过后
输入来源：A9 code_diff + A11 test_report
```

| 维度 | 内容 |
|------|------|
| LLM 入参 | 代码 diff + 测试结果（passed/failed 详情） |
| LLM 出参 | `{ score: 0-100, issues: [{severity, file, line, description, suggestion}], auto_fix_patches }` |
| 检查项 | SQL 注入、XSS、CSRF、硬编码密钥、不安全加密、空指针、异常处理、类型安全 |
| 写入 DB 位置 | `requirements.spec.artifacts.A12` |
| Auto-fix | warning/info 级别问题自动生成修补 patch |

---

## 三、数据在 DB 中的存储结构

所有 Agent 的产出存在 `requirements` 表的 `spec` JSONB 列中：

```json
// requirements.spec — 逻辑结构
{
  "acceptance_criteria": [...],           // A1 写入
  "openapi": {                            // A4 自写入
    "schema": { "info": {...}, "paths": {...}, "components": {...} }
  },
  "erd": {                                // A4 自写入
    "entities": [{ "name": "users", "columns": [...] }],
    "relationships": [...],
    "ddl": "CREATE TABLE ..."
  },
  "decisions": {                          // Gate 审批记录
    "resolved": { "gate_0": "approved", "gate_1": "approved" },
    "source_gates": ["gate_0", "gate_1"],
    "approved_at": "2026-07-08T12:00:00Z"
  },
  "artifacts": {                          // store_agent_result 写入（除 A4 外所有 Agent）
    "A1": { "status": "completed", "domain": "auth", "requirement_draft": {...} },
    "A2": { "status": "completed", "knowledge_package": {...} },
    "A3": { "status": "completed", "prototype_size": 8234, "html_preview": "..." },
    "A5": { "status": "failed", "pass": false, "scores": {...}, "issues": [...] },
    "A6": { "status": "completed", "dag": { "nodes": [...], "edges": [...] } },
    "A7": { "status": "completed", "test_cases": [...] },
    "A8": { "status": "completed", "review": {...} },
    "A9": { "status": "completed", "code_diff": "...", "commit_sha": "..." },
    "A10": { "status": "completed", "staging_url": "..." },
    "A11": { "status": "completed", "pass": true, "passed": 12, "failed": 0 },
    "A12": { "status": "completed", "verdict": "approved", "score": 85 },
    "A13": { "status": "completed", "release_id": "..." }
    // 注意：没有 A4！A4 不在 artifacts 里
  }
}
```

**查 DB 验证流水线的常用 SQL：**

```sql
-- 查看某个需求的所有 Agent 产物
SELECT spec->'artifacts' FROM requirements WHERE id = '3ab93964-...';

-- 查看 A3 是否崩溃
SELECT spec->'artifacts'->'A3'->>'status' FROM requirements WHERE id = '...';

-- 查看 A5 评审分数
SELECT spec->'artifacts'->'A5'->'scores'->>'average' FROM requirements WHERE id = '...';

-- 查看 A4 产出了几张表
SELECT jsonb_array_length(spec->'erd'->'entities') FROM requirements WHERE id = '...';

-- 查看 rework 次数（通过 artifacts 是否有 A5 且 pass=false 判断）
SELECT spec->'artifacts'->'A5'->>'pass' FROM requirements WHERE id = '...';
```

---

## 四、Context 组装规则 — build_context

每次 dispatch Agent 前，Orchestrator 调用 `build_context(req_id, state)` 组装上下文包。核心规则：

**按阶段选择性暴露上游产物，而不是把所有数据一股脑塞给 Agent。**

| 当前阶段 | 给 Agent 看哪些上游产物 | 不给看的 |
|---------|----------------------|----------|
| `analyzing` | 无（只看用户消息） | — |
| `designing` (A3/A4) | A1 需求草案, A2 知识检索 | A5 评审（还没跑） |
| `reviewing` (A5) | A1 需求, A2 知识, A3 原型, A4 规格 | A6 DAG（还没拆） |
| `decomposing` (A6) | A1 需求, A4 规格, A5 评审 | A9 代码（还没写） |
| `developing` (A9) | A1 需求, A4 API+ERD, A5 评审, A6 DAG, A7 测试用例 | A11 测试结果（还没测） |
| `testing` (A11) | A4 规格, A7 测试用例, A9 代码 | A12 审查（还没审） |
| `reviewing_code` (A12) | A4 规格, A9 代码, A11 测试结果 | A13 发布（还没发） |

**每个阶段上下文还有 3 个公共层：**
- **knowledge_context**：从向量库检索的历史相似需求、最佳实践、已知 Bug（按 Agent 定制搜索词）
- **environment_context**：项目名、技术栈、编码规范（CLAUDE.md）、部署地址（从 `.ai-native/project-config.yaml` 加载）
- **decisions_context**：Gate 审批决策记录（仅在 developing 及之后阶段包含）

---

## 五、Agent 间通信机制

```
Orchestrator (Temporal Workflow)
  │
  ├─ build_context (读 DB 组装上下文)
  │
  ├─ dispatch_agent (发布 NATS 消息)
  │     │
  │     └──→ NATS Subject: context.ready.{agent_type}
  │             │
  │             └──→ Agent Worker 消费消息，执行 execute()
  │                      │
  │                      └──→ NATS Subject: agent.result.{agent_id}
  │                               │
  │                               └──→ NATS-Temporal Bridge
  │                                        │
  │                                        └──→ Workflow Signal: agent_completed()
  │
  └─ store_agent_result (Agent 结果写入 DB)
```

**关键点：**
- Agent **不直接互相调用**，全部通过 Orchestrator 调度
- Agent 产出的 artifact（`report_artifact`）通过 NATS 发布，由 K14 Knowledge Keeper 索引到知识库
- NATS-Temporal Bridge 负责把 Agent 的异步结果回传给 Workflow（Signal 机制）
- A9 的双脑内循环（Coder ↔ Auditor）是 Agent 内部闭环，不涉及 Orchestrator

---

## 六、Rework 与 Inner Loop 的数据流

### Rework（A5 不过 → 回 DESIGNING）

```
Round 0: A3 + A4 产出 → A5 评审 → pass=false, scores 低
                                            │
Round 1:     Orchestrator 回退到 DESIGNING   │
             build_context 注入 rework_context = {
               round_number: 1,
               issues: [{severity, description, suggestion}, ...],  ← A5 的具体评审意见
               scores: {ux:10, api:5, biz:5}
             }
                    │
             ┌──────┴──────┐
             ▼              ▼
            A3             A4
        prompt 追加：   API/ERD 生成时参考：
        "请重点修复       [critical] 未定义 loading 状态 → 补充三种状态 UI
         critical 和      [high] N+1 查询风险 → 使用 JOIN
         major 问题"      [high] 缺少校验规则 → 定义邮箱格式+密码强度"

Round 2: (同上，rework_count=2)
         若仍不过 → 强制推进到 DECOMPOSING（不阻塞流水线）
```

### Inner Loop（A11 测试失败 → 回 DEVELOPING）

```
A9 产出代码 → A11 测试 → 3/12 失败
                            │
                            ▼
              Orchestrator 回退到 DEVELOPING
              注入 [TEST_FAILURE_FEEDBACK] = {
                failed_tests: ["test_login_invalid_password", "test_token_expiry"],
                failures_detail: ["AssertionError: expected 401 got 500", "..."],
                coverage_pct: 72,
                errors: [...]
              }
                            │
                            ▼
                           A9
              收到失败信息 → 针对性修复 → A11 重测
              最多 2 轮，超过后强制推进
```

---

## 七、完整数据流追踪（从用户输入到代码上线）

### 7.1 端到端数据流图

```
用户提交需求（"做一个用户登录功能"）
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DRAFT → ANALYZING (A1)                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ A1 输入: context_package.message                                             │
│ A1 LLM: task_type="requirement_analysis", temp=0.3                          │
│ A1 输出: {title, domain, summary, entities, acceptance_criteria, ...}       │
│ A1 写入: spec.artifacts.A1 = {完整输出}                                      │
│ A1 发布: artifact.produced.A1                                               │
│ notify_mc: "需求分析完成，domain=auth"                                        │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Gate 0（业务确认，SLA 1h）                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Phase 1: 等待 1h                                                            │
│ Phase 2: 无 grace period                                                    │
│ Phase 3: notify_mc("gate.sla_expired") → 永久等待人工 approve              │
│ 人工审批: approve_gate("gate_0", "pm@example.com")                          │
│ store_gate_decision: spec.decisions.gate_0 = "approved"                     │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DESIGNING (A3 ∥ A4 并行)                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ build_context("designing") → artifact_context: {A1, A2}                     │
│                                                                             │
│ ┌─ A3 分支 ─────────────────────────────────────────────────────────┐      │
│ │ A3 输入: context_package.requirement_draft.{title, domain}         │      │
│ │ A3 LLM: task_type="ui_prototype", temp=0.4                         │      │
│ │ A3 输出: {html: "完整 HTML（4 种状态）", screens: 4}               │      │
│ │ A3 写入: spec.artifacts.A3 = {prototype_size, screens, html_preview}│     │
│ │ A3 发布: prototype.generated.{req_id}                              │      │
│ └────────────────────────────────────────────────────────────────────┘      │
│                                                                             │
│ ┌─ A4 分支 ─────────────────────────────────────────────────────────┐      │
│ │ A4 输入: context_package.requirement_draft.{title, domain, ac}     │      │
│ │ A4 子模块: APISchemaGenerator + ERDGenerator 并行调 LLM            │      │
│ │ A4 输出: {api_schema, erd}                                         │      │
│ │ A4 自写: spec.openapi = api_schema.schema                          │      │
│ │         spec.erd = erd_result                                      │      │
│ │ A4 版本化: api_schemas(v1), erd_designs(v1)                        │      │
│ │ A4 发布: spec.changed, api.changed                                 │      │
│ └────────────────────────────────────────────────────────────────────┘      │
│                                                                             │
│ wait_condition(A3 done AND A4 done, timeout=15min)                         │
│ store_agent_result(A3) ← 只存 A3，A4 跳过（_AGENTS_THAT_PERSIST）         │
│ notify_mc: "设计完成，等待 Gate 1 审批"                                     │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Gate 1（设计方案确认，SLA 4h + grace 1h）                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Phase 1: 等待 4h                                                            │
│ Phase 2: notify_mc("gate.sla_expired") → grace 1h                          │
│ Phase 3: notify_mc("gate.escalated") → 永久等待                             │
│ 人工审批: approve_gate("gate_1", "tech_lead@example.com")                   │
│ store_gate_decision: spec.decisions.gate_1 = "approved"                     │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ REVIEWING (A5)                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ build_context("reviewing") → artifact_context: {A1, A2, A3, A4}            │
│ A5 输入: **直接从 DB 读 spec.openapi + spec.erd**（不从 context_package）   │
│ A5 LLM: task_type="design_review", temp=0.2                                 │
│ A5 输出: {pass, scores: {ux, api, business}, issues: [...], summary}       │
│ A5 写入: spec.artifacts.A5 = {完整评审结果}                                  │
│ A5 发布: artifact.produced.A5                                               │
│ notify_mc: "设计评审完成，平均分 6.7，不通过"                                │
│                                                                             │
│ ┌─ pass=false 判断 ─────────────────────────────────────────────┐          │
│ │ rework_count < 2 → 回到 DESIGNING                              │          │
│ │   _last_a5_result = A5 完整结果                                │          │
│ │   rework_context = {round_number: 1, issues: [...], scores} │          │
│ │   重新 dispatch A3 + A4（context 中注入 rework_context）      │          │
│ │                                                                │          │
│ │ rework_count ≥ 2 → 强制推进到 DECOMPOSING                     │          │
│ └────────────────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DECOMPOSING (A6)                                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ build_context("decomposing") → artifact_context: {A1, A4, A5}              │
│ A6 输入: context_package.requirement_draft + 压缩的 spec 信息                │
│ A6 LLM: task_type="task_decomposition", temp=0.2                            │
│ A6 输出: {dag: {nodes, edges, critical_path, parallel_groups}}              │
│ A6 写入: spec.artifacts.A6 = {dag}                                          │
│ A6 发布: artifact.produced.A6                                               │
│ notify_mc: "任务拆解完成，共 7 个节点"                                        │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Gate 2（任务计划确认，SLA 4h + grace 1h）                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ （同 Gate 1 流程）                                                          │
│ store_gate_decision: spec.decisions.gate_2 = "approved"                     │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DEVELOPING (A9 双脑架构)                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ build_context("developing") → artifact_context: {A1, A4, A5, A6, A7}       │
│                             + decisions_context: {gate_0, gate_1, gate_2}  │
│ A9 输入: openapi_hint, erd_hint, dag_hint, constraints, environment         │
│                                                                             │
│ ┌─ 双脑内循环（最多 3 轮）─────────────────────────────────────┐            │
│ │ Iteration 1:                                                  │            │
│ │   CoderModule 生成代码 → lint → build → unit test             │            │
│ │   → smoke test → Docker build                                 │            │
│ │   → AuditorModule 审查 diff                                   │            │
│ │   → 不通过，反馈给 Coder 重写                                  │            │
│ │                                                                │            │
│ │ Iteration 2:                                                  │            │
│ │   Coder 根据反馈修改 → 质量门禁 → Auditor 审查                 │            │
│ │   → 通过，提交代码                                             │            │
│ └───────────────────────────────────────────────────────────────┘            │
│                                                                             │
│ A9 输出: {code_diff, commit_sha, files_changed, audit, self_test}          │
│ A9 写入: spec.artifacts.A9 = {完整输出}                                     │
│ A9 发布: artifact.produced.A9                                               │
│ notify_mc: "开发完成，提交 commit abc1234"                                   │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ TESTING (A11)                                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ build_context("testing") → artifact_context: {A4, A7, A9}                  │
│ A11 输入: context_package.code_diff（A9 变更文件列表）                       │
│ A11 LLM: task_type="test_execution", temp=0.2                               │
│ A11 输出: {total, passed, failed, pass_rate, results}                       │
│ A11 写入: spec.artifacts.A11 = {测试报告}                                   │
│ A11 发布: test.passed 或 test.failed                                        │
│ notify_mc: "测试完成，通过率 95.7% (45/47)"                                  │
│                                                                             │
│ ┌─ passed=false 判断 ───────────────────────────────────────┐              │
│ │ inner_loop_count < 2 → 回到 DEVELOPING                     │              │
│ │   _last_test_result = A11 完整结果                         │              │
│ │   注入 TEST_FAILURE_FEEDBACK = {                           │              │
│ │     failed_tests, failures_detail, coverage_pct, errors   │              │
│ │   }                                                         │              │
│ │   重新 dispatch A9                                          │              │
│ │                                                             │              │
│ │ inner_loop_count ≥ 2 → 强制推进到 REVIEWING_CODE           │              │
│ └─────────────────────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ REVIEWING_CODE (A12)                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ build_context("reviewing_code") → artifact_context: {A4, A9, A11}          │
│ A12 输入: context_package（含 A11 test_report + A9 code_diff）              │
│ A12 LLM: task_type="code_review", temp=0.1                                  │
│ A12 输出: {verdict, score, issues, auto_fix_patches, summary}               │
│ A12 写入: spec.artifacts.A12 = {完整审查结果}                                │
│ A12 发布: review.completed                                                  │
│ notify_mc: "代码审查完成，得分 85，verdict=pass"                             │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Gate 3（代码审查确认，SLA 2h）                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ （同 Gate 0 流程）                                                          │
│ store_gate_decision: spec.decisions.gate_3 = "approved"                     │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ RELEASING (A13 金丝雀发布)                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ build_context("releasing") → artifact_context: {A4, A9, A11, A12}          │
│                             + decisions_context: {gate_0~3}                 │
│ A13 金丝雀策略: 5% → 20% → 50% → 100%                                       │
│   每阶段监控 Prometheus:                                                     │
│     - 错误率 >1% → 自动回滚                                                  │
│     - p99 延迟 >500ms → 自动回滚                                             │
│ A13 输出: {release_id, stages: [{percentage, status, metrics}]}            │
│ A13 写入: spec.artifacts.A13 = {发布记录}                                   │
│ A13 发布: release.completed                                                 │
│ notify_mc: "发布完成，100% 流量已切换"                                       │
└─────────────────────────────────────────────────────────────────────────────┘
  │
  ▼
DONE（终态）
```

### 7.2 DB 数据结构演进

**初始状态（DRAFT）**：
```json
requirements: {
  id: "3ab93964-...",
  title: "用户登录功能",
  description: "...",
  source_payload: {message: "做一个用户登录功能"},
  current_state: "draft",
  spec: {},
  state_metadata: {}
}
```

**ANALYZING 完成后**：
```json
spec: {
  artifacts: {
    A1: {
      status: "completed",
      domain: "auth",
      requirement_draft: {title, domain, summary, entities, acceptance_criteria, ...}
    }
  }
}
state_metadata: {
  last_state: "analyzing",
  last_agent: "A1",
  last_notify_at: "2026-07-08T10:00:00Z"
}
```

**DESIGNING 完成后**：
```json
spec: {
  openapi: {schema: {info, paths, components}},  // A4 自写
  erd: {entities, relationships, ddl},           // A4 自写
  artifacts: {
    A1: {...},
    A3: {status: "completed", prototype_size: 8234, screens: 4, html_preview: "..."}
    // 注意：没有 A4
  }
}
```

**Gate 1 审批后**：
```json
spec: {
  decisions: {
    resolved: {gate_0: "approved", gate_1: "approved"},
    source_gates: ["gate_0", "gate_1"],
    gate_0_approved_at: "2026-07-08T10:00:00Z",
    gate_0_approver: "pm@example.com",
    gate_1_approved_at: "2026-07-08T14:30:00Z",
    gate_1_approver: "tech_lead@example.com"
  },
  ...
}
```

**DONE 最终状态**：
```json
spec: {
  openapi: {...},
  erd: {...},
  decisions: {
    resolved: {gate_0: "approved", gate_1: "approved", gate_2: "approved", gate_3: "approved"}
  },
  artifacts: {
    A1: {...}, A3: {...}, A5: {...}, A6: {...}, A9: {...}, A11: {...}, A12: {...}, A13: {...}
    // A2, A7, A8 当前为空（未调度）
    // A4 不在这里（自持久化到 spec.openapi/erd）
  }
}
```

---

## 八、已知问题与架构改进建议

| 问题 | 影响 | 状态 |
|------|------|------|
| **A3 `requirement` 变量未初始化** | title 非空时崩溃，导致 A3 100% 失败 → A4 缺 UI 产物 → A5 低分 → 触发不必要 rework | ✅ 已修复 (2026-07-08) |
| **A2 不在调度链中** | `_AGENT_STATES` 映射不含 A2，Orchestrator 从不 dispatch A2 → `spec.artifacts.A2` 始终为空 | 待修复 |
| **A7/A8 不在调度链中** | 同样不在 `_AGENT_STATES` 中，靠外部事件触发，可能不被触发 | 待确认 |
