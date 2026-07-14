# A2 知识分析 Agent — 完整测试设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **参考**: [A2 开发设计文档 v1.0](./A2-知识分析Agent-开发设计文档.md) · [A2-MCP服务改造设计 v1.2](./A2-MCP服务改造设计.md) · [阶段一数据字典 v1.3](../Agent规格/阶段一-数据字典.md)
- **测试范围**: A2 全功能验证（三层降级 → 可行性评估 → 冲突检测 → 确认清单 → 持久化 → NATS 发布）
- **原则**: 每个用例包含明确的**输入数据、预期输出、验证 SQL/断言**，做到数据可视

---

## 一、测试分层策略

```
            ┌──────────────┐
            │  E2E 端到端   │  2 条：正常流程 + A2 超时降级全链路
            ├──────────────┤
            │  真实环境集成  │  9 条：MCP Gateway + NATS + LLM + Neo4j 真实服务
            ├──────────────┤
            │  集成测试     │  10 条：API + DB + Agent + MCP Gateway 联合验证
            ├──────────────┤
            │  单元测试     │  24 条：Agent、mappers、降级链、质量评分
            ├──────────────┤
            │  数据库测试   │  6 条：agent_results DML、UPSERT、查询
            └──────────────┘
```

---

## 二、数据库层测试（6 条）

### 2.1 agent_results 写入与查询

**T-A2-DB-001: agent_results 正常插入**
```
输入:
  req_id = (已存在的 requirements.id)
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A2', 0, 'completed', '{"quality_score": 0.72}'::jsonb)

验证 SQL:
  SELECT req_id, agent_key, cycle, status, artifact
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A2' AND cycle = 0;

预期结果:
  agent_key = 'A2'
  cycle = 0
  status = 'completed'
  artifact->>'quality_score' = '0.72'
```

**T-A2-DB-002: UPSERT — 同 (req_id, agent_key, cycle) 第二次写入更新**
```
步骤 1:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A2', 0, 'completed', '{}'::jsonb);
  → 成功

步骤 2:
  使用 UPSERT (ON CONFLICT DO UPDATE):
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A2', 0, 'empty', '{"quality_score": 0.05}'::jsonb)
  ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
  SET status = EXCLUDED.status, artifact = EXCLUDED.artifact;

验证 SQL:
  SELECT status, artifact->>'quality_score' as qs
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A2' AND cycle = 0;

预期结果:
  status = 'empty'
  qs = '0.05'
  且 count(*) = 1（未新增行）
```

**T-A2-DB-003: UNIQUE 约束 — 同键重复 INSERT 报错**
```
步骤 1:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A2', 1, 'completed', '{}'::jsonb);
  → 成功

步骤 2:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A2', 1, 'completed', '{}'::jsonb);
  → 预期: ERROR 23505 (duplicate key violates unique constraint)
```

**T-A2-DB-004: 不同 cycle 的记录独立存储**
```
输入:
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A2', 0, 'completed', '{"cycle": 0}'::jsonb);
  INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
  VALUES ('<req_id>', 'A2', 1, 'completed', '{"cycle": 1}'::jsonb);

验证 SQL:
  SELECT cycle, artifact->>'cycle' as ac FROM agent_results
  WHERE req_id = '<req_id>' AND agent_key = 'A2' ORDER BY cycle;

预期结果: 2 行, cycle=0 和 cycle=1
```

**T-A2-DB-005: agent_results 与 A1 共存不冲突**
```
前置: 已为同一 req_id 分别插入 A1 cycle=0 和 A2 cycle=0

验证 SQL:
  SELECT agent_key, cycle FROM agent_results
  WHERE req_id = '<req_id>' ORDER BY agent_key, cycle;

预期结果: 2 行
  A1, 0
  A2, 0
  (UNIQUE 约束仅区分 agent_key + cycle，不同 agent_key 不冲突)
```

**T-A2-DB-006: artifact JSONB 完整结构存储与查询**
```
输入:
  插入包含完整 feasibility_assessment + conflicts + checklist + quality_score 的 artifact

验证 SQL:
  SELECT
    artifact->'feasibility_assessment'->'technical'->>'feasible' as tech_feasible,
    artifact->'feasibility_assessment'->'business'->>'feasible' as biz_feasible,
    artifact->'feasibility_assessment'->>'risk_level' as risk_level,
    jsonb_array_length(artifact->'conflicts') as conflict_count,
    jsonb_array_length(artifact->'confirmation_checklist') as checklist_count,
    artifact->>'quality_score' as qs
  FROM agent_results WHERE req_id = '<req_id>' AND agent_key = 'A2';

预期结果:
  tech_feasible = 'true' / 'false'
  biz_feasible = 'true' / 'false'
  risk_level IN ('low', 'medium', 'high')
  conflict_count >= 0
  checklist_count >= 3 (模板或 LLM 生成)
  qs 可解析为 float
```

---

## 三、A2 Agent 单元测试（15 条）

### 3.1 三层降级链

