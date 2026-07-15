# A7 测试用例生成 Agent — 完整设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-15
- **状态**: 完整设计文档（从阶段三-完整设计 §4 + 数据字典 + 开发设计 + 测试设计提取）
- **参考**: [阶段三 数据字典](./阶段三-数据字典.md) · [阶段三 完整设计](./阶段三-完整设计.md) · [系统状态机与信息流设计](../系统架构/系统状态机与信息流设计.md)
- **说明**: A7 负责阶段三的测试用例生成，在 Gate1 通过后与 A6 并行启动，基于 Spec + API 契约生成测试用例骨架（单测/集成/E2E）。**本文档中所有数据结构、字段名、枚举值以阶段三数据字典为准。**

---

## 一、通信架构

A7 采用**纯 NATS 调度**模型（与 A2/A4/A5/A6 同构）：

``
┌──────────────┐        NATS         ┌──────────────┐
│ Orchestrator │ ◄─────────────────► │    A7 Agent   │
│              │  context.ready.A7   │              │
│              │  agent.result.A7    │              │
│              │  test.assets_ready  │              │
└──────────────┘                     └──────┬───────┘
                                           │
                                    LLM 调用（内部）
                                           │
                                    ┌──────┴───────┐
                                    │  DeepSeek API │
                                    └──────────────┘
``

- **NATS**：接收 Orchestrator 调度（context.ready.A7），发布完成结果（gent.result.A7）和测试资产就绪事件（	est.assets_ready）
- **LLM**：A7 内部通过 DeepSeek API 执行测试用例生成
- A7 不与用户直接交互，无 HTTP 接口

---

## 二、A7 在阶段三中的位置

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
         ▼ Gate2 通过后进入阶段四（A9 代码开发），A11 可订阅 A7 产出
``

### 核心流程

``
Gate1 pass
  → Orchestrator 并行发布 context.ready.A6 + context.ready.A7
  → A7 执行测试用例生成 → 持久化 test_assets + agent_results (A7, cycle)
  → 发布 agent.result.A7 + test.assets_ready

Gate2 拒绝（不管是否要求 a7_rework）
  → Orchestrator 收到 agent.result.gate2.reject
  → 更新 requirements (tech_prep_status='revising', tech_prep_revision_count+=1)
  → 发布 context.ready.A7（含 revision_context: gate2_rejection + a8_report）
  → A7 重新生成，同一 cycle 内 UPSERT 覆盖 agent_results

P0：A7 不等待 A6 DAG，独立基于 Spec 生成测试用例
P1：A7 接收 dag_preview 补充 DAG 节点覆盖映射
``

---

## 三、职责与设计理念

### 3.1 核心职责

1. **Spec 解析** — 从 context.ready.A7 中提取 spec_package（spec_doc + openapi_schema），按模块粒度提取测试目标
2. **LLM 生成** — 调用 DeepSeek API 生成分类测试用例（unit/integration/e2e/visual/api）
3. **边界与异常覆盖** — 每个模块至少生成 2 条用例，含正常路径 + 边界异常场景
4. **Fallback 规则生成** — LLM 不可用时回退到模板化规则生成
5. **修订感知** — Gate2 打回时在 prompt 中注入 revision_context 指引修正

### 3.2 关键设计原则

1. **NATS 驱动**：完全由 Orchestrator 调度，不自行决定启动时机
2. **P0 不等待 DAG**：A7 与 A6 完全并行，不依赖 A6 的 DAG 产出
3. **LLM 主路径 + Fallback 备路径**：LLM 正常走主路径（temperature=0.2），失败自动切换 fallback
4. **产物自持久化**：执行完成后写入 	est_assets（新表）+ gent_results (agent_key='A7')
5. **双事件发布**：gent.result.A7（Orchestrator 编排）+ 	est.assets_ready（A11/下游消费）
6. **幂等写入**：同一 (req_id, agent_key, cycle) 使用 UPSERT
7. **范围收敛**：A7 只到 Gate2

---

## 四、核心处理流程

### 4.1 执行阶段

``
阶段 1: 上下文解析     → 提取 spec_package + 检测 dag_preview（P1）
阶段 2: LLM 生成 (主)   → 组装 prompt → 调用 DeepSeek → 解析测试用例 JSON
阶段 3: Fallback (备)   → LLM 失败时执行模板规则生成
阶段 4: 用例组织        → 按 type + priority 分类 → 计算 dag_coverage（P1）
阶段 5: 持久化 + 发布   → INSERT test_assets + UPSERT agent_results + NATS 双事件
``

### 4.2 各阶段详情

#### 阶段 1 — 上下文解析

