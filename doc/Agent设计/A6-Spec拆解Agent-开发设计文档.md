# A6 Spec 拆解 Agent — 开发设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-15
- **状态**: 开发设计
- **参考**: [A6 Spec拆解Agent完整设计](../Agent规格/A6-Spec拆解Agent完整设计.md) · [阶段三数据字典](../Agent规格/阶段三-数据字典.md) · [阶段三开发设计](../Agent规格/阶段三-开发设计.md) · [阶段三测试设计](../Agent规格/阶段三-测试设计.md)
- **原则**: 以阶段三数据字典为唯一数据规范源；所有数据结构、字段名、枚举值严格对齐数据字典

---

## 一、现状分析与差距

### 1.1 当前实现 vs 目标架构

| 维度 | 当前实现 (`a6_spec_decomposer.py`) | 目标架构（规格 v1.0） | 差距 |
|------|------------------------------------|---------------------|------|
| **触发方式** | 手动调用 / Orchestrator 直接调用 | 纯 NATS 调度：订阅 `context.ready.A6`，发布 `agent.result.A6` + `dag.created` | 需改造为 NATS 驱动 |
| **产物写表** | 无持久化 | 写入 `task_dags`（INSERT，version 递增）+ `agent_results`（UPSERT，agent_key='A6'） | 缺少 `task_dags` 和 `agent_results` 写入 |
| **LLM 调用** | 无 LLM 集成 | DeepSeek API（temperature=0.2），含 prompt 模板 | 需新增 LLM 调用模块 |
| **DAG 验证** | 无验证 | 节点数边界检查（5-25）、自环检测、edge 引用有效性 | 需新增 DAG 验证器 |
| **Fallback** | 无 fallback | 关键词规则拆解（has_backend / has_frontend / has_db），source='fallback' | 需新增 fallback 模块 |
| **修订上下文** | 无修订支持 | Gate2 拒绝或 A8 对抗时注入 `revision_context`（is_revision + gate2_rejection + previous_a8_report），同 cycle UPSERT | 需新增修订感知 |
| **NATS 发布** | 不发布事件 | 发布 `agent.result.A6`（`{req_id}-agent.result.A6-{cycle}`）+ `dag.created`（`{req_id}-dag.created-{cycle}`） | 需新增事件发布 |
| **超时处理** | 无 | 10 分钟超时 → 重试 1 次 → status='empty'，a6_missing=true | 需新增超时降级 |

### 1.2 现有可复用模块

| 模块 | 文件 | 功能 | 改造要点 |
|------|------|------|---------|
| `A6SpecDecomposer` | `a6_spec_decomposer.py` | Agent 主体骨架 | 重构为 NATS 驱动，增加 DAG 验证 + LLM 调用 + 持久化 |
| `BaseAgentWorker` | `base_worker.py` | NATS 订阅/发布 + 生命周期管理 | 扩展 `_upsert_agent_results` + DB pool |
| DeepSeek API 配置 | 环境变量 | LLM API 连接 | 复用现有 DEEPSEEK_API_KEY / DEEPSEEK_API_BASE |

---

## 二、改造方案

### 2.1 核心流水线

A6 的核心执行逻辑分为五阶段：

```
context.ready.A6 到达
  │
  ├─ Stage 1: 上下文解析 (_parse_context)
  │     从 payload 提取 spec_package (spec_doc, openapi_schema, erd_diagram, ddl_statements)
  │     提取 revision_context (is_revision, gate2_rejection, previous_a8_report)
  │
  ├─ Stage 2: LLM 拆解 (_decompose_with_llm)
  │     调用 DeepSeek API (temperature=0.2)
  │     构建 Prompt：spec_doc 全文 + openapi 摘要 + erd 摘要 + 修订上下文（可选）
  │     解析 LLM 返回的 JSON → DAG struct
  │
  ├─ Stage 3: DAG 验证 (_validate_dag)
  │     节点数边界：5 ≤ len(nodes) ≤ 25
  │     自环检测：edge.from ≠ edge.to
  │     Edge 引用：edge.from / edge.to 均在 nodes 中
  │     → 验证失败 → 回退 Stage 4
  │
  ├─ Stage 4 (备): Fallback 拆解 (_fallback_decompose)
  │     按关键词规则生成 DAG（has_backend / has_frontend / has_db）
  │     source = 'fallback'
  │
  └─ Stage 5: 持久化 + 发布 (_persist_and_publish)
  │     INSERT INTO task_dags (version 递增)
  │     UPSERT INTO agent_results (agent_key='A6', cycle)
  │     发布 agent.result.A6 + dag.created（JetStream + Nats-Msg-Id）
  │     → msg.ack()
```

