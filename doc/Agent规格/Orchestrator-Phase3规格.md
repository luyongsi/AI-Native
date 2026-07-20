# Orchestrator Phase 3 编排规格

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-15
- **状态**: 完整编排规格
- **说明**: 本文档描述 Orchestrator 在阶段三（技术准备阶段）的完整编排逻辑。

---

## 一、阶段三概览

```
阶段三：技术准备 (tech_prep)
┌───────────────────────────────────────────────────────────────────────┐
│                                                                       │
│  Gate1 pass                                                           │
│    │                                                                  │
│    ├── context.ready.A6 ───► A6 Spec 拆解 ──► agent.result.A6         │
│    │                              │                  │                │
│    ├── context.ready.A7 ───► A7 测试生成 ──► agent.result.A7          │
│    │                              │                  │                │
│    │    (A6 + A7 并行，Orchestrator GATHER 两者都完成)                 │
│    │                              │                                   │
│    │                    context.ready.A8                               │
│    │                              │                                   │
│    │                    A8 架构评审 ──► agent.result.A8                │
│    │                              │                                   │
│    │                    build_context → context.ready.gate2            │
│    │                              │                                   │
│    │                         【Gate2】                                 │
│    │                        /  pass  \  reject                         │
│    │                         │        │                               │
│    │                    phase=    tech_prep_revision_count += 1        │
│    │                   development 重发 context.ready.A6/A7           │
│    │                         │                                        │
│    │                    context.ready.A9                               │
│                                                                       │
│  A6↔A8 对抗循环（P1）: score ∈ [50,70) 时 ≤2 轮自动修正              │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 二、状态机 Transition 详表

Orchestrator 在阶段三管理的 tech_prep_status 子状态：

| 当前状态 | 触发事件 | 目标状态 | 动作 |
|---------|---------|---------|------|
| — (Gate1 pass) | `agent.result.gate1.pass` | `decomposing` | 1. 更新 `phase='tech_prep'`, `tech_prep_revision_count=0`<br/>2. 并行发布 `context.ready.A6` + `context.ready.A7` |
| `decomposing` | `agent.result.A6` | `decomposed` | 若 A7 未完成 → 仅记录 A6 结果 |
| `decomposing` | `agent.result.A7` | `test_ready` | 若 A6 未完成 → 仅记录 A7 结果 |
| `decomposed` | `agent.result.A7` | `reviewing` | A6+A7 都完成 → GATHER → 发布 `context.ready.A8` |
| `test_ready` | `agent.result.A6` | `reviewing` | A6+A7 都完成 → GATHER → 发布 `context.ready.A8` |
| `reviewing` | `agent.result.A8` | `reviewing` | 1. 累积 A8 产物<br/>2. 检查 A6↔A8 对抗循环<br/>3. 若不需要对抗 → build_context → 发布 `context.ready.gate2` |
| `reviewing` (对抗中) | `agent.result.A6` (修订版) | `reviewing` | 重新发布 `context.ready.A8`（触发 A8 复评审） |
| `reviewing` | `agent.result.gate2.pass` | `tech_prep_completed` | 1. 更新 `phase='development'`<br/>2. 发布 `context.ready.A9` |
| `reviewing` | `agent.result.gate2.reject` | `revising` | 1. `tech_prep_revision_count += 1`<br/>2. 根据 `a6_rework`/`a7_rework` 并行重发 `context.ready.A6`/`context.ready.A7` |
| `revising` | [A6/A7 re-dispatch] | `decomposing` | 1. 发布 `context.ready.A6`/`context.ready.A7` 携带 `revision_context`<br/>2. `tech_prep_status = 'decomposing'` |

---

## 三、GATHER 逻辑

A6 和 A7 并行启动后，不相互等待。但 A8 必须在两者都完成后才能启动。Orchestrator 通过 GATHER 模式实现：

```python
class Phase3Orchestrator:
    def __init__(self):
        self._a6_done = False
        self._a7_done = False
        self._a6_result = None
        self._a7_result = None

    async def on_agent_result_a6(self, payload: dict):
        self._a6_done = True
        self._a6_result = payload
        await self._update_status("decomposed")
        await self._try_gather()

    async def on_agent_result_a7(self, payload: dict):
        self._a7_done = True
        self._a7_result = payload
        await self._update_status("test_ready")
        await self._try_gather()

    async def _try_gather(self):
        if self._a6_done and self._a7_done:
            await self._update_status("reviewing")
            a8_context = await build_context(
                target="A8",
                dag=self._a6_result.get("dag"),
                test_summary=self._a7_result.get("test_summary")
            )
            await publish_nats("context.ready.A8", a8_context)
