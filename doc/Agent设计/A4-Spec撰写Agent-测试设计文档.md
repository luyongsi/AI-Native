# A4 Spec 撰写 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-13
- **参考**: [A4 开发设计文档](./A4-Spec撰写Agent-开发设计文档.md) · [A4-Spec撰写Agent完整设计](../Agent规格/A4-Spec撰写Agent完整设计.md) · [阶段二数据字典](../Agent规格/阶段二-数据字典.md)
- **测试范围**: A4 全功能验证（三层降级 → Spec 六章生成 → OpenAPI → ERD/DDL → 质量评分 → 持久化 → NATS 发布 → Gate1 打回修订）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常流程 + Gate1 打回修订流程
            ├──────────────┤
            │  真实环境集成  │  7 条：LLM + MCP + NATS 真实服务
            ├──────────────┤
            │  集成测试     │  7 条：Agent + DB + NATS 联合验证
            ├──────────────┤
            │  单元测试     │  22 条：SpecGenerator、API/ERD/DDL 生成器、质量评分、降级链
            ├──────────────┤
            │  数据库测试   │  7 条：DDL、约束、版本管理、UPSERT
            └──────────────┘
```

---

## 二、数据库层测试（7 条）

### 2.1 design_specs 表

**T-A4-DB-001: design_specs 表可创建**
```
输入: 执行 migration（含 design_specs DDL）

验证 SQL:
  SELECT table_name FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name = 'design_specs';

预期结果: 返回 1 行
```

**T-A4-DB-002: 完整四件套 INSERT**
```
输入:
  INSERT INTO design_specs (req_id, cycle, version, spec_doc, openapi_schema, erd_diagram, ddl_statements, quality_score)
  VALUES ('<req_id>', 0, 1,
          '{"title":"用户管理系统技术规格","overview":"...","modules":[],"data_models":[]}'::jsonb,
          '{"openapi":"3.0.0","info":{"title":"User API"},"paths":{},"components":{}}'::jsonb,
          '{"entities":[{"name":"User","fields":[{"name":"id","type":"UUID","primary_key":true}]}]}'::jsonb,
          'CREATE TABLE users (id UUID PRIMARY KEY, name VARCHAR(100) NOT NULL);',
          0.85);

验证 SQL:
  SELECT
    spec_doc->>'title' as title,
    openapi_schema->>'openapi' as oa_version,
    jsonb_array_length(erd_diagram->'entities') as entity_count,
    length(ddl_statements) as ddl_len,
    quality_score
  FROM design_specs WHERE req_id = '<req_id>';

预期结果:
  title = '用户管理系统技术规格'
  oa_version = '3.0.0'
  entity_count = 1
  ddl_len > 0
  quality_score = 0.85
```

**T-A4-DB-003: UNIQUE (req_id, cycle, version) 约束**
```
步骤 1:
  INSERT INTO design_specs (req_id, cycle, version) VALUES ('<req_id>', 0, 1);
  → 成功

步骤 2:
  INSERT INTO design_specs (req_id, cycle, version) VALUES ('<req_id>', 0, 1);
  → 预期: ERROR 23505 (duplicate key)
```

**T-A4-DB-004: quality_score CHECK 约束**
```
-- 合法: 0-1
INSERT INTO design_specs (req_id, cycle, version, quality_score) VALUES ('<req_id>', 0, 1, 0.85);
→ 成功

-- 非法: > 1
INSERT INTO design_specs (req_id, cycle, version, quality_score) VALUES ('<req_id>', 0, 2, 1.5);
→ 预期: ERROR 23514 (check constraint violation)

-- 非法: < 0
INSERT INTO design_specs (req_id, cycle, version, quality_score) VALUES ('<req_id>', 0, 3, -0.1);
→ 预期: ERROR 23514 (check constraint violation)
```

**T-A4-DB-005: Gate1 打回修订 — version 递增保留历史**
```
输入:
  INSERT version=1 (首次产出, quality_score=0.72)
  INSERT version=2 (修订产出, quality_score=0.85)

验证 SQL:
  SELECT version, quality_score FROM design_specs
  WHERE req_id = '<req_id>' AND cycle = 0 ORDER BY version;

预期结果: 2 行
  version=1, quality_score=0.72
  version=2, quality_score=0.85
```

**T-A4-DB-006: agent_results A4 UPSERT 覆盖写入**
```
步骤 1:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A4', 0, 'completed', '{"quality_score":0.72}'::jsonb);
  → 成功

步骤 2:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A4', 0, 'completed', '{"quality_score":0.85}'::jsonb)
  ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
  SET artifact = EXCLUDED.artifact, status = EXCLUDED.status;

