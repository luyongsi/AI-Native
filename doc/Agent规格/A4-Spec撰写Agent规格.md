# A4 Spec 撰写 Agent - 完整设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 完整设计文档（已通过 critical 审计）
- **参考**: [系统状态机与信息流设计](../系统状态机与信息流设计.md) · [阶段二数据字典](./阶段二-数据字典.md) · [阶段一数据字典](./阶段一-数据字典.md)
- **说明**: A4 负责阶段二的技术规格撰写，在 A3 原型确认后执行，产出 Spec/OpenAPI/ERD/DDL 四件套，为 A5 设计检查和 Gate1 产品审批提供依据。**本文档中所有数据结构、字段名、枚举值以阶段二数据字典为准。**

---

## 一、通信架构

A4 采用**纯 NATS 调度**模型（与 A2 同构）：

```
┌──────────────┐        NATS         ┌──────────────┐
│ Orchestrator │ ◄─────────────────► │    A4 Agent   │
│              │  context.ready.A4   │              │
│              │  agent.result.A4    │              │
└──────────────┘                     └──────┬───────┘
                                           │
                                    MCP 调用（内部）
                                           │
                                    ┌──────┴───────┐
                                    │  知识库 MCP   │
                                    │ + DB 内省     │
                                    └──────────────┘
```

- **NATS**：接收 Orchestrator 调度（`context.ready.A4`），发布完成结果（`agent.result.A4`）
- **MCP**：A4 内部通过 MCP 协议调用知识库服务获取模板和最佳实践
- **DB 内省**：连接数据库获取现有表结构，用于增量 ERD/DDL 生成
- A4 不与用户直接交互，无 HTTP 接口

---

## 二、A4 在阶段二中的位置

```
阶段二：设计
┌──────────────────────────────────────────────────────┐
│                                                      │
│  A3 UI原型 ──► A4 Spec撰写 ──► A5 设计检查 ──► Gate1 │
│                  ↑                            │      │
│                  └── Gate1 打回（默认）───────┘      │
│                                                      │
└──────────────────────────────────────────────────────┘
         │
         ▼ Gate1 通过后进入阶段三（A6+A7，与 A4 无关）
```

### 核心流程

```
Orchestrator 收到 agent.result.A3
    → 写入 event_log → 查询 DB: requirements + agent_results (A1, A2) + prototype_artifacts (A3)
    → build_context → context.ready.A4
    → A4 执行 Spec 撰写 → 持久化 design_specs + agent_results (A4, cycle)
    → 发布 agent.result.A4

Gate1 打回（默认不含 a3_rework）
    → Orchestrator 收到 agent.result.gate1.reject
    → 更新 requirements (design_status='spec_writing', design_revision_count+=1)
    → 查询 DB: a1_output + a2_output + a3_output + a5_output + gate1_rejection
    → build_context（含 revision_context） → context.ready.A4（cycle 不变）
```

---

## 三、职责与设计理念

### 3.1 核心职责

1. **Spec 文档撰写** — 根据需求草案和原型生成结构化技术规格说明书（含状态机设计）
2. **OpenAPI 生成** — 根据 Spec 中的接口设计生成 OpenAPI 3.0 规范
3. **ERD 设计** — 根据数据模型设计实体关系图，检测现有表结构做增量设计
4. **DDL 生成** — 根据 ERD 产出建表 SQL 语句（含索引和约束）

### 3.2 关键设计原则

1. **NATS 驱动**：完全由 Orchestrator 调度
2. **MCP 增强**：通过知识库 MCP 检索最佳实践模板和数据库约定
3. **产物自持久化**：执行完成后写入 `design_specs` + `agent_results` (agent_key='A4')
4. **增量感知**：通过 DB 内省检测现有表结构，生成增量 DDL（仅新增/变更部分）
5. **优雅降级**：LLM 不可用时产出模板化规格，`status='completed'`（标注 source='fallback'）
6. **范围收敛**：A4 只到 Gate1

---

## 四、核心处理流程

A4 采用**五阶段流水线**：

```
Phase 1: 上下文解析    → 解析上游产物 + 检索知识库
Phase 2: Spec 撰写     → LLM 生成结构化技术规格
Phase 3: OpenAPI 生成  → 根据 Spec 接口设计生成 OpenAPI 3.0
Phase 4: ERD + DDL     → 实体关系图 + 建表语句（含增量检测）
Phase 5: 持久化 + 发布 → 写入 design_specs + agent_results + NATS
```

