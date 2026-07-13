# A2 知识分析 Agent — MCP 服务改造设计文档

**版本**: v1.2
**日期**: 2026-07-13
**状态**: 已审计（两轮），待实施
**参考**: [A2-知识分析Agent规格](../Agent规格/A2-知识分析Agent规格.md) · [阶段一-数据字典](../Agent规格/阶段一-数据字典.md) · [系统状态机 v2.4](../系统架构/系统状态机与信息流设计.md)
**审计**: 参见 §八 审计记录（v1.0: C1-C13, v1.2: C14-C21）

---

## 一、现状分析与差距

### 1.1 三层现状对照

| 层次 | 规格要求 (A2 Spec v3.5) | 实际实现 | 差距 |
|------|------------------------|---------|------|
| **MCP 工具定义** | 3 个知识库工具注册在 MCP Gateway | Gateway 有 31 个通用开发工具，**不包含** `search_similar_requirements` / `search_known_issues` / `get_domain_risks` | 工具缺失 |
| **MCP 路由** | ToolRouter 路由到知识库后端 | `tool_router.go:27` 所有工具返回 Mock 响应 | 全量 Mock |
| **A2 调用方式** | 通过 MCP 协议调用知识库 | `a2_knowledge_analyst.py` 使用 `RAGRetriever` 直接调 `POST /api/knowledge/search` (REST)，不经过 MCP | 绕过了 MCP 层 |
| **A2 检索逻辑** | 3 个 MCP 工具独立调用 | `RAGRetriever.search_similar_requirements()` 单一方法，用 `content_type=requirement` 过滤 | 功能未拆分 |
| **A2 产物完整性** | 数据字典 §5.2 要求 `feasibility_assessment` + `conflicts` + `confirmation_checklist` | `execute()` 返回 `knowledge_package`，缺少 `feasibility_assessment` 和 `conflicts` 字段 | 产物不完整 |
| **A2 agent.result NATS payload** | 数据字典 §5.6 要求 `req_id` + `session_id` + `cycle` | `execute()` 返回缺少 `session_id` 和 `cycle`，Orchestrator 无法路由 | **全局路由键缺失** |
| **A2 持久化** | 数据字典 §1.1 A2 自写 `agent_results` | 当前 `execute()` 只返回 dict 不写 DB；`BaseAgentWorker.subscribe_nats()` 也只发布 NATS 不写 DB | **产物不持久化** |
| **A1 MCPClient 可用性** | — | `MCP_GATEWAY_URL` 默认为 `localhost:8100/mcp`，但 Gateway 实际监听 `:8081`，路由在根路径 | A1 MCP 调用同样静默失败 |
| **feasibility.py 输出格式** | 数据字典 §5.2 二维评估 (technical + business) | `FeasibilityAssessor.assess()` 返回一维结构 `{feasible, risk_level, concerns, confidence}` | 字段结构和语义都不匹配 |
| **conflict_detector.py 输出格式** | 数据字典 §5.5 `{id, related_system, type, description, severity}` | `ConflictDetector.detect()` 返回 `{entity, field, attribute, existing_value, new_value, severity, existing_spec_id}` | 字段完全不匹配 |
| **conflict_detector 输入格式** | 需求草案 entities 用 `attributes` (string[]) | detector 期望 `fields` (dict[]) | 检测静默跳过 |

### 1.2 关键源码事实

| 事实 | 源码位置 | 影响 |
|------|---------|------|
| Go MCP Server 返回 `{result: <Route()裸返回值>}` | `mcp_server.go:115-121` | Python 客户端解析逻辑错误（见 §1.3） |
| Python MCPClient 期望 `result.content[0].text` | `mcp_client.py:134-138` | 与 Go 服务端格式不兼容，永远返回 `None` |
| MCPClient 方法用 `isinstance(result, list)` 兜底空列表 | `mcp_client.py:47-48` | 恰好掩盖了上述 bug——对 A1 不可见 |
| Gateway 监听 `:8081`，handler 在 `mux.HandleFunc("/tools/call",...)` | `main.go:23-35,44` | URL 必须为 `http://localhost:8081/tools/call` |
| MCPClient 默认 `localhost:8100/mcp` | `mcp_client.py:19` | 端口和路径都错 |
| Gateway 所有端点需 JWT 认证 | `main.go:24,30` | curl 测试必须先获取 token |
| `NewToolRouter` 只接受 `*ToolRegistry` | `tool_router.go:16` | 需修改构造函数注入后端客户端 |
| A2 当前未调用 `feasibility.py` 和 `conflict_detector.py` | `a2_knowledge_analyst.py:70-137` | 产物缺少数据字典字段 |
| MC Backend `POST /api/knowledge/search` 支持 `content_type` 可选 | `knowledge.py:146` | 可用现有 API，不需新端点 |
| `BaseAgentWorker.subscribe_nats()` 发布 `agent.result.{agent_id}` 后**不做 DB 写入** | `base_worker.py:355-367` | A2 必须自行持久化 `agent_results` |
| `FeasibilityAssessor.assess()` 返回 `{feasible, risk_level, concerns, confidence}` | `feasibility.py:102-107` | 需映射为数据字典 §5.2 的二维结构 |
| `ConflictDetector.detect()` 需要 `existing_specs: list[dict]` 参数 | `conflict_detector.py:39` | 需确定从何处获取已有 spec |
| 需求草案 entities 结构为 `{name, attributes: [...], description}` | 数据字典 §4.2 | detector 访问 `fields` 字段名不匹配 |

