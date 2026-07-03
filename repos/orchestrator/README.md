# orchestrator — Temporal 工作流编排引擎

基于 Temporal 的需求状态机 + DAG 调度 + 三级熔断引擎。

## 架构

```
Temporal Workflow (RequirementWorkflow)
├── 状态机: draft → analyzing → designing → ... → done/blocked
├── 快速通道: complexity=simple → fast_* 状态
├── Gate 审批: await_gate_approval (含 SLA 超时)
├── 熔断引擎: inner≤2 / outer≤3 / debate≤3
├── DAG 调度: dispatch_parallel
└── Context Builder: build_context Activity
```

## 快速开始

```bash
cd orchestrator
pip install temporalio nats-py asyncpg
python worker.py
# 输出: "Temporal Worker started on task queue: orchestrator-task-queue"
```

## 关键模块

| 模块 | 文件 | 功能 |
|---|---|---|
| 状态机 | `state_machine/` | 12 个状态 + 转移表 |
| Workflow | `workflows/` | 主流程 + 快速通道 + DAG 分发 |
| Activity | `activities/` | Agent 下发 + Gate 等待 + 上下文构建 |
| 熔断 | `circuit_breaker/` | 循环计数 + 策略升级 + 上下文清理 |
| Gate | `gate_state.py` | Gate 状态机 + 审批表 CRUD |
| 复杂度 | `complexity/classifier.py` | 五道防线分类器 |

## 依赖

- Temporal Server 1.24+
- NATS JetStream
- PostgreSQL

## 关联 Spec

spec-12 · Orchestrator 状态机 · spec-26 · Gate 引擎
