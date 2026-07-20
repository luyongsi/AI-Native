# A8 架构评审 Agent — 开发设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-17
- **状态**: 开发设计
- **原则**: 以阶段三数据字典为唯一数据规范源；所有数据结构、字段名、枚举值严格对齐数据字典

---

## 一、现状分析与差距

### 1.1 当前实现 vs 目标架构

| 维度 | 当前实现 (`a8_architecture_expert.py`) | 目标架构（规格 v1.0） | 差距 |
|------|----------------------------------------|---------------------|------|
| **事件发布** | `review.completed`（旧格式） | `agent.result.A8`（符合数据字典 §6.5） | 需改为新事件名 |
| **循环依赖检测** | DFS 颜色标记法（已实现） | DFS 多跳环检测 | 已达标 |
| **分层违规检测** | frontend→db 直接依赖检测（已实现） | 与规格一致 | 已达标 |
| **DB 回滚检查** | 检查 node.steps 字段（已修复） | 检查 steps 中的 rollback/回滚关键词 | 已达标 |
| **安全风险检查** | 无 | LLM 评审安全风险（P1-03） | 需新增 LLM 安全 prompt |
| **性能风险检查** | 无 | LLM 评审性能风险（P1-04） | 需新增 LLM 性能 prompt |
| **LLM 评审** | 已有基本框架 | 完整 prompt：安全 + 性能 + 耦合度 + 架构合理性 | 需增强 prompt |
| **评分合并** | 已实现 | 静态分析扣分 + LLM 评分合并（100 分制） | 已达标 |
| **空 DAG 处理** | 已实现 | status='skipped'，不阻塞流程 | 已达标 |
| **事件订阅** | `dag.created` | `context.ready.A8`（主入口） | 需改订阅 subject |

### 1.2 现有可复用模块

| 模块 | 文件 | 功能 | 改造要点 |
|------|------|------|---------|
| `ArchitectureExpertAgent` | `a8_architecture_expert.py` | Agent 主体骨架 | 改事件发布格式 + 增强 LLM prompt |
| `_check_cycles` | 同上 | DFS 多跳环检测 | 保持不变 |
| `_check_layer_violations` | 同上 | 分层违规检测 | 保持不变 |
| `_check_db_rollback` | 同上 | DB 回滚检查 | 保持不变 |
| `BaseAgentWorker` | `base_worker.py` | NATS 订阅/发布 + 生命周期管理 | 扩展 `_upsert_agent_results` |

---

## 二、改造方案

### 2.1 核心流水线

A8 的核心执行逻辑分为三个阶段：

```
context.ready.A8 到达
  │
  ├─ 空 DAG 检查
  │     dag.nodes 为空 → status='skipped'，reason='empty_dag'
  │     发布 agent.result.A8 (verdict=skipped) → 流程继续
  │
  ├─ Stage 1: 静态分析（纯算法，不依赖 LLM）
  │     _check_cycles(): DFS 颜色标记法检测多跳环
  │     _check_layer_violations(): frontend→db 跨层依赖
  │     _check_db_rollback(): db 节点 steps 中无 rollback/回滚关键词
  │
  ├─ Stage 2: LLM 评审
  │     调用 DeepSeek API (temperature=0.1)
  │     构建 Prompt：DAG 结构 + 静态分析结果 + 安全/性能/耦合/架构合理性
  │     LLM 返回 violations + suggestions + score + summary
  │     LLM 失败 → _fallback_review()：仅静态分析报告
  │
  └─ Stage 3: 合并报告 + 评分判定
        合并静态分析违规 + LLM 违规（去重）
        循环依赖强制扣 30 分
        评分 ≥ 70 且无循环 → verdict=pass
        评分 < 70 或有循环 → verdict=fail → gate2_required=true
        发布 agent.result.A8 → msg.ack()
```

### 2.2 关键模块描述

#### 2.2.1 循环依赖检测 (`_check_cycles`)