**T-A2-AG-001: 全 MCP 正常 → level=mcp × 3**
```
输入:
  MCP mock: 全部 3 路返回有效数据
  RAG mock: 不调用（L1 已成功）

验证:
  sim_level = "mcp"
  issues_level = "mcp"
  risks_level = "mcp"
  quality_score >= 0.6 (基础分 0.6)
```

**T-A2-AG-002: MCP 全部超时 → L2 REST 接管**
```
输入:
  MCPClient 全部抛出 TimeoutException
  RAGRetriever mock: 返回有效数据

验证:
  全部 3 路 level = "direct"
  RAGRetriever.search_similar_requirements 被调用
  RAGRetriever.search_general 被调用 2 次 (issues + risks)
  quality_score >= 0.3 (基础分 0.3)
```

**T-A2-AG-003: MCP + REST 全部失败 → L3 fallback**
```
输入:
  MCPClient 全部抛出 TimeoutException
  RAGRetriever 全部抛出 ConnectionError

验证:
  全部 3 路 level = "fallback"
  RAGRetriever._fallback_search 被调用 3 次
  quality_score >= 0.15 (基础分 0.15)
```

**T-A2-AG-004: 全部三层无数据 → status='empty'**
```
输入:
  MCP 返回空列表
  RAGRetriever 返回空列表
  _fallback_search 返回空列表

验证:
  status = "empty"
  quality_score = 0.05 (基础分 0.05)
  execute() 仍正常返回（不抛异常）
```

**T-A2-AG-005: 单路降级 — 其余正常**
```
输入:
  similar_requirements: MCP 成功 (level=mcp)
  known_issues: MCP 超时，REST 成功 (level=direct)
  domain_risks: MCP 超时，REST 超时，fallback 有数据 (level=fallback)

验证:
  retrieval_levels = ["mcp", "direct", "fallback"]
  quality_score 基础分 = 0.4 (mcp_count=1)
  已知问题数据和领域风险数据来自不同降级层
```

**T-A2-AG-006: known_issues L1/L2/L3 全部空 → 不影响其他路**
```
输入:
  similar_requirements: L1 MCP 返回 5 条
  known_issues: L1→L2→L3 全部返回空列表
  domain_risks: L1 MCP 返回 2 条

验证:
  issues_level = "empty"
  sim_level = "mcp"
  risks_level = "mcp"
  _determine_status(["mcp", "empty", "mcp"]) = "completed"
```

### 3.2 质量评分

**T-A2-AG-007: 全 MCP + 丰富内容 → 高质量评分**
```
输入:
  retrieval_levels = ["mcp", "mcp", "mcp"]
  knowledge_package = {
    "similar_requirements": [3条],
    "suggested_approach": "详细的LLM分析总结",
    "risks": [5条]
  }

预期计算:
  base = 0.6
  content = min(3*0.08, 0.25) + 0.10 + min(5*0.03, 0.10)
          = 0.24 + 0.10 + 0.10 = 0.44
  score = min(0.6 + 0.44, 1.0) = 1.0

验证: quality_score = 1.0 (截断验证)
```

**T-A2-AG-008: 全部 empty → 最低质量评分**
```
输入:
  retrieval_levels = ["empty", "empty", "empty"]
  knowledge_package = {"similar_requirements": [], "suggested_approach": "", "risks": []}

预期: quality_score = 0.05
```

**T-A2-AG-009: 截断验证 — 分数不超过 1.0**
```
输入:
  retrieval_levels = ["mcp", "mcp", "mcp"]
  knowledge_package = {"similar_requirements": [10条填满], "suggested_approach": "...", "risks": [10条]}

预期: quality_score = 1.0 (不抛异常)
```

**T-A2-AG-010: 混合降级质量评分验证**
```
子用例 A: mcp=2, direct=1
  基础分 = 0.4 (mcp_count=2 ≥ 1, 非全 3)
  ← 注意: 设计文档公式中 mcp_count == 3 是严格全通检查——
    只有三个工具都走 MCP 才给 0.6；部分 MCP 成功(≥1)统一给 0.4，
    不按比例插值。设计意图：要么全 MCP 可信(0.6)，要么MCP层有降级(0.4)。

子用例 B: direct=3
  基础分 = 0.3

子用例 C: direct=2, fallback=1
  基础分 = 0.3 (direct_count >= 1)

子用例 D: fallback=1, empty=2
  基础分 = 0.15
```

### 3.3 状态判定

**T-A2-AG-011: _determine_status 三态验证**
```
子用例: ["mcp", "mcp", "mcp"] → "completed"
子用例: ["direct", "empty", "fallback"] → "completed" (至少一个非 empty)
子用例: ["empty", "empty", "empty"] → "empty"
```

### 3.4 FeasibilityAssessor 异常降级

