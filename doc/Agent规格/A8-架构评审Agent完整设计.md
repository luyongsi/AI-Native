# A8 架构评审 Agent — 完整设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-15
- **状态**: 完整设计文档（从阶段三-完整设计 §5 + 数据字典 + 开发设计 + 测试设计提取）
- **参考**: [阶段三 数据字典](./阶段三-数据字典.md) · [阶段三 完整设计](./阶段三-完整设计.md) · [系统状态机与信息流设计](../系统架构/系统状态机与信息流设计.md)
- **说明**: A8 是阶段三的**外部自审角色**（独立于 A6 的拆解流程），负责对 A6 产出的 DAG 进行静态分析 + LLM 架构评审，产出评分报告供 Gate2 审批人参考。**本文档中所有数据结构、字段名、枚举值以阶段三数据字典为准。**

---

## 一、通信架构

A8 采用**纯 NATS 调度**模型（与 A2/A4/A5/A6/A7 同构）：

```
┌──────────────┐        NATS         ┌──────────────┐
│ Orchestrator │ ◄─────────────────► │    A8 Agent   │
│              │  context.ready.A8   │              │
│              │  agent.result.A8    │              │
└──────────────┘                     └──────┬───────┘
                                           │
                                    LLM 调用（内部）
                                           │
                                    ┌──────┴───────┐
                                    │  DeepSeek API │
                                    └──────────────┘
```

- **NATS**：接收 Orchestrator 调度（`context.ready.A8`），发布评审报告（`agent.result.A8`）
- **LLM**：A8 内部通过 DeepSeek API 执行架构评审
- A8 不与用户直接交互，无 HTTP 接口

> **触发方式说明**：A8 的主触发方式是 `context.ready.A8`（Orchestrator 在 A6+A7 都完成后 GATHER 发布，携带完整上下文）。`dag.created` 为 A6 的成果广播事件，供其他下游消费者订阅（如 P2-04 的人工通知），**不是 A8 的主触发源**。

---

## 二、A8 在阶段三中的位置

```
阶段三：技术准备
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  ┌─ A6 Spec 拆解 ─┐                                       │
│  │  (并行执行)     │──► A8 架构评审 ──► Gate2 架构确认     │
│  └────────────────┘                                       │
│  ┌─ A7 测试生成 ─┐                                        │
│  │  (并行执行)     │                                       │
│  └────────────────┘                                       │
│                                                            │
│  A6↔A8 对抗循环（P1）:  score ∈ [50,70) 时 ≤2 轮自动修正   │
│  Gate2 拒绝 → A6 + A7 + A8 全部修订（tech_prep_revision_count +1）│
└────────────────────────────────────────────────────────────┘
         │
         ▼ Gate2 通过后进入阶段四（A9 代码开发）
```

### 核心流程

```
A6 + A7 都完成
  → Orchestrator GATHER → 更新 tech_prep_status='reviewing'
  → 发布 context.ready.A8（含 DAG + spec_package）
  → A8 执行三阶段评审（静态分析 → LLM 评审 → 合并报告）
  → 持久化 agent_results (A8, cycle)
  → 发布 agent.result.A8

A6↔A8 对抗（P1）
  → A8 评审 score ∈ [50, 70) 且 stage3_revision_count < 2
  → Orchestrator 发布 context.ready.A6（含 a8_suggestions）
  → A6 修正 DAG → agent.result.A6 → Orchestrator 重新发布 context.ready.A8
  → A8 重新评审 → 重复直至 2 轮上限或 score ≥ 70

Gate2 拒绝
  → A6 + A7 + A8 全部重新执行（tech_prep_revision_count +1）
  → A8 重新接收 context.ready.A8，重新产出评审报告
```

---

## 三、职责与设计理念

### 3.1 核心职责

1. **静态分析** — 纯算法检查：循环依赖检测（DFS 多跳环）、分层违规、DB 回滚缺失
2. **LLM 架构评审** — 调用 DeepSeek API 评审架构分层合理性、安全风险、性能风险、模块耦合度
3. **评分与判定** — 合并静态分析 + LLM 评审结果，计算总分，判定 verdict（pass/fail）
4. **Fallback 降级** — LLM 不可用时仅产出静态分析报告，source 标记 `static_only`

