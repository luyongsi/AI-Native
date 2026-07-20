# A6 Spec 拆解 Agent — 完整设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-15
- **状态**: 完整设计文档
- **说明**: A6 负责阶段三的 Spec 拆解，在 Gate1 通过后与 A7 并行启动，将终版 Spec 拆解为可执行的任务 DAG。**本文档中所有数据结构、字段名、枚举值以阶段三数据字典为准。**

---

## 一、通信架构

A6 采用**纯 NATS 调度**模型（与 A2/A4/A5 同构）：

``
┌──────────────┐        NATS         ┌──────────────┐
│ Orchestrator │ ◄─────────────────► │    A6 Agent   │
│              │  context.ready.A6   │              │
│              │  agent.result.A6    │              │
│              │  dag.created        │              │
└──────────────┘                     └──────┬───────┘
                                           │
                                    LLM 调用（内部）
                                           │
                                    ┌──────┴───────┐
                                    │  DeepSeek API │
                                    └──────────────┘
``

- **NATS**：接收 Orchestrator 调度（context.ready.A6），发布完成结果（agent.result.A6）和 DAG 广播事件（dag.created）
- **LLM**：A6 内部通过 DeepSeek API 执行 Spec 拆解
- A6 不与用户直接交互，无 HTTP 接口

---

## 二、A6 在阶段三中的位置

``
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
│  Gate2 拒绝 → A6 + A7 修订（tech_prep_revision_count +1）    │
└────────────────────────────────────────────────────────────┘
         │
         ▼ Gate2 通过后进入阶段四（A9 代码开发）
``

### 核心流程

``
Gate1 pass
  → Orchestrator 并行发布 context.ready.A6 + context.ready.A7
  → A6 执行 Spec 拆解 → 持久化 task_dags + agent_results (A6, cycle)
  → 发布 agent.result.A6 + dag.created

Gate2 拒绝（不管是否要求 a6_rework）
  → Orchestrator 收到 agent.result.gate2.reject
  → 更新 requirements (tech_prep_status='revising', tech_prep_revision_count+=1)
  → 发布 context.ready.A6（含 revision_context: gate2_rejection + a8_report）
  → A6 重新拆解，同一 cycle 内 UPSERT 覆盖 agent_results

A6↔A8 对抗（P1）
  → A8 评审 score ∈ [50, 70) 且 stage3_revision_count < 2
  → Orchestrator 发布 context.ready.A6（含 a8_suggestions）
  → A6 修正 DAG → task_dags.stage3_revision_count += 1
``

---

## 三、职责与设计理念

### 3.1 核心职责

1. **Spec 解析** — 从 context.ready.A6 中提取 spec_package（spec_doc + openapi_schema + erd_diagram + ddl_statements）
2. **LLM 拆解** — 调用 DeepSeek API 将 Spec 拆解为结构化任务 DAG（nodes + edges + critical_path + parallel_groups）
3. **DAG 验证** — 对 LLM 产出执行结构验证（节点数边界、自环检测、edge 引用有效性）
4. **Fallback 拆解** — LLM 不可用时回退到关键词规则拆解（5-8 个默认节点）
5. **修订感知** — Gate2 打回或 A8 对抗时，在 prompt 中注入 revision_context 指引修正

### 3.2 关键设计原则

1. **NATS 驱动**：完全由 Orchestrator 调度，不自行决定启动时机
2. **LLM 主路径 + Fallback 备路径**：LLM 正常走主路径（temperature=0.2），失败自动切换 fallback
3. **产物自持久化**：执行完成后写入 task_dags（新表）+ agent_results (agent_key='A6')
4. **双事件发布**：agent.result.A6（Orchestrator 编排）+ dag.created（A8/下游消费）
5. **幂等写入**：同一 (req_id, agent_key, cycle) 使用 UPSERT（Gate2 打回后覆盖）
6. **范围收敛**：A6 只到 Gate2

---

## 四、核心处理流程

### 4.1 执行阶段

``
阶段 1: 上下文解析     → 提取 spec_package + 检查 revision_context
阶段 2: LLM 拆解 (主)   → 组装 prompt → 调用 DeepSeek → 解析 JSON
阶段 3: Fallback (备)   → LLM 失败时执行关键词规则拆解
阶段 4: DAG 验证        → 节点数/自环/edge 引用/源标记
阶段 5: 持久化 + 发布   → INSERT task_dags + UPSERT agent_results + NATS 双事件
``

### 4.2 各阶段详情

#### 阶段 1 — 上下文解析