**T-A2-AG-012: assessor.assess() 抛异常 → 使用默认值**
```
输入:
  FeasibilityAssessor mock: raise RuntimeError("unexpected error")
  domain_risks = [{"risk_name": "SQL注入", "description": "历史遗留SQL拼接问题"}]

验证:
  feasibility.technical.feasible = True
  feasibility.technical.concerns = []
  feasibility.business.feasible = True (LLM/启发式仍正常运行)
  feasibility.risk_level = "low"
  不抛异常
  日志中出现 "FeasibilityAssessor failed" warning
```

### 3.5 ConflictDetector 异常降级

**T-A2-AG-013: detector.detect() 抛异常 → 返回空列表**
```
输入:
  ConflictDetector mock: raise RuntimeError("unexpected error")
  similar_reqs 有 3 条含 entities

验证:
  conflicts = []
  不抛异常
  日志中出现 "ConflictDetector failed" warning
```

### 3.6 产物完整性

**T-A2-AG-014: execute() 返回结构含所有必需字段**
```
验证 done 返回 dict 的 keys:
  ✓ "req_id"
  ✓ "session_id"
  ✓ "cycle"
  ✓ "status"
  ✓ "feasibility_assessment"  (含 technical + business, 均为 {feasible, assessment, concerns})
  ✓ "confirmation_checklist"  (list[dict], 每个含 id, category, item, priority)
  ✓ "conflicts"               (list[dict], 每个含 id, related_system, type, description, severity)
  ✓ "quality_score"            (float, 0-1)
  ✓ "timestamp"                (ISO 8601)
```

**T-A2-AG-015: session_id 和 cycle 从 context_package 正确提取**
```
输入:
  context_package = {"session_id": "abc-123", "cycle": 2, "requirement_draft": {...}}

验证:
  execute() 返回的 session_id = "abc-123"
  execute() 返回的 cycle = 2
  _persist_agent_result 收到的 session_id = "abc-123", cycle = 2
```

---

## 四、mappers.py 单元测试（9 条）

### 4.1 可行性评估映射

**T-A2-MP-001: 正常映射 — 1D → 2D**
```
输入:
  FeasibilityAssessor 返回:
    {"feasible": true, "risk_level": "medium",
     "concerns": ["并发权限修改风险", "密码策略需加强"],
     "confidence": 0.6}

  domain_risks = [
    {"risk_name": "权限提升", "description": "角色分配需校验操作者权限", "severity": "high"}
  ]

  LLM mock: 返回 {"feasible": true, "assessment": "业务方向可行，与现有产品矩阵互补",
                   "concerns": ["需确认多租户定价策略"]}

验证:
  feasibility.technical.feasible = True
  feasibility.technical.assessment 包含 "并发权限修改风险" 和 "密码策略需加强"
  feasibility.technical.concerns 长度 = 2
  feasibility.business.feasible = True
  feasibility.business.assessment = "业务方向可行，与现有产品矩阵互补"
  feasibility.business.concerns 包含 "需确认多租户定价策略"
  feasibility.risk_level = "medium"
  feasibility.risk_rationale 包含 "并发权限修改风险" 和 "权限提升"
```

**T-A2-MP-002: LLM 不可用 → business 启发式降级**
```
输入:
  FeasibilityAssessor 正常返回
  call_llm = None

验证:
  feasibility.business.feasible = True
  feasibility.business.assessment 包含 "启发式"
  feasibility.business.concerns 包含 "LLM 不可用" 或类似提示
  不抛异常
```

**T-A2-MP-003: assessor 不可用 → technical 使用默认值**
```
输入:
  assessor = None
  domain_risks = []

验证:
  feasibility.technical.feasible = True
  feasibility.technical.assessment 包含 "无明显技术阻碍"
  feasibility.technical.concerns = []
  不抛异常
```

### 4.2 冲突检测映射

**T-A2-MP-004: 有冲突 → 映射为数据字典格式**
```
输入:
  draft = {"entities": [{"name": "用户", "attributes": ["用户名", "邮箱", "状态"], "description": "..."}]}
  similar_reqs = [{
    "content_id": "spec-001",
    "metadata": {"entities": [
      {"name": "用户", "fields": [
        {"name": "状态", "type": "string", "enum_values": ["active","inactive"]}
      ]}
    ]}
  }]

  ConflictDetector 返回:
    {"conflicts": [{"entity": "用户", "field": "状态", "attribute": "enum_values",
                     "existing_value": ["active","inactive"], "new_value": ["active","inactive","suspended"],
                     "severity": "medium", "existing_spec_id": "spec-001"}],
     "has_conflicts": true}

验证:
  conflicts[0].id = "conflict_1"
  conflicts[0].related_system = "用户"
  conflicts[0].type = "business_flow" (enum_values → business_flow)
  conflicts[0].description 包含 "用户" 和 "状态" 和 "enum_values"
  conflicts[0].severity = "medium"
```

**T-A2-MP-005: 无已有 spec → 返回空列表**
```
输入:
  draft = {"entities": [{"name": "用户", "attributes": ["用户名"]}]}
  similar_reqs = []  (无 metadata.entities)

验证:
  conflicts = []
  ConflictDetector.detect 不被调用
```

