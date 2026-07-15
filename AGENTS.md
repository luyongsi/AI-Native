# AI-Native Platform — Development Standards

## NATS 通信铁律

### 1. 发布必须走 JetStream，禁止 core NATS

- 所有业务消息发布使用 `js.publish()`，禁止 `nc.publish()`
- 例外（可用 `nc.publish`）：请求-回复模式中的回复（`msg.reply`）
- 例外（可用 `nc.subscribe`）：纯观测性/监控类消费者，明确标注 `loss-tolerant`

### 2. 每次 JetStream publish 必须带 Nats-Msg-Id

```python
headers = {"Nats-Msg-Id": str(uuid4())}
await js.publish(subject, body, headers=headers, stream="AI_NATIVE_EVENTS")
```
- Nats-Msg-Id 利用 JetStream 的 2 分钟 dedup window 实现 NATS 级别幂等
- 有业务语义的 id（如 `dispatch-{req_id}-{agent_id}`）比 uuid4 更好，但必须保持确定性
- 禁止用含时间戳的 id（如 `f"..._{int(time.time())}"`）— Temporal retry 时 id 变化，去重失效

### 3. Durable Consumer 名称固定，禁止带时间戳或随机数

```python
# 正确
consumer_name = "A1_consumer_context_ready_requirement_intake"

# 错误 — 每次重启创建新 consumer，触发全量消息重放
consumer_name = f"A1_consumer_{int(time.time())}"
```

### 4. Consumer 创建时显式设置 deliver_policy

```python
# 新 consumer：只收创建后的新消息
config = ConsumerConfig(durable_name=name, deliver_policy=DeliverPolicy.NEW, ...)

# 已有 consumer：自动从上次 ack 位置恢复（NATS 默认行为）
# 重启时确保 consumer name 不变即可，无需重新设置 deliver_policy
```
- `stream_manager.py` 中 `add_consumer()` 的默认 deliver_policy 从 `ALL` 改为 `NEW`

### 5. 消息处理完必须 ack

- 成功 → `await msg.ack()`（放在 try 块末尾，不在 finally 中）
- 失败但希望重试 → `await msg.nak()`
- 失败且不重试 → `await msg.term()`
- ack_wait 默认 120s，max_deliver 默认 10（覆盖慢 agent 场景）
- 禁止无声 return — JetStream 会在 ack_wait 超时后重发

### 6. 去重依赖 Nats-Msg-Id，不依赖内存

- 内存 set 仅作性能优化（减少重复处理次数），不作为唯一去重手段
- JetStream 的 `duplicate_window` (120s) + `Nats-Msg-Id` 是去重的权威来源
- 重启后内存 set 清空，Nats-Msg-Id 去重依然有效

### 7. Stream 保留策略保持 INTEREST，追加 max_age

- `INTEREST`：消息在所有 consumer ack 后删除。正确配置下最安全
- `max_age=7d`：防止孤儿 consumer 钉住消息过久
- 不用 `LIMITS` — 在 `max_consumers=-1` 下，`DiscardPolicy.OLD` 会丢弃慢 consumer 未消费的消息

### 8. Consumer 命名遵循统一前缀规范

```
{服务标识}_{用途}
```

- 服务标识：`A1`、`A2`、`bridge`、`mc_backend`、`observer` 等
- 用途：`consumer_context_ready_xxx`、`consumer_test_passed` 等
- 完整示例见 `doc/系统架构/NATS通信层修复规格.md` §三

### 9. NATS 客户端

- 优先使用 `event_bus.nats_client.NatsClient`（建设中，位于 `repos/event-bus/event_bus/nats_client.py`）
- NatsClient 未完成前，各模块直接使用 `js.publish()` + `js.subscribe()`，但必须遵守本规范全部铁律
- 不在 `NatsClient` 可用前创建临时封装层

### 10. Outbox 消息必须 JetStream + 幂等

- Outbox 记录通过 JetStream 发布，`Nats-Msg-Id` 使用 `outbox-{db_record_id}`
- Outbox retry 周期（31s）完全落在 dedup window（120s）内，Nats-Msg-Id 自动去重
- DB 记录仅在 JetStream ack 成功后标记 published

### 11. 消费端的 ack_wait 和 max_deliver 按 agent 类型区分

- 快 agent（A1、A2、A5、FC）：ack_wait=60s，max_deliver=5
- 慢 agent（A4、A7、A9）：ack_wait=300s，max_deliver=3
- 对于执行超过 ack_wait 的任务，调用 `await msg.in_progress()` 续期

## 代码风格

- 日志信息使用英文，代码注释优先中文
- 错误处理：系统边界（API 入口、外部调用）必须处理，内部模块之间信任调用方
- 不做防御性编程：不验证内部模块的返回值，不处理不可能发生的分支
- 不写 Java 风格的 docstring，函数命名已经说明意图
