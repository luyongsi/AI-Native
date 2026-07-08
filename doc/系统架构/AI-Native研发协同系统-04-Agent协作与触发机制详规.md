# AI Native 研发协同系统 · Agent 协作与触发机制详规

> **文档定位**：技术负责人 / Agent 工程师
> **版本**：v3.0
> **变更说明**：以实际代码实现为基准重写，保留原 v2.0 中尚未实现但有架构价值的规划内容，标记为架构演进路线图。

---

## 〇、Agent 全景速览（当前实现）

```
用户输入 ──→ [A1] 需求分析 ──→ Gate0 人工确认 ──→ [A3∥A4] 设计并行 ──→ Gate1 人工审核
                                                        │
                                   ┌────────────────────┘
                                   ▼
                             [A5] 设计评审 ──→ 不过 ──→ 回设计重新生成（最多 2 轮）
                                   │ 通过
                                   ▼
                             [A6] 任务拆解 ──→ Gate2 人工审核
                                   │
                                   ▼
                             [A9] 编码实现 ──→ [A11] 自动化测试 ──→ 不过 ──→ 回编码修复（最多 2 轮）
                                                                        │ 通过
                                                                        ▼
                                                                  [A12] 代码审查 ──→ Gate3 人工审核
                                                                        │
                                                                        ▼
                                                                  [A13] 金丝雀发布 ──→ 完成
```

当前主流程中实际参与调度的 Agent：A1, A3, A4, A5, A6, A9, A11, A12, A13（共 9 个，其中 A3/A4 并行）。
A2、A7、A8、A10、FC 的代码已存在，但**尚未集成到 Orchestrator 主状态机**——这是当前架构与设计目标之间的主要差距。

---

## 一、核心 Agent I/O 详规（当前实现）

### 1.0 通信机制总览

所有 Agent 通过 NATS 与 Orchestrator 通信，核心 Subject 两条：

```
Orchestrator → Agent:   context.ready.{agent_type}
Agent → Orchestrator:   agent.result.{agent_id}
```

Orchestrator 通过 Temporal Workflow 的 `dispatch_agent` Activity 发布 NATS 消息，Agent Worker 消费后执行 `execute()`，执行完毕后发布结果到 `agent.result.{agent_id}`。NATS-Temporal Bridge 监听 `agent.result.*`，将结果转为 Workflow Signal `agent_completed(agent_id, result)`。

**dispatch_agent 内部路由**（`dispatch_agent.py:97-114`）：
```
agent_id → agent_type → NATS subject:
  A1 → requirement_intake    → context.ready.requirement_intake
  A2 → knowledge_analyst     → context.ready.knowledge_analyst
  A3 → ui_generator          → context.ready.ui_generator
  A4 → spec_writer           → context.ready.spec_writer
  A5 → design_review         → context.ready.design_review
  A6 → spec_decomposer       → context.ready.spec_decomposer
  A7 → test_case_generator   → context.ready.test_case_generator
  A8 → architecture_expert   → context.ready.architecture_expert
  A9 → dev_agent             → context.ready.dev_agent
  A10 → ci_cd                → context.ready.ci_cd
  A11 → test_agent           → context.ready.test_agent
  A12 → code_review          → context.ready.code_review
  A13 → release              → context.ready.release
  K14 → knowledge_keeper     → 旁路监听 artifact.produced.*
  K15 → change_propagation   → 旁路监听 spec.changed / api.changed
  FC  → fast_channel         → context.ready.fast_channel
```

**dispatch envelope 结构**（每个 Agent 收到的 context_payload）：
```json
{
  "req_id": "uuid",
  "state": "analyzing|designing|...",
  "agent_id": "A1",
  "context": "<build_context 序列化字符串，截断到 64KB>",
  "workflow_id": "wf-xxx",
  "rework_context": {},
  "requirement_draft": { "title": "...", "domain": "...", ... },
  "title": "用户认证系统",
  "description": "实现登录注册功能",
  "spec_sections": []
}
```

### 1.1 Agent 类型映射表

| agent_id | agent_type | NATS 订阅 Subject | NATS 结果 Subject |
|----------|-----------|-------------------|-------------------|
| A1 | `requirement_intake` | `context.ready.requirement_intake` | `agent.result.A1` |
| A2 | `knowledge_analyst` | `context.ready.knowledge_analyst` | `agent.result.A2` |
| A3 | `ui_generator` | `context.ready.ui_generator` | `agent.result.A3` |
| A4 | `spec_writer` | `context.ready.spec_writer` | `agent.result.A4` |
| A5 | `design_review` | `context.ready.design_review` | `agent.result.A5` |
| A6 | `spec_decomposer` | `context.ready.spec_decomposer` | `agent.result.A6` |
| A7 | `test_case_generator` | `context.ready.test_case_generator` | `agent.result.A7` |
| A8 | `architecture_expert` | `context.ready.architecture_expert` | `agent.result.A8` |
| A9 | `dev_agent` | `context.ready.dev_agent` | `agent.result.A9` |
| A10 | `ci_cd` | `context.ready.ci_cd` | `agent.result.A10` |
| A11 | `test_agent` | `context.ready.test_agent` | `agent.result.A11` |
| A12 | `code_review` | `context.ready.code_review` | `agent.result.A12` |
| A13 | `release` | `context.ready.release` | `agent.result.A13` |
| K14 | `knowledge_keeper` | `artifact.produced.*`（旁路监听） | — |
| K15 | `change_propagation` | `spec.changed`, `api.changed`（旁路监听） | — |
| FC | `fast_channel` | `context.ready.fast_channel` | — |

---

### A1 — Requirement Intake（需求分析）

**触发**：Orchestrator 在 ANALYZING 状态 dispatch → `context.ready.requirement_intake`

**输入消费逻辑**（优先级链，`a1_requirement_intake.py:46-67`）：
1. `context_package.message`
2. `context_package.msg_received.text`
3. `context_package.title` + `context_package.description` 拼接
4. `context_package.requirement_draft.title` + `.description`

**LLM 调用**：`task_type="requirement_analysis"`, temperature=0.3, max_tokens=2000
- System prompt：要求输出结构化 JSON
- 输入：原始消息文本
- 输出结构：`{title, domain, summary, entities, acceptance_criteria, tech_stack_suggestion, risk_points, priority_suggestion}`

**非 LLM 兜底**：关键词匹配（"登录"→auth、"订单"→order_management）

**返回结果**（写入 DB `spec.artifacts.A1`）：
```json
{
  "status": "completed",
  "domain": "auth",
  "entities": {"user_role": ["end_user"], "entity_name": ["user", "login_attempt"]},
  "requirement_draft": {
    "title": "用户认证系统",
    "domain": "auth",
    "summary": "实现用户注册、登录、Token 刷新功能，支持 JWT 认证",
    "entities": {...},
    "acceptance_criteria": ["用户可通过邮箱+密码注册", "用户可通过邮箱+密码登录获取 Token", "Token 过期后可使用 Refresh Token 刷新"],
    "tech_stack_suggestion": {"backend": "FastAPI", "frontend": "React", "database": "PostgreSQL"},
    "risk_points": ["密码存储需加盐哈希", "Token 泄露风险"],
    "priority_suggestion": "P1"
  },
  "source": "llm"
}
```

**发布事件**：`artifact.produced.A1`（via `report_artifact("requirement_draft")`）