验证 SQL:
  SELECT artifact->>'quality_score' as qs, status
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A4' AND cycle = 0;

预期结果:
  qs = '0.85'
  status = 'completed'
  count(*) = 1
```

**T-A4-DB-007: requirements.spec JSONB 镜像写入**
```
步骤:
  1. INSERT INTO design_specs (含完整 spec_doc + openapi_schema + erd_diagram + ddl_statements)
  2. UPDATE requirements SET spec = <镜像>::jsonb

验证 SQL:
  SELECT
    spec->>'spec_doc' IS NOT NULL as has_spec,
    spec->>'openapi' IS NOT NULL as has_openapi,
    spec->>'erd' IS NOT NULL as has_erd,
    spec->>'ddl' IS NOT NULL as has_ddl,
    spec->>'updated_at' IS NOT NULL as has_ts
  FROM requirements WHERE id = '<req_id>';

预期结果: 全部 true
```

---

## 三、A4 Agent 单元测试（14 条）

### 3.1 SpecGenerator

**T-A4-AG-001: 正常生成六章 Spec**
```
输入:
  draft = {"title":"博客系统","description":"支持文章发布和评论","domain":"内容管理","entities":[...],"use_cases":[...]}
  feasibility = {"technical":{"feasible":true},"business":{"feasible":true},"risk_level":"low"}
  prototype_url = "https://s3/xxx/prototype_v1.html"
  domain = "内容管理"
  LLM mock: 返回六章完整 Spec

验证:
  spec = await SpecGenerator.generate(draft, feasibility, prototype_url, domain)
  spec 含 keys: title, version, overview, modules, data_models
  len(spec.modules) >= 1
  spec.modules[0] 含 name, description, states, state_machine
  spec.modules[0].state_machine 含 states + transitions
  spec.data_models 至少 1 个实体
```

**T-A4-AG-002: 修订 context 注入 — 含 Gate1 拒绝原因**
```
输入:
  revision_context = {
    "is_revision": true,
    "gate1_rejection": {
      "reject_reasons": [{"category":"spec_incomplete","description":"权限校验流程缺失"}],
      "revision_guidance": "请补充权限校验相关的状态机流转和 API 定义"
    },
    "previous_a5_report": {
      "check_report": {
        "dimensions": [
          {"dimension":"state_machine_closure","label":"状态机闭合性","issues":[
            {"severity":"critical","description":"状态 'pending_review' 没有出边","suggestion":"添加审批通过/拒绝的 transition"}
          ]}
        ]
      }
    }
  }

验证:
  prompt = _build_spec_prompt(...) + _build_revision_context(revision_context)
  prompt 包含 "权限校验流程缺失"
  prompt 包含 "状态 'pending_review' 没有出边"
  prompt 包含 "[critical]" 严重度标记
```

**T-A4-AG-003: 空 feasibility → Spec 仍可产出**
```
输入: feasibility = {} (空 dict)
验证: generate 不抛异常，spec.overview 非空（LLM 基于 draft 自身推断）
```

**T-A4-AG-004: prototype_url 为空 → 不影响生成**
```
输入: prototype_url = ""
验证: generate 正常产出，spec 含 modules（无原型参考，但不阻塞）
```

### 3.2 APISchemaGenerator

**T-A4-AG-005: 正常生成 OpenAPI 3.0**
```
输入:
  draft = {"title":"博客系统","use_cases":["创建文章","查看文章列表","编辑文章","删除文章"]}
  spec_doc = (六章 Spec 含 modules 和 data_models)
  templates = (MCP get_openapi_templates 结果)
  LLM mock: 返回完整 OpenAPI 3.0

验证:
  api_result = await APISchemaGenerator.generate(draft, templates, conventions, revision_context=None)
  api_result 含 'schema' key
  schema.openapi = "3.0.0"
  schema.paths 至少 4 个路径（对应 CRUD）
  schema.components.schemas 至少 1 个 schema
  schema.components.securitySchemes 含 bearerAuth
```

**T-A4-AG-006: MCP templates 为空 → 使用通用模板**
```
输入: templates = {} (MCP 超时降级)
验证: generate 正常产出，schema.paths 至少含 /health 兜底路径
```

**T-A4-AG-007: 含嵌套资源路径 → paths 结构正确输出**
```
输入: schema.paths 含 GET /users + GET /users/{id}/roles
验证: APISchemaGenerator 输出的 OpenAPI paths 结构完整（每个 method 含 responses/schema，嵌套路径独立定义）。
      N+1 检测由 A5 的 N1Detector 负责，不属于 APISchemaGenerator 测试范围。