``python
def _parse_context(context: dict) -> tuple:
    spec_package = {
        "spec_doc": context["spec_package"]["spec_doc"],
        "openapi_schema": context["spec_package"].get("openapi_schema"),
        "erd_diagram": context["spec_package"].get("erd_diagram"),
        "ddl_statements": context["spec_package"].get("ddl_statements"),
    }
    is_revision = context.get("revision_context", {}).get("is_revision", False)
    revision_info = context.get("revision_context") if is_revision else None
    return spec_package, is_revision, revision_info
``

#### 阶段 2 — LLM 拆解（主路径）

**Prompt 设计要点**：
- 输入 Spec 各章节摘要（限制 6000 tokens）
- 要求产出 nodes（id/type/title/description/complexity/estimated_hours/agent/steps/needs_human_review）+ edges（from/to/dependency_type）+ critical_path + parallel_groups
- 约束：节点数 5-20，高复杂度节点自动标记 needs_human_review
- Revision 模式下注入 revision_context（Gate2 拒绝原因 + A8 建议）

**LLM 参数**：
| 参数 | 值 | 说明 |
|------|-----|------|
| model | deepseek-chat | 复用现有配置 |
| temperature | 0.2 | 低温度保证确定性 |
| max_tokens | 4000 | 足够容纳 DAG JSON |
| timeout | 120s | 单次 LLM 调用超时 |

#### 阶段 3 — Fallback 拆解（备路径）

触发条件：
- LLM API 返回 None/异常
- LLM 返回的 JSON 解析失败

``python
def _fallback_decompose(spec_package: dict) -> dict:
    """基于 Spec 关键词分类，生成 5-8 个默认节点"""
    features = _detect_features(spec_package)  # has_backend / has_frontend / has_db
    nodes = [
        {"id": "planning", "type": "planning", "title": "项目规划与初始化", ...},
        *([{"id": "backend_setup", "type": "backend", ...}] if features["has_backend"] else []),
        *([{"id": "frontend_setup", "type": "frontend", ...}] if features["has_frontend"] else []),
        *([{"id": "db_setup", "type": "database", ...}] if features["has_db"] else []),
        {"id": "integration", "type": "integration", "title": "模块集成", ...},
        {"id": "testing", "type": "testing", "title": "测试与验证", ...},
        {"id": "deployment", "type": "deployment", "title": "部署与发布", ...},
    ]
    # 构建线性依赖 edges
    edges = [{"from": nodes[i]["id"], "to": nodes[i+1]["id"], "dependency_type": "sequential"}
             for i in range(len(nodes)-1)]
    return {"nodes": nodes, "edges": edges, "source": "fallback"}
``

#### 阶段 4 — DAG 验证

| 检查项 | 规则 | 违规处理 |
|--------|------|---------|
| 节点数下界 | nodes.length >= 5 | 回退到 fallback |
| 节点数上界 | nodes.length <= 25 | 回退到 fallback |
| 自环边 | 不允许 from == to | validation 失败，回退 fallback |
| Edge 引用有效性 | edge.from/to 必须在 nodes[].id 中 | validation 失败，回退 fallback |
| 必填字段 | 每个 node 必须有 id/type/title | 补充默认值后继续 |

``python
def _validate_dag(dag: dict) -> dict:
    errors = []
    node_ids = {n["id"] for n in dag.get("nodes", [])}

    if len(dag.get("nodes", [])) < 5:
        errors.append("节点数 < 5，无法完整覆盖 Spec 模块")
    if len(dag.get("nodes", [])) > 25:
        errors.append("节点数 > 25，拆分粒度过细")

    for e in dag.get("edges", []):
        if e["from"] == e["to"]:
            errors.append(f"自环边: {e['from']} → {e['to']}")
        if e["from"] not in node_ids:
            errors.append(f"Edge 引用不存在的源节点: {e['from']}")
        if e["to"] not in node_ids:
            errors.append(f"Edge 引用不存在的目标节点: {e['to']}")

    return {"valid": len(errors) == 0, "errors": errors}
``

#### 阶段 5 — 持久化

``python
async def _persist_results(req_id, session_id, cycle, dag, source):
    # 1. INSERT INTO task_dags（新版本号）
    version = await _get_next_version(req_id, cycle)
    dag_id = await db.insert("task_dags", {
        "req_id": req_id, "cycle": cycle, "version": version,
        "dag_json": dag, "node_count": len(dag["nodes"]),
        "source": source, "stage3_revision_count": 0,
    })

    # 2. UPSERT INTO agent_results
    await _upsert_agent_results(agent_key="A6", req_id=req_id, cycle=cycle,
                                artifact={"dag": dag, "dag_id": dag_id, "source": source})

    # 3. 发布 NATS 事件
    await js.publish("agent.result.A6", payload, headers={"Nats-Msg-Id": f"{req_id}-agent.result.A6-{cycle}"})
    await js.publish("dag.created", dag_payload, headers={"Nats-Msg-Id": f"{req_id}-dag.created-{cycle}"})