**下游谁会读**：A3（title, domain）、A4（title, domain, acceptance_criteria, summary）、A5（analysis）

---

### A2 — Knowledge Analyst（知识检索，当前未在主流程调度中）

> **⚠️ 架构演进项**：代码完整（`a2_knowledge_analyst.py`），RAG 检索、Neo4j 依赖拓扑、LLM 知识融合均已实现，但 Orchestrator 的 `_AGENT_STATES` 映射中不包含 A2，导致 `spec.artifacts.A2` 始终为空。

**触发**（设计目标）：A1 输出 `requirement_draft` → Orch 调度 → `context.ready.knowledge_analyst`

**输入**：`context_package.requirement_draft`（A1 产物）→ 取 title, domain

**四阶段处理**：
1. 语义检索（pgvector）→ 相似历史需求
2. Neo4j 依赖拓扑查询（graceful fallback 若不可用）
3. 相关 PR/Issue 查询
4. LLM 知识融合 → 摘要 + 代码模式 + 风险评估 + 复杂度估算

**LLM 调用**：`task_type="knowledge_analysis"`, temperature=0.3, max_tokens=2000

**返回结果**（写入 DB `spec.artifacts.A2`）：
```json
{
  "status": "completed",
  "req_id": "uuid",
  "similar_requirements_count": 3,
  "dependencies_count": 2,
  "related_prs_count": 1,
  "quality_score": 0.85,
  "knowledge_package": {
    "analyzed_at": "2026-07-08T...",
    "similar_requirements": [{"id": "...", "title": "...", "similarity": 0.92}],
    "code_patterns": ["Pattern: auth", "Pattern: jwt"],
    "risks": [{"risk": "auth", "description": "认证变更需全面测试", "severity": "medium"}],
    "suggested_approach": "基于 3 个相似需求的分析...",
    "estimated_complexity": {"score": 0.45, "level": "medium", "estimated_days": 11},
    "dependencies": [{"service": "user-service", "downstream": ["session-service"]}]
  }
}
```

**下游谁会读**（设计目标）：A3（参考历史 UI 方案）、A4（参考历史 API/DB 设计）、A5（对比历史评审结果）

---

### A3 — UI Generator（UI 原型生成，DESIGNING 阶段与 A4 并行）

**触发**：`context.ready.ui_generator`

**输入消费逻辑**（`a3_ui_generator.py:34-46`）：
- `requirement = context_package.get("requirement", context_package.get("requirement_draft", {}))` — 始终初始化
- 从 `requirement.title` / `.req_title` fallback 标题
- 从 `requirement.domain` 取业务领域
- 若有 `rework_context.issues`，注入到 prompt 末尾

**LLM 调用**：`task_type="ui_prototype"`, temperature=0.4, max_tokens=4000
- 输入：标题 + 描述 + domain + 压缩后的 knowledge_context + rework 反馈
- 输出：`{html: "完整 HTML 代码（内联 CSS，含 default/hover/empty/error 四种状态）", description: "设计说明"}`
- Prompt 关键句：`业务领域: {requirement.get('domain', 'general')}`

**返回结果**（写入 DB `spec.artifacts.A3`）：
```json
{
  "status": "completed",
  "prototype_size": 8234,
  "screens": 4,
  "source": "llm",
  "html_preview": "<html>...(前 5000 字符)...</html>"
}
```

**额外发布**：`prototype.generated.{req_id}` NATS 事件（payload: `{agent_id, req_id, html, screens}`）

**额外订阅**：`prototype.annotated.*` — 接收前端标注后通过 LLM 生成增量 React/TSX 代码（`ui_code_patch` artifact）

---

### A4 — Spec Writer（技术规格编写，DESIGNING 阶段与 A3 并行）

**触发**：`context.ready.spec_writer`（同时支持 `event_type == "spec.ready.designing"` 从 DB 读已有 spec 后触发）

**输入消费逻辑**（`a4_spec_writer.py:164-202`）：
- 从 `context_package.requirement_draft` 取 title, domain, acceptance_criteria, summary
- 若有 `rework_context.issues`，提取为 rework_info 字符串传给 `APISchemaGenerator.generate()` 和 `ERDGenerator.generate()`
- 同时检测已有数据库表（`information_schema.tables`），支持增量 ERD

**两个子模块并行调用**：
- `APISchemaGenerator.generate(requirement_text, context={title, domain, acceptance_criteria, rework_feedback}, max_retries=3)` → OpenAPI 3.0 schema
- `ERDGenerator.generate(requirement_text, context={title, domain, rework_feedback}, existing_tables=[...], max_retries=3)` → ER 图 + DDL

**LLM 调用**：通过子模块间接调用，task_type 为 `openapi_gen` / `erd_gen`

**返回结果**（不写入 `spec.artifacts.A4`——因为 A4 是 `_AGENTS_THAT_PERSIST`，Orchestrator 跳过 `store_agent_result` 对 A4 的调用）：
```json
{
  "status": "completed",
  "api_schema": {
    "schema": {"info": {"title": "...", "version": "1.0.0"}, "paths": {"/auth/login": {"post": {...}}}, "components": {"schemas": {...}}},
    "source": "llm",
    "validation_passed": true
  },
  "erd": {
    "entities": [{"name": "users", "columns": [{"name": "id", "type": "UUID", "primary_key": true}, {"name": "email", "type": "VARCHAR(255)", "unique": true}]}],
    "relationships": [{"from": "users", "to": "sessions", "type": "one_to_many", "foreign_key": "user_id"}],
    "erd_mermaid": "erDiagram\n  users ||--o{ sessions : has",
    "ddl": "CREATE TABLE users (id UUID PRIMARY KEY, ...);",
    "source": "llm",
    "is_incremental": false
  },
  "erd_tables": 4,
  "erd_relationships": 3,
  "api_schema_valid": true,
  "api_schema_source": "llm",
  "erd_valid": true,
  "erd_source": "llm",
  "is_incremental_schema": false
}
```

**自持久化路径**（A4 独有，`_write_spec_to_db` + `_save_api_schema` + `_save_erd_design`）：
1. `requirements.spec.openapi` = api_schema_result（JSONB 根 key，A5 从此读取）
2. `requirements.spec.erd` = erd_result（JSONB 根 key，A5 从此读取）
3. `api_schemas` 独立表 — 版本化存储（含 version 字段，每次生成递增）
4. `erd_designs` 独立表 — 版本化存储（含 version、is_incremental、existing_tables 等字段）

**发布事件**：`artifact.produced.A4`（openapi_spec + erd 两个 artifact）、`spec.changed`、`api.changed`（K15 变更传播的订阅源）

**下游谁会读**：A5（评审 API + 数据结构）、A6（拆解开发任务）、A9（编码参考 openapi_hint + erd_hint）

---

### A5 — Design Review（设计评审）

**触发**：`context.ready.design_review`

**数据来源**：**直接从 DB 读** `requirements.spec`（`a5_design_review.py:67-68`）——含 A4 写入的 `openapi` + `erd`，不从 context_package 取 A4 产物。这是 A5 与其他 Agent 的关键差异。

**spec 解析逻辑**（`a5_design_review.py:74-116`）：
- `openapi_spec = spec.get("openapi", {})` → `.schema.paths`（API 路径列表）
- `erd_spec = spec.get("erd", {})` → `.entities`（表名+列定义）, `.relationships`（外键关系）
- 构建 section_text（需求描述）、openapi_text（接口清单）、erd_text（实体清单）三个文本摘要

