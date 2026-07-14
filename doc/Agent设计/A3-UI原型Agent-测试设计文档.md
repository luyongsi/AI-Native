# A3 UI 原型 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.0
- **日期**: 2026-07-13
- **参考**: [A3 开发设计文档](./A3-UI原型Agent-开发设计文档.md) · [A3 完整设计规格](../Agent规格/A3-UI原型Agent完整设计.md) · [阶段二数据字典](../Agent规格/阶段二-数据字典.md)
- **测试范围**: A3 全功能验证（数据库 → API → Agent → SSE → S3 上传 → 持久化 → Outbox → Gate1 打回返工）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常流程 + 打回修订全链路
            ├──────────────┤
            │  真实环境集成  │  8 条：LLM + MCP + NATS + S3 真实服务
            ├──────────────┤
            │  集成测试     │  11 条：API + DB + Agent + SSE + Outbox 联合验证
            ├──────────────┤
            │  单元测试     │  20 条：PrototypeBuilder、AnnotationHandler、DesignTokenMapper、VisualDiff
            ├──────────────┤
            │  数据库测试   │  8 条：DDL、约束、版本管理、annotations 结构
            └──────────────┘
```

---

## 二、数据库层测试（8 条）

### 2.1 prototype_artifacts 表

**T-A3-DB-001: prototype_artifacts 表可创建**
```
输入: 执行 migration（含 prototype_artifacts DDL）

验证 SQL:
  SELECT table_name FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name = 'prototype_artifacts';

预期结果: 返回 1 行
```

**T-A3-DB-002: 基本 INSERT + 默认值**
```
输入:
  INSERT INTO prototype_artifacts (req_id, cycle, version, prototype_url, html_content, screens)
  VALUES ('<req_id>', 0, 1, 'https://s3/xxx/v1.html', '<html>...</html>',
          '[{"name":"列表页","state":"default","url":"https://s3/xxx/screen.png"}]'::jsonb);

验证 SQL:
  SELECT status, version, annotations, created_at, updated_at
  FROM prototype_artifacts WHERE req_id = '<req_id>' AND version = 1;

预期结果:
  status = 'draft'
  version = 1
  annotations = '[]'::jsonb
  created_at IS NOT NULL
  updated_at IS NOT NULL
```

**T-A3-DB-003: UNIQUE (req_id, cycle, version) 约束**
```
步骤 1:
  INSERT INTO prototype_artifacts (req_id, cycle, version) VALUES ('<req_id>', 0, 1);
  → 成功

步骤 2:
  INSERT INTO prototype_artifacts (req_id, cycle, version) VALUES ('<req_id>', 0, 1);
  → 预期: ERROR 23505 (duplicate key)
```

**T-A3-DB-004: 版本递增管理 — 同 req_id+cycle 多个 version**
```
输入:
  INSERT INTO prototype_artifacts (req_id, cycle, version, status) VALUES ('<req_id>', 0, 1, 'draft');
  INSERT INTO prototype_artifacts (req_id, cycle, version, status) VALUES ('<req_id>', 0, 2, 'draft');
  INSERT INTO prototype_artifacts (req_id, cycle, version, status) VALUES ('<req_id>', 0, 3, 'confirmed');

验证 SQL:
  SELECT version, status FROM prototype_artifacts
  WHERE req_id = '<req_id>' AND cycle = 0 ORDER BY version;

预期结果: 3 行
  version=1, status='draft'
  version=2, status='draft'
  version=3, status='confirmed'
```

**T-A3-DB-005: annotations JSONB 结构完整存储**
```
输入:
  INSERT INTO prototype_artifacts (req_id, cycle, version, annotations)
  VALUES ('<req_id>', 0, 1, '[
    {"annotation_id":"a1","element_id":"#table","type":"layout_change","comment":"调整列宽","position":{"x":120,"y":45},"created_at":"2026-07-13T10:00:00Z"},
    {"annotation_id":"a2","element_id":"#search","type":"content_change","comment":"修改占位文字","position":{"x":80,"y":20},"created_at":"2026-07-13T10:05:00Z"}
  ]'::jsonb);

验证 SQL:
  SELECT jsonb_array_length(annotations) as ann_count,
         annotations->0->>'type' as first_type,
         annotations->1->>'element_id' as second_element
  FROM prototype_artifacts WHERE req_id = '<req_id>';

预期结果:
  ann_count = 2
  first_type = 'layout_change'
  second_element = '#search'
```

**T-A3-DB-006: annotations append 模式 — 不覆盖已有标注**
```
步骤 1: INSERT version=1, annotations = '[{"annotation_id":"a1","type":"layout_change","comment":"初版标注"}]'::jsonb
步骤 2: INSERT version=2, annotations = (已有 + 新标注合并后写入)

验证 SQL:
  SELECT version, jsonb_array_length(annotations) FROM prototype_artifacts
  WHERE req_id = '<req_id>' ORDER BY version;

预期结果:
  version=1: 1 条标注
  version=2: 2 条标注（append 后保留全部历史）
