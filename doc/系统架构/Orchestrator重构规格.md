# Agent 调度收归 Orchestrator — 详细规格 v3 (FINAL)

## 1. 目标

将所有 Agent 调度权收归 Temporal Orchestrator（`RequirementWorkflow`），消灭 3 条独立调度链路，改为单一状态机驱动。

## 2. 当前问题（3 条调度链路）

```
链路1: Temporal dispatch_agent → NATS Core → Agent（发完不管，不等待结果）
链路2: MC Backend Approve → _dispatch_gate_agents → NATS Core → Agent（绕过 Orchestrator）
链路3: Agent 自级联（A4→review.start→A5→review.completed→A6→dag.created）
```

## 3. 目标架构（单一调度源）

```
MC Backend                Temporal Workflow              Bridge           Agent Workers
──────────                ─────────────────              ──────           ─────────────

POST /trigger ────────→ start_workflow
                           │
                           ├─ dispatch(A1) [Activity, ms级返回]
                           │       └─────────→ NATS (JetStream) ────→ A1.execute()
                           │                                              │
                           │   agent_completed(A1) Signal ←── Bridge ←── agent.result.A1
                           │                                              │
                           ├─ Gate 0: await workflow.wait_condition()
                           │       ↑
                           │   POST /approve → approve_gate Signal (via Temporal)
                           │
                           ├─ dispatch(A4) → ...
                           │
                           ... (持续到 DONE)
```

所有调度在 Workflow 内，所有等待通过 Temporal Signal + wait_condition，Agent 之间零直接通信。

## 4. 时序保证

| 步骤 | 机制 | 最短 | 最长 | 超时处理 |
|------|------|------|------|---------|
| dispatch_agent Activity | Temporal Activity | < 1s | 30s | 重试 3 次 |
| Agent LLM 执行 | wait_condition + workflow timer | 5s | 10min | timeout → escalate 到人工 |
| Agent 编码/自测 | wait_condition + workflow timer | 5min | 4h | timeout → escalate 到人工 |
| Gate 审批 | wait_condition（无 timeout） | 即时 | 无上限 | SLA 告警不强制终止 |

## 5. 状态机流转（完整，含 rework 闭环）

```
DRAFT
  │ dispatch(A1) → wait agent_completed(A1)
  ▼
ANALYZING
  │ create_gate(Gate 0) → wait gate_approved(Gate 0)
  ▼                          (无 timeout，几天都可以)
DESIGNING
  │ 并行 dispatch:
  │   dispatch(A3) → wait agent_completed(A3)   [UI 原型]
  │   dispatch(A4) → wait agent_completed(A4)   [OpenAPI + ERD]
  │ (两个都完成才推进)
  ▼
REVIEWING
  │ dispatch(A5) → wait agent_completed(A5)
  │
  ├─ A5.pass==false AND rework_count < 2:
  │    rework_count++ → 回到 DESIGNING（A4 根据 review issues 重新生成）
  │
  ├─ A5.pass==false AND rework_count >= 2:
  │    → escalate 到人工，创建 Gate 审批（人工决定继续或终止）
  │
  └─ A5.pass==true → 继续
  ▼
DECOMPOSING
  │ dispatch(A6) → wait agent_completed(A6)   [DAG 拆解]
  ▼
DEVELOPING
  │ dispatch(A9) → wait agent_completed(A9)   [编码]
  ▼
TESTING
  │ dispatch(A11) → wait agent_completed(A11)  [测试]
  ▼
REVIEWING_CODE
  │ dispatch(A12) → wait agent_completed(A12)  [Code Review]
  ▼
RELEASING
  │ dispatch(A13) → wait agent_completed(A13)  [发布]
  ▼
DONE
```

