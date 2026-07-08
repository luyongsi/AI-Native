# Orchestrator 改造 Spec

> **Status**: Final (v1.1, 2026-07-06)
> **Date**: 2026-07-06
> **Scope**: `repos/orchestrator/`, `repos/mc-backend/`, `repos/agent-workers/`, `.ai-native/` (2 files)

---

## 当前状态速查

```
✅ 正常的:
  - 12 状态机 + Transition Table 正确
  - dispatch_agent → NATS → Agent → Bridge → Signal 链路完整
  - A3/A4 并行分发 + rework feedback 注入已实现
  - gate_state.py + gate_routes.py + SLA tracker 已实现

🔴 致命:
  - Gate wait_condition 永久阻塞，SLA 超时后 Workflow 不知道
  - self._escalate flag 设了但没人读（Agent 超时静默消失）
  - dispatch_agent 截断 context 到 5000 字符（≈1250 tokens），Agent 拿不到足够信息
  - 除 A4 外所有 Agent 产物只存在于 Workflow 内存，未持久化到 DB
  - Gate decisions 存储/传输路径缺失（v1.1 新增）

🟡 功能缺口:
  - notify_mc 只发 NATS，不写 DB — 前端状态丢失
  - build_context 仅截断当前 spec 前 300 字符 — 没有上游产物、知识库、环境信息
  - Agent 侧各有一行暴力截断（A12: [:4000], A4: [:2000]）— 信息丢失且不可控
  - Circuit Breaker 3000+ 行完整实现但一行未接入
  - A2 知识分析师不在状态机主链路中
  - A4 持久化路径与 artifact_context 读取路径不匹配 (v1.1 新增)

⚪ 架构债（本 spec 不做）:
  - .ai-native/ 三层目录（除 project-config.yaml + context-budget.yaml 外）
  - SkillLoader / MCPClient / knowledge-base-mcp
  - A9/A10/A11/A13/K14/K15 stub 替换
  - Agent function calling / 懒加载 _refs 按需拉取
```

---

## 一、整体架构：五层上下文 + 分层压缩

### 1.1 上下文五层模型

```
ContextPackage
├── requirement_context       ← 需求自身 (DB: requirements 表)
│   ├── title, description, source_payload, acceptance_criteria
│   ├── spec_sections (需求文档章节，含历史版本)
│   └── analysis (A1 产出: 实体、领域、风险点、优先级)
│
├── artifact_context          ← 上游 Agent 产出物 (DB: requirements.spec.artifacts JSONB)
│   ├── A1 → analysis       │  A6 → dag
│   ├── A2 → knowledge_brief│  A7 → test_cases, test_outline
│   ├── A3 → prototype_url  │  A9 → code_diff_summary
│   ├── A4 → openapi, erd,  │  A11→ test_report
│   │        state_machine  │  A12→ review_report, security_findings
│   └── A5 → review_scores, │  A13→ release_notes
│            issues          │
│
├── knowledge_context         ← 知识库检索 (context-builder :8300 或直接查表)
│   ├── similar_requirements  历史相似需求及最终产出摘要
│   ├── relevant_code         相关模块代码片段
│   ├── best_practices        设计/编码最佳实践文档
│   ├── known_issues          历史 bug 记录、常见坑
│   └── dependency_graph      相关模块上下游依赖
│
├── environment_context       ← 项目/环境配置 (.ai-native/project-config.yaml)
│   ├── project (name, repo, branch, tech_stack, claude_md_content, coding_conventions)
│   ├── deployment (dev/staging/production URLs, db_connections)
│   └── integration (issue_tracker, ci_cd, monitoring)
│
├── decisions_context         ← Gate 审批决策 (DB: requirements.spec.decisions JSONB)
│   ├── resolved               已审批的架构决策 {decision_id: selected_option}
│   ├── source_gates           来源 Gate 级别 [1, 2]
│   └── approved_at            审批时间戳
│
└── rework_context            ← 返工回路 (Workflow 实例状态)
    ├── round_number (1..MAX_REWORK)
    ├── previous_feedback (上一轮的失败原因、具体问题列表)
    ├── previous_result (上一轮的原始产出，不做 diff)
    ├── gate_reject_reason
    └── suggestion (改进方向)
```

**注意**: `artifact_context` 的数据来源于 `requirements.spec.artifacts` JSONB——Agent 产出的持久化是 T5 的一部分。

### 1.2 关键前提：Agent 产物必须持久化

当前只有 A4 直接写 `requirements.spec`。其他 Agent（A1、A2、A5、A6、A7、A9、A11、A12、A13）的产出通过 NATS 传回 Workflow 后只存在 Workflow 内存中，不写入 DB。没有持久化，下游 Agent 的 `build_context` 就取不到上游产物。

因此增加 **T5: Agent 产物持久化 Activity**：

```python
# orchestrator/activities/store_agent_result.py (新增)

@activity.defn(name="store_agent_result")
async def store_agent_result(req_id: str, agent_id: str, result: dict) -> dict:
    """将 agent 产出写入 requirements.spec.artifacts JSONB。"""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE requirements
            SET spec = jsonb_set(
                COALESCE(spec, '{}'::jsonb),
                '{artifacts,' || $2 || '}',
                $3::jsonb,
                true
            ),
            updated_at = NOW()
            WHERE id = $1::uuid
        """, req_id, agent_id, json.dumps(result))
        return {"ok": True, "req_id": req_id, "agent_id": agent_id}

# requirement_workflow.py — 在 _dispatch_and_wait 成功后调用:
if self._agent_result is not None:
    await workflow.execute_activity(
        store_agent_result,
        args=[req_id, agent_id, self._agent_result],
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=_DEFAULT_RETRY,
    )
```

A4 不需要调用（它自己已经直接写了），所以 Workflow 可以用 `_AGENTS_THAT_PERSIST = {"A4"}` 跳过。

### 1.3 分层压缩策略

暴力截断丢失尾部全部信息。改用**分层压缩**：

```
Raw Context (8000+ tokens)
  │
  ├─ 1. 分层标记 (Tier Assignment)
  │      head: 必须完整 (requirement title, acceptance criteria, rework issues)
  │      mid:  可压缩 (OpenAPI 全量, ERD 全量, DAG, 代码片段)
  │      tail: 可丢弃 (历史需求参考, 最佳实践全文, 相似需求原始文本)
  │
  ├─ 2. 去重 (Deduplication) — 复用 context-builder Deduplicator
  │      相似度 > 85% 的重复上下文项，只留 relevance 最高的
  │
  ├─ 3. 按层压缩
  │      head → 完整保留
  │      mid →
  │        - 代码: 保留签名+注释+装饰器，丢弃函数体（已有 CodeCompressor）
  │        - 文档: LLM 摘要 (需显式开启)
  │        - API/ERD: 结构化提取（保留 endpoint summary + 字段名+类型+FK，丢全量 schema）
  │        - DAG: 保留 node id+title+edges，丢 estimated_hours/details
  │      tail → 保留标题+一行摘要+检索 ID（未来 Agent 支持 function calling 时按需拉取）
  │
  └─ 4. Token 预算检查
        超出 → 从 tail 开始逐级丢弃 → 仍超出 → 压缩 mid 中最大项 → 仍超出 → 记录 warning
```

**各类型内容压缩估算**:

| 内容类型 | 原始大小 | 压缩策略 | 压缩后 | 压缩率 |
|---------|---------|---------|--------|-------|
| OpenAPI spec | 3000-5000 | 结构化提取: endpoint summary + params + 状态码描述 | 800-1200 | 70% |
| ERD | 1500-3000 | 结构化提取: 表名+列名+类型+FK | 400-800 | 70% |
| DAG | 1000-2000 | 保留 node id+title+edges | 300-500 | 70% |
| A5 评审结果 | 500-1500 | 结构化提取: 只保留不通过的项+得分 | 200-400 | 60% |
| 代码 diff | 2000-8000 | 保留文件列表+每文件前三行变更+统计 | 500-1000 | 85% |
| 测试报告 | 1000-3000 | LLM 摘要: 通过/失败统计+关键失败 | 300-500 | 80% |
| 历史需求 | 1000-3000 | LLM 摘要: 做了什么+结果+关联 | 150-300 | 85% |
| CLAUDE.md | 2000-5000 | LLM 摘要: 编码规范+技术栈+关键约束 | 500-1000 | 75% |
| 知识库片段 | 各 200-800 | 去重后按 relevance 取 top-N | 原始 | 0-50% |

综合: 8000 tokens 原始 context → 压缩后约 **2000-4000 tokens**。

### 1.4 压缩对 LLM Prompt Cache 的影响

**结论：不影响命中率。核心原因——每个 Agent 调用的 context 内容本身就不一样。**

LLM API（Anthropic/DeepSeek）的 prompt cache 按前缀匹配：

```
┌─────────────────────────────────────────────────────────┐
│ System Prompt (固定)   │ Context (每次不同) │ User Msg  │
│ ← cache 命中 →        │ ← 始终 miss →     │           │
└─────────────────────────────────────────────────────────┘
```

- **System prompt**：每个 Agent 的 system prompt 是固定的模板（如 A1 的"你是一个需求分析师..."），这部分**前缀恒定**，cache 一定命中。
- **Context body**：每次调用的 `req_id`、artifact、知识库结果都不同，**不论是否压缩都必然 cache miss**。
- **压缩本身**：结构化提取（纯 Python 字符串处理）不涉及 LLM 调用，延迟可忽略（<50ms）。

**LLM 摘要对 cache 的影响**：LLM 摘要（`llm_summarize_enabled: true`）会增加一次额外的 LLM 调用。但这次调用只处理**项目级静态内容**（如 CLAUDE.md），且结果可以缓存。默认关闭 LLM 摘要，开启后对动静分离的内容（CLAUDE.md、编码规范）缓存摘要结果。

**正确的缓存策略**：

```
内容类型                  │ 变动频率   │ 压缩方式       │ 缓存策略
─────────────────────────┼───────────┼───────────────┼──────────────────
CLAUDE.md / coding_conventions│ 极少   │ LLM 摘要       │ 磁盘缓存，文件 mtime 校验
project-config.yaml       │ 极少     │ 直接引用       │ 进程内存，5min TTL
知识库搜索结果             │ 每次不同  │ 去重+top-N     │ 不缓存（内容依赖 query）
Agent 产物 (artifact)     │ 每个 req 不同│结构化提取  │ 不缓存（内容依赖 req_id）
Rework 信息               │ 每次不同  │ 直接引用       │ 不缓存
```

> **总结**: 上下文压缩对 prompt cache 命中率没有影响（context 本身必然 miss），但 LLM 摘要可以缓存项目级静态内容的摘要结果，减少额外的 LLM 调用开销。

---

## 二、可配置 Token 预算

### 2.1 配置文件

```yaml
# .ai-native/context-budget.yaml

# 基于模型窗口的百分比预算
# 换更大模型时自动按比例放大
model_window: 200000

budgets:
  analyzing:        { pct: 1.5, max: 3000 }
  designing:        { pct: 3.0, max: 6000 }
  reviewing:        { pct: 4.0, max: 8000 }
  decomposing:      { pct: 3.0, max: 6000 }
  developing:       { pct: 5.0, max: 10000 }
  testing:          { pct: 3.0, max: 6000 }
  reviewing_code:   { pct: 3.0, max: 6000 }
  releasing:        { pct: 3.0, max: 6000 }
  rework:           { pct: 6.0, max: 12000 }

# 压缩策略开关
compression:
  dedup_enabled: true
  dedup_threshold: 0.85
  llm_summarize_enabled: false       # 默认关闭，打开会增加额外 LLM 调用
  llm_summarize_model: "deepseek"
  structured_extract_enabled: true   # 纯 Python 处理，无额外 LLM 调用
  lazy_load_enabled: false           # 需要 Agent function calling，暂时关闭

# 静态内容摘要缓存
summary_cache:
  enabled: true                      # CLAUDE.md 等静态内容的摘要结果磁盘缓存
  ttl_minutes: 120                   # 120 分钟过期
  cache_dir: ".ai-native/cache"

# 传输链路配置
transport:
  dispatch_agent_max_chars: 65536    # 从 5000 扩大到 64K (≈16K tokens)
  agent_side_auto_compress: true     # Agent 侧启用 ContextCompressionService
```

### 2.2 文件路径解析

`build_context` Activity 通过环境变量定位配置文件：

```python
_CONFIG_DIR = Path(os.environ.get("AI_NATIVE_CONFIG_DIR", ".ai-native"))

def _load_yaml(filename: str) -> dict:
    path = _CONFIG_DIR / filename
    if path.exists():
        import yaml
        return yaml.safe_load(path) or {}
    return {}
```

### 2.3 各状态完整注入规则

A2（知识分析师）不在主状态机中——A2 作为 A1 的辅助调用，不需要独立状态。`build_context` 按 `target_agent` 参数区分上下文：

```
状态: analyzing (A1 需求分析) — target_agent="A1"
──────────────────────────────────────────
budget: 3000
requirement (1200): title, description, source_payload
artifact (0): —
knowledge (1200): similar_requirements top-3, known_issues
environment (600): project.name, project.tech_stack
rework (0): —

状态: analyzing (A2 知识分析) — target_agent="A2"
──────────────────────────────────────────
budget: 5000
requirement (1000): title, description, A1 analysis (如果已产出)
artifact (500): A1 analysis
knowledge (2500): similar_requirements top-5, relevant_code, dependency_graph, best_practices
environment (1000): project.tech_stack, project.claude_md_content (摘要)
rework (0): —

状态: designing (A3 UI 原型)
──────────────────────────────
budget: 5000
requirement (1200): title, spec_sections, A1 analysis
artifact (800): A1 analysis, A2 knowledge_brief
knowledge (2000): similar_requirements (原型/设计参考) top-3
environment (1000): project.tech_stack
rework (0): — (rework 时额外 2000)

状态: designing (A4 Spec 撰写)
──────────────────────────────
budget: 6000
requirement (1200): title, spec_sections, acceptance_criteria, A1 analysis
artifact (800): A1 analysis, A2 knowledge_brief, A3 prototype_url
knowledge (2500): similar_requirements (OpenAPI/ERD 参考) top-3, relevant_code
environment (1500): project.tech_stack, project.coding_conventions, project.claude_md_content
rework (0): — (rework 时额外 2000)

状态: reviewing (A5 设计评审)
──────────────────────────────
budget: 8000
requirement (1200): title, spec_sections, acceptance_criteria
artifact (4000): A4 openapi (完整, 结构化提取), A4 erd (完整, 结构化提取), A4 state_machine, A3 prototype_url
knowledge (1500): best_practices (设计评审检查清单)
environment (1300): project.coding_conventions
rework (0): —

状态: decomposing (A6 任务拆分)
──────────────────────────────
budget: 6000
requirement (800): title, spec_sections
artifact (3000): A4 openapi, A4 erd, A5 review_scores, A5 issues
knowledge (1400): relevant_code, dependency_graph
environment (800): project.repo_url, project.tech_stack
rework (0): —

状态: developing (A9 代码生成) ⬅ 最重
───────────────────────────────────
budget: 10000
requirement (1200): title, description, spec_sections, acceptance_criteria
artifact (5000): A4 openapi, A4 erd, A6 dag, A7 test_outline, A5 issues
decisions (300):  resolved decisions from Gate 1 + Gate 2
knowledge (1500): relevant_code top-10, best_practices, known_issues
environment (2000): project.*, deployment.dev, deployment.staging,
                    integration.issue_tracker, integration.ci_cd
rework (0): — (rework 时额外 2500)

状态: testing (A11 测试)
────────────────────────
budget: 6000
requirement (600): title, acceptance_criteria
artifact (3000): A4 openapi, A7 test_cases, A9 code_diff_summary
knowledge (1200): relevant_code (测试文件), known_issues (测试失败模式)
environment (1200): deployment.staging, integration.monitoring, deployment.test_db
rework (0): —

状态: reviewing_code (A12 代码审查)
───────────────────────────────────
budget: 6000
requirement (800): title, spec_sections, acceptance_criteria
artifact (2500): A9 code_diff_summary, A11 test_report, A4 openapi
knowledge (1200): relevant_code (被修改文件原版), best_practices
environment (1500): project.claude_md_content, project.coding_conventions
rework (0): — (rework 时额外 2000)

状态: releasing (A13 发布)
──────────────────────────
budget: 6000
requirement (500): title, spec_sections
artifact (2800): A4 openapi, A9 code_diff_summary, A11 test_report,
                 A12 security_findings, A12 review_report
knowledge (700): dependency_graph
environment (2000): deployment.production, deployment.staging,
                    integration.monitoring, integration.ci_cd
rework (0): —
```