```

**T-A3-DB-007: screens JSONB 结构验证**
```
输入:
  INSERT INTO prototype_artifacts (req_id, cycle, version, screens)
  VALUES ('<req_id>', 0, 1, '[
    {"name":"列表页-默认状态","description":"用户列表含搜索和分页","url":"https://s3/xxx/s1.png","state":"default"},
    {"name":"列表页-加载中","description":"骨架屏","url":"https://s3/xxx/s2.png","state":"loading"},
    {"name":"列表页-空数据","description":"空状态引导","url":"https://s3/xxx/s3.png","state":"empty"}
  ]'::jsonb);

验证 SQL:
  SELECT jsonb_array_length(screens) as screen_count,
         screens->0->>'state' as first_state,
         screens->2->>'state' as third_state
  FROM prototype_artifacts WHERE req_id = '<req_id>';

预期结果:
  screen_count = 3
  first_state = 'default'
  third_state = 'empty'
```

**T-A3-DB-008: agent_results A3 UPSERT 覆盖写入**
```
步骤 1:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A3', 0, 'completed', '{"version":1}'::jsonb);
  → 成功

步骤 2:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A3', 0, 'completed', '{"version":3,"annotation_count":5}'::jsonb)
  ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
  SET artifact = EXCLUDED.artifact, status = EXCLUDED.status;

验证 SQL:
  SELECT artifact->>'version' as v, artifact->>'annotation_count' as ac
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A3' AND cycle = 0;

预期结果:
  v = '3'
  ac = '5'
  count(*) = 1
```

---

## 三、A3 Agent 单元测试（12 条）

### 3.1 PrototypeBuilder 流式生成

**T-A3-AG-001: 完整事件序列（MCP 正常）**
```
输入:
  draft = {"title":"用户管理系统","domain":"企业后台","entities":[...],"use_cases":[...]}
  templates = [{"name":"后台管理模板","match_score":0.9}]
  design_system = {"components":["Table","SearchBar","Modal","Form"]}
  LLM mock: 流式返回完整 HTML

预期事件序列（按顺序）:
  1. ("thinking", {"message": "正在分析需求结构..."})
  2. ("knowledge", {"templates": [...], "design_system": {...}})
  3. ("prototype_update", {"html_chunk": "<div...", "progress": 0.X})  ← 至少 1 次
  4. ("screens", {"screens": [...]})
  5. ("done", {"prototype_url": "https://s3/...", "version": 1, "screens": [...]})

验证:
  - 事件序列不包含 error 事件
  - done 事件的 prototype_url 为合法 S3 URL
  - done.version = 1
  - screens 数组含 default/loading/empty/error 四个状态
  - knowledge 事件在 prototype_update 之前
```

**T-A3-AG-002: MCP 全部超时 → 跳过知识增强**
```
输入:
  MCP mock: get_ui_templates + get_design_system 均抛 TimeoutError
  LLM mock: 正常流式返回

验证:
  - 事件序列: thinking → prototype_update → screens → done
  - 不出现 knowledge 事件
  - done 事件正常产出（prototype_url 非空）
  - 无 error 事件
```

**T-A3-AG-003: LLM 不可用 → 降级到 fallback 模板**
```
输入:
  LLM mock: 抛 LLMException
  domain = "企业后台"

验证:
  - SSE 流以 error 事件结束: {"message": "生成失败，已降级到模板模式"}
  - 随后 done 事件产出，prototype_url 指向 fallback 模板 URL（非 null）
  - 日志中出现 "fallback template" 记录
```

**T-A3-AG-004: 打回修订 context 注入**
```
输入:
  revision_context = {
    "is_revision": true,
    "gate1_rejection": {
      "reject_reasons": [{"category":"prototype_change_needed","description":"列表页缺少批量操作"}],
      "revision_guidance": "请在列表页增加批量选择和批量删除功能"
    }
  }

验证:
  - _build_prompt 产出的 prompt 文本中包含 "列表页缺少批量操作"
  - prompt 文本中包含 "批量选择和批量删除"
  - 事件序列正常产出
```

### 3.2 AnnotationHandler 标注解析

**T-A3-AG-005: parse 正常解析多条标注**
```
输入:
  annotations = [
    {"annotation_id":"a1","element_id":"#table-header","type":"layout_change","comment":"三列等宽","position":{"x":120,"y":45}},
    {"annotation_id":"a2","element_id":"#search-bar","type":"style_change","comment":"搜索框改为圆角","position":{"x":80,"y":20}}
  ]

验证:
  parsed = AnnotationHandler.parse(annotations)
  len(parsed) = 2
  parsed[0].intent 包含 "三列等宽"
  parsed[0].target_element = "#table-header"
  parsed[1].intent 包含 "圆角"
```

**T-A3-AG-006: parse 空标注列表 → 返回空**
```
输入: annotations = []
验证: parsed = []，不抛异常
```

**T-A3-AG-007: parse 无效 type → 标记为 unknown**
```
输入:
  annotations = [{"annotation_id":"a1","element_id":"#x","type":"invalid_type","comment":"测试"}]

验证:
  - parse 不抛异常
  - parsed[0].type = "unknown" 或保留原值但标注 warning
```

**T-A3-AG-008: apply 流式增量更新**
```
输入:
  current_html = "<div id='table'><table>...</table></div>"
  parsed = [{"annotation_id":"a1","target_element":"#table","intent":"添加排序功能","type":"layout_change"}]
  LLM mock: 流式返回更新后的 HTML 片段

