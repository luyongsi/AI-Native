# 收尾工作与待办 — AI Native 研发协同系统

> 基于代码审计（agent-workers + orchestrator）与原始设计文档的差异分析

---

## 一、Agent 实现状态

| Agent | 名称 | LLM 调用 | 状态 | 说明 |
|-------|------|----------|------|------|
| A1 | Requirement Intake | ✅ `self.call_llm()` | **完成** | 需求分析 + JSON 输出 |
| A2 | Knowledge Analyst | ✅ `self.call_llm()` | **完成** | 知识检索 + PR 查询 |
| A3 | UI Generator | ✅ `self.call_llm()` | **完成** | HTML 原型生成 |
| A4 | Spec Writer | ✅ `self.call_llm()` | **完成** | OpenAPI + ERD 生成（子模块注入） |
| A5 | Design Review | ✅ `self.call_llm()` | **完成** | 三维度评审（UX/API/业务） |
| A6 | Spec Decomposer | ✅ `self.call_llm()` | **完成** | DAG 任务拆分 |
| A7 | Test Case Generator | ✅ `self.call_llm()` | **完成** | 测试用例生成 |
| A8 | Architecture Expert | ✅ `self.call_llm()` | **完成** | 架构评审 |
| A9 | Dev Agent | ⚠️ Stub | 需升级 | ClaudeCodeBridge 存在但用 sleep 模拟结果 |
| A10 | CI/CD Agent | ⚠️ Stub | 需升级 | 全部步骤 sleep 模拟（构建/部署） |
| A11 | Test Agent | ⚠️ Stub | 需升级 | 有 LLM 分析但执行逻辑为 stub |
| A12 | Code Review | ✅ `self.call_llm()` | **完成** | 代码审查 |
| A13 | Release Agent | ⚠️ Stub | 需升级 | Canary 部署用 sleep 模拟 |
| FC | Fast Channel | ✅ `self.call_llm()` | **完成** | 复杂度分类（5 道防线未建） |
| K14 | Knowledge Keeper | ⚠️ Stub | 需升级 | pgvector 存储但无 LLM 内容增强 |
| K15 | Change Propagation | ⚠️ Stub | 需升级 | 30s 消抖监控但无依赖图追溯 |

**统计**：8/16 完成 LLM 迁移、8 个仍需升级

---

## 二、Orchestrator 状态

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| RequirementWorkflow | workflows/requirement_workflow.py | ✅ 完成 | 12 状态机 + Gate 0-3 + rework |
| dispatch_agent | activities/dispatch_agent.py | ✅ 完成 | NATS 发布 context.ready |
| create_gate_approval | activities/gate_await.py | ✅ 完成 | Gate 记录创建 |
| build_context | activities/context_build.py | ⚠️ 简化版 | 从 DB 读 spec，但上下文丰富度不足（不含评审历史、历史产物） |
| notify_mc | activities/notify_mc.py | ⚠️ Stub | 只发 NATS "orchestrator.state"，不更新 MC Backend DB |
| complexity_classifier | activities/complexity_classifier.py | ⚠️ 有限 | LLM 调用存在，但未被 Workflow 调用 |
| embedding_index | activities/embedding_index.py | 🟡 未使用 | 后台索引任务 |
| Circuit Breaker | circuit_breaker/ | 🟡 未接入 | Loop tracker/sanitizer/model_selector 存在但 Workflow 未用 |

---

## 三、未实现功能清单

### P0：Stub 替换（Agent）

| # | 功能 | 来源 Spec | 说明 |
|---|------|-----------|------|
| 1 | A9 Dev Agent 真实 LLM | spec-15 | 将 ClaudeCodeBridge 的 `_execute_with_llm` 结果用于实际代码生成而非 mock 返回 |
| 2 | A10 CI/CD 真实 pipeline | spec-16 | 替换 sleep 为真实 Docker build + lint + deploy staging |
| 3 | A11 Test Agent 真实执行 | spec-02 | 替换 `tester_fallback.py` 为 VisAgent HTTP 调用 或 真实测试执行 |
| 4 | A13 Release Agent 真实发版 | spec-30 | 真实 canary 流量切换（Prometheus 指标检查） |
| 5 | K14 Knowledge Keeper LLM 增强 | spec-27 | 用 LLM 对 artifact 做摘要/向量化再写入 pgvector |
| 6 | K15 Change Propagation 依赖图 | spec-28 | 接入 Neo4j 图数据库做影响面分析，而非仅消抖 |