```

| 场景 | 行为 |
|------|------|
| A6 先完成，A7 仍在执行 | A6 结果被记录，tech_prep_status → `decomposed`，等待 A7 |
| A7 先完成，A6 仍在执行 | A7 结果被记录，tech_prep_status → `test_ready`，等待 A6 |
| A6 和 A7 同时完成 | GATHER，tech_prep_status → `reviewing`，发布 `context.ready.A8` |
| A6 超时但 A7 正常 | A6 结果包含 `a6_missing=true`，GATHER 时 A8 接收降级上下文 |
| A7 超时但 A6 正常 | A7 结果包含 `a7_missing=true`，GATHER 时 A8 接收降级上下文 |

---

## 四、build_context 组装（阶段三专用）

### 4.1 A8 上下文（reviewing 状态）

| 上下文层 | 内容 | 来源 |
|---------|------|------|
| requirement | title, spec_sections, acceptance_criteria | `requirements` 表 |
| artifact | A4 openapi, A4 erd, A4 ddl_statements, A5 review_scores, A5 issues, A6 dag, A7 test_summary | `agent_results` (A4, A5, A6, A7) |
| knowledge | relevant_code, dependency_graph, best_practices | 知识库 MCP (top-5) |
| environment | project.repo_url, project.tech_stack | `.ai-native/project-config.yaml` |
| rework | gate2_rejection (若为修订) | `context.ready.A8` payload 中的 `revision_context` |

Token 预算：**8000**（与 A5 同属于 reviewing 状态）。

### 4.2 Gate2 上下文（build_context after A8）

| 上下文层 | 内容 | 来源 |
|---------|------|------|
| requirement | title, acceptance_criteria | `requirements` 表 |
| artifact | A6 DAG 完整结果, A7 测试用例摘要 + 类型分布, A8 评审报告 (verdict + score + violations + suggestions) | `agent_results.A6/A7/A8` |
| knowledge | — (Gate2 审批人不需要知识库内容) | — |
| environment | project.tech_stack | `.ai-native/project-config.yaml` |
| decisions | Gate1 审批通过的架构决策 | `spec.decisions` JSONB |
| rework | 上一轮 Gate2 拒绝原因 (若修订) | `context.ready.gate2` payload |

### 4.3 A6/A7 修订上下文（revising → decomposing）

Orchestrator 在修订的 `context.ready.A6`/`context.ready.A7` 的 `revision_context` 中注入：
```json
{
  "revision_context": {
    "is_revision": true,
    "revision_round": 1,
    "rejection": {
      "reject_reasons": [...],
      "revision_guidance": "请补充独立的 DB migration 任务节点..."
    },
    "a8_report": { ... },
    "previous_results": { "a6": {...}, "a7": {...} }
  }
}
```

---

## 五、A6↔A8 对抗循环（P1）

### 5.1 触发条件

```python
def should_trigger_antagonism(a8_result: dict) -> bool:
    score = a8_result.get("score", 0)
    revision_count = a8_result.get("stage3_revision_count", 0)
    return (
        50 <= score < 70
        and revision_count < 2
        and not a8_result.get("cycle_detected", False)
    )
```

### 5.2 执行流程

```
A8 评审完成
  → should_trigger_antagonism?
  ├── 是:
  │     → Orchestrator 发布 context.ready.A6（含 a8_suggestions）
  │     → task_dags.stage3_revision_count += 1（记录在下一版 DAG 中）
  │     → A6 接收建议，修正 DAG
  │     → A6 发布 agent.result.A6（修订版，同 cycle）
  │     → Orchestrator 重新发布 context.ready.A8
  │     → A8 重新评审
  │     → 若仍触发 → 重复（直至 2 轮上限）
  └── 否:
        ├── score < 50 或循环依赖 → 生成《架构分歧报告》→ Gate2 人工裁决
        ├── 达到 2 轮上限 → 生成《架构分歧报告》→ Gate2 人工裁决
        └── score ≥ 70 → 正常流转 Gate2