验证:
  - apply 是 AsyncIterator，yield 至少 1 个 chunk
  - 最终累积的 HTML 包含 "sort" 或 "排序" 相关标记
  - 不改变未标注区域的 HTML 结构（diff 仅限 #table 区域）
```

### 3.3 DesignTokenMapper

**T-A3-AG-009: map_domain 返回正确 token 集合**
```
输入:
  domain = "企业后台"

验证:
  tokens = DesignTokenMapper.map_domain("企业后台")
  tokens 包含 keys: colors, spacing, typography, border_radius, shadow
  tokens.colors.primary 非空
  tokens.spacing.md = 16
```

**T-A3-AG-010: map_domain 未知 domain → 使用默认 enterprise tokens**
```
输入: domain = "unknown_domain_xyz"
验证:
  tokens = DesignTokenMapper.map_domain("unknown_domain_xyz")
  tokens.colors.primary = "#1890FF"  (enterprise 默认)
  不抛异常
```

### 3.4 VisualDiff

**T-A3-AG-011: compare 返回差异报告结构**
```
输入:
  v1_url = "https://s3/xxx/prototype_v1.html"
  v2_url = "https://s3/xxx/prototype_v2.html"

验证:
  result = await VisualDiff.compare(v1_url, v2_url)
  result 包含 keys: diff_pixels, diff_percentage, diff_regions, passed
  result.diff_percentage 为 0-100 的浮点数
  result.passed 为 bool
  result.diff_regions 为数组，每个元素含 {x, y, w, h}
```

**T-A3-AG-012: compare 相同 URL → diff = 0**
```
输入: v1_url = v2_url（同一 URL）
验证: result.diff_percentage ≈ 0, result.passed = True
```

---

## 四、SSE 事件流解析测试（6 条）

### 4.1 SSE 格式解析

**T-A3-SSE-001: 单事件完整解析**
```
输入 buffer:
  "event: thinking\ndata: {"message":"正在分析需求..."}\n\n"

验证:
  - 解析出 event = "thinking"
  - data.message = "正在分析需求..."
```

**T-A3-SSE-002: 流式 chunk 分片 — 跨 buffer 拼接**
```
模拟 SSE 流:
  chunk1: "event: prototype_upda"
  chunk2: "te\ndata: {"html_chunk":"<div","progress":0.3}\n\n"

验证:
  - 不提前解析（事件名不完整）
  - chunk2 到达后完整解析
  - event = "prototype_update"
  - data.html_chunk = "<div"
```

**T-A3-SSE-003: 多个事件连续 — 逐个解析**
```
输入 buffer:
  "event: thinking\ndata: {"message":"分析中..."}\n\nevent: knowledge\ndata: {"templates":[]}\n\n"

验证:
  - 第一个事件: thinking
  - 第二个事件: knowledge
  - 两个事件都正确解析
```

**T-A3-SSE-004: data 中含换行符 — 正确识别 event 边界**
```
输入 buffer:
  "event: prototype_update\ndata: {"html_chunk":"<div\\n  class=\\"header\\"","progress":0.5}\n\n"

验证:
  - data.html_chunk 包含换行符 "\n  class=\"header\""
  - progress = 0.5
```

**T-A3-SSE-005: error 事件 → handler 调用**
```
输入 buffer:
  "event: error\ndata: {"message":"生成失败，已降级到模板模式"}\n\n"

验证:
  - handlers.error 被调用
  - data.message = "生成失败，已降级到模板模式"
```

**T-A3-SSE-006: 连接中断 → finally 持久化已生成内容**
```
步骤:
  1. POST /api/prototype/generate
  2. 收到 3 个 prototype_update 事件后主动关闭连接
  3. 不等待 done 事件

验证:
  DB:
    - prototype_artifacts 存在 1 行，status='draft'
    - html_content 非空（已生成部分的 HTML）
    - version = 1

  注: 中断持久化依赖开发设计中的 finally 块逻辑（见开发设计文档 §8 异常处理表 "SSE 连接中断" 行）。
      测试前需确认 finally 块的执行时机——HTML 持久化发生在 done 事件之前（S3 上传后），
      若中断发生在 S3 上传前，则 html_content 为 LLM 输出的部分片段而非完整 HTML。

---

## 五、API 接口测试（13 条）

### 5.1 `GET /api/prototype/context/{req_id}`

**T-A3-API-001: 首次进入 — 无已有原型**
```
前置: requirements.phase='design', design_status='prototyping'
       prototype_artifacts 无记录

请求: GET /api/prototype/context/<req_id>
      Headers: Authorization: Bearer <valid_jwt>

验证:
  HTTP 200
  Response:
    req_id = '<req_id>'
    design_status = 'prototyping'
    requirement_summary.title 非空
    prototype.has_existing = false
    prototype.current_version = null
    revision_context = {"is_revision": false, "gate1_rejection": null}
```

**T-A3-API-002: 有已有原型 — 返回最新版本**
```
前置: prototype_artifacts 有 version=1,2,3 三行

请求: GET /api/prototype/context/<req_id>

验证:
  HTTP 200
  Response:
    prototype.has_existing = true
    prototype.current_version = 3
    prototype.status = 当前 MAX(version) 的 status
    prototype.prototype_url 非空
    prototype.screens 数组长度 >= 1
    prototype.annotations 数组长度 >= 0
```

