# agent-workers — 15 个 Agent Worker 实现

AI Native 研发协同系统全部核心 Agent 的 Python 实现。

## Agent 清单

| # | Agent | 文件 | 触发事件 | 状态 |
|---|---|---|---|---|
| 1 | Requirement Intake | `a1_requirement_intake.py` + `a1_upgrade.py` | `msg_received` | stub |
| 2 | Knowledge Analyst | `a2_knowledge_analyst.py` | `requirement.drafted` | stub |
| 3 | UI Generator | `a3_ui_generator.py` | `gate.0.approved` | stub |
| 4 | Spec Writer | `a4_spec_writer.py` | `gate.0.approved` | stub |
| 5 | Design Review Panel | `a5_design_review.py` | `spec.submitted` | stub |
| 6 | Spec Decomposer | `a6_spec_decomposer.py` | `gate.1.approved` | stub |
| 7 | Test Case Generator | `a7_test_case_generator.py` | `dag.created` | stub |
| 8 | Architecture Expert | `a8_architecture_expert.py` | `dag.created` | stub |
| 9 | Dev Agent | `a9_dev_agent_stub.py` + `a9_claude_code_bridge.py` | `gate.2.approved` | mock→Claude CLI |
| 10 | CI/CD Agent | `ci_agent.py` | `code.pushed` | mock |
| 11 | Auto Test Agent | `a11_test_agent_stub.py` | `pipeline.passed` | stub |
| 12 | Code Review Agent | `a12_code_review.py` | `test.passed` | stub |
| 13 | Release Agent | `release_agent.py` | `gate.3.approved` | stub |
| K14 | Knowledge Keeper | `k14_knowledge_keeper.py` | `artifact.produced` | stub |
| K15 | Change Propagation | `k15_change_propagation.py` | `spec.changed` / `api.changed` | stub |

## 快速开始

```bash
cd agent-workers
pip install temporalio nats-py httpx pydantic
python worker_launcher.py
```

## 基类

`base_worker.py` 提供 `BaseAgentWorker` 抽象基类，封装 NATS 连接、事件发布、Temporal Activity 注册。

所有 Agent stub 目前为 mock 实现，后续逐步接入真实 LLM / Claude Code / Playwright。

## 关联 Spec

spec-15/16/20~25/27/28/30/31 · 多个 Agent Spec
