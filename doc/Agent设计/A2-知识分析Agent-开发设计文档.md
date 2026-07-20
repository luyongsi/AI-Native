# A2 知识分析 Agent — 完整开发设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 开发设计（对齐 A2-MCP服务改造设计 v1.2 + 阶段一数据字典 v1.3，通过 critical 审计）
- **参考**: [A2-MCP服务改造设计](./A2-MCP服务改造设计.md) · [阶段一数据字典](../Agent规格/阶段一-数据字典.md) · [系统状态机 v2.4](../系统架构/系统状态机与信息流设计.md)
- **原则**: 以数据字典为唯一数据规范源；基于已完成实施的代码反向写文档
- **审计**: 参见 §十五 审计记录（v1.0: C1-C9）

---

## 一、开发范围

### 1.1 A2 在阶段一中的位置

```
阶段一：需求分析
┌──────────────────────────────────────────────────┐
│  A1 需求分析 ──► A2 知识分析 ──► 【Gate0】       │
│ (HTTP+SSE)      (NATS调度)      (人工审批)       │
└──────────────────────────────────────────────────┘
```

A2 是阶段一的**第二个 Agent**，在 A1 完成需求草案后由 Orchestrator 通过 NATS 调度执行。

### 1.2 A2 职责边界

- **负责**:
  - 通过 MCP Gateway 检索知识库（相似需求、已知问题、领域风险）
  - 三层降级保证检索可靠性（MCP → REST 直调 → 静态 KB fallback）
  - 可行性评估（技术 + 业务二维）
  - 冲突检测（与已有 Spec 比对）
  - 确认清单生成（供 Gate0 审批人参考）
  - 知识融合与质量评分
  - 自行持久化 `agent_results` 表
- **不负责**:
  - 用户交互（非对话式 Agent）
  - Gate0 审批决策
  - 需求草案修改

### 1.3 通信模型

```
Orchestrator 发布 context.ready.knowledge_analyst (NATS)
    ↓
BaseAgentWorker 接收 → A2KnowledgeAnalyst.execute(req_id, context_package)
    ↓
Phase 1: MCP Gateway (L1) → MC Backend REST (L2) → 静态 KB (L3) — 3 路独立降级
Phase 2: Neo4j 依赖查询
Phase 3: 关联 PR/Issue 查询
Phase 4: 可行性评估 (FeasibilityAssessor + mappers)
Phase 5: 冲突检测 (ConflictDetector + mappers)
Phase 6: 确认清单 (LLM + 模板降级)
Phase 7: 知识融合 (LLM 总结)
Phase 8: 持久化 agent_results (MC Backend API)
Phase 9: 发布 agent.result.A2 (NATS, base_worker 自动完成)
    ↓
Orchestrator 接收 agent.result.A2 → Gate0
```

**关键差异——A2 vs A1**:
| 维度 | A1 | A2 |
|------|----|----|
| 启动方式 | HTTP+SSE（用户触发） | NATS dispatch（Orchestrator 触发） |
| 运行模式 | 在线服务，多轮对话 | 自主 Agent，单次执行 |
| 降级策略 | MCP 超时不阻塞 | 三层降级（MCP→REST→fallback） |
| 持久化 | MC Backend confirm API 写入 | 自行调用 MC Backend API 写入 |
| 人类交互 | 实时对话、澄清问题 | 无交互，纯分析产出 |

---

## 二、模块架构

### 2.1 文件结构

```
agent-workers/
├── a2_knowledge_analyst.py    # A2KnowledgeAnalyst 主类
├── a2/
│   ├── __init__.py
│   ├── rag_retriever.py       # RAGRetriever — L2 REST 检索 + L3 静态 fallback
│   ├── feasibility.py         # FeasibilityAssessor — 技术可行性评估
│   ├── conflict_detector.py   # ConflictDetector — 跨 Spec 冲突检测
│   ├── mappers.py             # 数据映射层 — feasibility/conflict 输出 → 数据字典格式
│   └── test_knowledge_analyst.py  # 单元测试
├── a1/analyzer/
│   └── mcp_client.py          # MCPClient — L1 MCP Gateway 检索（A1+A2 共用）
```