**T-A3-API-003: Gate1 打回 revision_context**
```
前置: requirements.design_status='prototyping', design_revision_count=1
       approvals 表有 gate_level=1, decision='reject' 记录

请求: GET /api/prototype/context/<req_id>

验证:
  HTTP 200
  Response:
    revision_context.is_revision = true
    revision_context.gate1_rejection.reject_reasons 非空
    revision_context.gate1_rejection.revision_guidance 非空
```

**T-A3-API-004: 未认证 → 401**
```
请求: 无 Authorization header
验证: HTTP 401
```

### 5.2 `POST /api/prototype/generate`

**T-A3-API-005: 正常生成 — SSE 流完整**
```
前置: requirements.phase='design', design_status='prototyping'
       agent_results 有 A1, A2 记录

请求: POST /api/prototype/generate
      Body: {"req_id": "<req_id>", "session_id": "<sid>"}

验证:
  HTTP 200
  Content-Type: text/event-stream

  SSE 事件序列:
    event: thinking → data.message 非空
    event: knowledge → data.templates 为数组
    event: prototype_update → data.html_chunk 非空 (多次)
    event: screens → data.screens 为数组
    event: done → data.prototype_url 非空, data.version >= 1

DB 验证:
  SELECT prototype_url, version, status, screens FROM prototype_artifacts
  WHERE req_id = '<req_id>' AND cycle = 0 ORDER BY version DESC LIMIT 1;
  预期: status='draft', prototype_url 非空, screens 数组非空
```

**T-A3-API-006: design_status 不符 → 400**
```
前置: requirements.design_status = 'spec_writing'（非 prototyping）

请求: POST /api/prototype/generate
验证: HTTP 400, detail 包含 "prototyping"
```

**T-A3-API-007: req_id 不存在 → 404**
```
请求: POST /api/prototype/generate
      Body: {"req_id": "<nonexistent>", "session_id": "<sid>"}
验证: HTTP 404
```

### 5.3 `POST /api/prototype/annotate`

**T-A3-API-008: 正常标注 → SSE 流更新**
```
前置: prototype_artifacts 有 version=1

请求: POST /api/prototype/annotate
      Body: {
        "req_id": "<req_id>",
        "session_id": "<sid>",
        "annotations": [
          {"annotation_id":"a1","element_id":"#table","type":"layout_change","comment":"三列等宽","position":{"x":120,"y":45}}
        ]
      }

验证:
  HTTP 200
  SSE 事件序列:
    event: thinking
    event: annotation_parsed → data.parsed[0].intent 非空
    event: prototype_update → 增量 HTML chunk
    event: done → data.version = 2

DB 验证:
  SELECT version, jsonb_array_length(annotations) FROM prototype_artifacts
  WHERE req_id = '<req_id>' ORDER BY version DESC LIMIT 1;
  预期: version=2, annotations 含新标注
```

**T-A3-API-009: 多条标注一次提交**
```
请求: POST /api/prototype/annotate
      Body: {"req_id":"...","session_id":"...","annotations": [
        {"annotation_id":"a1","element_id":"#x","type":"layout_change","comment":"c1","position":{"x":0,"y":0}},
        {"annotation_id":"a2","element_id":"#y","type":"style_change","comment":"c2","position":{"x":0,"y":0}},
        {"annotation_id":"a3","element_id":"#z","type":"add_element","comment":"c3","position":{"x":0,"y":0}}
      ]}

验证:
  - SSE 流正常完成
  - done.version 递增
  - DB annotations JSONB 数组长度 = 上次 + 3
```

**T-A3-API-010: 空标注列表 → 400**
```
请求: POST /api/prototype/annotate
      Body: {"req_id":"...","session_id":"...","annotations": []}
验证: HTTP 400
```

### 5.4 `POST /api/prototype/confirm`

**T-A3-API-011: 正常确认 — 完整事务**
```
前置: prototype_artifacts 有 version=3, status='draft'
       requirements.design_status='prototyping'

请求: POST /api/prototype/confirm
      Body: {"req_id": "<req_id>", "session_id": "<sid>", "final_notes": "原型已确认"}

验证:
  HTTP 200
  Response: {"ok": true, "req_id": "<req_id>", "version": 3}

DB 验证:
  -- prototype_artifacts 最新版本 confirmed
  SELECT status FROM prototype_artifacts
  WHERE req_id = '<req_id>' AND version = 3;
  预期: 'confirmed'

  -- agent_results A3 写入
  SELECT agent_key, cycle, status FROM agent_results
  WHERE req_id = '<req_id>' AND agent_key = 'A3';
  预期: 1 行, status='completed'

  -- requirements.design_status 更新
  SELECT design_status FROM requirements WHERE id = '<req_id>';
  预期: 'spec_writing'

  -- event_log outbox 写入
  SELECT event_name, direction, outbox_status FROM event_log
  WHERE req_id = '<req_id>' AND event_name = 'agent.result.A3';
  预期: 1 行, direction='OUT', outbox_status='pending'
```