```

### 3.3 ERDGenerator + DDL

**T-A4-AG-008: 正常生成 ERD + DDL**
```
输入:
  draft = {"entities":[
    {"name":"User","attributes":["用户名","邮箱","角色"],"description":"核心实体"},
    {"name":"Article","attributes":["标题","内容","作者"],"description":"文章实体"}
  ]}
  patterns = (MCP get_erd_patterns 结果)
  conventions = (MCP get_ddl_conventions 结果)
  existing_tables = []

验证:
  erd_result = await ERDGenerator.generate(draft, patterns, conventions, existing_tables, revision_context=None)
  erd_result 含 entities + relations + ddl
  len(entities) >= 2
  entities[0].fields 每个含 name, type, nullable
  ddl 为合法 SQL（以 CREATE TABLE 开头或含 CREATE TABLE）
```

**T-A4-AG-009: 增量 ERD — 检测现有表**
```
输入:
  existing_tables = [
    {"table_name":"users","columns":[{"column_name":"id","data_type":"uuid"},{"column_name":"name","data_type":"varchar"}]}
  ]
  draft.entities = [{"name":"User","attributes":["用户名","邮箱","状态"]}, {"name":"Article","attributes":["标题","内容"]}]

验证:
  - User 实体标记 is_new=false（表已存在）。注: entity name "User" → table name "users" 的映射由 ERDGenerator 的命名规范化逻辑负责（大写→小写、单数→复数）；测试 mock 应预设此映射以确保可重复性
  - Article 实体标记 is_new=true（表不存在）
  - DDL 仅含 Article 的 CREATE TABLE（不含 DROP/CREATE users）
```

**T-A4-AG-010: DB 内省失败 → 全部标记 is_new**
```
输入: _detect_existing_tables 抛异常（DB 不可达）

验证:
  - existing_tables = []（防御性处理）
  - 所有实体标记 is_new=true
  - DDL 包含所有实体的 CREATE TABLE
  - 不抛异常
```

### 3.4 SchemaValidator + DDLValidator

**T-A4-AG-011: OpenAPI 校验通过**
```
输入: 合法 OpenAPI 3.0 Schema（含 paths + components + security）

验证:
  result = SchemaValidator.validate(openapi_schema)
  result.valid = True
  result.errors = []
```

**T-A4-AG-012: OpenAPI 校验失败 — 记录 warnings**
```
输入: 不完整 OpenAPI（paths 中某 endpoint 缺少 responses）

验证:
  result.valid = False
  result.errors 非空
  result.errors[0] 含描述信息
```

**T-A4-AG-013: DDL 语法校验通过**
```
输入: "CREATE TABLE users (id UUID PRIMARY KEY, name VARCHAR(100));"

验证:
  result.valid = True
  result.errors = []
```

**T-A4-AG-014: DDL 语法校验失败 — 记录 warnings**
```
输入: "CREAT TABLE users (id UUID PRIMARY KEY);"  (拼写错误)

验证:
  result.valid = False
  result.errors 非空
```

---

## 四、质量评分测试（5 条）

**T-A4-QS-001: 完整四件套 → 满分**
```
输入:
  spec_doc = {"overview":"...","modules":[...]}（六章齐全）
  api_result = {"schema":{"paths":{"/users":{"get":{},"post":{},"put":{},"delete":{}}}}}（≥8 端点）
  erd_result = {"entities":[{"fields":[{"primary_key":true}],"relations":[...]}],"ddl":"CREATE TABLE users (...);"}

预期: quality_score >= 0.8（四维加权均在优秀水平）
```

**T-A4-QS-002: 空产物 → 最低分**
```
输入:
  spec_doc = {}
  api_result = {"schema":{"paths":{}}}
  erd_result = {"entities":[],"ddl":""}

验证:
  quality_score < 0.3
  spec_completeness 维度的 _score_spec 返回 0.0（无 overview + modules）
```

**T-A4-QS-003: 截断验证 — 分数不超过 1.0**
```
输入: 全满分数据
验证: quality_score <= 1.0, 不抛异常
```

**T-A4-QS-004: 仅 DDL 不可用 — 扣分但不归零**
```
输入:
  spec_doc = 完整六章
  api_result = 含 5 个端点
  erd_result = {"entities":[{"fields":[{"primary_key":true}]}],"ddl":""}

预期: quality_score >= 0.5 且 < 0.8（ddl_validity 维度扣分）
```

**T-A4-QS-005: ddl_validity 维度的边界验证**
```
子用例 A: DDL 以 CREATE 开头 → score >= 0.9
子用例 B: DDL 以 ALTER 开头 → score >= 0.9
子用例 C: DDL 不以 CREATE/ALTER 开头 → score = 0.3
子用例 D: DDL 为空字符串 → score = 0.0
```

---

## 五、三层降级测试（5 条）

**T-A4-DG-001: 全 MCP 正常 → L1 LLM 完整产出**
```
输入: MCP 全部返回有效数据 (templates + patterns + conventions)