### P1：Orchestrator 补全

| # | 功能 | 说明 |
|---|------|------|
| 7 | `notify_mc` 真实现 | 调 MC Backend API `PUT /api/requirements/{id}` 更新 `status` 和 `stages` |
| 8 | `build_context` 丰富化 | 注入历史产物（A1 草案、A3 原型、A4 OpenAPI/ERD、A5 上次评审结果）而非仅当前 spec |
| 9 | Gate SLA 升级 | 超时自动升级：Gate 超时 → 自动通知 + 降级处理（spec-26） |
| 10 | Circuit Breaker 接入 | loop_tracker 防死循环、model_selector 自动降级模型（spec-12） |

### P2：集成链路

| # | 功能 | 说明 |
|---|------|------|
| 11 | Chat → Agent 桥接 | 聊天 `_extract_spec_from_reply` 更新 spec 后自动 trigger Orchestrator |
| 12 | WebSocket 实时推送 | 前端实时看到 Agent 执行状态（`ws/ws_gateway.py` 存在但 403 拒绝） |
| 13 | Fast Channel 5 道防线 | 简单需求 15min 快速通道（spec-11）— 分类器已实现但未走快速路径 |

### P3：远期（按需）

| # | 功能 | 说明 |
|---|------|------|
| 14 | Observability 全量 | Grafana Tempo/Loki/Mimir 全链路追踪 + 指标（spec-32） |
| 15 | Neo4j 知识图谱 | 跨仓库依赖追溯（spec-33） |
| 16 | Firecracker Sandbox | 从 Docker 迁移到 microVM（spec-34） |
| 17 | MCP Gateway | 统一工具注册网关（spec-14） |
| 18 | 金丝雀真实发版 | 真实流量切换 + Prometheus 指标 → 自动回滚（spec-30） |

---

## 四、Bug 修复进度

| Bug ID | 标题 | 状态 |
|--------|------|------|
| BUG-01 | A1 双调用 | ✅ 已修复（=BUG-08 根因） |
| BUG-02 | workflow_id 为空 | ✅ 已修复 |
| BUG-03 | 审计日志缺内容采样 | ✅ 已修复 |
| BUG-05 | API Key 缺失 | 🟢 workaround |
| BUG-06 | model 字段为 null | ✅ 已修复 |
| BUG-08 | A3/A4 重复触发 | ✅ 已修复 |
| BUG-09 | A4 req_id=UNKNOWN | ✅ 已修复 |
| BUG-10 | erd_gen 0 chars | ✅ 已修复 |
| BUG-12 | A5 评分全 0 | ✅ 已修复 |
| BUG-13 | Rework 无反馈 | ✅ 已修复 |
| BUG-14 | Spec 结构不匹配 | ✅ 已修复 |
| BUG-07 | notify_mc Stub | 🟡 待办 P1 |
| BUG-11 | 进程重复 | 🟡 操作规范 |

---

## 五、文档结构

```
README.md                           ← 当前文件
doc/
├── 00-总纲与导读.md                ← 核心设计（5 份）
├── 01-调研与立项报告.md
├── 02-多Agent编排架构与设计规格.md
├── 03-人机协同与指挥舱产品总览.md
├── 04-Agent协作与触发机制详规.md
├── 05-技术栈与工程落地详规.md
├── orchestrator-refactor-spec.md   ← 已实施 Spec（2 份）
├── llm-provider-audit-spec.md      ← 已实施 Spec
├── remaining-work.md               ← 本文件（待办清单）
└── bugs/
    └── llm-provider-audit-bugs.md  ← Bug 追踪（14 条）
```