``

---

## 五、产出物

A6 产出分别存入 task_dags 表和 agent_results 表：

| 产物 | 存储位置 | 说明 |
|------|---------|------|
| dag_json | task_dags | 完整 DAG JSON（nodes + edges + critical_path + parallel_groups） |
| 
ode_count | task_dags | 节点数量 |
| source | task_dags | 产出来源：llm / fallback |
| stage3_revision_count | task_dags | A6↔A8 对抗轮次计数（Gate2 打回后重置） |
| dag | agent_results.A6.artifact | DAG 快照（用于 Gate2 上下文组装） |
| dag_id | agent_results.A6.artifact | 关联 task_dags 记录 |

### DAG JSON 结构

``json
{
  "nodes": [
    {
      "id": "task-01",
      "type": "backend",
      "title": "用户认证模块",
      "description": "实现 JWT 认证、角色权限检查",
      "complexity": "high",
      "estimated_hours": 8.0,
      "agent": "A9",
      "steps": ["生成 JWT 工具类", "实现中间件", "编写单元测试"],
      "needs_human_review": true
    }
  ],
  "edges": [
    {"from": "task-01", "to": "task-02", "dependency_type": "sequential"}
  ],
  "critical_path": ["task-01", "task-02", "task-05"],
  "parallel_groups": [
    ["task-03", "task-04"]
  ],
  "metadata": {
    "total_estimated_hours": 40.0,
    "human_review_nodes": 2,
    "generated_by": "deepseek-chat",
    "generated_at": "ISO 8601"
  }
}
``

---

## 六、输入/输出接口

### 6.1 输入：context.ready.A6

完整结构见 [数据字典 §4.3](./阶段三-数据字典.md#43-nats-事件)。

| 字段 | 来源 | 说明 |
|------|------|------|
| req_id | 路由键 | 需求 ID |
| session_id | 路由键 | 会话 ID |
| cycle | 路由键 | 当前 cycle |
| spec_package | Orchestrator 组装 | spec_doc + openapi_schema + erd_diagram + ddl_statements |
| revision_context | Gate2 拒绝/A8 对抗 | is_revision + gate2_rejection + a8_report |

### 6.2 输出：agent.result.A6

``json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "dag": {},
  "dag_id": "int",
  "source": "llm",
  "node_count": 12,
  "critical_path_length": 5,
  "total_estimated_hours": 40.0,
  "human_review_nodes": 2,
  "stage3_revision_count": 0,
  "timestamp": "ISO 8601"
}
``

### 6.3 输出：dag.created（广播事件）

``json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "dag_id": "int",
  "version": 1,
  "node_count": 12,
  "source": "llm",
  "timestamp": "ISO 8601"
}
``

> dag.created 是 A6 成果的广播事件，供给下游消费者（如 A8、P2-04 人工通知）订阅。A8 **不直接**订阅此事件作为主触发——A8 由 Orchestrator 通过 GATHER 后发布的 context.ready.A8 触发。

---

## 七、依赖与集成

### 7.1 LLM 依赖

| 依赖 | 用途 | 降级行为 |
|------|------|---------|
| DeepSeek API | Spec → DAG 拆解 | 回退到关键词规则拆解（source='fallback'） |

### 7.2 数据库依赖

| 表 | 操作 | 说明 |
|----|------|------|
| task_dags | INSERT | 每次执行新增一行（version 递增） |
| agent_results | UPSERT | 同一 (req_id, agent_key='A6', cycle) 覆盖 |

### 7.3 降级策略

| 场景 | 行为 | source 标记 |
|------|------|------------|
| DeepSeek API 不可用 | 回退到关键词规则拆解 | fallback |
| DeepSeek 返回格式异常 | JSON 解析失败 → 回退 fallback | fallback |
| DAG 验证失败（节点数越界/自环） | 回退到 fallback | fallback |
| task_dags 写入失败 | 重试 3 次（30s 间隔）→ 仅写入 agent_results | — |
| A6 总体超时（10 分钟） | Orchestrator 重试 1 次 → a6_missing=true | timeout |

---

## 八、NATS 事件协议