**T-A2-MP-006: adapt_draft_for_detector — attributes → fields 转换**
```
输入:
  draft = {"entities": [
    {"name": "用户", "attributes": ["用户名", "邮箱", "角色"], "description": "核心实体"},
    {"name": "订单", "attributes": ["订单号", "金额"], "description": "订单实体"}
  ]}

验证:
  adapted = _adapt_draft_for_detector(draft)
  adapted["entities"][0]["name"] = "用户"
  adapted["entities"][0]["fields"] = [
    {"name": "用户名", "type": "unknown", "required": False},
    {"name": "邮箱", "type": "unknown", "required": False},
    {"name": "角色", "type": "unknown", "required": False}
  ]
  adapted["entities"][1]["name"] = "订单"
  adapted["entities"][1]["fields"] 长度 = 2
```

### 4.3 冲突类型映射

**T-A2-MP-007: _map_conflict_type 各属性映射**
```
输入/预期:
  "type"       → "data_model"
  "format"     → "data_model"
  "precision"  → "data_model"
  "scale"      → "data_model"
  "enum_values"→ "business_flow"
  "service_boundary" → "service_boundary"
  "max_length" → "field_naming"
  "required"   → "field_naming"
  "default"    → "field_naming"
```

### 4.4 确认清单

**T-A2-MP-008: LLM 正常 → 返回 LLM 生成的清单**
```
输入:
  LLM mock 返回: [
    {"id":"check_01","category":"requirement_clarity","item":"确认权限边界","priority":"high"},
    {"id":"check_02","category":"technical_risk","item":"评估并发量","priority":"medium"},
    {"id":"check_03","category":"dependency","item":"确认用户服务版本","priority":"high"}
  ]

验证:
  返回 3 条
  每条都有 id, category, item, priority
  category ∈ {"requirement_clarity", "technical_risk", "dependency"}
  priority ∈ {"high", "medium", "low"}
```

**T-A2-MP-009: LLM 不可用 → 返回模板清单**
```
输入:
  call_llm = None

验证:
  返回 5 条 (_CHECKLIST_TEMPLATES)
  包含 check_01 ~ check_05
  "需求边界是否清晰？" 在结果中
  "技术方案是否考虑了已知风险点？" 在结果中
```

---

## 五、MCP Gateway 集成测试（4 条）

**T-A2-GW-001: 工具列表包含 34 个工具**
```
步骤:
  curl -X POST http://localhost:8081/auth/token
    -H "Content-Type: application/json"
    -d '{"agent_id":"test","req_id":"test-001"}'
  → 获取 token

  curl -H "Authorization: Bearer $TOKEN" http://localhost:8081/tools/list

验证:
  HTTP 200
  返回 JSON 数组长度 = 34
  包含工具名: "search_similar_requirements", "search_known_issues", "get_domain_risks"
```

**T-A2-GW-002: search_similar_requirements 返回真实数据**
```
步骤:
  curl -X POST http://localhost:8081/tools/call
    -H "Content-Type: application/json"
    -H "Authorization: Bearer $TOKEN"
    -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"search_similar_requirements","arguments":{"query":"订单管理","limit":3}},"id":1}'

验证:
  HTTP 200
  Response.jsonrpc = "2.0"
  Response.result IS NOT NULL（非 Mock: 不含 "Mock response" 文本）
  Response.result 为数组或 {"results": [...], "count": N}
```

**T-A2-GW-003: 未知工具 → error 返回**
```
步骤:
  调用 tools/call 但不存在的工具名 "nonexistent_tool"

验证:
  HTTP 200（JSON-RPC 级别仍成功）
  Response.error IS NOT NULL
  Response.error 包含 "unknown tool"
```

**T-A2-GW-004: 无 JWT → 401**
```
步骤:
  curl http://localhost:8081/tools/list（不带 Authorization header）

验证:
  HTTP 401 或 403
```

---

## 六、agent_results API 测试（5 条）

**T-A2-API-001: POST 正常写入**
```
请求: POST /api/agent_results
      Body: {"req_id": "<uuid>", "agent_key": "A2", "cycle": 0,
             "status": "completed", "artifact": {"quality_score": 0.72}}

验证:
  HTTP 201
  Response: {"ok": true, "req_id": "<uuid>", "agent_key": "A2", "cycle": 0,
             "status": "completed", "created": true}

DB 验证:
  SELECT req_id, agent_key, cycle, status
  FROM agent_results WHERE req_id = '<uuid>' AND agent_key = 'A2';
  预期: 1 行, status='completed'
```

**T-A2-API-002: POST UPSERT → 第二次写入更新**
```
步骤 1: (同上) POST → 201, created=true
步骤 2: POST 相同 (req_id, agent_key, cycle) 但 status='empty', artifact 不同

验证:
  HTTP 200
  Response: {"ok": true, "created": false}

DB 验证:
  SELECT count(*) FROM agent_results WHERE req_id = '<uuid>' AND agent_key = 'A2' AND cycle = 0;
  预期: 1
  SELECT status FROM agent_results WHERE req_id = '<uuid>' AND agent_key = 'A2' AND cycle = 0;
  预期: 'empty'
```

