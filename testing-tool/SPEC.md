# Testing Tool 规格文档

## 1. 概述

Testing Tool 是 AI Native Pipeline 的端到端测试与可观测性平台。它通过 Web Dashboard 和 CLI 两种界面，提供需求创建、流水线触发、实时状态监控、结果验证和历史查询的完整闭环。

**核心能力：**
- 通过 MC Backend 创建测试需求并触发 Temporal 工作流
- 三通道观测引擎（NATS 消息、DB 轮询、Temporal 进度查询）
- 实时 SSE 推送流水线状态到 Web Dashboard
- 基于 Truth Spec 的自动化运行时验证（10 项检查）
- 测试数据自动清理（含孤儿数据恢复）

**技术栈：** FastAPI + SSE + NATS JetStream + asyncpg + Temporal + DeepSeek LLM

---

## 2. 架构

```
┌─────────────────────────────────────────────────┐
│                 Web Dashboard                    │
│            (static/index.html)                   │
│         SSE EventSource 接收实时事件              │
└─────────────────┬───────────────────────────────┘
                  │ HTTP + SSE
┌─────────────────▼───────────────────────────────┐
│              FastAPI Server (server.py)           │
│  POST /api/tests/run    触发测试                  │
│  GET  /api/tests/stream/{run_id}  SSE 流         │
│  GET  /api/tests/status  基础设施状态             │
│  POST /api/cleanup      数据清理                  │
│  GET  /api/diagnose/{req_id}  需求诊断            │
└──────┬──────────┬──────────┬────────────────────┘
       │          │          │
       ▼          ▼          ▼
┌──────────┐ ┌──────┐ ┌──────────┐
│Pipeline  │ │ DB   │ │ Temporal │
│Observer  │ │Poller│ │ Poller   │
└────┬─────┘ └──┬───┘ └────┬─────┘
     │          │          │
     ▼          ▼          ▼
┌─────────────────────────────────────────────────┐
│              RuntimeVerifier                     │
│  10 项运行时检查 (基于 truth-spec.yaml)           │
└─────────────────────────────────────────────────┘
```

### 2.1 三通道观测引擎 (PipelineObserver)

| 通道 | 机制 | 频率 | 采集数据 |
|------|------|------|----------|
| NATS | JetStream 订阅 `context.ready.>` 和 `agent.result.>` | 实时 | Agent 上下文输入、执行结果 |
| DB 轮询 | `SELECT status, spec FROM requirements` | 每 3s | 状态变更、spec 快照 |
| Temporal | `get_progress` 查询 | 每 5s | 工作流进度、终止检测 |

---

## 3. 文件结构

```
testing-tool/
├── server.py                  # FastAPI 主服务 (8500 端口)
├── cli.py                     # CLI 入口 (run/diagnose/infra/cleanup/export)
├── observer.py                # 三通道流水线观测器
├── preflight.py               # 启动前基础设施就绪检查
├── cleanup.py                 # 测试数据清理 (DB + worktree + LLM logs)
├── truth-spec.yaml            # 业务逻辑契约 (状态机、Agent、Gate、数据流)
├── infra-baseline.yaml        # 基础设施连接配置
├── requirements.txt           # Python 依赖
├── pytest.ini                 # Pytest 配置 (unit/db/integration/slow)
├── static/
│   └── index.html             # Web Dashboard 单页应用
├── checks/
│   ├── __init__.py
│   ├── infra.py               # 基础设施健康检查 (PG/NATS/Temporal/LLM/Redis/Bridge)
│   ├── runtime_verifier.py    # 运行时验证器 (10 项检查)
│   └── truth_spec_self_check.py  # Truth Spec 自洽性校验
├── utils/
│   ├── __init__.py
│   ├── db.py                  # asyncpg 连接池 + CRUD
│   ├── mc_client.py           # MC Backend HTTP 客户端
│   └── temporal_client.py     # Temporal 客户端
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # 添加 repos/agent-workers 到 sys.path
│   ├── unit/
│   │   ├── test_a1_agent.py   # A1 Agent 单元测试 (T-AG-001 ~ T-AG-016)
│   │   └── test_draft_builder.py  # DraftBuilder 流式解析测试 (T-PR-001 ~ T-PR-007)
│   └── integration/
│       ├── test_db_schema.py      # DB Schema 测试 (T-DB-001 ~ T-DB-016)
│       └── test_api_dialogue.py   # API 对话测试 (T-API-001 ~ T-API-008)
└── tools/
    └── archive/                # 历史工具脚本 (已归档)
```

