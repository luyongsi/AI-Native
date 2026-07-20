# A9 开发 Agent 实现说明

> 源码路径：`repos/agent-workers/a9/`

## 概述

A9 是一个**"双脑架构"（Dual-Brain）的自主开发 Agent**，核心思想是**编码 + 审查严格分离**：一个"脑"负责写代码（Coder），另一个独立的"脑"负责审查代码（Auditor），两者之间信息隔离，审查者看不到编码者的内部推理过程。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `main.py` | FastAPI 搭建的 LLM 调用日志查看器（Web UI），独立于核心逻辑 |
| `a9_dev_agent.py` | **主编排器**，整个 agent 的入口和调度中心 |
| `engine.py` | **编码引擎**，封装三种 LLM 后端的统一接口 |
| `coder.py` | **编码脑**，在隔离 worktree 中生成代码 |
| `auditor.py` | **审查脑**，独立进程对 diff 做静态分析+语义审查 |
| `runtime.py` | **隔离运行时**，管理 git worktree、lint/build/test/service 等 |
| `workflow.py` | **Temporal 工作流**定义（可选，支持 Temporal 分布式编排） |
| `metrics.py` | **Prometheus 指标**，追踪编码/审查/审批率/周期时间 |
| `static_analyzer.py` | **静态分析工具**，pylint/eslint 的封装 |
| `__init__.py` | 包导出 |

---

## 核心架构

```
A9DevAgent (主编排器)
    │
    ├── A9Runtime        ← 创建隔离 git worktree 环境
    │     ├── git clone --bare → worktree add
    │     ├── lint (pylint / eslint)
    │     ├── build (compileall / tsc / go build)
    │     ├── test (pytest / jest / go test)
    │     └── start_service (smoke test)
    │
    ├── A9CodingEngine   ← 统一的编码后端（三选一）
    │     ├── ① Claude Code CLI  (优先)
    │     ├── ② Codex CLI        (备选)
    │     └── ③ Anthropic API    (兜底，单轮 JSON 模式)
    │
    └── AuditorModule     ← 独立审查（仅看 diff，不看 Coder 推理）
          ├── 静态分析 (pylint/eslint 子进程)
          └── LLM 语义审查 (安全/业务逻辑/性能/规范 四维)
```

---

## 执行流程

A9 对每个开发任务执行**最多 3 轮迭代**（通过 `max_iterations = 3` 控制）：

```
第 N 轮迭代:

  1. Engine 生成代码
     └── Claude Code CLI 非交互模式 → 解析 NDJSON 事件流
         ├── 提取文件变更、session_id、cost
         ├── 提取 spec 歧义 (Type 1，记录但继续)
         └── CLI 失败且无文件 → 自动降级到 Anthropic API

  2. Lint 检查
     └── 失败 → 格式化错误信息作为 feedback，回到步骤 1

  3. Build 检查
     └── 失败 → 回到步骤 1

  4. Unit Test
     └── 失败 → 回到步骤 1

  5. Smoke Test
     ├── 启动服务 (自动分配空闲端口)
     ├── health check (curl 轮询最多 15s)
     ├── 运行集成测试
     └── 停止服务

  6. Docker CI 构建验证
     └── 通过 NATS 请求-回复发给 A10 CI 服务
         ├── 超时/不可用 → 优雅降级，不阻塞流程
         └── 明确失败 → 回到步骤 1

  7. Auditor 审查
     ├── 静态分析 (pylint/eslint)  ∥  并行执行
     └── LLM 语义审查 (4 维度)    ∥
         │
         ├── approved → 跳出循环 ✅
         └── rejected → 格式化问题列表作为 feedback，回到步骤 1

达到最大迭代次数仍未通过 → escalated（升级人工处理）
```

### 三种执行结果

| 状态 | 含义 |
|---|---|
| `completed` | 审查通过，产出代码 diff |
| `blocked` | Type 3 阻塞性问题，不可恢复（如 LLM 不可用） |
| `escalated` | 最大迭代次数用完仍未通过，升级人工 |

---

## 关键设计决策

### 1. Coder ↔ Auditor 信息隔离