### 3.2 关键设计原则

1. **NATS 驱动**：完全由 Orchestrator 在 GATHER 后调度，不自行决定启动时机
2. **独立自审**：A8 是阶段三的「自审大脑」（对应阶段二 A5），对 A6 产出做出独立评判
3. **环境即裁判**：A8 作为独立外部架构评审角色，在 Gate2 前进行独立裁决
4. **静态分析优先**：静态分析（循环依赖/分层违规/DB回滚）不依赖 LLM，保证基础可靠性
5. **verdict 强制规则**：循环依赖强制 fail（忽略 score），score < 70 也为 fail

---

## 四、核心处理流程

A8 采用**三阶段流水线**：

```
Phase 1: 静态分析（纯算法，不依赖 LLM）
  ├── 循环依赖检测 (DFS 颜色标记法，多跳环)
  ├── 分层违规检测 (前端→DB 直连 / 跨服务边界异常)
  ├── DB 回滚检查 (db 类型节点的 steps 中是否含 rollback/回滚)
  └── 生成静态分析 violations 列表

Phase 2: LLM 架构评审
  ├── 组装 prompt（含 DAG 摘要 + 静态分析结果 + Spec 背景）
  ├── 调用 DeepSeek API (temperature=0.1, max_tokens=2000)
  ├── 检查项: 架构分层合理性 + 安全风险 + 性能风险 + 模块耦合度
  └── 返回 violations + suggestions + summary

Phase 3: 合并报告
  ├── 合并静态分析 violations + LLM violations
  ├── 计算总分（评分规则见 §六）
  ├── 判定 verdict（cycle_detected → fail；score ≥ 70 → pass；否则 fail）
  ├── UPSERT INTO agent_results (agent_key='A8')
  └── 发布 NATS: agent.result.A8
```

### 4.1 静态分析：循环依赖检测（DFS 颜色标记法）

```python
def detect_cycles(nodes: list, edges: list) -> tuple[bool, list]:
    """使用 DFS 颜色标记法检测有向图中的环（支持多跳环）"""
    WHITE, GRAY, BLACK = 0, 1, 2

    graph = defaultdict(list)
    node_ids = {n["id"] for n in nodes}
    for e in edges:
        f, t = e["from"], e["to"]
        if f in node_ids and t in node_ids:
            graph[f].append(t)

    color = defaultdict(lambda: WHITE)
    parent = {}

    def dfs(u):
        color[u] = GRAY
        for v in graph.get(u, []):
            if color[v] == GRAY:
                # 找到环: 从 v 到 u 沿 parent 回溯
                cycle = [v]
                cur = u
                while cur != v:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.append(v)
                return cycle[::-1]
            elif color[v] == WHITE:
                parent[v] = u
                result = dfs(v)
                if result:
                    return result
        color[u] = BLACK
        return None

    for nid in node_ids:
        if color[nid] == WHITE:
            cycle = dfs(nid)
            if cycle:
                return True, cycle

    return False, []
```

> **审计修复说明**：原 A8 代码仅检测自环（`from == to`），本设计使用 DFS 颜色标记法替换，支持任意多跳环检测。源自审计 P0-08。

### 4.2 静态分析：分层违规检测

```python
def check_layer_violations(nodes: list, edges: list) -> list[dict]:
    """检查 DAG 中的分层违规"""
    violations = []

    # 构建 node_id → type 映射
    node_types = {n["id"]: n.get("type", "") for n in nodes}

    for e in edges:
        f, t = e["from"], e["to"]
        f_type = node_types.get(f, "")
        t_type = node_types.get(t, "")

        # 前端直接依赖 DB → critical
        if f_type == "frontend" and t_type in ("database", "db"):
            violations.append({
                "rule": "LAYER-VIO-001",
                "severity": "critical",
                "title": f"前端直连DB: {f} → {t}",
                "detail": "前端节点直接依赖数据库层，应通过 API 接口（backend）间接访问",
                "suggestion": "在前端和 DB 之间插入 backend 节点，通过 REST API 或 RPC 调用",
                "affected_nodes": [f, t],
            })

        # DB 依赖前端 → warning（不太可能但检查）
        if f_type in ("database", "db") and t_type == "frontend":
            violations.append({
                "rule": "LAYER-VIO-002",
                "severity": "warning",
                "title": f"反向依赖: {f}(db) → {t}(frontend)",
                "detail": "数据库节点不应依赖前端展示层",
                "suggestion": "解除反向依赖，数据流向应为 frontend → backend → db",
                "affected_nodes": [f, t],
            })

    return violations
```

