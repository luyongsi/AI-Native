# A2 - 知识分析 Agent 规格

## 基本信息
- **Agent ID**: A2
- **Agent Type**: knowledge_analyst
- **触发事件**: `requirement.drafted`
- **发布事件**: `agent.a2.completed`
- **状态机状态**: `ANALYZING`
- **代码位置**: `repos/agent-workers/a2_knowledge_analyst.py`
- **超时时间**: 5分钟

## 职责

A2 是 15-Agent 流水线的第二个 Agent，在 A1（需求接收）完成需求草案后执行。其核心职责是通过历史知识检索和技术智能分析，为需求草案补充上下文信息：

- 通过语义搜索查找相似的历史需求（pgvector embeddings）
- 评估技术可行性和复杂度
- 基于历史模式识别风险点
- 查询服务依赖拓扑（Neo4j）
- 基于代码模式提供实现建议

**设计理念：** 需求很少是孤立的。A2 防止重复造轮子，从相似工作中挖掘已知陷阱，并在设计开始前提供有据可依的复杂度估算。这使下游 Agent（A3-A15）能够做出更明智的规划决策。

**流水线位置：** Agent #2/15，在 A1（需求接收）之后执行，在 A3（UI 生成）之前完成

---

## 功能概览

### 核心职责

1. **语义搜索** — 通过 pgvector embeddings 查询历史需求，返回 Top 5 相似项
2. **依赖分析** — 从 Neo4j 检索服务拓扑（如不可用则优雅降级）
3. **模式提取** — 从相似需求的元数据中提取可复用的代码模式
4. **风险评估** — 将历史标签映射到已知风险类别（并发、认证、异步等）
5. **复杂度估算** — 计算复杂度分数（0-1）和预估工作量（3-20 天）
6. **知识融合** — 将所有来源整合为统一的知识包，并生成 LLM 建议

### 5 阶段执行流水线

```
阶段 1: 语义搜索         → 查找相似需求（pgvector/embeddings）
阶段 2: 依赖拓扑         → Neo4j 服务图查询（可选）
阶段 3: 相关 PRs/Issues  → PostgreSQL 查询（stub 实现）
阶段 4: 知识融合         → LLM 综合分析 + 结构化打包
阶段 5: 事件发布         → 发布结果和制品
```

---

## 当前实现

### 文件结构

```
repos/agent-workers/
├── a2_knowledge_analyst.py          # 主 Agent 类
└── a2/
    ├── __init__.py                  # 包定义
    ├── rag_retriever.py             # RAG 语义搜索接口
    ├── rag_search.py                # 遗留 RAG mock（已废弃）
    ├── conflict_detector.py         # 跨规格冲突检测（stub）
    ├── feasibility.py               # 技术可行性评估（stub）
    └── test_knowledge_analyst.py    # 完整测试套件
```

### 核心方法

| 方法 | 用途 | 实现状态 |
|------|------|---------|
| `execute(context_package)` | 主入口；编排 5 阶段流水线 | ✅ 完整 |
| `search_similar_requirements(query_text)` | 通过 `/api/knowledge/search` 进行 RAG 语义搜索 | ✅ 完整（含降级方案）|
| `query_dependencies(req_id)` | Neo4j 服务拓扑查询 | ✅ 完整（优雅降级）|
| `query_related_prs(query_text)` | 查找相关的 GitHub PRs/Issues | ⚠️ Stub（返回 `[]`）|
| `fuse_knowledge(...)` | 将所有来源整合为知识包 | ✅ 完整 |
| `summarize_similar_requirements(requirements)` | LLM 总结；降级到模板 | ✅ 完整 |
| `_extract_code_patterns(similar_reqs)` | 从元数据标签提取模式 | ✅ 完整 |
| `_assess_risks(similar_reqs)` | 将标签映射到风险类别 | ✅ 完整 |
| `_estimate_complexity(...)` | 计算复杂度分数和工作量估算 | ✅ 完整 |
| `_calculate_quality_score(knowledge_package)` | 评估知识丰富度（0-1）| ✅ 完整 |

### 子模块

**`RAGRetriever`** (`a2/rag_retriever.py`)
- 主路径：查询 MC Backend `/api/knowledge/search` 端点（pgvector embeddings）
- 降级方案：静态知识库（3 个硬编码示例）
- 返回最多 5 个相似需求及其相似度分数

**`ConflictDetector`** (`a2/conflict_detector.py`) ⚠️ Stub
- 预期功能：检测跨规格的字段/约束冲突
- 当前实现：返回空列表

**`FeasibilityAssessor`** (`a2/feasibility.py`) ⚠️ Stub
- 预期功能：深度技术可行性分析
- 当前实现：基于关键词的 `is_technically_feasible` 启发式判断

---

## 输入/输出接口

### 输入: `context_package` (dict)

从 `context_build` activity 传递的预期结构：

