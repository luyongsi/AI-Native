# Agent 实现状态审计 (A9/A10/A11/A12/A13/K14/K15)

## 审计日期

2026-07-06

## 审计方法

逐一检查每个 Agent 的：(1) worker_launcher 注册入口；(2) 主文件实现；
(3) 子模块实现；(4) LLM 集成状态；(5) 是否存在 stub/完整实现的二选一问题。

---

## A9 Dev Agent（开发 Agent）

### 入口文件（worker_launcher 使用）

`a9_dev_agent_stub.py` — 152 行，stub 版本。
- `execute()` 调用 `ClaudeCodeBridge.execute_task()` 生成代码
- `_build_dev_plan()` 硬编码文件路径推测，`random.randint(80,300)` 估算代码行数
- `_build_diff_from_bridge_result()` 含 fallback stub diff（`# AUTO STUB`）

### Bridge 文件

`a9_claude_code_bridge.py` — 135 行。
- `ClaudeCodeBridge` **不继承 BaseAgentWorker**
- `_execute_with_llm()` 调用 `self.call_llm(...)` — **运行时必定崩溃**
  （`ClaudeCodeBridge` 没有 `call_llm` 方法）
- `_execute_mock()` 硬编码 3 种文件模板，不是真实代码生成

### 子模块（未被 launcher 使用）

`a9/a9_dev_agent.py` — 278 行，完整"双脑架构"（Coder ↔ Auditor）。
- Coder 生成代码 → Auditor 独立审查（仅看 diff，不看推理）
- 最多 3 次迭代，被拒后反馈回 Coder
- 3 次后仍未通过则 escalate 到人工

`a9/coder.py` — 366 行，隔离环境代码生成。
- git worktree 隔离、mock/LLM 双模式、自检报告
- `_call_llm_for_code_generation()` 同样通过 `ClaudeCodeBridge` — **同样会崩溃**

`a9/auditor.py` — 315 行，独立代码审查模块。
- 通过 `self.call_llm()` 调 LLM — **不继承 BaseAgentWorker，会崩溃**

`a9/metrics.py`、`a9/static_analyzer.py` — 存在但未被调用。

### 核心问题
1. 【致命】`ClaudeCodeBridge`、`CoderModule`、`AuditorModule` 都不继承 BaseAgentWorker，
   但都调用 `self.call_llm()` — 运行时必定 AttributeError
2. launcher 使用 stub 版本（`a9_dev_agent_stub`），完整双脑实现（`a9/a9_dev_agent`）闲置
3. stub 版和完整版有重复逻辑（`_build_dev_plan` 在两处各自实现）

---

## A10 CI/CD Agent（CI/CD Agent）

### 入口文件

`ci_agent.py` — 411 行。
- `worker_launcher.py` 注册为 `CICDAgent`
- 支持 YAML 配置驱动（`load_pipeline_config`）和默认 3 步流水线
- 默认流水线：Docker Build (5s mock) → Lint (3s mock) → Staging Deploy (2s mock)
- 10% 概率 mock 失败（`FAILURE_PROBABILITY = 0.10`）
- 使用独立 `EventSubscriber` 监听 `code.pushed` 事件
- 使用独立 `EventPublisher` 发布 `pipeline.passed`/`pipeline.failed`

### 子模块

无独立子模块（逻辑全部在主文件）。

### 核心问题
1. 所有管道步骤为 `asyncio.sleep()` 模拟，无真实 Docker/build/lint 执行
2. 不通过 Orchestrator dispatch（独立 NATS 订阅），与主流 Agent 模式不一致
3. 无 LLM 集成（错误诊断、日志分析均缺失）
4. YAML 配置注入仅通过 CLI 参数，launcher 中未传配置

---

## A11 Auto Test Agent（测试 Agent）

### 入口文件（两个实现）

**stub 版** `a11_test_agent_stub.py` — 148 行。launcher 当前使用。
- `_plan_tests_with_llm()` 调 LLM 生成测试策略
- `_run_tests()` — 15% 随机失败率 mock（`random.random() < 0.15`）
- `_fallback_plan()` — 硬编码 type_map 推测测试类型

**完整版** `a11_auto_test_agent.py` — 665 行。launcher 未使用。
- VisAgent 可视化测试集成（`VisAgentTester`）
- 自愈客户端（`VisAgentHealerClient`）
- 变异测试引擎（mutmut/Stryker，通过 `MutationTester`）
- Critic 模式 — 变异存活时自动生成测试用例
- 覆盖率测量 + 增量补测（`_generate_augmented_tests`）
- 测试结果保存到 MC Backend

### 子模块

全部存在：`a11/tester.py` (221 行)、`a11/healer_client.py`、`a11/result_converter.py`、
`a11/stryker_runner.py`、`a11/mutation_reporter.py`、`a11/mutation_tester.py` (287 行)、
`a11/critic_mode.py` (306 行)、`a11/test_file_writer.py`、`a11/mutation_metrics.py`

### 核心问题
1. launcher 使用 stub 版，完整 VisAgent 实现闲置
2. `_measure_coverage()` 硬编码返回 `0.82`（非真实测量）
3. `_fetch_test_cases()` 依赖 MC Backend API（`/api/tests/{req_id}/cases`）— 可能不存在

---

## A12 Code Review Agent（代码审查 Agent）