### 2.2 依赖注入

```python
class A2KnowledgeAnalyst(BaseAgentWorker):
    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)

        # L1 — MCP Gateway (shared with A1)
        from a1.analyzer.mcp_client import MCPClient
        self.mcp = MCPClient()

        # L2 — RAGRetriever (direct REST to MC Backend)
        from a2.rag_retriever import RAGRetriever
        self.rag = RAGRetriever(api_base_url=MC_BACKEND_URL)

        # Sub-modules — feasibility + conflict detection
        from a2.feasibility import FeasibilityAssessor
        from a2.conflict_detector import ConflictDetector
        self.feasibility_assessor = FeasibilityAssessor()
        self.conflict_detector = ConflictDetector()

        self.neo4j_available = bool(NEO4J_URL)
```

---

## 三、核心执行流程

### 3.1 execute() 9-Phase 流水线

```
execute(req_id, context_package)
│
├── Phase 1: 知识检索 (3 路独立三层降级，并行执行)
│   ├── _retrieve_similar_requirements(draft) → (results, level)
│   ├── _retrieve_known_issues(draft)          → (results, level)
│   └── _retrieve_domain_risks(domain)         → (results, level)
│   level ∈ {"mcp", "direct", "fallback", "empty"}
│
├── Phase 2: Neo4j 依赖查询
│   └── query_dependencies(req_id) → list[dict]
│
├── Phase 3: 关联 PR/Issue 查询
│   └── query_related_prs(query_text) → list[dict]
│
├── Phase 4: 可行性评估 (NEW)
│   └── mappers.build_feasibility_assessment(draft, risks, assessor, call_llm)
│       → {technical: {feasible, assessment, concerns},
│          business:  {feasible, assessment, concerns},
│          risk_level, risk_rationale}
│
├── Phase 5: 冲突检测 (NEW)
│   └── mappers.build_conflicts(draft, similar_reqs, detector)
│       → [{id, related_system, type, description, severity}]
│
├── Phase 6: 确认清单 (NEW)
│   └── mappers.build_confirmation_checklist(draft, feasibility, conflicts, call_llm)
│       → [{id, category, item, priority}]
│
├── Phase 7: 知识融合 + 质量评分
│   ├── fuse_knowledge() → knowledge_package
│   └── _calc_quality_score(retrieval_levels, knowledge_package) → float
│
├── Phase 8: 持久化 agent_results (NEW)
│   └── _persist_agent_result(req_id, session_id, cycle, status, artifact)
│       → POST {MC_BACKEND_URL}/api/agent_results
│
└── Phase 9: 返回结果 → BaseAgentWorker 自动发布 agent.result.A2 (NATS)
    → {req_id, session_id, cycle, status, feasibility_assessment,
       confirmation_checklist, conflicts, quality_score, timestamp}
```

### 3.2 完整 execute() 代码