验证:
  - 日志: [A4] MCP: all 3 tools available
  - 产出 source = "llm"
  - quality_score >= 0.6
  - 四件套齐全 (spec_doc + openapi_schema + erd_diagram + ddl_statements)
```

**T-A4-DG-002: MCP 全部超时 → L2 LLM + 内置默认值**
```
输入: MCP 三路全部抛 TimeoutError

验证:
  - 产出 source = "llm_no_mcp"
  - spec_doc 非空（LLM 基于需求上下文仍可生成）
  - openapi_schema 含通用模板内容
  - quality_score >= 0.3
```

**T-A4-DG-003: LLM 不可用 → L3 fallback 模板**
```
输入: LLM 全部抛异常

验证:
  - 产出 source = "fallback"
  - spec_doc 来自模板（含 overview + 至少 1 个 module）
  - openapi_schema 含 /health 兜底端点
  - ddl_statements 含 CREATE TABLE 模板
  - quality_score = 0.0
  - status = 'completed'（不阻塞后续流程）
```

**T-A4-DG-004: 单路 MCP 超时 — 其余正常**
```
输入: get_erd_patterns 超时，其余 2 路正常

验证:
  - spec_doc 和 openapi_schema 质量不受影响
  - erd_diagram 生成基于内置默认模式（无 MCP 增强）
  - source = "llm"（单路 MCP 超时不会改变全局 source；source 的降级标记见 T-A4-DG-002 全 MCP 超时场景）
```

**T-A4-DG-005: DB 内省失败 → 视为新项目**
```
输入: _detect_existing_tables 抛异常

验证:
  - 所有实体标记 is_new=true
  - DDL 包含完整 CREATE TABLE（非增量）
  - 不抛异常
  - 日志含 "DB introspection failed"
```

---

## 六、集成测试（7 条）

### 6.1 Agent + DB 联合验证

**T-A4-IT-001: execute() 六阶段完整执行**
```
前置: DB 含 requirements + agent_results (A1, A2, A3)
       MCP mock 正常

步骤: await agent.execute(req_id, context_package)

验证:
  Phase 1 (加载上下文): _report_status 被调用 1 次
  Phase 2 (Spec 生成): spec_gen.generate 被调用
  Phase 3 (API+ERD): api_schema_gen.generate + erd_gen.generate 并行调用
  Phase 4 (验证): schema_validator.validate + ddl_validator.validate 被调用
  Phase 5 (评分): completeness.score 被调用
  Phase 6 (持久化): design_specs + agent_results INSERT

  DB 验证:
    SELECT count(*) FROM design_specs WHERE req_id = '<req_id>';
    预期: 1
    SELECT count(*) FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A4';
    预期: 1
```

**T-A4-IT-002: execute() 返回完整 NATS payload**
```
验证 execute() 返回 dict 的 keys:
  ✓ "req_id"
  ✓ "session_id"
  ✓ "cycle"
  ✓ "spec_doc"
  ✓ "openapi_schema"
  ✓ "erd_diagram"
  ✓ "ddl_statements"
  ✓ "quality_score"
  ✓ "metadata" (含 api_endpoint_count, entity_count, state_count)
  ✓ "source"
```

**T-A4-IT-003: 修订场景 — version 递增**
```
前置: design_specs 已有 version=1

步骤: await agent.execute(req_id, context_package_with_revision)

验证:
  DB:
    SELECT count(*) FROM design_specs WHERE req_id = '<req_id>' AND cycle = 0;
    预期: 2 (version=1 + version=2)
    agent_results A4 仍为 1 行（UPSERT）
    requirements.spec JSONB 更新为最新镜像
```

### 6.2 NATS 事件联调

**T-A4-IT-004: context.ready.A4 订阅 → A4 执行**
```
前置:
  - 嵌入式 nats-server 运行
  - A4 Worker 订阅 context.ready.A4
  - DB 含完整的 A1/A2/A3 产物

步骤: NATS 发布 context.ready.A4 (标准 payload)

验证:
  - A4 execute() 被触发
  - design_specs 写入 1 行
  - agent.result.A4 在 ≤ 30s 发布（mock LLM 场景，真实环境另见 T-A4-RL-007: ≤ 60s）
  - payload.quality_score >= 0
```

**T-A4-IT-005: agent.result.A4 发布后 Orchestrator 收到**
```
前置: A4 执行完成，agent.result.A4 已发布