Gate 插入位置（每个 Gate 在两阶段之间）：
- **Gate 0**: ANALYZING → DESIGNING（业务方确认需求分析，A1 产出）
- **Gate 1**: DESIGNING → REVIEWING（确认 A3+A4 的设计产物：原型 + OpenAPI + ERD）
- **Gate 2**: DECOMPOSING → DEVELOPING（架构师确认 A6 的 DAG 拆解）
- **Gate 3**: REVIEWING_CODE → RELEASING（Tech Lead 确认发布）

Rework 闭环：
- A5 评审不通过 → 回退 DESIGNING（最大 2 轮）
- 第 3 轮仍不通过 → 创建人工 Gate，由人决定继续或终止
- A5 的 review issues 作为 context 传给重试的 A4
- `rework_count` 存储在 Workflow 的 `self._rework_count` 中（Temporal 可重放）

## 6. 关键设计决策

### 6.1 Bridge 使用 JetStream consumer + WorkflowNotFoundError 处理

Bridge 必须使用 **JetStream consumer with durable name + ack after signal success**：

```
- 订阅 subject: agent.result.> 和 agent.status.changed.>
- Stream: AI_NATIVE_EVENTS（已存在）
- Consumer: BRIDGE_CONSUMER, durable, ack explicit
- 处理流程：
  1. 收到消息
  2. 解析 req_id, agent_id, workflow_id, result
  3. 调用 Temporal Signal
  4. Signal 成功 → msg.ack()
  5. WorkflowNotFoundError → msg.ack()（过期消息，安全丢弃）
  6. 其他异常 → msg.nak()（JetStream 自动重投）
```

```python
from temporalio.exceptions import WorkflowNotFoundError

try:
    await handle.signal(RequirementWorkflow.agent_completed, agent_id, result)
    await msg.ack()
except WorkflowNotFoundError:
    logger.info(f"Stale message for completed workflow {workflow_id}, discarding")
    await msg.ack()  # 安全丢弃，不重试
except Exception as e:
    logger.error(f"Bridge signal failed: {e}")
    await msg.nak()  # 重试
```

这样 Bridge 重启后 JetStream 回放所有未 ack 消息，不会丢失。过期消息安全丢弃。

### 6.2 `wait_condition` 正确使用 workflow timer

`workflow.wait_condition` 没有 `timeout` 参数。正确模式：

```python
# Agent 等待（有时限）
deadline = workflow.now() + timedelta(minutes=10)
while self._agent_result is None and workflow.now() < deadline:
    await workflow.wait_condition(
        lambda: self._agent_result is not None or workflow.now() >= deadline
    )
    # wait_condition 只在外部事件（Signal/Timer）时重新评估 lambda
    # 长时间等待期间不产生 History Event
```

```python
# Gate 等待（无时限）
await workflow.wait_condition(
    lambda: self._gate_approved is not None
)
# 没有 timeout，可以等几天。不产生多余 History Event
```

### 6.3 竞态防护：Signal 提前到达

在 `dispatch_agent` 之前重置标志位，dispatch 和 wait_condition 之间 Signal 到达不会丢失：

```python
# 正确顺序（关键！）
self._agent_result = None           # 1. 先重置标志位
self._agent_id_expected = agent_id  # 2. 记录期望的 agent
wf_id = workflow.info().workflow_id # 3. 获取 workflow_id
await workflow.execute_activity(    # 4. 发 dispatch（wf_id 作为参数传入）
    dispatch_agent, args=[req_id, state, agent_id, wf_id, context_str]
)
# Signal 可能在这里到达 ← 没问题，_agent_result 已被设置了

await workflow.wait_condition(      # 5. 立即能通过
    lambda: self._agent_result is not None
)
```

`agent_completed` Signal handler：
```python
@workflow.signal
async def agent_completed(self, agent_id: str, result: dict):
    if agent_id != self._agent_id_expected:
        return  # 不是当前等待的 agent，忽略
    self._agent_result = result
```

加 `_agent_id_expected` 作为来源验证（6.8）。

### 6.4 Bridge 精确路由：消息携带 `workflow_id`