### 4.3 静态分析：DB 回滚检查

```python
def check_db_rollback(nodes: list) -> list[dict]:
    """检查 db 类型节点的 steps 中是否包含回滚/rollback 方案"""
    issues = []

    for n in nodes:
        if n.get("type") not in ("database", "db"):
            continue

        steps = n.get("steps", [])
        has_rollback = any(
            "rollback" in str(s).lower() or "回滚" in str(s)
            for s in steps
        )

        if not has_rollback:
            issues.append({
                "rule": "DB-ROLLBACK-001",
                "severity": "warning",
                "title": f"DB 节点 {n['id']} 缺少回滚方案",
                "detail": f"节点 '{n.get('title','')}' 的 steps 中未包含数据库迁移的回滚（down migration）方案",
                "suggestion": "为每个 DDL 变更补充反向迁移步骤（如 ALTER TABLE DROP COLUMN → 回滚: ALTER TABLE ADD COLUMN）",
                "affected_nodes": [n["id"]],
            })

    return issues
```

> **审计修复说明**：原 A8 代码 `_check_db_rollback` 检查 `tasks` 而非 `steps`，导致检查永不生效。本设计修正为检查 `nodes[*].steps`。源自审计 P0-07。

---

## 五、LLM 评审设计

### 5.1 Prompt 模板

```
你是资深架构师。对以下 DAG 进行架构评审。

DAG 摘要:
- 节点 ({node_count}): {nodes_summary}
- 依赖边 ({edge_count}): {edges_summary}
- 关键路径: {critical_path}

Spec 背景:
{spec_summary}

静态分析结果:
- 循环依赖: {{"detected": true/false, "path": [...]}}
- 分层违规: {layer_violation_count} 项
- DB 回滚缺失: {db_rollback_issue_count} 项

输出 JSON（只输出 JSON）：
{
  "score": 0-100,
  "violations": [
    {
      "rule": "SEC-AUTH-001|SEC-SQL-001|SEC-DATA-001|SEC-KEY-001|PERF-N1-001|PERF-CACHE-001|PERF-PAGE-001",
      "severity": "critical|warning",
      "title": "标题（10字内）",
      "detail": "详细说明",
      "suggestion": "修复建议（可操作的具体方案）",
      "affected_nodes": ["node-id"]
    }
  ],
  "suggestions": ["全局建议1", "全局建议2"],
  "summary": "评审总结（50-100字，含最关键的发现和建议）"
}

检查要点:
1. 安全红线（必查）:
   - 认证/授权是否覆盖所有 API？
   - DAG 中是否有 SQL 拼接/注入风险节点？
   - 是否有敏感数据（密码/Token/PII）明文传输/存储？
   - 是否有硬编码密钥/AK/SK？
2. 性能风险:
   - 是否存在 N+1 查询模式（大量循环调 API）？
   - 热点数据是否缺少缓存策略？
   - 列表接口是否包含分页？
3. 架构分层合理性:
   - 前端/后端/DB 分层是否清晰？
   - 是否有跨服务/跨模块的不合理直接依赖？

只输出 JSON，不要任何其他文字
```

### 5.2 LLM 调用参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 模型 | DeepSeek API (chat) | — |
| temperature | 0.1 | 低温度确保障审稳定性 |
| max_tokens | 2000 | 足够输出完整评审报告 |
| 超时 | 120s | — |

---

## 六、评分规则

### 6.1 扣分规则

| 扣分项 | 分值 | 说明 |
|--------|------|------|
| 基础分 | 100 | — |
| 循环依赖（每项） | -30 | 且强制 verdict='fail' |
| critical violation（每项） | -10 | 安全红线 / 严重分层违规 |
| warning violation（每项） | -5 | DB回滚缺失 / 性能风险 |
| 最低分 | 0 | — |