### 入口文件

`a12_code_review.py` — 161 行。launcher 使用。
- LLM 驱动的一次性审查（1 次 `call_llm()`）
- 检查项：SQL 注入、XSS、CSRF、硬编码密钥、空指针等
- 自动修复建议（warning/info 级别的 issue → auto_fix_patches）

### 子模块（未被主文件引用）

`a12/cross_module_analyzer.py` — 跨模块影响分析
`a12/cwe_mapper.py` — CWE 漏洞分类映射
`a12/security_scanner.py` — Semgrep 安全扫描
`a12/auto_fix_patcher.py` — 自动修复
`a12/review_report.py` — 审查报告生成

### 核心问题
1. 子模块全部存在但 `execute()` 中未调用任何子模块
2. 审查只有一轮（无迭代），无跨模块影响分析、无安全扫描
3. 审查输入来自 `test.passed` NATS 事件（非 Orchestrator dispatch）
4. prompt 中的安全规则列表与实际集成脱节

---

## A13 Release Agent（发布 Agent）

### 入口文件

`release_agent.py` — 178 行。launcher 使用。
- 4 阶段金丝雀发布：5% → 20% → 50% → 100%
- `_check_prometheus_metrics()` — `random.uniform()` 仿真指标
- 使用独立 `EventPublisher` 发布 `release.completed`/`release.failed`
- 使用独立 `EventSubscriber` 监听 `gate.3.approved`

### 子模块

全部存在：`a13/auto_rollback.py` (177 行)、`a13/canary_deployer.py` (102 行)、
`a13/feature_flag.py`、`a13/metrics_monitor.py` — 均未被 `release_agent.py` 引用

### 核心问题
1. 子模块全部闲置，主文件自含独立实现
2. 指标检查为纯随机仿真（每次结果不同）
3. 15% 概率 mock 失败导致 abort（`ERROR_RATE_THRESHOLD = 1.0`，random 产生 0-2%）
4. 不通过 Orchestrator dispatch（独立 NATS 订阅模式）

---

## K14 Knowledge Keeper（知识管家）

### 入口文件

`k14_knowledge_keeper.py` — 189 行。launcher 使用。
- 监听 `artifact.produced` 事件
- 写入 `knowledge_chunks` 表（pgvector）
- **embedding 为 1024 维零向量占位**

### 子模块

`k14/artifact_vectorizer.py` (234 行) — **与主文件功能重复**。
- 同样写入 knowledge_chunks，同样零向量
- 多了一些逻辑：内容分块、去重、过期标记
`k14/knowledge_graph_updater.py` — 硬编码图关系（非 Neo4j）
`k14/expiration_marker.py` — 过期内容检测

### 核心问题
1. 主文件和子模块功能重复（`_write_chunks` vs `ArtifactVectorizer`）
2. embedding 为全零向量 — 语义检索完全不可用
3. 未集成任何真实 embedding 模型（text-embedding-3-large 等）
4. 知识图谱更新为硬编码字典，未连接 Neo4j

---

## K15 Change Propagation（变更传播）

### 入口文件

`k15_change_propagation.py` — 175 行。launcher 使用。
- 监听 `spec.changed`、`api.changed` 事件
- 30 秒防抖窗口，汇总后发布 `propagation.triggered`
- 使用独立 `EventSubscriber`/`EventPublisher`

### 子模块

`k15/dependency_traverser.py` (198 行) — 硬编码依赖图遍历
`k15/event_debouncer.py` — 事件防抖
`k15/impact_rater.py` (230 行) — 变更影响评级（breaking/major/minor/patch）

### 核心问题
1. 依赖图为硬编码字典（非 Neo4j 实时查询）
2. 防抖为内存实现（进程重启后丢失未触发的事件）
3. 影响评级基于规则匹配，非 ML/历史数据
4. 不通过 Orchestrator dispatch（独立 NATS 订阅模式）

---

## 汇总

| Agent | Launcher 使用 | 完整性 | LLM 集成 | 关键问题 |
|-------|-------------|--------|----------|---------|
| A9 | stub | 完整实现在地上 | **Bridge/子模块调用链断裂** | ClaudeCodeBridge 不继承 BaseAgentWorker |
| A10 | 完整 | Mock | 无 LLM | 全部 mock sleep |
| A11 | stub | 完整 VisAgent 实现在地上 | 完整 | launcher 未切换到完整版 |
| A12 | 完整 | 子模块闲置 | 基础 LLM | security_scanner 等未集成 |
| A13 | 完整 | 子模块闲置 | 无 LLM | 指标为 random 仿真 |
| K14 | 完整 | 主文件与子模块重复 | 无 embedding | 零向量占位 |
| K15 | 完整 | 子模块闲置 | 无 LLM | 硬编码依赖图 |

### 通用系统性问题

1. **A9/A10/A13/K14/K15 使用独立 EventSubscriber**，与 Orchestrator NATS dispatch 模式不一致。
   理想情况下所有 Agent 应通过 `subscribe_nats()` 统一接收 dispatch。

2. **LLM 调用链路断裂**：`ClaudeCodeBridge`、`CoderModule`、`AuditorModule` 都在非
   BaseAgentWorker 子类上调用 `self.call_llm()`。

3. **Stub vs 完整版**：A9 和 A11 都有两套实现，完整版闲置。