验证:
  - NATS consumer 收到消息
  - payload 含 spec_doc + openapi_schema + erd_diagram + ddl_statements
  - payload.req_id + session_id + cycle 正确
```

### 6.3 Gate1 打回修订集成

**T-A4-IT-006: Gate1 打回 → A4 收到 revision_context**
```
前置:
  - Gate1 reject (a3_rework=false)
  - Orchestrator 发布 context.ready.A4 (含 revision_context.is_revision=true)

步骤: A4 执行修订

验证:
  - _build_revision_context 被调用
  - prompt 中包含 A5 报告中的 critical/major issue
  - design_specs version 递增
  - quality_score 有新值（可能更高）
```

**T-A4-IT-007: A4 超时降级 → status='skipped'**
```
模拟: A4 execute() 超过 15min

验证:
  - Orchestrator 写入 agent_results (A4, status='skipped')
  - context.ready.A5 中 a4_missing=true
  - Gate1 审批上下文 a4_missing=true
```

---

## 七、并发与边界测试（4 条）

**T-A4-CC-001: 同一 req_id 重复触发 A4 → UPSERT 幂等**
```
步骤:
  1. A4 execute() → design_specs INSERT + agent_results INSERT
  2. A4 execute() 再次执行（同一 req_id + cycle）

验证:
  - design_specs 有 2 行（version=1 + version=2）
  - agent_results 只有 1 行（UPSERT 覆盖）
```

**T-A4-CC-002: design_specs UNIQUE 冲突 — ON CONFLICT DO UPDATE**
```
步骤:
  1. INSERT version=1 成功
  2. INSERT version=1 失败 → 预期 UPSERT 覆盖（在 A4 的 _persist_all 中使用 SELECT COALESCE(MAX(version),0)+1，不会产生 UNIQUE 冲突）
```

**T-A4-CC-003: 空 draft — 不崩溃**
```
输入:
  context_package.a1_output.requirement_draft = {}

验证:
  - execute() 不抛异常
  - spec_doc.title 为 "未命名需求" 或类似默认值
  - quality_score >= 0（降级但不崩溃）
```

**T-A4-CC-004: 极大 entities 数量 — LLM prompt 截断**
```
输入: draft.entities 有 50+ 个实体

验证:
  - _build_spec_prompt 产出的 prompt 长度合理（不超 LLM context）
  - 实体列表被截断或摘要化
  - execute() 正常完成
```

---

## 八、端到端测试（2 条）

### 8.1 正常全流程

**T-A4-E2E-001: A3 confirm → A4 → A5 衔接链路**

```
Step 1: 准备数据（模拟 A3 已完成）
  - requirements: design_status='spec_writing'
  - agent_results: A1, A2, A3 全部 cycle=0, status='completed'
  - prototype_artifacts: status='confirmed'

Step 2: Orchestrator build_context → 发布 context.ready.A4
  验证点:
    ✓ payload.a1_output.requirement_draft 非空
    ✓ payload.a2_output.feasibility_assessment 非空
    ✓ payload.a3_output.prototype_url 非空
    ✓ payload.revision_context.is_revision = false

Step 3: A4 执行
  验证点:
    ✓ 六阶段流水线完整执行
    ✓ design_specs 写入 version=1
    ✓ agent_results A4 cycle=0 status='completed'
    ✓ spec_doc 六章齐全
    ✓ openapi_schema 合法
    ✓ erd_diagram.entities 非空
    ✓ ddl_statements 非空
    ✓ quality_score >= 0

Step 4: agent.result.A4 发布
  验证点:
    ✓ NATS 消息已发布
    ✓ Orchestrator 收到 → event_log IN → 更新 design_status='design_checking' → context.ready.A5

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                      │ 预期行数 │ 关键字段        │
  ├─────────────────────────────────────────────────────┤
  │ design_specs            │ 1       │ version=1, quality_score≥0 │
  │ agent_results           │ 4       │ A1, A2, A3, A4 全部 completed │
  │ requirements            │ 1       │ design_status='design_checking' │
  │ event_log               │ >=2     │ context.ready.A4 + agent.result.A4 │
  └─────────────────────────────────────────────────────┘
```

### 8.2 Gate1 打回 A4 修订全流程

**T-A4-E2E-002: A3→A4→A5→Gate1 reject → A4 修订 → A5 重检**

```
Step 1-4: 同 T-A4-E2E-001（完成首次 A4）

Step 5: Gate1 审批人 reject（a3_rework=false）
  - Gate1 写入 approvals: decision='reject', reject_reasons=[...]
  - NATS 发布 agent.result.gate1.reject