**T-A2-API-003: 无效 status 值 → 400**
```
请求: POST /api/agent_results
      Body: {"req_id": "<uuid>", "agent_key": "A2", "cycle": 0, "status": "invalid"}

验证:
  HTTP 400
  detail 包含 "completed, empty, skipped"
```

**T-A2-API-004: 缺失必填字段 → 422**
```
请求: POST /api/agent_results
      Body: {"req_id": "<uuid>", "agent_key": "A2"}

验证:
  HTTP 422 (Pydantic validation error)
  缺少 cycle, status, artifact 字段
```

**T-A2-API-005: 不同 agent_key + cycle 组合独立存储**
```
步骤:
  POST A1/cycle=0 → 201
  POST A2/cycle=0 → 201
  POST A2/cycle=1 → 201

DB 验证:
  SELECT agent_key, cycle FROM agent_results
  WHERE req_id = '<uuid>' ORDER BY agent_key, cycle;
  预期: 3 行
    A1, 0
    A2, 0
    A2, 1
```

---

## 七、Gate0 审批上下文集成测试（3 条）

**T-A2-GT-001: GET /api/approvals/{id}/context 含完整 A2 数据**
```
前置:
  - approvals 表有 1 行 (gate_level=0, cycle=0, status='pending')
  - agent_results 有 A1 cycle=0 记录 (artifact.requirement_draft 非空)
  - agent_results 有 A2 cycle=0 记录 (artifact 含 feasibility_assessment + conflicts + checklist + quality_score)

请求: GET /api/approvals/<approval_id>/context

验证:
  HTTP 200
  Response.a1_output.requirement_draft IS NOT NULL
  Response.a2_output.a2_missing = false
  Response.a2_output.feasibility_assessment.technical IS NOT NULL
  Response.a2_output.feasibility_assessment.business IS NOT NULL
  Response.a2_output.confirmation_checklist 长度 >= 3
  Response.a2_output.conflicts 长度 >= 0
  Response.a2_output.quality_score IS NOT NULL
```

**T-A2-GT-002: A2 缺失 → a2_missing=true**
```
前置:
  - agent_results 无 A2 cycle=0 记录

请求: GET /api/approvals/<approval_id>/context

验证:
  Response.a2_output.a2_missing = true
  Response.a2_output.feasibility_assessment = null
  Response.a2_output.confirmation_checklist = []
  Response.a2_output.conflicts = []
  Response.a2_output.quality_score = null
```

**T-A2-GT-003: A2 status='empty' → a2_missing=false 但数据空**
```
前置:
  agent_results A2 cycle=0, status='empty', artifact={"quality_score": 0.05}

验证:
  Response.a2_output.a2_missing = false
  Response.a2_output.quality_score = 0.05
  feasibility_assessment 为 null（A2 未产出可行性评估）
```

---

## 八、端到端测试（2 条）

### 8.1 正常全流程

**T-A2-E2E-001: A1→A2→Gate0 正常链路**

```
Step 1: 创建需求 + A1 分析 + 确认 (模拟已有数据)
  - requirements: status='analyzing_completed', requirement_draft 非空
  - agent_results A1 cycle=0: completed

Step 2: Orchestrator 发布 context.ready.knowledge_analyst (NATS)
  Payload: {"req_id": "<req_id>", "session_id": "<sid>", "cycle": 0,
            "requirement_draft": {...}}

Step 3: A2 执行 (MCP 全部正常)
  验证点:
    ✓ 日志: [A2] Retrieval levels: sim=mcp, issues=mcp, risks=mcp
    ✓ agent_results A2 cycle=0 status='completed'
    ✓ artifact.feasibility_assessment.technical 非空
    ✓ artifact.feasibility_assessment.business 非空
    ✓ artifact.conflicts 为数组
    ✓ artifact.confirmation_checklist 长度 >= 3
    ✓ artifact.quality_score >= 0.6
    ✓ NATS agent.result.A2 已发布

Step 4: Gate0 审批上下文
  GET /api/approvals/<id>/context
  验证点:
    ✓ a1_output.requirement_draft = A1 产出
    ✓ a2_output.a2_missing = false
    ✓ a2_output.feasibility_assessment 完整

数据链验证:
  ┌─────────────────────────────────────────────────┐
  │ 表                  │ 预期行数 │ 关键字段        │
  ├─────────────────────────────────────────────────┤
  │ requirements        │ 1       │ status='analyzing_completed' │
  │ agent_results       │ 2       │ A1+0, A2+0, 均 completed │
  │ event_log           │ >=2     │ agent.result.A1 + agent.result.A2 |
  └─────────────────────────────────────────────────┘
```

### 8.2 A2 降级全流程

**T-A2-E2E-002: MCP Gateway 不可用 → L2 REST → Gate0 仍可用**