Coder 生成代码后会产出 `self_inspection`（自省推理，包含推理过程和置信度），但 Auditor **只能看到 raw diff**（文件路径、变更类型、补丁内容）。Coder 的内部思考**不会传递给 Auditor**，防止审查者被编码者的"解释"带偏。

```python
# a9_dev_agent.py: 传给 Auditor 的只有这些
diff_for_audit = {
    "files_changed": files_changed,         # 仅文件列表和 diff
    "changes_summary": engine_result.summary,  # 变更摘要
    "lint_result": lint,                     # lint 结果
    "test_result": tests,                    # 测试结果
}
# 注意：engine_result 的 self_inspection 没有传递
```

### 2. 三类异常分类处理

| 类型 | 说明 | 处理方式 |
|---|---|---|
| Type 1 歧义 | 规范不明确，Coder 自行选择了方案 | 记录并继续执行，通过 NATS 发 `spec.feedback` 消息反哺规范质量 |
| Type 2 质量问题 | lint/build/test 失败 | 格式化错误信息作为 feedback，下一轮迭代修复 |
| Type 3 阻塞 | LLM 不可用等不可恢复问题 | 立即停止，发送 `agent.escalated` 到 NATS，建议路由到 A6 |

### 3. 引擎自动降级

编码引擎优先使用 Claude Code CLI（自主编码能力最强），失败时逐级回退：

```
Claude Code CLI → (失败且无产出) → Anthropic API 单轮 JSON 模式
Codex CLI 需通过环境变量 CODEX_ENABLED=true 显式启用
```

### 4. 隔离环境

每个任务在独立 git worktree 中执行：

- 有仓库 URL → `git clone --bare` → `git worktree add` 到新分支
- 无仓库 URL（全新项目） → 创建临时目录 + `git init`
- 执行完自动清理（`finally` 块保证）
- 支持过期 worktree 批量清理（`cleanup_stale_worktrees`）

### 5. NATS 消息通信

通过 NATS 消息队列与整个 Agent 系统交互：

| 方向 | Topic | 用途 |
|---|---|---|
| 输出 | `spec.feedback` | Type 1 歧义反哺规范改进 |
| 输出 | `agent.escalated` | 升级到人工处理 |
| 请求 | `ci.build` | 向 A10 CI 构建服务请求 Docker 构建 |

### 6. 可观察性

完整的 Prometheus 指标体系（`A9Metrics`），包含：

- **Coder 指标**：迭代次数、生成耗时、文件数、代码行数、自省置信度
- **Auditor 指标**：审查次数（按 decision 分）、审查耗时、发现问题数、审查置信度
- **全局指标**：审批率、各迭代审批数、周期时间、升级次数、各阶段错误数

### 7. Temporal 可选支持

`workflow.py` 提供 Temporal 分布式工作流版本：

- `Temporal` 可用时：Coder 和 Auditor 作为独立的 Activity，Temporal 管理重试和状态
- `Temporal` 不可用时：`MockA9Workflow` 降级为直接调用 `A9DevAgent`

---

## 输入/输出格式

### 输入 (`context_package`)

```json
{
  "title": "开发任务标题",
  "note": "任务描述",
  "decisions": { "决策ID": "选中的选项" },
  "openapi_hint": { "endpoints": [...], "info": {...} },
  "erd_hint": { "tables": [...] },
  "dag_hint": { "nodes": [...], "edges": [...] },
  "environment_context": {
    "project": { "repo_url": "...", "branch": "main" }
  }
}
```

### 输出 (`report`)

```json
{
  "status": "completed|escalated|blocked",
  "code_diff": "git diff 文本",
  "files_changed": [...],
  "commit_sha": "...",
  "engine": "claude-code|anthropic-api",
  "iterations": 2,
  "audit": { "decision": "approved", "issues": [...], "confidence": 0.85 },
  "self_test": {
    "lint": { "status": "ok", "errors": 0 },
    "build": { "success": true },
    "tests": { "passed": 12, "failed": 0, "total": 12 }
  },
  "ambiguities": [...]
}
```

---

## 一句话总结

**A9 = 在隔离 worktree 中，用 Claude Code CLI 自主写代码，跑过 lint/build/test/smoke/CI 六道质量门，再由独立的 LLM 审查脑盲审 diff，最多三轮迭代，通过则产出 diff，不过则升级人工处理。**