### 1.3 MCP 响应格式不兼容的根因

```
Go 服务端返回 (实际):               Python 客户端解析 (期望):
{                                   content = body.get("result", {})
  "jsonrpc": "2.0",                          .get("content", [])
  "id": 1,                          if content and isinstance(content[0], dict):
  "result": [                          text = content[0].get("text", "{}")
    {...},  ← Route() 裸返回              return json.loads(text)
    {...}                            return None  ← 永远走到这里
  ]
}
```

**修复策略**：改 Python 客户端适配 Go 服务端的实际格式。

---

## 二、改造目标

### 2.1 核心目标

1. **修复 A1 MCPClient**：修正 URL/端口，修正响应解析，使其真正可用
2. **MCP Gateway 注册知识库工具**：新增 3 个工具定义
3. **MCP Gateway 路由真实后端**：ToolRouter 将知识工具调用转发到 MC Backend
4. **A2 接入 MCP**：A2 使用 MCPClient + 三层降级链替代直接 REST
5. **补齐 A2 产物**：接入 `feasibility.py` + `conflict_detector.py`，并添加**映射层**对齐数据字典 §5.2-§5.5
6. **补齐全局路由键**：`agent.result.A2` 包含 `req_id` + `session_id` + `cycle`
7. **A2 自行持久化** `agent_results` 表（对齐数据字典 §1.1 和 §3.2）

### 2.2 不改造的部分

- MC Backend 的 `/api/knowledge/search` API — 保持不变
- `feasibility.py` 和 `conflict_detector.py` 的内部评估/检测算法 — 只加映射层
- A1 的 `agent.py` 调用逻辑 — 接口不变，底层 MCPClient 修复后自动生效

---

## 三、改造方案

### 3.1 MCP Gateway — 新增 3 个知识库工具定义

在 `tool_registry.go:registerAll()` 末尾（`project_scaffolding` 之后）追加：

```go
// 32. search_similar_requirements (A1 + A2 共用)
{
    Name:        "search_similar_requirements",
    Description: "语义搜索相似的历史需求，返回按相似度排序的需求列表。",
    InputSchema: InputSchema{
        Type: "object",
        Properties: map[string]PropDef{
            "query":  {Type: "string", Description: "搜索查询文本（需求标题+描述拼接）"},
            "limit":  {Type: "integer", Description: "返回结果数量上限，默认 5"},
        },
        Required: []string{"query"},
    },
},

// 33. search_known_issues (A2 独用)
{
    Name:        "search_known_issues",
    Description: "检索已知问题/Bug/技术债务，按相似度排序。",
    InputSchema: InputSchema{
        Type: "object",
        Properties: map[string]PropDef{
            "query":  {Type: "string", Description: "搜索查询文本"},
            "limit":  {Type: "integer", Description: "返回结果数量上限，默认 10"},
        },
        Required: []string{"query"},
    },
},

// 34. get_domain_risks (A1 + A2 共用)
{
    Name:        "get_domain_risks",
    Description: "获取指定业务领域的历史风险信息。",
    InputSchema: InputSchema{
        Type: "object",
        Properties: map[string]PropDef{
            "domain": {Type: "string", Description: "业务领域标识，如 auth / order / payment"},
        },
        Required: []string{"domain"},
    },
},
```

### 3.2 MCP Gateway — ToolRouter + KnowledgeClient 改造

#### 3.2.1 新建 `backend/knowledge_client.go`

```go
package backend

// KnowledgeClient 封装对 MC Backend 知识库 API 的 HTTP 调用
// 三个方法对应三个 MCP 工具，参数映射如下：
//   search_similar_requirements → POST /api/knowledge/search (content_type=requirement)
//   search_known_issues         → POST /api/knowledge/search (content_type=issue)
//   get_domain_risks            → POST /api/knowledge/search (content_type=doc, query="domain:{domain} risks")

type KnowledgeClient struct { ... }
func NewKnowledgeClient(baseURL string) *KnowledgeClient { ... }
func (kc *KnowledgeClient) SearchSimilarRequirements(args map[string]interface{}) (interface{}, error) { ... }
func (kc *KnowledgeClient) SearchKnownIssues(args map[string]interface{}) (interface{}, error) { ... }
func (kc *KnowledgeClient) GetDomainRisks(args map[string]interface{}) (interface{}, error) { ... }
```