Step 6: Orchestrator 处理 Gate1 reject
  验证点:
    ✓ requirements.design_status = 'spec_writing'
    ✓ requirements.design_revision_count = 1
    ✓ event_log IN 记录 agent.result.gate1.reject

Step 7: Orchestrator 发布 context.ready.A4 (含 revision_context)
  验证点:
    ✓ revision_context.is_revision = true
    ✓ revision_context.gate1_rejection.reject_reasons 非空
    ✓ revision_context.previous_a5_report 非空

Step 8: A4 修订执行
  验证点:
    ✓ prompt 中含 Gate1 拒绝原因和 A5 critical issue
    ✓ design_specs version=2（递增）
    ✓ agent_results A4 cycle=0 UPSERT 覆盖
    ✓ quality_score 可能更高
    ✓ requirements.spec JSONB 镜像更新

Step 9: agent.result.A4 发布 → Orchestrator → context.ready.A5 → A5 重检

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                      │ 预期行数 │ 关键字段        │
  ├─────────────────────────────────────────────────────┤
  │ design_specs            │ 2       │ version=1, version=2 │
  │ agent_results           │ 4       │ A4 行 1 行 (UPSERT) │
  │ requirements            │ 1       │ design_revision_count=1 │
  │ approvals               │ 1       │ gate_level=1, decision='reject' │
  │ event_log               │ >=4     │ 含 gate1.reject + context.ready.A4(修订) │
  └─────────────────────────────────────────────────────┘
```

---

## 九、真实环境集成测试（7 条）

> 以下用例依赖真实外部服务，标记为 `@pytest.mark.integration`。

### 9.1 测试环境要求

| 组件 | 要求 |
|------|------|
| **PostgreSQL** | 真实 DB（test 库），含 design_specs 表 |
| **LLM (DeepSeek)** | 真实 API，用于 Spec/OpenAPI/ERD/DDL 生成 |
| **MCP Gateway** | 真实 Gateway，含 get_openapi_templates + get_erd_patterns + get_ddl_conventions |
| **NATS** | 嵌入式 nats-server -js |
| **目标数据库（内省）** | 真实 PostgreSQL 实例，含 information_schema 可查询 |

### 9.2 LLM 真实调用（3 条）

**T-A4-RL-001: 真实 LLM 生成六章 Spec**
```
输入:
  draft = {"title":"博客系统","description":"支持文章发布、评论、标签分类","domain":"内容管理","entities":[...],"use_cases":[...]}
  MCP: mock（减少外部依赖）

验证:
  - spec_doc 非空
  - spec_doc.title 非空
  - spec_doc.overview 非空（中文）
  - spec_doc.modules 长度 >= 1
  - spec_doc.data_models 长度 >= 1
  - 每个 data_model 含 name + fields

标记: @pytest.mark.integration @pytest.mark.llm
```

**T-A4-RL-002: 真实 LLM 生成 OpenAPI + ERD + DDL**
```
输入: 同上
       MCP: mock

验证:
  - openapi_schema.openapi = "3.0.0" 或 "3.1.0"
  - openapi_schema.paths 至少 3 个路径
  - erd_diagram.entities 至少 1 个实体
  - ddl_statements 以 CREATE TABLE 开头
  - 四件套同时产出，不丢失

标记: @pytest.mark.integration @pytest.mark.llm
```

**T-A4-RL-003: 修订场景 — LLM 产出改善**
```
输入:
  revision_context = {"is_revision":true, "gate1_rejection":{...},"previous_a5_report":{...}}

验证:
  - 修订后的 spec_doc 反映修订指引要求
  - quality_score 不低于首次 score（或至少不归零）
  - design_specs version 正确递增

标记: @pytest.mark.integration @pytest.mark.llm
```

### 9.3 MCP 真实调用（2 条）

**T-A4-RL-004: 三路 MCP 并行调用的真实延迟**
```
输入: domain = "order_management"

验证:
  - get_openapi_templates 在 ≤ 5s 返回
  - get_erd_patterns 在 ≤ 5s 返回
  - get_ddl_conventions 在 ≤ 5s 返回
  - 三路各自返回结构符合预期

标记: @pytest.mark.integration @pytest.mark.mcp @pytest.mark.slow
```

**T-A4-RL-005: MCP 全部超时 → L2 降级**
```
模拟: 通过防火墙规则使 MCP Gateway 不可达

验证:
  - source = "llm_no_mcp"
  - 不抛异常
  - 四件套仍产出（基于内置默认值）

标记: @pytest.mark.integration @pytest.mark.mcp @pytest.mark.resilience
```

### 9.4 DB 内省 + NATS（2 条）

**T-A4-RL-006: DB 内省 — 检测真实现有表**
```
前置: 目标数据库含测试表