**LLM 调用**：`task_type="design_review"`, temperature=0.2, max_tokens=3000
- 输入：需求标题 + 压缩后的上下文（A1 分析 + A3 原型 + A4 OpenAPI/ERD）
- 输出结构：
```json
{
  "ux_review": {"score": 0-100, "passed": true/false, "findings": [{"severity": "critical|major|minor|cosmetic", "heuristic": "启发式规则名", "description": "...", "suggestion": "..."}]},
  "api_review": {"score": 0-100, "passed": true/false, "findings": [{"severity": "high|medium|low", "endpoint": "路径", "risk": "N+1|性能|安全", "description": "...", "suggestion": "..."}]},
  "business_review": {"score": 0-100, "passed": true/false, "findings": [{"severity": "high|medium|low", "category": "auth|validation|error_handling|edge_case|audit", "description": "...", "suggestion": "..."}]},
  "overall_pass": true/false,
  "summary": "评审总结（100 字以内）"
}
```
- 评审维度：UX 启发式评估 + API N+1/性能检测 + 业务完整性（鉴权/校验/异常/审计）

**通过条件**（`a5_design_review.py:191`）：3 个维度中 ≥2 个 passed（score ≥ 70 per dimension），或 LLM 直接返回 `overall_pass=true`

**返回结果**（写入 DB `spec.artifacts.A5`）：
```json
{
  "status": "completed",
  "review_id": "REV-3ab93964-143052",
  "req_id": "3ab93964-...",
  "pass": false,
  "scores": {
    "ux_heuristic": {"score": 10, "passed": false},
    "api_n1": {"score": 5, "passed": false},
    "business_completeness": {"score": 5, "passed": false},
    "average": 6.7
  },
  "issues": [
    {"severity": "critical", "heuristic": "系统状态可见性", "description": "未定义 loading/error/empty 状态", "suggestion": "为每个页面补充三种状态的 UI 描述"},
    {"severity": "high", "endpoint": "/auth/login", "risk": "N+1", "description": "用户信息查询可能与 session 查询产生 N+1", "suggestion": "使用 JOIN 或批量查询"},
    {"severity": "high", "category": "validation", "description": "缺少输入校验规则", "suggestion": "定义邮箱格式、密码强度、Token 过期策略"}
  ],
  "total_issues": 8,
  "summary": "Spec 不完整，缺少 UI 交互状态和 API 错误处理定义",
  "recommendation": "需修改后重新提交评审"
}
```

**发布事件**：`artifact.produced.A5`（design_review artifact）

---

### A6 — Spec Decomposer（任务 DAG 拆解）

**触发**：`context.ready.spec_decomposer`（同时支持 `event_type == "review.completed"` 触发——检查 `pass` 状态，不通过则跳过）

**输入**：`context_package.requirement_draft` + 压缩后的上下文（A1 + A4 + A5 产物）

**LLM 调用**：`task_type="task_decomposition"`, temperature=0.2, max_tokens=4000
- 输入：需求标题 + 压缩上下文
- 输出结构：
```json
{
  "nodes": [{"id": "task-01", "type": "planning|backend|frontend|db|testing|deployment", "title": "...", "description": "...", "complexity": "low|medium|high", "estimated_hours": 4, "agent": "A1-A13", "steps": ["步骤1"]}],
  "edges": [{"from": "task-01", "to": "task-02", "type": "sequential|parallel"}],
  "critical_path": ["task-01", "task-02"],
  "parallel_groups": [{"name": "并行组名", "tasks": ["task-03", "task-04"]}],
  "total_estimated_hours": 40
}
```
- 约束：至少 5 个节点，标注并行关系，high complexity 的标记为需人工审核

**非 LLM 兜底**：关键词规则（检测 API/endpoint → backend 任务，检测 UI/前端 → frontend 任务）

**返回结果**（写入 DB `spec.artifacts.A6`）：
```json
{
  "status": "completed",
  "dag": {
    "dag_id": "dag-xxx-20260708143052",
    "nodes": [
      {"id": "task-01", "type": "db", "title": "用户表与会话表设计", "complexity": "medium", "estimated_hours": 4},
      {"id": "task-02", "type": "backend", "title": "注册接口开发", "complexity": "medium", "estimated_hours": 6},
      {"id": "task-03", "type": "backend", "title": "登录与 JWT 签发", "complexity": "high", "estimated_hours": 8}
    ],
    "edges": [{"from": "task-01", "to": "task-02", "type": "sequential"}, {"from": "task-01", "to": "task-03", "type": "sequential"}],
    "critical_path": ["task-01", "task-03"],
    "parallel_groups": [{"name": "前后端并行开发", "tasks": ["task-02", "task-05"]}],
    "total_estimated_hours": 37
  }
}
```

**发布事件**：`artifact.produced.A6`（dag artifact）

**下游谁会读**：A9（dag_hint.nodes/edges）、A7（按 DAG 节点生成测试用例）、A8（架构评审）

---

### A7 — Test Case Generator（测试用例生成，当前未在主流程调度中）

> **⚠️ 架构演进项**：代码完整，但不在 `_AGENT_STATES` 中。当前靠 NATS 事件异步触发。

**触发**（设计目标）：A6 输出 DAG → Orch 调度 → `context.ready.test_case_generator`

**输入**：DAG 节点列表 + spec（从 MC Backend API 读取）

**LLM 调用**：`task_type="test_case_gen"`, temperature=0.2, max_tokens=2000
- 按 DAG 节点生成单元测试 / 集成测试 / E2E / 视觉测试用例

**返回结果**（写入 DB `spec.artifacts.A7` + `test_assets` 表）：
```json
{
  "status": "completed",
  "test_cases": [...],
  "saved": true,
  "asset_id": "..."
}
```

**额外发布**：`test.assets_ready` NATS 事件

**下游谁会读**（设计目标）：A9（编码时参考测试用例做 TDD）、A11（测试执行时使用 A7 预生成的测试资产）

---

### A8 — Architecture Expert（架构评审，当前未在主流程调度中）

> **⚠️ 架构演进项**：代码完整，但不在 `_AGENT_STATES` 中。

**触发**（设计目标）：A6 输出 DAG → Orch 调度 → `context.ready.architecture_expert`

**输入**：DAG + 技术方案

**静态检查**（不依赖 LLM）：循环检测、分层违规检测（frontend→db 跨层调用）、DB rollback 检查

**LLM 调用**：`task_type="architecture_review"`, temperature=0.1, max_tokens=2000
- 评分 0-100，≥70 为通过
- 检查：分层合理性、循环依赖、DB 安全、性能风险

**返回结果**（写入 DB `spec.artifacts.A8`）：
```json
{
  "status": "completed",
  "review": {"score": 85, "pass": true, "issues": [...]}
}
```

**额外发布**：`review.completed` NATS 事件

---

### A9 — Dev Agent（编码实现，双脑架构）

**触发**：`context.ready.dev_agent`

**输入（context_package 核心字段）**：
```json
{
  "title": "用户认证系统",
  "note": "开发 Agent 需要基于 DAG 任务节点逐个实现",
  "openapi_hint": {"paths": {"/auth/login": ["post"], "/users/me": ["get"]}, "info": {...}},
  "erd_hint": {"tables": ["users", "sessions", "tokens"]},
  "dag_hint": {"nodes": [...], "edges": [...]},
  "environment_context": {"project": {"name": "...", "tech_stack": [...], "claude_md_content": "..."}},
  "decisions_context": {"resolved": {...}, "source_gates": [...]},
  "constraints": ["遵循现有代码规范", "不要修改数据库迁移文件"]
}
```