### 6.2 Verdict 判定

```python
if cycle_detected:
    verdict = "fail"  # 强制，忽略 score
elif score >= 70:
    verdict = "pass"
else:
    verdict = "fail"
```

### 6.3 安全红线（独立检查，Gate2 审批页突出展示）

| 检查项 | 检查方式 | 触发条件 | severity |
|--------|---------|---------|----------|
| 认证/授权缺失 | LLM 评审 | DAG 中无 auth 相关节点 | critical |
| SQL 注入风险 | LLM 评审 | DAG 中有 db 节点但 steps 中无参数校验/ORM | critical |
| 敏感数据暴露 | LLM 评审 | Spec 包含 PII/密码字段但无加密/脱敏节点 | critical |
| 硬编码密钥 | LLM 评审 | steps 中出现 key/secret/token 字面量 | critical |

### 6.4 性能风险（警告级）

| 检查项 | 检查方式 | severity |
|--------|---------|----------|
| N+1 查询风险 | LLM 评审 | warning |
| 缺少缓存层 | LLM 评审 | warning |
| 未考虑分页 | LLM 评审 | warning |

---

## 七、输入/输出接口

### 7.1 context.ready.A8 输入结构

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "dag": {
    "nodes": [
      {
        "id": "task-01",
        "type": "backend",
        "title": "用户认证模块",
        "description": "实现 JWT 认证流程",
        "complexity": "high",
        "estimated_hours": 8.0,
        "agent": "A9",
        "steps": ["设计 JWT token 结构", "实现 login API", "实现 middleware"],
        "needs_human_review": true
      }
    ],
    "edges": [
      {"from": "task-01", "to": "task-02", "dependency_type": "sequential"}
    ],
    "critical_path": ["task-01", "task-02", "task-05"],
    "parallel_groups": [["task-03", "task-04"]],
    "metadata": {
      "total_nodes": 8,
      "total_hours": 45.0,
      "critical_path_length": 5,
      "human_review_nodes": 2
    }
  },
  "spec_package": {
    "spec_doc": {},
    "openapi_schema": {},
    "erd_diagram": {},
    "ddl_statements": "string"
  },
  "a6_missing": false,
  "a7_missing": false
}
```

### 7.2 agent.result.A8 输出结构

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "review": {
    "verdict": "pass|fail",
    "score": 85,
    "checks": {
      "static": {
        "cycle_detected": false,
        "cycle_path": null,
        "layer_violations": [],
        "db_rollback_issues": []
      },
      "llm": {
        "available": true,
        "violations": [],
        "suggestions": [],
        "summary": "架构分层清晰，安全措施到位"
      }
    },
    "violations": [
      {
        "source": "static|llm",
        "rule": "LAYER-VIO-001|DB-ROLLBACK-001|SEC-AUTH-001|...",
        "severity": "critical|warning",
        "title": "违规标题",
        "detail": "详细说明",
        "suggestion": "修复建议",
        "affected_nodes": ["task-01"]
      }
    ],
    "suggestions": ["全局建议"],
    "summary": "评审总结（50-100字）",
    "source": "llm|static_only",
    "stage3_revision_count": 0
  },
  "timestamp": "ISO 8601"
}
```

---

## 八、依赖与集成

### 8.1 LLM 依赖

| 依赖 | 用途 | 降级行为 |
|------|------|---------|
| DeepSeek API | 架构评审（安全/性能/分层/耦合） | 仅产出静态分析结果，source 标记 `static_only` |

### 8.2 数据库依赖

| 表 | 操作 | 说明 |
|----|------|------|
| `agent_results` | UPSERT | 同一 (req_id, agent_key='A8', cycle) 覆盖 |

### 8.3 降级策略

| 场景 | 行为 | source 标记 |
|------|------|------------|
| DeepSeek API 不可用 | 仅产出静态分析报告，verdict 基于静态分析 | `static_only` |
| DeepSeek 返回格式异常 | JSON 解析失败 → 仅静态分析 | `static_only` |
| DAG 为空（A6 超时降级） | 跳过评审，agent_results status='skipped' | — |
| A8 总体超时（10 分钟） | Orchestrator 重试 1 次 → a8_missing=true | `timeout` |
| NATS 投递失败 | 30s | Outbox 重试，5 次入死信队列 |