``python
def _parse_context(context: dict) -> tuple:
    spec_package = {
        "spec_doc": context["spec_package"]["spec_doc"],
        "openapi_schema": context["spec_package"].get("openapi_schema"),
    }
    dag_preview = context.get("dag_preview")  # P1：A6 完成后的 DAG 节点列表
    is_revision = context.get("revision_context", {}).get("is_revision", False)
    revision_info = context.get("revision_context") if is_revision else None
    return spec_package, dag_preview, is_revision, revision_info
``

#### 阶段 2 — LLM 生成（主路径）

**Prompt 设计要点**：
- 输入 Spec 各模块摘要（限制 4000 tokens）+ OpenAPI endpoint 列表
- 要求按 5 种 type 分类生成：unit（单测）、integration（集成）、e2e（端到端）、visual（UI 视觉）、api（接口测试）
- 每个 Spec 模块至少 2 条用例，其中至少 1 条边界/异常场景
- 每条用例含：title + preconditions + steps[].{action, expected} + tags + priority
- Revision 模式下注入 revision_context

**LLM 参数**：
| 参数 | 值 | 说明 |
|------|-----|------|
| model | deepseek-chat | 复用现有配置 |
| temperature | 0.2 | 低温度保证确定性 |
| max_tokens | 4000 | 足够容纳测试用例 JSON |
| timeout | 120s | 单次 LLM 调用超时 |

#### 阶段 3 — Fallback 规则生成（备路径）

触发条件：
- LLM API 返回 None/异常
- LLM 返回的 JSON 解析失败

``python
def _fallback_generate(spec_package: dict) -> list:
    """基于 Spec 模块模板生成基础用例"""
    modules = spec_package["spec_doc"].get("modules", [])
    test_cases = []
    for mod in modules:
        # 每个模块至少 2 条基础用例
        test_cases.append({
            "id": f"TC-{mod['name']}-001",
            "title": f"[{mod['name']}] 正常流程验证",
            "type": "unit",
            "priority": "P0",
            "module": mod["name"],
            "preconditions": ["模块已初始化"],
            "steps": [
                {"action": "调用核心方法", "expected": "返回预期结果"}
            ],
            "tags": ["smoke", mod["name"], "auto"],
            "source": "fallback"
        })
        test_cases.append({
            "id": f"TC-{mod['name']}-002",
            "title": f"[{mod['name']}] 异常输入处理",
            "type": "unit",
            "priority": "P1",
            "module": mod["name"],
            "preconditions": ["模块已初始化"],
            "steps": [
                {"action": "传入 null/空值", "expected": "抛出参数校验异常"}
            ],
            "tags": ["exception", mod["name"], "auto"],
            "source": "fallback"
        })
    return test_cases
``

#### 阶段 4 — 用例组织

用例按以下维度组织后写入 	est_assets：

| 维度 | 值 | 说明 |
|------|-----|------|
| 	ype | unit/integration/e2e/isual/pi | 测试类型 |
| priority | P0/P1/P2 | 优先级 |
| module | Spec 模块名 | 归属模块 |
| 	ags | 自由标签数组 | 含 uto/smoke/exception 等 |

#### 阶段 5 — 持久化

``python
async def _persist_results(req_id, session_id, cycle, test_cases, source="llm"):
    # 1. INSERT INTO test_assets
    asset_id = await db.insert("test_assets", {
        "req_id": req_id, "session_id": session_id, "cycle": cycle,
        "asset_type": "test_case_suite",
        "test_cases": json.dumps(test_cases),
        "case_count": len(test_cases),
        "source": source,
    })

    # 2. UPSERT INTO agent_results
    await _upsert_agent_results(agent_key="A7", req_id=req_id, cycle=cycle,
        artifact={
            "test_cases": test_cases,
            "case_count": len(test_cases),
            "test_asset_id": asset_id,
            "source": source,
            "dag_coverage": _compute_dag_coverage(test_cases, dag_preview),  # P1
        })

    # 3. 发布 NATS 事件
    await js.publish("agent.result.A7", payload,
        headers={"Nats-Msg-Id": f"{req_id}-agent.result.A7-{cycle}"})
    await js.publish("test.assets_ready", test_payload,
        headers={"Nats-Msg-Id": f"{req_id}-test.assets_ready-{cycle}"})
``

---

## 五、产出物

A7 产出分别存入 	est_assets 表和 gent_results 表：

| 产物 | 存储位置 | 说明 |
|------|---------|------|
| 	est_cases | 	est_assets | 完整测试用例数组（按 type/priority/module 分类） |
| case_count | 	est_assets / gent_results.A7 | 用例总数 |
| source | 	est_assets / gent_results.A7 | 产出来源：llm / allback |
| dag_coverage | gent_results.A7.artifact | DAG 节点覆盖比例（P1） |

### 测试用例结构