```
Step 1: 停 MCP Gateway (port 8081 不可达)

Step 2: 触发 A2
  验证点:
    ✓ 日志: [A2] Retrieval levels: sim=direct, issues=direct, risks=direct
    ✓ quality_score >= 0.3 (基础分 0.3)
    ✓ agent_results A2 status='completed'
    ✓ Gate0 审批上下文 a2_missing=false

Step 3: 停 MC Backend (port 8000 不可达) + MCP Gateway

Step 4: 再次触发 A2
  验证点:
    ✓ 日志: [A2] Retrieval levels: sim=fallback, issues=fallback, risks=fallback
    ✓ quality_score >= 0.15 (基础分 0.15)
    ✓ agent_results A2 status='completed'
    ✓ Gate0 审批上下文 a2_missing=false

Step 5: 全部降级且无静态数据
  验证点:
    ✓ 日志: [A2] Retrieval levels: sim=empty, issues=empty, risks=empty
    ✓ quality_score = 0.05
    ✓ agent_results A2 status='empty'
```

---

## 九、真实环境集成测试（9 条）

> 以下用例依赖真实外部服务，标记为 `@pytest.mark.integration`，在 CI 中独立 stage 运行。

### 9.1 测试环境要求

| 组件 | 要求 |
|------|------|
| **PostgreSQL** | 真实 DB（test 库），含 migration 008 的 7 张新表 |
| **MCP Gateway** | 真实 Gateway (port 8081)，需含 34 个工具注册 |
| **MC Backend** | 真实后端 (port 8000)，/api/knowledge/search 可用 |
| **LLM (DeepSeek)** | 真实 API，用于可行性/清单 LLM 生成 |
| **NATS** | 嵌入式 nats-server -js |
| **Neo4j** | 可选（有则验证依赖查询） |

### 9.2 MCP 真实调用（3 条）

**T-A2-RL-001: 三路 MCP 并行调用的真实延迟**
```
输入: draft = {"title": "订单管理系统", "domain": "order_management", "description": "支持订单创建、支付、退款全流程"}

验证:
  - _retrieve_similar_requirements 在 ≤ 5s 返回
  - _retrieve_known_issues 在 ≤ 5s 返回
  - _retrieve_domain_risks 在 ≤ 5s 返回
  - 三路各自返回的结构符合预期（list[dict]）
  - 每路 level 为 "mcp"（除非 Gateway 不可达）

标记: @pytest.mark.integration @pytest.mark.mcp @pytest.mark.slow
```

**T-A2-RL-002: MCP 返回空 → L2 REST 接管**
```
前置: 用不匹配的 query 查询 MCP（确保返回空结果或低相似度）

验证:
  - 若 MCP 返回空列表，自动降到 L2 REST
  - REST 可正常返回数据
  - level = "direct"

标记: @pytest.mark.integration @pytest.mark.mcp
```

**T-A2-RL-003: Gateway 部分工具可用 → 仅故障路降级**
```
模拟: 假设 search_known_issues 的 backend 不可达（可模拟或观察真实故障）

验证:
  - similar_requirements: level=mcp
  - known_issues: level=direct (降级到 REST)
  - domain_risks: level=mcp
  - 三路互不影响, quality_score 基于 2 个 mcp + 1 个 direct

标记: @pytest.mark.integration @pytest.mark.mcp @pytest.mark.resilience
```

### 9.3 LLM 真实调用（2 条）

**T-A2-RL-004: feasibility_assessment LLM 生成业务可行性**
```
输入: draft = {"title": "实时视频处理平台", "domain": "general"}

验证:
  - feasibility.business 由 LLM 生成
  - feasibility.business.feasible 为 true/false (由 LLM 判断)
  - feasibility.business.assessment 非空且为中文
  - feasibility.business.concerns 为非空数组

标记: @pytest.mark.integration @pytest.mark.llm
```

**T-A2-RL-005: confirmation_checklist LLM 生成**
```
输入: draft = {"title": "多租户SaaS权限系统", "domain": "auth"}
      feasibility.risk_level = "high"
      conflicts = [{"id":"c1","type":"data_model","severity":"high",...}]

验证:
  - checklist 至少 3 条
  - checklist 内容与输入的高风险/冲突相关
  - 每条都有 id, category, item, priority

标记: @pytest.mark.integration @pytest.mark.llm
```

### 9.4 NATS 真实集成（2 条）

**T-A2-RL-006: context.ready.knowledge_analyst → A2 → agent.result.A2 全链路**
```
前置:
  - 启动嵌入式 nats-server -js
  - 启动 A2 Worker (BaseAgentWorker.subscribe_nats)
  - agent_results 表中无 A2 记录

步骤:
  1. NATS 发布 context.ready.knowledge_analyst
  2. 等待 agent.result.A2 (超时 60s)

验证:
  - agent.result.A2 消息在 ≤ 30s 发布
  - payload.req_id 匹配
  - payload.session_id 非空
  - payload.cycle 匹配
  - payload.feasibility_assessment IS NOT NULL
  - DB 中 agent_results A2 记录已写入

标记: @pytest.mark.integration @pytest.mark.nats
```