**双脑架构内部流程**（max 3 iterations，`a9_dev_agent.py:116-269`）：

```
A9CodingEngine 生成代码
  → lint（ESLint）
  → build（编译）
  → unit test（单元测试）
  → smoke test（冒烟测试）
  → Docker build（容器构建）
  → AuditorModule 审查 diff（仅看代码 + 环境信号，不看 Coder 思考过程）
  → 通过则 git commit + push
  → 不通过则反馈给 Engine 重写（≤3 轮）
```

**核心子模块**：
- **CoderModule** (`a9/coder.py`)：LLM 代码生成
- **AuditorModule** (`a9/auditor.py`)：静态分析 + LLM 语义审查
- **A9Runtime** (`a9/runtime.py`)：隔离 git worktree 环境
- **A9CodingEngine** (`a9/engine.py`)：CLI/API 驱动编码引擎
- **A9Metrics** (`a9/metrics.py`)：执行指标收集

**TDD 模式** (`a9_tdd_coder.py`)：注入 A7 预生成的 test_assets，指示 LLM 写出通过测试的代码

**返回结果**（写入 DB `spec.artifacts.A9`）：
```json
{
  "status": "completed",
  "code_diff": "diff --git a/src/auth/login.py ...",
  "files_changed": 5,
  "commit_sha": "abc1234",
  "session_id": "session-xxx",
  "engine": "claude-code",
  "iterations": 2,
  "audit": {"score": 85, "issues": [{"severity": "minor", "file": "auth.py:42", "description": "密码哈希未加盐", "suggestion": "使用 bcrypt"}]},
  "self_test": {"passed": 12, "failed": 0, "coverage": 0.85},
  "ambiguities": []
}
```

**额外发布**：`spec.feedback`（Spec 模糊点）、`agent.escalated`（阻塞问题）、`ci.build`（Docker 构建请求）

**Inner Loop（A9 ↔ A11）**：A11 测试不通过时，Orchestrator 回退到 DEVELOPING 状态，context 中注入 `[TEST_FAILURE_FEEDBACK]`：
```json
{
  "failed_tests": ["test_login_invalid_password", "test_token_expiry"],
  "failures_detail": ["AssertionError: expected 401 got 500", "..."],
  "coverage_pct": 72,
  "errors": ["..."]
}
```

---

### A10 — CI/CD Agent（持续集成，当前未在主流程调度中）

> **⚠️ 架构演进项**：代码存在但未集成到主流程。支持 config-driven YAML pipeline 或默认 3-step mock（build/lint/deploy，10% 模拟失败率）。

**触发**（设计目标）：A9 Push 代码 → Git Hook → `code.pushed` 事件 → Orch 调度 → `context.ready.ci_cd`

**返回结果**（写入 DB `spec.artifacts.A10`）：
```json
{
  "status": "completed",
  "staging_url": "https://staging-xxx.example.com",
  "pipeline_name": "default"
}
```

---

### A11 — Auto Test Agent（自动化测试）

**触发**：`context.ready.test_agent`

**输入**：`context_package.code_diff` / `context_package.payload.changes`（A9 的产出 → 变更文件列表）

**LLM 调用**：`task_type="test_execution"`, temperature=0.2, max_tokens=2000
- 输入：变更文件列表（path, change_type, lines_added, lines_removed）
- 输出：`{suites: [{name, type: "unit|integration|api|smoke|e2e", target_files, test_cases: [{name, input, expected, priority}]}]}`

**当前限制**：stub 实现——15% 模拟失败率。生产应接 Jest/Playwright 真实执行。

**返回结果**（写入 DB `spec.artifacts.A11`）：
```json
{
  "status": "completed",
  "total": 47,
  "passed": 45,
  "failed": 2,
  "pass_rate": 95.7
}
```

**额外发布**：`test.passed` 或 `test.failed` NATS 事件（A12 订阅 `test.passed` 触发代码审查）

**下游谁会读**：A12（通过订阅 test.passed 事件）、A9（通过 Inner Loop 机制收到测试失败反馈）

---

### A12 — Code Review Agent（代码审查）

**触发**：`context.ready.code_review`（同时**直接订阅** `test.passed` NATS 事件异步触发）

**输入**：`context_package`（含 A11 的 test_result + A9 的 code_diff/changes）

**LLM 调用**：`task_type="code_review"`, temperature=0.1, max_tokens=2000
- 输入：压缩后的代码变更上下文
- 输出：`{verdict: "pass|fail", score: 0-100, issues: [{file, line, rule, severity, description, suggestion}], positive_feedback, summary}`
- 检查项：SQL 注入、XSS、CSRF、硬编码密钥、不安全加密、空指针、未处理异常、类型安全、代码规范

**Auto-fix**：对 warning/info 级别的 issue 自动生成 patch（`auto_apply: true` 仅对 info 级别）

**返回结果**（写入 DB `spec.artifacts.A12`）：
```json
{
  "req_id": "uuid",
  "verdict": "pass",
  "score": 85,
  "issues": [{"file": "auth.py", "line": 42, "rule": "hash_without_salt", "severity": "warning", "description": "密码哈希未加盐", "suggestion": "使用 bcrypt"}],
  "auto_fix_patches": [{"file": "auth.py", "line": 42, "rule": "hash_without_salt", "auto_apply": false}],
  "positive_feedback": ["代码结构清晰", "错误处理完整"],
  "summary": "代码质量良好，建议人工复审关键安全逻辑",
  "reviewed_at": "2026-07-08T...",
  "reviewer": "A12 (LLM)"
}
```

**额外发布**：`review.completed` NATS 事件

**并发控制**：使用 `asyncio.Lock` 防止并发调用互相干扰

---

### A13 — Release Agent（金丝雀发布）

**触发**：Gate 3 通过 → Orch 调度 → `context.ready.release`

**金丝雀策略**：5% → 20% → 50% → 100%，每个阶段检查 Prometheus 指标（错误率 >1%、p99 延迟 >500ms 则回滚）

**返回结果**（写入 DB `spec.artifacts.A13`）：
```json
{
  "status": "completed",
  "release_id": "REL-xxx",
  "stages": [{"percentage": 5, "status": "completed"}, {"percentage": 20, "status": "completed"}, ...]
}
```

---

### K14 — Knowledge Keeper（知识沉淀，旁路）

**触发**：监听所有 `artifact.produced.*` NATS 事件

**处理**：将 artifact 拆分为文本 chunks → 向量化写入 pgvector `knowledge_chunks` 表

**发布事件**：无（纯旁路，不阻塞主流程）

---

### K15 — Change Propagation（变更传播，旁路）

**触发**：监听 `spec.changed` / `api.changed`（来自 A4）

**处理**：30s 防抖窗口内合并变更 → 沿依赖图追溯受影响下游 → 发布 `propagation.triggered`

---

## 二、Orchestrator 状态机与调度逻辑

### 2.1 状态定义（当前实现）