**T-A3-API-012: 重复确认 — UPSERT 幂等**
```
前置: T-A3-API-011 已确认

请求: POST /api/prototype/confirm
      Body: {"req_id": "<req_id>", "session_id": "<sid>"}

验证:
  HTTP 200
  DB: agent_results A3 同一 cycle 仍然只有 1 行（UPSERT 覆盖）
```

### 5.5 `GET /api/prototype/history/{req_id}`

**T-A3-API-013: 正常历史查询**
```
前置: prototype_artifacts 有 version=1,2,3 共 3 行

请求: GET /api/prototype/history/<req_id>

验证:
  HTTP 200
  Response:
    req_id = '<req_id>'
    versions 数组长度 = 3
    versions[0].version = 3（最新在前）
    versions[2].version = 1（最旧在后）
    每个 version 含 prototype_url, annotations, created_at
```

**T-A3-API-014: history — req_id 不存在**
```
前置: req_id 不存在

请求: GET /api/prototype/history/<nonexistent_req_id>

验证: HTTP 404
```

**T-A3-API-015: context — req_id 不存在**
```
前置: req_id 不存在

请求: GET /api/prototype/context/<nonexistent_req_id>

验证: HTTP 404
```

**T-A3-API-016: annotate — 无已有原型时拒绝**
```
前置: prototype_artifacts 无记录（尚未 generate）

请求: POST /api/prototype/annotate
      Body: {"req_id":"<req_id>","session_id":"<sid>","annotations":[...]}

验证: HTTP 400（不可对不存在的原型提交标注）
```

### 5.6 API 编号说明

T-A3-API-013 原为最后一个 API 用例。T-A3-API-014/015/016 为审计后新增的异常路径覆盖。

---

## 六、Outbox + NATS 测试（4 条）

**T-A3-OT-001: confirm → event_log OUT 写入 + Outbox 发布**
```
前置: 确认原型

验证:
  - event_log 有 direction='OUT', event_name='agent.result.A3', outbox_status='pending'
  - Outbox Publisher 发布 NATS agent.result.A3
  - event_log.outbox_status → 'published'
  - NATS 消息 payload.req_id 匹配
  - NATS 消息 payload.prototype_url 非空
```

**T-A3-OT-002: NATS 不可用 → 保持 pending**
```
前置: event_log (OUT, pending)
步骤: 关闭 NATS，触发 Outbox 发布

验证:
  - outbox_status 保持 'pending'
  - Publisher 不崩溃
```

**T-A3-OT-003: 5 次重试全部失败 → failed**
```
验证:
  - 5 次重试后 outbox_status = 'failed'
  - 第 6 次轮询跳过该记录
```

**T-A3-OT-004: MC Backend 订阅 context.ready.A3 → session REOPENED**
```
前置:
  - requirements: design_status='prototyping', design_revision_count=1
  - dialogue_sessions: status='completed'

模拟: NATS 发布 context.ready.A3 (含 gate1_rejection, a3_rework=true)

验证:
  DB:
    dialogue_sessions.status = 'reopened'
    dialogue_messages 新增 1 条 role='system', content.type='gate1_rejection'
    event_log direction='IN', event_name='context.ready.A3'
```

---

## 七、Gate1 打回 A3 返工全链路测试（4 条）

**T-A3-GT-001: Gate1 打回 a3_rework=true → context.ready.A3 收到**
```
前置:
  - requirements: design_status='spec_writing'（A3 已确认，A4/A5/Gate1 已完成）
  - Gate1 审批人勾选 a3_rework=true

模拟: Orchestrator 发布 context.ready.A3 (含 gate1_rejection)

验证:
  - requirements.design_status = 'prototyping'
  - requirements.design_revision_count 递增
  - prototype_artifacts 最新版本 status 仍为 'confirmed'（旧版保留）
  - context.ready.A3 payload.revision_context.is_revision = true
```

**T-A3-GT-002: 返工修订 → 新版 prototype_artifacts**
```
前置: T-A3-GT-001（打回已发生）

步骤:
  1. POST /api/prototype/annotate（提交修订标注）
  2. POST /api/prototype/confirm

验证:
  - prototype_artifacts 新增 1 行，version = 上次 MAX + 1
  - 新行 status = 'draft' → 'confirmed'（确认后）
  - agent_results A3 同一 cycle UPSERT 覆盖
  - design_status = 'spec_writing'（再次进入 A4）
```

**T-A3-GT-003: 返工 cycle 不变**
```
前置: T-A3-GT-001

验证:
  - 返工前后 prototype_artifacts.cycle 不变
  - agent_results A3.cycle 不变
  - requirements.gate_rejection_count 不变（design_revision_count 递增）
```

**T-A3-GT-004: Gate1 拒绝但 a3_rework=false → A3 不返工**
```
前置: Gate1 审批人未勾选 a3_rework

模拟: Orchestrator 发布 agent.result.gate1.reject (a3_rework=false)

验证:
  - context.ready.A3 不被发布
  - design_status 直接更新为 'spec_writing' → A4 修订
  - prototype_artifacts 无新行
```

---

## 八、并发与边界测试（6 条）

**T-A3-CC-001: 并发 annotate → 版本串行递增**
```
步骤: 同时发起两个 POST /api/prototype/annotate

验证:
  - 两个请求都返回 HTTP 200
  - prototype_artifacts 新增 2 行（version 连续递增）
  - 无 UNIQUE 冲突错误
```

