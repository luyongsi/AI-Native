# event-bus — NATS JetStream 事件总线

基于 NATS JetStream 的异步事件系统，提供 Publisher / Subscriber / Stream Manager 三大组件。

## 架构

```
EventPublisher → NATS JetStream (AI_NATIVE_EVENTS Stream) → EventSubscriber
```

支持 19 个事件 subject，涵盖 Gate 审批、Agent 状态、需求流转、测试执行、熔断等全部系统事件。

## 快速开始

```python
from event_bus import EventPublisher

pub = EventPublisher(nats_url='nats://localhost:4222')
await pub.connect()
await pub.gate_approved(req_id='REQ-001', gate=0, approver='张三')
```

## 主要事件类型

- `gate.{0-3}.approved/rejected/resubmitted`
- `agent.status.changed`
- `requirement.drafted`
- `test.completed` / `test.failed`
- `loop.tripped`
- `code.pushed` / `pipeline.passed` / `pipeline.failed`
- `context.ready` / `propagation.triggered`

## 依赖

- NATS 2.10+ (JetStream)
- nats-py

## 关联 Spec

spec-11 · Event Bus + 消息协议