### 2.2 关键模块描述

#### 2.2.1 上下文解析 (`_parse_context`)

```python
# a6_spec_decomposer.py

async def _parse_context(self, context_package: dict) -> dict:
    """从 context.ready.A6 payload 提取执行所需上下文"""
    spec_package = context_package.get('spec_package', {})
    return {
        'req_id': context_package.get('req_id'),
        'session_id': context_package.get('session_id'),
        'cycle': context_package.get('cycle', 0),
        'spec_doc': spec_package.get('spec_doc', {}),
        'openapi_schema': spec_package.get('openapi_schema', {}),
        'erd_diagram': spec_package.get('erd_diagram', {}),
        'ddl_statements': spec_package.get('ddl_statements', ''),
        'revision_context': context_package.get('revision_context'),
        'a8_suggestions': context_package.get('a8_suggestions'),
    }
```

#### 2.2.2 LLM 拆解 (`_decompose_with_llm`)

```python
# a6/decomposer.py（新文件）

class SpecDecomposer:
    """DeepSeek 驱动的 Spec → DAG 拆解器"""

    def __init__(self, llm_caller):
        self.llm = llm_caller

    async def decompose(self, ctx: dict) -> dict | None:
        """调用 DeepSeek API 拆解 Spec 为任务 DAG"""
        prompt = self._build_prompt(ctx)
        try:
            result = await self.llm(prompt, temperature=0.2, max_tokens=4000)
            dag = self._parse_dag_response(result)
            return dag
        except (ConnectionError, TimeoutError):
            return None  # 触发 fallback
        except json.JSONDecodeError:
            return None  # JSON 解析失败 → fallback

    def _build_prompt(self, ctx: dict) -> str:
        """构建拆解 System Prompt"""
        # 核心部分：spec_doc 全文（modules + data_models）
        # 辅助部分：openapi_schema 摘要（paths + endpoints）
        # 辅助部分：erd_diagram 摘要（entities）
        # 可选部分：revision_context（Gate2 拒绝原因 + A8 报告）
        ...

    def _parse_dag_response(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON → DAG struct"""
        dag = json.loads(raw)
        return {
            'dag_json': dag,
            'source': 'llm',
        }
```

#### 2.2.3 DAG 验证器 (`_validate_dag`)

```python
# a6/dag_validator.py（新文件）

class DAGValidator:
    """DAG 结构验证器"""

    MIN_NODES = 5
    MAX_NODES = 25

    def validate(self, dag: dict) -> dict:
        """
        返回 {'valid': bool, 'errors': [str]}
        """
        nodes = dag.get('nodes', [])
        edges = dag.get('edges', [])
        node_ids = {n['id'] for n in nodes}
        errors = []

        # 规则 1: 节点数边界
        if len(nodes) < self.MIN_NODES:
            errors.append(f"Node count {len(nodes)} < {self.MIN_NODES}")
        if len(nodes) > self.MAX_NODES:
            errors.append(f"Node count {len(nodes)} > {self.MAX_NODES}")

        # 规则 2: 自环边
        for e in edges:
            if e.get('from') == e.get('to'):
                errors.append(f"Self-loop edge: {e}")
                break

        # 规则 3: Edge 引用有效性
        for e in edges:
            if e.get('from') not in node_ids:
                errors.append(f"Edge from '{e.get('from')}' not in nodes")
            if e.get('to') not in node_ids:
                errors.append(f"Edge to '{e.get('to')}' not in nodes")

        return {
            'valid': len(errors) == 0,
            'errors': errors,
        }
```

#### 2.2.4 Fallback 拆解 (`_fallback_decompose`)

