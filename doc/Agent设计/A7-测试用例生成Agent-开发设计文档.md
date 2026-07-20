# A7 测试用例生成 Agent — 开发设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-17
- **状态**: 开发设计
- **原则**: 以阶段三数据字典为唯一数据规范源；所有数据结构、字段名、枚举值严格对齐数据字典

---

## 一、现状分析与差距

### 1.1 当前实现 vs 目标架构

| 维度 | 当前实现 (`a7_test_case_generator.py`) | 目标架构（规格 v1.0） | 差距 |
|------|----------------------------------------|---------------------|------|
| **触发方式** | Orchestrator 直接调用 | 纯 NATS 调度：订阅 `context.ready.A7`，发布 `agent.result.A7` + `test.assets_ready` | 已改为 NATS 驱动，需验证 |
| **dag_preview 模式** | 不支持 | 支持 `dag_preview.dag_available=false` 时独立生成基础用例 | 需新增 P0/P1 双模式 |
| **agent_result 格式** | 自定义格式 | 符合 PRD §6.4 + 数据字典 §5.4 格式 | 需对齐字段名 |
| **test_assets 写入** | 每次 INSERT new | 增加 version = MAX(version)+1 逻辑 | 需版本递增 |
| **DAG 覆盖报告** | 无 | 新增 `dag_coverage` 字段（P1） | 需新增覆盖计算 |
| **MC Backend 写入** | 有 | 容错处理：写入失败不影响核心流程 | 已实现 |
| **VisAgent 推送** | 有 | visual/e2e 类型用例推送到 VisAgent API | 已实现 |
| **修订上下文** | 部分支持 | Gate2 拒绝时注入 `revision_context`（is_revision + gate2_rejection） | 需增强 prompt 注入 |
| **超时处理** | 无 | 10 分钟超时 → 重试 1 次 → status='skipped'，a7_missing=true | 需新增超时降级 |

### 1.2 现有可复用模块

| 模块 | 文件 | 功能 | 改造要点 |
|------|------|------|---------|
| `TestCaseGeneratorAgent` | `a7_test_case_generator.py` | Agent 主体骨架 | 增加 dag_preview 双模式 + dag_coverage + 版本递增 |
| `BaseAgentWorker` | `base_worker.py` | NATS 订阅/发布 + 生命周期管理 | 扩展 `_upsert_agent_results` + DB pool |
| MC Backend API | HTTP | 测试用例存储 | 容错包装，失败不阻塞 |
| VisAgent API | HTTP | 可视化用例推送 | 保持现有逻辑 |

---

## 二、改造方案

### 2.1 核心流水线

A7 的核心执行逻辑分为六个阶段：

```
context.ready.A7 到达
  │
  ├─ Stage 1: 上下文解析 (_parse_context)
  │     从 payload 提取 spec_package (spec_doc, openapi_schema, erd_diagram)
  │     提取 dag_preview (dag_available, nodes)
  │     提取 revision_context (is_revision, gate2_rejection)
  │
  ├─ Stage 2: LLM 生成 (_generate_with_llm)
  │     调用 DeepSeek API (temperature=0.3)
  │     构建 Prompt：spec_doc + openapi 摘要 + DAG 节点（可选）+ 修订上下文（可选）
  │     P0: dag_available=false → 独立生成基础用例（node_id=null）
  │     P1: dag_available=true → 生成带 node_id 的 DAG 映射用例
  │     解析 LLM 返回的 JSON → test_cases list
  │
  ├─ Stage 3 (备): Fallback 生成 (_fallback_generate)
  │     LLM 不可用或 JSON 解析失败时触发
  │     按 DAG 节点类型映射测试类型（backend→unit+api, frontend→e2e+visual, db→integration）
  │     每个节点至少 2 条用例
  │
  ├─ Stage 4: 资产组织 (_organize_test_assets)
  │     按类型分组：unit_tests / integration_tests / e2e_tests / visual_tests
  │     统计 priority_distribution (P0/P1/P2/P3)
  │     设置 coverage_targets
  │
  ├─ Stage 5: 多路持久化
  │     test_assets 表 INSERT（version = MAX(version) + 1）
  │     MC Backend API 写入（容错，失败不影响主流程）
  │     VisAgent API 推送（visual + e2e 类型，最多 10 条）
  │
  └─ Stage 6: 发布 + 记录
        UPSERT agent_results (agent_key='A7', cycle)
        发布 agent.result.A7 + test.assets_ready（JetStream + Nats-Msg-Id）
        → msg.ack()
```

### 2.2 关键模块描述

#### 2.2.1 DAG 覆盖计算 (`_calculate_dag_coverage`)