**T-A2-RL-007: A2 Worker 断连重连 → 恢复订阅**
```
步骤:
  1. 启动 A2 Worker
  2. 停止 NATS server
  3. 等待 A2 Worker 日志出现 "Connection error"
  4. 重启 NATS server
  5. 等待 A2 Worker 重连

验证:
  - 重连后 context.ready.knowledge_analyst 仍可正常触发
  - agent.result.A2 正常发布

标记: @pytest.mark.integration @pytest.mark.nats @pytest.mark.resilience
```

### 9.5 Neo4j 集成（2 条）

**T-A2-RL-008: Neo4j 可用 → 返回依赖拓扑**
```
前置: Neo4j 已配置且含测试数据

验证:
  - query_dependencies(req_id) 返回非空列表
  - 列表中每条含 service 和 downstream 字段

标记: @pytest.mark.integration @pytest.mark.neo4j
```

**T-A2-RL-009: Neo4j 不可用 → 优雅降级空列表**
```
前置: Neo4j 未配置或不可达

验证:
  - query_dependencies(req_id) 返回 []
  - 不抛异常
  - 日志含 "Neo4j not configured" 或 "Neo4j query failed"

标记: @pytest.mark.integration @pytest.mark.neo4j @pytest.mark.resilience
```

---

## 十、并发与边界测试（4 条）

**T-A2-CC-001: 同一 req_id 重复触发 A2 → 第二次幂等**
```
步骤:
  1. 触发 A2 → execute() → agent_results INSERT → NATS 发布
  2. 再次触发 A2 (相同 req_id + cycle)
  3. execute() → agent_results UPSERT → 覆盖原记录 → NATS 发布

验证:
  agent_results 同一 (req_id, agent_key, cycle) 只有 1 行
  artifact 为第二次执行的结果（overwrite）
```

**T-A2-CC-002: empty drafts — 不崩溃**
```
输入:
  context_package = {"session_id": "sid", "cycle": 0, "requirement_draft": {}}

验证:
  - _retrieve_similar_requirements({}) → query = "" → MCP/REST 可处理空查询
  - _retrieve_domain_risks("general") → 默认 domain
  - FeasibilityAssessor.assess({}) → 返回低置信度结果
  - execute() 不抛异常
```

**T-A2-CC-003: session_id 为空字符串 — 不阻塞**
```
输入:
  context_package = {"session_id": "", "cycle": 0, "requirement_draft": {...}}

验证:
  - execute() 返回的 session_id = ""
  - _persist_agent_result 收到的 session_id = ""
  - POST /api/agent_results 不因 session_id 为空而失败
```

**T-A2-CC-004: 大数据量 similar_reqs — fuse_knowledge 截断处理**
```
输入:
  similar_reqs 返回 50 条

验证:
  - fuse_knowledge 只处理前 5 条
  - summarize_similar_requirements 收到最多 5 条
  - 不因数据量而 OOM 或超时
```

---

## 十一、测试环境与 Mock 策略

### 11.1 依赖隔离

| 组件 | 测试策略 |
|------|---------|
| **PostgreSQL** | 真实 DB（test 库），每个测试函数用事务回滚 |
| **MCP Gateway** | 单元测试全部 mock `MCPClient` 方法；集成测试用真实 Gateway |
| **MC Backend** | 单元测试 mock `RAGRetriever` 的 HTTP 调用；集成测试用真实 Backend |
| **LLM (DeepSeek)** | 全部 mock：`base_worker.call_llm` 返回预定义数据或抛异常 |
| **FeasibilityAssessor** | 单元测试 mock `assess()` 的返回；集成测试用真实实例 |
| **ConflictDetector** | 单元测试 mock `detect()` 的返回；集成测试用真实实例 |
| **Neo4j** | 单元测试 mock Neo4j URL 为空 |
| **NATS** | 集成测试用嵌入式 NATS（`nats-server -js`），单元测试 mock `base_worker` |
| **JWT / MCP Auth** | 集成测试用 Gateway 真实 `/auth/token` 端点 |

### 11.2 数据夹具 (Fixtures)

