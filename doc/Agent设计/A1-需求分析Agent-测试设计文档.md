# A1 需求分析 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-10
- **参考**: [A1 开发设计文档 v2.1](./A1-需求分析Agent-开发设计文档.md) · [阶段一数据字典 v1.3](../Agent规格/阶段一-数据字典.md)
- **测试范围**: A1 全功能验证（数据库 → API → Agent → SSE → 持久化 → Outbox → 打回修订）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视
- **重要提示**:
  - `event_log` 的 Outbox 列（`outbox_status`, `published_at`, `ck_outbox` 约束, `idx_event_log_outbox` 部分索引）以**开发设计文档 §2.6 为准**。数据字典 v1.3 为独立规格，不含 Outbox 实现细节，二者互补。
  - `understanding_snapshots.wireframe_data` 列以**开发设计文档 §2.5 为准**（v2.1 新增），数据字典 v1.3 尚未录入，后续升级时同步。

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常流程 + 打回修订全链路
            ├──────────────┤
            │  真实环境集成  │  12 条：LLM + MCP + NATS + S3 真实服务
            ├──────────────┤
            │  集成测试     │  12 条：API + DB + Agent + Outbox 联合验证
            ├──────────────┤
            │  单元测试     │  28 条：Agent、DraftBuilder、解析器、工具方法
            ├──────────────┤
            │  数据库测试   │  15 条：DDL、约束、索引、迁移
            └──────────────┘
```

---

## 二、数据库层测试（16 条）

### 2.1 DDL 执行

**T-DB-001: 全部 7 张表可创建**
```
输入: 执行 migration 008_phase_one_schema.py
验证 SQL:
  SELECT table_name FROM information_schema.tables
  WHERE table_schema = 'public'
    AND table_name IN (
      'requirements', 'agent_results', 'dialogue_sessions',
      'dialogue_messages', 'understanding_snapshots',
      'event_log', 'approvals'
    );
预期结果: 返回 7 行
```

**T-DB-002: requirements 表默认值**
```
输入: INSERT INTO requirements (title, status) VALUES ('测试需求', DEFAULT)
验证 SQL:
  SELECT status, gate_rejection_count, revision_count, analyzer_agent
  FROM requirements WHERE title = '测试需求';
预期结果:
  status           = 'draft'
  gate_rejection_count = 0
  revision_count   = 0
  analyzer_agent   = 'A1'
```

**T-DB-003: agent_results UNIQUE 约束**
```
步骤 1:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<uuid>', 'A1', 0, 'completed', '{}'::jsonb);
  → 成功

步骤 2:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<uuid>', 'A1', 0, 'completed', '{}'::jsonb);
  → 预期: ERROR 23505 (duplicate key)
```

**T-DB-004: dialogue_messages UNIQUE 约束**
```
步骤 1:
  INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number)
  VALUES ('<sid>', 'human', '{"text":"hi"}'::jsonb, 0, 1);
  → 成功

步骤 2:
  INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number)
  VALUES ('<sid>', 'human', '{"text":"hi again"}'::jsonb, 0, 1);
  → 预期: ERROR 23505
```

**T-DB-005: event_log CHECK 约束 `ck_outbox`**
```
-- OUT 方向必须填 outbox_status
INSERT INTO event_log (req_id, event_name, direction, payload, outbox_status)
VALUES ('<uuid>', 'agent.result.A1', 'IN', '{}'::jsonb, NULL);
→ 成功 (IN + NULL = OK)

INSERT INTO event_log (req_id, event_name, direction, payload, outbox_status)
VALUES ('<uuid>', 'agent.result.A1', 'IN', '{}'::jsonb, 'pending');
→ 成功 (IN + non-NULL = OK, CHECK 只要求 OUT 非空)

INSERT INTO event_log (req_id, event_name, direction, payload, outbox_status)
VALUES ('<uuid>', 'agent.result.A1', 'OUT', '{}'::jsonb, NULL);
→ 预期: ERROR 23514 (ck_outbox violation)

INSERT INTO event_log (req_id, event_name, direction, payload, outbox_status)
VALUES ('<uuid>', 'agent.result.A1', 'OUT', '{}'::jsonb, 'pending');
→ 成功
```

**T-DB-006: approvals CHECK 约束 `ck_approval_decision`**
```
-- pending 时 decision/reviewer/reviewed_at 必须 NULL
INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, decision)
VALUES ('<uuid>', '<sid>', 0, 0, 'pending', 'pass');
→ 预期: ERROR 23514

-- decided 时 decision/reviewer/reviewed_at 必须非 NULL
INSERT INTO approvals (req_id, session_id, gate_level, cycle, status, decision, reviewer_user_id, reviewed_at)
VALUES ('<uuid>', '<sid>', 0, 0, 'decided', NULL, NULL, NULL);
→ 预期: ERROR 23514
```

**T-DB-007: dialogue_messages CHECK role 枚举**
```
INSERT INTO dialogue_messages (session_id, role, content, sequence_number)
VALUES ('<sid>', 'bot', '{"text":"hi"}'::jsonb, 1);
→ 预期: ERROR 23514 (role not in 'human','ai','system')
```

**T-DB-008: event_log direction CHECK 枚举**
```
INSERT INTO event_log (event_name, direction, payload)
VALUES ('test', 'INCOMING', '{}'::jsonb);
→ 预期: ERROR 23514 (direction not in 'IN','OUT')

-- 额外验证: 字符串 'BOTH'（虽不在枚举中但也非 'INCOMING'）
INSERT INTO event_log (event_name, direction, payload)
VALUES ('test', 'BOTH', '{}'::jsonb);
→ 预期: ERROR 23514 (同样被 CHECK 拒绝)

-- 确认有效值均可插入
INSERT INTO event_log (event_name, direction, payload)
VALUES ('test1', 'IN', '{}'::jsonb);   → 成功
INSERT INTO event_log (event_name, direction, payload)
VALUES ('test2', 'OUT', '{}'::jsonb);  → 成功
```

**T-DB-009: dialogue_sessions req_id UNIQUE 约束**
```
-- 同一个 req_id 不能有两个 session
INSERT INTO dialogue_sessions (req_id) VALUES ('<req_id>');
INSERT INTO dialogue_sessions (req_id) VALUES ('<req_id>');
→ 第二条预期: ERROR 23505
```

**T-DB-010: requirements DELETE CASCADE 到 dialogue_sessions**
```
-- 删除 requirement 应该级联删除会话
SELECT count(*) FROM dialogue_sessions WHERE req_id = '<req_id>';
-- 记下 count = N
DELETE FROM requirements WHERE id = '<req_id>';
SELECT count(*) FROM dialogue_sessions WHERE req_id = '<req_id>';
→ 预期: 0
```

**T-DB-011: dialogue_sessions DELETE CASCADE 到 dialogue_messages**
```
DELETE FROM dialogue_sessions WHERE id = '<sid>';
SELECT count(*) FROM dialogue_messages WHERE session_id = '<sid>';
→ 预期: 0
```

**T-DB-012: dialogue_sessions DELETE CASCADE 到 understanding_snapshots**
```
DELETE FROM dialogue_sessions WHERE id = '<sid>';
SELECT count(*) FROM understanding_snapshots WHERE session_id = '<sid>';
→ 预期: 0
```

**T-DB-013: 所有索引存在**
```
验证 SQL:
  SELECT indexname FROM pg_indexes WHERE tablename IN (
    'requirements', 'agent_results', 'dialogue_messages',
    'understanding_snapshots', 'event_log', 'approvals'
  ) AND indexname != 'pg_toast_%';
预期结果: 至少包含
  - idx_requirements_status
  - idx_agent_results_req
  - idx_dialogue_messages_session_cycle
  - idx_understanding_snapshots_session_cycle
  - idx_event_log_req
  - idx_event_log_name
  - idx_event_log_outbox (partial index)
  - idx_approvals_req
```

**T-DB-014: event_log outbox 部分索引仅覆盖 pending 行**
```
验证 SQL:
  SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_event_log_outbox';