**T-A3-CC-002: 并发 confirm → 幂等**
```
步骤: 同时两个 POST /api/prototype/confirm

验证:
  - 都返回 200
  - agent_results A3 只有 1 行
  - design_status 只更新 1 次
```

**T-A3-CC-003: S3 上传失败 → Base64 inline 降级**
```
前置: S3 mock 抛异常

步骤: POST /api/prototype/generate

验证:
  - done 事件正常产出
  - prototype_artifacts.html_content 非空（Base64 inline）
  - prototype_artifacts.prototype_url IS NULL
```

**T-A3-CC-004: SSE 流中断 → 部分 HTML 持久化**
```
步骤:
  1. POST /api/prototype/generate
  2. 收到 2 个 prototype_update 事件后主动关闭连接

验证:
  DB:
    - prototype_artifacts 存在 1 行, status='draft'
    - html_content 非空（已生成部分的 HTML）
```

**T-A3-CC-005: LLM 超时 → fallback 模板**
```
输入: LLM mock 抛 TimeoutError

验证:
  - error 事件产出: {"message": "生成失败，已降级到模板模式"}
  - prototype_artifacts 写入 status='draft'
  - html_content 含 fallback 模板内容
```

**T-A3-CC-006: 标注类型覆盖全部 7 种枚举**
```
输入: 依次提交 7 种标注类型

验证:
  - layout_change / content_change / style_change
  - add_element / remove_element / flow_change / other
  - 每种类型 SSE 流正常完成
  - DB annotations 类型字段正确存储
```

---

## 九、端到端测试（2 条）

### 9.1 正常全流程

**T-A3-E2E-001: 生成 → 标注 → 确认 → 数据完整链**

```
Step 1: 准备数据
  - requirements: phase='design', design_status='prototyping'
  - agent_results: A1 cycle=0, A2 cycle=0
  - GET /api/prototype/context/<req_id> → has_existing=false

Step 2: POST /api/prototype/generate
  → SSE 流式返回

  验证点:
    ✓ 事件序列: thinking → knowledge → prototype_update(N次) → screens → done
    ✓ done.version = 1
    ✓ done.prototype_url 非空
    ✓ prototype_artifacts 1 行, version=1, status='draft'
    ✓ screens 含 default/loading/empty/error

Step 3: POST /api/prototype/annotate
  Body: annotations = [
    {"annotation_id":"a1","element_id":"#table","type":"layout_change","comment":"调整列宽"},
    {"annotation_id":"a2","element_id":"#search","type":"style_change","comment":"搜索框圆角"}
  ]
  → SSE 流式更新

  验证点:
    ✓ annotation_parsed 事件含 2 条解析结果
    ✓ done.version = 2
    ✓ prototype_artifacts 新增 1 行, version=2
    ✓ annotations JSONB 含 2 条标注

Step 4: POST /api/prototype/annotate（第二轮标注）
  Body: annotations = [
    {"annotation_id":"a3","element_id":"#header","type":"add_element","comment":"增加批量操作按钮"}
  ]

  验证点:
    ✓ done.version = 3
    ✓ prototype_artifacts 新增 version=3
    ✓ annotations JSONB 含 3 条标注（append 模式）

Step 5: POST /api/prototype/confirm
  验证点:
    ✓ prototype_artifacts version=3 status='confirmed'
    ✓ agent_results A3 cycle=0 status='completed'
    ✓ agent_results.artifact.version = 3
    ✓ agent_results.artifact.annotation_count = 3
    ✓ requirements.design_status = 'spec_writing'
    ✓ event_log agent.result.A3 OUT, published

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                      │ 预期行数 │ 关键字段        │
  ├─────────────────────────────────────────────────────┤
  │ prototype_artifacts     │ 3       │ v1,v2=draft, v3=confirmed │
  │ agent_results           │ 1       │ A3, cycle=0, completed │
  │ requirements            │ 1       │ design_status='spec_writing' │
  │ event_log               │ 1       │ OUT, agent.result.A3 │
  └─────────────────────────────────────────────────────┘
```

### 9.2 Gate1 打回 A3 返工全流程

**T-A3-E2E-002: 生成 → 确认 → Gate1 打回(a3_rework=true) → 返工修订 → 重新确认**

```
Step 1-5: 同 T-A3-E2E-001（完成首次确认）

Step 6: 模拟 Gate1 打回 a3_rework=true
  - Orchestrator 更新 requirements: design_status='prototyping', design_revision_count=1
  - NATS 发布 context.ready.A3 (含 gate1_rejection)

  验证点:
    ✓ dialogue_sessions.status = 'reopened'
    ✓ dialogue_messages 新增 system 消息 (type='gate1_rejection')
    ✓ requirements.design_status = 'prototyping'

Step 7: 用户修订
  POST /api/prototype/annotate
  Body: annotations = [
    {"annotation_id":"a4","element_id":"#table","type":"add_element","comment":"增加批量选择列"}
  ]

  验证点:
    ✓ done.version = 4
    ✓ prototype_artifacts version=4, status='draft'
    ✓ cycle 仍为 0（不变）

Step 8: POST /api/prototype/confirm
  验证点:
    ✓ prototype_artifacts version=4 status='confirmed'
    ✓ agent_results A3 cycle=0 UPSERT 覆盖
    ✓ requirements.design_status = 'spec_writing'
    ✓ requirements.design_revision_count = 1

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                      │ 预期行数 │ 关键字段        │
  ├─────────────────────────────────────────────────────┤
  │ prototype_artifacts     │ 4       │ v1,v2,v3,v4     │
  │ agent_results           │ 1       │ A3, cycle=0 (UPSERT) │
  │ requirements            │ 1       │ design_revision_count=1 │
  │ dialogue_sessions       │ 1       │ status='completed'(二次确认) │
  │ event_log               │ 2       │ agent.result.A3 × 2 次确认 │
  └─────────────────────────────────────────────────────┘
```