### 2.4 返工上下文

```python
# 返工类型
class ReworkType:
    DESIGN_REVIEW_FAIL = "design_review_fail"     # A5 → A3/A4
    REQUIREMENT_ISSUE = "requirement_issue"       # A5 → A1
    CODE_REVIEW_FAIL = "code_review_fail"         # A12 → A9
    CODE_REVIEW_SEVERE = "code_review_severe"     # A12 → A4 (严重架构问题)
    GATE_REJECT = "gate_reject"                   # 人类驳回 Gate

# 返工路由
_REWORK_PATHS = {
    RS.REVIEWING: {
        "fail": RS.DESIGNING,                      # A5 评审不通过 → A3/A4
        "fail_requirement": RS.ANALYZING,           # A5 判定需求有问题 → A1
    },
    RS.REVIEWING_CODE: {
        "fail": RS.DEVELOPING,                     # A12 审查不通过 → A9
        "fail_severe": RS.DESIGNING,                # A12 发现严重架构问题 → A4
    },
}

# 返工上下文注入
@dataclass
class ReworkContext:
    rework_type: str
    round_number: int                    # 第几轮
    source_agent: str                    # 谁触发
    issues: list[dict]                   # [{severity, file/field, description, suggestion}]
    scores: dict | None
    previous_result: dict | None         # 上一轮的原始产出（不做 diff—MVP 阶段简化）
    suggestion: str                      # 改进方向
    priority: str                        # "must_fix" | "should_fix" | "nice_to_fix"

# 返工 token 预算
rework_budget = 2500  # 独立于状态预算，额外分配
```

---

## 三、传输链路优化

### 3.1 问题

当前两个截断点导致 Agent 拿不到足够上下文：

```
build_context → dispatch_agent → NATS → Agent → LLM
 8000 tokens    截断 5000 字符    传输      截断 4000 字符   拿到 ≈1000 tokens
               (≈1250 tokens)            (≈1000 tokens)
```

### 3.2 dispatch_agent 改造

```python
# orchestrator/activities/dispatch_agent.py
# 改前:
"context": context[:5000],

# 改后:
_CONTEXT_MAX_CHARS = int(os.environ.get("DISPATCH_CONTEXT_MAX_CHARS", "65536"))

def _truncate_context(context: str, max_chars: int) -> str:
    """在 max_chars 处截断 context，尽量保持结构完整性。"""
    if len(context) <= max_chars:
        return context
    # 向前找最近的双换行作为断开点
    search_start = int(max_chars * 0.9)
    break_pos = context.rfind("\n\n", search_start, max_chars)
    if break_pos > search_start:
        return context[:break_pos] + "\n\n[truncated — remaining items in _refs]"
    return context[:max_chars] + "\n[truncated]"

# 在 dispatch 时:
"context": _truncate_context(context_str, _CONTEXT_MAX_CHARS),
```

### 3.3 Agent 侧 ContextCompressionService

```python
# repos/agent-workers/context_compression.py (新增)

class ContextCompressionService:
    """统一的上下文压缩服务 — Agent 调用 LLM 前处理 context。
    
    压缩流水线:
      1. 分层 (head/mid/tail)
      2. 去重 (dedup)
      3. 压缩 (结构化提取 / LLM摘要)
      4. 序列化 + 预算检查
    """

    def __init__(self, config: dict, llm_caller=None, cache_dir: str = ".ai-native/cache"):
        self.dedup_threshold = config.get("dedup_threshold", 0.85)
        self.llm_summarize_enabled = config.get("llm_summarize_enabled", False)
        self.structured_extract_enabled = config.get("structured_extract_enabled", True)
        self.llm_caller = llm_caller  # BaseAgentWorker.call_llm
        self._summary_cache_dir = Path(cache_dir)
        self._summary_cache: dict[str, str] = {}  # 内存缓存

    def get_budget_for_state(self, state: str) -> int:
        """获取指定状态的 token 预算。"""
        budgets = self.config.get("budgets", {})
        state_config = budgets.get(state, {"pct": 2.0, "max": 4000})
        window = self.config.get("model_window", 200000)
        pct_budget = int(window * state_config["pct"] / 100)
        return min(pct_budget, state_config["max"])

    async def prepare_context(
        self, context_package: dict, budget: int, agent_id: str
    ) -> str:
        """将结构化 context_package 压缩为 LLM 输入文本。"""
        ...
```

### 3.4 集成到 BaseAgentWorker

ContextCompressionService 作为 `BaseAgentWorker` 的统一入口，避免每个 Agent 各自实现：

```python
# repos/agent-workers/base_worker.py

class BaseAgentWorker:
    _compressor: ContextCompressionService | None = None

    async def prepare_llm_context(self, context_package: dict, state: str) -> str:
        """统一的 LLM 上下文预处理——去重、结构化提取、预算控制。"""
        if BaseAgentWorker._compressor is None:
            config = load_context_budget_config()
            BaseAgentWorker._compressor = ContextCompressionService(
                config,
                llm_caller=self.call_llm,
            )
        budget = BaseAgentWorker._compressor.get_budget_for_state(state)
        return await BaseAgentWorker._compressor.prepare_context(
            context_package, budget, self.agent_id,
        )
```

Agent 使用方式：

```python
# 改前 (a12_code_review.py:71):
review_text = json.dumps(context_package, ensure_ascii=False)[:4000]

# 改后:
review_text = await self.prepare_llm_context(context_package, state="reviewing_code")
prompt = f"你是资深代码审查员。审查以下代码变更。\n\n{review_text}\n\n输出 JSON:..."
```

**兼容性**：context_package 的结构保持向后兼容——新增字段（`knowledge`、`environment`、`rework`）只是增量，Agent 不消费的新字段不会影响现有逻辑。

---

## 四、上下文安全余量

### 200K 模型窗口下的占用