预期: WHERE outbox_status = 'pending'
```

**T-DB-015: requirements title 列为非空兼容性**
```
-- 允许不填 title（null 可插入）
INSERT INTO requirements (status) VALUES ('draft');
SELECT id FROM requirements WHERE title IS NULL;
→ 预期: 1 行
```

---

## 三、A1 Agent 单元测试（16 条）

### 3.1 A1Agent.analyze() 事件序列

**T-AG-001: 完整事件序列（MCP 正常）**
```
输入:
  user_message = "我想做一个用户管理系统，支持管理员增删改查用户"
  history = []
  current_draft = None
  cycle = 0
  MCP mock: 返回完整的 4 路数据

预期事件序列（按顺序）:
  1. {"type": "thinking",   "content": "正在检索知识库..."}
  2. {"type": "knowledge",  "sources": [{"name": "similar_requirements", "count": 3},
                                         {"name": "domain_risks", "count": 2},
                                         {"name": "tech_stack", "available": true},
                                         {"name": "cost_baseline", "available": true}]}
  3. {"type": "thinking",   "content": "正在分析需求..."}
  4. {"type": "draft_update", "draft": {...}}  ← 至少 1 次
  5. {"type": "clarification", "items": [...]} 或跳过（无澄清点）
  6. {"type": "wireframe", "data": {...}}       ← 可选（取决于 entities/use_cases）
  7. {"type": "done",        "draft": {...}, "confidence_score": N,
       "knowledge_sources": [...], "mcp_tools_used": [...]}

验证:
  - 事件序列不包含 error 事件
  - done 事件的 draft 包含 title、description、domain、entities 字段
  - confidence_score 在 [0, 1] 范围内
  - done.knowledge_sources 是摘要格式 [{"name","count/available"},...]
  - wireframe 事件仅在 _should_generate_wireframe 返回 True 时出现
```

**T-AG-002: 首次对话 draft 从空开始**
```
输入: current_draft = None
验证: 第 4 步 draft_update 事件至少有 title、description 两个字段有值
      后续 draft_update 事件逐步追加 entities、use_cases 等
```

**T-AG-003: 多轮对话 draft 从已有草案继续**
```
输入:
  current_draft = {
    "title": "用户管理系统",
    "description": "企业用户管理平台",
    "domain": "user_management",
    "entities": [{"name": "用户", "attributes": ["用户名","邮箱"], "description": "核心实体"}],
    "use_cases": ["管理员创建用户"],
    "acceptance_criteria": [],
    "constraints": [],
    "risks": [],
    "estimated_cost": null
  }
  user_message = "还需要支持角色管理和权限控制"

验证:
  - 所有 draft_update 事件的 draft 继承已有字段
  - 最终 done.draft.entities 包含 "用户" 和新增的 "角色" 实体
  - done.draft.use_cases 超过原有的 1 条
```

### 3.2 MCP 降级

**T-AG-004: 全部 4 个 MCP 超时 — 不阻塞**
```
输入: MCP mock 全部抛出 asyncio.TimeoutError
      LLM mock 返回最小草案: {"title": "测试", "description": null, "domain": "general",
                               "entities": null, "use_cases": [], "acceptance_criteria": [],
                               "constraints": [], "risks": [], "estimated_cost": null}
验证:
  - SSE 事件序列不变（thinking → knowledge(empty) → ... → done）
  - knowledge.sources = []（全部为空）
  - done.knowledge_sources = []
  - confidence_score = 0.5（仅基础分，draft 各字段均为 null/空，不加分；knowledge 全部空，不加分）
  - 无 error 事件

注意: 置信度验证依赖 LLM mock 输出的字段状态。若 LLM mock 产出了非空 description/entities/acceptance_criteria，
     则 confidence_score 会高于 0.5。此测试的 LLM mock 必须返回所有字段为 null/空的草案。
```

**T-AG-005: 单个 MCP 超时 — 其他正常**
```
输入: search_similar_requirements 抛 TimeoutError，其余 3 个正常
验证:
  - knowledge.sources: similar_requirements 不存在，其余 3 个存在
  - knowledge 内部: similar_requirements = [], domain_risks 有数据
  - confidence_score: similar_requirements 不加分
```

**T-AG-006: MCP 返回空结果 — 摘要正确**
```
输入:
  similar_requirements = []        (空列表)
  domain_risks = []                (空列表)
  tech_stack = {}                  (空字典)
  cost_baseline = None

验证:
  - knowledge.sources = []（全部为空/零）
  - confidence_score = 0.5（仅基础分）
```

### 3.3 类型安全防御

**T-AG-007: LLM 输出 entities=null — `_should_generate_wireframe` 不崩溃**
```
输入: draft = {"entities": null, "use_cases": null}
验证: _should_generate_wireframe 返回 False，不抛 TypeError
```

**T-AG-008: LLM 输出 acceptance_criteria=null — `_calculate_confidence` 不崩溃**
```
输入: draft = {"acceptance_criteria": null}
验证: isinstance(None, list) → False，不加分，不崩溃
```

**T-AG-009: BDD 输出 scenarios 含 dict — `_gwt_to_strings` 正确转换**
```
输入:
  gwt_result = {
    "scenarios": [
      {"given": "用户已登录", "when": "点击创建", "then": "弹出创建表单"},
      {"given": "表单已填写", "when": "点击提交", "then": "用户创建成功"}
    ],
    "coverage_score": 0.8
  }

验证输出:
  acceptance_criteria = [
    "Given 用户已登录 When 点击创建 Then 弹出创建表单",
    "Given 表单已填写 When 点击提交 Then 用户创建成功"
  ]
```

**T-AG-010: BDD 输出 scenarios 已是 string — 容错直通**
```
输入:
  gwt_result = {
    "scenarios": ["Given A When B Then C"],
    "coverage_score": 0.5
  }
验证输出:
  acceptance_criteria = ["Given A When B Then C"]
```

**T-AG-011: BDD 输出空 scenarios — 返回空列表**
```
输入: gwt_result = {"scenarios": [], "coverage_score": 0}
验证: _gwt_to_strings 返回 []
```

### 3.4 LLM 异常处理

**T-AG-012: DraftBuilder LLM 调用失败 → error 事件**
```
输入: DraftBuilder.stream_analyze 抛 LLMException
验证:
  - SSE 事件序列末尾为 {"type": "error", "content": "分析过程出错: ..."}
  - 前面的事件（thinking、knowledge）正常产出
```

**T-AG-013: ClarificationEngine 异常 → error 事件**
```
输入: clarification.identify 抛异常
验证:
  - SSE 流以 error 事件结束
  - 前面的 draft_update 事件已正常产出
```

### 3.5 置信度计算

**T-AG-014: 置信度各加分项独立验证**
```
目的: 验证 _calculate_confidence 中 draft 字段加分与 knowledge 字段加分完全独立。
      MCP 超时时 LLM mock 的 draft 字段状态决定最终得分。

子用例 T-AG-014a: LLM 产出完整 + MCP 全部超时
  输入:
    draft = {"title":"t","description":"d","domain":"general",
             "entities":[{"name":"e"}],"acceptance_criteria":["ac1"],
             "use_cases":[],"constraints":[],"risks":[],"estimated_cost":null}
    knowledge = {全部为空}
  预期: score = 0.5 + 0.10 + 0.10 + 0.15 = 0.85

子用例 T-AG-014b: LLM 产出完整 + MCP 全部有数据
  输入:
    draft = 同 T-AG-014a
    knowledge = {全4路有数据}
  预期: score = 0.85 + 0.10 + 0.05 + 0.05 + 0.05 = 1.0 (截断)

子用例 T-AG-014c: 截断验证（score 超过 1.0）
  输入:
    draft = {"title":"t","description":"d","domain":"g",
             "entities":[{"name":"e"},{"name":"e2"}],
             "acceptance_criteria":["ac1","ac2"],
             "use_cases":[],"constraints":[],"risks":[],"estimated_cost":null}
    knowledge = {全4路有数据}
    # 理论分: 0.5 + 0.10 + 0.10 + 0.15 + 0.10 + 0.05 + 0.05 + 0.05 = 1.10
  预期: round(min(1.10, 1.0), 2) = 1.0，不抛异常