```python
def _check_cycles(self, nodes: list, edges: list) -> tuple[bool, list]:
    """使用 DFS 颜色标记法检测有向图中的环（支持多跳环）"""
    WHITE, GRAY, BLACK = 0, 1, 2

    graph = defaultdict(list)
    node_ids = {n.get("id") for n in nodes if n.get("id")}
    for e in edges:
        f, t = e.get("from", ""), e.get("to", "")
        if f in node_ids and t in node_ids:
            graph[f].append(t)

    color = defaultdict(lambda: WHITE)
    parent = {}

    def dfs(u):
        color[u] = GRAY
        for v in graph.get(u, []):
            if color[v] == GRAY:
                # 找到环: 沿 parent 回溯
                cycle = [v]
                cur = u
                while cur != v:
                    cycle.append(cur)
                    cur = parent.get(cur, v)
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

#### 2.2.2 分层违规检测 (`_check_layer_violations`)

```python
def _check_layer_violations(self, nodes: list, edges: list) -> list:
    """检查分层违规（前端→DB 直接依赖 / DB→前端反向依赖）"""
    violations = []
    node_map = {n.get("id"): n for n in nodes if n.get("id")}

    for e in edges:
        f = node_map.get(e.get("from"))
        t = node_map.get(e.get("to"))
        if not f or not t:
            continue

        # 前端直接依赖 DB → critical
        if f.get("type") == "frontend" and t.get("type") == "db":
            violations.append({
                "rule": "LAYER-VIO-001",
                "severity": "critical",
                "title": f"跨层调用: {f['id']}(frontend) → {t['id']}(db)",
                "detail": "前端节点直接依赖数据库层，应通过 API 接口（backend）间接访问",
                "suggestion": "在前端和 DB 之间插入 backend 节点，通过 REST API 或 RPC 调用",
                "affected_nodes": [f.get("id"), t.get("id")],
            })

        # DB 依赖前端 → warning（反向依赖）
        if f.get("type") == "db" and t.get("type") == "frontend":
            violations.append({
                "rule": "LAYER-VIO-002",
                "severity": "warning",
                "title": f"反向依赖: {f['id']}(db) → {t['id']}(frontend)",
                "detail": "数据库节点不应依赖前端展示层",
                "suggestion": "解除反向依赖，数据流向应为 frontend → backend → db",
                "affected_nodes": [f.get("id"), t.get("id")],
            })

    return violations
```

#### 2.2.3 DB 回滚检查 (`_check_db_rollback`)

```python
def _check_db_rollback(self, nodes: list) -> list:
    """检查 db 类型节点的 steps 中是否包含回滚/rollback 方案"""
    issues = []

    for n in nodes:
        if n.get("type") != "db":
            continue

        steps = n.get("steps", [])
        if not steps:
            issues.append({
                "rule": "DB-ROLLBACK-001",
                "severity": "warning",
                "title": f"DB 节点缺少 steps 定义: {n.get('id')}",
                "detail": "db 类型节点的 steps 字段为空，无法验证回滚方案",
                "suggestion": "在 steps 中补充 migration 和 rollback 步骤",
                "affected_nodes": [n.get("id")],
            })
            continue

        has_rollback = any(
            isinstance(s, str) and any(kw in s.lower() for kw in ("rollback", "回滚", "revert", "down"))
            or (isinstance(s, dict) and any(kw in str(s).lower() for kw in ("rollback", "回滚", "revert", "down")))
            for s in steps
        )

        if not has_rollback:
            issues.append({
                "rule": "DB-ROLLBACK-001",
                "severity": "warning",
                "title": f"DB 节点缺少回滚方案: {n.get('id')}",
                "detail": "DB 变更操作缺少对应的 rollback/down migration 步骤",
                "suggestion": "为每个 DDL 变更补充反向 migration（如 DROP TABLE / DROP COLUMN 等）",
                "affected_nodes": [n.get("id")],
            })

    return issues
```

#### 2.2.4 LLM 评审 (`_llm_review`)

```python
async def _llm_review(self, req_id: str, dag: dict, nodes: list, edges: list,
                       cycle_detected: bool, cycle_path: list,
                       layer_violations: list, db_issues: list,
                       context_package: dict) -> dict | None:
    """LLM 架构评审：安全风险 + 性能风险 + 耦合度 + 架构合理性"""
    context_text = await self.prepare_llm_context(context_package, state="reviewing")

    prompt = f"""你是一位资深架构师，请对以下 DAG 任务拆解进行架构评审。

## DAG 结构
- 节点数: {len(nodes)}
- 边数: {len(edges)}
- 关键路径: {dag.get('critical_path', [])}

## 预检测结果
- 循环依赖: {'发现: ' + ' → '.join(cycle_path) if cycle_detected else '无'}
- 分层违规: {len(layer_violations)} 项
- DB 回滚缺失: {len(db_issues)} 项

## 评审维度
1. **安全风险 (SEC)**: 认证缺失、权限泄露、敏感数据暴露、注入风险
2. **性能风险 (PERF)**: N+1 查询、缺少缓存、串行化瓶颈、大数据量无分页
3. **耦合度 (COUP)**: 循环依赖、模块边界不清、过度拆分
4. **架构合理性 (ARCH)**: 技术选型、分层设计、可扩展性、可维护性

## 上下文
{context_text[:4000]}

请以 JSON 格式返回评审报告:
```json
{{
  "score": 85,
  "violations": [
    {{"rule": "SEC-001", "severity": "high", "title": "...", "detail": "...", "suggestion": "...", "affected_nodes": []}},
    {{"rule": "PERF-001", "severity": "medium", "title": "...", "detail": "...", "suggestion": "...", "affected_nodes": []}},
    {{"rule": "COUP-001", "severity": "warning", "title": "...", "detail": "...", "suggestion": "...", "affected_nodes": []}}
  ],
  "suggestions": ["建议1", "建议2"],
  "summary": "整体架构评审结论..."
}}
```
"""
    try:
        result = await self.call_llm(prompt, temperature=0.1, max_tokens=4000)
        return json.loads(result)
    except (ConnectionError, TimeoutError):
        return None
    except json.JSONDecodeError:
        return None