```python
async def execute(self, req_id: str, context_package: dict) -> dict:
    start_time = time.time()
    draft = context_package.get("requirement_draft", {})
    domain = draft.get("domain", "general")
    session_id = context_package.get("session_id", "")
    cycle = context_package.get("cycle", 0)

    try:
        # Phase 1: Knowledge retrieval (3 independent 3-tier chains, parallel)
        sim_task = asyncio.ensure_future(self._retrieve_similar_requirements(draft))
        issues_task = asyncio.ensure_future(self._retrieve_known_issues(draft))
        risks_task = asyncio.ensure_future(self._retrieve_domain_risks(domain))

        (sim_reqs, sim_level), (issues, issues_level), (risks, risks_level) = (
            await asyncio.gather(sim_task, issues_task, risks_task)
        )
        retrieval_levels = [sim_level, issues_level, risks_level]

        # Phase 2: Neo4j dependencies
        dependencies = await self.query_dependencies(req_id)

        # Phase 3: Related PRs
        related_prs = await self.query_related_prs(draft.get("title", ""))

        # Phase 4: Feasibility assessment
        from a2.mappers import build_feasibility_assessment
        feasibility = await build_feasibility_assessment(
            draft, risks, assessor=self.feasibility_assessor,
            call_llm=self.call_llm,
        )

        # Phase 5: Conflict detection
        from a2.mappers import build_conflicts
        conflicts = await build_conflicts(
            draft, sim_reqs, detector=self.conflict_detector,
        )

        # Phase 6: Confirmation checklist
        from a2.mappers import build_confirmation_checklist
        checklist = await build_confirmation_checklist(
            draft, feasibility, conflicts, call_llm=self.call_llm,
        )

        # Phase 7: Knowledge fusion
        # NOTE: 'knowledge_package' (local var) and artifact key "knowledge_package"
        #       share the same name by design — the fused dict is stored as-is in
        #       the artifact, making the JSON structure self-describing.
        knowledge_package = await self.fuse_knowledge(
            sim_reqs, dependencies, related_prs, draft.get("title", ""),
            req_id, context_package,
        )
        quality_score = self._calc_quality_score(retrieval_levels, knowledge_package)

        # Phase 8: Persist agent_results
        status = self._determine_status(retrieval_levels)
        artifact = {
            "knowledge_package": knowledge_package,
            "feasibility_assessment": feasibility,
            "confirmation_checklist": checklist,
            "conflicts": conflicts,
            "quality_score": quality_score,
        }
        await self._persist_agent_result(req_id, session_id, cycle, status, artifact)

        # Phase 9: Return
        return {
            "req_id": req_id,
            "session_id": session_id,
            "cycle": cycle,
            "status": status,
            "feasibility_assessment": feasibility,
            "confirmation_checklist": checklist,
            "conflicts": conflicts,
            "quality_score": quality_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("[A2] Analysis failed: %s", e, exc_info=True)
        await self.report_status(req_id, "failed", str(e))
        raise
```

---

## 四、三层降级检索

### 4.1 降级链设计

每个检索方法独立执行三层降级，单个失败不阻塞整体：

```
L1: MCP Gateway (JSON-RPC, 5s 超时)
│   成功 → ("mcp", results)
│   失败 ↓
L2: MC Backend REST (直接 HTTP, 10s 超时)
│   成功 → ("direct", results)
│   失败 ↓
L3: 静态知识库 (关键词匹配)
    → ("fallback", results)  或  ("empty", [])
```

### 4.2 三个检索方法

```python
async def _retrieve_similar_requirements(self, draft: dict) -> tuple[list[dict], str]:
    """L1: MCPClient.search_similar_requirements() → L2: RAGRetriever.search_similar_requirements() → L3: RAGRetriever._fallback_search()"""

async def _retrieve_known_issues(self, draft: dict) -> tuple[list[dict], str]:
    """L1: MCPClient.search_known_issues() → L2: RAGRetriever.search_general(content_type='issue') → L3: fallback"""

async def _retrieve_domain_risks(self, domain: str) -> tuple[list[dict], str]:
    """L1: MCPClient.get_domain_risks() → L2: RAGRetriever.search_general(content_type='doc', query='domain:{domain} risks') → L3: fallback"""
```

### 4.3 RAGRetriever 接口

```python
class RAGRetriever:
    def __init__(self, api_base_url: str = "http://localhost:8000")

    async def search_similar_requirements(
        self, query_text: str, limit: int = 5, threshold: float = 0.5,
    ) -> list[dict]:
        """POST /api/knowledge/search (content_type=requirement)"""

    async def search_general(
        self, query_text: str, content_type: str | None = None,
        limit: int = 10, threshold: float = 0.5,
    ) -> list[dict]:
        """POST /api/knowledge/search (通用查询，可选 content_type)"""

    def _fallback_search(self, query_text: str, limit: int = 5) -> list[dict]:
        """静态关键词匹配，5 个预置文档"""
```

---

## 五、数据映射层 (mappers.py)

### 5.1 设计动机

现有子模块的输出格式与数据字典要求不一致：