**关键实现细节**：
- HTTP 超时 10s
- 后端不可达时返回 `error`（Go 层面），ToolRouter 通过 `CallToolResponse.Error` 返回
- `search_known_issues` 使用 `content_type=issue`——若无数据返回空列表（正常降级，不报错）
- `get_domain_risks` query 为 `"domain:{domain} risks"`, `content_type=doc`

#### 3.2.2 修改 `tool_router.go`

```go
type ToolRouter struct {
    registry  *ToolRegistry
    client    *http.Client
    knowledge *backend.KnowledgeClient  // 新增
}

func NewToolRouter(registry *ToolRegistry, knowledgeBackendURL string) *ToolRouter {
    return &ToolRouter{
        registry:  registry,
        client:    &http.Client{Timeout: 30 * time.Second},
        knowledge: backend.NewKnowledgeClient(knowledgeBackendURL),
    }
}

var knowledgeToolNames = map[string]bool{
    "search_similar_requirements": true,
    "search_known_issues":         true,
    "get_domain_risks":            true,
}

func (tr *ToolRouter) Route(name string, args map[string]interface{}) (interface{}, error) {
    if _, ok := tr.registry.GetTool(name); !ok {
        return nil, fmt.Errorf("unknown tool: %s", name)
    }
    if knowledgeToolNames[name] {
        return tr.routeKnowledgeBackend(name, args)
    }
    return tr.mockResponse(name, args), nil
}

func (tr *ToolRouter) routeKnowledgeBackend(name string, args map[string]interface{}) (interface{}, error) {
    switch name {
    case "search_similar_requirements":
        return tr.knowledge.SearchSimilarRequirements(args)
    case "search_known_issues":
        return tr.knowledge.SearchKnownIssues(args)
    case "get_domain_risks":
        return tr.knowledge.GetDomainRisks(args)
    default:
        return nil, fmt.Errorf("unknown knowledge tool: %s", name)
    }
}
```

#### 3.2.3 修改 `main.go`

```go
func main() {
    registry := server.NewToolRegistry()
    mcBackendURL := os.Getenv("MC_BACKEND_URL")
    if mcBackendURL == "" {
        mcBackendURL = "http://localhost:8000"
    }
    router := server.NewToolRouter(registry, mcBackendURL)
    // ... 其余不变
}
```

### 3.3 MCP Client（Python 端）— 修复 MCPClient

#### 3.3.1 修复要点

1. **URL 修正**：`localhost:8100/mcp` → `localhost:8081/tools/call`
2. **响应解析修正**：适配 Go 服务端 `{result: <裸数据>}` 格式
3. **参数名统一**：`top_k` → `limit`
4. **新增方法**：`search_known_issues()`

#### 3.3.2 `_call_tool()` 修改

```python
# 修改前：
content = body.get("result", {}).get("content", [])
if content and isinstance(content[0], dict):
    text = content[0].get("text", "{}")
    return json.loads(text)
return None

# 修改后：
data = body.get("result")
if data is not None:
    return data
if "error" in body:
    raise MCPCallError(str(body["error"]))
return None
```

#### 3.3.3 完整修改清单

| 修改点 | 旧值 | 新值 |
|--------|------|------|
| `MCP_GATEWAY_URL` | `http://localhost:8100/mcp` | `http://localhost:8081/tools/call` |
| `search_similar_requirements` 参数 | `{"query": query, "top_k": 5}` | `{"query": query, "limit": 5}` |
| `_call_tool()` 解析逻辑 | `result.content[0].text` | `result` 直接取值 |
| 新增 `search_known_issues()` | 无 | 新增方法 |

### 3.4 A2 Agent — 接入 MCPClient + 补齐产物 + 映射层

#### 3.4.1 改造前

```
A2KnowledgeAnalyst.execute()
    ├── Phase 1: self.rag.search_similar_requirements()  ← REST 直接调
    ├── Phase 2: self.query_dependencies()              ← Neo4j
    ├── Phase 3: self.query_related_prs()               ← 固定返回 []
    └── Phase 4: self.fuse_knowledge()                  ← 仅融合 similar_reqs
    → 返回 {knowledge_package, quality_score}            ← 缺字段，缺持久化
```

#### 3.4.2 改造后