``json
{
  "test_cases": [
    {
      "id": "TC-auth-001",
      "title": "[用户认证] 正常登录流程 — 有效凭据返回 JWT",
      "type": "unit",
      "priority": "P0",
      "module": "auth",
      "preconditions": [
        "数据库中存在测试用户 (test@example.com / Test123!)",
        "JWT 服务已配置密钥"
      ],
      "steps": [
        {"action": "POST /api/auth/login {email, password}", "expected": "HTTP 200，返回 access_token + refresh_token"},
        {"action": "解析 access_token payload", "expected": "含 user_id、role、exp 字段"}
      ],
      "tags": ["smoke", "auth", "auto"],
      "estimated_duration_ms": 500,
      "source": "llm"
    },
    {
      "id": "TC-auth-002",
      "title": "[用户认证] 无效密码 — 返回 401 不泄露信息",
      "type": "unit",
      "priority": "P0",
      "module": "auth",
      "preconditions": ["数据库中存在测试用户"],
      "steps": [
        {"action": "POST /api/auth/login {email, password: 'wrong'}", "expected": "HTTP 401，消息不含具体失败原因"},
        {"action": "连续 5 次错误尝试", "expected": "第 5 次后账户锁定，返回 423"}
      ],
      "tags": ["exception", "auth", "auto"],
      "estimated_duration_ms": 600,
      "source": "llm"
    }
  ],
  "metadata": {
    "total_count": 24,
    "by_type": {"unit": 12, "integration": 5, "e2e": 3, "api": 4},
    "by_priority": {"P0": 10, "P1": 8, "P2": 6},
    "module_coverage": ["auth", "user", "order", "notification"],
    "generated_by": "deepseek-chat",
    "generated_at": "ISO 8601"
  }
}
``

### 用例字段规范

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| id | string | ✅ | 唯一标识，格式 TC-{module}-{NNN} |
| 	itle | string | ✅ | 格式 [{模块}] {场景描述} |
| 	ype | enum | ✅ | unit/integration/e2e/isual/pi |
| priority | enum | ✅ | P0/P1/P2 |
| module | string | ✅ | 归属模块名（对应 Spec modules） |
| preconditions | string[] | ✅ | 前置条件列表 |
| steps | object[] | ✅ | {action, expected} 步骤列表 |
| 	ags | string[] | ✅ | 标签，必须包含 uto |
| estimated_duration_ms | int | | 预估执行时长（毫秒） |
| source | string | | llm / allback |

### P1：DAG 覆盖映射

``json
{
  "dag_coverage": {
    "total_dag_nodes": 12,
    "covered_nodes": 10,
    "coverage_ratio": 0.83,
    "uncovered_nodes": ["deployment"],
    "node_test_map": {
      "task-01": ["TC-auth-001", "TC-auth-002"],
      "task-02": ["TC-user-001"]
    }
  }
}
``

---

## 六、输入/输出接口

### 6.1 输入：context.ready.A7

完整结构见 [数据字典 §5](./阶段三-数据字典.md#五context-事件-payload)。

| 字段 | 来源 | 说明 |
|------|------|------|
| eq_id | 路由键 | 需求 ID |
| session_id | 路由键 | 会话 ID |
| cycle | 路由键 | 当前 cycle |
| spec_package | Orchestrator 组装 | spec_doc + openapi_schema |
| dag_preview | Orchestrator 组装（P1） | A6 完成后的 DAG 节点列表 |
| evision_context | Gate2 拒绝 | is_revision + gate2_rejection + a8_report |

### 6.2 输出：agent.result.A7

``json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "test_cases": [],
  "case_count": 24,
  "test_asset_id": "int",
  "source": "llm",
  "dag_coverage": {},
  "metadata": {
    "by_type": {"unit": 12, "integration": 5, "e2e": 3, "api": 4},
    "by_priority": {"P0": 10, "P1": 8, "P2": 6}
  },
  "timestamp": "ISO 8601"
}
``

### 6.3 输出：test.assets_ready（广播事件）

``json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "test_asset_id": "int",
  "case_count": 24,
  "source": "llm",
  "timestamp": "ISO 8601"
}
``

> 	est.assets_ready 是 A7 成果的广播事件，供给 A11（自动化测试）等下游消费者订阅。

---

## 七、依赖与集成

### 7.1 LLM 依赖

| 依赖 | 用途 | 降级行为 |
|------|------|---------|
| DeepSeek API | Spec → 测试用例生成 | 回退到模板规则生成（source='fallback'） |

### 7.2 数据库依赖

| 表 | 操作 | 说明 |
|----|------|------|
| 	est_assets | INSERT | 每次执行新增一行 |
| gent_results | UPSERT | 同一 (req_id, agent_key='A7', cycle) 覆盖 |

### 7.3 降级策略