---

## 4. API 接口

### 4.1 测试执行

**`POST /api/tests/run`**
- **请求体：**
  ```json
  {
    "title": "需求标题 (必填)",
    "description": "需求描述 (可选)",
    "gate_strategy": "auto | manual (默认 auto)",
    "keep_data": false,
    "timeout_minutes": 120
  }
  ```
- **响应：** `{ ok, run_id, req_id, workflow_id, gate_strategy }`
- **流程：** 预检 → 创建 Requirement → 触发 Workflow → 启动 Observer → 返回 run_id

### 4.2 SSE 实时流

**`GET /api/tests/stream/{run_id}`**
- 返回 `text/event-stream`，事件类型：
  - `checkpoint` — Agent 上下文构建/执行完成
  - `finding` — 运行时验证发现的问题
  - `state-change` — 需求状态变更
  - `gate-approved` — Gate 自动审批
  - `run-complete` — 测试完成 (含 final_state, total_duration_s, findings_count)
  - `run-error` — 测试异常
  - `ping` — 心跳 (30s 超时)

### 4.3 查询接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tests/results/{run_id}` | 查询运行结果 (含完整 timeline + findings) |
| GET | `/api/tests/history` | 最近 50 条运行历史 |
| GET | `/api/tests/status` | 基础设施状态缓存 (60s 刷新) |
| GET | `/api/tests/derived-config` | 解析后的 Truth Spec 配置 |
| GET | `/api/diagnose/{req_id}` | 需求快照诊断 (不触发 Agent) |

### 4.4 清理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/cleanup` | 清理全部测试数据 |
| POST | `/api/cleanup/{req_id}` | 清理单个需求 (含 Temporal 终止) |
| GET | `/api/cleanup/stats` | 清理统计 (测试需求数、worktree 占用) |

---

## 5. Web Dashboard

### 5.1 布局

```
┌──────────────────────────────────────────────┐
│ 标题行 + 服务器信息                            │
├──────────────────────────────────────────────┤
│ 状态栏: [Spec ✓] [Infra ✓] [NATS ✓] [Idle]   │
├──────────────────────────────────────────────┤
│ 测试控制: 标题输入 | 描述 | 预设 | Gate策略    │
│           [▶ Run] [■ Stop] [🧹 Clean]        │
│           诊断 req-id 输入 [🔍 Diagnose]       │
├──────────────────────────────────────────────┤
│ 流水线状态流 (Pipeline State Flow)            │
│ DRAFT → ANALYZING → Gate 0 → DESIGNING → ... │
│ ✓=已完成  ◉=活跃  ○=待定  ✗=失败              │
├──────────────────────────────────────────────┤
│ 发现列表 (Findings)                           │
│ 可筛选: All | Errors | Warnings              │
│ 点击展开详细信息 (建议/上下文/DB快照)           │
├──────────────────────────────────────────────┤
│ 节点详情 (Node Detail)                        │
│ 四个 Tab: 📥输入 | 📤输出 | 🤖LLM调用 | 🗄DB状态│
├──────────────────────────────────────────────┤
│ 运行历史 (Run History)                        │
└──────────────────────────────────────────────┘
```

### 5.2 状态流节点

每个节点显示状态名 + 执行该状态的 Agent ID。Gate 节点插入在对应状态之后。节点颜色与状态对应：绿=已完成、蓝=活跃、红=失败、灰=待定。

点击任意节点弹出详情面板，四个 Tab 分别展示：
- **Context Input** — NATS 消息中的 context_snapshot（含原始上下文字符串 + 结构化解析）
- **Agent Output** — agent.result 消息中的执行结果
- **LLM Calls** — 提示查看服务器日志路径（`/opt/ai-native/logs/llm_calls/`）
- **DB State** — 该时刻的数据库快照