```
A2KnowledgeAnalyst.execute(req_id, context_package)
    │
    ├── Phase 1: MCP 知识检索 (并行，每个工具独立降级)
    │   ├── _retrieve_similar_requirements(draft)
    │   │   └── MCPClient → Gateway(:8081) → MC Backend(:8000)
    │   │       └── 失败 → RAGRetriever 直接调 /api/knowledge/search
    │   │       └── 仍失败 → 静态 KB fallback
    │   ├── _retrieve_known_issues(draft)          ← 同上三层降级
    │   └── _retrieve_domain_risks(domain)         ← 同上三层降级
    │   → 每个方法返回 (results, level: "mcp"|"direct"|"fallback"|"empty")
    │
    ├── Phase 2: Neo4j 依赖查询 (不变)
    │
    ├── Phase 3: 关联 PR/Issue 查询 (不变)
    │
    ├── Phase 4: 可行性评估 ← 接入 feasibility.py + 映射层 (NEW)
    │   ├── _build_feasibility_assessment(draft, domain_risks)
    │   │   └── FeasibilityAssessor.assess() → 映射为数据字典 §5.2 二维结构
    │   │       └── LLM 不可用 → 启发式映射（只用 feasibility.py 结果）
    │
    ├── Phase 5: 冲突检测 ← 接入 conflict_detector.py + 映射层 (NEW)
    │   ├── _build_conflicts(draft, similar_reqs)
    │   │   └── 从 similar_reqs 提取已有 spec → ConflictDetector.detect()
    │   │       → 映射为数据字典 §5.5 字段
    │   │       └── 无已有 spec → 返回空列表
    │
    ├── Phase 6: LLM 知识融合 (context 包含 MCP + 可行性 + 冲突)
    │   ├── _build_confirmation_checklist(draft, feasibility, conflicts, similar_reqs)
    │   │   └── LLM 基于全文上下文生成待确认清单
    │   │       └── LLM 不可用 → 模板规则生成
    │
    ├── Phase 7: 组装产物 (对齐数据字典 §5.2)
    │
    ├── Phase 8: 持久化 agent_results ← 自写 DB (NEW)
    │   └── INSERT INTO agent_results (req_id, agent_key='A2', cycle, status, artifact)
    │
    └── Phase 9: 发布 agent.result.A2 ← 包含 session_id + cycle
```

#### 3.4.3 构造函数变更

```python
def __init__(self, nats_url: str = "nats://localhost:4222"):
    super().__init__(self.agent_id, self.agent_type, nats_url)
    # MCPClient 一级检索通道
    from a1.analyzer.mcp_client import MCPClient
    self.mcp = MCPClient()
    # RAGRetriever 降级为 L2/L3
    from a2.rag_retriever import RAGRetriever
    self.rag = RAGRetriever(api_base_url=MC_BACKEND_URL)
    # 可行性评估 + 冲突检测
    from a2.feasibility import FeasibilityAssessor
    from a2.conflict_detector import ConflictDetector
    self.feasibility_assessor = FeasibilityAssessor()
    self.conflict_detector = ConflictDetector()
    self.neo4j_available = bool(NEO4J_URL)
    # DB 持久化用的连接池 (延迟初始化)
    self._db_pool = None
```

#### 3.4.4 降级链设计

每个检索方法独立三层降级，返回 `(results, level)`：

```
L1: MCP Gateway (JSON-RPC, 5s 超时)
│   成功 → ("mcp", results)
│   失败 ↓
L2: MC Backend REST (直接, 10s 超时)
│   成功 → ("direct", results)
│   失败 ↓
L3: 静态知识库 (关键词匹配)
    → ("fallback", results)  或  ("empty", [])
```

**质量评分**基于三个工具的 level 汇总：

```python
def _calc_quality_score(retrieval_levels: list[str], knowledge_package: dict) -> float:
    mcp_count = retrieval_levels.count("mcp")
    direct_count = retrieval_levels.count("direct")
    fallback_count = retrieval_levels.count("fallback")

    if mcp_count == 3:       base = 0.6
    elif mcp_count >= 1:     base = 0.4
    elif direct_count >= 1:  base = 0.3
    elif fallback_count >= 1:base = 0.15
    else:                    base = 0.05  # 全部 empty

    # 内容加成
    base += min(len(knowledge_package.get("similar_requirements", [])) * 0.08, 0.25)
    if knowledge_package.get("suggested_approach"):
        base += 0.10
    if knowledge_package.get("risks"):
        base += min(len(knowledge_package["risks"]) * 0.03, 0.10)

    return round(min(base, 1.0), 3)
```

#### 3.4.5 映射层：feasibility.py → 数据字典 §5.2

`FeasibilityAssessor.assess(draft)` 输出 `{feasible, risk_level, concerns, confidence}`，需映射为：