---

## 十、真实环境集成测试（8 条）

> 以下用例依赖真实外部服务，标记为 `@pytest.mark.integration`。

### 10.1 测试环境要求

| 组件 | 要求 |
|------|------|
| **PostgreSQL** | 真实 DB（test 库），含 prototype_artifacts 表和 migration |
| **LLM (DeepSeek)** | 真实 API，用于 HTML 原型生成和标注处理 |
| **MCP Gateway** | 真实 Gateway，含 get_ui_templates + get_design_system 工具 |
| **NATS** | 嵌入式 nats-server -js |
| **S3 / MinIO** | 本地 MinIO 实例，测试用 bucket |

### 10.2 LLM 真实调用（3 条）

**T-A3-RL-001: 真实 LLM 生成完整 HTML 原型**
```
输入:
  draft = {"title":"博客系统","domain":"内容管理","entities":[...],"use_cases":[...]}
  MCP: mock（减少外部依赖）

验证:
  - SSE 流以 done 事件结束（无 error）
  - done.prototype_url 非空
  - prototype_artifacts.html_content 为合法 HTML（含 <html> 或 <div> 标签）
  - html_content 长度 > 500 字符
  - screens 数组至少含 2 个状态

标记: @pytest.mark.integration @pytest.mark.llm
```

**T-A3-RL-002: 真实 LLM 标注处理 — 增量更新**
```
输入:
  current_html = (前一步生成的原型 HTML)
  annotations = [{"annotation_id":"a1","element_id":"#main","type":"style_change","comment":"将主题色改为深蓝"}]

验证:
  - SSE 流正常完成
  - 更新后的 HTML 与原始 HTML 不同（发生了变更）
  - 更新后 HTML 仍为合法 HTML
  - done.version = 上一版本 + 1

标记: @pytest.mark.integration @pytest.mark.llm
```

**T-A3-RL-003: 复杂多标注 LLM 处理**
```
输入:
  annotations = [
    {"annotation_id":"a1","element_id":"#table","type":"layout_change","comment":"增加分页组件"},
    {"annotation_id":"a2","element_id":"#search","type":"content_change","comment":"搜索框占位文字改为'请输入关键词搜索'"},
    {"annotation_id":"a3","element_id":"#header","type":"add_element","comment":"增加用户头像和退出按钮"}
  ]

验证:
  - 3 条标注同时处理，不丢失
  - 更新后 HTML 反映所有 3 条变更
  - 无 error 事件

标记: @pytest.mark.integration @pytest.mark.llm
```

### 10.3 MCP 真实调用（2 条）

**T-A3-RL-004: get_ui_templates 真实返回**
```
输入: domain = "企业后台"

验证:
  - MCP 调用在 5s 超时内返回
  - 返回数据为数组，每个元素含 name + match_score
  - SSE knowledge 事件含 templates 数据

标记: @pytest.mark.integration @pytest.mark.mcp
```

**T-A3-RL-005: get_design_system 真实返回**
```
输入: platform = "web"

验证:
  - MCP 调用在 5s 超时内返回
  - 返回数据含 components 数组
  - 至少包含 Table/Button/Form/Modal 等基础组件

标记: @pytest.mark.integration @pytest.mark.mcp
```

### 10.4 S3 真实集成（2 条）

**T-A3-RL-006: HTML 上传 S3 → URL 可访问**
```
前置: MinIO 实例运行中，bucket 已创建

步骤: POST /api/prototype/generate（原型生成 + 上传）

验证:
  - done.prototype_url 格式: http://localhost:9000/prototypes/<req_id>/v1.html
  - HTTP GET prototype_url → 200，返回 HTML 内容
  - S3 object Content-Type = text/html; charset=utf-8

标记: @pytest.mark.integration @pytest.mark.s3
```

**T-A3-RL-007: 截图上传 S3 → URL 可访问**
```
前置: MinIO 运行中

验证:
  - screens[0].url 可访问
  - HTTP GET 截图 URL → 200, Content-Type = image/png

标记: @pytest.mark.integration @pytest.mark.s3
```

### 10.5 NATS 真实集成（1 条）

**T-A3-RL-008: agent.result.A3 端到端发布与消费**
```
前置:
  - 嵌入式 nats-server -js
  - MC Backend 订阅已启动

步骤:
  1. POST /api/prototype/confirm
  2. NATS consumer 订阅 agent.result.A3

验证:
  - consumer 在 ≤ 3 秒内收到消息
  - 消息 payload.prototype_url 非空
  - event_log.outbox_status = 'published'

标记: @pytest.mark.integration @pytest.mark.nats
```