`workflow_id` 由 **Workflow 获取后作为参数传入 Activity**（Activity 无法访问 `workflow.info()`）：

Workflow 侧：
```python
wf_id = workflow.info().workflow_id
await workflow.execute_activity(
    dispatch_agent, args=[req_id, state, agent_id, wf_id, context_str], ...
)
```

dispatch_agent Activity：
```python
@activity.defn(name="dispatch_agent")
async def dispatch_agent(req_id: str, state: str, agent_id: str,
                         workflow_id: str, context: str = "") -> dict:
    envelope = {
        "event_id": f"dispatch-{req_id}-{state}",
        "event_type": event_type,
        "payload": {
            "req_id": req_id,
            "state": state,
            "agent_id": agent_id,
            "context": context,
            "workflow_id": workflow_id,     # ← 从参数获取
        },
        "req_id": req_id,
    }
```

Agent `_handle()` 把 `workflow_id` 放入 `agent.result`：
```python
result_envelope = {
    "agent_id": self.agent_id,
    "req_id": req_id,
    "workflow_id": context.get("workflow_id", ""),  # ← 带回
    "result": result,
    "timestamp": ...,
}
```

Bridge 用 `workflow_id` 精确路由：
```python
workflow_id = data.get("workflow_id", "")
handle = temporal_client.get_workflow_handle(workflow_id)
```

### 6.5 Rework 闭环

Workflow 内维护 `self._rework_count: int = 0`：

```
REVIEWING:
  dispatch(A5) → wait agent_completed(A5)
  if A5.pass:
      → DECOMPOSING
  else:
      rework_count += 1
      if rework_count < 3:
          → DESIGNING（A4 收到 A5 review issues 作为 context 重新生成）
      else:
          → 创建人工 Gate（escalate_gate），等待人决定
```

A4 在 rework 时收到的 context 中包含上一轮 A5 的 issues：
```python
context = {
    ...,
    "rework": True,
    "rework_count": rework_count,
    "previous_review_issues": a5_result.get("issues", []),
}
```

### 6.6 DESIGNING 状态 A3 和 A4 并行

A3 和 A4 在 DESIGNING 状态内并行执行，两个都完成才推进：

```python
async def _run_designing(self, req_id):
    self._agent_result_a3 = None
    self._agent_result_a4 = None
    wf_id = workflow.info().workflow_id
    
    await workflow.execute_activity(
        dispatch_agent, args=[req_id, "designing", "A3", wf_id, context_a3], ...
    )
    await workflow.execute_activity(
        dispatch_agent, args=[req_id, "designing", "A4", wf_id, context_a4], ...
    )
    
    deadline = workflow.now() + timedelta(minutes=15)
    while (self._agent_result_a3 is None or self._agent_result_a4 is None) \
          and workflow.now() < deadline:
        # 同时等两个 Signal
        await workflow.wait_condition(
            lambda: (self._agent_result_a3 is not None 
                     and self._agent_result_a4 is not None)
                     or workflow.now() >= deadline
        )
    
    # 部分失败处理
    if self._agent_result_a3 is None:
        pass  # A3 非致命，用 fallback HTML
    if self._agent_result_a4 is None:
        self._escalate = True  # A4 致命，escalate
```

### 6.7 Agent 进度可见性

Agent 在执行中通过 `agent.status.changed` 报告进度 → Bridge 转发到 Workflow：

```python
# Agent execute() 中
await self.report_status(req_id, "running", "Phase 1: LLM 需求分析", progress=25)
```

Workflow 存储并暴露为 Query：
```python
self._agent_progress: dict = {}  # {agent_id: {...}}

@workflow.query
def get_progress(self) -> dict:
    return {
        "state": self._state.value,
        "agent_progress": dict(self._agent_progress),
        "rework_count": self._rework_count,
    }
```

### 6.8 消息来源验证

Workflow Signal 中校验 agent_id：

