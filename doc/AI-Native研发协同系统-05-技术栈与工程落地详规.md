# AI Native 研发协同系统 · 技术栈与工程落地详规

> **文档定位**：工程落地向 · 面向平台工程师、SRE、后端/基础设施团队
> **回答的问题**：这系统到底怎么写出来？用什么语言/框架/中间件？各个 Agent 跑在哪里？Dev Agent 用 Claude Code 还是自研？自动化测试系统怎么搭？Event Bus 选 NATS 还是 Kafka？怎么部署、怎么扩容、一块 GPU 够不够？
> **配套文档**：`02 · 架构与设计规格`、`04 · Agent 协作与触发机制详规`、`00 · 总纲与导读`
> **版本**：v1.0

---

## 〇、决策总表（TL;DR）

| 决策项 | 选型 | 一句话理由 |
|---|---|---|
| **编排引擎** | **Temporal**（主）+ LangGraph（辅） | 确定性工作流需要持久化执行保证；LLM 调用链用 LangGraph 做可观测性更好的 DAG |
| **Event Bus** | **NATS JetStream** | 比 Kafka 轻一个数量级、比 Redis Streams 语义更完整；适合百级 Agent 的中等吞吐场景 |
| **Dev Agent 运行时** | **Claude Code Agent SDK**（`claude -p` + `--output-format json`） | 不重新发明"AI 写代码"；唯一需要 Anthropic 的场景——Claude Code 的工具链/agent loop/MCP 生态无可替代 |
| **Auto Test Agent** | **自研 Python Wrapper + Playwright + Jest + Stryker** | 测试执行是确定性逻辑，不需要 LLM；Critic 的变异测试用 Stryker Mutator |
| **其他 Agent（P1–P3, P5, Sidecar）** | **自研 Python/TS Agent Worker**（LLM Provider 抽象层 → 默认 DeepSeek） | 读文档/写 Spec/评估/检索类任务走 DeepSeek（便宜）；多模态走千问 VL / GLM-5V |
| **LLM Provider 策略** | **DeepSeek（主力）+ 千问 VL（多模态）+ GLM-5V（多模态备用）+ Anthropic（Dev Agent 专用）** | 一行 YAML 切换；非 Dev Agent 成本可降 ~80%（见 §十五） |
| **Context Builder (RAG)** | **pgvector + 自定义 retrieval pipeline** | 轻量、与 PostgreSQL 共享运维；不需要 Elasticsearch 的复杂度 |
| **知识图谱** | **Neo4j** | Agent 间依赖、API 契约、代码模块关系是天然的图 |
| **Worker 沙箱** | **Firecracker microVM**（via Fly Machines 或自建） | 比 Docker 更安全，启动 <200ms；每任务一 VM |
| **MCP Gateway** | **自研轻量 Gateway**（Go/Node） | 聚合多 Worker 的 MCP Server，统一认证/限流/审计 |
| **可观测性** | **OpenTelemetry + Grafana Stack**（Tempo + Mimir + Loki） | 与 04 §十 的 Span/Metrics/Logs 设计直接对应 |
| **语言分布** | **TypeScript**(MC 前端 + MCP Gateway) + **Python**(Orch + Agent Workers) + **Go**(Event Bus 侧车、高性能组件) | 各取所长 |

---

## 一、编排引擎：Temporal + LangGraph 双引擎

### 1.1 为什么不是纯 LangGraph？

LangGraph 的定位是 **LLM 应用的状态图**——Agent 的 think/tool_call/reflect 循环建模非常自然。但它有一个生产级短板：**没有持久化执行保证**。如果 Orch 进程挂了，正在跑的 DAG 状态就丢了，正在 `await` 的 `gate.2.approved` 永远收不到。

Temporal 解决的就是这个——它是 **Workflow as Code** 引擎，提供：
- **持久化执行**：工作流状态写进数据库，进程崩溃后从断点恢复
- **定时器/超时**：`await_gate_approval(2h_timeout)` → 超时自动触发 SLA 升级
- **重试/补偿**：Saga 模式的事务补偿（比如 Dev Agent 已 push 了代码但后续 Gate 3 打回，怎么回滚）
- **多语言 SDK**：Go/Java/Python/TS，Orch 可以与各 Agent Worker 解耦

### 1.2 为什么 LangGraph 还在栈里？

Temporal 擅长"确定性步骤的编排"，但 **LLM 调用链本身是高度非确定性的**——同样输入可能产出不同代码。LangGraph 的价值在于：
- **Agent 内部的 think → tool_call → observe → reflect 循环**建模优于 Temporal
- **流式输出**（streaming token）天然支持
- **Checkpointing** 支持"回退到上一步思考"（LangGraph 的 `interrupt` 机制）

### 1.3 分工

```
Temporal Workflow（外层）
├── 状态机推进: draft → analyzing → designing → ... → done
├── Gate 审批: await_gate_approval(timeout, sla_escalation)
├── 熔断判定: loop_round_counter ≤ 3 else trip
├── Context Builder 调用: context.build(targetAgent, reqId)
├── 下发任务: dispatch_to_agent_worker(agentId, contextPackage)
│
└── 每个 Agent Worker 内部（如果需要 LLM 循环）
    └── LangGraph StateGraph
        ├── node: think (调用 Claude API)
        ├── node: tool_call (调 Skill API)
        ├── node: observe (收集环境信号)
        ├── node: reflect (Inner Auditor / Critic 判定)
        ├── conditional_edge: pass? → exit : retry_round ≤ 2? → think
        └── 超限 → raise LoopTrippedException → Temporal 收到 → 熔断
```

### 1.4 Temporal 部署拓扑

```yaml
Temporal Server:         # 托管或自建
  - 1× Temporal Server (Go binary, 含 Frontend + History + Matching)
  - 1× PostgreSQL 或 Cassandra（持久化 workflow state）
  
Temporal Workers:        # 我们写的业务代码
  - 2× Orch Worker (Python, 跑 Temporal Workflow + Activity)
  - N× Agent Worker (Python/TS, 跑 LangGraph + API 调用)
```

---

## 二、Dev Agent：Claude Code CLI 还是自研？

### 2.1 结论：用 Claude Code CLI，不重新发明

Claude Code 已经是业界最好的 coding agent，具备：
- 完整的 **ReAct 循环**（think → tool_call → observe → next）
- 原子化工具：`Read` / `Write` / `Edit` / `Bash` / `Grep` / `Glob`
- `CLAUDE.md` 项目记忆注入（我们通过 Context Builder 动态生成 `CLAUDE.md`）
- 子 Agent 拆分（`/agents` 命令，与我们的"并行 Dev Agent"理念天然匹配）
- 终端报错驱动的自修复（stderr → 自动分析 → 自动修复 —— 天然"环境裁判"）

**自己实现一个同等水平的 coding agent，工作量是重新造一个 Claude Code**——包括权限管理、沙箱安全、Git 集成、LSP 集成、子 Agent 编排、token 预算、上下文压缩等。这条路没有任何差异化价值。

### 2.2 Claude Code 无头模式（Agent SDK）

**2026 年 6 月的最新 API 口径**：Claude Code 已经提供了正式的 **Agent SDK**（`claude -p` / `--print` 非交互模式），而不是之前猜测的 `--print --output-format json` 组合。

正确用法（来自 Claude Code 官方文档 `code.claude.com/docs/en/headless`）：

```bash
# 基础非交互执行（-p = --print）
claude -p "Find and fix the bug in auth.py" --allowedTools "Read,Edit,Bash"

# 纯净模式（--bare）：跳过 MCP/hooks/skills/CLAUDE.md 自动发现，保证 CI 环境可复现
claude --bare -p "Summarize this file" --allowedTools "Read"

# 结构化 JSON 输出
claude -p "Summarize this project" --output-format json
# → 返回 { result, session_id, total_cost_usd, usage, ... }

# Schema 约束输出
claude -p "Extract function names from auth.py" \
  --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}}}'

# 流式输出
claude -p "Explain recursion" --output-format stream-json --verbose --include-partial-messages

# 继续会话（跨多次 claude -p 调用）
claude -p "Review this codebase" 
claude -p "Now focus on DB queries" --continue
claude -p "Summarize all issues" --continue
```

**与本系统的集成方式**：我们在 `ai-task` Wrapper 里做几件事：

1. `ai-task start TASK_ID` → Context Builder 拉上下文 → 写入 `/tmp/task_context.md`
2. 调 `claude --bare -p "<prompt>" --output-format json --allowedTools "Read,Edit,Bash(npm*),Bash(npx*),Bash(git*),Bash(tsc*),Bash(eslint*),Grep,Glob"` 
3. 解析返回的 JSON：`result` 字段是最终输出，`total_cost_usd` 用于成本追踪，`session_id` 用于 OTEL Span 关联
4. 上报 `agent.status.changed` + `task.completed` 到 Event Bus

**Agent SDK（Python/TypeScript 包）**：除了 CLI 模式，Claude Code 还提供 Python 和 TypeScript SDK。对于 Dev Agent（#9）仍用 Anthropic——因为 Claude Code CLI 的代码工具链生态是唯一成熟的；其余 Agent Worker 走 LLM Provider 抽象层，默认 DeepSeek，成本更低。

### 2.3 Claude Code vs 自研：分界线

| 场景 | 用什么 | 理由 |
|---|---|---|
| **写代码**（读文件 → 改文件 → Lint → 修复 → commit） | Claude Code CLI | 这是 Claude Code 的核心领地，比自研强一个数量级；Dev Agent 唯一保留 Anthropic 的场景 |
| **写 Spec / 评审 / 评估**（读文档 → 生成 PRD / OpenAPI / 评估报告） | 自研 Python Worker（调 LLM Provider → 默认 DeepSeek） | 不需要文件系统/终端/Git 工具，只需要 LLM + Skill API |
| **CI/CD / 发布**（触发构建 → 部署 → 监控） | 自研 Python Worker（确定性脚本） | 无 LLM 调用，纯 DevOps 自动化 |
| **知识检索 / 变更传播** | 自研 Python Worker（RAG + 图遍历） | 确定性逻辑为主 |
| **多模态**（UI 截图分析/设计稿对比/视觉回归分析） | 自研 Python Worker（调 LLM Provider → 千问 VL / GLM-5V） | 国产多模态模型性价比远高于 Anthropic Vision |

**结论**：15 个 Agent 中，只有 **#9 Dev Agent** 使用 Claude Code CLI。其余 14 个 Agent 全部是自研 Worker——因为它们的工作是"读文档/写 Spec/调 API/跑脚本/做 RAG"，不是"读写代码仓库"。

---

## 三、各 Agent 运行时形态一览

| # | Agent | 运行时 | LLM 调用方式 | 核心依赖 |
|---|---|---|---|---|
| ⓪ | **Orchestrator** | Temporal Workflow (Python) | LLM Provider 抽象层 → 默认 DeepSeek（仅复杂度分类 + Gate 判定等需 LLM 的步骤） | Temporal SDK, pgvector |
| 1 | Requirement Intake | Python Worker + LangGraph | LLM Provider → DeepSeek | NLP 库, Sandpack |
| 2 | Knowledge Analyst | Python Worker | LLM Provider → DeepSeek + Embedding (千问/voyage) | pgvector, Neo4j |
| 3 | UI Generator | Python Worker | LLM Provider → DeepSeek | Sandpack, 像素对比引擎 |
| 4 | Spec Writer | Python Worker | LLM Provider → DeepSeek | OpenAPI 库, ERD 生成 |
| 5 | Design Review Panel | Python Worker × 3 并行 | LLM Provider → DeepSeek（三个独立 prompt） | UX 规则库, N+1 检测规则 |
| 6 | Spec Decomposer | Python Worker | LLM Provider → DeepSeek | DAG 库 |
| 7 | Test Case Generator | Python Worker | LLM Provider → DeepSeek | Jest/Playwright 模板 |
| 8 | Architecture Expert | Python Worker | LLM Provider → DeepSeek | 架构红线规则库 |
| **9** | **Dev Agent（⭐）** | **Claude Code CLI** + AITP Wrapper (Node) | **Claude API 直调**（Dev Agent 唯一场景——需完整代码工具链） | Claude Code, Git, Lint/TS/Security 工具链 |
| **11** | **Auto Test Agent（⭐）** | **Python Wrapper + Jest/Playwright + Stryker** | LLM Provider（弱断言/失败归因用 DeepSeek；截图分析用千问 VL / GLM-5V） | Playwright, Jest, Stryker Mutator |
| 12 | Code Review Agent | Python Worker | LLM Provider → DeepSeek | Diff 解析, AST 分析 |
| 13 | Release Agent | Python Worker | 无 LLM（金丝雀 + Prometheus 查询 + K8s API） | K8s, Prometheus, Feature Flag SDK |
| 14 | Knowledge Keeper | Python Worker | Embedding API (千问/voyage) | pgvector, Neo4j, S3 |
| 15 | Change Propagation | Python Worker | 无 LLM（图遍历 + 防抖） | Neo4j |

---

## 四、自动化测试系统实现方案