```python
def _calculate_dag_coverage(self, test_cases: list, dag_nodes: list,
                             dag_available: bool) -> dict:
    """计算测试用例对 DAG 节点的覆盖率"""
    if not dag_available or not dag_nodes:
        return {
            "total_dag_nodes": 0,
            "covered_nodes": 0,
            "uncovered_nodes": [],
            "dag_available": False,
        }

    all_dag_ids = {n.get("id") for n in dag_nodes if n.get("id")}
    covered_ids = set()

    for case in test_cases:
        node_id = case.get("node_id")
        if node_id and node_id in all_dag_ids:
            covered_ids.add(node_id)

    uncovered = sorted(all_dag_ids - covered_ids)

    return {
        "total_dag_nodes": len(all_dag_ids),
        "covered_nodes": len(covered_ids),
        "uncovered_nodes": uncovered,
        "dag_available": True,
    }
```

#### 2.2.2 test_assets 版本递增 (`_save_to_postgres`)

```python
async def _save_to_postgres(self, req_id: str, test_assets: dict) -> int | None:
    """写入 test_assets 表，带版本递增"""
    try:
        pool = await self._get_db_pool()
        async with pool.acquire() as conn:
            # 获取下一个版本号
            version = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM test_assets WHERE req_id = $1::uuid",
                req_id
            )

            result = await conn.fetchval("""
                INSERT INTO test_assets (
                    req_id, unit_tests, integration_tests, e2e_tests,
                    visual_tests, coverage_targets, total_cases,
                    priority_distribution, source, version
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
            """,
                req_id,
                json.dumps(test_assets.get("unit_tests", []), ensure_ascii=False),
                json.dumps(test_assets.get("integration_tests", []), ensure_ascii=False),
                json.dumps(test_assets.get("e2e_tests", []), ensure_ascii=False),
                json.dumps(test_assets.get("visual_tests", []), ensure_ascii=False),
                json.dumps(test_assets.get("coverage_targets", {}), ensure_ascii=False),
                sum(len(test_assets.get(k, [])) for k in ["unit_tests", "integration_tests", "e2e_tests", "visual_tests"]),
                json.dumps(test_assets.get("priority_distribution", {}), ensure_ascii=False),
                "a7_generator",
                version,
            )
            logger.info(f"[A7] Saved test assets to PostgreSQL: id={result} version={version}")
            return result
    except Exception as e:
        logger.warning(f"[A7] Failed to save test assets to PostgreSQL: {e}")
        return None
```

#### 2.2.3 Fallback 生成 (`_fallback_generate`)

```python
def _fallback_generate(self, dag_nodes: list) -> list:
    """规则驱动的测试用例生成（LLM 不可用时）"""
    test_cases = []
    case_id = 1

    if not dag_nodes:
        # 无 DAG 节点时生成基础用例
        dag_nodes = [
            {"id": "task-backend", "type": "backend"},
            {"id": "task-frontend", "type": "frontend"},
            {"id": "task-db", "type": "db"},
        ]

    # 类型 → 测试类型映射
    TYPE_MAP = {
        "backend": ["unit", "api"],
        "frontend": ["e2e", "visual"],
        "db": ["integration", "unit"],
        "planning": ["unit"],
        "deployment": ["e2e"],
        "testing": ["unit"],
    }

    for node in dag_nodes:
        node_type = node.get("type", "backend")
        test_types = TYPE_MAP.get(node_type, ["unit"])

        for test_type in test_types:
            test_cases.append({
                "case_id": f"TC-{case_id:03d}",
                "node_id": node.get("id"),
                "title": f"[{node_type}] {node.get('title', '任务')} - {test_type} 测试",
                "type": test_type,
                "priority": "P1" if test_type in ("e2e", "visual") else "P2",
                "steps": [
                    {"step_number": 1, "action": "准备测试数据", "expected": "数据就绪"},
                    {"step_number": 2, "action": f"执行 {test_type} 测试", "expected": "测试通过"},
                ],
                "source": "fallback",
            })
            case_id += 1

    return test_cases
```

---

## 三、数据库

### 3.1 test_assets 表（确认已有）

```sql
-- test_assets 表 DDL（与阶段三数据字典 §五 严格对齐）
CREATE TABLE IF NOT EXISTS test_assets (
    id                      BIGSERIAL PRIMARY KEY,
    req_id                  UUID NOT NULL
        REFERENCES requirements(id) ON DELETE CASCADE,
    unit_tests              JSONB,
    integration_tests       JSONB,
    e2e_tests               JSONB,
    visual_tests            JSONB,
    coverage_targets        JSONB,
    total_cases             INT,
    priority_distribution   JSONB,
    source                  VARCHAR(50) DEFAULT 'a7_generator',
    version                 INT DEFAULT 1,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_test_assets_req ON test_assets(req_id, created_at DESC);
```

### 3.2 agent_results 写入

```sql
-- UPSERT 语句（agent_key='A7'）
INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact, created_at, updated_at)
VALUES ($1, 'A7', $2, 'completed', $3::jsonb, NOW(), NOW())
ON CONFLICT (req_id, agent_key, cycle)
DO UPDATE SET
    artifact = EXCLUDED.artifact,
    status = EXCLUDED.status,
    updated_at = NOW();
```

---

## 四、NATS 事件 payload 对齐