### Phase 1：上下文解析

**输入：**
- A1 需求草案：`requirement_draft`（title, description, entities, use_cases, acceptance_criteria, constraints, risks）
- A2 可行性分析：`feasibility_assessment`（技术/业务可行性 + 冲突点）
- A3 原型 URL：`prototype_url` + `screens`

**MCP 知识库检索（并行，5 秒超时）：**
- `get_openapi_templates(domain)` — 获取领域 OpenAPI 模板
- `get_erd_patterns(domain)` — 获取领域 ERD 设计模式
- `get_ddl_conventions()` — 获取团队 DDL 编写约定（命名规范/索引策略/字段类型）

**DB 内省（并行）：**
- 连接目标数据库 → 查询 `information_schema.tables` → 获取现有表列表和字段定义
- 用于后续增量 ERD/DDL 生成的参考基线

### Phase 2：Spec 文档撰写

LLM 任务（temperature=0.3，低温度保证规格一致性）：

```
System Prompt 注入:
  - A1 需求草案完整内容
  - A2 可行性分析和冲突点
  - A3 原型 URL（提示参考原型交互流）
  - 知识库模板（如有）

产出 Spec 文档，包含以下章节：
  1. 概述 — 系统目标、范围、与现有系统关系
  2. 功能规格 — 按模块拆分，每模块含功能描述、输入/输出、前置条件
  3. 状态机设计 — 核心业务对象的状态流转（状态 + 转移条件 + 触发事件）
  4. 接口设计 — API 列表（method/path/参数/响应/错误码）
  5. 数据模型 — 实体定义（名称/字段/类型/约束/关系）
  6. 非功能需求 — 性能指标、安全要求、审计日志、幂等性
```