### 5.3 预设场景

| 预设 | 标题 | 描述 |
|------|------|------|
| User Login | 用户登录系统 | 用户名/密码登录、记住我、密码重置、3次失败锁定 |
| Order Management | 订单管理系统 | CRUD、状态工作流、支付回调、分页筛选 |

---

## 6. CLI 命令

```
python cli.py run --title "需求标题" [--desc "..."] [--gate auto|manual] [--keep-data] [--export result.json]
python cli.py diagnose --req-id <uuid>
python cli.py infra
python cli.py validate-spec
python cli.py cleanup --all | --req-id <id> | --orphans | --worktrees | --stats [--dry-run]
python cli.py export --run-id <id> [-o output.json]
```

---

## 7. 运行时验证器 (RuntimeVerifier)

基于 `truth-spec.yaml` 的 10 项自动化检查：

| # | 检查项 | 触发时机 | 严重级别 |
|---|--------|----------|----------|
| 1 | upstream_visibility | context_built (NATS) | warning |
| 2 | agent_output_fields | agent_completed (NATS) | error |
| 3 | data_quantity_constraints | agent_completed (NATS) | warning |
| 4 | persistence_contracts | agent_completed (NATS) + on-demand | error/warning |
| 5 | gate_progression_sync | 流程结束时 | error |
| 6 | flow_contracts_sync | 流程结束时 | error |
| 7 | duplicate_dispatch_sync | 流程结束时 | warning |
| 8 | gate_sla_sync | 流程结束时 | warning |
| 9 | llm_audit_completeness | agent_completed (NATS) | info |
| 10 | worktree_cleanup_sync | 流程结束时 | warning |

### 7.1 检查详情

**Check 1 — Upstream Visibility：** 对应当前状态，验证所有上游 Agent 的输出数据已存在于 DB 中。例如 ANALYZING 状态进入 DESIGNING 时，验证 A1 的产物已写入 `spec.artifacts.A1`。

**Check 2 — Agent Output Required Fields：** 根据 `constraints.hard` 定义，验证 Agent 输出必须包含指定字段（如 A1 必须输出 `status, domain, requirement_draft`）。

**Check 3 — Data Quantity Constraints：** 软约束检查，如 A4 至少生成 1 张 ERD 表，A6 至少生成 5 个 DAG 节点。

**Check 4 — Persistence Contracts：** 验证 Agent 输出已按约定位置写入数据库。A4 特殊处理（写入 `spec.openapi`, `spec.erd`, `api_schemas`, `erd_designs` 多张表），其他 Agent 使用默认合约（写入 `spec.artifacts.{agent_id}`）。

**Check 5 — Gate Progression：** Gate 审批后的状态变更是否与预期一致。例如 Gate 0 (ANALYZING) 审批后应进入 DESIGNING。

**Check 6 — Flow Contracts：** 检查 rework/inner_loop 反馈关键词是否出现在下游 Agent 的 context 中。

**Check 7 — Duplicate Dispatch：** 同一状态在 N 秒内（默认 300s）不应被重复派发。

**Check 8 — Gate SLA：** Gate 等待时间是否超过 SLA。

**Check 9 — LLM Audit Completeness：** 检查 `/opt/ai-native/logs/llm_calls/` 下是否存在 Agent 的 LLM 调用记录。

**Check 10 — Worktree Leak：** 检查 `/tmp/a9-runtimes/` 下是否有超过 120 分钟未清理的工作树目录。

---

## 8. 基础设施检查 (Infra Checks)

| 检查项 | 验证内容 |
|--------|----------|
| PostgreSQL | 连接 + 预期表是否存在 |
| NATS | 连接 + JetStream `AI_NATIVE_EVENTS` 流 + 预期 subject |
| Temporal | 连接 + 预期 Workflow 类型 |
| LLM (DeepSeek) | API ping (发送 "ping" 消息) |
| MC Backend | HTTP 可达性 (GET /api/requirements?limit=1) |
| Redis | PING 命令 |
| Bridge | NATS→Temporal 桥 probe (发布 test 消息到 agent.result.test) |