| 场景 | 行为 | source 标记 |
|------|------|------------|
| DeepSeek API 不可用 | 回退到模板规则生成（每模块 2 条基础用例） | allback |
| DeepSeek 返回格式异常 | JSON 解析失败 → 回退 fallback | allback |
| test_assets 写入失败 | 重试 3 次（30s 间隔）→ 仅写入 agent_results | — |
| A7 总体超时（10 分钟） | Orchestrator 重试 1 次 → a7_missing=true | 	imeout |

---

## 八、NATS 事件协议

| 事件 | 方向 | 触发时机 | Nats-Msg-Id 格式 |
|------|------|---------|-----------------|
| context.ready.A7 | Orchestrator → A7 | Gate1 pass / Gate2 拒绝 | {req_id}-context.ready.A7-{cycle} |
| gent.result.A7 | A7 → Orchestrator | 测试用例持久化完成 | {req_id}-agent.result.A7-{cycle} |
| 	est.assets_ready | A7 → 广播 | 测试用例持久化完成 | {req_id}-test.assets_ready-{cycle} |

### Consumer 配置

| Consumer | 订阅 Subject | 交付策略 | ack_wait |
|----------|-------------|---------|----------|
| A7_consumer | context.ready.A7 | All, 按 req_id 有序 | 60s |

---

## 九、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| LLM API 不可用 | 120s | 回退到 fallback 规则生成，status='completed', source='fallback' |
| LLM 返回格式异常 | — | JSON 解析失败 → 回退 fallback |
| test_assets 写入失败 | 30s × 3 | 仅写入 agent_results 兜底 |
| A7 总体超时 | 10min | 重试 1 次，仍失败 → agent_results (status='skipped')，a7_missing=true |
| NATS 投递失败 | 30s | Outbox 重试，5 次入死信队列 |
| Gate2 打回修订 | — | 正常执行，注入 revision_context，同 cycle UPSERT |

---

## 十、测试质量与覆盖规则

### 10.1 覆盖要求

| 维度 | 要求 |
|------|------|
| 模块覆盖 | 每个 Spec 模块至少 2 条用例 |
| 类型覆盖 | 5 种 type（unit/integration/e2e/visual/api）至少各 1 条 |
| 场景覆盖 | 每模块至少 1 条正常路径 + 1 条边界/异常 |
| 优先级分布 | P0: ~40%、P1: ~35%、P2: ~25% |

### 10.2 用例质量标准

| 检查项 | 要求 |
|--------|------|
| 标题可读 | 格式 [{模块}] {场景} — {预期}，≤80 字符 |
| 前置明确 | 前置条件列表化，不含模糊描述 |
| 步骤可执行 | 每步含具体 action + 可验证 expected |
| 标签规范 | 必含 uto，模块标签取 Spec module name |
| source 标记 | llm / fallback 明确区分 |

### 10.3 A11 兼容性

- 所有 uto 标签用例可被 A11 直接订阅执行
- steps[].action 使用结构化描述，A11 解析为测试执行指令
- preconditions 由 A11 在测试 setup 阶段自动执行

---

## 十一、实施建议

### Phase 1：核心生成（Day 1-2）
- A7 Agent 核心流水线：上下文解析 → LLM 生成 → 用例组织 → 持久化
- 	est_assets 表（阶段二已预建，阶段三规范化）
- DeepSeek API 集成 + prompt 模板

### Phase 2：Fallback + 修订（Day 3-4）
- 模板规则 fallback（每模块 2 条基础用例）
- Gate2 打回 revision_context 注入
- 同一 cycle UPSERT 覆盖验证

### Phase 3：P1 增强（Day 7-8）
- DAG 节点覆盖映射（dag_coverage 计算）
- A7 接收 dag_preview 补充节点级测试用例
- 用例跨节点依赖标记

---

## 十二、总结

| 维度 | 内容 |
|------|------|
| **入口** | context.ready.A7（Gate1 pass 并行 / Gate2 拒绝） |
| **出口** | gent.result.A7（Orchestrator 编排）+ 	est.assets_ready（下游广播） |
| **核心产物** | 分类测试用例（unit/integration/e2e/visual/api）× 模块 |
| **产物存储** | 	est_assets（每次新增）+ gent_results（A7, cycle UPSERT） |
| **交互模式** | 纯 NATS 调度，无用户交互 |
| **LLM 策略** | DeepSeek API（temperature=0.2），失败回退 fallback 规则生成 |
| **修订机制** | Gate2 拒绝 → 注入 revision_context，同 cycle 覆盖 |
| **并行关系** | 与 A6 并行启动，P0 不等待 DAG；P1 可接收 dag_preview 补充覆盖 |
| **下游消费** | A11 订阅 	est.assets_ready 获取可执行测试资产 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-15
**版本**: v1.0
**数据规范**: [阶段三数据字典](./阶段三-数据字典.md)