---

## 九、NATS 事件协议

| 事件 | 方向 | 触发时机 | Nats-Msg-Id 格式 |
|------|------|---------|-----------------|
| `context.ready.A8` | Orchestrator → A8 | A6+A7 都完成后 GATHER | `{req_id}-context.ready.A8-{cycle}` |
| `agent.result.A8` | A8 → Orchestrator | 评审报告持久化完成 | `{req_id}-agent.result.A8-{cycle}` |

### Consumer 配置

| Consumer | 订阅 Subject | 交付策略 | ack_wait |
|----------|-------------|---------|----------|
| `A8_consumer` | `context.ready.A8` | All, 按 req_id 有序 | 300s（慢 agent） |

> `ack_wait=300s`：A8 属于慢 agent（含 LLM 调用 + 静态分析），需较长 ack_wait。

---

## 十、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| LLM API 不可用 | 120s | 仅静态分析报告，verdict 基于静态分析评分，source='static_only' |
| LLM 返回格式异常 | — | JSON 解析失败 → 仅静态分析 |
| DAG 为空（A6 超时） | — | 跳过评审，agent_results status='skipped' |
| 循环依赖检测到环 | — | 强制 verdict='fail'，生成含环路径的 violation |
| A8 总体超时 | 10min | 重试 1 次，仍失败 → agent_results (status='skipped')，a8_missing=true |
| NATS 投递失败 | 30s | Outbox 重试，5 次入死信队列 |
| context.ready.A8 中 DAG 格式异常 | — | 仅基于 spec_package 执行 LLM 评审，静态分析标记为 skipped |

---

## 十一、A6↔A8 对抗循环设计（P1）

### 11.1 触发条件

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

### 11.2 执行流程

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

> **`stage3_revision_count` 语义**：计数器追踪当前 Gate2 审批轮次内的 A6↔A8 对抗轮次（每轮 +1）。Gate2 打回后进入新审批周期，计数器**重置为 0**。不跨 Gate2 审批周期累加。

### 11.3 分歧报告结构

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
  "recommendation": "建议 Gate2 审批人关注安全模块拆分粒度，在拒绝原因中明确要求包含独立的 security_setup 任务节点"
}
```

---

## 十二、实施建议

### Phase 1：静态分析核心（Day 1-2）
- DFS 循环依赖检测（替换旧自环检测）
- 分层违规检测（前端→DB 直连 / 反向依赖）
- DB 回滚检查（修正 steps 字段路径）
- 静态分析报告结构输出

### Phase 2：LLM 评审集成（Day 3-4）
- DeepSeek API 集成 + prompt 模板
- 静态分析 → LLM 评审合并
- 评分规则 + verdict 判定
- Fallback 降级（static_only）

### Phase 3：对抗循环 + 集成（Day 7-8，P1）
- A6↔A8 对抗循环触发逻辑
- stage3_revision_count 管理
- 分歧报告生成
- Gate2 审批页 A8 报告展示集成

---

## 十三、总结

| 维度 | 内容 |
|------|------|
| **入口** | `context.ready.A8`（A6+A7 都完成后 Orchestrator GATHER 发布） |
| **出口** | `agent.result.A8`（Orchestrator 编排 → Gate2 审批） |
| **核心产物** | 架构评审报告（verdict + score + violations + suggestions + summary） |
| **产物存储** | `agent_results`（A8, cycle UPSERT） |
| **交互模式** | 纯 NATS 调度，无用户交互 |
| **LLM 策略** | DeepSeek API（temperature=0.1），失败降级 static_only |
| **评分机制** | 基础 100 分，循环依赖 -30（强制 fail），critical violation -10，warning -5 |
| **Verdict** | 循环依赖 → 强制 fail；score ≥ 70 → pass；否则 fail |
| **对抗循环** | P1，score ∈ [50,70) 时 ≤2 轮 A6↔A8 自动修正 |
| **安全红线** | 4 项必查（认证/授权/SQL注入/敏感数据/硬编码密钥），Gate2 独立展示 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-15
**版本**: v1.0
**数据规范**: [阶段三数据字典](./阶段三-数据字典.md)
