# 死循环深度分析报告

## 问题摘要

**LLM 调用总数**: 5,060 次  
**时间跨度**: 2026-07-01 08:19 - 2026-07-02 09:56  
**最严重Agent**: A6 (1,066次 LLM调用，7,891次处理)  
**最严重需求**: 91ba906c (2,208次 LLM调用)

---

## 根本原因

### 🔴 P0 问题：NATS 消息堆积 + 无退避机制

#### 问题机制

```
1. A5 设计评审完成 → 发布 review.completed 到 NATS

2. A6 订阅 review.completed

3. NATS 队列中有大量历史消息未消费

4. A6 启动时收到所有堆积消息

5. A6 处理每条消息：
   - pass=True → 调用 LLM 分解（耗时~30s）
   - pass=False → 跳过分解（瞬间完成）
   - 发布 agent.result.A6
   
6. NATS 立即推送下一条消息

7. 循环往复，无法停止
```

#### 时间戳证据

```log
2026-07-01 08:19:28,380 [A6] Received NATS message
2026-07-01 08:19:28,380 [A6] Review NOT passed, skipping
2026-07-01 08:19:28,380 [A6] Published result
2026-07-01 08:19:28,380 [A6] Received NATS message  ← 同一毫秒！
2026-07-01 08:19:28,380 [A6] Review NOT passed, skipping
2026-07-01 08:19:28,380 [A6] Published result
2026-07-01 08:19:28,381 [A6] Received NATS message  ← 1ms后
```

**说明**: 消息是批量推送，A6 立即处理，形成死循环

---

## 详细数据分析

### 时间段分布

```
08:49-09:30  正常  (1-2次/分钟)
09:31-09:50  加速  (4-10次/分钟)
09:54-09:55  爆发  (260次/2分钟 = 130次/分钟)
09:56       停止  (Agent Workers 被停止)
```

### Agent 调用统计

| Agent | LLM调用 | 处理次数 | 说明 |
|-------|---------|---------|------|
| **A6** | 1,066 | 7,891 | review.completed 消息堆积 |
| **A5** | 834 | N/A | 设计评审 |
| **A1** | 181 | N/A | 需求接入 |
| **A4** | 103 | N/A | Spec 撰写 |
| **A7** | 1 | N/A | 测试生成 |
| **A12** | 1 | N/A | 代码审查 |

**base_worker**: 3,701次（所有 Agent 的基础调用）

### 需求调用统计

| 需求 ID | LLM调用 | 说明 |
|---------|---------|------|
| **91ba906c** | 2,208 | 历史需求，反复循环 |
| bf12295c | 156 | 测试需求 |
| aaaaaaaa | 56 | 新创建需求 |

---

## 问题根源：需求 91ba906c

### 为什么这个需求调用这么多？

**循环路径**:
```
A4 生成 Spec (version N)
  ↓
A5 设计评审
  ↓ pass=False
发布 review.completed
  ↓
A6 收到消息，跳过分解
  ↓ 但 A4 又重新生成
A4 生成 Spec (version N+1)
  ↓
A5 再次评审
  ↓ pass=False 或 pass=True
发布 review.completed
  ↓
A6 收到消息
  ↓ 如果 pass=True
调用 LLM 分解任务
  ↓
发布 dag.created
  ↓
... 继续循环
```

### A6 的处理逻辑

```python
# a6_spec_decomposer.py (伪代码)

async def handle_review_completed(message):
    scores = message['scores']
    passed = message['pass']
    
    if passed:
        # 调用 LLM（耗时30秒）
        dag = await llm_decompose(spec)
        await publish('dag.created', dag)
    else:
        # 跳过分解（瞬间完成）
        logger.info("Review NOT passed, skipping")
    
    # 立即处理下一条消息（问题所在！）
```

**问题**: 
- 无消息确认延迟
- 无批量处理
- 无退避机制
- 历史消息全部立即处理

---

## 爆发点分析（09:54-09:55）

### 触发因素

1. **09:54:10** - 手动触发 A6/A7/A9/A11/A12
2. **NATS 发送测试消息**
3. **A6 收到新消息 + 历史堆积消息**
4. **LLM API 开始返回 502**
5. **A6 疯狂重试**
6. **2分钟内 260 次 LLM 调用**

### 日志证据

```log
09:54:11,858 [A6] LLM call (502)
09:54:11,971 [A6] LLM call (502)
09:54:12,039 [A6] LLM call (502)
09:54:12,236 [A6] LLM call (502)
09:54:13,111 [A6] LLM call (502)
09:54:13,482 [A6] LLM call (502)
... 持续2分钟
```

**每秒 2-3 次调用，持续 120 秒 = 240-360 次**

---

## LLM API 状态

### 502 Bad Gateway 原因

**可能原因**:
1. **并发过高** - 瞬间大量请求
2. **API 网关限流** - 超过 QPS 限制
3. **后端服务过载** - 无法处理请求
4. **网络问题** - 连接超时

**证据**:
- 09:54 之前：200 OK（正常）
- 09:54-09:56：502 Bad Gateway（过载）
- 部分请求仍返回 200（说明不是完全宕机）

---

## 解决方案

### 🔴 P0 - 立即修复

#### 1. NATS 消息确认机制

