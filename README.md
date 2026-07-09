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
| [04-Agent协作与触发机制详规](doc/系统架构/AI-Native研发协同系统-04-Agent协作与触发机制详规.md) | 事件协议、触发条件、NATS 主题规范 | 40 min |
| [05-技术栈与工程落地详规](doc/AI-Native研发协同系统-05-技术栈与工程落地详规.md) | 基础设施、部署架构、技术选型 | 40 min |
| [系统状态机与信息流设计](doc/系统状态机与信息流设计.md) | **权威基线 v2.4** — 全流程 Mermaid 图、Agent/Gate 节点定义、事件协议 | 30 min |

### 实施 Spec（当前迭代的工作规格）

| 文档 | 状态 | 说明 |
|------|------|------|
| [系统状态机与信息流设计](doc/系统状态机与信息流设计.md) | ✅ v2.4 | **权威基线** — 完整流程、17节点定义、33事件协议、循环计数器规则 |
| [Orchestrator完整规格](doc/系统架构/Orchestrator完整规格.md) | ✅ v1.1 | 五层上下文、分层压缩、8个Task的实施规格 |
| [llm-provider-audit-spec.md](doc/系统架构/LLM-Provider审计规格.md) | ✅ 已实施 | LLM 调用统一 — llm-provider 加审计层 + Agent 迁移 |

### Agent 规格

| 文档 | 状态 | 说明 |
|------|------|------|
| [A1-需求分析Agent完整设计](doc/Agent规格/A1-需求分析Agent完整设计.md) | ✅ | 多轮对话、需求草案、验收标准、线框图 |
| [A2-知识分析Agent规格](doc/Agent规格/A2-知识分析Agent规格.md) | ✅ | 知识库检索、可行性评估、冲突识别 |
| [A9-开发Agent实现说明](doc/Agent规格/A9-开发Agent实现说明.md) | ✅ | Claude Code SDK、双脑架构 |
| [A10-CI-CD-Agent改造规格](doc/Agent规格/A10-CI-CD-Agent改造规格.md) | ✅ | Sandbox部署、NATS+MCP双模式 |
| [Agent规格目录](doc/Agent规格/README.md) | 📋 | 全部Agent状态清单与编写优先级 |

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
用户创建需求 → A1 多轮对话(HTTP+SSE)
  │
  ├─ 阶段一：需求分析
  │   A1 产出需求草案+验收标准 → A2 知识分析+可行性评估 → Gate0 产品审批
  │   Gate0 reject → 回到 A1 修订
  │
  ├─ 阶段二：设计
  │   A3 高保真原型 → A4 Spec+OpenAPI+ERD+DDL → A5 自动设计检查 → Gate1 产品审批
  │   Gate1 reject → 回到 A4 修订（A3不自动返工）
  │
  ├─ 阶段三：技术准备
  │   A6+DAG架构设计 ∥ A7 测试用例生成 → Gate2 架构师审批
  │   Gate2 reject → 回到 A6+A7 修订
  │
  └─ 阶段四：开发→测试→审查 循环
      A9 代码开发 → A10 Sandbox部署 → A11 自动化测试 → A12 Code Review → ✅ 完成
      A11 失败 ≤5轮 → 自动回 A9   |  >5轮 → Gate3 人工判断
      A12 不通过 ≤3轮 → 自动回 A9  |  >3轮 → Gate4 人工判断
```

---

## 当前进度

| 模块 | 状态 | 备注 |
|------|------|------|
| 系统设计基线 | ✅ v2.4 | 《系统状态机与信息流设计》— 17节点、33事件、4阶段完整流程 |
| Orchestrator 状态机 | ✅ 已完成 | 完整流程走通 DRAFT→DONE |
| Gate 0-4 审批 | ✅ 已设计 | Gate0-2 已实现，Gate3-4 待实施 |
| LLM 统一审计 | ✅ 已完成 | llm-provider 集成 + JSONL 审计日志 |
| Agent 迁移 | ✅ 已完成 | 13 个 Agent 全部用 self.call_llm() |
| A2 调度接入 | 🔴 | 当前不在主状态机链路中，待接入 |
| A7 调度接入 | 🔴 | 已实现但未调度，待接入 PARALLEL_A6_A7 阶段 |
| notify_mc 同步 | 🟡 | Stub 实现，需求 status 未同步到 MC |
| A10 CI/CD部署 | 🟡 | 待从TDD Coder改造为CI/CD部署Agent |