---

## 十一、测试环境与 Mock 策略

### 11.1 依赖隔离

| 组件 | 测试策略 |
|------|---------|
| **PostgreSQL** | 真实 DB（test 库），每个测试函数用事务回滚 |
| **LLM (DeepSeek)** | 全部 mock：`PrototypeBuilder.build_stream` 返回预定义 chunk 序列 |
| **MCP Gateway** | 单元测试 mock `MCPClient.call_tool`；集成测试用真实 Gateway |
| **S3 / MinIO** | 单元测试 mock `S3PrototypeStorage`；集成测试用本地 MinIO |
| **NATS** | 集成测试用嵌入式 NATS（`nats-server -js`），单元测试 mock |
| **JWT** | 测试用固定密钥签发 token |

### 11.2 数据夹具（Fixtures）

```python
# 标准 LLM HTML 流式 chunk 序列
MOCK_LLM_HTML_CHUNKS = [
    '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n',
    '<title>用户管理系统</title>\n<style>\nbody{font-family:sans-serif;margin:0;padding:0}\n',
    '.header{background:#1890FF;color:#fff;padding:16px 24px}\n',
    '.content{padding:24px}\ntable{width:100%;border-collapse:collapse}\n',
    '</style>\n</head>\n<body>\n<div class="header"><h1>用户管理系统</h1></div>\n',
    '<div class="content">\n<table>\n<thead><tr><th>用户名</th><th>邮箱</th><th>角色</th></tr></thead>\n',
    '<tbody><tr><td>张三</td><td>zhang@example.com</td><td>管理员</td></tr></tbody>\n</table>\n',
    '</div>\n</body>\n</html>',
]

# 标准 MCP 返回数据
MOCK_MCP_TEMPLATES = [
    {"name": "后台管理模板", "match_score": 0.92, "description": "含侧边栏+表格+弹窗的标准后台布局"},
    {"name": "数据看板模板", "match_score": 0.78, "description": "含图表卡片和统计面板"},
]

MOCK_MCP_DESIGN_SYSTEM = {
    "platform": "web",
    "components": ["Table", "SearchBar", "Modal", "Form", "Button", "Pagination", "Dropdown"],
    "color_palette": {"primary": "#1890FF", "success": "#52C41A", "warning": "#FAAD14", "danger": "#FF4D4F"},
    "font_family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
}

# 标准标注数据
MOCK_ANNOTATIONS = [
    {"annotation_id": "a1", "element_id": "#user-table-header", "type": "layout_change",
     "comment": "表格列宽需要调整为三列等宽", "position": {"x": 120, "y": 45}},
]

# 标准 Gate1 打回 payload (a3_rework)
MOCK_GATE1_A3_REWORK = {
    "gate_level": 1,
    "reject_reasons": [
        {"category": "prototype_change_needed", "description": "列表页缺少批量操作功能"}
    ],
    "revision_guidance": "请在列表页增加批量选择和批量删除功能",
    "a3_rework": True,
    "rejected_at": "2026-07-13T14:00:00Z",
}
```

---

## 十二、测试执行清单

### 按 Phase 分配

| Phase | 测试编号 | 测试数 | 关键依赖 |
|-------|---------|:-----:|---------|
| **Phase 1** (DB) | T-A3-DB-001 → T-A3-DB-008 | 8 | PostgreSQL 就绪 |
| **Phase 2** (Unit: Agent+SSE) | T-A3-AG-001 → T-A3-AG-012, T-A3-SSE-001 → T-A3-SSE-006 | 18 | LLM/MCP/S3 mock 就绪 |
| **Phase 3** (API+Outbox) | T-A3-API-001 → T-A3-API-016, T-A3-OT-001 → T-A3-OT-004 | 20 | NATS 就绪 |
| **Phase 4** (Gate1+Edge) | T-A3-GT-001 → T-A3-GT-004, T-A3-CC-001 → T-A3-CC-006 | 10 | 全链路环境 |
| **Phase 5** (E2E) | T-A3-E2E-001 → T-A3-E2E-002 | 2 | 全链路环境就绪 |
| **Phase 6** (Real Env) | T-A3-RL-001 → T-A3-RL-008 | 8 | LLM/NATS/MCP/S3 真实服务 |

### 测试通过标准

- **Phase 1**: 8/8 通过 → prototype_artifacts 表结构正确，约束生效，JSONB 操作正常
- **Phase 2**: 18/18 通过 → Agent 流式生成正确，标注解析正确，SSE 解析可靠，降级策略生效
- **Phase 3**: 20/20 通过 → API 契约完整，SSE 流正确，confirm 事务完整，Outbox 可靠
- **Phase 4**: 10/10 通过 → Gate1 打回链路正确，并发安全，边界覆盖
- **Phase 5**: 2/2 通过 → 全链路数据一致，打回修订闭环正确
- **Phase 6**: 8/8 通过 → 真实 LLM/MCP/S3/NATS 环境下行为正确

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
**总测试数**: 66 条（数据库 8 + Agent 单元 12 + SSE 解析 6 + API 16 + Outbox 4 + Gate1 返工 4 + 并发边界 6 + E2E 2 + 真实环境集成 8）