```

#### 2.2.5 Fallback 评审 (`_fallback_review`)

```python
def _fallback_review(self, nodes: list, edges: list,
                      cycle_detected: bool, cycle_path: list,
                      layer_violations: list, db_issues: list) -> dict:
    """LLM 不可用时，仅基于静态分析产出评审报告"""
    violations = []
    for lv in layer_violations:
        violations.append(lv)
    for di in db_issues:
        violations.append(di)

    # 静态分析评分
    score = 100
    if cycle_detected:
        score -= 30
    score -= len(layer_violations) * 10
    score -= len(db_issues) * 5
    score = max(score, 0)

    return {
        "score": score,
        "violations": violations,
        "suggestions": ["[Fallback] LLM 不可用，仅完成静态分析"],
        "summary": f"[Fallback] 静态分析完成：循环依赖={cycle_detected}，分层违规={len(layer_violations)}，DB 回滚问题={len(db_issues)}",
    }
```

---

## 三、数据库

### 3.1 agent_results 写入

```sql
-- UPSERT 语句（agent_key='A8'）
INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact, created_at, updated_at)
VALUES ($1, 'A8', $2, $3, $4::jsonb, NOW(), NOW())
ON CONFLICT (req_id, agent_key, cycle)
DO UPDATE SET
    artifact = EXCLUDED.artifact,
    status = EXCLUDED.status,
    updated_at = NOW();
```

### 3.2 artifact 结构

```json
{
  "review": {
    "review_id": "rev-{req_id}-20260717103000",
    "verdict": "pass",
    "score": 85,
    "gate2_required": false,
    "checks": {
      "cycle_dependency": {"passed": true, "count": 0},
      "layer_violation": {"passed": true, "count": 0},
      "db_rollback": {"passed": true, "count": 0},
      "security_risk": {"passed": true, "count": 0},
      "performance_risk": {"passed": true, "count": 0}
    },
    "violations": [],
    "suggestions": ["建议增加缓存层"],
    "summary": "架构设计合理，无重大风险",
    "reviewed_at": "2026-07-17T10:30:00Z"
  }
}
```

---

## 四、NATS 事件 payload 对齐

### 4.1 订阅：context.ready.A8

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "dag": {
    "nodes": [
      {"id": "task-01", "type": "planning", "title": "技术方案设计", "steps": [...]},
      {"id": "task-02", "type": "backend", "title": "API 开发", "steps": [...]},
      {"id": "task-03", "type": "db", "title": "数据库迁移", "steps": ["CREATE TABLE...", "回滚: DROP TABLE..."]}
    ],
    "edges": [
      {"from": "task-01", "to": "task-02"},
      {"from": "task-01", "to": "task-03"}
    ],
    "critical_path": ["task-01", "task-02"]
  },
  "spec_package": {
    "spec_doc": {...},
    "openapi_schema": {...},
    "erd_diagram": {...}
  }
}
```

### 4.2 发布：agent.result.A8

```python
# 发布时 js.publish() 携带 Nats-Msg-Id header
headers = {"Nats-Msg-Id": f"{req_id}-agent.result.A8-{cycle}"}
payload = {
    "req_id": req_id,
    "session_id": session_id,
    "cycle": cycle,
    "status": "completed",           # completed | skipped
    "verdict": "pass",               # pass | fail | skipped
    "score": 85,
    "gate2_required": False,
    "checks": {
        "cycle_dependency": {"passed": True, "count": 0},
        "layer_violation": {"passed": True, "count": 0},
        "db_rollback": {"passed": True, "count": 0},
        "security_risk": {"passed": True, "count": 0},
        "performance_risk": {"passed": True, "count": 0}
    },
    "violation_count": 0,
    "critical_count": 0,
    "timestamp": "2026-07-17T10:30:00Z"
}

await js.publish(
    "agent.result.A8",
    json.dumps(payload).encode(),
    headers=headers,
    stream="AI_NATIVE_EVENTS"
)
```