| 场景 | 原始 | 压缩后 | 窗口占比 |
|------|------|--------|---------|
| A1 analyzing | 2000 | 1800 | 0.9% |
| A4 designing | 6000 | 3000 | 1.5% |
| A5 reviewing | 8000 | 3500 | 1.75% |
| **A9 developing** | **10000** | **4500** | **2.25%** |
| A9 + 全部扩展 (skills/tools/claude_md 全文) | — | 8000 | 4% |
| A9 双脑多轮 (3 轮上下文叠加) | — | 15000 | 7.5% |

### 1M 模型窗口下的占用

| 场景 | 压缩后 | 窗口占比 |
|------|--------|---------|
| A9 developing | 4500 | 0.45% |
| A9 最坏情况 | 15000 | 1.5% |

**结论: 200K 窗口即使最坏情况仅占 7.5%，1M 窗口不到 2%。足够容纳未来 skills、tools、历史对话等所有扩展。**

---

## 五、五个 Task

```
T1: Gate SLA     T2: notify_mc     T3: Agent 超时    T4: build_context    T5: 产物持久化
    超时通知          DB 同步           升级通知           富化 + 压缩          store_agent_result
       │               │                 │                  │                    │
  改 _run_gate    改 notify_mc +     改 _dispatch_      重写 context_build    新增 Activity
  _stage           MC Backend         and_wait          新增 context_comp     改 Workflow
                                                        新增 2 个 yaml
```

### T1: Gate SLA 超时 → 通知但不自动通过

所有 Gate **必须人工审批**，SLA 超时后发升级通知但**不自动推进**。

**改动**: `requirement_workflow.py` / `gate_await.py`

- `_run_gate_stage` 第一段：`asyncio.wait_for(timeout=sla)` 等待人工审批
- 超时后：调用 `notify_mc` 发 Gate 超时事件
- **Gate 0/3 直接重新等待（无超时 `wait_condition`）**
- Gate 1/2 可选择性地再次等待 N 分钟（不是自动通过，而是给额外宽限期）
- 新增 `gate_timeout` Signal：管理员主动跳过 Gate（区分"自动"和"手动跳过"）
- SLA 配置: `_GATE_SLA = {0:1h, 1:4h, 2:4h, 3:2h}`，可通过环境变量覆盖

```python
# requirement_workflow.py

_GATE_SLA: dict[int, timedelta] = {
    0: timedelta(hours=1),
    1: timedelta(hours=4),
    2: timedelta(hours=4),
    3: timedelta(hours=2),
}

_GATE_GRACE_PERIOD: dict[int, timedelta | None] = {
    0: None,          # Gate 0: 无宽限期，超时后通知并无限等待
    1: timedelta(hours=1),   # Gate 1: 超时后给 1h 宽限期
    2: timedelta(hours=1),   # Gate 2: 超时后给 1h 宽限期
    3: None,          # Gate 3: 无宽限期，超时后通知并无限等待
}

async def _run_gate_stage(self, req_id: str, gate_level: int):
    self._gate_approved = None
    sla = _GATE_SLA.get(gate_level, timedelta(hours=4))

    await workflow.execute_activity(
        create_gate_approval,
        args=[req_id, gate_level, sla.total_seconds()],
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=_DEFAULT_RETRY,
    )

    # Phase 1: Wait for approval within SLA
    try:
        await asyncio.wait_for(
            self._wait_for_gate(), timeout=sla.total_seconds()
        )
        return  # approved within SLA
    except asyncio.TimeoutError:
        pass

    # Phase 2: SLA expired — notify
    await workflow.execute_activity(
        notify_mc,
        args=[req_id, self._state.value, self._state.value,
              {"event": "gate_timeout", "gate_level": gate_level,
               "sla_hours": sla.total_seconds() / 3600}],
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=_DEFAULT_RETRY,
    )

    grace = _GATE_GRACE_PERIOD.get(gate_level)
    if grace is not None:
        # Gate 1/2: give grace period
        try:
            await asyncio.wait_for(
                self._wait_for_gate(), timeout=grace.total_seconds()
            )
            return  # approved during grace period
        except asyncio.TimeoutError:
            # Grace period expired — escalate, notify again, wait indefinitely
            await workflow.execute_activity(
                notify_mc,
                args=[req_id, self._state.value, self._state.value,
                      {"event": "gate_grace_expired", "gate_level": gate_level}],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_DEFAULT_RETRY,
            )

    # Gate 0/3 或 Gate 1/2 宽限期后: 无限等待人工审批
    await self._wait_for_gate()

async def _wait_for_gate(self):
    """Block until gate approved or force-skipped by admin."""
    await workflow.wait_condition(
        lambda: self._gate_approved is not None
    )

@workflow.signal
async def gate_timeout(self, gate_level: int, approver: str = ""):
    """Signal: admin manually skip a gate.
    
    与 SLA 超时不同——这是人类管理员主动操作，记录 approver。
    """
    workflow.logger.warning(
        "Gate %d force-skipped by admin: %s", gate_level, approver
    )
    self._gate_approved = f"force-skip-gate-{gate_level}-by-{approver}"
```

**文件**: `requirement_workflow.py` (+50 行), `gate_await.py` (+5 行)

### T2: notify_mc 写 DB

**改动**: `notify_mc.py` / `mc-backend/api/requirements.py`

- MC Backend 新增 `PUT /api/requirements/{req_id}/status`
- `notify_mc` Activity: 发 NATS 后 HTTP PUT 到 MC Backend（best-effort, 失败不阻塞）
- MC Backend 收到后更新 `requirements.status` + `requirements.spec.stages` + 写 `agent_activities` 审计记录

**文件**: `mc-backend/api/requirements.py` (+50 行), `notify_mc.py` (+15 行), `requirements.txt` (+`httpx`)

### T3: Agent 超时 → 升级通知

**改动**: `requirement_workflow.py`

- `_dispatch_and_wait` 包 `asyncio.wait_for(timeout)`
- 超时后 `_agent_failures[agent_id] += 1`，达阈值 (2) 时调用 `notify_mc` 发升级事件
- 成功后重置计数
- 去掉废弃的 `self._escalate` flag

**文件**: `requirement_workflow.py` (+30 行)

### T4: build_context 富化 + 压缩

**改动**: `context_build.py`(重写) / `context_compression.py`(新增) / 2 个 yaml 配置

| 文件 | 动作 | 说明 |
|------|------|------|
| `orchestrator/activities/context_build.py` | 重写 | 五层上下文 + 每状态注入规则 + 知识库检索 |
| `repos/agent-workers/context_compression.py` | 新增 | ContextCompressionService: 分层+去重+压缩+预算检查 |
| `.ai-native/project-config.yaml` | 新增 | 项目环境配置 |
| `.ai-native/context-budget.yaml` | 新增 | token 预算 + 压缩策略配置 |
| `orchestrator/activities/dispatch_agent.py` | 改 1 行 | `context[:5000]` → `_truncate_context(context, max_chars)` |
| `orchestrator/requirements.txt` | +`pyyaml` +`httpx` | config 解析 + MC Backend 调用 |
| Agent 文件 (各 1 行) | 改 | 暴力截断 → `self.prepare_llm_context()` |

#### T4 详细设计：知识库注入

当前 orchestrator 的 `build_context` Activity **没有调用** context-builder 服务（独立 FastAPI :8300，hybrid pgvector + PostgreSQL FTS）。

**接入方式**：