```python
async def _build_feasibility_assessment(self, draft: dict, domain_risks: list) -> dict:
    """映射 feasibility.py 一维输出 → 数据字典 §5.2 二维结构。
    
    技术可行性: 用 assessor 原始结果
    业务可行性: 用 domain_risks + LLM 推理（LLM 不可用时用 heuristic 模板）
    """
    # 调用现有评估器
    raw = await self.feasibility_assessor.assess(draft)

    technical = {
        "feasible": raw["feasible"],
        "assessment": "; ".join(raw["concerns"]) if raw["concerns"] else "技术栈支持，无明显技术阻碍",
        "concerns": raw["concerns"]
    }

    # 业务可行性: 结合 domain_risks + LLM
    business = await self._assess_business_feasibility(draft, domain_risks)

    # risk_rationale: 技术风险 + 领域风险综合
    risk_rationale = self._build_risk_rationale(raw, domain_risks)

    return {
        "technical": technical,
        "business": business,
        "risk_level": raw["risk_level"],
        "risk_rationale": risk_rationale,
    }


async def _assess_business_feasibility(self, draft: dict, domain_risks: list) -> dict:
    """业务可行性评估。LLM 可用时用 LLM；不可用时用 heuristic 模板。"""
    title = draft.get("title", "")
    domain = draft.get("domain", "general")

    risk_text = "\n".join(
        f"- {r.get('risk_name', r.get('risk', ''))}: {r.get('description', '')}"
        for r in (domain_risks or [])[:5]
    ) or "无已知领域风险"

    prompt = (
        f"需求: {title}\n领域: {domain}\n已知风险:\n{risk_text}\n"
        "判断此需求在当前业务方向上是否可行。返回 JSON: "
        '{"feasible": bool, "assessment": "简要评估", "concerns": ["顾虑1"]}'
    )

    try:
        llm_result = await self.call_llm(
            [{"role": "user", "content": prompt}],
            task_type="knowledge_analysis", req_id="", temperature=0.3, max_tokens=500,
        )
        if llm_result:
            data = json.loads(self._extract_json_block(llm_result))
            return {"feasible": data.get("feasible", True),
                    "assessment": data.get("assessment", "LLM 评估完成"),
                    "concerns": data.get("concerns", [])}
    except Exception as e:
        logger.warning(f"[A2] Business feasibility LLM failed: {e}")

    # 降级: heuristic 模板
    return {
        "feasible": True,
        "assessment": "业务可行性评估通过（启发式）",
        "concerns": ["LLM 不可用，未进行深度业务分析"] if not domain_risks else []
    }
```

> `_extract_json_block(text)` 从 LLM 返回值中提取 JSON——因为 `call_llm()` 不支持的 `response_format`，不能强制 JSON 模式。后续如果 LLM Provider 支持 tool-use，可改用 structured output。

#### 3.4.6 映射层：conflict_detector.py → 数据字典 §5.5

```python
async def _build_conflicts(self, draft: dict, similar_reqs: list) -> list[dict]:
    """冲突检测 → 映射为数据字典 §5.5 格式。
    
    从 similar_reqs 中提取已有 spec 作为 ConflictDetector.detect() 的 existing_specs 参数。
    若 similar_reqs 中无 entities 结构 → 返回空列表。
    """
    # 从相似需求中提取有实体定义的 spec
    existing_specs = []
    for r in (similar_reqs or [])[:5]:
        meta = r.get("metadata", {})
        if meta.get("entities"):
            existing_specs.append({
                "id": r.get("content_id", ""),
                "entities": meta["entities"]  # 数据字典格式: [{name, attributes, description}]
            })

    if not existing_specs:
        logger.debug("[A2] No existing specs with entities for conflict detection")
        return []

    # 需求草案 entities 格式: [{name, attributes: [...string], description}]
    # ConflictDetector 期望: entities[].fields[{name, type, ...}]
    # 适配: 将 attributes 的 string 列表转为 fields 格式
    adapted_draft = self._adapt_draft_for_detector(draft)
    adapted_specs = [self._adapt_spec_for_detector(s) for s in existing_specs]

    raw = await self.conflict_detector.detect(adapted_draft, adapted_specs)

    # 映射 detector 输出 → 数据字典 §5.5
    conflicts = []
    for i, c in enumerate(raw.get("conflicts", [])):
        conflicts.append({
            "id": f"conflict_{i+1}",
            "related_system": c.get("entity", ""),
            "type": self._map_conflict_type(c),
            "description": (
                f"'{c.get('entity', '')}'的'{c.get('field', '')}'字段的{c.get('attribute', '')}"
                f"属性：现有值'{c.get('existing_value', '')}' vs 新值'{c.get('new_value', '')}'"
            ),
            "severity": c.get("severity", "low"),
        })

    return conflicts


def _adapt_draft_for_detector(self, draft: dict) -> dict:
    """将数据字典格式 entities[{name, attributes:[string], desc}] → detector 格式 [{name, fields:[dict]}]"""
    entities = draft.get("entities", [])
    adapted = []
    for ent in entities:
        attrs = ent.get("attributes", [])
        fields = []
        for attr_name in attrs:
            fields.append({"name": attr_name, "type": "unknown", "required": False})
        adapted.append({"name": ent.get("name", ""), "fields": fields})
    return {"entities": adapted}

# 同样 _adapt_spec_for_detector 处理 spec 中的 entities 字段

@staticmethod
def _map_conflict_type(c: dict) -> str:
    """映射 detector 输出到数据字典 §5.5 type 枚举"""
    attr = c.get("attribute", "")
    if attr in ("type", "format", "precision", "scale"):
        return "data_model"
    if attr == "enum_values":
        return "business_flow"
    return "field_naming"
```