```

> **`stage3_revision_count` 语义**：该计数器追踪当前 Gate2 审批轮次内的 A6↔A8 对抗轮次（每轮 +1）。Gate2 打回后进入新审批周期，计数器**重置为 0**。

### 5.3 分歧报告结构

```json
{
  "report_type": "architecture_deadlock",
  "rounds_completed": 2,
  "a6_versions": [
    {"version": 1, "dag_summary": "..."},
    {"version": 2, "dag_summary": "..."},
    {"version": 3, "dag_summary": "..."}
  ],
  "a8_reviews": [
    {"round": 1, "score": 58, "key_violations": ["..."], "suggestions": ["..."]},
    {"round": 2, "score": 62, "key_violations": ["..."], "suggestions": ["..."]}
  ],
  "recurring_issues": ["A6 持续忽略安全认证模块的拆分"],
  "recommendation": "建议 Gate2 审批人关注安全模块拆分粒度"
}
```

---

## 六、Gate2 pass/reject 路由

### 6.1 Pass 路由

```
agent.result.gate2.pass
  → Orchestrator 更新: phase = 'development', tech_prep_status = 'tech_prep_completed'
  → 发布 context.ready.A9 → 阶段四开始
```

### 6.2 Reject 路由

```
agent.result.gate2.reject (含 a6_rework / a7_rework)
  → Orchestrator 更新: tech_prep_revision_count += 1, tech_prep_status = 'revising'
  → 根据 a6_rework / a7_rework 并行重发:
      context.ready.A6 (含 revision_context)
      context.ready.A7 (含 revision_context)
  → tech_prep_status = 'decomposing'
```

### 6.3 a6_rework / a7_rework 独立控制

| a6_rework | a7_rework | 场景 | 说明 |
|-----------|-----------|------|------|
| `true` | `true` | 完整打回 | DAG 和测试用例都需要修订（默认） |
| `true` | `false` | 仅 DAG 修订 | 测试用例覆盖足够，只需修正 DAG 结构 |
| `false` | `true` | 仅测试修订 | DAG 结构合理，但测试覆盖不足 |
| `false` | `false` | 无效组合 | 前端应阻止此组合（至少一项为 true） |

### 6.4 Gate2 SLA 处理

| 时间点 | 动作 | 实现方式 |
|--------|------|---------|
| 审批创建 | 系统发送通知（飞书/邮件） | MC Backend API → 消息服务 |
| 2h | 预警通知（提醒审批人 + 抄送直属上级） | Orchestrator Gate SLA Activity (T1) |
| 4h | 超时升级通知（通知技术总监） | Orchestrator Gate SLA Activity (T1) |
| 4h+ | **持续等待人工审批，不自动通过** | Orchestrator 无限等待 Gate signal |

---

## 七、超时与降级处理

### 7.1 Agent 超时配置

| Agent | 超时阈值 | 重试次数 | 最终降级 |
|-------|---------|---------|---------|
| A6 | 10 分钟 | 1 次 | agent_results status='empty', a6_missing=true |
| A7 | 10 分钟 | 1 次 | agent_results status='skipped', a7_missing=true |
| A8 | 10 分钟 | 1 次 | agent_results status='skipped', a8_missing=true |

### 7.2 降级流转

```python
_AGENT_TIMEOUT_SECONDS = 600  # 10 分钟

def _handle_agent_timeout(agent_key: str):
    match agent_key:
        case "A6":
            write_agent_results(agent_key="A6", status="empty")
            if a7_done:
                publish("context.ready.A8")  # 携带 a6_missing=true
        case "A7":
            write_agent_results(agent_key="A7", status="skipped")
            if a6_done:
                publish("context.ready.A8")  # 携带 a7_missing=true
        case "A8":
            write_agent_results(agent_key="A8", status="skipped")
            publish("context.ready.gate2")  # 携带 a8_missing=true