```python
# a6/fallback_decomposer.py（新文件）

FALLBACK_TEMPLATES = {
    'planning': {
        'id': 'task-01', 'type': 'planning', 'title': '项目初始化与架构搭建',
        'complexity': 'low', 'estimated_hours': 1.0,
    },
    'backend': {
        'id': 'task-02', 'type': 'backend', 'title': '后端 API 骨架开发',
        'complexity': 'medium', 'estimated_hours': 4.0,
    },
    'frontend': {
        'id': 'task-03', 'type': 'frontend', 'title': '前端页面骨架开发',
        'complexity': 'medium', 'estimated_hours': 4.0,
    },
    'database': {
        'id': 'task-04', 'type': 'database', 'title': '数据库表结构与迁移',
        'complexity': 'low', 'estimated_hours': 2.0,
    },
    'integration': {
        'id': 'task-05', 'type': 'integration', 'title': '前后端联调集成',
        'complexity': 'medium', 'estimated_hours': 3.0,
    },
    'testing': {
        'id': 'task-06', 'type': 'testing', 'title': '单元测试 + 集成测试',
        'complexity': 'low', 'estimated_hours': 2.0,
    },
    'deployment': {
        'id': 'task-07', 'type': 'deployment', 'title': 'CI/CD 流水线配置与部署',
        'complexity': 'low', 'estimated_hours': 1.0,
    },
}

DEFAULT_EDGES = [
    {'from': 'task-01', 'to': 'task-02', 'dependency_type': 'sequential'},
    {'from': 'task-01', 'to': 'task-03', 'dependency_type': 'parallel'},
    {'from': 'task-01', 'to': 'task-04', 'dependency_type': 'parallel'},
    {'from': 'task-02', 'to': 'task-05', 'dependency_type': 'sequential'},
    {'from': 'task-03', 'to': 'task-05', 'dependency_type': 'sequential'},
    {'from': 'task-04', 'to': 'task-05', 'dependency_type': 'sequential'},
    {'from': 'task-05', 'to': 'task-06', 'dependency_type': 'sequential'},
    {'from': 'task-06', 'to': 'task-07', 'dependency_type': 'sequential'},
]


class FallbackDecomposer:
    """关键词规则驱动的 DAG 生成器"""

    def decompose(self, spec_doc: dict) -> dict:
        """按关键词规则生成 5-8 个默认节点"""
        nodes = [FALLBACK_TEMPLATES['planning']]

        spec_text = json.dumps(spec_doc).lower()
        has_backend = any(kw in spec_text for kw in ['api', 'backend', 'server', 'controller', 'service'])
        has_frontend = any(kw in spec_text for kw in ['page', 'frontend', 'ui', 'component', 'screen'])
        has_db = any(kw in spec_text for kw in ['database', 'table', 'entity', 'schema', 'migration'])

        if has_backend:
            nodes.append(FALLBACK_TEMPLATES['backend'])
        if has_frontend:
            nodes.append(FALLBACK_TEMPLATES['frontend'])
        if has_db:
            nodes.append(FALLBACK_TEMPLATES['database'])

        nodes.append(FALLBACK_TEMPLATES['integration'])
        nodes.append(FALLBACK_TEMPLATES['testing'])
        nodes.append(FALLBACK_TEMPLATES['deployment'])

        return {
            'dag_json': {
                'nodes': nodes,
                'edges': DEFAULT_EDGES,
                'critical_path': [n['id'] for n in nodes],
                'parallel_groups': self._build_parallel_groups(nodes),
            },
            'source': 'fallback',
        }

    def _build_parallel_groups(self, nodes: list) -> list:
        """识别可并行的节点组"""
        parallel_nodes = [n['id'] for n in nodes if n['type'] in ('backend', 'frontend', 'database')]
        return [parallel_nodes] if len(parallel_nodes) > 1 else []
```

#### 2.2.5 持久化 (`_persist_and_publish`)