---

## 9. Pre-flight 检查

在 Observer 启动前执行，验证基础设施就绪：

1. **NATS 连接** — 失败则直接返回 `ready: false`
2. **JetStream 流存在** — `AI_NATIVE_EVENTS` 必须存在，且至少有 1 个 consumer（否则 Agent Worker 未运行）
3. **MC Backend 可达** — HTTP 状态码 < 500
4. **LLM API 可达** — DeepSeek API ping

---

## 10. 数据清理

### 10.1 安全边界
- 仅删除 `external_id LIKE 'TEST-%'` 的数据
- 非测试数据拒绝删除
- 删除顺序遵循 FK 依赖：`test_executions → gate_approvals → agent_activities → api_schemas → erd_designs → requirements`

### 10.2 清理时机
- **正常结束：** Observer 完成后延迟 300s（等待 NATS ack 窗口关闭）再清理
- **启动时：** 自动清理超过 24 小时的孤儿测试数据
- **手动：** 通过 Web UI 或 CLI 触发

### 10.3 清理范围
- 数据库：requirements 及关联表
- 文件系统：`/tmp/a9-runtimes/` 下的过期 worktree 目录
- LLM 日志：`/opt/ai-native/logs/llm_calls/` 下对应 req_id 的日志文件

---

## 11. Truth Spec (truth-spec.yaml)

系统的"真相文件"，描述业务流程应该如何运行。业务架构变更时先更新此文件再改代码。

### 11.1 状态机
- **normal_flow:** DRAFT → ANALYZING → DESIGNING → REVIEWING → DECOMPOSING → DEVELOPING → TESTING → REVIEWING_CODE → RELEASING → DONE
- **fast_flow:** DRAFT → FAST_PASS → DEVELOPING → TESTING → RELEASING → DONE
- **rework:** 最多 2 轮，触发条件 A5 返回 pass=false
- **inner_loop:** 最多 2 轮，触发条件 A11 返回 pass=false

### 11.2 Agent 状态映射
| 状态 | Agent | 类型 |
|------|-------|------|
| ANALYZING | A1 | 需求分析 |
| DESIGNING | A3, A4 | 并行（A3=API设计, A4=ERD设计） |
| REVIEWING | A5 | 设计评审 |
| DECOMPOSING | A6 | 任务分解 |
| DEVELOPING | A9 | 代码生成 |
| TESTING | A11 | 测试 (stub) |
| REVIEWING_CODE | A12 | 代码评审 |
| RELEASING | A13 | 发布 |

### 11.3 Gate 定义
| Gate | 在状态 | 下一状态 | SLA | 宽限期 |
|------|--------|----------|-----|--------|
| 0 | ANALYZING | DESIGNING | 1h | - |
| 1 | DESIGNING | REVIEWING | 4h | 1h |
| 2 | DECOMPOSING | DEVELOPING | 4h | 1h |
| 3 | REVIEWING_CODE | RELEASING | 2h | - |

### 11.4 数据流
- `upstream_artifacts`: 定义每个状态依赖的上游 Agent 产物
- `context_key_mapping`: 定义上游产物在 context 中的映射路径
- `persistence_contracts`: 定义 Agent 产物的持久化目标位置

### 11.5 Self-Check 规则
Truth Spec 加载时自动校验 7 项自洽性：
1. Gate 的 `runs_in_state` 必须在 agent 定义中存在
2. upstream agents 必须有对应的 context_key_mapping
3. 状态转移目标必须已定义
4. 并行状态不能同时出现在单状态映射中
5. Stub agent 出现在状态映射中 → warning
6. Gate 总等待时间 > 24h → warning
7. Persistence target 有效性检查

---

## 12. A1 Agent 集成

Testing Tool 通过 MC Backend 间接触发 A1 Agent。当需求进入 ANALYZING 状态时，Orchestrator 通过 NATS 派发 context 消息，A1 Agent Worker 订阅并执行分析。