```python
{
    "requirement_draft": {
        "id": str,                    # UUID
        "title": str,                 # 例如："添加用户认证"
        "domain": str,                # 例如："auth", "payment"
        "entities": [str],            # 例如：["User", "Session"]
        "description": str            # (可选)
    },
    "message": str                    # 原始用户消息（降级方案）
}
```

### 输出: 结果字典

```python
{
    "status": "completed",
    "req_id": str,                           # 需求 UUID
    "similar_requirements_count": int,       # 找到的数量（0-5）
    "dependencies_count": int,               # Neo4j 拓扑边数
    "related_prs_count": int,                # 始终为 0（stub）
    "quality_score": float,                  # 0.0-1.0
    "knowledge_package": {
        "analyzed_at": str,                  # ISO 8601 时间戳
        "query_text": str,                   # 使用的搜索查询
        "similar_requirements": [
            {
                "id": str,
                "title": str,
                "similarity": float,         # 0.0-1.0
                "metadata": {
                    "tags": [str],           # 例如：["async", "redis"]
                    "complexity": str,       # "low"|"medium"|"high"
                    "patterns": [str]
                }
            }
        ],
        "code_patterns": [str],              # 提取的模式
        "risks": [
            {
                "risk": str,                 # 例如："并发问题"
                "description": str,
                "severity": str              # "high"|"medium"|"low"
            }
        ],
        "suggested_approach": str,           # LLM 生成或降级模板
        "estimated_complexity": {
            "score": float,                  # 0.0-1.0
            "level": str,                    # "low"|"medium"|"high"
            "estimated_days": int,           # 3-20 天
            "rationale": str
        },
        "dependencies": [
            {
                "service": str,              # 源服务
                "downstream": str            # 依赖服务
            }
        ],
        "related_prs": []                    # 始终为空（stub）
    }
}
```

---

## 依赖和集成

### 外部服务

| 服务 | 用途 | 端点/配置 | 降级行为 |
|------|------|----------|----------|
| **MC Backend** | Pgvector 语义搜索 | `MC_BACKEND_URL` + `/api/knowledge/search` | 使用静态知识库（3 个硬编码示例）|
| **Neo4j** | 服务依赖拓扑 | `NEO4J_URL`, `NEO4J_USER`, `NEO4J_PASSWORD` | 跳过依赖查询；记录警告；继续执行 |
| **LLM Provider** | 总结生成 | 通过 `llm_provider` 使用 `DEEPSEEK_*` 环境变量 | 模板降级："基于 {N} 个相似需求..." |
| **PostgreSQL** | PR/Issue 查询 | 通过 MC Backend（未来）| Stub 返回空列表 |

### 内部依赖

**基类：** `BaseAgentWorker` (`base_worker.py`)
- NATS 事件总线集成（`self.nc`）
- LLM 调用抽象（`call_llm()` 含重试/降级）
- 状态上报（`report_status()`）
- 活动记录用于 SSE 流式传输
- OpenTelemetry 追踪

**LLM Provider：** `llm_provider` 包
- 任务类型：`"knowledge_analysis"`
- 模型：DeepSeek（可通过环境变量配置）
- 超时：45 秒
- Temperature：0.7

---

## 配置

### 环境变量

```bash
# MC Backend
MC_BACKEND_URL=http://localhost:8000      # Backend API 基础 URL

# Neo4j（可选）
NEO4J_URL=bolt://localhost:7687           # 图数据库 URL
NEO4J_USER=neo4j                          # 用户名
NEO4J_PASSWORD=<secret>                   # 密码

# LLM Provider
DEEPSEEK_API_KEY=<secret>                 # API 密钥
DEEPSEEK_BASE_URL=https://uniapi.ruijie.com.cn  # 端点
DEEPSEEK_MODEL=deepseek-v4-pro-202606     # 模型标识符
```

### 超时和限制

- **工作流超时：** 5 分钟（来自 `requirement_workflow.py`）
- **RAG 搜索限制：** Top 5 结果
- **LLM 超时：** 45 秒（含重试）
- **复杂度分数范围：** 0.0-1.0
- **预估天数范围：** 3-20 天

---

## 可观测性

### Prometheus 指标

| 指标 | 类型 | 标签 | 用途 |
|------|------|------|------|
| `a2_rag_queries_total` | Counter | `query_type`, `status` | RAG 查询尝试次数（semantic_search, execute）|
| `a2_knowledge_quality_score` | Gauge | - | 整体知识包质量（0-1）|
| `a2_execution_duration_seconds` | Histogram | `phase` | 各阶段执行时间（semantic_search, dependency_query, related_prs_query, knowledge_fusion, total）|

### 日志

- **级别：** 正常流程用 INFO，降级用 WARNING，失败用 ERROR
- **关键事件：**
  - RAG 搜索成功/失败
  - Neo4j 连接问题
  - LLM 降级到模板
  - 知识融合完成
  - 质量分数计算

### 活动流（SSE）