这是系统里最"工程化"的组件——不像 Dev Agent 需要 LLM 写代码，测试系统大部分是确定性工具链。

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│               Auto Test Agent (#11)                      │
│                                                         │
│  ┌─────────────┐     ┌──────────────────────────────┐  │
│  │ Tester       │     │ Critic                       │  │
│  │ (Python Wrapper)│  │ (Python Wrapper + Claude API)│  │
│  │             │     │                              │  │
│  │ 调度执行:    │     │ 分析测试质量:                 │  │
│  │ - Jest      │ ──▶ │ - 弱断言检测 (Claude)        │  │
│  │ - Playwright│     │ - 变异测试 (Stryker)         │  │
│  │ - 收集结果   │     │ - 边界覆盖分析 (Claude)      │  │
│  └─────┬───────┘     └──────────┬───────────────────┘  │
│        │                        │                       │
│        ▼                        ▼                       │
│  ┌──────────────────────────────────────────────────┐   │
│  │                测试基础设施                          │   │
│  │                                                    │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │   │
│  │  │ Jest     │  │Playwright│  │ Stryker Mutator   │ │   │
│  │  │(单测/集成)│  │(E2E+截图)│  │ (变异测试引擎)     │ │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘ │   │
│  │                                                    │   │
│  │  ┌──────────────────────────────────────────────┐ │   │
│  │  │         Docker Staging 沙箱                    │ │   │
│  │  │  app + DB + Mock 服务                         │ │   │
│  │  └──────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Tester（执行者）——确定性脚本

技术栈：**Python subprocess wrapper + Jest + Playwright**

```python
# test_runner.py —— Auto Test Agent Tester 的核心
class TestRunner:
    def __init__(self, staging_url: str, test_assets: list, test_config: dict):
        self.staging_url = staging_url
        self.assets = test_assets
        self.parallel_workers = test_config.get("parallel", 4)
        self.timeout_per_case_ms = test_config.get("timeout_per_case", 30000)
    
    def run(self) -> TestResult:
        results = TestResult()
        
        # 1. 单元测试 + 集成测试 → Jest
        if self.assets.unit or self.assets.integration:
            jest_result = self._run_jest(
                test_files=self.assets.unit + self.assets.integration,
                workers=self.parallel_workers,
                timeout=self.timeout_per_case_ms,
                coverage=True,
                reporters=["json", "html"]
            )
            results.add(jest_result)
        
        # 2. E2E 测试 → Playwright
        if self.assets.e2e:
            playwright_result = self._run_playwright(
                test_files=self.assets.e2e,
                base_url=self.staging_url,
                workers=self.parallel_workers,
                trace="on-first-retry",
                video="retain-on-failure",
                screenshot="only-on-failure"
            )
            results.add(playwright_result)
        
        # 3. 视觉回归 → Playwright snapshot + pixelmatch
        if self.assets.visual:
            visual_result = self._run_visual_regression()
            results.add(visual_result)
        
        return results
    
    def _run_jest(self, test_files, workers, timeout, coverage, reporters):
        cmd = [
            "npx", "jest",
            "--maxWorkers", str(workers),
            "--testTimeout", str(timeout),
            "--json", "--outputFile", "/tmp/jest-result.json",
            "--coverage" if coverage else "--no-coverage",
        ] + test_files
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.workdir, timeout=600)
        return self._parse_jest_output(result)
    
    def _run_playwright(self, test_files, base_url, workers, trace, video, screenshot):
        cmd = [
            "npx", "playwright", "test",
            "--workers", str(workers),
            "--reporter=json",
        ] + test_files
        
        env = {**os.environ, "BASE_URL": base_url, "CI": "true"}
        result = subprocess.run(cmd, capture_output=True, env=env, cwd=self.workdir, timeout=900)
        return self._parse_playwright_output(result)
```

### 4.3 Critic（测试质量审查员）——LLM + Stryker

技术栈：**Python wrapper + Stryker Mutator + Claude API**

```python
# critic.py —— Auto Test Agent Critic 的核心
class TestCritic:
    def __init__(self, source_files: list, test_files: list):
        self.source_files = source_files
        self.test_files = test_files
    
    def evaluate(self, test_result: TestResult) -> CritiqueResult:
        critique = CritiqueResult()
        
        # 阶段 1: 弱断言检测（LLM 辅助）
        critique.weak_assertions = self._detect_weak_assertions(test_result)
        
        # 阶段 2: 变异测试（Stryker Mutator，确定性工具）
        critique.mutation_score = self._run_mutation_testing()
        
        # 阶段 3: 失败归因（LLM 辅助——只对失败用例）
        if test_result.failed:
            critique.root_causes = self._analyze_failures(test_result.failed_cases)
        
        # 阶段 4: 边界覆盖分析（LLM 辅助）
        critique.boundary_coverage = self._analyze_boundary_coverage(test_result)
        
        # 阶段 5: 去重检测
        critique.duplication = self._detect_duplicate_tests()
        
        critique.pass_ = (
            critique.mutation_score >= 70
            and len(critique.weak_assertions) == 0
            and critique.boundary_coverage >= 70
        )
        
        return critique
    
    def _run_mutation_testing(self) -> MutationResult:
        """用 Stryker Mutator 做变异测试——这是整个测试系统最耗时的操作"""
        config = {
            "mutator": {
                "plugins": ["typescript", "javascript"],
                "excludedMutations": ["StringLiteral"]  # 排除字符串变异，减少噪声
            },
            "thresholds": {
                "high": 80, "low": 60,
                "break": 50   # 低于 50 直接判定不通过
            },
            "timeoutMS": 600000,  # 10 分钟超时
            "concurrency": 4
        }
        
        # Stryker 在 Docker 沙箱内运行，避免污染主机
        cmd = ["npx", "stryker", "run", "--concurrency", "4"]
        result = subprocess.run(cmd, capture_output=True, timeout=config["timeoutMS"])
        
        return MutationResult(
            score=parse_stryker_score(result.stdout),
            killed=parse_stryker_killed(result.stdout),
            survived=parse_stryker_survived(result.stdout),
            pass_=parse_stryker_score(result.stdout) >= 70
        )
    
    def _detect_weak_assertions(self, test_result):
        """用 Claude 分析测试代码，找出弱断言模式"""
        prompt = f"""分析以下测试代码，找出所有弱断言。弱断言的定义：
        1. 只检查 statusCode / HTTP 200，不检查响应体
        2. expect(true).toBe(true) 或类似的恒真断言
        3. expect(x).toBeDefined() / notNull 但未验证具体值
        4. 无断言（测试名和期望不符）
        
        测试代码：
        {json.dumps(test_result.test_code, indent=2)}
        
        返回 JSON: {{"weak_assertions": [{{"file", "line", "assertion", "issue_type", "suggestion"}}]}}
        """
        
        response = claude_api_call(prompt, max_tokens=2000)
        return parse_json(response)

    def _analyze_failures(self, failed_cases):
        """用 Claude 做失败归因——这是 LLM 提供真正增量价值的地方"""
        prompt = f"""分析以下测试失败，给出根因分类和修复建议。不要给"再试一次"的建议。
        
        失败用例：
        {json.dumps(failed_cases, indent=2)}
        
        相关源码：
        {self._read_source_files()}
        
        返回 JSON: {{"root_causes": [
            {{"case_name", "category": "missing_validation|type_mismatch|null_ref|race_condition|api_mismatch|ui_drift|timeout", "explanation", "likely_file", "fix_hint", "confidence": 0.0-1.0}}
        ]}}
        """
        
        response = claude_api_call(prompt, max_tokens=3000)
        return parse_json(response)
```

### 4.4 变异测试的性能策略

Stryker 在大型项目里可能跑几十分钟——所以必须做策略优化：

| 策略 | 说明 | 适用场景 |
|---|---|---|
| **增量变异** | 只对 Git diff 涉及的文件做变异（`stryker --mutate changedFiles`） | 所有 PR |
| **采样变异** | Stryker 的 `--mutate` 支持 glob，只变异高利用率模块 | 大项目 |
| **超时熔断** | 总时长 > 10min → 返回当前得分 + 标记 `MUTATION_PARTIAL` | 所有 |
| **快速通道跳过** | §十一快速通道完全跳过变异测试 | simple 需求 |
| **离线变异** | 核心模块的全量变异安排在夜间定时跑，结果存库供次日引用 | 长期策略 |
| **并行 VM** | 每个文件一个 Firecracker VM，并行变异 | 大项目 |

### 4.5 视觉回归 Diff 引擎

```yaml
技术方案:
  - Pixelmatch (npm) — 像素级图片对比，输出 diff 热力图
  - 集成到 Playwright snapshot 流程
  - 差异阈值分级（来自 03）:
      <2%:  自动忽略
      2-5%: 建议修复
      5-10%:默认选中
      >10%: 强制阻止
  - Diff 热力图存入 S3，URL 写入 TestExecution.visualDiffs
```

---

## 五、Event Bus 选型：NATS JetStream

### 5.1 为什么是 NATS 而不是 Kafka？

| 维度 | NATS JetStream | Kafka | Redis Streams |
|---|---|---|---|
| **部署复杂度** | 单二进制 20MB，零依赖 | ZooKeeper/controller + Broker × N | 已有的 Redis 实例即可 |
| **吞吐量** | ~10M msg/s（单节点） | ~100M msg/s（集群） | ~1M msg/s |
| **延迟 P99** | <1ms | 10–100ms | <1ms |
| **持久化** | JetStream（文件或内存） | 原生持久化到磁盘 | AOF/RDB + Stream |
| **消费者组** | ✅（JetStream Consumer） | ✅ | ✅（Consumer Group） |
| **消息重放** | ✅（按时间/序列号） | ✅ | ✅ |
| **运维负担** | 极低 | 高 | 低（已有 Redis 的话） |

对本系统而言，NATS 是最优解：
- **百级 Agent、千级 req/s**——远远低于 Kafka 才需要的吞吐量级
- **零运维负担**——和我们的 Go/Node 服务一起部署，不需要专门的 Kafka 运维团队
- **JetStream 提供的持久化 + 消费者组 + 消息重放**，完全够用
- **Kafka 更适合**的场景是"日均数十亿事件 + 多团队多消费者 + 需要事件溯源"——本系统远未到那个规模

### 5.2 Event Bus 部署

```yaml
NATS Cluster (3 节点, 高可用):
  每个节点: 2 vCPU, 4 GB RAM
  JetStream 持久化: 挂载 50 GB SSD
  客户端: nats.py (Python), nats.ws (Node/浏览器 SSE 桥接)

事件流主题设计:
  agent.{agent_id}.status        # Agent 状态变更（活动直播）
  gate.{gate_id}.{action}        # 审批操作
  requirement.{req_id}.{action}  # 需求状态变更
  artifact.{req_id}.produced     # 产出物生成
  loop.{scope}.tripped           # 熔断事件
  system.metrics                 # 遥测指标流
```

---

## 六、Context Builder (RAG) 实现方案

### 6.1 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| **向量存储** | **pgvector** (PostgreSQL 扩展) | 和需求/Agent 状态共享一个 DB，零额外运维；支持 IVFFlat/HNSW 索引；性能够用 |
| **Embedding 模型** | **Voyage AI** `voyage-code-3`（代码）+ `voyage-3`（文档） | 比 OpenAI Embedding 在代码检索上好 ~15%；或自托管 `stella_en_1.5B` |
| **文本 Embedding** | `voyage-3` 或 `text-embedding-3-large` | — |
| **全文检索** | PostgreSQL 内置 `tsvector` + `pg_trgm` | 不需要 Elasticsearch；混合检索（向量 + 关键词）用 pgvector + tsvector 并联查询 |
| **分块策略** | **语义分块**（按函数/类/API 边界切分，非固定 token 大小） | 代码检索的核心——按 AST 切分 >> 按 token 切分 |

### 6.2 RAG Pipeline

```python
# context_builder/rag_pipeline.py
class RAGPipeline:
    """
    Context Builder 的 SELECT 阶段（04 §8.2）在工程上就是这个 Pipeline。
    """
    
    def retrieve(self, query: str, filters: dict, top_k: int = 10) -> list:
        # Step 1: 嵌入查询
        query_embedding = self.embedder.embed(query)
        
        # Step 2: 混合检索（向量 + 关键词）
        results = self.db.execute("""
            SELECT 
                doc_id, title, content, doc_type, file_path,
                (1 - (embedding <=> %s::vector)) AS vector_score,  -- 余弦相似度
                ts_rank(search_vector, plainto_tsquery('english', %s)) AS keyword_score,
                (1 - (embedding <=> %s::vector)) * 0.7 
                    + ts_rank(search_vector, plainto_tsquery('english', %s)) * 0.3 
                    AS combined_score
            FROM knowledge_chunks
            WHERE 
                (filters.doc_types IS NULL OR doc_type = ANY(%s))
                AND (filters.project IS NULL OR project = %s)
                AND (filters.date_range IS NULL OR updated_at BETWEEN %s AND %s)
            ORDER BY combined_score DESC
            LIMIT %s
        """, [query_embedding, query, query_embedding, query, 
              filters.doc_types, filters.project, 
              filters.date_from, filters.date_to, top_k])
        
        return self._format_results(results)
    
    def semantic_code_search(self, task_description: str, repo_path: str, top_k: int = 5):
        """代码语义检索——给 Dev Agent 找相关代码"""
        embedding = self.embedder.embed(task_description, model="voyage-code-3")
        
        return self.db.execute("""
            SELECT file_path, chunk_content, start_line, end_line,
                   (1 - (embedding <=> %s::vector)) AS similarity
            FROM code_chunks
            WHERE repo_path = %s AND similarity > 0.7
            ORDER BY similarity DESC
            LIMIT %s
        """, [embedding, repo_path, top_k])
```

### 6.3 代码分块策略

```
对 TypeScript/Python 等主流语言:
  1. AST 解析 → 识别 function / class / method / interface 边界
  2. 每个顶层定义 = 1 chunk
  3. Chunk metadata: { file_path, symbol_name, start_line, end_line, 
                        dependencies, exported }
  4. Embedding = 函数签名 + 注释 + JSDoc/docstring 的嵌入
  5. 检索时返回整个 chunk（包含实现体），而不是截断的片段
```

---

## 七、Worker Sandbox（Agent 执行环境）

### 7.1 为什么沙箱是必须的

Dev Agent 会执行：
- `npm install`（可能下载恶意包）
- `git push`（可能推到错误分支）
- 文件系统读写（可能删除项目文件）
- 终端命令（可能 `rm -rf`）

**绝对不能在生产环境的开发者机器或共享服务器上裸跑 Agent**。

### 7.2 沙箱方案：Firecracker microVM

| 层级 | 方案 | 适用 |
|---|---|---|
| **云端无头 Agent**（Codex/沙箱模式） | **Firecracker microVM**（每个任务一个 VM，启动 <200ms，内核级隔离） | 后台并行开发 |
| **本地开发者 Agent**（Claude Code/Cursor） | 开发者本机 + Git 分支隔离 + pre-push Hook 保护 | 人工在回路 |
| **CI/CD 沙箱** | Docker container（GitHub Actions Runner 或自建） | 构建+测试 |
| **高危操作** | 额外 VM 层 + 命令白名单（禁止 `rm -rf`、`git push --force`、`DROP TABLE` 等） | 全场景 |

部署选择：
- **小团队**（<10 人）：直接买 Fly Machines（Firecracker 托管版），按任务计费
- **大团队**（>50 人）：自建 Firecracker 集群（用 `firecracker-containerd` 或 Kata Containers）

### 7.3 Sandbox 生命周期

```
1. Orch 调度 Dev Agent:
   → 创建 Firecracker VM
   → Git clone 仓库（sparse checkout 只拉相关文件）
   → 注入上下文（CLAUDE.md + Spec + 测试资产）
   → 执行 Claude Code CLI
   → 产出 diff → 传回主机
   → 销毁 VM
   
   整个过程 3–5 分钟（含 VM 启动 200ms + Git clone + Claude Code 执行）

2. VM 网络策略:
   - 只能出站到 npm registry / Git 仓库 / Anthropic API
   - 不能访问内网（除非白名单）
   - 所有外发流量经审计代理
```

---

## 八、MCP Gateway（工具接入层）

### 8.1 为什么需要 Gateway

系统有三种 Worker（Claude Code CLI / IDE 插件 / 云端 Agent），每个都有自己的工具集。如果每个 Worker 自己直接访问 Skill API（§七定义的 31 个 API），就会出现：
- 认证碎片（每个 Worker 各自配 API Key）
- 限流失控（某个 Dev Agent 疯狂调 RAG 把向量库打爆）
- 审计盲区（不知道是哪个 Agent、在哪个需求里调了哪个 Skill）

**MCP Gateway 是统一入口**：一个实现了 MCP（Model Context Protocol）Server 规范的反向代理，Worker 通过 MCP Client 协议调 Gateway，Gateway 再路由到具体 Skill API。

### 8.2 Gateway 架构

```yaml
技术栈: TypeScript (Hono) 或 Go (net/http)
          选 Go——更好并发、更低内存，适合做网关

功能:
  - MCP Server 协议实现（tools/list, tools/call, resources/list, prompts/list）
  - JWT 认证（Agent ID + Req ID 绑定，防止跨需求调用）
  - 限流（per Agent, per Req, per Skill）
  - 审计日志（每次 tools/call 记录 → OTel Span → Loki）
  - Skill 路由（根据 tool_name 路由到具体 Python/Node 微服务）
  - 响应压缩（大文件 diff 在 Gateway 层 gzip）

部署:
  - 2× Go 实例（K8s Deployment, HPA 自动扩缩）
  - 前置 Envoy 或 Nginx 处理 TLS
```

### 8.3 Worker 调 MCP 的方式

```
Claude Code CLI Worker:
  ├── 内置 MCP Client
  ├── 配置 .claude/mcp.json:
  │     { "ai-native-gateway": { "url": "https://mcp-gw.internal/otlp", "token": "..." } }
  └── Claude Code 里自然调 Skill: get_task_context / report_progress / submit_artifact

Python Agent Worker:
  ├── 使用 anthropic-sdk 的 tool 机制
  ├── tool 定义从 MCP Gateway tools/list 动态拉取
  └── Agent 调 tool → Gateway 路由到实际 Skill API

IDE Worker (Cursor/VSCode):
  └── MCP Server 跑在插件本地 → 代理到云端 Gateway
```

---

## 九、知识图谱（Neo4j）

### 9.1 为什么需要图数据库

关系型数据库可以存 ERD 和 API 契约，但以下查询在 SQL 里是递归 CTE 的地狱，在图里是几行 Cypher：

- "这个 API 的响应字段变更影响了哪些前端组件？"（沿图遍历 API → 组件 → 测试）
- "哪些需求依赖这个已废弃的公共组件？"（反向引用查询）
- "这个 Agent 的产出物被哪些下游 Agent 消费了？"（沿 Event 流追溯）

### 9.2 图模型（简化）

```cypher
// 节点类型
(:Requirement {id, title, status})
(:Spec {id, version})
(:API {method, path})
(:Model {name, table_name})
(:Component {name, file_path, type})   // 前端/后端组件
(:TestCase {id, type})
(:Agent {id, type})
(:Artifact {id, type, url})

// 关系
(:Requirement)-[:HAS_SPEC]->(:Spec)
(:Spec)-[:DEFINES]->(:API)
(:API)-[:PRODUCES|CONSUMES]->(:Model)
(:Model)-[:REFERENCES]->(:Model)
(:Component)-[:CALLS]->(:API)
(:TestCase)-[:COVERS]->(:Component)
(:TestCase)-[:COVERS]->(:API)
(:Agent)-[:PRODUCED]->(:Artifact)
(:Artifact)-[:CONSUMED_BY]->(:Agent)
(:ChangeEvent)-[:AFFECTS]->(:Component)
```

### 9.3 部署

```yaml
Neo4j:
  社区版（单节点即可）：4 vCPU, 16 GB RAM, 200 GB SSD
  用途: K14 (Knowledge Keeper), K15 (Change Propagation), A12 (Code Review 跨模块影响)
  备选: 小团队用 Neo4j AuraDB 托管版，省运维
```

---

## 十、全系统部署拓扑与资源估算

### 10.1 基础设施总览

```
┌──────────────────────────────────────────────────────────────────┐
│                         K8s Cluster                               │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ Mission Control   │  │ Control Plane     │  │ Worker Pods    │  │
│  │                   │  │                   │  │                │  │
│  │ Next.js (2 pods)  │  │ Temporal Server   │  │ Agent Workers │  │
│  │ + SSE/WS 网关     │  │ + Orch Workers   │  │ (Python, 8 pods)│  │
│  │                   │  │ (3 pods)         │  │              │  │
│  └──────────────────┘  └──────────────────┘  │ MCP Gateway   │  │
│                                                │ (Go, 2 pods)  │  │
│  ┌──────────────────┐  ┌──────────────────┐  └───────────────┘  │
│  │ 数据层            │  │ 消息/事件         │                     │
│  │                   │  │                   │  ┌───────────────┐  │
│  │ PostgreSQL+       │  │ NATS Cluster      │  │Firecracker VM │  │
│  │ pgvector (HA)    │  │ (3 节点)          │  │Fleet (按需)   │  │
│  │                   │  │                   │  │               │  │
│  │ Neo4j (单节点)    │  │                   │  │ Dev Agent 执行 │  │
│  └──────────────────┘  └──────────────────┘  └───────────────┘  │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              可观测性 (Grafana Stack)                        │  │
│  │  Tempo (Traces) · Mimir (Metrics) · Loki (Logs)              │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 10.2 资源估算（中型团队，20–50 开发者，日均 10–20 需求）

| 组件 | 副本数 | vCPU/实例 | RAM/实例 | 存储 | 月费估算（云） |
|---|---|---|---|---|---|
| **Mission Control** (Next.js SSR) | 2 | 2 | 4 GB | — | ~$150 |
| **Temporal Server** | 1+2 Worker | 2 | 4 GB | 100 GB SSD (PG) | ~$200 |
| **NATS** | 3 | 2 | 4 GB | 50 GB SSD | ~$100 |
| **PostgreSQL + pgvector** | 2 (HA) | 4 | 16 GB | 500 GB SSD | ~$400 |
| **Neo4j** | 1 | 4 | 16 GB | 200 GB SSD | ~$300 |
| **Agent Workers (Python)** | 8 | 2 | 4 GB | — | ~$400 |
| **MCP Gateway (Go)** | 2 | 1 | 1 GB | — | ~$50 |
| **Firecracker Fleet** | 按需 (0–20) | 2 | 4 GB | 临时 | ~$500（按用量） |
| **Grafana Stack** | 各 1 | 2 | 4 GB | 200 GB SSD | ~$200 |
| **S3 / Object Store** | — | — | — | 1 TB | ~$25 |
| **合计** | | | | | **~$2300/月** |

**GPU 需求**：默认不需要 GPU。所有 LLM 调用走云端 API；Embedding 优先千问 text-embedding-v3。私有化部署时仅需 1× GPU 做本地 Embedding。

### 10.3 混合部署方案（企业私有化）

对于数据合规要求高的企业：

```yaml
可替换为私有化:
  - Anthropic API → AWS Bedrock (Claude) 或 私有 vLLM 集群
  - Voyage AI Embedding → 私有部署 stella_en_1.5B (1 GPU: A10 或 L40S)
  - Fly Machines / Firecracker → 自建 Firecracker + K8s
  - S3 → MinIO (S3 兼容)
  - Grafana Cloud → 自建 Tempo + Mimir + Loki

增量: +2–4 GPU (A10/L40S) 用于私有 Embedding + 可选私有 LLM
```

---

## 十一、启动顺序与开发环境

### 11.1 最小可运行开发环境（Phase 1 MVP）

要跑通"编码—测试—修复"闭环，最少需要：

```bash
# 1. 中间件（Docker Compose 一把起）
docker compose up -d postgres nats temporal temporal-ui

# 2. Control Plane
cd control-plane && pip install -r requirements.txt
temporal worker start --task-queue agent-orchestrator  # Orch Worker
python -m agent_workers.dev_agent                       # Dev Agent Worker (调 Claude Code)

# 3. MCP Gateway
cd mcp-gateway && go run . --config config.dev.yaml

# 4. Mission Control
cd mission-control && npm run dev

# 5. Agent Worker（随便起一个验证）
python -m agent_workers.auto_test                       # Auto Test Agent (调 Jest/Playwright)
```

### 11.2 依赖服务版本锁定

```yaml
中间件:
  PostgreSQL: 16.x (含 pgvector 0.7.x, pg_trgm)
  NATS: 2.10.x (含 JetStream)
  Temporal: 1.24.x
  Neo4j: 5.x (Phase 2+ 需要)
  Firecracker: 1.7.x

语言运行时:
  Python: 3.12+
  Node.js: 22 LTS
  Go: 1.23+
  TypeScript: 5.x

关键 SDK:
  temporalio: 1.x (Python)
  nats-py: 0.x
  anthropic: 0.49+ (Python/Node)
  langgraph: 0.2+ (Python)
  pgvector: 0.3+ (Python)
  @anthropic-ai/claude-code: latest (Node, Dev Agent 用)
  playwright: 1.50+
  stryker: 8.x
  opentelemetry: 1.x (所有语言)
  voyageai: 0.x (Python, Embedding)
```

---

## 十二、专题深化（常见工程落地疑问）

### 12.1 codebase-memory-mcp 能否替代 Neo4j 图数据库？

**结论：互补而非替代。** 两者解决的是不同层次的问题。

#### codebase-memory-mcp 的能力边界

`codebase-memory-mcp`（以及同类 MCP-server 如 `@anthropic/mcp-server-codebase`）本质上是一个 **MCP 协议包装的代码库索引+检索工具**，它提供的能力是：

| 能力 | 实现方式 | 适用场景 |
|---|---|---|
| **符号搜索** | 代码索引（tree-sitter AST 解析 → 符号表） | "find_usages of `getOrderStatus`" → 返回所有引用位置 |
| **文件/模块发现** | 项目结构索引 | "list all files under src/api/" |
| **语义搜索** | Embedding + 向量检索（通常内置） | "find code related to order export" |
| **依赖分析** | import/require 图（轻量，无持久化） | "what does this file import" |

**它做不到的**：
- **跨仓库/跨项目的依赖追溯**：codebase-memory 通常绑定单个 repo，不知道"A 项目的 API 变更会影响 B 项目的哪个前端组件"
- **历史演化查询**："这个 API 在过去三个月被哪些需求改过？每次改了什么？"
- **多 Agent 产出物的关联**："Spec Decomposer 产出的 DAG 节点 #3 对应的 Dev Agent 改了哪些文件？那些文件的测试覆盖率变化趋势？"
- **持久化的知识沉淀**：codebase-memory 的生命周期通常跟一次 Agent 会话绑定，会话结束索引就没了（除非做了持久化存储，但那正是我们在 Neo4j 里做的事）
- **图遍历查询**："从这个 API 出发，找到所有消费它的前端组件 → 找到这些组件的测试用例 → 找到变异得分 < 60 的"

#### 正确的互补架构

```
┌─────────────────────────────────────────────────────┐
│                Context Builder (SELECT 阶段)          │
│                                                     │
│  短期/实时索引（一次任务内）                            │
│  ┌─────────────────────────┐                        │
│  │ codebase-memory-mcp      │  ← Dev Agent 用它找"当前│
│  │ (tree-sitter + 轻量向量)  │    仓库里这个函数在哪"    │
│  │                          │                        │
│  │ • find_usages(symbol)    │                        │
│  │ • list_directory(path)   │                        │
│  │ • semantic_search(q, k)  │                        │
│  └──────────┬──────────────┘                        │
│             │                                       │
│  长期/跨项目知识（跨需求持久化）                          │
│  ┌──────────┴──────────────┐                        │
│  │ Neo4j 知识图谱            │  ← K14/K15/A12 用它做    │
│  │                          │    跨需求影响分析         │
│  │ • 跨仓库 API→组件→测试    │                        │
│  │ • 历史变更追溯            │                        │
│  │ • 多 Agent 产出物关联     │                        │
│  └─────────────────────────┘                        │
└─────────────────────────────────────────────────────┘
```

**分阶段策略**：
- **Phase 1（MVP，不需要 Neo4j）**：`codebase-memory-mcp` 足够——Dev Agent 用它来找代码，A12 Code Review 用它的依赖图做跨模块分析（单 repo 内）
- **Phase 2（3–6 月，引入 Neo4j）**：当需要跨 repo 追溯、Change Propagation 需要知道"Spec 改了 → 哪个 Agent 的哪个任务要重置"，此时 Neo4j 出场
- **长期**：两者并存。codebase-memory-mcp 负责"当前任务内的快速代码查找"（像 LSP），Neo4j 负责"跨时间、跨仓库的知识网络"（像企业知识库）

---

### 12.2 Worker Sandbox 的完整能力：支持各类 Dev Agent + 编译检查

#### 问题拆解

两个子问题：
1. Firecracker 能否同时支持 Claude Code CLI 和 Codex 等不同 Agent？
2. 能否支持编译检查（TypeScript `tsc`、ESLint、Java `javac` 等）？

#### 答案：完全可以，关键在"镜像"而非"VM 类型"

Firecracker microVM 本身只是一个**轻量虚拟机运行时**——它和我们关系不大，真正重要的是 **VM 里跑什么镜像**。把 Dev Agent 需要的工具链 **预装进基础镜像**，Firecracker 启动 VM 时就有了。

#### 12.2.1 通用 Agent 镜像分层设计

```dockerfile
# ─── Layer 0: OS 基础（极少变动） ───
FROM alpine:3.21
# 或 ubuntu:noble（如果 Agent 需要 apt-get）

# ─── Layer 1: 通用开发工具链（团队统一维护，月度更新） ───
# 所有 Agent 共享
RUN apk add --no-cache \
    git openssh-client curl wget \
    bash jq yq \
    nodejs npm \
    python3 py3-pip \
    ripgrep fd

# ─── Layer 2: 语言/框架特定工具（按项目选装） ───
# TypeScript 项目
RUN npm install -g typescript eslint prettier jest playwright

# Python 项目
RUN pip install pytest black mypy ruff

# Java 项目
# RUN apk add openjdk21 maven gradle

# 通用编译 Lint 工具
RUN npm install -g tree-sitter-cli
# SonarQube scanner, etc.

# ─── Layer 3: Agent 运行时（按 Agent 类型选装） ───
# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Codex CLI（如果 OpenAI 提供）
# RUN curl -fsSL https://codex.openai.com/install.sh | sh

# 通用 CLI Agent 也可以通过 npx 动态安装，不预装
```

#### 12.2.2 三类 Agent 的镜像变体

| Agent 类型 | 基础镜像 | 必须预装 | 启动时注入 |
|---|---|---|---|
| **Claude Code CLI** | `agent-base:latest` | Node.js + npm + Git + Claude Code CLI | CLAUDE.md + MCP Gateway 配置 + 任务 Spec |
| **Codex / 云端 Agent** | `agent-base:latest` | Codex CLI + 目标语言工具链 | 任务 Spec + API Key + 沙箱配置 |
| **通用 Python Agent Worker** | `agent-base:latest` | Python + pip 依赖（无需 Node） | Skill API 配置 + 任务上下文 |

**编译/构建工具支持**（回答你第二个子问题）：镜像 Layer 1 已经装了 `typescript` / `eslint` / `gcc` / `javac` 等。Dev Agent 的 Inner Auditor 调 `Static_Analysis_Runner` Skill API 时，API 的实现就是 `subprocess.run(["npx", "tsc", "--noEmit"])` —— 这在 VM 内直接执行，和开发者的本机完全一致。

```python
# static_analysis_runner.py —— 在 VM 内执行
class StaticAnalysisRunner:
    def run_eslint(self, files: list) -> LintResult:
        cmd = ["npx", "eslint", "--format", "json"] + files
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return LintResult.from_eslint_json(result.stdout)
    
    def run_tsc(self, files: list) -> TypeCheckResult:
        cmd = ["npx", "tsc", "--noEmit", "--pretty", "false"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return TypeCheckResult.from_tsc_output(result.stdout + result.stderr)
    
    def run_sonarqube(self, files: list) -> SonarResult:
        cmd = ["sonar-scanner", f"-Dsonar.inclusions={','.join(files)}"]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return SonarResult.from_sonar_output(result.stdout)
```

#### 12.2.3 Firecracker vs Docker：什么时候选哪个

| 场景 | 推荐方案 | 理由 |
|---|---|---|
| **发布给外部用户的代码执行** | Firecracker（内核级隔离） | 安全无妥协 |
| **内部自动化 CI/测试** | Docker（足够 + 团队熟悉） | Docker 生态更丰富、启动更快（<1s vs 200ms） |
| **并行 Dev Agent 多实例** | Docker in Docker 或 K8s Pod | 每 VM 的 overhead 在并行时叠加 |
| **需要 GPU** | Docker（nvidia-docker runtime） | Firecracker 不支持 GPU passthrough |

**务实建议**：Phase 1 用 Docker（启动快、团队熟），Phase 3 生产环境再将"高危操作 Agent"迁移到 Firecracker。不必一开始就上 microVM。

---

### 12.3 Sandbox 基础开发环境 & Agent 初始配置注入

#### 12.3.1 基础环境定义：Image + 启动脚本

```yaml
# sandbox-templates/typescript-project.yaml
# 这个文件定义了一个"TypeScript 项目的标准沙箱环境"
name: "ts-project-standard"
base_image: "ghcr.io/our-org/agent-sandbox:ts-v3"
  # 镜像已预装: Node 22, npm, tsc, eslint, jest, playwright, claude-code

resources:
  cpu: 4
  memory: "8Gi"
  disk: "20Gi"  # 临时盘，VM 销毁后清除

network:
  egress:
    - "github.com"           # Git clone
    - "registry.npmjs.org"   # npm install
    - "api.anthropic.com"    # Claude API (Dev Agent 专用)
    - "api.deepseek.com"     # DeepSeek API (文本 LLM 主力)
    - "dashscope.aliyuncs.com"  # 千问 API (多模态)
    - "open.bigmodel.cn"     # 智谱 GLM API (多模态备用)
    - "mcp-gw.internal:443"  # 我们的 MCP Gateway
  egress_default: "DENY"    # 其他一切出站被防火墙拦截
  ingress: "NONE"            # 不能从外部连入

env:
  # 所有 Agent 共用的环境变量
  NODE_ENV: "ci"
  CI: "true"
  ANTHROPIC_API_KEY: "${from_vault:agent/anthropic-key}"  # 从 Vault 注入
  MCP_GATEWAY_URL: "https://mcp-gw.internal"
  MCP_GATEWAY_TOKEN: "${from_vault:agent/mcp-token}"

# 模型网关地址——回答你的问题："agent 的初始配置，比如模型网关接口地址"
llm_config:
  provider: "anthropic"
  base_url: "https://api.anthropic.com"        # 或企业代理: "https://llm-gw.company.com"
  default_model: "claude-sonnet-4-6"           # 默认模型
  fallback_models:                              # 熔断降级时的备选
    - "claude-opus-4-8"
    - "claude-haiku-4-5"
  max_tokens_per_request: 128000
  temperature_default: 0.3
  # 如果企业有自建代理，改一行即可
  # base_url: "https://bedrock-runtime.us-east-1.amazonaws.com"
  # 或私有 vLLM: "https://llm.internal.company.com/v1"
```

#### 12.3.2 Agent 启动时的配置注入流程

```
Orch 调度 Dev Agent:
  │
  ├─ 1. 选择沙箱模板: "ts-project-standard"
  │      （根据任务类型自动匹配——如果任务是 "修改 Java 后端"，
  │       则选 "java-backend-standard"）
  │
  ├─ 2. 拼接实际配置（模板 + 任务特定覆盖）:
  │     {
  │       template: "ts-project-standard",
  │       task_overrides: {
  │         env: {
  │           CLAUDE_MD_CONTENT: "<Context Builder 生成的动态 CLAUDE.md>",
  │           TASK_SPEC: "{...}",
  │           REPO_URL: "git@github.com:org/repo.git",
  │           BRANCH_NAME: "ai-task/REQ-789-T2",
  │         },
  │         llm_config: {
  │           model: "claude-opus-4-8",   // 这个任务比较复杂，用 Opus
  │           max_turns: 50
  │         }
  │       }
  │     }
  │
  ├─ 3. 注入 MCP Gateway 配置（自动生成）:
  │     → 写入 VM 内的 ~/.claude/mcp.json:
  │       {
  │         "ai-native": {
  │           "url": "https://mcp-gw.internal",
  │           "headers": { "Authorization": "Bearer <task-scoped-jwt>" }
  │         }
  │       }
  │     → 这个 JWT 限定了: 只能在这个 task 的有效期内、以这个 Agent 身份调用 MCP
  │
  ├─ 4. 启动 VM → 执行 init script:
  │     ├─ git clone <repo> --branch ai-task/REQ-789-T2
  │     ├─ npm install
  │     ├─ 写 ~/CLAUDE.md（来自 CLAUDE_MD_CONTENT 环境变量）
  │     └─ 写 ~/task.json（来自 TASK_SPEC）
  │
  └─ 5. 执行 Agent:
        ├─ Claude Code: claude --bare -p "<task prompt>" --output-format json
        └─ 或其他 Agent 运行时: codex run / 自定义脚本
```

#### 12.3.3 模型网关地址的配置层级

模型网关地址不在代码里写死，按以下优先级查找：

```
1. 沙箱模板 llm_config.base_url        ← 任务级覆盖（最高优先级）
2. 项目配置 .ai-native/llm.yaml         ← 项目级（仓库根目录，由团队维护）
3. 系统默认配置                          ← 全局级（由平台团队在 K8s ConfigMap 维护）

示例 .ai-native/llm.yaml（放在每个代码仓库根目录）:
  provider: anthropic
  base_url: https://api.anthropic.com   # ← 这一行就是"模型网关地址"
  # 换成企业代理: base_url: https://llm-gw.acme-corp.com
  # AWS Bedrock:  base_url: https://bedrock-runtime.us-east-1.amazonaws.com
  default_model: claude-sonnet-4-6
  code_model: claude-opus-4-8           # 复杂代码任务用
  review_model: claude-sonnet-4-6       # Code Review 用
```

---

### 12.4 UI 自动化测试技术栈（含截图查看）

#### 核心方案：Playwright + 自研快照面板

**Playwright 是当前工业界 UI 测试的事实标准**，本系统基于它构建完整的 UI 测试可视化链路。

#### 12.4.1 Playwright 的截图能力

Playwright 内置了三层截图/回放能力，不需要额外集成：

| 能力 | Playwright 配置 | 在我们的系统中如何使用 |
|---|---|---|
| **失败自动截图** | `screenshot: "only-on-failure"` | 每个失败用例自动截取失败瞬间的页面全貌 → 存 S3 → MC 测试洞察面板展示 |
| **Trace Viewer（录屏回放）** | `trace: "on-first-retry"` | 完整的 DOM 快照时间线 + 网络请求 + 控制台日志 → 可在 MC 中嵌入 Playwright Trace Viewer |
| **Video 录制** | `video: "retain-on-failure"` | 失败用例的完整操作视频（.webm）→ 存 S3 → MC 内嵌播放 |
| **toMatchSnapshot** | 内置 | 自动截图 → 对比基线 → pixelmatch diff |

#### 12.4.2 在 Mission Control 中查看 UI 测试结果

A11 Auto Test Agent 在 Playwright 执行完后，将产物结构化写入 S3，MC 前端通过预签名 URL 直接加载：

```python
# auto_test_agent/test_reporter.py
class PlaywrightReporter:
    def collect_artifacts(self, test_result_dir: str) -> dict:
        return {
            "failed_cases": [
                {
                    "name": "导出按钮应在订单列表可见",
                    "error": "Expected element [data-testid='export-btn'] to be visible",
                    # 三种可视化产物，MC 前端按需加载
                    "screenshot_url": self._upload_to_s3(f"{dir}/screenshots/tc-015-failure.png"),
                    "trace_url":     self._upload_to_s3(f"{dir}/traces/tc-015-trace.zip"),
                    "video_url":     self._upload_to_s3(f"{dir}/videos/tc-015.webm"),
                    
                    # Diff 热力图（视觉回归失败时）
                    "visual_diff": {
                        "expected_url": ".../baseline/export-btn.png",
                        "actual_url":   ".../actual/export-btn.png",
                        "diff_url":     ".../diff/export-btn-diff.png",
                        "diff_percent": 12.3,   # ← 这个来自 pixelmatch
                        "threshold": 5.0,
                        "verdict": "FAIL"
                    }
                }
            ]
        }
```

#### 12.4.3 MC 测试洞察面板的 UI 测试视图

在 `03` 产品总览中描述的测试洞察面板里，UI 测试（E2E/视觉回归）支持三种查看模式：

```
模式 A: 单帧截图（默认展开）
  ┌────────────────────────────────┐
  │ 🔴 TC-015: 导出按钮应在订单列表可见│
  │                                 │
  │ [失败截图]                       │
  │ ┌────────────────────────────┐  │
  │ │                            │  │
  │ │   实际页面渲染截图           │  │
  │ │   （红色虚线框标注缺失元素）  │  │
  │ │                            │  │
  │ └────────────────────────────┘  │
  │                                 │
  │ 错误: Expected visible, got     │
  │       display:none              │
  └────────────────────────────────┘

模式 B: Trace 时间轴（点击 [查看 Trace]）
  ┌───────────────────────────────────────────────────────┐
  │ Playwright Trace Viewer（嵌入 iframe）                  │
  │                                                        │
  │  0s      2s      4s      6s      8s                    │
  │  ├───────┼───────┼───────┼───────┤                    │
  │  │导航到页│勾选订单│点击导出│断言失败│                     │
  │  │ ✅    │ ✅    │ ✅    │ ❌    │                     │
  │  │       │       │       │       │                     │
  │  │[截图]  │[截图]  │[截图]  │[截图]  │                    │
  │                                                        │
  │  右侧: 每步的 DOM 快照 + 网络请求 + Console 日志         │
  └───────────────────────────────────────────────────────┘

模式 C: 设计稿对比（视觉回归，点击 [对比]）
  ┌──────────────┬──────────────┬──────────────┐
  │   设计稿      │   实际渲染    │   Diff 热力图 │
  │   [image]    │   [image]    │   [image]    │
  │              │              │              │
  │              │              │  红色=差异区   │
  │              │              │  蓝色=偏移     │
  │              │              │  差异 12.3%    │
  └──────────────┴──────────────┴──────────────┘
  阈值: 5% | 结果: ❌ FAIL  |  [标记为可接受] [回写为新基线]
```

#### 12.4.4 截图/Trace 与 Agent 自动化闭环

```
A11 Tester 执行 Playwright:
  → 失败 → 自动截图 + Trace
  → Critic 分析（Claude 读截图——多模态，描述"页面上少了什么"）
  → 生成失败报告 { "suggestion": "导出按钮被父容器 overflow:hidden 裁剪" }
  → 打回 A9 Dev Agent（失败报告含截图 URL）
  → A9 的 Coder 读取截图 URL → Claude 多模态理解 → 修复 CSS → 重新提交
```

**Claude 的多模态能力在这里关键**：Critic 和 Coder 都能"看懂测试截图"，不需要人类描述"那个按钮不见了"。

#### 12.4.5 移动端 / 响应式 UI 测试

```python
# Playwright 支持多设备视口
BROWSERS = [
    {"name": "chrome-desktop", "viewport": {"width": 1440, "height": 900}},
    {"name": "safari-mobile",  "viewport": {"width": 390, "height": 844}, "isMobile": True},
    {"name": "chrome-tablet",  "viewport": {"width": 768, "height": 1024}},
]

for browser in BROWSERS:
    context = await playwright.chromium.launch().new_context(**browser)
    page = await context.new_page()
    await page.goto(staging_url)
    # 每个视口独立截图，独立对比
    await page.screenshot(path=f"screenshots/{test_name}-{browser['name']}.png")
```

---

### 12.5 接口 Mock、压测、测试环境初始化（AI 自动执行）

#### 12.5.1 总体方案

| 需求 | 工具 | AI 如何参与 |
|---|---|---|
| **API Mock** | **WireMock** (JVM) 或 **Mockoon** (Node/桌面) 或 **MSW** (前端内嵌) | A7 Test Case Generator 自动生成 Mock 规则配置；根据 Spec 的 OpenAPI 定义 → 自动产出 Mock 响应 |
| **接口测试** | **Jest + Supertest** (Node) 或 **pytest + httpx** (Python) | A7 生成，A11 执行 |
| **压测** | **k6** (Grafana) 或 **Artillery** (Node) | A7 生成压测脚本；A11 在独立沙箱执行（不与功能测试共享环境） |
| **测试环境初始化** | **Testcontainers** (Node/Python) + **Docker Compose** | A7 生成 `docker-compose.test.yaml` + 初始化脚本；A11 在测试执行前自动拉起环境、执行后自动销毁 |

#### 12.5.2 API Mock：基于 OpenAPI 自动生成

这是"AI 自动执行"最直接的体现——A4 Spec Writer 产出 OpenAPI 规范后，A7 不需要人写 Mock，直接从 OpenAPI 生成：

```python
# test_case_generator/mock_generator.py
class MockGenerator:
    """
    A7 Test Case Generator 的子模块。
    输入: A4 产出的 OpenAPI Spec
    输出: WireMock stubs / MSW handlers
    """
    
    def generate_wiremock_stubs(self, openapi_spec: dict) -> dict:
        stubs = {"mappings": []}
        
        for path, methods in openapi_spec["paths"].items():
            for method, detail in methods.items():
                # 自动为每个 endpoint 生成:
                # 1. 正常响应 (200 + example body)
                success_stub = self._gen_success_response(method, path, detail)
                stubs["mappings"].append(success_stub)
                
                # 2. 错误响应 (400 / 401 / 404 / 500)
                for error_code in detail.get("responses", {}).keys():
                    if error_code.startswith("4") or error_code.startswith("5"):
                        error_stub = self._gen_error_response(method, path, error_code, detail)
                        stubs["mappings"].append(error_stub)
                
                # 3. 边界值响应 (空数组 / null 字段 / 超长字符串)
                edge_stubs = self._gen_edge_case_responses(method, path, detail)
                stubs["mappings"].extend(edge_stubs)
        
        return stubs
    
    def _gen_success_response(self, method, path, detail):
        schema = detail["responses"]["200"]["content"]["application/json"]["schema"]
        example = self._generate_example_from_schema(schema)  # Claude 辅助生成逼真示例
        
        return {
            "request": {
                "method": method.upper(),
                "urlPath": path,
            },
            "response": {
                "status": 200,
                "jsonBody": example,
                "headers": {"Content-Type": "application/json"}
            }
        }
```

**Mock 工具选择**：

| 工具 | 适用场景 | 为什么选它 |
|---|---|---|
| **WireMock** | 独立 Mock Server（Java 进程，HTTP API 管理） | 功能最全（延迟注入、状态机、录制/回放）；A7 可以通过 HTTP API 动态注册 stub；适合集成测试环境 |
| **MSW (Mock Service Worker)** | 前端单元/集成测试（浏览器 Service Worker 拦截） | 前端测试不需要起独立进程；Playwright 原生支持 MSW；更适合 Dev Agent 本地开发 |
| **Mockoon** | 快速本地 Mock（带 GUI，可导出 OpenAPI） | 产品经理也能用 GUI 调整 Mock 数据；适合需求阶段原型演示 |

**本系统的分层 Mock 策略**：

```
层 1: 单元测试 → MSW（浏览器内拦截，不发起真实网络请求）
层 2: 集成测试 → WireMock（独立进程，模拟后端全部 API）
层 3: E2E 测试  → Staging 真实环境 + WireMock 辅助（只 Mock 外部第三方 API）
```

#### 12.5.3 压测：k6 + AI 自动生成

```python
# test_case_generator/load_test_generator.py
class LoadTestGenerator:
    """
    A7 Test Case Generator 的子模块。
    输入: OpenAPI Spec + 业务场景
    输出: k6 压测脚本
    """
    
    def generate_k6_script(self, openapi_spec: dict, scenarios: list) -> str:
        # Claude 辅助生成压测脚本
        prompt = f"""根据以下 OpenAPI 规范和业务场景，生成一个 k6 压测脚本。

OpenAPI 规范:
{json.dumps(openapi_spec, indent=2)}

压测场景:
{json.dumps(scenarios, indent=2)}

要求:
1. 使用 k6 的 ramping-vus executor（逐步增加并发）
2. 对每个 endpoint 检查: 状态码、响应时间 p95 < 500ms、无错误
3. 生成有意义的测试数据（不全是 "test"）
4. 包含 checks 和 thresholds

只输出 k6 JavaScript 代码，不要解释。
"""
        
        k6_script = claude_api_call(prompt, max_tokens=4000)
        return k6_script

# A11 Auto Test Agent 执行压测（与功能测试隔离）:
async def run_load_test(k6_script: str, target_url: str):
    # 写入临时文件
    with open("/tmp/load-test.js", "w") as f:
        f.write(k6_script)
    
    # 在独立沙箱中执行（不共享功能测试的 Staging 环境）
    cmd = [
        "k6", "run",
        "--out", "json=/tmp/k6-result.json",
        "--vus", "10",           # 初始 10 并发
        "--duration", "60s",     # 持续 60s
        "-e", f"BASE_URL={target_url}",
        "/tmp/load-test.js"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return parse_k6_output(result.stdout)

# 压测结果在 MC 效能仪表盘中的展示:
# - QPS vs 并发曲线
# - P50 / P95 / P99 延迟分布
# - 错误率时间线
# - 与历史基线的对比（上次压测 P95=320ms，本次 P95=450ms → ⚠️ 退化）
```

**压测隔离规则**（AI 自动执行的安全边界）：
- 压测**永远不在生产环境跑**——只对 `staging-perf` 专用环境
- 压测并发上限由环境配置写死（k6 `--vus` 参数由系统根据 staging-perf 资源配额注入，Agent 不能改）
- 压测结果不和功能测试的 Pass/Fail 混在一起——单独一个 `load_test.completed` 事件，信息类告警

#### 12.5.4 测试环境初始化：Testcontainers + AI 自动编排

```python
# test_case_generator/env_orchestrator.py
class TestEnvOrchestrator:
    """
    A7 Test Case Generator 的子模块。
    根据 Spec 里定义的依赖（数据库、缓存、消息队列、第三方 API），
    自动生成 docker-compose.test.yaml + 初始化脚本。
    """
    
    def generate_test_env(self, spec: dict, api_contract: dict) -> TestEnvConfig:
        # 分析 Spec 需要的依赖
        dependencies = self._analyze_dependencies(spec, api_contract)
        
        services = {}
        
        # 基础依赖
        if "postgresql" in dependencies:
            services["db-test"] = {
                "image": "postgres:16-alpine",
                "environment": {
                    "POSTGRES_DB": "test_db",
                    "POSTGRES_USER": "test",
                    "POSTGRES_PASSWORD": "test"
                },
                "ports": ["5432"],
                "volumes": ["./test-data/init.sql:/docker-entrypoint-initdb.d/init.sql"]
            }
        
        if "redis" in dependencies:
            services["redis-test"] = {
                "image": "redis:7-alpine",
                "ports": ["6379"]
            }
        
        if "wiremock" in dependencies:
            services["wiremock"] = {
                "image": "wiremock/wiremock:latest",
                "ports": ["8080"],
                "volumes": ["./test-data/wiremock:/home/wiremock/mappings"]
            }
        
        # 生成初始化脚本（Claude 辅助）
        init_sql = self._generate_seed_data(spec)  # Claude 生成逼真测试数据
        wiremock_stubs = MockGenerator().generate_wiremock_stubs(api_contract)
        
        return TestEnvConfig(
            docker_compose=services,
            init_sql=init_sql,
            wiremock_stubs=wiremock_stubs,
            startup_timeout_seconds=60,
            health_checks={
                "db-test": "pg_isready -U test",
                "redis-test": "redis-cli ping",
                "wiremock": "curl -f http://localhost:8080/__admin/"
            }
        )

# A11 Auto Test Agent 使用 Testcontainers（Python SDK）自动管理环境生命周期:
from testcontainers.compose import DockerCompose

class TestEnvManager:
    def __enter__(self):
        # Docker Compose 拉起全量测试依赖
        self.compose = DockerCompose(
            "./test-env",
            compose_file_name="docker-compose.test.yaml"
        )
        self.compose.start()
        self._wait_for_healthy(timeout=60)
        return self.compose.get_service_ports()
    
    def __exit__(self, *args):
        # 测试结束自动销毁（无论成功失败），不残留资源
        self.compose.stop()
        shutil.rmtree("./test-env")  # 清理临时文件

# 使用:
with TestEnvManager() as ports:
    test_runner.run(staging_url=f"http://localhost:{ports['app']}")
# 这里出去后，所有容器已自动销毁
```

#### 12.5.5 全链路 AI 自动化流程

```
触发: A6 产出 DAG → Orch 调度 A7

A7 Test Case Generator 自动执行:

1. 读 Spec → 分析依赖（DB/缓存/MQ/第三方 API）
2. 生成 docker-compose.test.yaml（Testcontainers 编排）
3. 生成 init.sql（种子数据——Claude 生成逼真示例数据，非 "test123"）
4. 生成 WireMock stubs（Mock 外部第三方 API）
5. 生成 Jest/Playwright 测试代码
6. 生成 k6 压测脚本
7. 打包输出: test.ready 事件

↓

A10 CI/CD Agent → 部署 Staging

↓

A11 Auto Test Agent 执行:

8. TestEnvManager 拉起 Docker Compose（含 DB + Redis + WireMock）
9. 等待 healthy check 全绿
10. 对真实 DB 跑集成测试
11. 对 WireMock 覆盖的 API 跑 E2E
12. 对专用 perf 环境跑 k6 压测
13. TestEnvManager 销毁所有容器（__exit__）
14. 上报结果: test.completed { unit, integration, e2e, visual, load_test }
```

---

## 十三、总结：从 0 到 1 最快的路径

如果只有 **一个人 + 三个月**，按这个顺序开工：

```
Week 1–2:  Docker Compose 起全部中间件
           写 Orch Temporal Workflow（只实现 draft → analyzing → developing → testing → done 五态）
           写 Context Builder（最简版：硬编码 Spec + 固定文件列表）

Week 3–4:  接 Claude Code CLI 无头模式（ai-task Wrapper）
           跑通"一次需求 → Claude Code 写代码 → Git push"的最简闭环
           
Week 5–6:  写 Auto Test Agent（Jest/Playwright Wrapper + Stryker 集成）
           跑通"测试失败 → 回写 Event Bus → Orch 重新调度 Dev Agent"的外部循环

Week 7–8:  写 MCP Gateway（最小可行版：tools/list + tools/call）
           接 Mission Control 前端（已有原型，接上真实 WebSocket/SSE 数据）
           
Week 9–10: 完整双脑机制（Inner Auditor / Inner Critic 的 LangGraph 实现）
           熔断引擎（Temporal workflow 内的 loop counter + timeout）
           
Week 11–12: 可观测性（OTel SDK 注入 + Grafana Dashboard）
           压测 + 修复 + 文档
```

前 6 周打完"编码-测试-修复"闭环，后 6 周加固。Phase 2/3 的 Agent（P1–P3, Gate, Sidecar）在第二季度迭代。

---

## 十四、完整技术栈清单与资源需求矩阵

### 14.1 完整技术栈全景（无遗漏清单）

> 审计原则：从"一个需求从飞书群聊进入系统 → 代码部署到生产"的每一环反向追溯，确保每个环节都有明确的技术选型。

#### 14.1.1 基础设施层

| 类别 | 组件 | 选型 | 用途 | Phase |
|---|---|---|---|---|
| **容器编排** | Kubernetes | K8s 1.30+ (AWS EKS / GKE / 自建 k3s) | 所有服务运行底座 | P1 |
| **容器运行时** | containerd / Docker | K8s 内置 containerd + Docker (沙箱) | 服务容器 + Agent 沙箱 | P1 |
| **沙箱运行时** | Firecracker / Docker | Docker (P1 Dev Agent) → Firecracker (P3 高危操作) | Dev Agent 执行隔离 | P1→P3 |
| **服务网格/入口** | Ingress + Cert-Manager | Nginx Ingress + cert-manager (Let's Encrypt) | TLS 终结、域名路由 | P1 |
| **内部 DNS** | CoreDNS | K8s 内置 | `mcp-gw.internal` 等服务发现 | P1 |
| **Secret 管理** | HashiCorp Vault | Vault (或云原生: AWS Secrets Manager) | API Key、Token、数据库密码管理 | P1 |
| **对象存储** | S3 / MinIO | AWS S3 (云) 或 MinIO (自建) | Trace/截图/Video/artifact 存储 | P1 |
| **容器镜像仓库** | OCI Registry | GHCR / ECR / Harbor (自建) | Agent Sandbox 基础镜像、服务镜像 | P1 |
| **Git 服务** | GitHub / GitLab | 已有 | 代码仓库、Webhook 触发 CI | P1 |
| **CI Runner** | GitHub Actions / GitLab CI | 已有 + 自建 Runner (用于沙箱化 CI) | CI/CD Agent 执行构建 | P1 |

#### 14.1.2 数据层

| 类别 | 组件 | 选型 | 用途 | Phase |
|---|---|---|---|---|
| **关系数据库** | PostgreSQL 16 | 主库 (RDS / Cloud SQL / 自建) | 需求/Agent/审批/Gate/测试 全部业务数据 | P1 |
| **向量扩展** | pgvector 0.8 | PostgreSQL 扩展 | RAG 语义检索、代码相似度 | P1 |
| **全文检索** | PostgreSQL tsvector + pg_trgm | PostgreSQL 内置 | 关键词搜索（不需要 ES） | P1 |
| **图数据库** | Neo4j 5.x Community | 自建 或 AuraDB 托管 | 代码依赖图、API→组件→测试关联、变更影响分析 | P2 |
| **缓存** | Redis 7 | ElastiCache / 自建 | Temporal 状态缓存、Mission Control 会话 | P1 |
| **消息队列** | NATS 2.10 JetStream | 自建 3 节点 Cluster | Event Bus | P1 |
| **工作流持久化** | PostgreSQL（Temporal 后端） | 与主库共用或独立 | Temporal Workflow state | P1 |

#### 14.1.3 编排与 Agent 运行时

| 类别 | 组件 | 选型 | 用途 | Phase |
|---|---|---|---|---|
| **工作流引擎** | Temporal 1.24+ | 自建 Server + Worker (Python SDK) | Orchestrator 状态机、Gate 超时、DAG 调度、熔断 | P1 |
| **LLM Agent 框架** | LangGraph 0.2+ | Python SDK | Agent 内部 think→tool→observe→reflect 循环 | P1 |
| **LLM 调用** | Anthropic API (Claude Opus/Sonnet/Haiku) | 直调 或 AWS Bedrock 或 企业代理 | Agent 的 LLM 推理 | P1 |
| **Embedding** | Voyage AI API (`voyage-code-3` + `voyage-3`) | 直调 或 私有化部署 stella_en_1.5B | 代码/文档向量化 | P1 |
| **Dev Agent 运行时** | Claude Code Agent SDK (`claude -p --output-format json`) | CLI 无头模式 + `--bare` | 代码编写 (唯一需要沙箱文件系统的 Agent) | P1 |
| **Python Agent Worker** | 自研 Python 服务 | asyncio + FastAPI | 其余 14 个 Agent 的运行时 | P1 |
| **MCP Gateway** | 自研 Go 服务 (net/http) | 反向代理实现 MCP Server 协议 | Agent 工具调用统一入口 | P1 |
| **AITP Wrapper** | 自研 Node CLI (`ai-task`) | Commander.js + Claude Code SDK | 给 Claude Code 包上下文注入层 | P1 |
| **Sandbox 镜像工厂** | Dockerfile 分层构建 + CI 自动发布 | 标准 Dockerfile | 预装工具链的 Agent 基础镜像 | P1 |

#### 14.1.4 集成层

| 类别 | 组件 | 选型 | 用途 | Phase |
|---|---|---|---|---|
| **飞书集成** | 飞书开放平台 API | Webhook 接收 + Bot 消息发送 + 会议转写 API | 多源需求汇入、审批通知推送 | P1 |
| **飞书 Bot** | 自研 Python 服务 | FastAPI + 飞书 SDK | 群聊 @Bot 捕获需求、卡片消息交互 | P1 |
| **Git 集成** | Git Webhook + GitHub/GitLab API | 已有 | Push 触发 CI、PR 创建 | P1 |
| **IDE 集成** | VSCode Extension (Claude Code 官方) + MCP config | `.mcp.json` 注入 Gateway URL | Cursor/VSCode 内调系统 Skill | P2 |
| **CI 集成** | CI Pipeline 模板 + 自建 Runner | Docker Runner with tools preinstalled | CI/CD Agent 的 Staging Deploy | P1 |
| **容器平台集成** | K8s API + kubectl | 内置 | Staging 部署、金丝雀发布、回滚 | P1 |
| **监控集成** | Prometheus + AlertManager | 已有或新建 | 发布后指标监控、自动回滚判定 | P2 |

#### 14.1.5 可观测性

| 类别 | 组件 | 选型 | 用途 | Phase |
|---|---|---|---|---|
| **分布式追踪** | Grafana Tempo (或 Jaeger) | OTLP 接收 → Tempo 存储 | Agent 全链路 Trace | P1 |
| **指标** | Grafana Mimir (或 VictoriaMetrics) | Prometheus 兼容存储 | Agent 执行次数、循环轮次、上下文填充率等 | P1 |
| **日志** | Grafana Loki (或 Elasticsearch) | 结构化 JSON log → Loki | Agent 活动日志、Skill API 审计 | P1 |
| **OTel Collector** | OpenTelemetry Collector | DaemonSet 部署 | SDK → Collector → Mimir/Tempo/Loki | P1 |
| **Dashboard** | Grafana | 统一可视化 | Mission Control 的数据源后端 | P1 |
| **告警** | AlertManager + 飞书 Webhook | 内置 | 熔断/超时/异常告警 → 飞书通知 | P1 |

#### 14.1.6 安全与合规

| 类别 | 组件 | 选型 | 用途 | Phase |
|---|---|---|---|---|
| **身份认证** | OAuth 2.0 / OIDC | Keycloak 或云厂商 IAM | Mission Control 用户登录 | P2 |
| **API 认证** | JWT (短时效, Agent-scoped) | 自研 MCP Gateway 签发 | Worker → MCP Gateway 认证 | P1 |
| **网络策略** | K8s NetworkPolicy + Sandbox egress 防火墙 | 内置 | Sandbox 出站白名单 | P1 |
| **审计日志** | Loki (结构化) | OTel + log 关联 | 每次 tools/call、每次 Gate 操作全程留痕 | P1 |
| **代码安全扫描** | npm audit / pip audit / Trivy | CI 内嵌 | Sandbox 镜像漏洞扫描 (CI 自动) | P1 |
| **Secret 扫描** | GitGuardian / truffleHog | CI 内嵌 | 防止 Agent 误将 API Key 写入代码 | P2 |

#### 14.1.7 开发工具链

| 类别 | 组件 | 选型 | 用途 | Phase |
|---|---|---|---|---|
| **本地开发** | Docker Compose | 所有中间件一键拉起 | 开发者本机 | P1 |
| **API 文档** | OpenAPI 3.1 (自动生成) | A4 Spec Writer 产出 | Skill API 文档 | P2 |
| **Schema 迁移** | Alembic (Python) / Prisma (Node) | 常规 | DB Schema 变更管理 | P1 |
| **Temporal UI** | Temporal Web UI (内置) | 已有 | 调试工作流 | P1 |
| **NATS 监控** | NATS Board / Prometheus Exporter | 内置 | Event Bus 健康 | P1 |
| **E2E 测试 (自己测自己)** | Playwright + Jest | 同一套 | 系统自身的测试 | P2 |

---

### 14.2 分阶段服务器资源需求矩阵

> 以下为**自建 / 私有云**资源估算。如果使用 AWS/GCP 托管服务 (RDS/ElastiCache/MSK)，运维负担更轻但月费略高。

#### 14.2.1 Phase 1（MVP · 0–3 月 · 最小闭环）

| 组件 | 实例规格 | 数量 | vCPU 合计 | RAM 合计 | 存储 |
|---|---|---|---|---|---|
| PostgreSQL (含 pgvector) | 4 vCPU, 16 GB | 2 (HA) | 8 | 32 GB | 200 GB SSD |
| Redis | 2 vCPU, 4 GB | 1 | 2 | 4 GB | — |
| NATS | 2 vCPU, 4 GB | 1 | 2 | 4 GB | 20 GB SSD |
| Temporal Server | 2 vCPU, 4 GB | 1 | 2 | 4 GB | 50 GB SSD (共用 PG) |
| Mission Control (Next.js) | 2 vCPU, 4 GB | 2 | 4 | 8 GB | — |
| Orch Worker (Python) | 2 vCPU, 4 GB | 2 | 4 | 8 GB | — |
| Agent Workers (Python) | 2 vCPU, 4 GB | 3 | 6 | 12 GB | — |
| MCP Gateway (Go) | 1 vCPU, 1 GB | 2 | 2 | 2 GB | — |
| Dev Agent Sandbox (Docker) | 2 vCPU, 4 GB | 按需 0–4 | 峰值 8 | 峰值 16 GB | 临时 20 GB × 4 |
| OTel Collector | 1 vCPU, 1 GB | 1 | 1 | 1 GB | — |
| Grafana + Tempo + Loki | 2 vCPU, 8 GB | 1 (all-in-one) | 2 | 8 GB | 100 GB SSD |
| K8s Control Plane | — | 云托管 | — | — | — |
| **合计** | | | **峰值 ~41** | **峰值 ~99 GB** | **~370 GB SSD** |

**月费估算（自建）**：**~$1,200–1,800**（3 台裸金属 × $400–600/月）+ LLM API 费用另计
**月费估算（云托管服务：RDS + ElastiCache + EKS）**：**~$2,000–2,500**

**LLM API 费用估算（Phase 1，日均 10 需求）**：

| 消费者 | 模型 | 日均 token 估算 | 日均费用 (API 定价) |
|---|---|---|---|
| Dev Agent (Claude Code) | Sonnet 默认, Opus 降级时 | ~1.5M input + ~200K output | ~$40–60 |
| 其他 Agent Workers (P1/P2/P3) | Haiku (分析) + Sonnet (生成) | ~500K input + ~150K output | ~$8–12 |
| Embedding (Voyage) | voyage-code-3 | ~2M tokens | ~$0.30 |
| **日均 LLM 总费用** | | | **~$50–75** |
| **月均 LLM 费用** | | | **~$1,500–2,250** |

#### 14.2.2 Phase 2（扩展 · 3–6 月 · 需求→设计 + 知识沉淀）

Phase 1 基础上增加：

| 组件 | 实例规格 | 数量 | vCPU 合计 | RAM 合计 | 存储 |
|---|---|---|---|---|---|
| Neo4j | 4 vCPU, 16 GB | 1 | 4 | 16 GB | 200 GB SSD |
| Agent Workers (Python) 扩容 | +3 (共 6) | 6 | 12 | 24 GB | — |
| Dev Agent Sandbox | +并发 2 (共 6) | 峰值 6 | +4 | +8 GB | — |
| Vault | 2 vCPU, 4 GB | 1 | 2 | 4 GB | 20 GB SSD |
| 飞书 Bot Service | 2 vCPU, 4 GB | 1 | 2 | 4 GB | — |
| Grafana Stack 拆分 | Tempo/Mimir/Loki 各 1 | 3 | 6 | 16 GB | 300 GB SSD |
| **Phase 1+2 合计** | | | **峰值 ~69** | **峰值 ~171 GB** | **~890 GB SSD** |

**月费估算**：**~$3,000–4,000** + LLM API **~$3,000–4,500/月**（需求增加 + 更多 Agent）

#### 14.2.3 Phase 3（生产 · 6–12 月 · 全局智能 + 高可用）

Phase 2 基础上增加：

| 组件 | 实例规格 | 数量 | vCPU 合计 | RAM 合计 | 存储 |
|---|---|---|---|---|---|
| PostgreSQL 升级 | 8 vCPU, 32 GB | 2 (HA) | 16 | 64 GB | 1 TB SSD |
| NATS 升级为 3 节点 | 2 vCPU, 4 GB × 3 | 3 | 6 | 12 GB | 50 GB SSD × 3 |
| Neo4j 升级为 3 节点 (HA) | 4 vCPU, 16 GB × 3 | 3 | 12 | 48 GB | 500 GB SSD × 3 |
| Agent Workers 扩容 | +4 (共 10) | 10 | 20 | 40 GB | — |
| Dev Agent Sandbox (Firecracker) | 峰值 12 | 峰值 12 | 峰值 24 | 峰值 48 GB | 临时 |
| Staging 环境 (独立) | 按需 | 独立集群 | 16 | 32 GB | 200 GB SSD |
| Perf 环境 (压测专用) | 按需 | 独立集群 | 8 | 16 GB | 100 GB SSD |
| Grafana Stack 全量 | 独立 HA | 各 2 | 12 | 32 GB | 500 GB SSD |
| K8s Node 扩容 | +3 节点 (共 6–8) | 6–8 | 96–128 | 192–256 GB | — |
| **Phase 1–3 合计** | | | **~210–240** | **~500–600 GB** | **~4 TB SSD** |

**月费估算**：**~$8,000–12,000** + LLM API **~$6,000–10,000/月**

#### 14.2.4 GPU 需求

| 场景 | GPU | 用途 |
|---|---|---|
| **默认 (Phase 1–3)** | **无 GPU** | 所有 LLM 调用走 Anthropic API；Embedding 走 Voyage AI API |
| **私有化 Embedding** | 1× A10 (24 GB) 或 L40S (48 GB) | 部署 `stella_en_1.5B` 替代 Voyage AI |
| **私有化 LLM (可选)** | 4–8× A100/H100 (80 GB) | 部署 Claude 等级模型 (vLLM 集群) |

---

### 14.3 常见遗漏项查漏补缺 (20 项)

| # | 遗漏项 | 选型 | 备注 |
|---|---|---|---|
| 1 | **域名 & TLS 证书** | cert-manager + Let's Encrypt (自动) | `mc.ai-native.company.com` / `mcp-gw.ai-native.company.com` |
| 2 | **飞书应用凭证管理** | Vault (或 K8s Secret) | 飞书 App ID / App Secret / Verification Token |
| 3 | **NATS TLS** | NATS 内置 TLS + cert-manager | 生产环境必须加密 Event Bus 流量 |
| 4 | **Temporal TLS + Auth** | Temporal mTLS + 自签 CA (内部) | 生产环境必须开启 |
| 5 | **PostgreSQL 备份** | pgBackRest 或云厂商自动备份 | 每日全量 + 持续 WAL 归档 |
| 6 | **Neo4j 备份** | neo4j-admin backup (在线) | 每日一次 |
| 7 | **S3 生命周期策略** | 30 天后自动归档 Glacier | Trace/截图/Video 量大但低价值 |
| 8 | **WebSocket 网关** | 独立 Node 服务 (Socket.IO + Redis adapter) | MC 的实时推送需要 sticky session |
| 9 | **金丝雀部署系统** | Argo Rollouts 或 Flagger | 替代手写 K8s API 调用的金丝雀逻辑 |
| 10 | **Feature Flag** | LaunchDarkly / Unleash (自建) | A13 发布时的灰度开关 |
| 11 | **npm 私有源** | Verdaccio (自建) 或 GitHub Packages | Agent Sandbox 内的 `npm install` 不走公网 |
| 12 | **PyPI 私有源** | Devpi (自建) 或 AWS CodeArtifact | 同上 |
| 13 | **Claude Code 许可管理** | Anthropic Console 组织管理 | 确保 `claude -p` 调用有有效订阅 |
| 14 | **成本追踪/预算告警** | Anthropic API usage dashboard + AWS/GCP Budget Alerts | 防止 Token 费用失控 (日均 >$200 告警) |
| 15 | **Slack/飞书 On-call** | PagerDuty 或飞书 Bot 告警通道 | 熔断/Agent 死循环/DB 宕机 → 自动通知值班 |
| 16 | **Playwright Browser 依赖** | Sandbox 镜像预装 Chromium + 依赖库 | `npx playwright install --with-deps chromium` |
| 17 | **k6 二进制** | Sandbox 镜像预装 | `apk add k6` 或下载官方 binary |
| 18 | **WireMock 独立部署** | K8s Deployment (长期运行) | 集成测试共用，不每次起新容器 |
| 19 | **文档生成** | A4 Spec Writer 产出 → Markdown → 可选 pdf (pandoc) | 非 MVP，但架构文档里提到过 |
| 20 | **系统自身的 CI/CD** | GitHub Actions + ArgoCD | 本系统本身的代码也要走 CI/CD |

---

## 十五、国产模型适配与多 Provider 切换方案

> **场景**：企业可能要求使用 DeepSeek 作为主力 LLM、通义千问/GLM 做多模态，以及需要一套配置即可切换 provider 的机制，而非深度绑定单一厂商。

### 15.1 总体架构：LLM Provider 抽象层

```
所有 Agent 不是直接调 anthropic.messages.create()
   │
   ▼
┌─────────────────────────────────────────────┐
│          LLM Provider Adapter (自研)          │
│                                              │
│  llm.chat(model, messages, tools, ...)       │
│  llm.chat_stream(model, messages, ...)       │
│  llm.image_understand(model, image_urls, ..) │
│  llm.embed(texts, model)                     │
│                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │DeepSeek  │ │Anthropic │ │Qwen/GLM  │     │
│  │Adapter   │ │Adapter   │ │Adapter   │     │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘     │
│       │            │            │            │
│       ▼            ▼            ▼            │
│  https://api    https://api   https://dash   │
│  .deepseek.com  .anthropic   scope.aliyun   │
│                 .com         .com           │
└─────────────────────────────────────────────┘
```

每个 Adapter 实现的接口完全相同，Agent 代码**不写死 provider**：

```python
# llm_provider/adapter.py —— 统一接口
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str
    model: str
    tool_calls: list | None
    usage: dict                     # {input_tokens, output_tokens, cost_usd}

@dataclass 
class LLMStreamChunk:
    delta_text: str | None
    delta_tool_call: dict | None
    finish_reason: str | None

class LLMAdapter(ABC):
    """所有 LLM Provider 的统一接口"""
    
    @abstractmethod
    async def chat(self, model: str, messages: list, 
                   tools: list | None = None,
                   temperature: float = 0.3,
                   max_tokens: int = 4096) -> LLMResponse:
        ...
    
    @abstractmethod
    async def chat_stream(self, model: str, messages: list,
                          tools: list | None = None,
                          temperature: float = 0.3,
                          max_tokens: int = 4096) -> AsyncIterator[LLMStreamChunk]:
        ...
    
    @abstractmethod
    async def image_understand(self, model: str, image_urls: list[str],
                                prompt: str) -> str:
        """多模态：理解图片内容。不是所有 provider 都支持——见 15.3"""
        ...
    
    @abstractmethod
    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        ...
```

### 15.2 各 Provider 的具体 Adapter 实现

#### 15.2.1 DeepSeek Adapter（主力文本 LLM）

```python
# llm_provider/deepseek_adapter.py
import httpx
from .adapter import LLMAdapter, LLMResponse, LLMStreamChunk

class DeepSeekAdapter(LLMAdapter):
    """
    DeepSeek API 适配器。
    API 兼容 OpenAI 格式 → 可以用 openai Python SDK，示例用 httpx 展示核心逻辑。
    """
    
    BASE_URL = "https://api.deepseek.com"  # 或企业代理: https://deepseek-gw.company.com/v1
    
    # 模型能力映射
    MODELS = {
        "text-fast":      "deepseek-chat",           # 日常用，便宜快速
        "text-powerful":  "deepseek-reasoner",       # 复杂推理 (R1)
        "code-primary":   "deepseek-chat",           # 代码生成主力
        "code-complex":   "deepseek-reasoner",       # 复杂代码用 R1 深思
    }
    
    # DeepSeek 的特殊行为配置
    FEATURES = {
        "supports_tool_calling": True,               # ✅ 支持 function calling
        "supports_streaming": True,                  # ✅ 支持 SSE 流式
        "supports_vision": False,                    # ❌ 不支持图片理解——需切换到 Qwen/GLM
        "supports_embedding": False,                 # ❌ 无 Embedding API——需切换到其他 provider
        "max_input_tokens": 128_000,                 # 128K 上下文窗口
        "rate_limit_rpm": 500,                       # 默认 500 RPM
    }
    
    async def chat(self, model: str, messages: list,
                   tools: list | None = None,
                   temperature: float = 0.3,
                   max_tokens: int = 4096) -> LLMResponse:
        
        body = {
            "model": self.MODELS.get(model, model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = self._convert_tools_to_openai_format(tools)
        
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=body
            )
            resp.raise_for_status()
            data = resp.json()
        
        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"].get("content", ""),
            model=data["model"],
            tool_calls=choice["message"].get("tool_calls"),
            usage={
                "input_tokens": data["usage"]["prompt_tokens"],
                "output_tokens": data["usage"]["completion_tokens"],
                "cost_usd": self._calculate_cost(
                    data["usage"]["prompt_tokens"],
                    data["usage"]["completion_tokens"],
                    model
                )
            }
        )
    
    async def chat_stream(self, model, messages, tools=None, temperature=0.3, max_tokens=4096):
        body = {
            "model": self.MODELS.get(model, model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = self._convert_tools_to_openai_format(tools)
        
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", f"{self.BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0].get("delta", {})
                        yield LLMStreamChunk(
                            delta_text=delta.get("content"),
                            delta_tool_call=delta.get("tool_calls", [None])[0] if delta.get("tool_calls") else None,
                            finish_reason=chunk["choices"][0].get("finish_reason")
                        )
    
    async def image_understand(self, model, image_urls, prompt):
        # DeepSeek 不支持多模态 → 自动路由到多模态 provider
        raise NotImplementedError("DeepSeek does not support vision. Use multimodal_provider instead.")
    
    async def embed(self, texts, model="text-embedding"):
        # DeepSeek 无 Embedding API → 自动路由到 Embedding provider
        raise NotImplementedError("DeepSeek does not support embedding. Use embedding_provider instead.")
    
    def _calculate_cost(self, input_tokens, output_tokens, model):
        # DeepSeek 定价 (2026 年中): chat≈¥1/M input, ¥2/M output; reasoner≈¥4/M input, ¥16/M output
        price_per_m = {
            "text-fast":     (1.0, 2.0),      # (input, output) 人民币/百万token
            "text-powerful": (4.0, 16.0),
            "code-primary":  (1.0, 2.0),
            "code-complex":  (4.0, 16.0),
        }
        in_price, out_price = price_per_m.get(model, (1.0, 2.0))
        cny = (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
        return round(cny / 7.2, 4)  # 转换为 USD (approximate)
    
    def _convert_tools_to_openai_format(self, tools):
        """将内部 tool 格式转为 OpenAI function calling 格式"""
        return [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t.get("parameters", {"type": "object", "properties": {}})
            }
        } for t in tools]
```

#### 15.2.2 通义千问 (Qwen) Adapter（多模态主力）

```python
# llm_provider/qwen_adapter.py
class QwenAdapter(LLMAdapter):
    """
    通义千问 API 适配器 (Qwen3 系列)。
    核心用途: 多模态（UI 截图分析、设计稿对比、视觉回归失败分析）。
    """
    
    BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"  # OpenAI 兼容模式
    
    MODELS = {
        "vision":        "qwen-vl-max",             # 多模态理解 (UI 截图、设计稿)
        "vision-fast":   "qwen-vl-plus",            # 轻量多模态
        "text-fast":     "qwen-turbo",              # 文本备用
        "text-powerful": "qwen-plus",               # 中等推理
        "code-primary":  "qwen-coder-plus",         # 代码生成 (专有模型)
    }
    
    FEATURES = {
        "supports_tool_calling": True,
        "supports_streaming": True,
        "supports_vision": True,                     # ✅ 支持图片理解
        "supports_embedding": True,                  # ✅ 有 Embedding API (text-embedding-v3)
        "max_input_tokens": 131_072,
        "rate_limit_rpm": 200,
    }
    
    async def image_understand(self, model, image_urls, prompt):
        """用 Qwen VL 理解 UI 截图——这是多模态的核心场景"""
        # 构建 vision messages
        content = [{"type": "text", "text": prompt}]
        for url in image_urls:
            content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })
        
        body = {
            "model": self.MODELS.get(model, "qwen-vl-max"),
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 2000,
        }
        
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body
            )
            return resp.json()["choices"][0]["message"]["content"]
    
    async def embed(self, texts, model="text-embedding-v3"):
        body = {
            "model": "text-embedding-v3",
            "input": {"texts": texts},
            "parameters": {"text_type": "document"}
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body
            )
            data = resp.json()
            return [item["embedding"] for item in data["output"]["embeddings"]]
```

#### 15.2.3 智谱 GLM Adapter（多模态备用 + 代码理解）

```python
# llm_provider/glm_adapter.py
class GLMAdapter(LLMAdapter):
    """
    智谱 GLM-5 API 适配器。
    核心用途: 多模态 + 长上下文代码理解 (GLM 支持 128K→1M)。价格极具竞争力。
    """
    
    BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    
    MODELS = {
        "vision":        "glm-5v",                   # 多模态主力
        "text-fast":     "glm-5-flash",              # 免费/极低价格，日常分析用
        "text-powerful": "glm-5",                     # 复杂推理
        "code-primary":  "glm-5",                     # 代码生成
        "long-context":  "glm-5",                     # 利用 128K/1M 长上下文
    }
    
    FEATURES = {
        "supports_tool_calling": True,
        "supports_streaming": True,
        "supports_vision": True,                     # ✅ GLM-5V 支持图片+视频理解
        "supports_embedding": True,                  # ✅ Embedding-3
        "supports_long_context": True,               # ✅ 128K default, 1M extended
        "max_input_tokens": 128_000,
        "rate_limit_rpm": 300,
    }
```

#### 15.2.4 Anthropic Adapter（保留，用于复杂代码场景）

保留在系统中但不再是唯一选项。对于 Claude Code CLI 的 Dev Agent，仍然走 Anthropic——因为 Claude Code 的工具使用、代码 diff 精确度、CLI 生态是最好的。但对于 P1–P3 的"读文档/写 Spec/做 RAG/评估"类 Agent，可以完全切换到 DeepSeek。

### 15.3 统一 Provider 管理器：自动路由与切换

```python
# llm_provider/manager.py
class LLMProviderManager:
    """
    统一 LLM 调用入口，Agent 代码只调这个 Manager，不直接调具体 Adapter。
    
    路由逻辑:
    - 文本 LLM (默认): DeepSeek
    - 多模态 (截图分析): 千问 Qwen VL → fallback GLM-5V
    - Embedding: Qwen text-embedding-v3 → fallback voyage-code-3
    - Dev Agent (Claude Code CLI): Anthropic (唯一场景)
    """
    
    def __init__(self, config: dict):
        self.adapters = {}
        self.routing = config.get("routing", {})
        
        # 按需初始化 adapter（未配置 API key 的 provider 不初始化）
        if config.get("deepseek_api_key"):
            self.adapters["deepseek"] = DeepSeekAdapter(config["deepseek_api_key"],
                                                        config.get("deepseek_base_url"))
        if config.get("anthropic_api_key"):
            self.adapters["anthropic"] = AnthropicAdapter(config["anthropic_api_key"])
        if config.get("qwen_api_key"):
            self.adapters["qwen"] = QwenAdapter(config["qwen_api_key"])
        if config.get("glm_api_key"):
            self.adapters["glm"] = GLMAdapter(config["glm_api_key"])
    
    async def chat(self, 
                   messages: list,
                   model: str | None = None,
                   task_type: str = "text",          # "text" | "code" | "review" | "analysis"
                   tools: list | None = None,
                   temperature: float = 0.3,
                   max_tokens: int = 4096) -> LLMResponse:
        """
        自动路由到合适的 provider + model。
        """
        provider, actual_model = self._route(task_type, model)
        adapter = self.adapters[provider]
        
        try:
            return await adapter.chat(actual_model, messages, tools, temperature, max_tokens)
        except Exception as e:
            # Fallback 逻辑
            fallback = self._get_fallback(provider, task_type)
            if fallback:
                fb_provider, fb_model = fallback
                return await self.adapters[fb_provider].chat(fb_model, messages, tools, temperature, max_tokens)
            raise
    
    async def image_understand(self, image_urls: list[str], prompt: str) -> str:
        """多模态：始终走 Qwen → fallback GLM"""
        for provider in ["qwen", "glm"]:
            if provider in self.adapters:
                try:
                    adapter = self.adapters[provider]
                    return await adapter.image_understand("vision", image_urls, prompt)
                except Exception:
                    continue
        raise RuntimeError("No multimodal provider available. Configure QWEN_API_KEY or GLM_API_KEY.")
    
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embedding：Qwen → voyage → 本地模型"""
        for provider in ["qwen", "voyage"]:  # 先走千问 embedding
            if provider in self.adapters:
                return await self.adapters[provider].embed(texts)
        # 都不行就走 pgvector 内置的本地 embedding（最慢但能跑）
        return local_embed(texts)
    
    def _route(self, task_type: str, override_model: str | None) -> tuple[str, str]:
        """
        核心路由表——控制每种任务类型走哪个 provider 的哪个 model。
        
        可按项目配置 .ai-native/llm.yaml 覆盖。
        """
        # 允许调用方直接指定 model (如 "deepseek:deepseek-reasoner")
        if override_model and ":" in override_model:
            provider, model = override_model.split(":", 1)
            return provider, model
        
        default_routes = {
            "text":     ("deepseek", "text-fast"),         # 日常: DeepSeek Chat
            "code":     ("deepseek", "code-primary"),      # 代码: DeepSeek
            "complex":  ("deepseek", "code-complex"),      # 复杂推理: DeepSeek R1
            "review":   ("deepseek", "text-fast"),         # 评审: DeepSeek
            "analysis": ("deepseek", "text-fast"),         # 分析: DeepSeek
            "vision":   ("qwen", "vision"),                # 多模态: 千问 VL
        }
        
        if override_model and ":" not in override_model:
            # 直接 model 名 → 用默认 provider (deepseek)
            return "deepseek", override_model
        
        route = default_routes.get(task_type, ("deepseek", "text-fast"))
        
        # 如果首选 provider 不可用 → fallback
        if route[0] not in self.adapters:
            return self._get_fallback(route[0], task_type) or ("deepseek", "text-fast")
        
        return route
    
    def _get_fallback(self, failed_provider: str, task_type: str) -> tuple[str, str] | None:
        """Provider 故障时的自动降级链"""
        fallback_chain = {
            "deepseek":  [("anthropic", "claude-haiku-4-5"), ("glm", "text-fast"), ("qwen", "text-fast")],
            "anthropic": [("deepseek", "text-fast"), ("glm", "text-fast")],
            "qwen":      [("glm", "vision"), ("deepseek", "text-fast")],  # vision → GLM 有 vision
            "glm":       [("qwen", "vision"), ("deepseek", "text-fast")],
        }
        
        for fb_provider, fb_model in fallback_chain.get(failed_provider, []):
            if fb_provider in self.adapters:
                return fb_provider, fb_model
        return None
```

### 15.4 配置切换：一行 YAML 即可

所有 Agent 的 LLM 调用都在 `LLMProviderManager` 统一入口，provider 切换只需改配置：

```yaml
# 全局默认配置 (K8s ConfigMap: llm-provider-config)
llm:
  # ── 主力文本 LLM ──
  primary:
    provider: deepseek
    base_url: https://api.deepseek.com             # 或企业代理: https://deepseek-gw.company.com/v1
    api_key: "${from_vault:llm/deepseek-key}"
    models:
      fast: deepseek-chat
      powerful: deepseek-reasoner
  
  # ── 多模态 LLM ──
  multimodal:
    provider: qwen                                 # 千问 VL
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: "${from_vault:llm/qwen-key}"         # 阿里云 DashScope API Key
    models:
      vision: qwen-vl-max
      vision_fast: qwen-vl-plus
    fallback:
      provider: glm                                # 千问挂了走 GLM-5V
      base_url: https://open.bigmodel.cn/api/paas/v4
      api_key: "${from_vault:llm/glm-key}"
      models:
        vision: glm-5v
  
  # ── Embedding ──
  embedding:
    provider: qwen                                 # 千问 text-embedding-v3
    model: text-embedding-v3
    fallback:
      provider: voyage
      model: voyage-code-3
      api_key: "${from_vault:llm/voyage-key}"
  
  # ── Dev Agent 专用 (Claude Code CLI) ──
  dev_agent:
    provider: anthropic                            # Claude Code CLI 必须用 Anthropic
    base_url: https://api.anthropic.com
    api_key: "${from_vault:llm/anthropic-key}"
    models:
      default: claude-sonnet-4-6
      fallback: claude-haiku-4-5

  # ── 路由规则 (哪些任务类型走哪个 provider) ──
  routing:
    text: deepseek
    code: deepseek
    complex: deepseek                              # DeepSeek R1 做复杂推理
    vision: qwen                                   # 千问 VL 做多模态
    embedding: qwen
    dev: anthropic                                 # Dev Agent 不变
```

**切换示例**：

```yaml
# 场景 A: 全用国产 → DeepSeek + 千问 + GLM (上面默认配置)
# 场景 B: 只用 Anthropic → 改 routing 全部指向 anthropic
routing:
  text: anthropic
  code: anthropic
  complex: anthropic
  vision: anthropic     # Claude 也支持 vision

# 场景 C: 混合——DeepSeek 主力 + Anthropic 复杂代码兜底
routing:
  text: deepseek
  code: deepseek        # 日常代码用 DeepSeek
  complex: anthropic    # 复杂代码走 Claude Opus (DeepSeek R1 不稳定时)
  vision: qwen
```

### 15.5 多模态的具体使用场景与 Provider 对标

| 场景 | 原方案 (Anthropic only) | 新方案 (国产混合) | 所用 Provider |
|---|---|---|---|
| **A11 Critic 分析失败 UI 截图** | Claude Vision 读截图 → 描述"按钮被 overflow:hidden 裁剪" | **千问 VL Max** 读截图 → 同效果，1/3 价格 | Qwen VL |
| **A3 UI Generator 设计稿对比** | Claude Vision 对比 before/after → 差异描述 | **千问 VL** 或 **GLM-5V** | Qwen GLM |
| **A9 Coder 看截图修 bug** | Claude Code CLI 内置多模态 | **不变**——Dev Agent 的 Claude Code CLI 自带多模态 | Anthropic (Dev Agent only) |
| **A12 Code Review 理解架构图** | 无 (原方案不看图) | **GLM-5V** 或 **千问 VL** 解读架构白板照片/手绘图 | Qwen GLM |
| **需求阶段的产品草图识别** | 无 | **千问 VL** 将手绘线框图转为结构化描述 → 给 A3 UI Generator | Qwen VL |
| **A7 Test Case Gen 读 UI 设计稿生成测试** | 无 | **千问 VL** 从设计稿自动推导交互逻辑 → 生成 Playwright 测试步骤 | Qwen VL |

### 15.6 成本对比（参考）

| Provider | 模型 | 输入价格 (¥/M tokens) | 输出价格 (¥/M tokens) | 多模态 | 适用 |
|---|---|---|---|---|---|
| **DeepSeek** | deepseek-chat | ~1 | ~2 | ❌ | 日常文本/代码主力 |
| **DeepSeek** | deepseek-reasoner | ~4 | ~16 | ❌ | 复杂推理 (熔断降级时) |
| **千问** | qwen-vl-max | ~3 | ~12 | ✅ | 多模态主力 |
| **千问** | qwen-turbo | ~0.3 | ~0.6 | ❌ | 极低成本批量分析 |
| **GLM** | glm-5-flash | **免费** | **免费** | ❌ | 开发环境/批量简单任务 |
| **GLM** | glm-5v | ~5 | ~5 | ✅ | 多模态备用 |
| **Anthropic** | claude-sonnet-4-6 | ~$3/M (~¥22) | ~$15/M (~¥108) | ✅ | Dev Agent (仅此场景) |
| **Anthropic** | claude-haiku-4-5 | ~$0.8/M (~¥6) | ~$4/M (~¥29) | ✅ | 降级备用 |

> 全切 DeepSeek + 千问 后，非 Dev Agent 的 LLM 成本可降低 **~80%**（DeepSeek chat 比 Claude Sonnet 便宜一个数量级）。Dev Agent 因为依赖 Claude Code CLI 的代码工具链生态，仍保留 Anthropic，但日均 Dev Agent 调用量是可控的（每个需求 1–3 次）。

### 15.7 Dev Agent 的多模型支持

Dev Agent 仍用 Claude Code CLI + Anthropic 的原因（不可替换）：

1. **Claude Code 的工具链集成**（Read/Write/Edit/Bash/Grep/Glob）是目前唯一成熟的"AI 写代码"CLI 工具，DeepSeek/千问/GLM 都没有等价的开箱即用 CLI
2. **Claude Code 的 agent loop 稳定**——它能自己做"修复 → Lint → 再修复"的循环，而不需要外部编排
3. **MCP 协议原生支持**——Claude Code 通过 `.mcp.json` 接入我们的 MCP Gateway 是零代码的

如果未来 DeepSeek 或国产模型提供了同等成熟的 coding agent CLI，切换就是改一行配置——因为 AITP Wrapper (`ai-task`) 本身是 provider-agnostic 的：

```bash
# 现在: Claude Code
claude --bare -p "<prompt>" --output-format json

# 未来: DeepSeek Coder CLI (如果有了)
deepseek-code --bare -p "<prompt>" --output-format json
```

Wrapper 只需替换二进制名，接口不变。

### 15.8 Embedding 的多 Provider 支持

```python
# llm_provider/embedding_router.py
class EmbeddingRouter:
    """
    Embedding 路由：千问 text-embedding-v3 → Voyage → 本地模型
    """
    
    PROVIDERS = {
        "qwen": {
            "model": "text-embedding-v3",
            "dimensions": 1024,
            "batch_size": 25,              # 千问 Embedding API 不支持批量，需逐条调
            "cost_per_1m": 0.7,            # ¥0.7/百万token
        },
        "voyage": {
            "model": "voyage-code-3",
            "dimensions": 1024,
            "batch_size": 128,             # Voyage 支持批量
            "cost_per_1m": 0.14,           # $0.14/百万token (≈¥1)
        },
        "local": {
            "model": "BAAI/bge-m3",        # 本地 embedding 模型，需要 1× GPU
            "dimensions": 1024,
            "batch_size": 256,
            "cost_per_1m": 0,
        }
    }
```

---

## 十六、VisAgent 现有能力评估与复用方案

> VisAgent（`D:\Vibe Coding\VisAgent`）是一套已实现的自动化测试系统，含 74 个 Go 源文件、25 张数据表、50+ API 端点。它覆盖了脚本生成、脚本执行、自愈修复、浏览器管理、元素感知、多供应商 LLM、实时屏幕直播、CI/CD 集成等完整链路。本节评估它与本系统的重叠点和具体复用方案。

### 16.1 重叠度总览

| A7/A11 模块 | VisAgent 对应实现 | 重叠度 | 复用方式 |
|---|---|---|---|
| **A7 脚本生成** | `script/generator.go`（Mode B VLM / Mode C 录制） | **~90%** | 直接复用作为 A7 的生成引擎 |
| **A7 测试脚手架** | `script/smoke.go`（冒烟验证 + LLM 重试） | **~80%** | 复用冒烟管线 |
| **A11 脚本执行** | `script/executor.go`（`npx playwright test --reporter=json`） | **~95%** | 直接复用，接口完全匹配 |
| **A11 Critic 弱断言** | 无（VisAgent 不做断言质量评估） | **0%** | 我们自己写 |
| **A11 Critic 变异测试** | 无 | **0%** | 我们自己写 (Stryker) |
| **A11 Critic 失败归因** | `healer/patcher.go`（L1 选择器修复）+ `healer/rewrite.go`（L2 上下文重写） | **~60%** | 复用 L1/L2 修复逻辑，补上 LLM 归因 |
| **A11 执行监控** | `screencast/broadcaster.go`（WebSocket + 异步截图） | **~85%** | 直接复用实时推送架构 |
| **测试基础设施** | `browser/manager.go`（Playwright Chromium 管理） | **~80%** | 复用浏览器池管理 |
| **环境初始化** | `model/environment.go`（BaseURL + 配置 JSON） | **~50%** | 适配到我们的 Testcontainers 方案 |
| **多 Provider LLM** | `llm/client.go`（含电路熔断器、指数退避） | **~85%** | 复用熔断器 + 退避逻辑，替换本文 §十五 的 Python 版 LLM Provider Manager |
| **选择器验证** | `script/selector_validator.go`（实时 DOM 校验） | **100%** | **直接复用——我们完全没做这个** |
| **自愈引擎** | `healer/healer.go`（L1→L2→L3 三层） | **100%** | **直接复用——我们设计中有外部循环但没实现自动修复** |
| **多分辨率** | `script/resolution.go`（7 断点坐标矩阵） | **100%** | **直接复用——我们文档里只提了设备预设，没实现** |
| **Git 双向同步** | `script/store.go` + `script/syncer.go`（DB+Git 双写+乐观锁） | **90%** | 复用双写机制 |
| **缺陷管理** | `handler/defect_handler.go`（自动创建 + Jira 同步） | **70%** | 适配到我们的 Event Bus |
| **样本管理** | `handler/sample_handler.go`（截图+标注自动收集） | **60%** | 可选复用 |

### 16.2 VisAgent 的最大差异化能力（我们完全没做但应该有的）

以下 6 项是 VisAgent 独有能力，且在我们的 `04`/`05` 文档中只有设计、没有实现细节。**直接复用能省 3–6 个月开发量**：

| # | 能力 | VisAgent 模块 | 在我们系统中的价值 | 省多少 |
|---|---|---|---|---|
| 1 | **三层自愈引擎** | `healer/` (healer.go, patcher.go, rewrite.go, auditor.go, monitor.go) | 测试失败后**自动修复选择器/脚本**，而非打回 A9 重新生成——比我们的"外部循环 ≤3 次"更智能 | **2–3 月** |
| 2 | **选择器实时验证** | `script/selector_validator.go` | 生成脚本前先**在真实浏览器中验证选择器是否存在**，大幅减少"生成就跑不通" | **1 月** |
| 3 | **冒烟+LLM重试** | `script/smoke.go` + `generator.go` (generateWithRetry) | 脚本生成后立即执行冒烟，失败自动喂回 LLM 重写——这就是我们设计的 A7→A11 内部循环的**现成实现** | **1.5 月** |
| 4 | **多分辨率坐标矩阵** | `script/resolution.go` | 7 个强制断点独立采集元素坐标，响应式 UI 测试不再靠线性内插猜测 | **1 月** |
| 5 | **固化规则引擎** | `memory/rule_engine.go` | 同类型自愈成功 3 次自动固化为规则，**不再重复调 LLM**——直接降本 | **0.5 月** |
| 6 | **LLM 电路熔断器** | `llm/client.go` (内置 circuit breaker) | 5 次连续失败自动熔断，30s 后 half-open——比我们在 `04` 里设计的外部循环熔断**更底层、更可靠** | **0.5 月** |

### 16.3 直接复用方案：最小改造集成

#### 方案 A（推荐）：VisAgent 作为 A7 + A11 的核心执行引擎

```
┌─────────────────────────────────────────────────────────┐
│              AI Agent Control Plane                      │
│  Orchestrator (Temporal) · Event Bus (NATS) · Gate       │
└──────────────────────┬──────────────────────────────────┘
                       │ Event Bus: test.ready / test.rerun
                       ▼
┌─────────────────────────────────────────────────────────┐
│              A11 Auto Test Agent（我们自己写）             │
│  ┌──────────────────┐  ┌───────────────────────────────┐ │
│  │ A11 Tester        │  │ A11 Critic                    │ │
│  │ (Python Wrapper)  │  │ (LLM Provider → DeepSeek)    │ │
│  │ 调度 → VisAgent   │  │ 弱断言检测 (Claude API)       │ │
│  │      HTTP API     │  │ 变异测试 (Stryker, 我们自己)  │ │
│  └────────┬─────────┘  │ 失败归因 → 调用 VisAgent Healer│ │
│           │            └───────────────┬───────────────┘ │
│           │ HTTP API                   │ HTTP API        │
│           ▼                            ▼                 │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              VisAgent（直接部署为独立服务）             │ │
│  │                                                     │ │
│  │  • 脚本生成: Generator.ModeB/C → .spec.ts            │ │
│  │  • 脚本执行: Executor.Execute() → 执行结果 JSON       │ │
│  │  • 自愈引擎: Healer.Heal() → L1 Patch / L2 Rewrite   │ │
│  │  • 冒烟验证: SmokeTest()                             │ │
│  │  • 选择器验证: SelectorValidator                     │ │
│  │  • 屏幕直播: Screencast (WebSocket → MC 测试洞察)     │ │
│  │  • 报告生成: ReportService                           │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**具体对接方式**：

```python
# a11_auto_test_agent/tester.py —— 改造后
class VisAgentTester:
    """
    不再自己 subprocess.run("npx playwright test")，
    而是调 VisAgent 的 HTTP API。
    """
    def __init__(self, visagent_base_url: str, visagent_api_key: str):
        self.client = httpx.AsyncClient(
            base_url=visagent_base_url,
            headers={"Authorization": f"Bearer {visagent_api_key}"}
        )
    
    async def run_test(self, test_script_id: str, base_url: str) -> TestResult:
        """调 VisAgent 执行已有的 Playwright 脚本"""
        # 1. 创建测试任务
        task = await self.client.post("/api/v1/tasks", json={
            "name": f"AI-Native-Task-{uuid4()}",
            "type": "regression",
            "trigger_type": "ci",
            "test_case_ids": [test_script_id],
            "env_id": self._get_env_id(base_url)
        })
        task_id = task.json()["data"]["id"]
        
        # 2. 执行任务（VisAgent 内部走 Executor → 返回结果）
        exec_result = await self.client.post(f"/api/v1/tasks/{task_id}/execute")
        
        # 3. 获取执行详情（含步骤级截图/Trace/耗时/错误）
        executions = await self.client.get(f"/api/v1/tasks/{task_id}/executions")
        
        return self._convert_to_a11_format(executions.json())
    
    async def heal_and_retry(self, script_id: str, failure: TestFailure) -> HealResult:
        """测试失败时 → 调 VisAgent 自愈引擎，而非打回 A9 Dev Agent"""
        # VisAgent Healer 自动执行 L1（选择器补丁）→ L2（步骤重写）→ L3（标记人工）
        heal_result = await self.client.post(f"/api/v1/scripts/{script_id}/heal", json={
            "failed_step": failure.step_name,
            "error_message": failure.error,
            "base_url": failure.base_url,
            "viewport_w": 1920,
            "viewport_h": 1080
        })
        
        if heal_result.json()["data"]["healed"]:
            # 自愈成功 → 直接用修复后的脚本重跑，不惊动 Dev Agent
            return HealResult(success=True, new_script_id=script_id, level=heal_result.json()["data"]["level"])
        else:
            # 自愈失败（L3 人工介入）→ 这时候才触发外部循环，通知 Dev Agent
            return HealResult(success=False, fallback="trigger_dev_agent")
```

#### 方案 B（备选）：选模块嵌入

如果不想部署 VisAgent 作为独立服务，可以把最关键的几个模块**直接嵌入 A11 Agent Worker**（Go 编译为共享库或微服务）：

| 嵌入模块 | 嵌入方式 | 工作量 |
|---|---|---|
| `healer/` 自愈引擎 | Go 源码直接编译进 Python Worker（via CGO/PyO3/或独立 sidecar） | 1 周 |
| `smoke.go` 冒烟验证 | 同上，或 fork 为独立 CLI 工具 | 3 天 |
| `selector_validator.go` 选择器验证 | 独立微服务 (Go)，通过 MCP Gateway 以 Skill API 暴露 | 1 周 |
| `resolution.go` 多分辨率 | 嵌入 A7 Test Case Generator 的生成逻辑 | 3 天 |

### 16.4 改造事项（需要适配的地方）

| 改造点 | 当前 VisAgent | 需要改为 | 原因 |
|---|---|---|---|
| **LLM 供应商** | OpenAI / Azure / Ollama / Custom | 统一走我们的 `LLMProviderManager`（§十五），支持 DeepSeek + 千问 + GLM | VisAgent 的 LLM client 支持 custom OpenAI-compatible endpoint，DeepSeek 天然兼容；千问 VL 需增加 Vision adapter |
| **多模态** | GPT-4o | 千问 VL Max / GLM-5V | 国内合规 + 成本优势 |
| **事件通知** | 钉钉/飞书/Webhook | 统一走我们的 Event Bus (NATS) | 与 Orchestrator 解耦 |
| **认证** | 独立 JWT + RBAC | 复用我们的 MCP Gateway JWT（Agent-scoped token） | 避免多套认证体系 |
| **测试资产注入** | 手动创建 TestCase → 关联 Task | 从 A7 `test.ready` 事件自动创建 + 关联 | 打通 A7 → A11 自动化链路 |
| **截图存储** | MinIO（自建） | 统一走 S3（MC 前端用预签名 URL 加载） | 产品总览 `03` 中定义 |
| **WebSocket 推送** | 自建 Room Manager | 改为发布到 NATS → MC 的 WebSocket Gateway 消费 | 与现有 MC 通信架构一致 |

### 16.5 结合后的总工作量对比

| 模块 | 自研预估 | 结合 VisAgent 后 | 节省 |
|---|---|---|---|
| A7 脚本生成 (Mode B VLM) | 6–8 周 | **1 周适配**（接入 LLM Provider + Event Bus） | **5–7 周** |
| A7 冒烟验证 + LLM 重试 | 3–4 周 | **0 周**（VisAgent 原生支持） | **3–4 周** |
| A7 多分辨率坐标采集 | 2–3 周 | **0 周**（VisAgent 原生支持） | **2–3 周** |
| A11 Playwright 执行器 | 2–3 周 | **0.5 周适配**（HTTP API wrapper） | **1.5–2.5 周** |
| A11 选择器验证 | 3–4 周 | **0 周**（VisAgent 原生支持） | **3–4 周** |
| A11 自愈引擎 | 8–12 周 | **1 周适配**（HTTP API → Healer） | **7–11 周** |
| A11 实时执行监控 | 3–4 周 | **1 周适配**（WebSocket → NATS 桥接） | **2–3 周** |
| A11 报告生成 | 2 周 | **0 周**（VisAgent 原生支持） | **2 周** |
| **合计** | **29–40 周** | **4 周** | **≈节省 25–36 周（6–9 个月）** |

### 16.6 建议的分步实施

```
Week 1:  部署 VisAgent 为独立服务（Docker Compose）
         配置 LLM Provider (DeepSeek + 千问 VL) → 验证脚本生成 + 执行链路

Week 2:  写 A11 VisAgentTester（HTTP API Wrapper）
         写 A11 HealerClient（自愈调用 Wrapper）
         把 VisAgent 的 WebSocket 实时推流转发到 NATS → MC

Week 3:  对接 Event Bus: test.ready → VisAgent Task 创建
         test.completed → VisAgent Report 转换为我们的 TestExecution 格式
         打通 A7 Test Case Generator 的输出 → VisAgent 的输入

Week 4:  Stryker 变异测试集成（VisAgent 之外我们自己写）
         整体联调 + 修复
         文档：VisAgent 运维手册 + API 对接文档
```

**4 周后，A7 + A11 的核心闭环（脚本生成→执行→自愈→报告）即可完全跑通。**