```python
# orchestrator/activities/context_build.py

CONTEXT_BUILDER_URL = os.environ.get("CONTEXT_BUILDER_URL", "http://localhost:8300")

async def build_context(req_id: str, state: str, target_agent: str = "") -> dict:
    pool = await _get_pool()

    # 1. 读需求 + 产物 (DB)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, description, spec, source_payload FROM requirements WHERE id = $1::uuid",
            req_id,
        )
        if not row:
            return {"req_id": req_id, "state": state, "error": "Requirement not found"}

        spec = _parse_json(row["spec"])
        requirement_context = _extract_requirement_context(row, spec)
        artifact_context = _extract_artifact_context(spec, state)  # 从 spec.artifacts.{agent_id} 读

    # 2. 读环境配置 (文件缓存)
    environment_context = await _load_environment_context()

    # 3. 读知识库 (context-builder 服务 或 直接查表)
    agent_id = target_agent or _agent_for_state(state)
    knowledge_context = await _build_knowledge_section(
        target_agent=agent_id,
        req_id=req_id,
        requirement_context=requirement_context,
        token_budget=2000,
    )

    # 4. 组装 + 预算控制
    context = _assemble_with_budget(
        requirement_context, artifact_context, knowledge_context,
        environment_context, state,
    )
    context["req_id"] = req_id
    context["state"] = state
    context["agent_id"] = agent_id
    return context
```

**知识库查询——优先调 context-builder 服务，失败时回退直查表**：

```python
async def _query_knowledge_base(target_agent: str, req_id: str, query_text: str, max_tokens: int) -> dict:
    # 方案 A: HTTP 调用 context-builder 服务
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{CONTEXT_BUILDER_URL}/context/build",
                json={"target_agent": target_agent, "req_id": req_id,
                      "query_text": query_text, "max_tokens": max_tokens},
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("success"):
                return result["context_package"]
    except Exception as e:
        logger.warning("context-builder unavailable: %s, falling back to direct DB", e)

    # 方案 B: 直接查 knowledge_chunks 表
    return await _query_knowledge_chunks_direct(target_agent, req_id, query_text, max_tokens)


async def _query_knowledge_chunks_direct(target_agent, req_id, query_text, max_tokens) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """SELECT title, content, doc_type, file_path,
                         ts_rank(search_vector, plainto_tsquery('english', $1)) AS rank
                  FROM knowledge_chunks
                  WHERE search_vector @@ plainto_tsquery('english', $1)
                  ORDER BY rank DESC LIMIT 20""",
                query_text,
            )
        except Exception:
            return {"head": [], "mid": [], "tail": [], "discarded": []}

        items = []
        for row in rows:
            items.append({
                "type": row["doc_type"], "content": row["content"],
                "relevance": float(row["rank"]) if row["rank"] else 0.0,
                "tokens": count_tokens(row["content"]), "file": row["file_path"],
            })
        return {"head": items, "mid": [], "tail": [], "discarded": []}
```

**按 Agent 类型构建搜索查询——每个 Agent 搜不同的东西**：

```python
def _build_search_queries(agent_id: str, req: dict) -> dict[str, str]:
    title = req.get("title", "")
    description = req.get("description", "")
    base = f"{title} {description}"

    return {
        "A1": {
            "similar_requirements": f"需求分析 历史需求 {base}",
            "known_issues": f"问题 风险 {base}",
        },
        "A2": {
            "similar_requirements": f"需求 设计 {base}",
            "relevant_code": f"代码 {base}",
            "dependency_graph": f"依赖 模块 {base}",
            "best_practices": f"最佳实践 {base}",
        },
        "A3": {
            "similar_requirements": f"UI原型 界面设计 {base}",
        },
        "A4": {
            "similar_requirements": f"API设计 数据库 ERD OpenAPI {base}",
            "relevant_code": f"API Schema SQL {base}",
        },
        "A5": {
            "best_practices": f"设计评审 架构评审 安全检查清单 反模式",
        },
        "A6": {
            "relevant_code": f"模块结构 项目架构 {base}",
            "dependency_graph": f"依赖关系 模块 {base}",
        },
        "A9": {
            "relevant_code": f"代码实现 {base}",
            "best_practices": f"编码规范 错误处理 日志 安全 最佳实践",
            "known_issues": f"Bug 问题 历史缺陷 {base}",
        },
        "A11": {
            "relevant_code": f"测试 测试用例 {base}",
            "known_issues": f"测试失败 常见测试问题",
        },
        "A12": {
            "relevant_code": f"代码 {base}",
            "best_practices": f"代码审查 代码质量 安全",
        },
        "A13": {
            "dependency_graph": f"依赖 影响范围 {base}",
        },
    }.get(agent_id, {"similar_requirements": base})
```

**知识库内容在 context 中的展示格式**——按 context-builder 的分层结构：

```
[KNOWLEDGE_CONTEXT]
────────────────────

## Head (高相关性 — 优先阅读)
- [code] src/api/auth.py (relevance: 0.92)
  内容: ...

- [knowledge] JWT Token 最佳实践 (relevance: 0.88)
  内容: ...

## Mid (参考 — 需要时查阅)
- [doc] API 设计规范 v2.1 (relevance: 0.75)
  内容: ...

## Tail (背景 — 相关信息)
- [spec] 历史需求 #124: 用户登录改造 (relevance: 0.64)
  内容: ...
```

### T5: Agent 产物持久化

**改动**: `store_agent_result.py`(新增) / `requirement_workflow.py`

```python
# orchestrator/activities/store_agent_result.py (新增)

@activity.defn(name="store_agent_result")
async def store_agent_result(req_id: str, agent_id: str, result: dict) -> dict:
    """将 agent 产出写入 requirements.spec.artifacts JSONB。"""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE requirements
            SET spec = jsonb_set(
                COALESCE(spec, '{}'::jsonb),
                '{artifacts,' || $2 || '}',
                $3::jsonb,
                true
            ),
            updated_at = NOW()
            WHERE id = $1::uuid
        """, req_id, agent_id, json.dumps(result))
        return {"ok": True, "req_id": req_id, "agent_id": agent_id}

# requirement_workflow.py — _dispatch_and_wait 成功后:
_AGENTS_THAT_PERSIST = {"A4"}  # A4 自己直接写 DB，不需要重复写入

if self._agent_result is not None and agent_id not in _AGENTS_THAT_PERSIST:
    await workflow.execute_activity(
        store_agent_result,
        args=[req_id, agent_id, self._agent_result],
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=_DEFAULT_RETRY,
    )
```

**文件**: `orchestrator/activities/store_agent_result.py` (新增, 40 行), `requirement_workflow.py` (+6 行)

### T6: Gate Decisions 持久化 + Context 注入

**背景** (来自 `doc/bugs/a9-agent-design-analysis.md` v2.1 第 12.2 节 G1): A5 产出 `decisions_required[]`，Gate 1 审批后选定决策值，但选定的决策值在整个 Phase 0 规划中没有存储和传递路径。A9 开发时收不到架构决策约束。

**改动**: `gate_await.py` / `context_build.py` / 新增 `store_gate_decision` Activity

**存储方案** — `spec.decisions` JSONB 独立根键:

```sql
-- Gate 审批通过后执行:
UPDATE requirements
SET spec = jsonb_set(
    COALESCE(spec, '{}'::jsonb),
    '{decisions}',
    $1::jsonb,
    true
),
updated_at = NOW()
WHERE id = $2::uuid;
```

`spec.decisions` 结构:
```json
{
  "resolved": {
    "arch-d1": "Redis",
    "arch-d2": "JWT"
  },
  "source_gates": [1],
  "approved_at": "2026-07-06T15:30:00Z",
  "approver": "tech-lead",
  "a5_review_id": "REV-abc12345-143000"
}
```