Spec 文档结构（与 [数据字典 §5.2](./阶段二-数据字典.md#52-产物结构) 对齐）：

```json
{
  "title": "用户管理系统技术规格",
  "version": "1.0",
  "overview": "系统概述",
  "modules": [
    {
      "name": "用户管理模块",
      "description": "...",
      "states": ["list", "detail", "edit", "create"],
      "state_machine": {
        "states": ["list", "detail", "edit", "create"],
        "transitions": [
          {"from": "list", "to": "detail", "trigger": "点击行"},
          {"from": "list", "to": "create", "trigger": "点击新建"},
          {"from": "detail", "to": "edit", "trigger": "点击编辑"},
          {"from": "edit", "to": "detail", "trigger": "保存成功"},
          {"from": "create", "to": "detail", "trigger": "创建成功"}
        ]
      }
    }
  ],
  "data_models": [
    {
      "name": "User",
      "fields": [
        {"name": "id", "type": "UUID", "nullable": false, "primary_key": true},
        {"name": "name", "type": "VARCHAR(100)", "nullable": false},
        {"name": "email", "type": "VARCHAR(255)", "nullable": false, "unique": true},
        {"name": "role", "type": "VARCHAR(50)", "nullable": false},
        {"name": "created_at", "type": "TIMESTAMPTZ", "nullable": false, "default": "NOW()"}
      ]
    }
  ]
}
```

### Phase 3：OpenAPI 生成

LLM 任务（temperature=0.2）：

- 输入：Phase 2 产出的 Spec 文档（接口设计章节 + 数据模型）
- 输出：OpenAPI 3.0.0 规范 JSON（paths、components/schemas、security）
- 自动校验：`openapi.paths` 中的 schema `$ref` 必须解析到 `components.schemas`
- 安全定义：默认添加 Bearer Token 认证方案

### Phase 4：ERD + DDL 生成

**ERD 生成：**
- 输入：Spec 数据模型 + DB 内省结果（现有表结构）
- 增量逻辑：新实体标记为 `is_new: true`，与现有表有冲突的标记 `conflict: true` + 冲突描述
- 输出：结构化 ERD JSON（entities + relations）

**DDL 生成：**
- 输入：ERD + DB 内省结果
- 仅生成新表和 ALTER 语句（增量），非完整 DROP/CREATE
- 包含索引、外键约束、注释
- DDL 语法基础校验（关键字拼写、括号匹配、分号结尾）

### Phase 5：持久化与发布

```
BEGIN 事务
  1. INSERT INTO design_specs (req_id, cycle, version, spec_doc, openapi_schema, erd_diagram, ddl_statements, quality_score)
     VALUES (?, ?, (SELECT COALESCE(MAX(version),0)+1 FROM design_specs WHERE req_id=? AND cycle=?), ...)
     -- 修订场景下 version 递增，保留历史版本
  2. INSERT INTO agent_results (req_id, agent_key='A4', cycle, status='completed', artifact)
     ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
       SET artifact=EXCLUDED.artifact, status='completed', created_at=NOW()
  3. UPDATE requirements SET spec = {spec_doc, openapi, erd, ddl}::jsonb（最新镜像，兜底用）
COMMIT

发布 NATS: agent.result.A4
```

---

## 五、产出物

| 产物 | 存储位置 | 说明 |
|------|---------|------|
| Spec 文档 | `design_specs.spec_doc` + `agent_results` (A4) | 结构化技术规格，含状态机 |
| OpenAPI 3.0 | `design_specs.openapi_schema` + `agent_results` (A4) | API 规范，含 paths + schemas |
| ERD | `design_specs.erd_diagram` + `agent_results` (A4) | 实体关系图，结构化 JSON |
| DDL | `design_specs.ddl_statements` + `agent_results` (A4) | 增量建表 SQL |
| 质量评分 | `design_specs.quality_score` | 0-1（`agent_results` artifact 中冗余保存一份便于查询） |

### agent_results.A4 结构

```json
{
  "spec_doc": {},
  "openapi_schema": {},
  "erd_diagram": {},
  "ddl_statements": "CREATE TABLE IF NOT EXISTS ...",
  "quality_score": 0.85,
  "source": "llm",
  "metadata": {
    "api_endpoint_count": 12,
    "entity_count": 5,
    "new_entity_count": 3,
    "state_count": 8,
    "transition_count": 15
  }
}
```

---

## 六、输入/输出接口

### context.ready.A4 输入结构

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "a1_output": {
    "requirement_draft": {
      "title": "string",
      "description": "string",
      "domain": "string",
      "entities": [],
      "use_cases": [],
      "acceptance_criteria": [],
      "constraints": [],
      "risks": []
    },
    "wireframe_url": "string | null",
    "confidence_score": 0.85
  },
  "a2_output": {
    "feasibility_assessment": {
      "technical": {"feasible": true, "assessment": "string", "concerns": []},
      "business": {"feasible": true, "assessment": "string", "concerns": []},
      "risk_level": "medium",
      "risk_rationale": "string"
    },
    "confirmation_checklist": [],
    "conflicts": [],
    "quality_score": 0.72
  },
  "a3_output": {
    "prototype_url": "string",
    "screens": []
  },
  "revision_context": {
    "is_revision": false,
    "revision_count": 0,
    "previous_a5_report": null,
    "gate1_rejection": null
  }
}
```

### agent.result.A4 输出结构

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "spec_doc": {},
  "openapi_schema": {},
  "erd_diagram": {},
  "ddl_statements": "string",
  "quality_score": 0.85,
  "metadata": {
    "api_endpoint_count": 12,
    "entity_count": 5,
    "state_count": 8
  },
  "timestamp": "ISO 8601"
}
```

---

## 七、依赖与集成

### 7.1 MCP 工具

| 工具 | 用途 | 降级行为 |
|------|------|---------|
| `get_openapi_templates(domain)` | 获取领域 OpenAPI 模板 | 超时/失败 → 使用通用模板 |
| `get_erd_patterns(domain)` | 获取领域 ERD 设计模式 | 超时/失败 → 使用通用数据模型 |
| `get_ddl_conventions()` | 获取团队 DDL 约定 | 超时/失败 → 使用内置默认约定 |

### 7.2 DB 内省

A4 直接连接目标数据库查询元数据：

```sql
SELECT table_name FROM information_schema.tables WHERE table_schema='public';
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns WHERE table_name=?;
```

内省失败不阻塞流程，视为"全新项目"，所有实体标记 `is_new: true`。

### 7.3 三层降级策略