```

### 7.3 降级场景总结

| 场景 | Gate2 审批页表现 | 审批人可操作 |
|------|-----------------|-------------|
| A6 缺失 | 标记 ⚠️"A6 DAG 未产出"，仅看 A7 + 空 DAG 提示 | 可拒绝（触发重新执行）或风险接受通过 |
| A7 缺失 | 标记 ⚠️"A7 测试用例未产出"，仅看 DAG + A8 报告 | 可拒绝（触发重新执行）或风险接受通过 |
| A8 缺失 | 无评审报告区，标记"A8 架构评审未执行" | 可拒绝（触发重新执行）或风险接受通过 |

---

## 八、NATS 事件协议（阶段三）

### 8.1 Orchestrator 发布的事件

| 事件 | 触发时机 | Nats-Msg-Id 格式 |
|------|---------|-----------------|
| `context.ready.A6` | Gate1 pass / Gate2 拒绝 / A8 对抗 | `{req_id}-context.ready.A6-{cycle}` |
| `context.ready.A7` | Gate1 pass / Gate2 拒绝 | `{req_id}-context.ready.A7-{cycle}` |
| `context.ready.A8` | A6+A7 GATHER / A6↔A8 对抗复评 | `{req_id}-context.ready.A8-{cycle}` |
| `context.ready.gate2` | A8 评审完成/对抗循环结束 | `{req_id}-context.ready.gate2-{cycle}` |
| `context.ready.A9` | Gate2 pass | `{req_id}-context.ready.A9-{cycle}` |

### 8.2 Orchestrator 订阅的事件

| 事件 | 来源 | 处理 |
|------|------|------|
| `agent.result.gate1.pass` | Gate1 | 进入阶段三，并行启动 A6+A7 |
| `agent.result.A6` | A6 | 记录结果，GATHER 检查 |
| `agent.result.A7` | A7 | 记录结果，GATHER 检查 |
| `agent.result.A8` | A8 | 检查对抗循环 → build_context → Gate2 |
| `agent.result.gate2.pass` | Gate2 | 更新 phase='development'，启动 A9 |
| `agent.result.gate2.reject` | Gate2 | tech_prep_revision_count += 1，重发 A6/A7 |

### 8.3 新 Consumer 配置

| Consumer | 订阅 Subjects | ack_wait | max_deliver |
|----------|-------------|----------|-------------|
| `orch_consumer_agent_results` | `agent.result.*` | 60s | 5 |
| `orch_consumer_gate_results` | `agent.result.gate*.*` | 60s | 5 |

---

## 九、与阶段一/阶段二的差异

| 维度 | 阶段一/二 | 阶段三 |
|------|----------|--------|
| **并行模式** | A3∥A4 (阶段二) | A6∥A7 (并行拆解+测试) |
| **自审脑** | A5（设计检查） | A8（架构评审） |
| **对抗循环** | 无 | A6↔A8 ≤2 轮 P1 对抗 |
| **Gate 打回** | 打回上游 Agent 重做 | 支持 a6_rework/a7_rework 独立控制 |
| **降级路径** | 无 | A6/A7/A8 超时降级，Gate2 可见缺失标记 |
| **SLA 机制** | Gate1: 4h SLA | Gate2: 2h 预警 + 4h 升级，不自动通过 |

---

## 十、实施建议

### Phase 1：核心编排（Day 1-3）
- 阶段三 Transition Table 实现
- GATHER 逻辑（A6 + A7 并行等待 → 发布 context.ready.A8）
- build_context 组装 for A8 和 Gate2
- Gate2 pass/reject 路由

### Phase 2：降级 + SLA（Day 4-5）
- Agent 超时处理（A6/A7/A8 timeout → 降级 Gate2）
- Gate2 SLA 预警/升级通知
- a6_rework/a7_rework 独立控制路由

### Phase 3：对抗循环（Day 7-8，P1）
- A6↔A8 对抗循环触发 + stage3_revision_count 管理
- 分歧报告生成 → Gate2 嵌入
- 完整对抗循环 → Gate2 全链路联调

---

## 十一、总结

| 维度 | 内容 |
|------|------|
| **入口** | `agent.result.gate1.pass`（Gate1 审批通过） |
| **第一阶段** | 并行启动 A6 + A7，GATHER 后触发 A8 |
| **第二阶段** | A8 架构评审 → 对抗循环检查 → build_context → Gate2 |
| **Pass 出口** | `phase='development'` → `context.ready.A9` |
| **Reject 出口** | `tech_prep_revision_count += 1` → 重发 A6/A7 |
| **对抗循环** | P1，A6↔A8 ≤2 轮，分歧报告 → Gate2 人工裁决 |
| **降级策略** | 各 Agent 超时后 Gate2 可见缺失标记，审批人自行判断 |
| **SLA** | Gate2: 2h 预警 + 4h 升级，**不自动通过** |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-15
**版本**: v1.0
**数据规范**: [阶段三数据字典](./阶段三-数据字典.md)