| 子模块 | 输出格式 | 数据字典要求 | 差距 |
|--------|---------|-------------|------|
| `FeasibilityAssessor.assess()` | `{feasible, risk_level, concerns, confidence}` (一维) | `{technical, business, risk_level, risk_rationale}` (二维) | 缺少业务可行性维度 |
| `ConflictDetector.detect()` | `{entity, field, attribute, existing_value, new_value, severity, existing_spec_id}` | `{id, related_system, type, description, severity}` | 字段名不匹配 |
| Draft entities | `{name, attributes: [string]}` | `{name, fields: [{name, type, required}]}` | detector 需要 fields 格式 |

`mappers.py` 在子模块输出和数据字典格式之间做翻译。

### 5.2 build_feasibility_assessment()

```
FeasibilityAssessor.assess(draft) → {feasible, risk_level, concerns, confidence}
        │
        ▼ 映射
{
  "technical": {
    "feasible": raw["feasible"],
    "assessment": "; ".join(raw["concerns"]) 或 默认文本,
    "concerns": raw["concerns"]
  },
  "business": {
    "feasible": LLM评估结果 或 True (启发式),
    "assessment": LLM评估文本 或 默认文本,
    "concerns": LLM顾虑 或 []
  },
  "risk_level": raw["risk_level"],
  "risk_rationale": 技术顾虑 + 领域风险综合文本
}
```

业务可行性评估：LLM 优先（基于 domain_risks + 需求标题），LLM 不可用时用启发式模板降级。

**`_build_risk_rationale` 领域风险字段键名兼容**:
`domain_risks` 列表中的元素可能来自多个数据源（MCP Gateway、RAGRetriever REST、静态 fallback），字段键名存在差异。`_build_risk_rationale()` 按以下优先级查找显示文本：
1. `"description"` 字段
2. `"risk_name"` 字段
3. `"risk"` 字段（fallback）

调用方无需关心数据来源，映射层统一处理三种格式。

### 5.3 build_conflicts()

```
Step 1: 从 similar_reqs metadata 提取已有 spec (含 entities 的)
Step 2: 适配 draft entities 格式: attributes[] → fields[{name, type: "unknown", required: false}]
Step 3: 调用 ConflictDetector.detect(adapted_draft, adapted_specs)
Step 4: 映射输出字段:
  entity → related_system
  field + attribute + existing_value + new_value → description
  attribute → type (data_model | business_flow | field_naming | service_boundary)
  severity → severity (原样保留)
```

`_adapt_draft_for_detector()`:
```python
# 输入: {"entities": [{"name": "用户", "attributes": ["用户名", "邮箱"], "description": "..."}]}
# 输出: {"entities": [{"name": "用户", "fields": [
#           {"name": "用户名", "type": "unknown", "required": false},
#           {"name": "邮箱", "type": "unknown", "required": false}
#        ]}]}
```

### 5.4 build_confirmation_checklist()

LLM 优先生成 3-5 条上下文相关的确认项，LLM 不可用时用 5 条预置模板降级：

```python
_CHECKLIST_TEMPLATES = [
    {"id": "check_01", "category": "requirement_clarity",
     "item": "需求边界是否清晰？有无遗漏的上下游依赖？", "priority": "high"},
    {"id": "check_02", "category": "technical_risk",
     "item": "技术方案是否考虑了已知风险点？能否在现有架构上实现？", "priority": "high"},
    {"id": "check_03", "category": "dependency",
     "item": "是否与已有系统/数据模型存在冲突？冲突点是否已澄清？", "priority": "medium"},
    {"id": "check_04", "category": "requirement_clarity",
     "item": "验收标准是否可度量？关键场景是否已覆盖？", "priority": "medium"},
    {"id": "check_05", "category": "dependency",
     "item": "是否需要外部团队/第三方配合？排期是否已对齐？", "priority": "low"},
]
```

### 5.5 _extract_json_block — JSON 提取器