```
层次 1（完整）：MCP 全部可用 + LLM 正常 → 完整四件套产出（source='llm'）
层次 2（降级）：MCP 部分/全部不可用 + LLM 正常 → 四件套产出但无知识增强（source='llm_no_mcp'）
层次 3（最小）：LLM 不可用 → 模板化产出，status='completed'，source='fallback'
```

---

## 八、NATS 事件协议

| 事件 | 方向 | 触发时机 |
|------|------|---------|
| `context.ready.A4` | Orchestrator → A4 | A3 确认后 / Gate1 打回（默认不含 a3_rework） |
| `agent.result.A4` | A4 → Orchestrator | Spec 撰写完成 |

完整 payload 定义见 [数据字典 §5.3](./阶段二-数据字典.md#53-nats-事件)。

---

## 九、异常处理

| 场景 | 超时 | 策略 |
|------|------|------|
| LLM API 不可用 | — | 降级到模板生成，status='completed', source='fallback' |
| OpenAPI 校验失败 | — | 标注 `validation_warnings`，仍正常产出 |
| DDL 语法校验失败 | — | 标注 `ddl_warnings`，仍正常产出 |
| MCP 全部超时 | 5s×3 | 跳过知识增强，直接生成 |
| DB 内省失败 | 5s | 视为新项目，全部实体标记 is_new |
| A4 总体超时 | 15min | 重试 1 次，仍失败 Orchestrator 写入 agent_results (A4, status='skipped')；Gate0→Gate1 全链路降级 |
| NATS 投递失败 | 30s | Outbox 重试，5 次入死信队列 |

### Gate1 打回修订异常

- Gate1 拒绝含 `require_a3_rework=true` 时 A4 **不**被调度（先等 A3 返工）
- A4 修订时收到 `revision_context.is_revision=true`，应优先修复 A5 报告中标记的 critical/major 问题

---

## 十、质量评分

### 评分维度

| 维度 | 权重 | 评分标准 |
|------|:----:|---------|
| Spec 完整度 | 35% | 所有必填章节是否存在，模块划分是否清晰 |
| API 覆盖率 | 25% | use_cases 是否全部映射为 API endpoints |
| ERD 实体覆盖率 | 20% | entities 是否全部在 ERD 中有对应定义 |
| DDL 语法正确性 | 20% | 基础语法校验通过率 |

### 评分等级

| 分数 | 等级 | 说明 |
|------|------|------|
| >0.8 | 完整 | 四件套齐全，校验全部通过 |
| 0.5-0.8 | 可用 | 核心产物品质良好，有少量 warn |
| <0.5 | 降级 | 部分产物缺失或质量较低 |

---

## 十一、与 A3/A5 的协作边界对比表

| 维度 | A3 UI原型 | A4 Spec撰写 | A5 设计检查 |
|------|----------|------------|-----------|
| **输入** | A1 草案 + A2 分析 | A1 草案 + A2 分析 + A3 原型 | A3 原型 + A4 Spec |
| **通信方式** | HTTP+SSE + NATS | 纯 NATS | 纯 NATS |
| **用户交互** | 多轮标注迭代 | 无 | 无 |
| **产物存储** | prototype_artifacts + agent_results | design_specs + agent_results | agent_results |
| **发布事件** | agent.result.A3 | agent.result.A4 | agent.result.A5 |
| **Gate1 打回** | 仅 a3_rework=true | 默认打回目标 | 不返工（非阻断） |
| **cycle 影响** | cycle 不变（阶段内） | cycle 不变（阶段内） | cycle 不变 |

---

## 十二、总结

| 维度 | 内容 |
|------|------|
| **入口** | `context.ready.A4`（A3 确认 / Gate1 打回默认） |
| **出口** | `agent.result.A4`（Spec 撰写完成） |
| **核心产物** | Spec 文档 + OpenAPI 3.0 + ERD + DDL |
| **产物存储** | `design_specs`（UNIQUE req_id,cycle）+ `agent_results`（A4, cycle 快照） |
| **交互模式** | 纯 NATS 调度，无用户直接交互 |
| **返工机制** | Gate1 拒绝默认 → A4 修订（含 A5 报告 + 拒绝原因） |
| **降级策略** | LLM 不可用→模板；MCP 不可用→跳过增强；DB 内省失败→视为新项目 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