**Trigger 时机**: Gate 审批通过时。有两种方式:

```python
# 方案 A: gate_await.py 的 create_gate_approval 返回后,
# Workflow 调用新的 store_gate_decision Activity
@activity.defn(name="store_gate_decision")
async def store_gate_decision(req_id: str, gate_level: int, decision_data: dict) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # 读取 Gate 1 审批时关联的 A5 decisions_required
        # 合并选定的决策值
        await conn.execute("""
            UPDATE requirements
            SET spec = jsonb_set(
                COALESCE(spec, '{}'::jsonb),
                '{decisions}',
                $1::jsonb,
                true
            ),
            updated_at = NOW()
            WHERE id = $2::uuid
        """, json.dumps(decision_data), req_id)
    return {"ok": True}

# 方案 B (更简单): MC Backend 审批通过时直接写 decisions 到 spec
# MC Backend PUT /api/requirements/{req_id}/decisions
# 存储 decisions + source_gates + approved_at
```

**推荐方案 B** — MC Backend 审批通过时写。避免在 Temporal Workflow 中新增 Activity。MC Backend 已经有 `requirements` 表的写权限（T2 的 `notify_mc` DB 同步）。

**Context 注入** — `context_build.py`:

```python
# build_context() 中, 在组装 context dict 时新增 decisions 层:

# 6. Decisions context (Gate 审批决策)
decisions_context = await _extract_decisions_context(req_id, state, conn)

# 组装:
context = {
    # ... 现有五层
    "decisions_context": decisions_context,  # ← 新增
    # 向后兼容 key
    "decisions": decisions_context.get("resolved", {}),
}


async def _extract_decisions_context(req_id: str, state: str, conn) -> dict:
    """读取 Gate decisions — 从 spec.decisions JSONB 根键。

    对于 DEVELOPING 阶段: 读 Gate 1 的架构决策
    对于 TESTING 阶段: 读 Gate 1 + Gate 2 的决策
    """
    if state not in ("developing", "testing", "reviewing_code", "releasing"):
        return {}

    row = await conn.fetchrow(
        "SELECT COALESCE(spec->'decisions', '{}'::jsonb) AS decisions FROM requirements WHERE id = $1::uuid",
        req_id,
    )
    if not row:
        return {"resolved": {}, "source_gates": []}

    decisions = json.loads(row["decisions"]) if isinstance(row["decisions"], str) else row["decisions"]
    return {
        "resolved": decisions.get("resolved", {}),
        "source_gates": decisions.get("source_gates", []),
        "approved_at": decisions.get("approved_at", ""),
    }
```

**A5 侧 decisions_required 输出** (见 `doc/bugs/a9-agent-design-analysis.md` 第 2.2 节):

A5 review result 中新增 `decisions_required` 数组。MC Backend 审批 UI 展示这些选项，审批后选定的值写入 `spec.decisions`。

**文件**: `mc-backend/api/requirements.py` (+40 行, `PUT /api/requirements/{req_id}/decisions`), `context_build.py` (+25 行)

### T7: A4 Artifact 数据通路修复

**背景** (来自 `doc/bugs/a9-agent-design-analysis.md` v2.1 第 12.1 节 C1): A4 在 `_AGENTS_THAT_PERSIST` skip set 中，写 `spec.openapi`/`spec.erd` 根键。但 `_extract_artifact_context` 从 `spec.artifacts.A4` 读取，该 key 永不被写入。结果是 A9/A5/A6 等下游 Agent 的 `openapi_hint` / `erd_hint` 始终为空。

**修复方案** — context_build 特殊处理 A4 的数据读取:

```python
# context_build.py — _extract_artifact_context 修改

def _extract_artifact_context(spec: dict, state: str) -> dict:
    relevant = _STATE_UPSTREAM.get(state, [])
    artifacts = spec.get("artifacts", {}) or {}

    result = {}
    for agent_id in relevant:
        if agent_id == "A4":
            # A4 writes to spec.openapi / spec.erd (root keys) instead of
            # spec.artifacts.A4 because it's in _AGENTS_THAT_PERSIST.
            # Read from root keys and normalize into artifact_context.
            a4_data = {}
            openapi = spec.get("openapi", {})
            erd = spec.get("erd", {})

            if openapi:
                api_schema = openapi.get("schema", openapi)
                a4_data["openapi"] = {
                    "endpoints": list(api_schema.get("paths", {}).keys()) if isinstance(api_schema, dict) else [],
                    "info": api_schema.get("info", {}) if isinstance(api_schema, dict) else {},
                    "has_schema": bool(api_schema.get("paths")) if isinstance(api_schema, dict) else False,
                }
            if erd:
                a4_data["erd"] = {
                    "tables": [e.get("name", "") for e in erd.get("entities", [])],
                    "relationships": erd.get("relationships", []),
                    "has_entities": bool(erd.get("entities", [])),
                }

            result[agent_id] = a4_data if a4_data else artifacts.get(agent_id, {})
        elif agent_id in artifacts:
            result[agent_id] = artifacts[agent_id]
        else:
            result[agent_id] = {}

    return result
```

**向后兼容**: openapi_hint / erd_hint 的 backward-compatible keys (context_build.py L378-389) 现在会收到真实数据，因为 `artifact_context.A4` 不再为空。

**文件**: `orchestrator/activities/context_build.py` (+25 行, 改 `_extract_artifact_context`)

### T8: DEVELOPING ↔ TESTING 内循环 + Escalation → BLOCKED 路径

**背景** (来自 `doc/bugs/a9-agent-design-analysis.md` v2.1 Audit-02 + Audit-04):
- `DEVELOPING → TESTING` 当前是单向的，A11 测试失败后没有路径回到 A9
- A9 返回 `{"status": "blocked"}` 时 Workflow 没有对应的 BLOCKED 转换

**改动**: `requirement_workflow.py`

#### T8a: Escalation → BLOCKED 路径

Agent 返回 `{"status": "blocked", "reason": "..."}` 时，Workflow 应立即进入 BLOCKED，不等待 timeout:

```python
# requirement_workflow.py — _dispatch_and_wait 中

if self._agent_result is None:
    # ... 现有 timeout 处理 ...
else:
    self._agent_failures[agent_id] = 0

    # NEW: 检查 agent result 是否要求 block
    agent_status = self._agent_result.get("status", "")
    if agent_status in ("blocked", "escalated"):
        workflow.logger.warning(
            "Agent %s requested block: %s",
            agent_id,
            self._agent_result.get("reason", "unknown"),
        )
        # 不做 store_agent_result (该 state 的产出无效)
        # _compute_next_state 会读取 status 并返回 BLOCKED
        return  # 提前退出，跳过 store_agent_result
```

`_compute_next_state` 中新增:

```python
def _compute_next_state(self, req_id: str, current: RS) -> RS:
    # NEW: 检查 agent result 是否要求 block (在所有分支之前)
    if self._agent_result:
        agent_status = self._agent_result.get("status", "")
        if agent_status in ("blocked", "escalated"):
            workflow.logger.warning(
                "Agent %s requested block: %s",
                self._agent_id_expected,
                self._agent_result.get("reason", "unknown"),
            )
            return RS.BLOCKED
    
    # ... 现有 REVIEWING rework 逻辑 ...
    # ... 现有线性映射 ...
```

#### T8b: DEVELOPING ↔ TESTING 内循环