### 4.3 Consumer 配置

| Consumer | 订阅 Subject | DeliverPolicy | ack_wait | max_deliver |
|----------|-------------|---------------|----------|-------------|
| `A8_consumer` | `context.ready.A8` | All, 按 req_id 有序 | 60s | 5 |

```python
# Consumer 创建
config = ConsumerConfig(
    durable_name="A8_consumer",
    deliver_policy=DeliverPolicy.ALL,
    ack_wait=60,
    max_deliver=5,
)
await js.add_consumer("AI_NATIVE_EVENTS", config, filter_subjects=["context.ready.A8"])
```

---

## 五、违规规则枚举

### 5.1 静态分析违规

| 规则 ID | 严重度 | 说明 | 扣分 |
|---------|--------|------|------|
| `DAG-CYCLE-001` | critical | 循环依赖（多跳环） | -30 |
| `LAYER-VIO-001` | critical | 前端→DB 跨层直接依赖 | -10/项 |
| `LAYER-VIO-002` | warning | DB→前端反向依赖 | -5/项 |
| `DB-ROLLBACK-001` | warning | DB 迁移无回滚方案 | -5/项 |

### 5.2 LLM 评审违规（P1）

| 规则 ID | 严重度 | 说明 |
|---------|--------|------|
| `SEC-001` | critical | 缺少认证/授权机制 |
| `SEC-002` | high | 敏感数据未加密存储 |
| `SEC-003` | medium | 输入校验缺失（注入风险） |
| `PERF-001` | high | N+1 查询或缺少缓存 |
| `PERF-002` | medium | 大数据量操作无分页 |
| `PERF-003` | warning | 可并行任务被串行化 |
| `COUP-001` | medium | 模块间循环依赖 |
| `COUP-002` | warning | 节点粒度过细（过度拆分） |
| `ARCH-001` | high | 技术选型不合理 |
| `ARCH-002` | medium | 缺少可扩展性设计 |
| `ARCH-003` | warning | 可维护性问题 |

---

## 六、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| DeepSeek API 连接失败 | 120s | 回退到 `_fallback_review()`（仅静态分析） |
| DeepSeek 返回非 JSON | — | JSON 解析失败 → `_fallback_review()` |
| 空 DAG 输入 | — | status='skipped'，agent.result.A8 含 empty_dag 原因 |
| agent_results UPSERT 冲突 | — | ON CONFLICT DO UPDATE 幂等覆盖 |
| A8 总体超时 | 10min | Orchestrator 重试 1 次 → 仍超时 → agent_results (status='skipped')，a8_missing=true |
| NATS publish 失败 | 30s | Outbox 重试，5 次入死信队列 |
| A6↔A8 对抗修订（P1） | — | 注入 a8_suggestions，stage3_revision_count +1 |

---

## 七、实施计划

### Phase 1：静态分析 + LLM 集成（~2 天）
- [ ] 事件订阅迁移：`dag.created` → `context.ready.A8`
- [ ] 事件发布迁移：`review.completed` → `agent.result.A8`
- [ ] `_check_cycles`：DFS 多跳环检测（已有，验证）
- [ ] `_check_layer_violations`：分层违规检测（已有，验证）
- [ ] `_check_db_rollback`：steps 字段回滚检查（已有，验证）
- [ ] `_llm_review`：安全/性能/耦合/架构四维 LLM prompt
- [ ] `_fallback_review`：LLM 不可用时仅静态分析
- [ ] 评分合并与 verdict 判定

### Phase 2：事件对齐 + 异常（~1 天）
- [ ] agent.result.A8 payload 对齐数据字典 §6.5
- [ ] Consumer 配置调整（durable_name=A8_consumer, ack_wait=60s）
- [ ] 空 DAG 处理完善
- [ ] 超时降级链路

### Phase 3：P1 功能（~2 天）
- [ ] LLM 安全风险检查（`_check_security_risks`）
- [ ] LLM 性能风险检查（`_check_performance_risks`）
- [ ] A6↔A8 对抗循环（a8_suggestions 注入 + 分歧报告）

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-17
**版本**: v1.0