### 4.1 订阅：context.ready.A7

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "spec_package": {
    "spec_doc": { "title": "...", "modules": [...], "data_models": [...] },
    "openapi_schema": { "openapi": "3.0.0", "paths": {...}, "components": {...} },
    "erd_diagram": { "entities": [...], "relations": [...] }
  },
  "dag_preview": {
    "dag_available": false,
    "nodes": [],
    "node_count": 0
  },
  "revision_context": {
    "is_revision": false,
    "gate2_rejection": { "reject_reasons": [...], "revision_guidance": "..." }
  }
}
```

### 4.2 发布：agent.result.A7

```python
# 发布时 js.publish() 携带 Nats-Msg-Id header
headers = {"Nats-Msg-Id": f"{req_id}-agent.result.A7-{cycle}"}
payload = {
    "req_id": req_id,
    "session_id": session_id,
    "cycle": cycle,
    "status": "completed",           # completed | skipped
    "total_cases": 16,
    "test_asset_id": 42,
    "saved_to_mc": 16,
    "pushed_to_visagent": 5,
    "dag_coverage": {
        "total_dag_nodes": 8,
        "covered_nodes": 7,
        "uncovered_nodes": ["task-05"],
        "dag_available": True
    },
    "timestamp": "2026-07-17T10:30:00Z"
}

await js.publish(
    "agent.result.A7",
    json.dumps(payload).encode(),
    headers=headers,
    stream="AI_NATIVE_EVENTS"
)
```

### 4.3 发布：test.assets_ready

```python
headers = {"Nats-Msg-Id": f"{req_id}-test.assets_ready-{cycle}"}
payload = {
    "req_id": req_id,
    "session_id": session_id,
    "cycle": cycle,
    "test_asset_id": 42,
    "total_cases": 16,
    "version": 1,
    "timestamp": "2026-07-17T10:30:00Z"
}

await js.publish(
    "test.assets_ready",
    json.dumps(payload).encode(),
    headers=headers,
    stream="AI_NATIVE_EVENTS"
)
```

### 4.4 Consumer 配置

| Consumer | 订阅 Subject | DeliverPolicy | ack_wait | max_deliver |
|----------|-------------|---------------|----------|-------------|
| `A7_consumer` | `context.ready.A7` | All, 按 req_id 有序 | 60s | 5 |

```python
# Consumer 创建
config = ConsumerConfig(
    durable_name="A7_consumer",
    deliver_policy=DeliverPolicy.ALL,
    ack_wait=60,
    max_deliver=5,
)
await js.add_consumer("AI_NATIVE_EVENTS", config, filter_subjects=["context.ready.A7"])
```

---

## 五、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| DeepSeek API 连接失败 | 120s | 回退到 fallback 规则生成，source='fallback' |
| DeepSeek 返回非 JSON | — | JSON 解析失败 → 回退 fallback |
| LLM 子任务超时 | 120s | 该子任务降级为 fallback |
| MC Backend API 不可用 | 30s | 仅日志警告，不阻塞主流程（saved_to_mc=0） |
| VisAgent API 不可用 | 30s | 仅日志警告，pushed_to_visagent=0 |
| test_assets 写入失败 | 30s × 3 | agent_results 兜底（artifact 含 test_assets） |
| agent_results UPSERT 冲突 | — | ON CONFLICT DO UPDATE 幂等覆盖 |
| A7 总体超时 | 10min | Orchestrator 重试 1 次 → 仍超时 → agent_results (status='skipped')，a7_missing=true |
| NATS publish 失败 | 30s | Outbox 重试，5 次入死信队列 |
| Gate2 打回修订 | — | 正常执行完整流水线，注入 revision_context，同 cycle UPSERT 覆盖 |

---

## 六、实施计划

### Phase 1：核心生成（~2 天）
- [ ] dag_preview 双模式（P0 独立生成 + P1 DAG 映射）
- [ ] LLM prompt 增强（DAG 节点注入 + 修订指引注入）
- [ ] `_calculate_dag_coverage`：DAG 覆盖计算
- [ ] `_save_to_postgres`：test_assets 版本递增
- [ ] `_organize_test_assets`：按类型分组 + priority 统计
- [ ] agent_results UPSERT 写入（agent_key='A7'）
- [ ] NATS 发布 agent.result.A7 + test.assets_ready（JetStream + Nats-Msg-Id）

### Phase 2：修订 + 异常（~2 天）
- [ ] Gate2 打回 revision_context 解析与 prompt 注入
- [ ] MC Backend 写入容错（失败不阻塞）
- [ ] VisAgent 推送容错
- [ ] 超时降级链路（LLM 超时 → fallback，Agent 超时 → skipped）

### Phase 3：DAG 映射补充（~1 天，P1）
- [ ] 订阅 `dag.created` 事件，补充 DAG node_id 映射
- [ ] 二次写入 test_assets（新 version）补充 DAG 覆盖
- [ ] 更新 agent_results 中的 dag_coverage

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-17
**版本**: v1.0