```python
# 标准 context_package（模拟 Orchestrator 传入）
MOCK_CONTEXT_PACKAGE = {
    "req_id": "test-req-001",
    "session_id": "test-sid-001",
    "cycle": 0,
    "workflow_id": "wf-test-001",
    "requirement_draft": {
        "title": "用户管理系统",
        "description": "构建企业用户管理平台，支持增删改查和角色权限",
        "domain": "user_management",
        "entities": [
            {"name": "用户", "attributes": ["用户名", "邮箱", "角色", "状态"], "description": "核心用户实体"},
            {"name": "角色", "attributes": ["角色名", "权限列表"], "description": "权限组定义"}
        ],
        "use_cases": ["管理员创建用户", "用户自助注册"],
        "acceptance_criteria": ["Given 管理员已登录 When 填写信息并提交 Then 用户创建成功"],
        "constraints": ["单租户部署"],
        "risks": ["并发权限修改"],
        "estimated_cost": "2人月"
    },
    "message": "做一个用户管理系统"
}

# 标准 MCP 返回数据
MOCK_MCP_SIMILAR_REQS = [
    {"content_id": "req-001", "content_text": "企业用户中心 v2", "similarity": 0.92,
     "metadata": {"tags": ["auth", "rbac"], "entities": [
         {"name": "用户", "fields": [{"name": "用户名", "type": "string"}, {"name": "邮箱", "type": "string"}]}
     ]}},
    {"content_id": "req-002", "content_text": "权限管理系统", "similarity": 0.85,
     "metadata": {"tags": ["security"]}},
    {"content_id": "req-003", "content_text": "账户管理后台", "similarity": 0.78,
     "metadata": {"tags": ["admin"]}},
]

MOCK_MCP_KNOWN_ISSUES = [
    {"content_id": "issue-001", "content_text": "并发角色分配导致的权限不一致",
     "similarity": 0.88, "metadata": {"tags": ["concurrency", "rbac"]}},
]

MOCK_MCP_DOMAIN_RISKS = [
    {"risk_name": "权限提升攻击", "description": "角色分配需校验操作者权限", "severity": "high"},
    {"risk_name": "密码策略不符合安全规范", "description": "需强制复杂度要求", "severity": "medium"},
]

# 标准 FeasibilityAssessor 输出
MOCK_FEASIBILITY_RAW = {
    "feasible": True,
    "risk_level": "medium",
    "concerns": ["并发权限修改可能导致不一致", "需确认多租户需求"],
    "confidence": 0.60,
}

# 标准 ConflictDetector 输出
MOCK_CONFLICT_RAW = {
    "conflicts": [
        {"entity": "用户", "field": "状态", "attribute": "enum_values",
         "existing_value": ["active", "inactive"], "new_value": ["active", "inactive", "suspended"],
         "severity": "medium", "existing_spec_id": "spec-001"},
    ],
    "has_conflicts": True,
}

# 标准 LLM 返回（可行性评估）
MOCK_LLM_BUSINESS_FEASIBILITY = json.dumps({
    "feasible": True,
    "assessment": "业务方向可行，用户管理是SaaS平台的核心基础模块",
    "concerns": ["需确认多租户定价策略", "与现有CRM系统的用户数据同步方案待定"],
})

# 标准 LLM 返回（确认清单）
MOCK_LLM_CHECKLIST = json.dumps([
    {"id": "check_01", "category": "requirement_clarity",
     "item": "多租户模式下不同租户的角色权限隔离策略？", "priority": "high"},
    {"id": "check_02", "category": "technical_risk",
     "item": "角色分配并发操作的竞态条件需评估", "priority": "high"},
    {"id": "check_03", "category": "dependency",
     "item": "与现有CRM系统的用户数据同步方案需对齐", "priority": "medium"},
])
```

---

## 十二、测试执行清单

### 按 Phase 分配

| Phase | 测试编号 | 测试数 | 关键依赖 |
|-------|---------|:-----:|---------|
| **Phase 1** (DB+API) | T-A2-DB-001 → T-A2-DB-006, T-A2-API-001 → T-A2-API-005 | 11 | PostgreSQL 就绪 |
| **Phase 2** (Unit: Agent+Mappers) | T-A2-AG-001 → T-A2-AG-015, T-A2-MP-001 → T-A2-MP-009 | 24 | LLM/assessor mock 就绪 |
| **Phase 3** (Integration: MCP+Gate0) | T-A2-GW-001 → T-A2-GW-004, T-A2-GT-001 → T-A2-GT-003 | 7 | MCP Gateway + Backend 就绪 |
| **Phase 4** (E2E+Concurrency) | T-A2-E2E-001 → T-A2-E2E-002, T-A2-CC-001 → T-A2-CC-004 | 6 | NATS 就绪 |
| **Phase 5** (Real Env Integration) | T-A2-RL-001 → T-A2-RL-009 | 9 | LLM/NATS/MCP/Neo4j 真实服务 |

### 测试通过标准

- **Phase 1**: 11/11 通过 → agent_results DB 操作正确，API 契约完整
- **Phase 2**: 24/24 通过 → 降级链正确，映射层格式对齐数据字典，质量评分公式正确
- **Phase 3**: 7/7 通过 → MCP Gateway 集成正确，Gate0 审批上下文完整
- **Phase 4**: 6/6 通过 → 全链路正确，降级链路验证，并发安全
- **Phase 5**: 9/9 通过 → 真实服务环境下行为正确

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.1
**总测试数**: 57 条（数据库 6 + Agent 单元 15 + mappers 9 + MCP 集成 4 + API 5 + Gate0 集成 3 + E2E 2 + 真实环境集成 9 + 并发边界 4）
