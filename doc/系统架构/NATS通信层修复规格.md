# NATS 通信层修复规格 v1.1

> 状态：待实施 | 审计日期：2026-07-14 | 已通过 critical audit
> 产出：统一 NATS 客户端 + Stream/Consumer 修复 + 开发规范

---

## 一、审计结论（5 大类根因）

### 1.1 每次重启全量消息重放

**根因**：`base_worker.py:381` 用 `int(time.time())` 生成 consumer 名，每次重启创建全新 consumer。`stream_manager.py:155` 默认 `DeliverPolicy.ALL`，新 consumer 从 Stream 第一条消息重放全部历史。

### 1.2 成功路径不发 ack

**根因**：`base_worker.py` 的 `_handle` 函数在正常返回路径（line 339 execute 成功后 → line 359 发布结果 → line 366 return）没有 `msg.ack()`。只在去重跳过（line 309）和异常处理（line 372）处 ack。JetStream 在 ack_wait 超时后不断重发。

### 1.3 孤儿 consumer 无限累积

**根因**：每次重启 = 新的 durable consumer（带时间戳），旧 consumer 永不删除。`delete_consumer()` 是死代码。RetentionPolicy.INTEREST 下孤儿 consumer 会把消息永远钉在 Stream 中，无法回收磁盘。

### 1.4 核心消息流用 core NATS（无持久化）

**根因**：`dispatch_agent.py:149`、`notify_mc.py:92,101`、`base_worker.py:359,400,416` 均用 `nc.publish()`。subscriber 离线 → 消息永久丢失 → Temporal 工作流超时死锁（30 分钟）。

### 1.5 Outbox 模式被违背

**根因**：`outbox_publisher.py:95` 用 core NATS 发布。DB 记录标记 "published" 但下游可能根本没收到 — 完全违背 outbox 的 at-least-once 语义。

---

## 二、修复方案

### 2.1 Stream 配置修正 (`stream_manager.py`)

**保留 `RetentionPolicy.INTEREST`，不改为 LIMITS。**

原因：LIMITS 在 `max_consumers=-1` + 孤儿 consumer 累积的场景下，`DiscardPolicy.OLD` 会在 Stream 满时丢弃最老的消息，造成**新的数据丢失**（慢 consumer 来不及消费就被驱逐）。INTEREST 只在所有 consumer 都 ack 后才删除消息，配合孤儿 consumer 清理后行为正确。

| 配置项 | 当前值 | 修正为 | 原因 |
|--------|--------|--------|------|
| `deliver_policy` 默认值 | `ALL` | `NEW` | ALL 导致新 consumer 重放全部历史 |
| `max_age` | (未设置) | `7d` | 防止孤儿 consumer 钉住消息过久。正常消费不受影响 |

### 2.2 新建统一 NATS 客户端 (`repos/event-bus/event_bus/nats_client.py`)

放在 `event_bus` 包内（与现有 `publisher.py`、`subscriber.py`、`stream_manager.py` 同级），不放在 `repos/infra/`。

```python
class NatsClient:
    """所有 NATS 通信的统一入口。封装 JetStream publish/subscribe，强制 Nats-Msg-Id。"""

    async def subscribe(
        self, subject: str, handler: Callable,
        durable_name: str,
        deliver_policy: DeliverPolicy = DeliverPolicy.NEW,
        ack_wait: int = 120,     # 长任务默认 2 分钟
        max_deliver: int = 10,   # 足够覆盖慢 agent 的多次 nak
    ) -> JetStreamContext.PushSubscription

    async def publish(
        self, subject: str, payload: dict, msg_id: str | None = None,
    ) -> PubAck

    # msg_id 为空时自动生成 uuid4，保证每条消息都有 Nats-Msg-Id
```

**设计决策**：
- `ack_wait=120` + `max_deliver=10`：A9 等慢 agent 可能执行数分钟，120s ack_wait 减少无效重发，10 次重试覆盖 20 分钟窗口
- `max_deliver` 不是 `3`：慢 agent（A9 dev agent、A4 spec writer）可能需要数分钟，3 次重试后消息被终止
- 返回 `PushSubscription` 不是 `PullSubscription`：callback-based subscribe 在 nats-py 中是 push 模式