```python
def _extract_json_block(text: str) -> str:
    """Extract the first JSON object or array from an LLM response.

    Uses bracket-depth counting with string/escape tracking to correctly
    handle { and } inside JSON string values (e.g. "当 {order.status} 变更时").
    """
    text = text.strip()
    # try raw parse first
    try:
        json.loads(text)
        return text
    except (json.JSONDecodeError, ValueError):
        pass
    # find first { or [
    for start_char in ("{", "["):
        start = text.find(start_char)
        if start == -1: continue
        end_char = "}" if start_char == "{" else "]"
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            if escape:                   escape = False; continue
            if text[i] == '\\' and in_string: escape = True; continue
            if text[i] == '"':           in_string = not in_string; continue
            if in_string:                continue
            if text[i] == start_char:    depth += 1
            elif text[i] == end_char:    depth -= 1
                if depth == 0: return text[start : i + 1]
    return text
```

与 A1 的 `DraftBuilder._try_parse_json()` 使用相同的字符串/转义状态机模式，确保 LLM 回复中 JSON 值内包含 `{` / `}` 字符时不会导致括号计数错误。

---

## 六、质量评分

### 6.1 计算逻辑

对齐 [A2-MCP服务改造设计 §3.4.4](./A2-MCP服务改造设计.md#344-降级链设计)：

```python
def _calc_quality_score(retrieval_levels: list[str], knowledge_package: dict) -> float:
    # 基础分 (基于检索数据来源质量)
    mcp_count = retrieval_levels.count("mcp")
    direct_count = retrieval_levels.count("direct")
    fallback_count = retrieval_levels.count("fallback")

    if mcp_count == 3:       base = 0.6
    elif mcp_count >= 1:     base = 0.4
    elif direct_count >= 1:  base = 0.3
    elif fallback_count >= 1: base = 0.15
    else:                    base = 0.05   # 全部 empty

    # 内容加分
    # NOTE: 'suggested_approach' uses a truthiness check — an empty string ""
    #       from a fallback summary will NOT earn the +0.10 bonus. This is
    #       intentional: a genuinely-empty summary indicates no usable LLM output.
    base += min(len(knowledge_package.get("similar_requirements", [])) * 0.08, 0.25)
    if knowledge_package.get("suggested_approach"):
        base += 0.10
    if knowledge_package.get("risks"):
        base += min(len(knowledge_package["risks"]) * 0.03, 0.10)

    return round(min(base, 1.0), 3)
```

### 6.2 状态判定

```python
@staticmethod
def _determine_status(retrieval_levels: list[str]) -> str:
    if all(lvl == "empty" for lvl in retrieval_levels):
        return "empty"
    return "completed"
```

`status='skipped'` 仅由 Orchestrator 在 A2 超时时写入，A2 不自写此值。

---

## 七、产物结构

### 7.1 agent_results.artifact

对齐 [数据字典 §5.2](../Agent规格/阶段一-数据字典.md#52-a2-知识分析产出):

```json
{
  "knowledge_package": {
    "analyzed_at": "2026-07-13T10:00:00Z",
    "query_text": "用户管理系统",
    "similar_requirements": [
      {"id": "uuid", "title": "...", "similarity": 0.92, "metadata": {...}}
    ],
    "code_patterns": ["Pattern: auth", "Pattern: rbac"],
    "risks": [{"risk": "concurrency", "description": "...", "severity": "medium"}],
    "suggested_approach": "基于相似需求的LLM分析总结...",
    "estimated_complexity": {"score": 0.45, "level": "medium", "estimated_days": 11},
    "dependencies": [{"service": "user-service", "downstream": ["auth-service"]}],
    "related_prs": []
  },
  "feasibility_assessment": {
    "technical": {"feasible": true, "assessment": "...", "concerns": [...]},
    "business": {"feasible": true, "assessment": "...", "concerns": [...]},
    "risk_level": "medium",
    "risk_rationale": "技术风险: ... \n领域风险: ..."
  },
  "confirmation_checklist": [
    {"id": "check_01", "category": "requirement_clarity",
     "item": "需求边界是否清晰？", "priority": "high"}
  ],
  "conflicts": [
    {"id": "conflict_1", "related_system": "用户",
     "type": "field_naming", "description": "...", "severity": "low"}
  ],
  "quality_score": 0.72
}
```

### 7.2 execute() 返回值 (agent.result.A2 NATS payload)

对齐 [数据字典 §5.6](../Agent规格/阶段一-数据字典.md#56-a2-agent-输出):

```python
{
    "req_id": "uuid",
    "session_id": "uuid",        # 全局路由键
    "cycle": 0,                   # 全局路由键
    "status": "completed",
    "feasibility_assessment": {...},
    "confirmation_checklist": [...],
    "conflicts": [...],
    "quality_score": 0.72,
    "timestamp": "ISO 8601"
}
```

---

## 八、持久化

### 8.1 agent_results 写入

A2 **自行写入** `agent_results` 表（对齐数据字典 §1.1 职责归属），通过 MC Backend API 间接写入（遵循项目架构：Agent → MC Backend → DB）：

```python
async def _persist_agent_result(self, req_id, session_id, cycle, status, artifact):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{MC_BACKEND_URL}/api/agent_results",
                json={
                    "req_id": req_id,
                    "agent_key": "A2",
                    "cycle": cycle,
                    "status": status,
                    "artifact": artifact,
                },
            )
            if resp.status_code in (200, 201):
                logger.info("[A2] Persisted agent_result (cycle=%d, status=%s)", cycle, status)
            else:
                logger.warning("[A2] Failed to persist: HTTP %d", resp.status_code)
    except Exception as e:
        logger.warning("[A2] Failed to persist: %s (non-fatal)", e)
```

**失败策略**: 持久化失败不阻塞——NATS 事件仍通过 `base_worker` 发布。日志中记录 warning 供运维排查。

### 8.2 MC Backend API

`POST /api/agent_results`:
- 接收 `{req_id, agent_key, cycle, status, artifact}`
- UPSERT 逻辑: `INSERT ... ON CONFLICT (req_id, agent_key, cycle) DO UPDATE`
- 返回 201 (新建) 或 200 (更新)

---

## 九、MCP Gateway 集成

### 9.1 三个知识库工具

| 工具名 | 参数 | MCP Gateway 行为 | MC Backend API |
|--------|------|-----------------|---------------|
| `search_similar_requirements` | `query`, `limit`(optional) | → KnowledgeClient → | `POST /api/knowledge/search?content_type=requirement` |
| `search_known_issues` | `query`, `limit`(optional) | → KnowledgeClient → | `POST /api/knowledge/search?content_type=issue` |
| `get_domain_risks` | `domain` | → KnowledgeClient → | `POST /api/knowledge/search?content_type=doc&query=domain:{domain} risks` |

### 9.2 MCPClient (A1+A2 共用)

位于 `a1/analyzer/mcp_client.py`：

- URL: `http://localhost:8081/tools/call` (环境变量 `MCP_GATEWAY_URL`)
- JWT 认证: 自动从 `/auth/token` 获取 token
- 响应解析: 直接取 `body["result"]`（Go 服务端返回裸数据，非 MCP 标准 `content[0].text` 格式）
- 5s 超时 + 1.5s 连接超时

### 9.3 MCP Gateway KnowledgeClient

位于 `repos/mcp-gateway/backend/knowledge_client.go`：

```go
type KnowledgeClient struct {
    baseURL    string
    httpClient *http.Client  // 10s timeout
}

func (kc *KnowledgeClient) SearchSimilarRequirements(args map[string]interface{}) (interface{}, error)
func (kc *KnowledgeClient) SearchKnownIssues(args map[string]interface{}) (interface{}, error)
func (kc *KnowledgeClient) GetDomainRisks(args map[string]interface{}) (interface{}, error)
```

三个方法均调用 `POST {baseURL}/api/knowledge/search`，通过 `content_type` query 参数区分。

---

## 十、子模块接口

### 10.1 FeasibilityAssessor

```python
class FeasibilityAssessor:
    async def assess(self, requirement: dict) -> dict:
        """
        Returns: {feasible: bool, risk_level: "low"|"medium"|"high",
                  concerns: list[str], confidence: float}
        """
```

基于关键词启发式匹配检测硬性阻碍和风险模式。内部维护 `HARD_BLOCKERS`（如 `real_time_video`）和 `HIGH_RISK_PATTERNS`（如 `legacy_migration`）字典。

### 10.2 ConflictDetector

```python
class ConflictDetector:
    async def detect(self, new_requirement: dict, existing_specs: list[dict]) -> dict:
        """
        Args:
            new_requirement: {"entities": [{"name": "..", "fields": [{"name": "..", "type": "..", ...}]}]}
            existing_specs: [{"id": "..", "entities": [...]}]
        Returns: {conflicts: [{entity, field, attribute, existing_value, new_value, severity, existing_spec_id}],
                  has_conflicts: bool}
        """
```

按 `_SENSITIVE_FIELDS`（status, type, max_length, enum_values 等 13 个字段）逐字段比对同名实体，输出差异点。

### 10.3 RAGRetriever

```python
class RAGRetriever:
    def __init__(self, api_base_url: str = "http://localhost:8000")
    async def search_similar_requirements(query_text, limit=10, threshold=0.5) -> list[dict]
    async def search_similar_code(query_text, limit=10, threshold=0.5) -> list[dict]
    async def search_general(query_text, content_type=None, limit=10, threshold=0.5) -> list[dict]
    def _fallback_search(query_text, limit) -> list[dict]
```

L2 直接调 `POST /api/knowledge/search` REST API。L3 用 5 个预置文档做关键词匹配降级。

---

## 十一、异常处理

### 11.1 超时策略

| 场景 | 超时 | 处理 |
|------|------|------|
| MCP 单路调用 | 5s | 降级到 L2 REST |
| RAGRetriever REST 调用 | 10s | 降级到 L3 静态 fallback |
| FeasibilityAssessor 异常 | — | 用默认值 `{feasible: True, risk_level: "low", concerns: []}` |
| ConflictDetector 异常 | — | 返回空列表 `[]` |
| LLM 调用 (feasibility/checklist) | 30s (base_worker 默认) | 降级到启发式模板 |
| A2 整体执行 | 10min (Orchestrator) | Orchestrator 重试 1 次，仍失败写 status='skipped' |
| agent_results API 持久化 | 10s | 记录 warning 不阻塞，NATS 仍发布 |

### 11.2 错误恢复

| 场景 | 恢复策略 |
|------|---------|
| MCP Gateway 不可达 | L2 REST 自动接管 |
| MC Backend 不可达 | L3 静态 KB 自动接管 |
| 全部 L1/L2/L3 空 | status='empty', quality_score=0.05 |
| Neo4j 不可用 | 跳过依赖查询，返回空列表 |
| agent_results API 写入失败 | 非致命，NATS 事件仍发布，日志 warning |
| execute() 异常 | base_worker 捕获，report_status('failed') |

### 11.3 降级不阻塞原则

三个检索方法独立执行，互不影响：
- A 路 MCP 成功 + B 路降到 L2 + C 路降到 L3 → quality_score 基于各级别计数综合计算
- 不会因为 "get_domain_risks 的 MCP 超时" 而导致 "search_similar_requirements 也不走 MCP"

---

## 十二、NATS 事件协议

### 12.1 context.ready.knowledge_analyst → A2

由 Orchestrator 发布，`BaseAgentWorker.subscribe_nats()` 接收后调用 `execute()`。

Payload 由 Orchestrator 的 `build_context` activity 构建，包含：
- `req_id`, `session_id`, `cycle`
- `requirement_draft` (A1 最终产出)
- `message` (用户原始消息)

### 12.2 agent.result.A2 → Orchestrator

由 `BaseAgentWorker` 在 `execute()` 返回后自动发布到 NATS。

Payload = execute() 的返回值：`{req_id, session_id, cycle, status, feasibility_assessment, confirmation_checklist, conflicts, quality_score, timestamp}`

---

## 十三、文件变更清单

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `repos/agent-workers/a2_knowledge_analyst.py` | 重写 | 9-Phase 流水线，三层降级，完整产物 |
| 2 | `repos/agent-workers/a2/mappers.py` | 新建 | feasibility/conflict 映射层 |
| 3 | `repos/agent-workers/a1/analyzer/mcp_client.py` | 修改 | URL/响应解析/JWT/参数名修复 |
| 4 | `repos/mcp-gateway/server/tool_registry.go` | 修改 | 新增 3 个知识库工具定义 |
| 5 | `repos/mcp-gateway/backend/knowledge_client.go` | 新建 | MC Backend HTTP 调用封装 |
| 6 | `repos/mcp-gateway/server/tool_router.go` | 修改 | 知识工具真实路由 |
| 7 | `repos/mcp-gateway/main.go` | 修改 | 传入 MC_BACKEND_URL |
| 8 | `repos/mc-backend/api/agent_results.py` | 新建 | POST /api/agent_results UPSERT |
| 9 | `repos/mc-backend/main.py` | 修改 | 注册 agent_results 路由 |

---

## 十四、关键设计决策

### 14.1 A2 不通过 HTTP+SSE，走 NATS dispatch

A2 是纯分析 Agent，无人类交互。由 Orchestrator 调度、通过 NATS 接收上下文、自动完成全部分析。与 A1 的 HTTP+SSE 模型不同。

### 14.2 MCPClient 与 A1 共用

MCPClient 位于 `a1/analyzer/mcp_client.py`，A2 通过 import 共用。修复（URL、响应解析、JWT）对 A1 和 A2 同时生效。

### 14.3 mappers.py 解耦子模块与数据字典

不做子模块内部算法修改——只在外部加翻译层。子模块按自己舒适的格式工作，mappers.py 负责适配数据字典格式。

### 14.4 每个工具独立降级

三个检索工具各自独立三层降级，A 工具 MCP 失败不影响 B/C 继续走 MCP。质量评分基于汇总计数而非单一降级状态。

### 14.5 持久化非阻塞

agent_results 写入失败不阻塞 NATS 事件发布。Orchestrator 的 workflow 主要依赖 NATS payload（已在内存中），agent_results 表是审计和 Gate0 审批页的数据源。写入失败 → Gate0 审批页显示 a2_missing=true → 审批人基于 A1 草案判断。

---

## 十五、审计记录

### v1.0 → v1.1 (critical 审计)

| # | 发现 | 严重度 | 处置 |
|---|------|--------|------|
| C1 | Phase 1 文档标"并行"但代码是顺序 await — 三路检索延迟累加而非并行 | 致命 | 改为 `asyncio.gather()` 并行执行 |
| C2 | `_extract_json_block` 缺字符串/转义状态机 — JSON 值中含 `{` `}` 时括号计数错误 | 致命 | 加入 `in_string` / `escape` 追踪，对齐 A1 `_try_parse_json` |
| C3 | mappers.py docstring 错误声称函数是 "synchronous wrappers"（实为 async） | 严重 | 修正 docstring |
| C4 | `knowledge_package` 变量名与 artifact JSON key 同名，易混淆 | 严重 | 文档加注释说明设计意图 |
| C5 | 测试文档 T-A2-AG-010 子用例 A 的基础分计算缺少设计意图说明 | 严重 | 补充 `mcp_count == 3` 严格全通检查的设计理由 |
| C6 | 测试文档 T-A2-MP-006 引用私有 `_adapt_draft_for_detector` | 中等 | 保留（避免过度工程化），建议后续重构时改测公共 API |
| C7 | 未记录 `_extract_json_block` 实现细节 | 中等 | 新增 §5.5 完整描述字符串/转义状态机 |
| C8 | `_build_risk_rationale` 领域风险字段键名兼容性未说明 | 中等 | §5.2 补充三种字段键名及优先级 |
| C9 | `suggested_approach` 空字符串不加减分的 edge case 未说明 | 中等 | §6.1 补充注释说明 truthiness check 设计意图 |

---
**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.1（critical 审计修复版）
