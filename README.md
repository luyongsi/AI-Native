# AI Native 研发协同系统 — 文档索引

## 快速导航

### 部署

[**DEPLOY.md**](DEPLOY.md) — 从零部署到 109 服务器的完整指南（首次部署、日常运维、故障排查、测试流程）

### 核心设计文档（一次性阅读，理解全局）

| 文档 | 说明 | 阅读时间 |
|------|------|----------|
| [00-总纲与导读](doc/AI-Native研发协同系统-00-总纲与导读.md) | 项目背景、核心价值、阅读路线图 | 10 min |
| [01-调研与立项报告](doc/AI-Native研发协同系统-01-调研与立项报告.md) | 行业调研、竞品分析、立项依据 | 20 min |
| [02-多Agent编排架构与设计规格](doc/AI-Native研发协同系统-02-多Agent编排架构与设计规格.md) | Agent 职责定义、状态机、协作拓扑 | 30 min |
| [03-人机协同与指挥舱产品总览](doc/AI-Native研发协同系统-03-人机协同与指挥舱产品总览.md) | Mission Control 前端、Gate 审批流程 | 20 min |
| [04-Agent协作与触发机制详规](doc/AI-Native研发协同系统-04-Agent协作与触发机制详规.md) | 事件协议、触发条件、NATS 主题规范 | 40 min |
| [05-技术栈与工程落地详规](doc/AI-Native研发协同系统-05-技术栈与工程落地详规.md) | 基础设施、部署架构、技术选型 | 40 min |

### 实施 Spec（当前迭代的工作规格）

| 文档 | 状态 | 说明 |
|------|------|------|
| [orchestrator-refactor-spec.md](doc/orchestrator-refactor-spec.md) | ✅ 已实施 | 调度收归 — Signal+wait_condition 替代 Activity 阻塞 |
| [llm-provider-audit-spec.md](doc/llm-provider-audit-spec.md) | ✅ 已实施 | LLM 调用统一 — llm-provider 加审计层 + Agent 迁移 |

### Bug 追踪

| 文档 | 说明 |
|------|------|
| [llm-provider-audit-bugs.md](doc/bugs/llm-provider-audit-bugs.md) | 端到端测试发现的 14 个 Bug（10 个 P1） |

---

## 代码仓库

```
repos/
├── agent-workers/       # 16 个 Agent (A1-A13, K14-K15, FC) + NATS-Temporal Bridge
├── orchestrator/        # Temporal Workflow 状态机 + Activities (dispatch/gate/context)
├── mc-backend/          # FastAPI 后端 (Requirements/Approvals/Chat API)
├── llm-provider/        # LLM 抽象层 (DeepSeek/Qwen/GLM/Anthropic Adapter + 审计)
├── frontend/            # Next.js 前端 (Mission Control 指挥舱)
│   ├── \              # [暂不关注] node_modules
│   └── src/
├── event-bus/           # NATS 客户端工具
├── gate-state-machine/  # Gate 状态机 (审批 + SLA)
├── infra/               # Docker Compose + 监控 (Grafana/Prometheus/Loki)
└── tests/               # 测试脚本 (trigger_req.py 等)
```

---

## 部署环境（109 服务器）

| 服务 | 地址 | 说明 |
|------|------|------|
| MC Backend API | http://172.27.78.109:8000 | FastAPI REST API |
| MC Frontend | http://172.27.78.109:3000 | Next.js 前端 |
| Temporal UI | http://172.27.78.109:8088 | Workflow 执行历史 |
| NATS | 172.27.78.109:4222 | JetStream 事件总线 |
| PostgreSQL | 172.27.78.109:5432 | 主数据库 (`ai_native`) |
| Grafana | http://172.27.78.109:3000 | 监控面板 |

**服务管理**：
```bash
# Agent Workers (systemd)
systemctl restart ai-native-agents

# MC Backend (systemd)
systemctl restart ai-native-backend

# Orchstrator (manual)
cd /opt/ai-native/repos/orchestrator && nohup python3 worker.py > /var/log/orchestrator-worker.log 2>&1 &
```

**日志**：
- Agent 日志: `/var/log/agent-workers.log`
- LLM 审计: `/opt/ai-native/logs/llm_audit.jsonl`
- Orchestrator: `/var/log/orchestrator-worker.log`

---

## 核心流程图

```
用户创建需求 → POST /api/requirements/{id}/trigger
  │
  ├─ MC Backend 启动 Temporal Workflow
  │   └─ RequirementWorkflow (DRAFT → ANALYZING → DESIGNING → ... → DONE)
  │
  ├─ Workflow 调用 dispatch_agent Activity
  │   └─ 发布 NATS: context.ready.{agent_type}
  │       └─ Agent Worker 收到消息 → execute() → 发布 agent.result.{agent_id}
  │           └─ NATS-Temporal Bridge 转发 Signal → Workflow 继续
  │
  ├─ Gate 阶段: Workflow 等待 approve_gate Signal
  │   └─ 用户在 MC 审批 → POST /api/approvals/{id}/approve
  │       └─ approvals.py 调用 handle.signal("approve_gate")
  │
  └─ Rework: A5 fail → REVIEWING 回到 DESIGNING (max 2次)
```

---

## 当前进度

| 模块 | 状态 | 备注 |
|------|------|------|
| Orchestrator 状态机 | ✅ 已完成 | 完整流程走通 DRAFT→DONE |
| Gate 0-3 审批 | ✅ 已完成 | Signal+wait_condition 模式 |
| LLM 统一审计 | ✅ 已完成 | llm-provider 集成 + JSONL 审计日志 |
| Agent 迁移 | ✅ 已完成 | 13 个 Agent 全部用 self.call_llm() |
| Rework 闭环 | 🔴 | BUG-13: 评审反馈未传递给 A3/A4 |
| Spec 数据 Schema | 🔴 | BUG-14: A4 产出结构不与 A5 输入匹配 |
| notify_mc 同步 | 🟡 | Stub 实现，需求 status 未同步到 MC |