**注意**：`NatsClient` 是一个**目标架构组件**。在当前阶段（NatsClient 未完成前），各模块直接使用 `js.publish()` + `js.subscribe()`，但**必须**遵守本规格中的 JetStream/Nats-Msg-Id/固定 consumer name 规则。NatsClient 创建后将逐步迁移。

### 2.3 `base_worker.py` 修复

| 位置 | 当前 | 修正 |
|------|------|------|
| Line 381 | `consumer_name = f"..._{int(_time.time())}"` | `consumer_name = f"{agent_id}_consumer_{subj.replace('.', '_')}"` |
| Line 293-374 (`_handle`) | 成功路径无 ack；异常路径 line 372 手动 ack | 在 line 366（发布 result 成功后）加 `await msg.ack()`；去掉 line 372 的 ack（避免 double-ack） |
| Line 359 | `nc.publish(reply_subject, ...)` | `js.publish(reply_subject, ..., headers={"Nats-Msg-Id": f"agent-result-{event_id}"})` |
| Line 400 (`report_status`) | `nc.publish(subject, ...)` | `js.publish(subject, ...)` |
| Line 416 (`report_artifact`) | `nc.publish(subject, ...)` | `js.publish(subject, ...)` |

**ack 控制流修正细节**：

```python
async def _handle(msg):
    try:
        # ... dedup check (already acks and returns on duplicate) ...
        # ... execute ...
        # ... publish result (line 359) ...
        await msg.ack()  # <-- 加在这里，成功路径唯一 ack 点
    except Exception as e:
        logger.error(...)
        await msg.nak()  # <-- 失败重试，不用 ack
    # 注意：不在 finally 中 ack，因为：
    # 1. 去重路径已 return（内含 ack）
    # 2. 异常路径用 nak（让 JetStream 重试）
    # 3. 成功路径在 try 末尾 ack
```

### 2.4 核心消息流迁移到 JetStream

| 文件 | 当前调用 | 修正为 |
|------|---------|--------|
| `orchestrator/activities/dispatch_agent.py:149` | `nc.publish(event_type, ...)` | `js.publish(event_type, ..., headers={"Nats-Msg-Id": msg_id})` |
| `orchestrator/activities/notify_mc.py:92,101` | `nc.publish(subject, ...)` | `js.publish(subject, ..., headers={"Nats-Msg-Id": msg_id})` |
| `mc-backend/services/outbox_publisher.py:95` | `self._nats.publish(...)` | `self._js.publish(..., headers={"Nats-Msg-Id": f"outbox-{row_id}"})` |
| `mc-backend/api/approvals.py:90,466,495` | `NATS_CLIENT.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `mc-backend/api/prototype.py:75,659` | `NATS_CLIENT.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `mc-backend/api/test_cases.py:404,468` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `mc-backend/api/chat_spec.py:519` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a3_ui_generator.py:144` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a6_architect.py:375` | `self.nats_client.publish(...)` (core NATS) | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a7_test_case_generator.py:175,469` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a8_architecture_expert.py:109` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a9/a9_dev_agent.py:477,493` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a11_auto_test_agent.py:207,243,532` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a12_code_review.py:156` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a11_test_agent_stub.py:59` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/fast_channel_classifier.py:113` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/a1_upgrade.py:206,224` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |
| `agent-workers/activity_recorder.py:78,117,156` | `js.publish(subject, body)` (缺 Nats-Msg-Id) | `js.publish(subject, body, headers={"Nats-Msg-Id": ...})` |
| `feishu-bot/main.py:103` | `nc.publish(subject, body)` | `js.publish(subject, body, headers={"Nats-Msg-Id": ...})` |
| `feishu-bot/card_sender.py:135,169` | `nc.publish(...)` | `js.publish(..., headers={"Nats-Msg-Id": ...})` |

**dispatch_agent 幂等 key 修正**：当前 `dispatch_agent.py:121` 用 `dispatch-{req_id}-{state}-{agent_id}-{timestamp_ms}`，timestamp 每次调用都变，Temporal retry 生成的 msg_id 不同，JetStream 无法去重。修正为：

```python
msg_id = f"dispatch-{req_id}-{state}-{agent_id}-{activity.info().attempt}"
```

### 2.5 统一杂散订阅 (`nc.subscribe` → `js.subscribe`)