#### 3.4.7 `status` 判定逻辑

对齐数据字典 §3.2 的 `agent_results.status` 三态：

```python
def _determine_status(retrieval_levels: list[str]) -> str:
    """判定 A2 产物的 agent_results.status 值。
    
    - 'completed': 有至少一个有效检索结果，或启发式替代完整
    - 'empty':     MCP 全部失败 + REST 全部失败 + 静态 KB 无数据
    - 'skipped':   仅由 Orchestrator 写入（A2 超时），A2 不自写此值
    """
    if all(lvl == "empty" for lvl in retrieval_levels):
        return "empty"
    return "completed"
```

#### 3.4.8 持久化 agent_results

数据字典 §1.1 规定 A2 自行写入 `agent_results`。新增 Phase 8：

```python
async def _persist_agent_result(
    self, req_id: str, session_id: str, cycle: int,
    status: str, artifact: dict,
) -> None:
    """A2 自行写入 agent_results 表。
    
    通过 MC Backend API 写入，而非直连 DB（遵循项目架构：Agent → MC Backend → DB）。
    失败时记录日志但不阻塞——NATS 事件仍会发布。
    """
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
            if resp.status_code not in (200, 201):
                logger.warning(f"[A2] Failed to persist agent_result: HTTP {resp.status_code}")
            else:
                logger.info(f"[A2] Persisted agent_result (cycle={cycle}, status={status})")
    except Exception as e:
        logger.warning(f"[A2] Failed to persist agent_result: {e} (non-fatal, NATS event still published)")
```

> **注意**：如果 MC Backend 尚无 `POST /api/agent_results` 端点，需要在 `mc-backend/api/` 中新增。如果不方便，备选方案是通过 NATS `artifact.produced.A2` 事件携带完整产物，由 K14 Knowledge Keeper 持久化。本设计首选 MC Backend API（对齐数据字典 §1.1 职责归属）。

#### 3.4.9 最终返回结构 — 完整对齐

```python
async def execute(self, req_id: str, context_package: dict) -> dict:
    # ... Phase 1-7 ...

    # Phase 8: 持久化
    session_id = context_package.get("session_id", "")
    cycle = context_package.get("cycle", 0)
    retrieval_levels = [sim_level, issues_level, risks_level]
    status = self._determine_status(retrieval_levels)
    quality_score = self._calc_quality_score(retrieval_levels, knowledge_package)

    agent_artifact = {
        "feasibility_assessment": feasibility,
        "confirmation_checklist": checklist,
        "conflicts": conflicts,
        "quality_score": quality_score,
    }
    await self._persist_agent_result(req_id, session_id, cycle, status, agent_artifact)

    # Phase 9: 发布 agent.result.A2 (对齐数据字典 §5.6)
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
```

---

## 四、文件变更清单

### 4.1 新建文件

| 文件 | 说明 |
|------|------|
| `repos/mcp-gateway/backend/knowledge_client.go` | KnowledgeClient — 封装 MC Backend HTTP 调用 |
| `repos/agent-workers/a2/mappers.py` | 数据映射层 — feasibility/conflict_detector 输出 → 数据字典格式 |

### 4.2 修改文件

| # | 文件 | 修改内容 | 复杂度 |
|---|------|---------|--------|
| 1 | `repos/mcp-gateway/server/tool_registry.go` | `registerAll()` 追加 3 个知识库工具 | 低 |
| 2 | `repos/mcp-gateway/server/tool_router.go` | 添加 `knowledge` 字段；`NewToolRouter` 加参数；`Route()` 分流 | 中 |
| 3 | `repos/mcp-gateway/main.go` | `NewToolRouter` 传入 `MC_BACKEND_URL` | 低 |
| 4 | `repos/agent-workers/a1/analyzer/mcp_client.py` | 修正 URL、`_call_tool()` 解析、参数 `top_k`→`limit`、新增 `search_known_issues()` | 低 |
| 5 | `repos/agent-workers/a2_knowledge_analyst.py` | 构造函数注入 MCPClient+FeasibilityAssessor+ConflictDetector；重写 Phase 1（三层降级）；新增 Phase 4-9（可行性+冲突+融合+持久化+发布）；返回结构完整对齐数据字典 §5.6 | 中 |
| 6 | `repos/mc-backend/api/agent_results.py` | 新增 `POST /api/agent_results` 端点供 A2 持久化（如不存在） | 低 |

### 4.3 不改的文件