```

**T-AG-015: 空草案 + 无知识 → 最低置信度**
```
输入:
  draft = {}（空 dict）
  knowledge = {全部为空}

预期:
  confidence_score = 0.5
```

**T-AG-016: 部分草案 → 中间置信度**
```
输入:
  draft = {"description": "xxx", "entities": null, "acceptance_criteria": []}
  knowledge = {"similar_requirements": [1,2,3], ...others空}

预期:
  score = 0.5 + 0.10 (desc) + 0 (entities=null→False) + 0 (ac=[]→False)
        + 0.10 (similar) + 0 + 0 + 0 = 0.70
```

---

## 四、DraftBuilder 流式解析测试（7 条）

### 4.1 JSON 完整性判断

**T-PR-001: 完整 JSON 一次解析成功**
```
输入 buffer:
  '{"title":"测试","description":"这是测试","domain":"general","entities":[],"use_cases":[],"acceptance_criteria":[],"constraints":[],"risks":[],"estimated_cost":null}'

验证:
  _try_parse_json 返回 (dict, len(buffer))
  parsed.title = "测试"
  consumed = 完整 buffer 长度
```

**T-PR-002: 不完整 JSON — 等待更多 chunk**
```
输入 buffer:
  '{"title":"测试","description":"这是测试","entities":['

验证:
  _try_parse_json 返回 (None, 0)
  不抛异常
```

**T-PR-003: 两个连续 JSON — 只消费第一个**
```
输入 buffer:
  '{"title":"v1","domain":"general"}   {"title":"v2","domain":"auth"}'

验证:
  第一次 _try_parse_json → 返回 v1 的 dict + consumed 长度
  第二次 _try_parse_json → 返回 v2 的 dict（如果 buffer 已被消费到第二个 JSON 开始处）
```

**T-PR-004: JSON 前有垃圾字符 — 跳过**
```
输入 buffer:
  '这是一些解释文本\n{"title":"正式草案","domain":"general"}'

验证:
  _try_parse_json 成功解析，consumed 包含前面的垃圾字符长度
  parsed.title = "正式草案"
```

**T-PR-005: 非 dict JSON → 拒绝**
```
输入 buffer:
  '[{"title":"array","domain":"general"}]'

