# LLM 死循环问题最终诊断报告

## 问题发现

LLM API 在没有任何用户任务的情况下被反复调用，截至检查时已超过 **5,000 次**，且每 30 秒仍在持续增长。

## 根本原因

**Temporal Workflow 的死循环** — 具体是 4 个历史 Workflow（需求 `91ba906c-13bb-437d-a0dd-68d9b35512fb`）从 **6月30号** 运行至今（超过 2 天），不断在 `analyzing` 和 `designing ↔ reviewing` 阶段之间循环。

### 循环机制

```
Workflow analyze 阶段 (inner loop, max=2)
  → dispatch_agent → NATS context.ready.requirement_intake
  → A1 接受 → 调用 LLM (1次)
  → Gate 创建 → 等待5分钟 → 超时 → approved=False
  → 重新进入 analyze (inner loop 第2轮)
  → dispatch_agent → A1 → LLM (2次)
  → Gate 创建 → 等待 → 超时
  → 推进到 designing
  
Workflow designing ↔ reviewing (debate loop, max=3)
  → dispatch_agent → NATS context.ready.spec_writer
  → A4 生成 Spec → review.start
  → A5 设计评审 → review.completed
  → A6 收到 review.completed → 调用 LLM
  → Gate 创建 → 等待 → 超时 → approved=False
  → 再次进入 designing/debate
  → ... 无限重复
```

### 数据证明

**Temporal 活跃 Workflow**:
```
req-91ba906c-1782892599 (running since 2026-07-01 07:56)
req-91ba906c-1782816793 (running since 2026-06-30 10:53)
req-91ba906c-1782814932 (running since 2026-06-30 10:22)
req-91ba906c (running since 2026-06-30 07:58)
```

**LLM 调用统计**:
- 总调用: 5,060+ 次
- 需求 91ba906c: 2,208 次（43%）
- A6: 1,066 次（最高）
- A5: 834 次
- A1: 181 次

**时间分布**:
- 6月30-7月1日: 正常频率（每分钟 1-2 次）
- 7月2日 09:54-09:55: 爆发 260 次（NatS 堆积恢复 + LLM 502 重试）

## 修复措施

### 已实施（短期修复）:
1. ✅ **终止 4 个活跃 Workflow** — 通过 Temporal API terminate
2. ✅ **停止 Orchestrator Worker** — 不再产生新消息
3. ✅ **NATS 重启** — 清除堆积的消费者和消息
4. ✅ **ephemeral consumer** — 修改 `base_worker.py` 始终使用 ephemeral 而非 durable

### 仍需修复（长期修复）:
1. 🔴 **requirement_workflow.py** — 减少循环次数或增加退出条件
2. 🔴 **Gate 自动批准** — 目前所有 Gate 等待 5 分钟超时，应支持 API 立即批准
3. 🟡 **LLM 重试退避** — 添加指数退避机制
4. 🟡 **消息去重** — 对同一 req_id 的重复消息进行过滤

## 修复效果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| LLM 调用/分钟 | 130 | 12（逐渐减少） |
| 活跃 Workflow | 4 | 0 |
| Agent 状态 | 死循环 | 正常 |

## 结论

死循环已基本解决。剩余的少量 LLM 调用是 Agents 重启后处理 NATS 中残余的启动消息，正在逐渐归零。根本修复需要修改 **Orchestrator Workflow 的状态机逻辑** 和 **Gate 审批机制**。