```python
@workflow.signal
async def agent_completed(self, agent_id: str, result: dict):
    if agent_id != self._agent_id_expected:
        workflow.logger.warning(...)
        return
    self._agent_result = result
```

dispatch_agent Activity 也校验状态→Agent 映射：
```python
_STATE_AGENT_MAP = {
    "analyzing": "A1",
    "designing": None,   # 特殊：同时发 A3 和 A4
    "reviewing": "A5",
    "decomposing": "A6",
    "developing": "A9",
    "testing": "A11",
    "code_review": "A12",
    "releasing": "A13",
}
```

## 7. 改动清单

### 7.1 新建文件

**`repos/agent-workers/nats_temporal_bridge.py`**

- 连接 NATS + JetStream + Temporal Client
- 使用 JetStream durable consumer 订阅 `agent.result.>` 和 `agent.status.changed.>`
- 收到消息 → 解析 `workflow_id` → `get_workflow_handle` → `signal()`
- Signal 成功后 `ack()`；`WorkflowNotFoundError` → `ack()` 丢弃；其他错误 → `nak()` 重试

### 7.2 修改文件

| 文件 | 改动摘要 |
|------|---------|
| `requirement_workflow.py` | 主循环重构：dispatch → wait_condition；新增 `agent_completed`/`agent_status` Signal；`approve_gate` 设标志位；rework 闭环 (6.5)；A3+A4 并行 (6.6)；进度查询 Query (6.7)；来源校验 (6.8)；正确 timer + 竞态防护 (6.2/6.3) |
| `dispatch_agent.py` | 签名增加 `agent_id` 和 `workflow_id` 参数；envelope 中注入 `workflow_id`；增加状态→Agent 映射校验 |
| `gate_await.py` | 更名为 `create_gate_approval`；只创建 Gate DB 记录，立刻返回；不轮询 |
| `approvals.py` | 删除 `_dispatch_gate_agents()`；`approve()` 只发 Temporal Signal |
| `base_worker.py` | `_handle()` 中 ack 提前到 `execute()` 之前；消息去重（`event_id` set + 5 分钟过期）；`agent.result` 消息中携带 `workflow_id` |
| `a4_spec_writer.py` | 删除末尾 `nc.publish("review.start", ...)` 自级联 |
| `a5_design_review.py` | 删除末尾 `nc.publish("review.completed", ...)` 自级联 |
| `a6_spec_decomposer.py` | 删除末尾 `nc.publish("dag.created", ...)` 自级联 |
| `worker_launcher.py` | 启动 Bridge 作为 asyncio Task；删除所有 extra_subjects |

## 8. LLM 调用预估（单次需求）

| Agent | 次数 | 说明 |
|-------|------|------|
| A1 | 1 | 需求分析 |
| A3 | 1 | UI 原型 |
| A4 | 2 | OpenAPI + ERD |
| A5 | 1 | 设计评审 |
| A6 | 1 | DAG 拆解 |
| A9 | 1 | 编码 |
| A11 | 1 | 测试 |
| A12 | 1 | Code Review |
| **总计** | **9** | rework 每轮 +3 (A4×2 + A5×1)，最多 2 轮 → 额外 +6 |

## 9. 部署验证步骤

1. 停止所有服务
2. 部署改动文件
3. 创建/验证 NATS JetStream stream `AI_NATIVE_EVENTS`（含 `agent.result.>` 和 `agent.status.changed.>`）
4. 启动 Orchestrator → 启动 Agents + Bridge → 重启 MC Backend
5. 创建需求 → trigger → 验证 LLM 审计各 Agent 1 次调用
6. 验证 A4→A5→A6 不在 Gate 0 之外运行
7. 逐 Gate 批准，验证到 DONE
8. 验证 rework：故意让 A5 不通过 → 验证回到 DESIGNING
9. 验证 Bridge 重启：kill Bridge → 恢复 → 验证未 ack 消息被回放