```
DRAFT → ANALYZING(A1) → Gate0 → DESIGNING(A3∥A4) → Gate1 → REVIEWING(A5)
                                  ┌──────────────────────────────────┘
                                  │ pass=false + rework<2 → 回 DESIGNING
                                  │ pass=true 或 rework≥2 → DECOMPOSING

DECOMPOSING(A6) → Gate2 → DEVELOPING(A9) → TESTING(A11)
                                  ┌─────────────────────────┘
                                  │ pass=false + inner_loop<2 → 回 DEVELOPING
                                  │ pass=true → REVIEWING_CODE

REVIEWING_CODE(A12) → Gate3 → RELEASING(A13) → DONE
```

### 2.2 Agent 状态映射（当前实现）

```python
# requirement_workflow.py:553-564
_AGENT_STATES = {
    RS.ANALYZING:      "A1",
    RS.REVIEWING:      "A5",
    RS.DECOMPOSING:    "A6",
    RS.DEVELOPING:     "A9",
    RS.TESTING:        "A11",
    RS.REVIEWING_CODE: "A12",
    RS.RELEASING:      "A13",
}
# DESIGNING 状态特殊处理：A3 和 A4 在 _run_designing_parallel() 中并行 dispatch
# 注意：A2, A7, A8, A10 不在上述映射中
```

### 2.3 DESIGNING 阶段并行调度

`_run_designing_parallel()` (`requirement_workflow.py:197-293`)：
1. 若有 `review_feedback`（来自上一轮 A5），注入 `[REWORK_FEEDBACK]` → context_str
2. `dispatch_agent(A3, context + rework_block)`
3. `dispatch_agent(A4, context + rework_block)`
4. 等待两者都完成（`wait_condition(A3 done AND A4 done OR timeout)`）
5. A3 超时 → warning 级别（非致命）；A4 超时 → error 级别；连续 2 次超时 → notify_mc 升级
6. `store_agent_result(A3)` — 只存 A3（A4 在 `_AGENTS_THAT_PERSIST` 中，跳过）

### 2.4 Gate 审批

| 触发位置 | Gate 级别 | SLA | Grace Period | 过期后行为 |
|---------|----------|-----|-------------|-----------|
| ANALYZING 之后 | Gate 0 | 1h | 无 | notify → 无限等待 |
| DESIGNING 之后 | Gate 1 | 4h | 1h | notify → grace → escalate → 无限等待 |
| DECOMPOSING 之后 | Gate 2 | 4h | 1h | 同上 |
| REVIEWING_CODE 之后 | Gate 3 | 2h | 无 | notify → 无限等待 |

Gate 永远不自动通过。`approve_gate`、`reject_gate`、`gate_timeout` 三个 Workflow Signal 控制。

### 2.5 Rework 机制（设计辩论）

```
A5 pass=false + rework_count < _MAX_REWORK(2):
  → 回到 DESIGNING 状态
  → _last_a5_result = A5 的完整评审结果
  → _run_designing_parallel() 时:
      review_feedback = _last_a5_result
      注入 rework_block = {round_number, issues: [...A5 的具体评审意见...], scores, suggestion}
  → A3 prompt 追加: "【上一轮评审反馈 — 请重点修复以下问题】"
  → A4 rework_info 传给 APISchemaGenerator / ERDGenerator

rework_count >= 2:
  → 强制推进到 DECOMPOSING（不阻塞流水线）
```

### 2.6 Inner Loop（A9 ↔ A11 测试修复）

```
A11 pass=false + inner_loop_count < 2:
  → 回到 DEVELOPING 状态
  → _last_test_result = A11 的完整测试结果
  → _run_agent_stage() 时:
      注入 [TEST_FAILURE_FEEDBACK] = {failed_tests, failures_detail, coverage_pct, errors}
  → A9 收到失败信息 → 针对性修复 → A11 重测

inner_loop_count >= 2:
  → 强制推进到 REVIEWING_CODE
```

### 2.7 Agent 超时配置

| 状态 | 超时 | 连续 2 次超时行为 |
|------|------|-----------------|
| ANALYZING | 5 min | notify_mc 升级 |
| DESIGNING | 15 min | A3=warning, A4=error → notify_mc |
| REVIEWING | 10 min | notify_mc 升级 |
| DECOMPOSING | 10 min | notify_mc 升级 |
| DEVELOPING | 4 h | notify_mc 升级 |
| TESTING | 2 h | notify_mc 升级 |
| REVIEWING_CODE | 15 min | notify_mc 升级 |
| RELEASING | 30 min | notify_mc 升级 |

---

## 三、Context Build 五层模型

Orchestrator 每次 dispatch Agent 前调用 `build_context(req_id, state)`（`context_build.py:376-468`）。

### 3.1 五层结构

| 层 | 内容 | 来源 |
|---|------|------|
| `requirement_context` | title, description, acceptance_criteria, A1 analysis, source_type | `requirements` 表 |
| `artifact_context` | **按状态选择性暴露**上游 Agent 产物 | `spec.artifacts` JSONB + `spec.openapi/erd`（A4） |
| `knowledge_context` | 按 Agent 定制搜索词检索的历史知识（分 head/mid/tail 三档） | `knowledge_chunks` 表（pgvector 全文搜索） |
| `environment_context` | 项目名、技术栈、编码规范（CLAUDE.md 前 2000 字符）、部署地址 | `.ai-native/project-config.yaml` |
| `decisions_context` | Gate 审批决策记录（仅在 developing/testing/reviewing_code/releasing 阶段包含） | `spec.decisions` JSONB |
| `rework_context` | 由 Workflow 传入（非 DB 读取） | Workflow 在 rework 时注入 |

### 3.2 按阶段的 artifact_context 选择性暴露

| 当前 state | 包含哪些上游 Agent 产物 | 数据读取方式 |
|-----------|----------------------|------------|
| `analyzing` | 无 | — |
| `designing` | A1, A2 | `spec.artifacts.A1`, `spec.artifacts.A2` |
| `reviewing` | A1, A2, A3, A4 | `spec.artifacts.A1/A2/A3` + DB `spec.openapi/erd`（A4 特殊处理） |
| `decomposing` | A1, A4, A5 | `spec.artifacts.A1/A5` + DB `spec.openapi/erd` |
| `developing` | A1, A4, A5, A6, A7 | 同上 + `spec.artifacts.A6/A7` |
| `testing` | A4, A7, A9 | DB `spec.openapi/erd` + `spec.artifacts.A7/A9` |
| `reviewing_code` | A4, A9, A11 | DB `spec.openapi/erd` + `spec.artifacts.A9/A11` |
| `releasing` | A4, A9, A11, A12 | DB `spec.openapi/erd` + `spec.artifacts.A9/A11/A12` |

### 3.3 A4 特殊处理（`context_build.py:251-280`）

A4 不在 `spec.artifacts`（因为 `_AGENTS_THAT_PERSIST` 跳过了 `store_agent_result`），context_build 从 DB 的 `spec.openapi` 和 `spec.erd` 根 key 直接读，并转换为结构化格式：

```python
artifact_context["A4"] = {
    "openapi": {
        "paths": {"/auth/login": ["post"], "/users/me": ["get"]},  # path → methods 映射
        "info": {"title": "用户认证 API", "version": "1.0.0"},
        "has_schema": True
    },
    "erd": {
        "tables": ["users", "sessions"],  # entities[].name 列表
        "relationships": [{"from": "users", "to": "sessions", "type": "one_to_many"}],
        "has_entities": True
    }
}
```

### 3.4 按阶段的知识检索关键词