```python
# a6_spec_decomposer.py

async def _persist_and_publish(self, ctx: dict, dag_result: dict) -> dict:
    """
    1. INSERT INTO task_dags (version 递增)
    2. UPSERT INTO agent_results (agent_key='A6', cycle)
    3. 发布 agent.result.A6 + dag.created
    """
    req_id = ctx['req_id']
    cycle = ctx['cycle']

    # 计算统计字段
    dag = dag_result['dag_json']
    nodes = dag.get('nodes', [])
    node_count = len(nodes)
    critical_path_len = len(dag.get('critical_path', []))
    total_hours = sum(n.get('estimated_hours', 0) for n in nodes)
    human_review_nodes = sum(1 for n in nodes if n.get('needs_human_review'))

    # 获取当前最大 version 并 +1
    max_version = await self.db.fetchval(
        "SELECT COALESCE(MAX(version), 0) FROM task_dags WHERE req_id = $1 AND cycle = $2",
        req_id, cycle
    )
    new_version = max_version + 1

    # 写入 task_dags
    await self.db.execute(
        """INSERT INTO task_dags
           (req_id, cycle, version, dag_json, node_count, critical_path_length,
            total_estimated_hours, human_review_nodes, source, stage3_revision_count)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
        req_id, cycle, new_version,
        json.dumps(dag), node_count, critical_path_len,
        total_hours, human_review_nodes,
        dag_result.get('source', 'llm'),
        ctx.get('tech_prep_revision_count', 0)
    )

    # UPSERT agent_results
    await self._upsert_agent_results(
        req_id=req_id, agent_key='A6', cycle=cycle,
        status='completed',
        artifact={
            'node_count': node_count,
            'version': new_version,
            'source': dag_result.get('source', 'llm'),
            'critical_path_length': critical_path_len,
            'total_estimated_hours': total_hours,
            'human_review_nodes': human_review_nodes,
        }
    )

    return {
        'req_id': req_id,
        'session_id': ctx['session_id'],
        'cycle': cycle,
        'task_dag_id': None,  # 由 DB 返回
        'node_count': node_count,
        'version': new_version,
        'source': dag_result.get('source', 'llm'),
    }
```

---

## 三、数据库

### 3.1 task_dags 表（新建）

```sql
-- task_dags 表 DDL（与阶段三数据字典 §四 严格对齐）
CREATE TABLE IF NOT EXISTS task_dags (
    id                      BIGSERIAL PRIMARY KEY,
    req_id                  UUID NOT NULL
        REFERENCES requirements(id) ON DELETE CASCADE,
    cycle                   INT NOT NULL DEFAULT 0,
    version                 INT NOT NULL DEFAULT 1,
    dag_json                JSONB NOT NULL,
    node_count              INT,
    critical_path_length    INT,
    total_estimated_hours   NUMERIC(6,1),
    human_review_nodes      INT DEFAULT 0,
    source                  VARCHAR(20) DEFAULT 'llm',
    stage3_revision_count   INT DEFAULT 0,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_dags_req ON task_dags(req_id, cycle, version DESC);
```

### 3.2 agent_results 写入

```sql
-- UPSERT 语句（agent_key='A6'）
INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact, created_at, updated_at)
VALUES ($1, 'A6', $2, 'completed', $3::jsonb, NOW(), NOW())
ON CONFLICT (req_id, agent_key, cycle)
DO UPDATE SET
    artifact = EXCLUDED.artifact,
    status = EXCLUDED.status,
    updated_at = NOW();
```

### 3.3 SQL 迁移

```sql
-- Migration: V013__phase3_task_dags.sql
BEGIN;

CREATE TABLE IF NOT EXISTS task_dags (
    id                      BIGSERIAL PRIMARY KEY,
    req_id                  UUID NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    cycle                   INT NOT NULL DEFAULT 0,
    version                 INT NOT NULL DEFAULT 1,
    dag_json                JSONB NOT NULL,
    node_count              INT,
    critical_path_length    INT,
    total_estimated_hours   NUMERIC(6,1),
    human_review_nodes      INT DEFAULT 0,
    source                  VARCHAR(20) DEFAULT 'llm',
    stage3_revision_count   INT DEFAULT 0,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_dags_req ON task_dags(req_id, cycle, version DESC);

COMMIT;
```

---

## 四、NATS 事件 payload 对齐

### 4.1 订阅：context.ready.A6

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "spec_package": {
    "spec_doc": { "title": "...", "modules": [...], "data_models": [...] },
    "openapi_schema": { "openapi": "3.0.0", "paths": {...}, "components": {...} },
    "erd_diagram": { "entities": [...], "relations": [...] },
    "ddl_statements": "CREATE TABLE ..."
  },
  "revision_context": {
    "is_revision": false,
    "gate2_rejection": { "reject_reasons": [...], "revision_guidance": "..." },
    "previous_a8_report": { "review": { "score": 75, "issues": [...] } }
  },
  "a8_suggestions": {
    "dag_fixes": ["添加索引任务", "拆分前端任务"]
  }
}
```

### 4.2 发布：agent.result.A6

```python
# 发布时 js.publish() 携带 Nats-Msg-Id header
headers = {"Nats-Msg-Id": f"{req_id}-agent.result.A6-{cycle}"}
payload = {
    "req_id": req_id,
    "session_id": session_id,
    "cycle": cycle,
    "status": "completed",           # completed | empty
    "node_count": 10,
    "version": 1,
    "source": "llm",                 # llm | fallback | timeout
    "timestamp": "2026-07-15T10:30:00Z"
}