| 文件 | 理由 |
|------|------|
| `repos/agent-workers/a1/agent.py` | 接口不变，底层 MCPClient 修复后自动生效 |
| `repos/agent-workers/a2/feasibility.py` | 内部算法不变，映射层解耦 |
| `repos/agent-workers/a2/conflict_detector.py` | 内部算法不变，映射层 + 适配层解耦 |
| `repos/mc-backend/api/knowledge.py` | 现有 `/api/knowledge/search` 完全满足需求 |
| `doc/Agent规格/A2-知识分析Agent规格.md` | 规格已对齐 |
| `doc/Agent规格/阶段一-数据字典.md` | 数据规范无变化 |

---

## 五、实施步骤

### Step 1: 修复 MCPClient（无依赖，先修基础设施）

1. 修正 `mcp_client.py`: URL `localhost:8100/mcp` → `localhost:8081/tools/call`
2. 修正 `_call_tool()` 解析逻辑：`result.content[0].text` → `result` 直接取值
3. 参数 `top_k` → `limit`
4. 新增 `search_known_issues()` 方法
5. 验证：启动 Gateway，用带 JWT token 的 curl 调用 `/tools/call`，确认返回非 None

### Step 2: MCP Gateway 注册知识工具 + KnowledgeClient

1. 在 `tool_registry.go` 追加 3 个工具定义（编译验证：`go build .`）
2. 新建 `backend/knowledge_client.go`
3. 修改 `tool_router.go`: 添加分流逻辑
4. 修改 `main.go`: 传入 `MC_BACKEND_URL`
5. 验证：`GET /tools/list` 返回 34 个工具

### Step 3: MCP Gateway 知识路由连通性测试

```bash
TOKEN=$(curl -s -X POST http://localhost:8081/auth/token \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"test","req_id":"test-001"}' | jq -r '.token')

curl -s -X POST http://localhost:8081/tools/call \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"search_similar_requirements","arguments":{"query":"订单管理","limit":3}},"id":1}' | jq .
```

预期：`{"jsonrpc":"2.0","id":1,"result":[...]}`

### Step 4: 新建 `mappers.py`

1. `_build_feasibility_assessment()` — feasibility.py 输出 → 数据字典 §5.2
2. `_build_conflicts()` — conflict_detector.py 输出 → 数据字典 §5.5，含 `_adapt_draft_for_detector()`
3. `_assess_business_feasibility()` — LLM 优先，启发式降级
4. 单元测试：验证映射前/后格式

### Step 5: 新增 MC Backend `POST /api/agent_results` 端点

1. 新建 `repos/mc-backend/api/agent_results.py`（如不存在）
2. 接收 `{req_id, agent_key, cycle, status, artifact}` → INSERT/UPDATE `agent_results`
3. 验证：curl POST 后查询 DB 确认写入

### Step 6: A2 Agent 重构

1. 修改构造函数，注入 MCPClient + FeasibilityAssessor + ConflictDetector
2. 重写 Phase 1 为三个独立三层降级方法
3. 新增 Phase 4（可行性+映射）、Phase 5（冲突+映射+适配）、Phase 6（LLM 融合+确认清单）、Phase 7（组装产物）、Phase 8（持久化）、Phase 9（发布）
4. `execute()` 返回完整对齐数据字典 §5.6
5. 更新 `test_knowledge_analyst.py`：新增降级链测试、映射层测试、产物结构验证
6. 运行：`pytest repos/agent-workers/a2/test_knowledge_analyst.py -v`

### Step 7: 端到端验证

1. 全链路：MC Backend(8000) → MCP Gateway(8081) → A2 Agent
2. 通过 NATS 发布 `context.ready.A2`，检查日志
3. 正常路径：`[A2] MCP retrieval: similar_reqs=mcp, known_issues=mcp, domain_risks=mcp`
4. 降级 L2：停 Gateway → direct；降级 L3：停 Backend → fallback
5. 查询 DB：`agent_results WHERE agent_key='A2'` 含 `feasibility_assessment`(technical+business), `conflicts`(id+related_system+type+description+severity), `confirmation_checklist`(id+category+item+priority), `quality_score`

---

## 六、设计决策记录

### D1: MCP 响应格式适配——改 Python 端

Go 端 `result: result` 是最简透传。Python 端改一处解析逻辑，Python 端 `isinstance` 兜底已验证可行。

### D2: 映射层解耦 `feasibility.py` / `conflict_detector.py`

现有模块的输入/输出格式与数据字典不一致，但内部算法（关键词匹配、字段比对）可用。新增 `mappers.py` 做格式适配——不改内部逻辑，只加翻译层。

### D3: 每个工具独立降级

三个 MCP 工具并行但**独立**——A 工具 MCP 失败不影响 B/C 继续走 MCP。质量评分基于汇总计数，消除并发竞争。

### D4: A2 自行持久化 agent_results

数据字典 §1.1 明确 A2 写入 `agent_results`。通过 MC Backend API 写入（非直连 DB），遵循项目架构约束。失败不阻塞——NATS 事件仍发布。

### D5: `search_known_issues` 的 `content_type=issue`