验证:
  - _detect_existing_tables 返回非空列表
  - 返回的表信息含 table_name + columns
  - 增量 DDL 仅含新表

标记: @pytest.mark.integration @pytest.mark.db
```

**T-A4-RL-007: context.ready.A4 → A4 → agent.result.A4 全链路**
```
前置:
  - 嵌入式 nats-server -js
  - A4 Worker 订阅就绪
  - DB 含 A1/A2/A3 产物

步骤: NATS 发布 context.ready.A4

验证:
  - agent.result.A4 在 ≤ 60s 发布
  - payload 含完整四件套
  - DB design_specs + agent_results 已写入

  注: 真实环境超时预期 60s（含真实 LLM 生成耗时），集成测试 mock 场景为 30s。

标记: @pytest.mark.integration @pytest.mark.nats @pytest.mark.slow
```

---

## 十、测试环境与 Mock 策略

### 10.1 依赖隔离

| 组件 | 测试策略 |
|------|---------|
| **PostgreSQL** | 真实 DB（test 库），每个测试函数用事务回滚 |
| **LLM (DeepSeek)** | 全部 mock：SpecGenerator/APISchemaGenerator/ERDGenerator 返回预定义数据或抛异常 |
| **MCP Gateway** | 单元测试 mock `A4KnowledgeClient`；集成测试用真实 Gateway |
| **NATS** | 集成测试用嵌入式 NATS（`nats-server -js`），单元测试 mock |
| **目标数据库（内省）** | 单元测试 mock `_detect_existing_tables`；集成测试用真实 DB |

### 10.2 数据夹具（Fixtures）

```python
# 标准 context_package（模拟 Orchestrator 传入）
MOCK_CONTEXT_PACKAGE_A4 = {
    "req_id": "test-req-a4-001",
    "session_id": "test-sid-001",
    "cycle": 0,
    "a1_output": {
        "requirement_draft": {
            "title": "博客系统",
            "description": "支持文章发布和评论的内容管理系统",
            "domain": "内容管理",
            "entities": [
                {"name": "Article", "attributes": ["标题", "内容", "作者", "发布时间"], "description": "文章实体"},
                {"name": "Comment", "attributes": ["内容", "作者", "文章ID"], "description": "评论实体"},
            ],
            "use_cases": ["创建文章", "查看文章列表", "编辑文章", "删除文章", "发表评论"],
            "acceptance_criteria": ["Given 用户已登录 When 点击发布 Then 文章创建成功"],
            "constraints": ["需要支持Markdown编辑器"],
            "risks": ["高并发下评论去重"],
        },
        "wireframe_url": "https://s3/xxx/wireframe.png",
        "confidence_score": 0.85,
    },
    "a2_output": {
        "feasibility_assessment": {
            "technical": {"feasible": True, "assessment": "技术可行", "concerns": []},
            "business": {"feasible": True, "assessment": "业务方向可行", "concerns": []},
            "risk_level": "low",
        },
        "confirmation_checklist": [],
        "conflicts": [],
        "quality_score": 0.72,
    },
    "a3_output": {
        "prototype_url": "https://s3/xxx/prototype_v1.html",
        "screens": [
            {"name": "文章列表", "state": "default", "url": "https://s3/xxx/screen_list.png"},
        ],
    },
    "revision_context": {"is_revision": False, "revision_count": 0, "previous_a5_report": None, "gate1_rejection": None},
}

# 标准 LLM Spec 输出
MOCK_SPEC_DOC = {
    "title": "博客系统技术规格",
    "version": "1.0",
    "overview": "博客系统是一个内容管理平台，支持文章发布、编辑、评论和标签分类。系统面向内容创作者和读者两类用户。",
    "modules": [
        {
            "name": "文章管理模块",
            "description": "文章的核心 CRUD 功能，含列表/详情/编辑/创建四个视图",
            "states": ["列表页", "详情页", "编辑页", "创建页"],
            "state_machine": {
                "states": ["list", "detail", "edit", "create"],
                "transitions": [
                    {"from": "list", "to": "detail", "trigger": "点击文章行"},
                    {"from": "list", "to": "create", "trigger": "点击新建"},
                    {"from": "detail", "to": "edit", "trigger": "点击编辑"},
                    {"from": "edit", "to": "detail", "trigger": "保存成功"},
                    {"from": "create", "to": "detail", "trigger": "创建成功"},
                ],
            },
        },
    ],
    "data_models": [
        {
            "name": "Article",
            "fields": [
                {"name": "id", "type": "UUID", "nullable": False, "primary_key": True},
                {"name": "title", "type": "VARCHAR(255)", "nullable": False},
                {"name": "content", "type": "TEXT", "nullable": False},
                {"name": "author_id", "type": "UUID", "nullable": False},
                {"name": "created_at", "type": "TIMESTAMPTZ", "nullable": False, "default": "NOW()"},
            ],
        },
    ],
}