| 文件 | 当前 | 修正 |
|------|------|------|
| `agent-workers/a12_code_review.py:33` | `nc.subscribe("test.passed")` | `js.subscribe("test.passed", ..., durable="A12_consumer_test_passed")` |
| `agent-workers/a11_auto_test_agent.py:80` | `nc.subscribe("test.augment_request")` | `js.subscribe(..., durable="A11_consumer_test_augment_request")` |
| `agent-workers/ci_build_service.py:32` | `nc.subscribe("ci.build")` | `js.subscribe(..., durable="A10_consumer_ci_build")` |
| `agent-workers/a3_ui_generator.py:154` | `nc.subscribe("prototype.annotated.*")` | `js.subscribe(..., durable="A3_consumer_prototype_annotated")` |
| `agent-workers/a7_test_case_generator.py:54` | `nc.subscribe("test.validate")` | `js.subscribe(..., durable="A7_consumer_test_validate")` |
| `agent-workers/a1_upgrade.py:239` | `nc.subscribe("msg_received")` | `js.subscribe(..., durable="A1_upgrade_consumer_msg_received")` |

### 2.6 MC Backend subscriber 持久化

`nats_subscriber.py` 的 3 个 subscribe 改为 durable：

```python
await js.subscribe("context.ready.gate0", cb=..., stream="AI_NATIVE_EVENTS", durable="mc_backend_gate0")
await js.subscribe("context.ready.gate1", cb=..., stream="AI_NATIVE_EVENTS", durable="mc_backend_gate1")
await js.subscribe("context.ready.A1", cb=..., stream="AI_NATIVE_EVENTS", durable="mc_backend_a1")
```

**保留 `while True` 重连循环**。nats-py 的 JetStream push subscribe（callback 模式）在断连后不一定自动重建，外层 `while True` 是必要的安全网。不能依赖 NATS 内建 reconnect 来恢复 JetStream 订阅。

### 2.7 Consumer 清理逻辑

`stream_manager.py` 新增 `cleanup_orphaned_consumers()`：

```python
async def cleanup_orphaned_consumers(
    self,
    active_names: set[str],  # 当前进程持有的 consumer 名称集合
    max_idle_hours: int = 1,  # 空闲超过此时间视为孤儿
):
    """列出所有 consumer，删除不在 active_names 中且空闲超过 max_idle_hours 的 consumer。

    空闲判定：
    1. consumer_info.created 距现在 > max_idle_hours
    2. consumer_info.num_ack_pending == 0（没有未确认的消息）
    3. consumer_info.num_pending == 0（没有待投递的消息）
    4. consumer 名称不在 active_names 中

    只删除同时满足以上 4 条的 consumer。
    使用 consumer_info.created 字段（NATS server 返回的 RFC 3339 时间戳）。
    """
```

`worker_launcher.py` 启动时调用：收集所有已注册 agent 的 consumer 名称 → 传入 `cleanup_orphaned_consumers`。

### 2.8 visagent-nats-bridge (Go) — 保留 core NATS

**不改为 JetStream durable。**

`repos/visagent-nats-bridge/main.go` 订阅 `test.completed`、`agent.status.changed`、`loop.tripped` 三个观测性事件。该 bridge 是监控桥接（fire-and-forward 到外部 VisAgent 服务），本身是 loss-tolerant 的。改为 durable 增加 Go 端 consumer 生命周期管理复杂度，无实际收益。

该 bridge 的 handler 目前是 stub（line 151-153），后续如需升级为关键数据管道，届时再改为 JetStream。

### 2.9 其他隐式订阅的修正

- **`testing-tool/observer.py:192-195`**：ephemeral `js.subscribe()` → 改为 durable（带固定名称），避免每次 observer 运行留下孤儿 consumer
- **`mc-backend/api/activity_stream.py:58`**：ephemeral `js.subscribe()` → 每个 SSE 连接创建 ephemeral consumer 可接受（SSE 连接关闭时 `unsubscribe` 清理），但需确认 `unsubscribe` 后 consumer 确实被删除
- **`mc-backend/main.py:62`**：`nc.subscribe("agent.status.changed")` → 改为 `js.subscribe(..., durable="mc_backend_agent_status")`

---

## 三、Consumer 命名规范

```
{服务标识}_{用途}
```