| 事件 | 方向 | 触发时机 | Nats-Msg-Id 格式 |
|------|------|---------|-----------------|
| context.ready.A6 | Orchestrator → A6 | Gate1 pass / Gate2 拒绝 / A8 对抗 | {req_id}-context.ready.A6-{cycle} |
| agent.result.A6 | A6 → Orchestrator | DAG 持久化完成 | {req_id}-agent.result.A6-{cycle} |
| dag.created | A6 → 广播 | DAG 持久化完成 | {req_id}-dag.created-{cycle} |

### Consumer 配置

| Consumer | 订阅 Subject | 交付策略 | ack_wait |
|----------|-------------|---------|----------|
| A6_consumer | context.ready.A6 | All, 按 req_id 有序 | 60s |

---

## 九、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| LLM API 不可用 | 120s | 回退到 fallback 规则拆解，status='completed', source='fallback' |
| LLM 返回格式异常 | — | JSON 解析失败 → 回退 fallback |
| DAG 节点数 < 5 | — | 验证失败 → 回退 fallback |
| DAG 节点数 > 25 | — | 验证失败 → 回退 fallback |
| DAG 含自环边 | — | 验证失败 → 回退 fallback |
| task_dags 写入失败 | 30s × 3 | 仅写入 agent_results 兜底 |
| A6 总体超时 | 10min | 重试 1 次，仍失败 → agent_results (status='empty')，a6_missing=true |
| NATS 投递失败 | 30s | Outbox 重试，5 次入死信队列 |
| Gate2 打回修订 | — | 正常执行，注入 revision_context，同 cycle UPSERT |
| A8 对抗修订 | — | 正常执行，注入 a8_suggestions，stage3_revision_count +1 |

---

## 十、DAG 质量与验证规则

### 10.1 节点字段规范

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| id | string | ✅ | 唯一标识，格式 task-NN |
| type | enum | ✅ | planning/backend/frontend/database/integration/testing/deployment |
| title | string | ✅ | 简短标题 |
| description | string | ✅ | 任务详细描述 |
| complexity | enum | ✅ | low/medium/high |
| estimated_hours | float | ✅ | 预估工时（小时） |
| agent | string | | 执行 Agent（默认 A9） |
| steps | string[] | | 子步骤列表 |
| 
eeds_human_review | bool | | complexity=high 自动标记 true |

### 10.2 Edge 字段规范

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| from | string | ✅ | 源节点 id |
| to | string | ✅ | 目标节点 id |
| dependency_type | enum | ✅ | sequential/conditional/parallel |

### 10.3 复杂节点人工介入标记

- DAG 中 complexity = 'high' 的节点自动设置 
eeds_human_review = true
- critical_path 上的 high 复杂度节点在 Gate2 审批页高亮展示
- human_review_nodes 字段统计标记数量，供 Gate2 审批人参考

---

## 十一、实施建议

### Phase 1：核心拆解（Day 1-2）
- A6 Agent 核心流水线：上下文解析 → LLM 拆解 → DAG 验证 → 持久化
- task_dags 表 Migration SQL 执行
- DeepSeek API 集成 + prompt 模板

### Phase 2：Fallback + 修订（Day 3-4）
- 关键词规则 fallback（has_backend / has_frontend / has_db）
- Gate2 打回 revision_context 注入
- 同一 cycle UPSERT 覆盖验证

### Phase 3：A6↔A8 对抗（Day 7-8，P1）
- A8 评审建议注入 prompt
- stage3_revision_count 管理（Gate2 打回后重置）
- 对抗分歧报告生成

---

## 十二、总结

| 维度 | 内容 |
|------|------|
| **入口** | context.ready.A6（Gate1 pass 并行 / Gate2 拒绝 / A8 对抗） |
| **出口** | agent.result.A6（Orchestrator 编排）+ dag.created（下游广播） |
| **核心产物** | 任务 DAG（nodes + edges + critical_path + parallel_groups） |
| **产物存储** | task_dags（每次新增版本）+ agent_results（A6, cycle UPSERT） |
| **交互模式** | 纯 NATS 调度，无用户交互 |
| **LLM 策略** | DeepSeek API（temperature=0.2），失败回退 fallback 规则拆解 |
| **修订机制** | Gate2 拒绝 → 注入 revision_context，同 cycle 覆盖；A8 对抗 → 注入 a8_suggestions |
| **并行关系** | 与 A7 并行启动，不相互等待 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-15
**版本**: v1.0
**数据规范**: [阶段三数据字典](./阶段三-数据字典.md)