MC Backend `knowledge_embeddings` 可能暂无此类型数据。返回空列表正常降级，后续可扩展独立索引 pipeline。

### D6: 需求草案 entities.attributes → detector fields 适配

`conflict_detector` 期望 `fields[{name, type, ...}]`，需求草案是 `attributes[string[]]`。映射时用属性名当字段名、`type=unknown` 作为兜底——检测能力受限但不会静默跳过。

---

## 七、验证清单

| # | 验证项 | 方法 | 预期 |
|---|-------|------|------|
| 1 | Gateway 注册 34 个工具 | `curl -H "Auth: Bearer $T" localhost:8081/tools/list` | 含 3 个知识工具 |
| 2 | 知识工具返回真实数据 | Step 3 curl 命令 | 非 Mock，含 pgvector 结果或空列表 |
| 3 | A1 MCPClient 不再静默失败 | A1 agent 日志 | MCP 检索有数据返回 |
| 4 | A2 通过 MCP 获取知识（正常路径） | 触发 A2，检查日志 | 三个工具均 `level=mcp`，quality_score >= 0.6 |
| 5 | MCP Gateway 宕机 → L2 降级 | 停 Gateway，触发 A2 | 显示 `level=direct`，结果来自 RAGRetriever |
| 6 | MC Backend 宕机 → L3 降级 | 停 Backend，触发 A2 | 显示 `level=fallback`，quality_score < 0.4 |
| 7 | 全部降级且无数据 → status='empty' | 停所有后端，无缓存 | agent_results.status = 'empty' |
| 8 | agent_results.A2 结构对齐 | 查询 DB | 含 feasibility(technical+business)+conflicts(§5.5)+checklist(§5.4)+quality_score |
| 9 | agent.result.A2 payload 含全局路由键 | NATS 消息 | 含 req_id + session_id + cycle |
| 10 | 映射层格式验证 | 单元测试 | feasibility 二维结构；conflicts 字段名对齐数据字典 |
| 11 | 现有测试通过 | `pytest repos/agent-workers/a2/test_knowledge_analyst.py -v` | 全部通过 |

---

## 八、审计记录

### 第一轮审计 (v1.0 → v1.1)

| # | 发现 | 严重度 | 处置 |
|---|------|--------|------|
| C1 | MCP 响应格式 Go/Python 不兼容 | 致命 | Python 端 `_call_tool()` 解析逻辑 |
| C2 | `knowledgeTools` 含未注册的 `get_tech_stack_recommendations` | 致命 | 从分流 map 移除 |
| C3 | `NewToolRouter` 签名变更未涉及 main.go | 严重 | §3.2.3 补充 |
| C4 | 文档自相矛盾（改 vs 不改 MCPClient） | 严重 | 明确为修改 |
| C5 | MCP_GATEWAY_URL 默认值错误 | 严重 | Step 1 修正 |
| C6 | `_mcp_healthy` 单 bool 并发竞争 | 严重 | 每个工具独立 level |
| C7 | get_domain_risks 是否需要新端点 | 中等 | 用现有 `/api/knowledge/search` |
| C8 | search_known_issues 用 content_type=spec | 中等 | 改为 `content_type=issue` |
| C9 | feasibility.py 和 conflict_detector.py 未接入 | 中等 | 新增 Phase 4/5 |
| C10 | 测试命令缺 jsonrpc 字段和 JWT | 中等 | Step 3 完整 curl |
| C11 | curl 无 JWT 会被 401 | 中等 | 先获取 token |
| C13 | 文件路径建议 | 低 | 放在 `backend/` |

### 第二轮审计 (v1.1 → v1.2)

| # | 发现 | 严重度 | 处置 |
|---|------|--------|------|
| C14 | agent.result.A2 缺少 session_id 和 cycle | 致命 | §3.4.9 完整对齐数据字典 §5.6 |
| C15 | feasibility.py 输出与数据字典 §5.2 不匹配 | 致命 | §3.4.5 新增映射层 `_build_feasibility_assessment()` |
| C16 | conflict_detector.py 输出与数据字典 §5.5 不匹配 | 致命 | §3.4.6 新增映射层 `_build_conflicts()` |
| C17 | conflict_detector 需要 existing_specs 参数 | 严重 | §3.4.6 从 similar_reqs metadata 中提取 |
| C18 | status='empty' 判定条件不明确 | 严重 | §3.4.7 `_determine_status()` |
| C19 | 谁负责写入 agent_results | 严重 | §3.4.8 A2 自写 DB（MC Backend API） |
| C20 | LLM 不可用时可行性评估无降级 | 中等 | §3.4.5 `_assess_business_feasibility()` 启发式降级 |
| C21 | entities 格式不匹配 (attributes vs fields) | 低 | §3.4.6 `_adapt_draft_for_detector()` |

---

**文档维护**: AI-Native 团队
**最后更新**: 2026-07-13
**版本**: v1.2（两轮审计修正）