```python
# requirement_workflow.py — __init__ 新增状态变量
def __init__(self) -> None:
    # ... 现有变量
    self._inner_loop_count: int = 0       # ← 新增: DEVELOPING↔TESTING 循环计数
    self._last_test_result: dict | None = None  # ← 新增: A11 失败报告

# _compute_next_state 中新增:
def _compute_next_state(self, req_id: str, current: RS) -> RS:
    # ... BLOCKED check (T8a) ...
    # ... REVIEWING rework (existing) ...

    # NEW: TESTING fail → back to DEVELOPING (inner loop)
    if current == RS.TESTING:
        a11_pass = False
        if self._agent_result:
            a11_pass = self._agent_result.get("pass", self._agent_result.get("status") == "completed")

        if not a11_pass and self._inner_loop_count < 2:
            self._inner_loop_count += 1
            workflow.logger.info(
                "Inner loop #%d: TESTING -> DEVELOPING (rework)", self._inner_loop_count
            )
            self._last_test_result = self._agent_result
            return RS.DEVELOPING

        # Pass or exhausted → continue to REVIEWING_CODE
        self._inner_loop_count = 0
        return RS.REVIEWING_CODE

    # ... 其余不变
```

**Rework feedback 注入** — `_run_agent_stage` 中:

```python
# DEVELOPING 阶段，如果是 inner loop rework，注入 A11 测试失败信息
if state == RS.DEVELOPING and self._last_test_result:
    import json as _json
    context_str = context_str + "\n[TEST_FAILURE_FEEDBACK]\n" + _json.dumps({
        "failed_tests": self._last_test_result.get("failed_tests", []),
        "failures_detail": self._last_test_result.get("failures_detail", []),
        "coverage_pct": self._last_test_result.get("coverage_pct", 0),
        "errors": self._last_test_result.get("errors", [])[:10],
    }, ensure_ascii=False)
    self._last_test_result = None
```

**Transition table** — `transitions.py` 已经允许 `DEVELOPING → TESTING` 和 `TESTING → REVIEWING_CODE`，内循环是:
```
DEVELOPING → TESTING → [fail] → DEVELOPING → TESTING → [pass] → REVIEWING_CODE
```
`DEVELOPING → BLOCKED` 的转换也已在 TRANSITION_TABLE 中定义。

**文件**: `requirement_workflow.py` (+55 行), `transitions.py` (无需改动)


## 六、实施顺序

```
T1 ──── T2 ──── T3 ──── T5 ──── T4
 │        │       │       │       │
Gate    notify  Agent   产物     context
SLA     DB同步  超时    持久化   富化+压缩

依赖链:
T1,T2,T3 无依赖可并行
T5 依赖 T2 (notify_mc DB 写权限 + MC Backend API 已可用)
T4 依赖 T5 (产物持久化后 artifact_context 才有数据可读)
T6 可在 T2 完成后独立实施 (MC Backend API 已有 requirements 写权限)
T7 依赖 T5 (对 _extract_artifact_context 的修改)
T8 独立 — 纯 Workflow 逻辑改动，不依赖 T5/T4
```

### 每 Task 改动面

| Task | 改动文件数 | 新增文件 | 风险 |
|------|-----------|---------|------|
| T1 | 2 | 0 | 低 — 只改 timeout 路径 |
| T2 | 2 | 0 | 低 — notify_mc 加 side effect |
| T3 | 1 | 0 | 低 — 只改超时处理 |
| T5 | 2 | 1 (store_agent_result.py) | 低 — 单次 DB UPDATE |
| T4 | 5 | 4 (context_compression.py + 2 yaml + context_build 重写) | 中 — 重写 build_context |
| T6 | 2 | 0 | 低 — MC Backend API (+40 行) + context_build (+25 行) |
| T7 | 1 | 0 | 低 — context_build 25 行改动 |
| T8 | 1 | 0 | 低 — requirement_workflow +55 行，纯逻辑改动 |

---

## 七、验收标准

1. 所有 Gate SLA 超时后发通知但**不自动通过**，必须人工审批或管理员跳过
2. Gate 1/2 超时后有宽限期，宽限期后仍等待人工审批
3. `gate_timeout` Signal 可让管理员主动跳过 Gate（记录 approver）
4. Workflow 状态变更后 `requirements.status` 在 DB 中对应更新
5. Agent 连续超时 2 次后触发 `notify_mc` 升级事件
6. `store_agent_result` 将 Agent 产出持久化到 `requirements.spec.artifacts.{agent_id}`
7. `build_context("developing")` 返回五层完整上下文，含上游 artifact + project.claude_md_content
8. `build_context` 的 artifact 数据来源于 DB 中已持久化的 Agent 产出
9. Agent 侧不再有 `[:4000]` 暴力截断，统一使用 `self.prepare_llm_context()`
10. `dispatch_agent` 的 context 截断位置从 5000 字符提升到 64K
11. `.ai-native/` config 文件不存在时不报错，使用默认值
12. 换 1M 窗口模型后只需改 `model_window`，token 预算自动按比例放大
13. ContextCompressionService 的摘要缓存对 CLAUDE.md 等静态内容生效，文件 mtime 校验
14. Gate 审批后 decisions 持久化到 `spec.decisions`，`build_context("developing")` 能读到 (T6, v1.1)
15. `build_context` 的 `artifact_context.A4` 正确包含 openapi/erd 数据 (T7, v1.1)
16. A11 测试失败后 Workflow 自动回到 DEVELOPING（inner loop max 2 轮）(T8, v1.1)
17. Agent 返回 `{"status": "blocked"}` 时 Workflow 立即进入 BLOCKED，不等待 timeout (T8, v1.1)

---

## 八、远景兼容性：与 JAP Plus 三层架构的关系

本文档与 `doc/specs/jap-plus-absorption-plan.md` 的关系：
- **jap-plus-absorption-plan** = 远景架构蓝图（终极目标）
- **本文档** = Phase 0 基础设施（打地基，铺路）

### 8.1 设计兼容性对照

所有当前设计都是正向铺路，**不存在将来需要推倒重来的东西**：

| 当前设计 | 远景需要 | 兼容性 |
|---------|---------|:---:|
| `.ai-native/` + config yaml | 完整三层目录 (agents/shared/mcp/) | ✅ 将来在其中加子目录，不影响现有文件 |
| `prepare_llm_context()` 上下文预处理 | SkillLoader → `build_enhanced_prompt()` 注入 skills | ✅ 同一个入口点，将来加 Skills 层是叠加不是替代 |
| `build_context` → context-builder (HTTP) 查知识库 | knowledge-base-mcp (MCP stdio) 暴露知识库 | ✅ 查询构建逻辑（`_build_search_queries`）完全复用，只换传输协议 |
| `ContextCompressionService` 单体压缩 | shared/tools 独立模块 (dedup/fallback-parser/cross-check) | ✅ 解耦即可——当前压缩逻辑拆成独立工具，CompressionService 变编排层 |
| `store_agent_result` → `spec.artifacts.{agent_id}` | Agent Skills 定义 output schema | ✅ 产物按 agent_id 分组，将来可加 schema 校验 |
| `context-budget.yaml` 百分比预算 | 支持更大模型 + 更复杂上下文 | ✅ 换模型只改 `model_window` 一行 |
| `dispatch_agent` 的 context truncation | MCP 协议传输 | ✅ 将来 context 走 MCP 时，64K 截断逻辑直接去掉 |

**Context vs Skills 的核心区别**：
- **Context**（当前 spec）= 管"**喂什么数据**"——需求、产物、知识库、环境信息
- **Skills**（远景）= 管"**按什么规则处理数据**"——Agent 行为约束、质量门禁、输出格式要求
- 两者不是替代关系，是**叠加关系**。`prepare_llm_context()` 处理数据输入，`build_enhanced_prompt()` 在此基础上注入行为规则。