| 模块 | Consumer 名称 | agent_type 来源 |
|------|--------------|----------------|
| A1 Worker | `A1_consumer_context_ready_requirement_intake` | `a1_requirement_intake.py:40` |
| A1 Upgrade | `A1_upgrade_consumer_msg_received` | `a1_upgrade.py:114` |
| A2 Worker | `A2_consumer_context_ready_knowledge_analyst` | `a2_knowledge_analyst.py:58` |
| A3 Worker | `A3_consumer_context_ready_ui_generator` | `a3_ui_generator.py:27` |
| A4 Worker | `A4_consumer_context_ready_spec_writer` | `a4_spec_writer.py:44` |
| A5 Worker | `A5_consumer_context_ready_design_review` | `a5_design_review.py:51` |
| A6 Spec Decomposer | `A6_consumer_context_ready_spec_decomposer` | `a6_spec_decomposer.py:23` |
| A7 Worker | `A7_consumer_context_ready_test_case_generator` | `a7_test_case_generator.py:25` |
| A8 Worker | `A8_consumer_context_ready_architecture_expert` | `a8_architecture_expert.py:17` |
| A9 Worker | `A9_consumer_context_ready_dev_agent` | `a9/a9_dev_agent.py:39` |
| A10 Worker | `A10_consumer_context_ready_ci_cd` | `ci_agent.py:36` |
| A11 Stub | `A11_consumer_context_ready_test_agent` | `a11_test_agent_stub.py:21` |
| A11 Auto | `A11_consumer_context_ready_auto_test` | `a11_auto_test_agent.py:34` |
| A12 Worker | `A12_consumer_context_ready_code_review` | `a12_code_review.py:18` |
| A13 Worker | `A13_consumer_context_ready_release` | `release_agent.py:27` |
| K14 Worker | `K14_consumer_context_ready_knowledge_keeper` | `k14_knowledge_keeper.py:28` |
| K15 Worker | `K15_consumer_context_ready_change_propagation` | `k15_change_propagation.py:29` |
| FC Worker | `FC_consumer_context_ready_fast_channel` | `fast_channel_classifier.py:34` |
| NATS-Temporal Bridge | `bridge_agent_result` / `bridge_agent_status` | 固定常量 |
| MC Backend | `mc_backend_gate0` / `mc_backend_gate1` / `mc_backend_a1` / `mc_backend_agent_status` | nats_subscriber.py |
| Event Subscriber | `subscriber_{pattern_slug}` | event_bus/subscriber.py |
| Observer | `observer_context_ready` / `observer_agent_result` | testing-tool/observer.py |

**已知注意**：
- A6 有两个类：`A6Architect`（`a6_architect.py`，agent_type="architect"）不继承 BaseAgentWorker，无 subscribe_nats。`SpecDecomposerAgent`（`a6_spec_decomposer.py`，agent_type="spec_decomposer"）继承 BaseAgentWorker。dispatch_agent 的 `_AGENT_TYPE_MAP` 映射 `"A6": "spec_decomposer"` — 路由到后者。
- A11 有两个类：`A11AutoTestAgent`（agent_type="auto_test"）和 `A11TestAgentStub`（agent_type="test_agent"）。dispatch_agent 映射 `"A11": "test_agent"` — 路由到 stub。需确认这是刻意的还是 bug。

---

## 四、验证步骤

1. 启动 NATS + JetStream，确认 `AI_NATIVE_EVENTS` stream retention=INTEREST，max_age=7d
2. 启动 mc-backend → `nats consumer info AI_NATIVE_EVENTS mc_backend_gate0` 确认 durable 存在
3. 启动 worker_launcher → 每个 agent 的 consumer name 不含时间戳
4. 停止 worker_launcher → `nats consumer ls` 确认 consumer 仍在（durable 持久）
5. 重启 worker_launcher → consumer 数量不增加（复用已有 consumer）
6. 发送一条 dispatch 消息 → 检查 agent 日志只有一条 "[agent_id] Published result"，无 "Duplicate message" 日志
7. 停止 mc-backend → 发布 `context.ready.gate0` 消息 → 重启 mc-backend → 检查 approvals 表有新记录（证明消息在 offline 期间保留并投递）
8. 连续重启 worker_launcher 3 次 → `nats consumer ls AI_NATIVE_EVENTS | wc -l` 数量不变