# 标准 OpenAPI 输出
MOCK_OPENAPI_SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "博客系统 API", "version": "1.0.0"},
    "paths": {
        "/articles": {
            "get": {"summary": "获取文章列表", "responses": {"200": {"description": "成功"}}},
            "post": {"summary": "创建文章", "responses": {"201": {"description": "创建成功"}}},
        },
        "/articles/{id}": {
            "get": {"summary": "获取文章详情", "responses": {"200": {"description": "成功"}}},
            "put": {"summary": "更新文章", "responses": {"200": {"description": "更新成功"}}},
            "delete": {"summary": "删除文章", "responses": {"204": {"description": "删除成功"}}},
        },
    },
    "components": {
        "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
    },
}

# 标准 ERD + DDL 输出
MOCK_ERD_RESULT = {
    "entities": [
        {
            "name": "Article",
            "fields": [
                {"name": "id", "type": "UUID", "primary_key": True},
                {"name": "title", "type": "VARCHAR(255)", "nullable": False},
                {"name": "content", "type": "TEXT", "nullable": False},
                {"name": "author_id", "type": "UUID", "nullable": False, "index": True},
                {"name": "created_at", "type": "TIMESTAMPTZ", "nullable": False},
            ],
            "relations": [],
        },
    ],
    "ddl": "CREATE TABLE articles (\n  id UUID PRIMARY KEY,\n  title VARCHAR(255) NOT NULL,\n  content TEXT NOT NULL,\n  author_id UUID NOT NULL,\n  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()\n);\nCREATE INDEX idx_articles_author ON articles(author_id);",
}

# Gate1 打回 revision_context
MOCK_REVISION_CONTEXT_A4 = {
    "is_revision": True,
    "revision_count": 1,
    "previous_a5_report": {
        "check_report": {
            "overall_score": 0.62,
            "dimensions": [
                {"dimension": "state_machine_closure", "label": "状态机闭合性", "score": 0.55,
                 "issues": [{"severity": "critical", "description": "评论审核流程的状态机缺少 'rejected' 终态"}]},
            ],
        },
    },
    "gate1_rejection": {
        "reject_reasons": [{"category": "spec_incomplete", "description": "评论审核流程未在 Spec 中描述"}],
        "revision_guidance": "请补充评论审核的状态机流转（含 approved/rejected 终态）",
    },
}
```

---

## 十一、测试执行清单

### 按 Phase 分配

| Phase | 测试编号 | 测试数 | 关键依赖 |
|-------|---------|:-----:|---------|
| **Phase 1** (DB) | T-A4-DB-001 → T-A4-DB-007 | 7 | PostgreSQL 就绪 |
| **Phase 2** (Unit: Agent+Quality) | T-A4-AG-001 → T-A4-AG-014, T-A4-QS-001 → T-A4-QS-005 | 19 | LLM mock 就绪 |
| **Phase 3** (Degradation+Integration) | T-A4-DG-001 → T-A4-DG-005, T-A4-IT-001 → T-A4-IT-007 | 12 | MCP+NATS mock 就绪 |
| **Phase 4** (Edge+E2E) | T-A4-CC-001 → T-A4-CC-004, T-A4-E2E-001 → T-A4-E2E-002 | 6 | 全链路环境就绪 |
| **Phase 5** (Real Env) | T-A4-RL-001 → T-A4-RL-007 | 7 | LLM/NATS/MCP/DB 真实服务 |

### 测试通过标准

- **Phase 1**: 7/7 通过 → design_specs 表结构正确，约束生效，UPSERT 行为正确
- **Phase 2**: 19/19 通过 → Spec 六章生成正确，API/ERD/DDL 生成器正确，质量评分公式正确，校验器正确
- **Phase 3**: 12/12 通过 → 三层降级链正确，六阶段流水线完整，NATS 发布正确，Gate1 打回 revision_context 解析正确
- **Phase 4**: 6/6 通过 → 并发安全，边界覆盖，E2E 全链路数据一致
- **Phase 5**: 7/7 通过 → 真实 LLM/MCP/DB/NATS 环境下行为正确

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
**总测试数**: 51 条（数据库 7 + Agent 单元 14 + 质量评分 5 + 降级链 5 + 集成 7 + 并发 4 + E2E 2 + 真实环境集成 7）