当前行为（已知问题）:
  _try_parse_json 中 start = buffer.find("{") 跳过了开头的 [，
  只取 {"title":"array","domain":"general"} 做 parse + isinstance 校验，
  结果: 意外解析成功，返回 (dict, len(buffer))

目标行为（待修复）:
  _try_parse_json 在 json.loads 成功后，检查完整切片（0 到 i+1）的首个非空白字符
  是否为 {。注意不能简单用 buffer.lstrip()[0] != '{'（会错误拒绝 T-PR-004 的垃圾字符前缀场景）。

推荐修复方案:
  # 在 consumed = i + 1 之后，返回之前:
  # 检查从 0 到 consumed 的切片，除去前导空白和垃圾字符后，
  # 第一个 { 之前如果紧邻 [（数组包装），则拒绝
  prefix = buffer[:start]
  if prefix.rstrip() and prefix.rstrip()[-1] == '[':
      return None, 0

关联代码缺陷: C2 / C8 — _try_parse_json 缺少数组外层包装检测，
且简单的 lstrip 方案会破坏 T-PR-004。
```

**T-PR-006: 流式 chunk 累积 → 多次 yield**
```
模拟 LLM 流:
  chunk1: '{"title":"用'
  chunk2: '户管理","domain":"'
  chunk3: 'user_management"}'
  chunk4: '{"title":"用户管理 v2","domain":"user_management","description":"改进版"}'

验证:
  消费 chunk1+chunk2 后 → 不解析（指针仍在字符串/括号内）
  消费 chunk3 后 → 解析出 v1，yield
  消费 chunk4 后 → 解析出 v2，yield
  总共 yield 2 次
  两个版本的 draft 字段完整
```

**T-PR-007: JSON 值中含转义引号 — 正确识别闭合**
```
目的: 验证 _try_parse_json 的 escape 状态机正确处理字符串内转义引号，
      不会将 \" 误认为字符串结束符。

输入 buffer:
  '{"title":"他说\\"你好\\"","domain":"general"}'

验证:
  - _try_parse_json 返回 (dict, len(buffer))
  - parsed.title = '他说"你好"'
  - in_string 状态在遇到 \" 时不翻转（escape=True 跳过后续字符）

额外验证（非转义引号混合）:
  buffer = '{"title":"test","description":"a\\"b\\"c","domain":"x"}'
  预期: _try_parse_json 正常解析，description = 'a"b"c'
```

---

## 五、API 接口测试（20 条）

### 5.1 `POST /api/requirements`

**T-API-001: 正常创建**
```
请求: POST /api/requirements
      Headers: Authorization: Bearer <valid_jwt>
      Body: {"title": "用户管理系统"}
      JWT claims: {sub: "user001", name: "张三"}

验证:
  HTTP 201
  Response: {"req_id": "<uuid>", "status": "draft", "title": "用户管理系统", "created_at": "ISO8601"}

DB 验证:
  SELECT title, status, creator_user_id, creator_name, requirement_draft
  FROM requirements WHERE id = '<req_id>';
  预期:
    title = '用户管理系统'
    status = 'draft'
    creator_user_id = 'user001'
    creator_name = '张三'
    requirement_draft = {"title": "用户管理系统"}
```

**T-API-002: 无 title — 仍然允许（可选标题）**
```
请求: POST /api/requirements
      Body: {}
验证:
  HTTP 201
  Response: {"req_id": "<uuid>", "status": "draft", "title": null, ...}
  DB: title IS NULL, requirement_draft = {"title": null}
```

**T-API-003: 未认证**
```
请求: 无 Authorization header
验证: HTTP 401
```

**T-API-003a: XSS 注入防护 — title 字段**
```
请求: POST /api/requirements
      Headers: Authorization: Bearer <valid_jwt>
      Body: {"title": "<script>alert('xss')</script>"}

验证:
  HTTP 201
  DB: title 原样存储（不转义，JSONB 天然安全）
  Response 中 title 值不执行脚本（前端负责转义，后端不干预）
```

**T-API-003b: SQL 注入防护 — message 字段**
```
请求: POST /api/dialogue/chat
      Body: {"req_id": "<req_id>", "message": "'; DROP TABLE requirements; --", "session_id": null}

验证:
  HTTP 200（参数化查询防御）
  requirements 表未被删除
  dialogue_messages.content.text = "'; DROP TABLE requirements; --"（原样存储）
```

### 5.2 `POST /api/dialogue/chat`

**T-API-004: 首次对话 — 创建 session + SSE 返回**
```
前置: T-API-001 创建的 req_id, status='draft'

请求: POST /api/dialogue/chat
      Body: {"req_id": "<req_id>", "message": "我想做一个用户管理系统", "session_id": null}

验证:
  HTTP 200
  Content-Type: text/event-stream

  SSE 事件序列:
    event: thinking   → data: {"content": "正在检索知识库..."}
    event: knowledge  → data: {"sources": [...]}
    event: thinking   → data: {"content": "正在分析需求..."}
    event: draft_update → data: {"draft": {...}}
    ...
    event: done       → data: {"draft": {...}, "confidence_score": 0.X, "session_id": "<sid>"}

DB 验证:
  -- session 已创建
  SELECT id, req_id, status, iterations, total_messages
  FROM dialogue_sessions WHERE req_id = '<req_id>';
  预期: 1 行, status='active', iterations>0, total_messages>0

  -- 消息已持久化
  SELECT role, cycle, sequence_number FROM dialogue_messages
  WHERE session_id = '<sid>' ORDER BY sequence_number;
  预期: 第 1 条 role='human', 第 2 条 role='ai'

  -- 快照已创建
  SELECT draft, confidence_score, knowledge_sources, mcp_tools_used
  FROM understanding_snapshots WHERE session_id = '<sid>';
  预期: draft IS NOT NULL, knowledge_sources 含摘要数据
```

**T-API-005: 多轮对话 — 同一 session**
```
前置: T-API-004 的 session_id

请求: POST /api/dialogue/chat
      Body: {"req_id": "<req_id>", "message": "还需要支持角色管理", "session_id": "<sid>"}

验证:
  HTTP 200

  DB 验证:
    -- sequence_number 递增
    SELECT sequence_number, role FROM dialogue_messages
    WHERE session_id = '<sid>' AND cycle = 0 ORDER BY sequence_number;
    预期: 3, 'human' / 4, 'ai'（在已有的 2 条之后）

    -- iterations 递增
    SELECT iterations, total_messages FROM dialogue_sessions WHERE id = '<sid>';
    预期: iterations = 2, total_messages = 4

    -- 快照新增一条
    SELECT count(*) FROM understanding_snapshots WHERE session_id = '<sid>';
    预期: 2
```

**T-API-006: session_id 不匹配 req_id**
```
前置: req_A 创建 session_A, req_B 创建 session_B
请求: POST /api/dialogue/chat
      Body: {"req_id": "<req_B>", "message": "...", "session_id": "<session_A>"}
验证: HTTP 400 / 403 (session 不属于该 req)
```

**T-API-007: req_id 不存在**
```
请求: POST /api/dialogue/chat
      Body: {"req_id": "<nonexistent>", "message": "...", "session_id": null}
验证: HTTP 404
```

**T-API-008: req_id status 不允许对话（如 analyzing_completed 且未打回）**
```
前置: requirements.status = 'analyzing_completed'
请求: POST /api/dialogue/chat
验证: HTTP 400
```

### 5.3 `POST /api/dialogue/confirm`

**T-API-009: 正常确认 — 完整事务**
```
前置: T-API-004/005 的 session (status='active')

请求: POST /api/dialogue/confirm
      Body: {"session_id": "<sid>", "final_notes": "需求已明确"}

验证:
  HTTP 200
  Response: {"ok": true, "req_id": "<req_id>", "session_id": "<sid>",
             "cycle": 0, "status": "analyzing_completed"}

DB 验证:
  -- requirements 更新
  SELECT status, requirement_draft, confidence_score, analyzed_at, revision_count
  FROM requirements WHERE id = '<req_id>';
  预期:
    status = 'analyzing_completed'
    requirement_draft IS NOT NULL
    confidence_score BETWEEN 0 AND 1
    analyzed_at IS NOT NULL
    revision_count = 0 (cycle=0 不递增)

  -- agent_results 写入
  SELECT agent_key, cycle, status, artifact
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A1';
  预期: 1 行, cycle=0, status='completed'
    artifact.requirement_draft IS NOT NULL

  -- session 状态更新
  SELECT status, human_confirmations, first_confirmed_at, last_confirmed_at
  FROM dialogue_sessions WHERE id = '<sid>';
  预期:
    status = 'completed'
    human_confirmations[0].cycle = 0
    human_confirmations[0].confirmed_at IS NOT NULL
    human_confirmations[0].final_notes = '需求已明确'

  -- event_log outbox 写入
  SELECT event_name, direction, outbox_status, payload
  FROM event_log WHERE req_id = '<req_id>' AND event_name = 'agent.result.A1';
  预期: 1 行, direction='OUT', outbox_status='pending'
    payload.req_id = '<req_id>'
    payload.cycle = 0
    payload.draft = 与 requirement_draft 一致的完整草案
```

**T-API-010: 重复确认 — 幂等返回**
```
前置: T-API-009 已确认

请求: POST /api/dialogue/confirm
      Body: {"session_id": "<sid>"}

验证:
  HTTP 200
  Response: {"ok": true, "already_confirmed": true}

  注意: already_confirmed 响应格式目前仅在本文档中定义，
        开发文档 §3.3 仅描述了正常确认的响应体。应与开发文档同步。

DB 验证:
  -- agent_results A1 cycle=0 仍然只有 1 条（未重复插入）
  SELECT count(*) FROM agent_results
  WHERE req_id = '<req_id>' AND agent_key = 'A1' AND cycle = 0;
  预期: 1
```

**T-API-011: session 状态不允许确认**
```
前置: session.status = 'completed'
请求: POST /api/dialogue/confirm
验证: HTTP 400
```

**T-API-012: session 不存在**
```
请求: POST /api/dialogue/confirm
      Body: {"session_id": "<nonexistent>"}
验证: HTTP 404
```

### 5.4 `GET /api/dialogue/history`

**T-API-013: 正常加载历史（单 cycle）**
```
前置: T-API-004 + T-API-005（两轮对话） + T-API-009（确认）

请求: GET /api/dialogue/history/<sid>

验证:
  HTTP 200
  Response:
    session_id = '<sid>'
    req_id = '<req_id>'
    cycles = [
      {
        "cycle": 0,
        "status": "completed",
        "messages": [
          {"role": "human", "content": {"text": "我想做一个用户管理系统"}, ...},
          {"role": "ai", "content": {"text": "...", "draft_preview": {...}}, ...},
          {"role": "human", "content": {"text": "还需要支持角色管理"}, ...},
          {"role": "ai", "content": {"text": "...", "draft_preview": {...}}, ...}
        ],
        "draft_snapshot": {完整的 requirement_draft},
        "confirmed_at": "ISO8601"
      }
    ]
```

**T-API-014: 未认证用户访问他人的 session**
```
前置: session 的 creator_user_id = 'user001'
请求: GET /api/dialogue/history/<sid>   JWT sub = 'user002'
验证: HTTP 403
```

### 5.5 `GET /api/dialogue/current`

**T-API-015: 获取活跃会话**
```
前置: T-API-004（session 未确认）

请求: GET /api/dialogue/current/<req_id>

验证:
  HTTP 200
  Response:
    req_id = '<req_id>'
    session_id = '<sid>'
    status = 'active'
    cycle = 0
    iterations > 0
```

### 5.6 `POST /api/requirements/{req_id}/status`

**T-API-016: Orchestrator 更新打回状态**
```
前置: T-API-001 的 req_id

请求: POST /api/requirements/<req_id>/status
      Headers: X-Api-Key: <valid_internal_key>
      Body: {
        "status": "gate_rejected",
        "gate_rejection_count": 1,
        "last_gate_rejection": {
          "gate_level": 0,
          "reject_reasons": [{"category": "requirement_unclear", "description": "验收标准不具体"}],
          "revision_guidance": "请补充详细的验收条件",
          "rejected_at": "2026-07-10T14:00:00Z",
          "reviewer_name": "李四"
        }
      }

验证:
  HTTP 200
  Response: {"ok": true, "req_id": "<req_id>", "status": "gate_rejected"}

DB 验证:
  SELECT status, gate_rejection_count, last_gate_rejection FROM requirements WHERE id = '<req_id>';
  预期:
    status = 'gate_rejected'
    gate_rejection_count = 1
    last_gate_rejection.reject_reasons[0].category = 'requirement_unclear'
```

**T-API-017: 缺失或无效 API Key → 401/403**
```
请求: POST /api/requirements/<req_id>/status
      Headers: (无 X-Api-Key)
      Body: {"status": "gate_rejected", ...}

验证: HTTP 401

请求: POST /api/requirements/<req_id>/status
      Headers: X-Api-Key: <invalid_key>
      Body: {"status": "gate_rejected", ...}

验证: HTTP 401/403
```

**T-API-018: 请求体含非白名单字段 → 被拒绝或忽略**
```
请求: POST /api/requirements/<req_id>/status
      Headers: X-Api-Key: <valid_internal_key>
      Body: {
        "status": "gate_rejected",
        "gate_rejection_count": 1,
        "last_gate_rejection": {...},
        "requirement_draft": {"title": "恶意覆盖"},    ← 非白名单字段
        "confidence_score": 0.99                       ← 非白名单字段
      }

验证:
  - HTTP 200 或 400（取决于设计决策：拒绝 vs 忽略非白名单字段）
  - DB 验证:
    SELECT status, requirement_draft, confidence_score FROM requirements WHERE id = '<req_id>';
    预期:
      status = 'gate_rejected'
      requirement_draft != {"title": "恶意覆盖"}  ← 未被覆盖
      confidence_score != 0.99                    ← 未被覆盖

安全依据: 开发文档 §3.6 — 仅允许更新白名单字段
```

---

## 六、Outbox 机制测试（4 条）

**T-OT-001: Outbox Publisher 正常发布**
```
前置: 写入一条 event_log (direction='OUT', outbox_status='pending')

步骤:
  1. 启动 Outbox Publisher（轮询 1 秒）
  2. 模拟 NATS server

验证:
  - NATS subject 'agent.result.A1' 收到一条消息
  - 消息 payload 可解析为 JSON，字段齐全
  - event_log.outbox_status 更新为 'published'
  - event_log.published_at IS NOT NULL
```

**T-OT-002: NATS 不可用 → 保持 pending**
```
前置: event_log (outbox_status='pending')
步骤: 关闭 NATS server，启动 Publisher

验证:
  - event_log.outbox_status 保持 'pending'
  - 无异常导致 Publisher 崩溃
```

**T-OT-003: 5 次重试全部失败 → failed**
```
前置: event_log (outbox_status='pending')
模拟: NATS 始终不可用

验证:
  - 5 次重试后 outbox_status = 'failed'
  - Prometheus metric a1_outbox_failed_total 增加
  - 第 6 次轮询跳过该记录
```

**T-OT-004: pending 恢复**
```
前置: event_log (outbox_status='failed')

步骤: 手动 UPDATE event_log SET outbox_status='pending' WHERE id=?
      NATS 恢复正常

验证:
  - 下轮轮询发布成功
  - outbox_status = 'published'
```

---

## 七、Gate0 打回全链路测试（4 条）

**T-GT-001: context.ready.A1 收到 → session REOPENED**
```
前置:
  - requirements: status='analyzing_completed', gate_rejection_count=0
  - dialogue_sessions: status='completed'
  - dialogue_messages: cycle=0, role='human'+'ai'

模拟: NATS 发布 context.ready.A1:
  {
    "req_id": "<req_id>",
    "session_id": "<sid>",
    "cycle": 1,
    "action": "revise",
    "gate_rejection": {
      "gate_level": 0,
      "reject_reasons": [{"category": "requirement_unclear",
                           "description": "需求不清晰"}],
      "revision_guidance": "请补充权限模型说明",
      "rejected_at": "2026-07-10T14:00:00Z"
    }
  }

验证:
  DB:
    -- session 重开
    SELECT status FROM dialogue_sessions WHERE id = '<sid>';
    预期: 'reopened'

    -- 系统消息注入（cycle = 0，打回发生时的旧 cycle）
    SELECT role, content, cycle, sequence_number FROM dialogue_messages
    WHERE session_id = '<sid>' AND role = 'system'
    ORDER BY sequence_number DESC LIMIT 1;
    预期:
      role = 'system'
      content.type = 'gate_rejection'
      content.reject_reasons[0].category = 'requirement_unclear'
      content.revision_guidance = '请补充权限模型说明'
      cycle = 0

    -- event_log 审计
    SELECT event_name, direction FROM event_log
    WHERE session_id = '<sid>' AND event_name = 'context.ready.A1';
    预期: 1 行, direction='IN'
```

**T-GT-002: 修订后确认 → cycle 递增**
```
前置: T-GT-001（session REOPENED, cycle 变为 1）

步骤:
  1. POST /api/dialogue/chat {req_id, message: "增加RBAC权限模型", session_id}
  2. POST /api/dialogue/confirm {session_id}

验证:
  DB:
    -- 新消息 cycle = 1
    SELECT role, cycle, sequence_number FROM dialogue_messages
    WHERE session_id = '<sid>' AND cycle = 1
    ORDER BY sequence_number;
    预期: 至少 2 条 (human + ai)

    -- agent_results 新增 cycle=1 记录
    SELECT agent_key, cycle FROM agent_results
    WHERE req_id = '<req_id>' AND agent_key = 'A1'
    ORDER BY cycle;
    预期: 2 行 (cycle=0, cycle=1)

    -- revision_count 递增
    SELECT revision_count, last_revised_at FROM requirements WHERE id = '<req_id>';
    预期: revision_count = 1, last_revised_at IS NOT NULL

    -- agent.result.A1 payload cycle = 1
    SELECT payload->>'cycle' as cycle FROM event_log
    WHERE req_id = '<req_id>' AND event_name = 'agent.result.A1'
    ORDER BY created_at DESC LIMIT 1;
    预期: '1'
```

**T-GT-003: 修订后会话被重新标记为 completed**
```
前置: T-GT-002（修订确认）

验证:
  SELECT status, human_confirmations
  FROM dialogue_sessions WHERE id = '<sid>';
  预期:
    status = 'completed'
    human_confirmations 数组长度 = 2 (cycle=0 和 cycle=1 各一条)
```

**T-GT-004: 打回后用户不在线 → 下次加载 history 可见**
```
前置: T-GT-001（打回已发生，但 WebSocket 推送失败或不推）

验证:
  GET /api/dialogue/history/<sid>
  Response:
    cycles[0].messages 包含 system 角色消息
      content.type = 'gate_rejection'
      content.reject_reasons = [...]

  GET /api/dialogue/current/<req_id>
  Response:
    status = 'reopened'
```

---

## 八、并发与边界测试（6 条）

**T-CC-001: 两个并发首次对话 → 串行化**
```
前置: req_id, 无 session

步骤: 同时发起两个 POST /api/dialogue/chat
      Body: {"req_id": "<req_id>", "message": "msg1", "session_id": null}
      Body: {"req_id": "<req_id>", "message": "msg2", "session_id": null}

验证:
  - 两个请求都返回 HTTP 200（串行化而非拒绝：第二个阻塞等待锁释放后正常执行）
  - DB 中 requirements 对应的 session 只有 1 条
  - dialogue_messages 按 sequence_number 有序排列且无重复
  - 第二个请求的 message 晚于第一个请求被处理（sequence_number 更大）

设计依据: 开发文档 §8.3 — SELECT ... FOR UPDATE 串行化，第二个请求等待而非失败。
```

**T-CC-002: 并发 confirm → 幂等**
```
步骤: 同时两个 POST /api/dialogue/confirm {session_id}
验证:
  - 都返回 200
  - 至少一个返回 already_confirmed: true
  - agent_results 只有 1 条
```

**T-CC-003: SSE 流中断 → finally 持久化**
```
步骤:
  1. POST /api/dialogue/chat
  2. 收到 2 个 draft_update 事件后主动关闭连接（不等待 done）

验证:
  DB:
    -- AI 回复仍然持久化
    SELECT role, sequence_number, cycle FROM dialogue_messages
    WHERE session_id = '<sid>' ORDER BY sequence_number;
    预期: 2 行
      row 1: role='human', sequence_number=1
      row 2: role='ai', sequence_number=2（连续，无跳跃）

    -- snapshot 存在
    SELECT count(*) FROM understanding_snapshots WHERE session_id = '<sid>';
    预期: 1
```

**T-CC-004: wireframe S3 可用 → URL 存入 artifact**
```
前置:
  - A1 分析过程中产出 wireframe 数据
  - S3 mock 正常

步骤: confirm

验证:
  agent_results.artifact.wireframe_url 格式: "https://s3.../wireframes/<req_id>/0.json"
  understanding_snapshots.wireframe_data IS NOT NULL
```

**T-CC-005: wireframe S3 不可用 → URL 为 null 不阻塞**
```
前置:
  - A1 分析过程中产出 wireframe 数据
  - S3 连接失败

步骤: confirm

验证:
  HTTP 200（确认不因为 S3 失败而报错）
  agent_results.artifact.wireframe_url = null
```

**T-CC-006: 会话 24h 无活动 → abandoned**
```
前置:
  - 手动将 dialogue_sessions.last_updated 设为 25 小时前
  - 会话 status = 'active'

步骤: 执行定时任务

验证:
  SELECT status FROM dialogue_sessions WHERE id = '<sid>';
  预期: 'abandoned'

注意: 定时任务本身不在 A1 范围内（Temporal Schedule / cron），但验证的是 MC Backend API 是否正确处理此状态标记。
```

---

## 九、端到端测试（2 条）

### 9.1 正常全流程

**T-E2E-001: 创建 → 对话 → 确认 → 数据完整链**

```
Step 1: POST /api/requirements {"title": "用户管理系统"}
  → 获得 req_id_A, status='draft'

  验证点:
    ✓ requirements 行存在，creator 字段来自 JWT
    ✓ requirement_draft = {"title": "用户管理系统"}

Step 2: POST /api/dialogue/chat
        {"req_id": req_id_A, "message": "做一个完整的用户管理，支持增删改查和角色权限", "session_id": null}
  → SSE 流式返回

  验证点:
    ✓ session 创建，dialogue_sessions 关联 req_id_A
    ✓ cycle = 0
    ✓ 事件序列: thinking → knowledge → draft_update(N次) → [clarification] → done
    ✓ done 事件含 session_id
    ✓ done.draft.title ≈ "用户管理系统"
    ✓ done.draft.domain = "user_management"
    ✓ done.draft.entities 至少 1 条
    ✓ done.confidence_score > 0
    ✓ dialogue_messages 已持久化 (human + ai)
    ✓ understanding_snapshots 1 条

Step 3: POST /api/dialogue/chat
        {"req_id": req_id_A, "message": "还需要支持批量导入和导出功能", "session_id": <sid>}
  → SSE 流式返回

  验证点:
    ✓ sequence_number 递增
    ✓ iterations 递增
    ✓ 草案增加了 use_cases 或 acceptance_criteria

Step 4: POST /api/dialogue/confirm {"session_id": <sid>, "final_notes": "需求已确认"}

  验证点:
    ✓ requirements.status = 'analyzing_completed'
    ✓ requirements.requirement_draft 包含完整草案
    ✓ requirements.confidence_score > 0
    ✓ requirements.analyzed_at 不为空
    ✓ agent_results A1 cycle=0 存在
    ✓ agent_results.artifact.requirement_draft 与 requirements.requirement_draft 一致
    ✓ dialogue_sessions.status = 'completed'
    ✓ dialogue_sessions.human_confirmations[0] = {confirmed_at, cycle:0, final_notes}
    ✓ event_log agent.result.A1 存在, direction='OUT', outbox_status='published'
    ✓ NATS agent.result.A1 消息已发布

  草案一致性独立验证:
    -- 三方草案必须一致
    SELECT
      r.requirement_draft as req_draft,
      ar.artifact->>'requirement_draft' as ar_draft,
      us.draft as snapshot_draft
    FROM requirements r
    JOIN agent_results ar ON ar.req_id = r.id AND ar.agent_key = 'A1' AND ar.cycle = 0
    JOIN understanding_snapshots us ON us.session_id = '<sid>'
    ORDER BY us.created_at DESC LIMIT 1;

    预期: req_draft = ar_draft = snapshot_draft（JSON 字段全等）

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                    │ 预期行数 │ 关键字段验证      │
  ├─────────────────────────────────────────────────────┤
  │ requirements          │ 1       │ status='analyzing_completed' │
  │ agent_results         │ 1       │ A1, cycle=0  │
  │ dialogue_sessions     │ 1       │ status='completed' │
  │ dialogue_messages     │ 4       │ human,ai,human,ai │
  │ understanding_snapshots│ 2      │ iteration=1,2  │
  │ event_log             │ 1       │ OUT, published   │
  └─────────────────────────────────────────────────────┘
```

### 9.2 打回修订全流程

**T-E2E-002: 创建 → 对话 → 确认 → 打回 → 修订 → 重新确认**

```
Step 1-4: 同 T-E2E-001（完成首次确认）

Step 5: 模拟 Gate0 打回
  5a. Orchestrator 写入 event_log (IN)
  5b. Orchestrator 调 POST /api/requirements/<req_id>/status
      {"status": "gate_rejected", "gate_rejection_count": 1, "last_gate_rejection": {...}}
  5c. Orchestrator 发布 NATS context.ready.A1 {req_id, session_id, cycle:1, action:"revise", gate_rejection:{...}}

  验证点:
    ✓ requirements.status = 'gate_rejected'
    ✓ requirements.gate_rejection_count = 1
    ✓ dialogue_sessions.status = 'reopened'
    ✓ dialogue_messages 新增 1 条 system 消息 (cycle=0, content.type='gate_rejection')
    ✓ event_log IN 记录 context.ready.A1

Step 6: 用户看到打回通知，进入对话页
  GET /api/dialogue/current/<req_id>
  → status='reopened'

  GET /api/dialogue/history/<sid>
  → cycles[0].messages 含系统打回消息（红色）

Step 7: 用户修订
  POST /api/dialogue/chat
  {"req_id": req_id_A, "message": "好的，我补充：使用RBAC模型，管理员拥有全部权限...", "session_id": <sid>}

  验证点:
    ✓ 新消息 cycle = 1
    ✓ sequence_number 从 0 重新开始（每个 cycle 独立计数）
    ✓ 草案在前一 cycle 基础上修订

Step 8: POST /api/dialogue/confirm {"session_id": <sid>}

  验证点:
    ✓ requirements.revision_count = 1
    ✓ requirements.last_revised_at 不为空
    ✓ agent_results 新增 A1 cycle=1 记录
    ✓ agent_results 中 cycle=0 和 cycle=1 的 artifact.requirement_draft 不同（修订有变更）
    ✓ event_log 新增 agent.result.A1 cycle=1

完整数据链验证:
  ┌─────────────────────────────────────────────────────┐
  │ 表                    │ 预期行数 │ 关键字段验证      │
  ├─────────────────────────────────────────────────────┤
  │ requirements          │ 1       │ status='analyzing_completed' │
  │                       │         │ gate_rejection_count=1  │
  │                       │         │ revision_count=1  │
  │ agent_results         │ 2       │ A1, cycle=0 + cycle=1  │
  │ dialogue_sessions     │ 1       │ status='completed' (两次confirm) │
  │                       │         │ human_confirmations 长度 2  │
  │ dialogue_messages     │ 7       │ role 序列:                │
  │                       │         │   cycle=0 (5条): human,ai,human,ai,system │
  │                       │         │   cycle=1 (2条): human,ai │
  │ understanding_snapshots│ 3      │ cycle=0: 2条, cycle=1: 1条  │
  │ event_log             │ 4       │ A1 可观测范围明细:          │
  │                       │         │   agent.result.A1 OUT (cycle=0) │
  │                       │         │     <- confirm 时 MC Backend 写入 │
  │                       │         │   context.ready.A1 IN (cycle=1)  │
  │                       │         │     <- MC Backend 订阅写入       │
  │                       │         │     (cycle = payload.cycle = 1)  │
  │                       │         │   agent.result.A1 OUT (cycle=1) │
  │                       │         │     <- 修订 confirm 时 MC Backend 写入 │
  │                       │         │   agent.result.gate0.reject IN   │
  │                       │         │     (cycle=0, Orchestrator写入)  │
  │                       │         │ 注: 第 4 条为 Orchestrator 写入，│
  │                       │         │     A1 仅通过 payload 间接感知    │
  └─────────────────────────────────────────────────────┘
```

---

## 十、测试环境与 Mock 策略

### 10.1 依赖隔离

| 组件 | 测试策略 |
|------|---------|
| **PostgreSQL** | 真实 DB（test 库），每个测试函数用独立 schema 或事务回滚 |
| **NATS** | 集成测试用嵌入式 NATS（`nats-server -js`），单元测试 mock |
| **LLM (DeepSeek)** | 全部 mock：`DraftBuilder._stream_llm` 返回预定义的 chunk 序列，`ClarificationEngine`/`BDDDrafter`/`WireframeGenerator` 返回预定义数据 |
| **MCP Gateway** | 全部 mock：`MCPClient` 方法返回预定义数据或抛异常 |
| **S3** | mock：`s3_proxy.upload_json` 返回预定义 URL 或抛异常 |
| **Redis** | 集成测试用真实 Redis（Docker）
| **JWT** | 测试用固定密钥签发 token |

### 10.2 数据夹具（Fixtures）

```python
# 标准 LLM 输出 chunk 序列（模拟一次完整分析，单 chunk 版本）
MOCK_LLM_CHUNKS_V1 = [
    # 注意：跨 chunk 边界拼接后必须仍为合法 JSON。以下 chunk 分界处不会破坏 JSON 结构。
    '{"title":"用户管理系统","description":"企业用户管理平台，支持增删改查和角色权限控制",'
    '"domain":"user_management","entities":[{"name":"用户","attributes":["用户名","邮箱","角色","状态"],"description":"核心用户实体"}],"use_cases":["管理员创建用户","用户自助注册"],"acceptance_criteria":["Given 管理员已登录 When 填写用户信息并提交 Then 用户创建成功"],"constraints":["单租户部署"],"risks":["并发权限修改"],"estimated_cost":"2人月"}',
]

# 多 chunk 版本（模拟真实流式输出，用于 T-PR-006 和流式中断测试）
MOCK_LLM_CHUNKS_MULTI = [
    '{"title":"用户管理系统","description":"企业用户管理平台",',
    '"domain":"user_management","entities":[{"name":"用户","attributes":["用户名","邮箱"]}],',
    '"use_cases":["创建用户","编辑用户"],"acceptance_criteria":[],"constraints":[],"risks":[],"estimated_cost":null}',
]

# 标准 MCP 返回数据
MOCK_KNOWLEDGE_FULL = {
    "similar_requirements": [
        {"id": "r1", "title": "企业用户中心", "similarity": 0.92, "metadata": {"tags": ["auth","rbac"]}},
        {"id": "r2", "title": "权限管理系统", "similarity": 0.85, "metadata": {"tags": ["security"]}},
        {"id": "r3", "title": "账户管理后台", "similarity": 0.78, "metadata": {"tags": ["admin"]}},
    ],
    "domain_risks": [
        {"risk": "权限提升攻击", "description": "角色分配需校验操作者权限", "severity": "high"},
        {"risk": "密码策略不符合安全规范", "description": "需强制复杂度要求", "severity": "medium"},
    ],
    "tech_stack": {"backend": "Python/FastAPI", "frontend": "React+TypeScript", "database": "PostgreSQL"},
    "cost_baseline": {"estimated_effort_months": 2.5, "team_size": 2, "breakdown": {"backend": 1.5, "frontend": 1.0}},
}

# 标准 Gate0 打回 payload
MOCK_GATE_REJECTION = {
    "gate_level": 0,
    "reject_reasons": [
        {"category": "requirement_unclear", "description": "用户角色的权限边界需进一步明确"}
    ],
    "revision_guidance": "建议补充用户角色权限矩阵，明确管理员和普通用户的操作边界",
    "rejected_at": "2026-07-10T14:00:00Z",
}
```

---

## 十一、测试执行清单

### 按 Phase 分配

| Phase | 测试编号 | 测试数 | 关键依赖 |
|-------|---------|:-----:|---------|
| **Phase 1** (DB+API) | T-DB-001 → T-DB-016, T-API-001 → T-API-020, T-OT-001 → T-OT-004 | 40 | PostgreSQL 就绪 |
| **Phase 2** (Agent+解析) | T-AG-001 → T-AG-016, T-PR-001 → T-PR-007 | 23 | LLM mock 就绪 |
| **Phase 3** (Orchestrator+Gate0+边界) | T-GT-001 → T-GT-004, T-CC-001 → T-CC-006 | 10 | NATS+Temporal 就绪 |
| **Phase 4** (E2E) | T-E2E-001 → T-E2E-002 | 2 | 全链路环境就绪 |
| **Phase 5** (真实环境集成) | T-RL-001 → T-RL-012 | 12 | LLM/NATS/MCP/S3 真实服务 |

### 测试通过标准

- **Phase 1**: 40/40 通过 → DB schema 正确，API 契约完整，安全约束生效，Outbox 可靠
- **Phase 2**: 23/23 通过 → Agent 事件流正确，类型安全，SSE 解析可靠（含转义引号边界）
- **Phase 3**: 10/10 通过 → 并发安全，打回链路正确，边界覆盖
- **Phase 4**: 2/2 通过 → 全链路数据一致，打回修订闭环正确
- **Phase 5**: 12/12 通过 → 真实 LLM/MCP/NATS/S3 环境下行为正确

---

## 十二、真实环境集成测试（12 条）

> 以下用例依赖**真实外部服务**（LLM API、NATS Server、MCP Gateway、S3），与 Phase 1-4 的 mock 测试互补。标记为 `@pytest.mark.integration`，在 CI 中独立 stage 运行，不阻塞日常开发循环。

### 12.1 测试环境要求

| 组件 | 要求 |
|------|------|
| **LLM (DeepSeek)** | 真实 API endpoint，测试用 API key，限流策略: 最多 20 req/min |
| **NATS** | 嵌入式 `nats-server -js`（JetStream 模式），测试用独立 stream |
| **MCP Gateway** | 真实 MCP 服务或 staging 环境，knowledge-base 需有预置种子数据 |
| **S3** | MinIO 本地实例（`docker run minio/minio`），测试用 bucket |
| **PostgreSQL** | 同 Phase 1，真实 DB（test 库） |

### 12.2 LLM 真实调用（4 条）

**T-RL-001: 单条消息完整 JSON 输出校验**
```
输入:
  user_message = "做一个简单的博客系统，支持发布文章和评论"
  history = []
  current_draft = None
  cycle = 0
  MCP: mock（减少外部依赖，仅验证 LLM 输出）

验证:
  - SSE 流以 done 事件结束（无 error）
  - done.draft 的 JSON 可解析为合法 dict
  - done.draft.title 不为空
  - done.draft.description 不为空
  - done.draft.domain 在 10 个枚举值之一
  - done.draft.entities 至少有 1 条
  - done.draft.use_cases 至少有 1 条
  - done.confidence_score > 0

注意: 不验证具体内容（LLM 非确定性），只验证结构和非空约束。
标记: @pytest.mark.integration @pytest.mark.llm
```

**T-RL-002: 多轮对话 context 传递正确性**
```
输入:
  第 1 轮: user_message = "做一个博客系统", current_draft = None
  第 2 轮: user_message = "还需要支持文章标签和分类功能", current_draft = 第 1 轮 done.draft

验证:
  - 第 2 轮 done.draft.entities 包含第 1 轮已有的实体 AND 新增实体
  - 第 2 轮 done.draft.use_cases 数量 >= 第 1 轮数量
  - 第 2 轮 done.draft 中 title 与第 1 轮一致（未丢失）
  - 第 2 轮未产生 error 事件

标记: @pytest.mark.integration @pytest.mark.llm
```

**T-RL-003: 极短/模糊输入 → 合理推断而非空输出**
```
输入:
  user_message = "做个APP"
  history = []
  current_draft = None

验证:
  - done 事件正常产出（无 error）
  - done.draft.title 不为空（LLM 做了合理推断）
  - done.draft.description 不为空
  - done.draft.domain 不为 null
  - clarification 事件可能包含待澄清问题（非强制）
  - confidence_score < 0.7（输入信息不足，置信度应偏低）

标记: @pytest.mark.integration @pytest.mark.llm @pytest.mark.edge_case
```

**T-RL-004: System Prompt {{→{ 转义有效性**
```
目的: 验证 DraftBuilder._build_system_prompt() 中 Python 源码
      {{ 和 }} 经过 str.replace() 后，最终发给 LLM 的文本中花括号正确折叠。

此用例为纯单元测试（不依赖外部服务），因与 LLM 输出质量强相关，
归入本章节以便统一查阅。执行时归入 Phase 2（Agent 单元测试）。

验证方式:
  在测试中直接调用 _build_system_prompt() 获取最终 prompt 文本，
  不实际调用 LLM API（仅验证模板渲染结果）。

验证:
  - prompt 文本中不含 "{{" 或 "}}"（已全部折叠）
  - JSON 示例中的 "title"、"description"、"entities" 等字段的花括号为单层 { }
  - __KNOWLEDGE_CONTEXT__ 占位符已被替换
  - __CURRENT_DRAFT__ 占位符已被替换
  - __HISTORY__ 占位符已被替换
  - __USER_MESSAGE__ 占位符已被替换

标记: @pytest.mark.unit（不需要外部服务）
```

### 12.3 MCP 真实调用（3 条）

**T-RL-005: 4 路并行调用的真实延迟与超时边界**
```
输入:
  使用真实 MCP Gateway（staging 环境，含预置种子数据）
  current_draft = {"title": "用户管理系统", "domain": "user_management"}

验证:
  - 4 路调用全部在 5 秒超时内返回（计时验证）
  - search_similar_requirements 返回 list[dict]，每个含 id/title/similarity
  - get_domain_risks 返回 list[dict]，每个含 risk/description/severity
  - get_tech_stack_recommendations 返回 dict
  - get_cost_baseline 返回 dict 或 null
  - knowledge.sources 摘要与原始数据一致（count 匹配）

标记: @pytest.mark.integration @pytest.mark.mcp @pytest.mark.slow
```

**T-RL-006: 单路 MCP 超时/失败 → 其他路不受影响**
```
模拟:
  通过环境变量或网络规则使 get_cost_baseline 的 MCP endpoint 不可达（超时）
  其余 3 路正常

验证:
  - 整体 _fetch_knowledge 在 ~5s 完成（不等待超时路的 5s+ 重试）
  - knowledge.sources 中 cost_baseline 不存在
  - knowledge.sources 中其他 3 个存在
  - 无未捕获异常
  - SSE 流正常产出 thinking → knowledge → draft_update → done

标记: @pytest.mark.integration @pytest.mark.mcp
```

**T-RL-007: MCP 返回空结果 → 摘要为空**
```
前置: 用冷门 domain 值（如 "quantum_computing_scheduling"）查询 MCP，
      确保种子数据不覆盖此领域

验证:
  - knowledge.sources = []（全部空）
  - done.draft 仍然基于 LLM 自身知识产出（不依赖 MCP）
  - confidence_score 中 knowledge 加分项全部为 0

标记: @pytest.mark.integration @pytest.mark.mcp @pytest.mark.edge_case
```

### 12.4 NATS 真实集成（3 条）

**T-RL-008: Outbox → NATS JetStream 端到端发布与消费**
```
前置:
  - 启动嵌入式 nats-server -js
  - 创建 AI_NATIVE_EVENTS stream，subject: agent.result.A1
  - Outbox Publisher 配置指向 localhost NATS

步骤:
  1. 写入一条 event_log (OUT, outbox_status='pending',
     event_name='agent.result.A1', payload=<标准 payload>)
  2. 启动 Outbox Publisher（轮询间隔 1s 用于测试）
  3. NATS consumer 订阅 agent.result.A1

验证:
  - consumer 在 ≤ 3 秒内收到消息
  - 消息 payload 可解析为 JSON，字段与写入的 payload 一致
  - event_log.outbox_status 更新为 'published'
  - event_log.published_at IS NOT NULL

标记: @pytest.mark.integration @pytest.mark.nats
```

**T-RL-009: NATS 断连 → Outbox 重试 → 恢复后发布成功**
```
步骤:
  1. 写入 event_log (OUT, pending)
  2. 启动 Outbox Publisher
  3. 关闭 NATS server
  4. 等待 Outbox Publisher 尝试发布并失败（确认 outbox_status 仍为 'pending'）
  5. 重新启动 NATS server
  6. 等待下一次轮询

验证:
  - NATS 不可用期间 outbox_status 保持 'pending'
  - NATS 恢复后 outbox_status → 'published'（无需人工介入）
  - 无重复发布（JetStream 去重）
  - 发布延迟 ≤ 轮询间隔 + 重连时间

标记: @pytest.mark.integration @pytest.mark.nats @pytest.mark.resilience
```

**T-RL-010: context.ready.A1 订阅 → session REOPENED 全链路**
```
前置:
  - requirements: status='analyzing_completed', gate_rejection_count=0
  - dialogue_sessions: status='completed'
  - MC Backend NATS 订阅已启动

步骤:
  1. 发布 NATS context.ready.A1（标准 Gate0 打回 payload）
  2. 等待 MC Backend 处理（轮询 DB 验证或使用回调）

验证:
  DB:
    ✓ dialogue_sessions.status = 'reopened'
    ✓ dialogue_messages 新增 1 条 role='system' 消息
    ✓ system 消息 content.type = 'gate_rejection'
    ✓ system 消息 cycle = 0（打回发生时的旧 cycle）
    ✓ event_log 新增 direction='IN', event_name='context.ready.A1'
  API:
    ✓ GET /api/dialogue/current/{req_id} → status='reopened'
    ✓ GET /api/dialogue/history/{sid} → cycles[0].messages 包含 system 消息

标记: @pytest.mark.integration @pytest.mark.nats
```

### 12.5 S3 真实集成（2 条）

**T-RL-011: 线框图上传 S3 → URL 可访问**
```
前置:
  - MinIO 实例运行中，bucket "wireframes" 已创建
  - understanding_snapshots 中有 wireframe_data

步骤:
  1. 写入 understanding_snapshots (wireframe_data = <测试线框图 JSON>)
  2. 调用 POST /api/dialogue/confirm

验证:
  - HTTP 200
  - agent_results.artifact.wireframe_url 格式: http://localhost:9000/wireframes/{req_id}/0.json
  - HTTP GET wireframe_url → 200，返回与上传时一致的 JSON
  - S3 object 的 Content-Type = application/json

标记: @pytest.mark.integration @pytest.mark.s3
```

**T-RL-012: S3 不可用 → wireframe_url = null 不阻塞 confirm**
```
前置:
  - MinIO 未启动或网络不可达
  - understanding_snapshots 中有 wireframe_data

步骤:
  1. 调用 POST /api/dialogue/confirm

验证:
  - HTTP 200（确认成功，wireframe 降级）
  - agent_results.artifact.wireframe_url = null
  - requirements.status = 'analyzing_completed'（不受影响）
  - event_log 正常写入（agent.result.A1 OUT）
  - 日志中出现 S3 上传失败的 warning 记录

标记: @pytest.mark.integration @pytest.mark.s3 @pytest.mark.resilience
```

### 12.6 真实环境测试执行说明

```python
# conftest.py 或 pytest.ini 中的标记注册
# [pytest]
# markers =
#     integration: 真实外部服务集成测试
#     llm: 需要真实 LLM API
#     mcp: 需要真实 MCP Gateway
#     nats: 需要真实 NATS Server
#     s3: 需要真实 S3/MinIO
#     slow: 执行较慢的测试
#     resilience: 故障恢复测试
#     edge_case: 边界输入测试

# CI 中运行方式:
#   pytest -m "not integration"          # 日常开发循环（仅 mock 测试）
#   pytest -m "integration"              # 每日夜间构建（真实服务）
#   pytest -m "integration and not slow" # 快速集成检查
```

---
**文档维护**: AI-Native团队
**最后更新**: 2026-07-10
**版本**: v1.1
**总测试数**: 87 条（数据库 16 + Agent 单元 16 + 流式解析 7 + API 20 + Outbox 4 + 打回 4 + 并发边界 6 + E2E 2 + 真实环境集成 12 条）