| 目标 Agent | 搜索词 |
|-----------|--------|
| A1 | `需求分析 历史需求 {base}`, `问题 风险 {base}` |
| A2 | `需求 设计 {base}`, `代码 {base}`, `依赖 模块 {base}`, `最佳实践 {base}` |
| A3 | `UI原型 界面设计 {base}` |
| A4 | `API设计 数据库 ERD OpenAPI {base}`, `API Schema SQL {base}` |
| A5 | `设计评审 架构评审 安全检查清单 反模式` |
| A6 | `模块结构 项目架构 {base}`, `依赖关系 模块 {base}` |
| A9 | `代码实现 {base}`, `编码规范 错误处理 日志 安全 最佳实践`, `Bug 问题 历史缺陷 {base}` |
| A11 | `测试 测试用例 {base}`, `测试失败 常见测试问题` |
| A12 | `代码 {base}`, `代码审查 代码质量 安全` |
| A13 | `依赖 影响范围 {base}` |

其中 `{base} = f"{title} {description}"[:500]`

### 3.5 知识检索结果分层

按 relevance 分三档：
- **head**（≥0.8）：最高相关度，放在上下文窗口头部
- **mid**（0.5–0.8）：中等相关度，放在中间
- **tail**（<0.5）：低相关度，放在尾部或丢弃

### 3.6 Backward-Compatible 别名

build_context 返回的 dict 同时包含语义层字段和 Agent 代码直接使用的别名：

```python
{
    # 5 层规范字段
    "requirement_context": {...},
    "artifact_context": {...},
    "knowledge_context": {...},
    "environment_context": {...},
    "decisions_context": {...},
    "rework_context": {...},

    # Backward-compatible 别名（Agent 代码直接用这些）
    "title": requirement_context["title"],
    "spec_sections": spec.get("spec_sections", []),
    "openapi_hint": {
        "paths": artifact_context["A4"]["openapi"]["paths"],
        "info":  artifact_context["A4"]["openapi"]["info"],
    },
    "erd_hint": {
        "tables": artifact_context["A4"]["erd"]["tables"][:10],
    },
    "dag_hint": {
        "nodes": artifact_context["A6"]["nodes"][:10],
        "edges": artifact_context["A6"]["edges"][:10],
    },
    "constraints": _constraints_for_state(state),
    "note": _note_for_state(state),
}
```

### 3.7 上下文 token 预算控制

各状态的上下文 token 预算按 model_window 百分比计算（`context_build.py:67-73`）：
- 默认 model_window = 200,000 tokens
- 各状态 budget 按 `pct` 比例分配，同时受 `max` 上限约束

---

## 四、NATS 事件完整词典

### 4.1 Orchestrator ↔ Agent 核心事件

| Subject | 方向 | 载荷 | 说明 |
|---------|------|------|------|
| `context.ready.{agent_type}` | Orch → Agent | dispatch envelope（含 context, req_id, workflow_id, rework_context, requirement_draft, title, description, spec_sections） | 触发 Agent 执行 |
| `agent.result.{agent_id}` | Agent → Bridge → Orch | `{agent_id, req_id, workflow_id, result}` | Agent 执行结果（Bridge 转为 `agent_completed` Workflow Signal） |
| `agent.status.changed.{agent_id}` | Agent → MC | `{agent_id, req_id, status, message, timestamp}` | Agent 状态更新 |
| `artifact.produced.{agent_id}` | Agent → MC + K14 | `{agent_id, req_id, artifact_type, data, timestamp}` | 产物事件（K14 索引到知识库） |

### 4.2 Agent 自主发布的业务事件

| Subject | 发布者 | 载荷 | 说明 |
|---------|--------|------|------|
| `prototype.generated.{req_id}` | A3 | `{agent_id, req_id, html, screens, timestamp}` | UI 原型生成 |
| `spec.feedback` | A9 | ambiguities 信息 | 编码中发现的 Spec 模糊点 |
| `agent.escalated` | A9 | blocking issues | 编码无法解决的阻塞问题 |
| `ci.build` | A9 | Docker 构建请求 | 请求-响应模式 |
| `test.passed` | A11 | `{req_id, report, passed: true}` | 测试全部通过 |
| `test.failed` | A11 | `{req_id, report, passed: false}` | 测试有失败 |
| `review.completed` | A12 | `{verdict, score, issues, ...}` | 代码审查完成 |
| `review.completed` | A8 | 架构评审结果 | 架构评审完成 |
| `test.assets_ready` | A7 | 测试资产信息 | 测试资产就绪 |
| `pipeline.passed` | A10 | `{req_id, staging_url}` | CI 通过 |
| `pipeline.failed` | A10 | `{req_id, error_log}` | CI 失败 |
| `release.completed` | A13 | `{req_id, version, deployed_at}` | 发布完成 |
| `rollback.triggered` | A13 | `{req_id, reason, metric}` | 自动回滚 |

### 4.3 Orchestrator Workflow Signal（Gate 审批）

| Signal | 方向 | 说明 |
|--------|------|------|
| `approve_gate(gate_name, approver)` | MC → Orch | 人工审批通过 |
| `reject_gate(gate_name, reason)` | MC → Orch | 人工审批拒绝 |
| `gate_timeout(gate_level, approver)` | MC → Orch | 管理员强制跳过 Gate |
| `agent_completed(agent_id, result)` | Bridge → Orch | Agent 结果回传 |
| `agent_status(agent_id, status, message)` | Bridge → Orch | Agent 进度更新 |
| `pause()` / `resume()` | MC → Orch | 暂停/恢复工作流 |

### 4.4 旁路监听事件

| Subject | 监听者 | 说明 |
|---------|--------|------|
| `artifact.produced.*` | K14 | 索引所有产出到知识库（pgvector + Neo4j） |
| `spec.changed` / `api.changed` | K15 | 变更传播（30s 防抖窗口内合并） |
| `prototype.annotated.*` | A3 | 前端标注触发增量代码生成 |
| `test.passed` | A12 | 直接订阅触发代码审查（双重触发：Orch dispatch + 事件订阅） |
| `test.validate` | A7 | 运行时测试校验请求 |

---

## 五、DB 存储结构

所有 Agent 产出存在 `requirements` 表的 `spec` JSONB 列中：

```json
{
  "acceptance_criteria": ["验收条件1", "验收条件2"],
  "openapi": {                          // A4 自写入（_AGENTS_THAT_PERSIST 逻辑）
    "schema": {"info": {...}, "paths": {...}, "components": {...}}
  },
  "erd": {                              // A4 自写入
    "entities": [{"name": "users", "columns": [{"name": "id", "type": "UUID", "primary_key": true}]}],
    "relationships": [{"from": "users", "to": "sessions", "type": "one_to_many"}],
    "ddl": "CREATE TABLE users (...);"
  },
  "decisions": {                        // Gate 审批记录
    "resolved": {"gate_0": "approved", "gate_1": "approved"},
    "source_gates": ["gate_0", "gate_1"],
    "approved_at": "2026-07-08T12:00:00Z"
  },
  "artifacts": {                        // store_agent_result 写入（除 A4 外的所有 Agent）
    "A1": {"status": "completed", "domain": "auth", "requirement_draft": {...}},
    "A2": {"status": "completed", "knowledge_package": {...}},   // 当前始终为空（未调度）
    "A3": {"status": "completed", "prototype_size": 8234, "html_preview": "..."},
    // 注意：没有 A4！
    "A5": {"status": "completed", "pass": false, "scores": {...}, "issues": [...]},
    "A6": {"status": "completed", "dag": {"nodes": [...], "edges": [...]}},
    "A7": {"status": "completed", "test_cases": [...]},
    "A8": {"status": "completed", "review": {...}},
    "A9": {"status": "completed", "code_diff": "...", "commit_sha": "..."},
    "A10": {"status": "completed", "staging_url": "..."},
    "A11": {"status": "completed", "total": 47, "passed": 45, "failed": 2},
    "A12": {"status": "completed", "verdict": "pass", "score": 85, "issues": [...]},
    "A13": {"status": "completed", "release_id": "..."}
  }
}
```