await js.publish(
    "agent.result.A6",
    json.dumps(payload).encode(),
    headers=headers,
    stream="AI_NATIVE_EVENTS"
)
```

### 4.3 发布：dag.created

```python
headers = {"Nats-Msg-Id": f"{req_id}-dag.created-{cycle}"}
payload = {
    "req_id": req_id,
    "session_id": session_id,
    "cycle": cycle,
    "node_count": 10,
    "version": 1,
    "source": "llm",
    "timestamp": "2026-07-15T10:30:00Z"
}

await js.publish(
    "dag.created",
    json.dumps(payload).encode(),
    headers=headers,
    stream="AI_NATIVE_EVENTS"
)
```

### 4.4 Consumer 配置

| Consumer | 订阅 Subject | DeliverPolicy | ack_wait | max_deliver |
|----------|-------------|---------------|----------|-------------|
| `A6_consumer` | `context.ready.A6` | All, 按 req_id 有序 | 60s | 5 |

```python
# Consumer 创建
config = ConsumerConfig(
    durable_name="A6_consumer",
    deliver_policy=DeliverPolicy.ALL,
    ack_wait=60,
    max_deliver=5,
)
await js.add_consumer("AI_NATIVE_EVENTS", config, filter_subjects=["context.ready.A6"])
```

---

## 五、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| DeepSeek API 连接失败 | 120s | 回退到 fallback 规则拆解，source='fallback'，status='completed' |
| DeepSeek 返回非 JSON | — | JSON 解析失败 → 回退 fallback |
| DAG 验证失败（节点数越界/自环） | — | 自动回退 fallback，不写入非法 DAG |
| LLM 子任务超时 | 120s | 该子任务降级为 fallback |
| task_dags 写入失败 | 30s × 3 | 仅写入 agent_results 兜底（artifact 含 dag_json） |
| agent_results UPSERT 冲突 | — | ON CONFLICT DO UPDATE 幂等覆盖 |
| A6 总体超时 | 10min | Orchestrator 重试 1 次（重新发布 context.ready.A6）→ 仍超时 → agent_results (status='empty')，a6_missing=true |
| NATS publish 失败 | 30s | Outbox 重试，5 次入死信队列 |
| Gate2 打回修订 | — | 正常执行完整流水线，注入 revision_context，同 cycle UPSERT 覆盖 |
| A8 对抗修订 | — | 正常执行，注入 a8_suggestions，stage3_revision_count +1 |

---

## 六、实施计划

### Phase 1：核心拆解（~2 天）
- [ ] Migration: `task_dags` 建表（V013）
- [ ] `a6/decomposer.py`：DeepSeek API 集成 + prompt 模板 + JSON 解析
- [ ] `a6/dag_validator.py`：DAG 结构验证器（边界/自环/引用）
- [ ] `a6/fallback_decomposer.py`：关键词规则 fallback
- [ ] `A6SpecDecomposer.execute()` 重构为五阶段流水线
- [ ] agent_results UPSERT 写入（agent_key='A6'）
- [ ] NATS 发布 agent.result.A6 + dag.created（JetStream + Nats-Msg-Id）

### Phase 2：修订 + 异常（~2 天）
- [ ] Gate2 打回 revision_context 解析与注入
- [ ] 同 cycle UPSERT 覆盖 + version 递增验证
- [ ] 超时降级链路（LLM 超时 → fallback，Agent 超时 → empty）
- [ ] task_dags 写入失败重试 + agent_results 兜底

### Phase 3：A6↔A8 对抗（~2 天，P1）
- [ ] A8 评审建议注入 prompt（a8_suggestions → dag_fixes）
- [ ] stage3_revision_count 管理（Gate2 打回后重置）
- [ ] 对抗分歧报告生成（供 Gate2 审批人参考）

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-15
**版本**: v1.0