### 12.1 A1 Agent 执行流程
```
1. MCP 知识库检索 (并行 4 路, 各 5s 超时)
   ├── search_similar_requirements
   ├── get_domain_risks
   ├── get_tech_stack_recommendations
   └── get_cost_baseline
2. LLM 流式草案构建 (DeepSeek)
3. 澄清点识别 (ClarificationEngine)
4. 低保真线框图生成 (WireframeGenerator, 条件触发)
5. BDD 验收标准生成 (BDDDrafter)
6. 置信度评分 (0.5 ~ 1.0)
```

### 12.2 A1 输出事件类型
| 事件类型 | 说明 |
|----------|------|
| `thinking` | 进度提示文字 |
| `knowledge` | MCP 知识源摘要 |
| `draft_update` | 流式草案更新（每次产出完整 JSON 时推送） |
| `clarification` | 澄清问题列表 |
| `wireframe` | 线框图 JSON |
| `done` | 分析完成（含最终 draft、置信度、知识源） |
| `error` | 异常信息 |

### 12.3 A1 单元测试覆盖 (T-AG-001 ~ T-AG-016)
| 编号 | 测试内容 |
|------|----------|
| T-AG-001 | 完整事件序列（MCP 正常） |
| T-AG-002 | 首轮对话空草案 |
| T-AG-003 | 多轮对话增量更新 |
| T-AG-004 | 全部 4 路 MCP 超时 — 不阻塞 |
| T-AG-005 | 单路 MCP 超时 — 其他正常 |
| T-AG-006 | MCP 空结果 — 摘要正确 |
| T-AG-007 | entities=null → 不触发线框图 |
| T-AG-008 | acceptance_criteria=null → 不崩溃 |
| T-AG-009 | BDD 字典场景 → GWT 字符串转换 |
| T-AG-010 | BDD 字符串场景 → 直通 |
| T-AG-011 | BDD 空场景 → 返回空列表 |
| T-AG-012 | LLM 失败 → error 事件 |
| T-AG-013 | Clarification 异常 → error 事件 |
| T-AG-014 | 置信度评分 (多场景) |
| T-AG-015 | 空草案 → 最低置信度 0.5 |
| T-AG-016 | 部分草案 → 中间置信度 |

### 12.4 DraftBuilder 流式解析测试 (T-PR-001 ~ T-PR-007)
| 编号 | 测试内容 |
|------|----------|
| T-PR-001 | 完整 JSON 一次性解析 |
| T-PR-002 | 不完整 JSON 等待更多 chunk |
| T-PR-003 | 两个连续 JSON — 仅消费第一个 |
| T-PR-004 | JSON 前的垃圾文本 → 跳过 |
| T-PR-005 | 数组包裹 → 拒绝 |
| T-PR-006 | 流式 chunk 累积 → 多次 yield |
| T-PR-007 | JSON 内转义引号 → 正确闭合检测 |

---

## 13. 配置与部署

### 13.1 环境变量
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `postgresql://ai_native:ai_native_dev@localhost:5432/ai_native` | PostgreSQL 连接 |
| `DEEPSEEK_API_KEY` | (空) | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | `https://uniapi.ruijie.com.cn` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro-202606` | LLM 模型 |
| `MCP_GATEWAY_URL` | `http://localhost:8100/mcp` | MCP 知识库网关 |

### 13.2 启动命令
```bash
# Web Dashboard (端口 8500)
python server.py

# CLI 运行测试
python cli.py run --title "需求标题"

# 运行单元测试
pytest tests/unit/ -v

# 运行集成测试 (需要 PostgreSQL)
pytest tests/integration/ -v -m integration
```

### 13.3 依赖服务
- PostgreSQL (localhost:5432, database: ai_native)
- NATS (localhost:4222, stream: AI_NATIVE_EVENTS)
- Temporal (localhost:7233, namespace: ai-native)
- MC Backend (localhost:8000)
- DeepSeek LLM API
- MCP Gateway (localhost:8100)
- Redis (localhost:6379, 可选)