通过 `self.record_activity()` 记录的活动：
- "搜索相似需求..."
- "查询依赖拓扑..."
- "知识融合..."
- 最终结果（含质量指标）

---

## 测试

### 测试套件: `a2/test_knowledge_analyst.py`

覆盖范围：
- ✅ RAG retriever API 成功路径
- ✅ RAG retriever 降级到静态知识库
- ✅ 从标签提取代码模式
- ✅ 风险评估映射（5 个风险类别）
- ✅ 复杂度估算（低/高场景）
- ✅ 质量分数计算逻辑
- ✅ 基于 LLM 的总结
- ✅ 模板降级总结
- ✅ Neo4j 优雅降级
- ✅ 端到端知识融合

### 测试命令

```bash
cd repos/agent-workers
python -m pytest a2/test_knowledge_analyst.py -v
```

---

## 工作流集成

### 状态机位置

**来自 `requirement_workflow.py`：**
- **触发事件：** `requirement.drafted`
- **进入状态：** `RS.ANALYZING`
- **超时时间：** 5 分钟
- **下一个 Gate：** Gate 0（设计前的人工审批）
- **下一个状态：** `RS.DESIGNING`（A3 UI 生成）

### Temporal Workflow Activities

**调度流程：**
1. `context_build` → 准备输入包
2. `dispatch_agent` → 通过 NATS 执行 A2
3. `store_agent_result` → 持久化知识包（A2 不在跳过列表中）
4. `gate_await` → 等待 Gate 0 审批

### NATS 事件总线

**订阅：** `agent.a2.execute`（来自工作流调度）
**发布：** `agent.a2.completed`（成功执行后）

---

## 已知限制和未来工作

### Stub 实现

1. **`query_related_prs()`** ⚠️
   - 当前：返回空列表
   - 未来：通过 MC Backend 查询 PostgreSQL 中的相关 GitHub PRs/Issues
   - 影响：缺少交叉引用智能

2. **`ConflictDetector`** ⚠️
   - 当前：始终返回空冲突
   - 未来：检测多个规格间的字段/约束冲突
   - 影响：无法警告冲突的需求

3. **`FeasibilityAssessor`** ⚠️
   - 当前：简单的关键词启发式
   - 未来：结合架构约束的深度技术可行性分析
   - 影响：技术风险评估有限

### 改进机会

1. **缓存层**
   - 问题：相似需求的重复查询每次都会命中后端
   - 方案：Redis 缓存 RAG 结果（TTL: 1 小时）

2. **质量分数校准**
   - 问题：质量分数公式基于启发式
   - 方案：根据相似需求的历史成功率进行校准

3. **复杂度估算准确性**
   - 问题：线性公式（3 + similar_count * 3 + depth * 2）过于简化
   - 方案：在历史（需求 → 实际工作量）对上训练回归模型

4. **LLM 提示工程**
   - 问题：总结模板过于通用
   - 方案：为 auth、payment、messaging 等领域定制提示

---

## 验证策略

### 人工测试检查清单

1. **正常路径：**
   - 从包含 `title`、`domain`、`entities` 的草案需求开始
   - 验证 MC Backend 返回相似需求
   - 确认 Neo4j 返回依赖拓扑
   - 检查知识包结构
   - 验证质量分数 > 0.5

2. **降级路径：**
   - 停止 MC Backend → 应使用静态知识库
   - 停止 Neo4j → 应优雅地跳过依赖查询
   - 停止 LLM provider → 应使用模板总结

3. **边界情况：**
   - 空需求草案 → 应使用 `message` 字段
   - 未找到相似需求 → 应返回空列表
   - 零依赖 → 应返回空列表
   - 所有服务都停机 → 应完成并返回最小知识包

### 集成测试

```bash
# 启动依赖
docker-compose up -d mc-backend neo4j

# 运行 A2 集成测试
cd repos/agent-workers
python -m pytest a2/test_knowledge_analyst.py::TestA2KnowledgeAnalyst::test_execute_with_context -v

# 验证指标
curl http://localhost:9090/metrics | grep a2_
```

---

## 总结

**A2 的作用：** 通过查询 pgvector embeddings、Neo4j 拓扑和 LLM 分析，用历史上下文、技术情报和复杂度估算来丰富需求草案。

**关键文件：**
- `repos/agent-workers/a2_knowledge_analyst.py` — 主实现
- `repos/agent-workers/a2/rag_retriever.py` — 语义搜索接口
- `repos/orchestrator/workflows/requirement_workflow.py` — 工作流集成

**Gate 0 之后的后续步骤：** 知识包被 A3（UI 生成器）和 A4（规格编写器）消费，用于做出明智的设计决策。

**质量门槛：**
- 找到相似需求 → 质量分数 > 0.3
- 生成 LLM 总结 → 质量分数 > 0.5
- 完整知识包（模式 + 风险 + 复杂度）→ 质量分数 > 0.7