### store_agent_result 写入逻辑（`store_agent_result.py:31-90`）

- 读取现有 `spec` → 合并 `artifacts.{agent_id}` → 写回
- 大结果（>100KB）写磁盘文件 `/opt/ai-native/data/artifacts/{req_id}/{agent_id}.json`，DB 中留 `_file_ref` 指针
- **跳过**：A4（在 `_AGENTS_THAT_PERSIST` 中）、状态为 blocked/escalated 的 Agent

### A4 额外独立表

| 表名 | 内容 | 版本化 |
|------|------|--------|
| `api_schemas` | `(req_id, schema_json, version, validation_passed, source)` | 是（每次生成 version 递增） |
| `erd_designs` | `(req_id, erd_mermaid, ddl, entities, relationships, validation_passed, is_incremental, existing_tables, version, source)` | 是 |

---

## 六、架构演进路线图（尚未实现的设计规划）

> **说明**：以下内容来自原 v2.0 设计文档，代码已有部分基础但尚未集成到主流程。每个条目标注了优先级、预估工程量、以及阻塞的前置条件。

---

### 6.1 目标架构全景图（含演进项）

```
                              ┌──→ [A2] 知识检索 ──┐
用户输入 ──→ [A1] 需求分析 ──→ Gate0 ──→ [A3] UI原型 ──→ [A4] 技术规格 ──→ [A5] 设计评审
                              │         (A3/A4 当前并行，规划改为 A3→A4 串行以利用 UI 产物)
                              │
                              ├── 设计评审(A5):
                              │    ┌ UX 启发式评审（独立 LLM 子 Agent）──┐
                              │    ├ API N+1 检测（独立 LLM 子 Agent）──┤ 并行 → 汇总打分
                              │    └ 业务完整性检查（独立 LLM 子 Agent）─┘
                              │
                              ├── Gate1 ──→ [A6] 任务拆解
                              │                ├──→ [A7] 测试用例生成（Orch 调度）
                              │                └──→ [A8] 架构评审（Orch 调度，对抗循环 ≤3 轮）
                              │
                              ├── Gate2 ──→ [A9] 编码实现 ×N 实例（双脑内循环 ≤2 轮）
                              │                └──→ [A10] CI/CD（自动触发，构建+部署 Staging）
                              │                       └──→ [A11] 自动化测试（双脑内循环 ≤2 轮）
                              │                                ├── A11 通过 → [A12] 代码审查
                              │                                └── A11 失败 → A9 修复（外部循环 ≤3 轮）
                              │
                              ├── [A12] 代码审查（跨模块影响分析 + Auto Fix Patch）
                              │
                              ├── Gate3 ──→ [A13] 金丝雀发布（5%→20%→50%→100%，自动回滚）
                              │
                              └── 旁路: [K14] 知识沉淀 ← 监听所有 artifact.produced
                                  [K15] 变更传播 ← 监听 spec.changed / api.changed
                                  [FC]  快速通道 ← 五道防线复杂度分类器
```

---

### 6.2 演进项一：A2/A7/A8/A10 集成到主状态机

**当前状态**：代码完整，worker 实例化且订阅 NATS，但 Orchestrator 从不 dispatch。

**集成方案**：

| Agent | 在哪个状态 dispatch | 触发条件 | 并行/串行 | 预估工程量 |
|-------|-------------------|---------|----------|-----------|
| A2 | ANALYZING | A1 产出 `requirement_draft` | 可在 A1 之后串行，或与 A1 并行（A2 只读 A1 的 draft） | 小（改 `_AGENT_STATES` + 新增状态或扩展 ANALYZING 逻辑） |
| A7 | DECOMPOSING | A6 产出 DAG | 与 A8 并行 dispatch | 小（扩展 `_run_agent_stage` 的 DECOMPOSING 分支） |
| A8 | DECOMPOSING | A6 产出 DAG | 与 A7 并行 dispatch | 小（同上） |
| A10 | DEVELOPING → TESTING 之间 | A9 产出 code_diff | A9 之后串行，作为 TESTING 的前置 | 中（新增状态或扩展 DEVELOPING 后的 transition） |

**推荐方案**：参考 DESIGNING 阶段的 `_run_designing_parallel()` 模式，为 DECOMPOSING 阶段实现类似的并行 dispatch（A7+A8），为 DEVELOPING 阶段增加 A10 dispatch。

---

### 6.3 演进项二：A3 → A4 串行化（A4 利用 A3 的 UI 产物生成更精准的 API/ERD）

**当前状态**：A3 ∥ A4 并行，A4 不从 A3 取 UI 产物。

**变更理由**：A3 生成的 UI 原型包含页面状态定义（default/loading/empty/error），这些状态直接映射到 A4 需要生成的 API 端点（如空状态需要分页接口、错误状态需要错误码定义）。并行模式下 A4 只能从 A1 的需求文本推导 API，质量较低。

**实现**：将 DESIGNING 阶段拆为两步：
1. A3 先执行（生成 prototype）
2. A4 再执行（context 中注入 A3 的 prototype 信息 → prompt 中追加 UI 状态→API 映射逻辑）

**风险评估**：串行会增加 DESIGNING 阶段耗时（A3 耗时 + A4 耗时，而非 max(A3, A4)），但 A3 的 HTML 生成通常较快（<2 min），整体影响可控。

---

### 6.4 演进项三：A5 子 Agent 并行化

**当前状态**：单 Agent 单次 LLM 调用，prompt 内分三个维度。

**设计目标**：三个独立 LLM 子 Agent 并行评审：
- **UX Heuristic Evaluator**：专门做 UX 启发式评估
- **API N+1 Detector**：专门做 API 性能和 N+1 检测
- **Business Completeness Checker**：专门做业务完整性检查

**优势**：
- 每个子 Agent 用更专注的 system prompt 和更低的 temperature（0.1），减少幻觉
- 并行执行，总耗时 = max(三个子 Agent)，而非串行累加
- 每个子 Agent 可以独立熔断和重试

**实现方案**：A5 内部用 `asyncio.gather` 并行调用 3 次 LLM，各自带独立的 system prompt，汇总结果时计算总分和 pass 判定（任 2/3 通过即为 pass）。

---

### 6.5 演进项四：Fast Channel 快速通道（FC Agent 集成）

**当前状态**：FC Agent（`fast_channel_classifier.py`）代码完整，配置了五道防线分类器，但 Orchestrator 在 DRAFT 状态时未调用分类器。

**设计架构**（原 v2.0 §十一）：五道防线按序执行，任一道未通过即回退完整通道：
1. **防线 0 — 来源信誉**：飞书来源/角色/紧急标记
2. **防线 1 — 文本语义**：关键词 + 否定语义 + 非功能性暗语检测
3. **防线 2 — 代码影响探测**：symbol index 搜索 → 传播半径分析（≤200ms）
4. **防线 3 — 知识库快查**：微型冲突检测（≤500ms）
5. **防线 4 — 历史误判库**：embedding 相似度匹配 + 文件级误判历史