```python
# base_worker.py

async def _handle(msg):
    try:
        # 处理消息
        await self.execute(...)
        
        # 添加延迟，避免立即处理下一条
        await asyncio.sleep(0.5)  # 500ms 延迟
        
    except Exception as e:
        logger.error(f"Message handling error: {e}")
        # 不要立即重试
        await asyncio.sleep(5)
```

#### 2. A6 批量处理

```python
# a6_spec_decomposer.py

class A6SpecDecomposer:
    def __init__(self):
        self.pending_messages = []
        self.last_process_time = 0
    
    async def handle_review_completed(self, message):
        self.pending_messages.append(message)
        
        # 每 5 秒或 10 条消息才处理一次
        now = time.time()
        if (now - self.last_process_time > 5) or (len(self.pending_messages) >= 10):
            await self._batch_process()
            self.last_process_time = now
    
    async def _batch_process(self):
        # 去重：同一个 req_id 只处理最新的
        unique_messages = {}
        for msg in self.pending_messages:
            req_id = msg['req_id']
            unique_messages[req_id] = msg
        
        # 批量处理
        for msg in unique_messages.values():
            await self._process_one(msg)
        
        self.pending_messages.clear()
```

#### 3. LLM 重试退避

```python
# 所有 Agent 的 LLM 调用

async def call_llm_with_backoff(prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = await llm_client.chat(prompt)
            return result
        except Exception as e:
            if '502' in str(e):
                # 指数退避
                wait_time = (2 ** attempt)  # 1s, 2s, 4s
                logger.warning(f"LLM 502, retry {attempt+1}/{max_retries} after {wait_time}s")
                await asyncio.sleep(wait_time)
            else:
                raise
    
    # 重试耗尽，使用 fallback
    logger.error("LLM retries exhausted, using fallback")
    return fallback_response()
```

#### 4. NATS 消息过滤

```python
# a6_spec_decomposer.py

async def handle_review_completed(self, message):
    req_id = message['req_id']
    
    # 检查是否是历史消息
    req = await db.get_requirement(req_id)
    if req.status in ['blocked', 'done']:
        logger.info(f"Skipping completed/blocked req {req_id}")
        return  # 直接跳过，不处理
    
    # 检查最近是否处理过
    last_process_key = f"a6_processed_{req_id}"
    if await redis.exists(last_process_key):
        ttl = await redis.ttl(last_process_key)
        if ttl > 0:
            logger.info(f"Recently processed {req_id}, skip (TTL: {ttl}s)")
            return
    
    # 处理消息
    await self._decompose(message)
    
    # 标记已处理（5分钟内不重复处理）
    await redis.setex(last_process_key, 300, '1')
```

### 🟡 P1 - 监控告警

#### 5. LLM 调用频率监控

```python
# 添加到所有 Agent

class RateLimiter:
    def __init__(self, max_calls_per_minute=30):
        self.max_calls = max_calls_per_minute
        self.calls = []
    
    async def acquire(self):
        now = time.time()
        
        # 清理 1 分钟前的记录
        self.calls = [t for t in self.calls if now - t < 60]
        
        if len(self.calls) >= self.max_calls:
            logger.error(f"Rate limit exceeded: {len(self.calls)} calls/min")
            raise Exception("LLM rate limit exceeded")
        
        self.calls.append(now)

# 使用
rate_limiter = RateLimiter(max_calls_per_minute=30)
await rate_limiter.acquire()
result = await llm_client.chat(...)
```

#### 6. NATS 队列监控

```python
# 添加监控脚本

import nats

async def monitor_nats_queue():
    nc = await nats.connect('nats://localhost:4222')
    js = nc.jetstream()
    
    while True:
        # 检查队列长度
        info = await js.stream_info('agent-stream')
        pending = info.state.messages
        
        if pending > 100:
            logger.warning(f"NATS queue backlog: {pending} messages")
            # 发送告警
        
        await asyncio.sleep(60)
```

---

## 测试验证

### 修复后预期行为

**A6 处理 review.completed 消息**:
```
收到消息 → 检查是否历史消息 → 是 → 跳过
                              → 否 → 检查是否最近处理 → 是 → 跳过
                                                    → 否 → 批量缓存
                                                           等待 5s 或 10 条
                                                           去重处理
                                                           标记已处理
```

### 预期数据

```
A6 处理次数: 7,891 → <100
LLM 调用: 1,066 → <50
死循环: 是 → 否
```

---

## 总结

### 问题本质

**不是 LLM API 的问题，而是消息队列管理的问题！**

1. NATS 消息堆积未清理
2. A6 订阅了高频事件（review.completed）
3. 无消息去重机制
4. 无处理延迟
5. 无退避机制

### 修复优先级

| 优先级 | 修复项 | 预期效果 |
|-------|--------|----------|
| P0 | NATS 消息过滤（历史消息） | 减少 95% 无效处理 |
| P0 | A6 批量处理 + 去重 | 减少 90% LLM 调用 |
| P0 | LLM 重试退避 | 避免 502 雪崩 |
| P1 | 调用频率限制 | 保护 API |
| P1 | 队列监控 | 提前告警 |

### 验证标准

修复后运行 24 小时：
- ✅ A6 处理次数 < 100
- ✅ LLM 调用次数 < 1000
- ✅ 无 502 错误
- ✅ NATS 队列长度 < 50

---

**分析完成！根本原因已定位！** 🎯