### 8.2 缺的桥（后续 Phase 需要补的）

| # | 缺的桥 | 当前状态 | 影响范围 |
|---|--------|---------|---------|
| 1 | **SkillLoader** — `.skill.md` 解析 + 注入 system prompt | 未建 | Agent 没有行为规则约束，完全靠 prompt 模板 |
| 2 | **MCPClient (Python)** — Agent 侧调用 MCP 工具 | 未建 | Agent 不能主动查知识库/校验 spec/执行沙箱 |
| 3 | **knowledge-base-mcp Server** — MCP 协议暴露知识库 | 未建 | 知识库查询耦合在 orchestrator 的 HTTP 调用中 |
| 4 | **Agent function calling** — 所有 Agent 当前是 single-turn | 未建 | 不能用懒加载 `_refs`，不能用 MCP tools |
| 5 | **shared/skills** — quality-gates/error-handling/security-baseline | 未建 | 跨 Agent 质量约束靠代码硬编码 |
| 6 | **A2 不在主状态机** | 未建 | A2 的知识分析结果不进入 artifact 链 |
| 7 | **Circuit Breaker 在 Agent 侧** — LLM 调用失败时的模型升级 | 未建 | Agent 的 `call_llm()` 失败直接返回 None |

### 8.3 当前设计预留的接口点（Phase 2+ 时只需扩展，不需重写）

```
BaseAgentWorker
  │
  ├── prepare_llm_context()          ← [Phase 0] 统一上下文预处理入口
  │     └── 压缩 + 预算控制
  │     └── [Phase 2] ↑ 叠加 build_enhanced_prompt() — Skills 注入
  │
  ├── call_llm()                     ← [Phase 0] 统一 LLM 调用
  │     └── [Phase 3] ↑ 叠加 Agent function calling — MCP tools
  │
  └── execute(context_package)       ← [Phase 0] Agent 主逻辑
        └── context_package 结构向后兼容
        └── [Phase 3] Agent 可用 context_package 中的 _refs 做懒加载

build_context Activity
  │
  ├── requirement_context            ← [Phase 0] 从 DB requirements 表
  ├── artifact_context               ← [Phase 0] 从 DB spec.artifacts JSONB
  ├── knowledge_context              ← [Phase 0] HTTP → context-builder
  │     └── [Phase 3] ↑ 改为 MCP → knowledge-base-mcp
  │     └── _build_search_queries() 查询构建逻辑完全复用
  ├── environment_context            ← [Phase 0] 从 .ai-native/project-config.yaml
  └── rework_context                 ← [Phase 0] 从 Workflow 实例状态

store_agent_result Activity
  │
  └── requirements.spec.artifacts.{agent_id}  ← [Phase 0] 直接写 JSONB
        └── [Phase 2] ↑ 叠加 output schema 校验 (来自 Agent skill 定义)
```

---

## 九、全系统演进路线图

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Phase 0 — Orchestrator 补全 (本 spec)                                    │
│                                                                          │
│  T1: Gate SLA 超时通知          T4: build_context 富化 + 压缩            │
│  T2: notify_mc DB 同步          T5: Agent 产物持久化                     │
│  T3: Agent 超时升级通知                                                   │
│                                                                          │
│  产出: 稳定的 Orchestrator + 五层上下文基础设施 + .ai-native/ 骨架        │
│  时间: ~2 周                                                             │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Phase 1 — Stub Agent 替换                                                │
│                                                                          │
│  A9: ClaudeCodeBridge 真实调用 → 实际代码生成                             │
│  A10: 接真实 Docker build + lint + deploy staging                        │
│  A11: 接真实 VisAgent HTTP + 测试执行                                     │
│  A13: 接真实 Prometheus + canary 流量切换                                 │
│  K14: LLM 增强 pgvector 写入 (摘要 + 向量化)                              │
│  K15: 接入 Neo4j 依赖图 → 影响面分析                                      │
│                                                                          │
│  产出: 端到端流程可跑通 (DRAFT → DONE)                                    │
│  时间: ~3 周                                                             │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Phase 2 — Skills 系统                                                    │
│                                                                          │
│  1. 实现 SkillLoader (解析 .skill.md + TTL 缓存 + 组合加载)              │
│  2. 创建 public shared skills (quality-gates + error-handling +          │
│     security-baseline)                                                   │
│  3. 创建 A1/A4/A5/A9 独立 Skills                                         │
│  4. BaseAgentWorker 增加 build_enhanced_prompt()                         │
│     → 在 prepare_llm_context() 前注入 Skills rules                       │
│  5. base_worker.py 增加 call_llm_with_fallback()                         │
│                                                                          │
│  产出: Agent 产出质量有统一规则约束                                       │
│  时间: ~2 周                                                             │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Phase 3 — MCP 基础设施                                                   │
│                                                                          │
│  1. 实现 Python MCPClient (多 Server stdio 连接管理 + 工具发现缓存)       │
│  2. 实现 knowledge-base-mcp Server (MVP: search_knowledge +              │
│     retrieve_by_id)                                                      │
│  3. 实现 spec-validator-mcp Server                                       │
│  4. ⚡ Agent function calling 改造 (最关键的一步)                         │
│  5. 开启 lazy_load_enabled — Agent 通过 _refs 按需拉取细节               │
│  6. build_context 的知识库注入从 HTTP 切换到 MCP stdio                    │
│                                                                          │
│  产出: Agent 可以主动调用工具，上下文从 push 变为 pull                    │
│  时间: ~3 周                                                             │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Phase 4 — 全量覆盖 + 生产加固                                             │
│                                                                          │
│  1. A6-A13, K14-K15 独立 Skills 创建                                     │
│  2. Circuit Breaker 接入 Agent 侧 — call_llm() 失败时模型升级             │
│  3. code-search-mcp + sandbox-runner-mcp Server                          │
│  4. 分段合并降级 + Context Builder 四策略对照                             │
│  5. MCP 服务注册表自动发现                                                │
│  6. 全链路可观测性 (Grafana Tempo/Loki/Mimir)                             │
│                                                                          │
│  产出: 全 Agent Skills/Tools/MCP 三层架构完成                            │
│  时间: ~4 周                                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phase 依赖关系

```
Phase 0 ──→ Phase 1 (依赖当前基础设施)
         ──→ Phase 2 (依赖 prepare_llm_context 入口)
              ──→ Phase 3 (依赖 Agent 改造 + context-builder 数据)
                   ──→ Phase 4 (依赖 MCP 基础设施)
```

Phase 1 和 Phase 2 可以并行——一个改 Agent 实现逻辑（接真实外部服务），一个加 Agent 行为规则（Skills 系统），互不冲突。

### 各 Phase 关键交付物

| Phase | 核心交付物 | 关键新增文件 |
|-------|----------|------------|
| **0** (本 spec) | 稳定的 Orchestrator + 五层上下文 | `context_compression.py`, `store_agent_result.py`, `project-config.yaml`, `context-budget.yaml` |
| **1** | 端到端可跑通 | 重写 A9/A10/A11/A13/K14/K15 约 10 个文件 |
| **2** | Skills 系统 | `skill_loader.py`, 6+ 个 `.skill.md`, `base_worker.py` 新增方法 |
| **3** | MCP 基础设施 | `mcp-client.tool.py`, `knowledge-base-mcp/{server,tools,config}`, Agent function calling 改造 |
| **4** | 三层架构完成 | 15 个 Agent Skills, code-search-mcp, sandbox-runner-mcp, Circuit Breaker Agent 侧接入 |