快速通道状态机（跳过 DESIGNING/REVIEWING/DECOMPOSING/REVIEWING_CODE）：
```
DRAFT → FAST_PASS → DEVELOPING(A9 轻量模式) → TESTING(A11 轻量模式) → RELEASING(A13 原地更新) → DONE
```

**动态降级哨兵**：快速通道执行中，A9/A11/A12 任一发现影响面超预期 → `DOWNGRADE_TO_FULL` → 切回完整通道。

**预估工时**：大（需扩展状态机、Orchestrator DRAFT 阶段逻辑、A9/A11/A12 轻量模式实现）

---

### 6.6 演进项五：Context Builder 高级特性

**当前状态**：基本 5 层模型已实现，但缺少高级上下文管理。

**规划特性**：
- **Lost-in-the-Middle 排序**：高相关度→头部，次高相关度→尾部，中等→中间（仅剩余预算时放入）
- **上下文压缩**：代码片段保留函数签名+关键逻辑+注释（删实现体），知识片段 LLM 摘要压缩
- **上下文清理（Sanitization）**：连续失败 ≥2 次时清空所有推理痕迹，只保留原始 Spec + 最新失败日志
- **隔离判定（Isolate）**：填充率 >50% 建议拆分子 Agent，>75% 强制 compact
- **Write 策略**：超预算内容写入外部存储，附指针供 Agent 按需拉取

---

### 6.7 演进项六：Agent Skills API 规范

以下 Skills API 签名来自原 v2.0 设计文档 §七，作为 A3/A4/A7/A9/A11/A12 内部子模块的接口契约标准：

**A3（UI Generator）调用**：
- `Design_Token_Mapper(mapped_jsx)` — 企业 Design Token 映射
- `Interactive_Prototype_Builder(mapped_jsx, states, device_presets)` — 可交互原型构建

**A4（Spec Writer）调用**（当前 `APISchemaGenerator` / `ERDGenerator` 的规范化接口）：
- `API_Schema_Generator(prototype_states, entities, existing_apis)` → OpenAPI 3.1 完整规范
- `ERD_Designer(entities, api_spec, existing_ddl)` → Mermaid ER 图 + DDL + Migration Notes

**A9（Dev Agent）调用**（当前 `CoderModule` / `AuditorModule` 的规范化接口）：
- `Codebase_Context_Retriever(task_spec, repo_path, max_tokens)` → 相关代码片段 + 依赖图
- `Static_Analysis_Runner(files, rules)` → Lint/TS 错误列表
- `Security_Scanner(files, rules)` → 安全漏洞列表
- `Architecture_Rules_Checker(diff, rules_profile)` → 架构红线违规列表

**A11（Test Agent）调用**（当前 stub 实现的规范化接口）：
- `Test_Runner(staging_url, test_suite, parallel)` → 执行结果 + 失败详情 + 覆盖率
- `Log_Analyzer(failed_cases, source_code)` → 失败根因分析 + 修复建议
- `Assertion_Mutation_Checker(test_files, source_files)` → 变异得分 + 弱断言检测

**A12（Code Review Agent）调用**：
- `Cross_Module_Impact_Analyzer(diff, dependency_graph)` → 跨模块影响分析
- `Auto_Fix_Patcher(issues, source_code)` → 自动修复补丁生成

---

### 6.8 演进项七：可观测性（OpenTelemetry）

**当前状态**：base_worker 中有 OTel 集成的基础设施（la lazy import, tracer init），但未在全系统铺开。

**规划**：
- **Traces**：每个 Agent 执行一个 Root Span，内部步骤（context.build → think → tool_call → code_gen → commit）为 Child Span
- **跨 Agent 链路**：通过 NATS Event 中传播 W3C Trace Context（Span Link，非父子关系）
- **Metrics**：`agent_executions_total`, `agent_execution_duration_seconds`, `agent_token_usage_total`, `loop_rounds_total`, `loop_tripped_total`, `context_fill_percentage`
- **告警规则**：AgentLoopTripped, AgentExecutionFailureRate(>10%), ContextFillHigh(P95>75%), AgentStuck(>5min), ToolFailureSpike(>3/5min)

---

### 6.9 演进项八：Mission Control 测试工作台集成

**规划交互能力**：
- 人编辑测试 → A7 校验（边界 + 去重检查）
- 人请求 AI 补全边界用例 → A7 分析缺失边界 → 生成 supplementary cases
- 人点击强化弱断言 → A7 生成加强版断言 → A11 做变异验证
- 测试就绪评审状态机（not_started → in_review → approved/rejected）
- 测试质量雷达图（边界覆盖 / 断言质量 / 变异得分 / 去重 / 稳定性），每维度可点击下钻到具体用例

---

### 6.10 演进项优先级排序

| 优先级 | 演进项 | 理由 |
|--------|--------|------|
| **P0** | A2 集成到 ANALYZING 阶段 | 知识检索是下游 Agent（A3/A4/A5）高质量产出的基础，当前 A2 完全不运行导致整条链路质量下降 |
| **P0** | A7 集成到 DECOMPOSING 阶段 | A9 TDD 模式和 A11 测试执行都依赖 A7 产出的测试资产 |
| **P1** | A3 → A4 串行化 | 让 A4 利用 A3 的 UI 产物提升 API/ERD 质量，直接改善 A5 评分 |
| **P1** | A10 集成到 DEVELOPING→TESTING 之间 | CI/CD 是代码进入测试的前提，缺少则 A11 没有 Staging 环境运行 |
| **P1** | A8 集成到 DECOMPOSING 阶段 | 架构评审是防止高风险代码进入开发的关键门禁 |
| **P2** | A5 子 Agent 并行化 | 提升评审质量和速度，但当前单 Agent 模式可工作 |
| **P2** | Context Builder 高级特性 | 上下文管理是 Agent 质量的隐性瓶颈，但需要实际运行数据来校准压缩/排序参数 |
| **P3** | Fast Channel 快速通道 | 提效显著但需前面各项稳定后再加入（防滥用机制复杂） |
| **P3** | OpenTelemetry 全链路 | 可观测性是生产运维基础，但可在核心流程稳定后再铺开 |

---

## 七、实施建议

1. **优先打通的修复**：A2（知识检索）和 A7（测试生成）是当前最关键的缺失环节，直接影响产出质量。修改量小（在 `_AGENT_STATES` 映射和相关 transition 中加调度逻辑），收益大。

2. **DESIGNING 阶段改进**：当前 A3∥A4 并行虽快，但 A4 缺乏 UI 产物导致 ERD columns 为 0。建议先改为 A3→A4 串行，待 A4 利用 UI 产物逻辑稳定后再考虑是否恢复并行。

3. **A5 评审基准**：当前 A5 的 fallback 评审给空 spec 打出 75 分（含 path/entities 时），需要校准阈值——空 spec 应为 0 分，防止劣质 spec 通过评审。

4. **A11 stub 替换**：当前 15% 模拟失败率在生产不可用。需要接入真实 Jest/Playwright 执行引擎，并接入 A7 预生成的测试资产。

5. **A9 超时**：DEVELOPING 阶段超时设为 4h，但 A9 内部 max 3 次迭代无总时长限制。建议内部加迭代级别的超时（如每次迭代 ≤30min）。
