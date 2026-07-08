# A9 Dev Agent — 完整设计规格 (v2.1, 2026-07-06)

## 1. 系统全景

### 1.1 状态机流程（当前 + 改动）

```
当前:
  DRAFT → ANALYZING → Gate 0 → DESIGNING → Gate 1 → REVIEWING →
    DECOMPOSING → Gate 2 → DEVELOPING(A9) → TESTING(A11) →
    REVIEWING_CODE(A12) → Gate 3 → RELEASING(A13) → DONE

  Rework: REVIEWING fail → back to DESIGNING (max 2)

目标 (保持状态机不变，只增强数据流):
  DRAFT → ANALYZING → Gate 0 → DESIGNING(A3/A4) → Gate 1 → REVIEWING(A5)
    ↓
    A5 产出: review_result + decisions_required[]
    ↓
    Gate 1 审批设计 + 可选的架构决策
    ↓
    DECOMPOSING(A6) ← 注入 decisions[]
    ↓
    Gate 2 → DEVELOPING(A9) ← 注入 decisions[]
    ↓
    A9 自主开发 → 自测 → Auditor 审查 →
    ├─ Type 1: ambiguity → 记录到 feedback log，不阻断
    ├─ Type 3: blocking → publish agent.escalated → BLOCKED
    └─ success → code_diff artifact
    ↓
    TESTING(A11) → REVIEWING_CODE(A12) → Gate 3 → RELEASING(A13) → DONE
```

### 1.2 Agent 协作全景

```
┌─────────────────────────────────────────────────────────────────┐
│                       Orchestrator                              │
│                                                                  │
│  A3/A4(设计) → A5(审查+决策识别) → Gate1(决策审批)               │
│       → A6(拆解) → A9(开发) → A11(测试) → A12(代码审查)          │
│       → Gate3 → A13(发布)                                        │
│                                                                  │
│  Agent 间协作:                                                   │
│  ┌──────────┐   NATS pub/sub    ┌──────────┐                   │
│  │    A9    │ ←───────────────→ │    A10   │ (CI Service)       │
│  │ (开发)   │   request-reply   │ (构建)   │                   │
│  └──────────┘                   └──────────┘                   │
│       │                              │                           │
│       │ NATS pub                     │ NATS pub                  │
│       ▼                              ▼                           │
│  ┌──────────┐                   ┌──────────┐                   │
│  │  A11     │ (Orchestrator调度) │  A13     │ (Orchestrator调度)│
│  │ (测试)   │                   │ (发布)   │                   │
│  └──────────┘                   └──────────┘                   │
│                                                                  │
│  A9 不自调 A11/A13 — 由 Orchestrator 状态机驱动                   │
│  A9 可调 A10 (NATS request-reply) — Docker build 验证             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 决策分层

### 2.1 决策在正确的阶段完成

```
Stage        Agent       产出                       谁来决策
────────────────────────────────────────────────────────────
DESIGNING    A3/A4       API设计 + ERD + UI原型     产品/设计师
Gate 1       人工        设计审批 (SLA 4h)           产品负责人
REVIEWING    A5          设计审查 + 架构决策识别      技术负责人
                         ├─ decisions_required[]      (A5 建议，人工定)
                         ├─ scores (UX/API/Biz)
                         └─ issues[]
Gate 1       人工        架构决策审批                 技术负责人
             (如果 A5     (与设计审批同 Gate，可       (可与产品审批
              产出了      逐项决策或批量批准)           合并或分批)
              决策点)
DECOMPOSING  A6          任务拆解 ← 注入 decisions[]  Tech Lead
Gate 2       人工        任务计划审批 (SLA 4h)        Tech Lead
DEVELOPING   A9          代码生成 ← 收到完整 spec     A9 自主
                         + decisions 约束
                         A9 只管:
                         - 实现细节 (自己决定)
                         - 记录 spec 模糊点 (不阻断)
                         - 遇到阻塞升级 (→ BLOCKED)
```

### 2.2 A5 新增输出

```python
A5.review() → {
    "verdict": "approved|approved_with_decisions|rejected",
    "scores": { "ux": 82, "api": 75, "business": 88 },
    "issues": [...],
    "decisions_required": [          # ← 新增
        {
            "id": "arch-d1",
            "question": "缓存方案",
            "options": [
                {"label": "Redis", "implications": "需新增 Redis 实例",
                 "effort": "+3h", "risk": "low"},
                {"label": "PostgreSQL", "implications": "复用已有 PG",
                 "effort": "0h", "risk": "QPS 较低时无影响"},
            ],
            "recommendation": "Redis",
            "recommendation_reason": "预期 QPS > 1000，PG 缓存表无法满足",
            "impact": "medium",
        },
        {
            "id": "arch-d2",
            "question": "API 认证方式",
            "options": [
                {"label": "JWT", "implications": "无状态，适合微服务扩展"},
                {"label": "Session", "implications": "需 sticky session"},
            ],
            "recommendation": "JWT",
            "impact": "high",
        },
    ],
}
```

### 2.3 Gate 1 决策审批流

```
Phase 1: 设计审批 (SLA 4h)
  → 查看 A3 UI 原型 + A4 API/ERD → 审批/打回

Phase 2: 架构决策审批 (A5 审查后，如果有 decisions_required)
  → MC Backend UI 逐项展示:
     ┌──────────────────────────────────────────┐
     │  架构决策 — 需求 #109                     │
     │                                          │
     │  A5 审查通过 (平均分 81.7)                │
     │                                          │
     │  需要决策:                                │
     │  1. 缓存方案                              │
     │     ● Redis (A5 推荐: QPS > 1000)        │
     │     ○ PostgreSQL                         │
     │     [批准推荐] [选择另一个]                 │
     │                                          │
     │  2. API 认证方式                          │
     │     ● JWT (A5 推荐: 微服务友好)           │
     │     ○ Session                            │
     │     [批准推荐] [选择另一个]                 │
     │                                          │
     │  [全部批准A5推荐] [逐项决定]               │
     └──────────────────────────────────────────┘

Phase 3: 决策结果编码到 context
  → MC Backend 发布 agent.decision_result NATS event
  → Workflow Signal: decisions_resolved
  → Workflow 把 decisions[] 注入到 context_str
  → A6 拆解时带上 decisions 约束
  → A9 开发时决不再问"用 Redis 还是 PG"
```

### 2.4 A9 的不确定性处理（修正后）

A9 **不需要** `_request_human_decision()`。只保留两个方法:

```python
class A9DevAgent(BaseAgentWorker):

    def _record_ambiguity(self, req_id: str, amb: dict):
        """
        Type 1: SPEC_AMBIGUITY — spec 写得不够细。
        A9 自行选择一个合理默认值继续执行。
        记录反馈以供 A5/A6 后续改进 spec 质量。
        """
        logger.warning(
            f"[A9] Spec ambiguity: field={amb['field']}, "
            f"chose={amb['chosen']}, reason={amb.get('reason')}"
        )
        # 发布到 NATS → MC Backend → spec_feedback 表 → 定期 review
        asyncio.create_task(self.nc.publish("spec.feedback", json.dumps({
            "req_id": req_id, "agent_id": "A9",
            "type": "ambiguity",
            "field": amb["field"],
            "chosen": amb["chosen"],
            "reason": amb.get("reason", ""),
            "suggested_fix": amb.get("suggested_fix", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })))

    async def _escalate_blocking_issue(self, req_id: str, issues: list[dict]):
        """
        Type 3: BLOCKING_ISSUE — 完全无法继续。
        发布 escalate 事件 → Bridge → Workflow → BLOCKED 状态。
        """
        await self.report_status(req_id, "blocked",
            f"阻塞性问题，需人工介入: {issues[0].get('summary')}")

        await self.nc.publish("agent.escalated", json.dumps({
            "event_id": f"escalate-a9-{req_id}",
            "req_id": req_id,
            "agent_id": "A9",
            "from_state": "developing",
            "reason": "blocking_issue",
            "issues": issues,
            "suggested_reroute": "A6",  # 回到任务拆解阶段
            "context": {"artifacts": self._partial_artifacts},
        }))
```

---

## 3. A9 自测 vs 协作 Agent 边界

### 3.1 明确分工

```
┌─────────────────────────────────────────────────────────┐
│                 A9 内部循环 (快速反馈，分钟级)            │
│                                                          │
│  Claude Code CLI 在 worktree 内:                        │
│    读代码 → 生成代码 → lint → build → unit test         │
│    → [L1 自动修复] → 再跑 → 通过                         │
│                                                          │
│  A9DevAgent 额外验证:                                    │
│    runtime.lint(changed_files, lang)        ← 0.5 min   │
│    runtime.build(lang)                     ← 1 min      │
│    runtime.test(["pytest", "tests/unit/"]) ← 2 min      │
│    runtime.start_service()                 ← 0.5 min    │
│    runtime.test(["pytest", "tests/smoke/"]) ← 1 min     │
│    runtime.stop_service()                                │
│    Auditor.review(diff)                    ← 0.5 min    │
│                                                          │
│  总计: ~5-8 分钟/轮，最多 3 轮 = 15-25 分钟              │
│                                                          │
│  可选 (NATS request-reply):                              │
│    A10.build(dockerfile)                   ← 2-5 min    │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼ A9 完成，发布 agent.result
                          │
┌─────────────────────────────────────────────────────────┐
│          Orchestrator 调度层 (正式验证，分钟-小时级)       │
│                                                          │
│  TESTING (A11):                                          │
│    全量 unit test + integration test + e2e test          │
│    mutation testing (mutmut/Stryker)                     │
│    coverage measurement                                  │
│    [fail? → 回到 DEVELOPING，A9 收到 A11 的失败报告]      │
│                                                          │
│  REVIEWING_CODE (A12):                                   │
│    Semgrep 安全扫描 + CWE 映射                           │
│    跨模块影响分析                                        │
│    LLM 代码审查                                          │
│                                                          │
│  RELEASING (A13):                                        │
│    金丝雀发布 (5%→20%→50%→100%)                          │
│    Prometheus 指标监控                                   │
│    auto-rollback on error                                │
└─────────────────────────────────────────────────────────┘
```

### 3.2 A9 ↔ A10 协作方式

A10 改造为 **NATS request-reply CI Service**（不再是独立 EventSubscriber）:

```python
# A10 新接口 — 运行在 worker_launcher 中，响应 NATS request
class CIBuildService:
    """响应 NATS request-reply 的 CI 构建服务"""

    async def init(self):
        # 订阅 NATS request subject
        await self.nc.subscribe("ci.build", queue="ci-workers")
        # 处理 request — 类似 RPC 调用
        ...

# A9 中调用 A10
async def _verify_docker_build(self, worktree_path: str, req_id: str):
    try:
        reply = await self.nc.request(
            "ci.build",
            json.dumps({
                "req_id": req_id,
                "repo_path": str(worktree_path),
                "dockerfile": "Dockerfile",
                "tag": f"a9-dev-{req_id}",
            }).encode(),
            timeout=180,
        )
        result = json.loads(reply.data.decode())
        return result  # {success, image_id, size_mb, logs[:2000]}
    except asyncio.TimeoutError:
        logger.warning("[A9] CI build timeout — skipping docker verification")
        return {"success": True, "skipped": True, "reason": "timeout"}
    except Exception as e:
        logger.warning(f"[A9] CI service unavailable: {e}")
        return {"success": True, "skipped": True, "reason": str(e)}
```

**A10 调用对 A9 是可选的**。不可用 → 跳过，不影响主流程。

---

## 4. A9 集群运行架构

### 4.1 三层伸缩

```
Layer 1: 服务器级 (NATS Queue Group)
  VM-Dev-1: A9_WORKER_COUNT=3  →  3 个 A9 Worker 进程
  VM-Dev-2: A9_WORKER_COUNT=3  →  3 个 A9 Worker 进程
  NATS subject: context.ready.dev_agent → queue group a9-workers
  自动负载均衡: 轮询分发 message 到各个 Worker
  扩容: 加 VM-Dev-3，启动同样 process，NATS 自动纳入

Layer 2: 进程级 (asyncio.Semaphore)
  每个 A9 Worker: self._semaphore = asyncio.Semaphore(3)
  单进程最多 3 个并发开发任务
  限制: 磁盘 (3 × 500MB worktree) + CPU (3 个 Claude Code CLI)

Layer 3: 任务级 (git worktree)
  每个任务: /data/a9-worktrees/wt-a9rt-{uuid}/
  任务间完全隔离
  任务结束立即 cleanup

并发能力: 2 VM × 3 Worker × 3 Semaphore = 18 任务同时
```

### 4.2 VM-Dev 环境要求

```
必须:
  git 2.x+, Python 3.10+, ANTHROPIC_API_KEY 环境变量

推荐:
  Node.js 18+                ← Claude Code CLI 运行环境
  @anthropic-ai/claude-code  ← npm install -g
  pylint, eslint             ← 代码静态检查
  pytest, jest               ← 单元测试
  Docker 20+                 ← A10 调用 / 项目启动

可选:
  kubectl + kubeconfig       ← K8s dev namespace 部署
  go, rustc, tsc             ← 按团队技术栈

磁盘: 每台 VM-Dev ≥ 50GB
清理: cron: find /data/a9-worktrees -mmin +120 -exec rm -rf {} \;
```

### 4.3 部署清单

```
组件                  位置              配置
─────────────────────────────────────────────────────
Temporal + NATS       VM-Orchestrator   docker-compose.yml (已有)
MC Backend            VM-Orchestrator   已有
worker_launcher       VM-Dev-1,2,...    A9_WORKER_COUNT=3 python worker_launcher.py
A10 CI Service        VM-Dev 或独立     python worker_launcher.py (作为 request-reply service)
A11 测试 Agent        VM-Dev 或独立     docker-compose 启动测试环境
cron cleanup          VM-Dev-1,2,...    find /data/a9-worktrees -mmin +120 -delete
```

---

## 5. 项目启动与部署验证

### 5.1 三层验证策略

```
验证层           方式                    执行者  耗时
────────────────────────────────────────────────────
Lint+Build       pylint/eslint/compileall  A9     < 1 min
Unit Test        pytest/jest (变更相关)    A9     1-2 min
Smoke Test       start_service → /health   A9     1-2 min
  (轻量启动验证)   → curl smoke endpoint
                 → stop_service
Docker Build     A10.build(dockerfile)     A9     2-5 min
  (可选)           NATS request-reply       (可选)
────────────────────────────────────────────────────
Integration Test 全量 integration + e2e    A11    10-30 min
Mutation Test    mutmut/Stryker           A11    10-30 min
Deploy Dev       A13 金丝雀部署            A13    5-30 min
```

### 5.2 A9Runtime.start_service 实现

```python
class A9Runtime:

    async def start_service(self, command: list[str],
                            health_check_url: str = "",
                            timeout: int = 30) -> dict:
        """
        在 worktree 中启动项目进程，等待健康检查通过。
        返回 {"pid": int, "port": int, "url": str}
        """
        import socket
        # 找空闲端口
        sock = socket.socket()
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()

        env = {**os.environ, "PORT": str(port)}
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.worktree_path),
            env=env,
        )
        self._running_services.append(proc)

        # 等待健康检查
        if health_check_url:
            url = f"http://localhost:{port}{health_check_url}"
            for _ in range(timeout):
                await asyncio.sleep(1)
                try:
                    check = await asyncio.create_subprocess_exec(
                        "curl", "-sf", "-o", "/dev/null", url,
                    )
                    if await check.wait() == 0:
                        break
                except Exception:
                    pass

        return {"pid": proc.pid, "port": port, "url": f"http://localhost:{port}"}

    async def stop_all_services(self):
        for proc in self._running_services:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=10)
            except Exception:
                proc.kill()
        self._running_services.clear()
```

### 5.3 Docker Compose 验证（可选增强）

```python
class A9Runtime:

    async def deploy_dev_compose(self, compose_file: str,
                                  project_name: str = "") -> dict:
        """docker-compose up -d --wait，返回 service endpoints"""
        name = project_name or f"a9-dev-{self.session_id}"
        proc = await asyncio.create_subprocess_exec(
            "docker-compose", "-f", compose_file,
            "-p", name, "up", "-d", "--wait",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.worktree_path),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=180,
        )
        # 收集端口映射
        # docker-compose -p <name> port <service> <private_port>
        return {"project": name, "success": proc.returncode == 0}

    async def cleanup_dev_compose(self, project_name: str):
        proc = await asyncio.create_subprocess_exec(
            "docker-compose", "-p", project_name,
            "down", "-v", "--remove-orphans",
            cwd=str(self.worktree_path),
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
```

---

## 6. A9 文件结构

```
repos/agent-workers/a9/
├── __init__.py                # (已有)
├── a9_dev_agent.py            # ★ 重构: 集成 Runtime + Engine + Auditor
├── runtime.py                 # ★ 新增: A9Runtime (worktree/lint/build/test/service)
├── engine.py                  # ★ 新增: A9CodingEngine (Claude Code/Codex/API)
├── coder.py                   # △ 保留降级: prompt 翻译器 + API fallback
├── auditor.py                 # △ 修复: 注入 llm_caller + 增强审查维度
├── static_analyzer.py         # 保留 (已有)
├── metrics.py                 # 保留 (已有)
├── workflow.py                # 保留 (已有, Temporal activities)
└── a9_dev_agent_stub.py       # ✗ 删除
└── a9_claude_code_bridge.py   # ✗ 删除 (功能迁移到 engine.py)
```

---

## 7. A9.execute() 完整流程

```python
async def execute(self, req_id: str, context: dict) -> dict:
    spec = context.get("spec_package", {})
    task = context.get("task", {})
    decisions = context.get("decisions", {})
    repo_url = context.get("repo_url", "")
    branch = context.get("branch", "main")

    runtime = A9Runtime()
    engine = A9CodingEngine(runtime, llm_caller=self.call_llm)

    task_prompt = self._build_task_prompt(spec, task, decisions)
    feedback = ""  # 每一轮迭代的反馈

    final_result = None
    final_audit = None

    for iteration in range(1, self.max_iterations + 1):
        await self.report_status(req_id, "running",
            f"Iteration {iteration}/{self.max_iterations}: 编码中")

        # ── 1. 引擎编码 ──
        result = await engine.execute(
            task_prompt, feedback=feedback,
            language=self._detect_language(task),
            max_turns=50,
        )

        # Type 3: 阻塞性错误
        if not result.success and result.blocking_issues:
            await self._escalate_blocking_issue(req_id, result.blocking_issues)
            await runtime.cleanup()
            return {"status": "blocked", "issues": result.blocking_issues}

        if not result.success:
            feedback = f"执行失败: {result.summary}"
            continue

        # Type 1: 记录模糊点
        for amb in result.ambiguities or []:
            self._record_ambiguity(req_id, amb)

        # ── 2. 静态检查 ──
        await self.report_status(req_id, "running", "自测: lint + build")
        files = [f["path"] for f in result.files_changed]
        lang = self._detect_language(result.files_changed)

        lint = await runtime.lint(files, lang)
        if lint.status == "error":
            feedback = self._format_feedback(lint, None, None)
            continue

        build = await runtime.build(lang)
        if not build.success:
            feedback = self._format_feedback(lint, build, None)
            continue

        # ── 3. 单元测试 ──
        await self.report_status(req_id, "running",
            f"自测: unit test ({len(files)} 文件)")
        tests = await runtime.test()
        if tests.failed > 0:
            feedback = self._format_feedback(lint, build, tests)
            continue

        # ── 4. Smoke test ──
        await self.report_status(req_id, "running", "自测: smoke test")
        try:
            service = await runtime.start_service(
                command=self._detect_start_command(lang),
                health_check="/health", timeout=15,
            )
            smoke = await runtime.test(
                command=["pytest", "tests/smoke/", "-x",
                         f"--base-url={service['url']}"])
            await runtime.stop_all_services()
            if smoke.failed > 0:
                feedback = f"Smoke test 失败 ({smoke.failed}/{smoke.total})"
                continue
        except Exception as e:
            logger.warning(f"[A9] Smoke test skipped: {e}")

        # ── 5. Docker build (可选) ──
        await self.report_status(req_id, "running", "自测: CI build 验证")
        docker_ok = await self._verify_ci_build(runtime.worktree_path, req_id)
        if not docker_ok:
            feedback = "Docker build 失败，请检查 Dockerfile"
            continue

        # ── 6. Auditor 审查 ──
        await self.report_status(req_id, "running", "代码审查中")
        audit = await self.auditor.review({
            "files_changed": result.files_changed,
            "changes_summary": result.summary,
            "lint_result": lint,
            "test_result": tests,
        })

        final_result = result
        final_audit = audit

        if audit["decision"] == "approved":
            await self.report_status(req_id, "running",
                f"审查通过 (迭代 {iteration})")
            break

        feedback = self._format_audit_feedback(audit)

    # ── 7. 清理 ──
    await runtime.cleanup()

    # ── 8. 返回 ──
    status = "completed" if final_audit and final_audit["decision"] == "approved" \
             else "escalated"

    return {
        "status": status,
        "code_diff": final_result.diff_raw if final_result else "",
        "files_changed": final_result.files_changed if final_result else [],
        "self_test": {"lint": lint, "build": build, "tests": tests},
        "audit": final_audit,
        "iterations": iteration,
        "engine": final_result.engine if final_result else "none",
        "ambiguities": self._collected_ambiguities,
    }
```

---

## 8. 实现计划

### Phase 1: 基础层 (P0)
1. `a9/runtime.py` — A9Runtime (worktree/lint/build/test/start_service/cleanup)
2. 修复 LLM 注入: CoderModule/AuditorModule 接受 `llm_caller` 参数
3. 删除 `a9_dev_agent_stub.py` + `a9_claude_code_bridge.py`

### Phase 2: 引擎层 (P0)
4. `a9/engine.py` — A9CodingEngine (Claude Code CLI/Codex CLI/Anthropic API)
5. 改造 `a9/a9_dev_agent.py` — 集成 Runtime + Engine + Auditor + 完整 execute()

### Phase 3: 协作层 (P1)
6. 改造 `worker_launcher.py` — 多实例并发 (A9_WORKER_COUNT + Semaphore)
7. 改造 A10 为 NATS request-reply CI Service
8. A5 新增 `decisions_required` 输出

### Phase 4: 监控与运维 (P1)
9. `spec.feedback` NATS subject + MC Backend 存储
10. `agent.escalated` → Workflow BLOCKED 状态处理
11. Prometheus 指标: a9_active_tasks, a9_cycle_time
12. 磁盘清理 cron

### Phase 5: IDE 辅助模式 (P2)
13. A9ReviewAgent — assisted mode (人类编码 → A9 审查 → 反馈)
14. IDE 内联反馈 (NATS → MC Backend SSE → IDE 插件)

---

## 9. A9 不确定性处理速查

| 场景 | 类型 | A9 行为 | 后果 |
|---|---|---|---|
| Spec 字段未定义 | Type 1: ambiguity | 选默认值 + 记录 `spec.feedback` | 不阻断，后续改进 spec |
| 第三方库版本选择 | 实现细节 | A9 自行决定 | 不需要人工 |
| 错误处理策略 | 实现细节 | A9 自行决定 | 不需要人工 |
| 依赖包不存在 | Type 3: blocking | escalate → BLOCKED | 回到 A6 重新拆解 |
| Dockerfile 有安全漏洞 | Auditor 发现 | reject → 反馈修复 | 迭代循环内解决 |
| 测试基础设施缺失 | Type 3: blocking | escalate → BLOCKED | 需要基础设施团队 |
| Git clone 失败 | Type 3: blocking | escalate → BLOCKED | 需要检查 repo 权限 |

---

## 10. 审计发现与修复方案 (2026-07-06)

以下为对 v2.0 spec 的 critical audit 结果，按严重度排序。

---

### 🔴 Audit-01: Gate 1 decisions → A9 context 数据通路缺失

**严重度**: P0 — 致命

**现状**: `context_build.py` 的 `build_context()` 在 `state=="developing"` 时构建 A9 的 context，当前从 `spec.artifacts` JSONB 列读取 A4/A6 的 artifact hint (L379-389)，但**没有任何代码读取 Gate 1 审批后的 decisions**。

Decisions 存储在 MC Backend 的 `gate_approvals` 表中 (`decision_data` JSONB 列)，与 `spec.artifacts` 是两个独立的存储路径。如果不在 `build_context` 中显式查询，A9 收到的 `context` dict 里不会有 `decisions` 字段。

**影响**: 设计规格第 2.2 节承诺的 "A9 开发时决不再问'用 Redis 还是 PG'" 无法实现。A9 收不到架构决策，遇到设计级歧义时会退化成随机选择。

**修复方案**:

1. MC Backend `gate_approvals` 表结构确认 (需验证):
   ```sql
   -- 预期结构 (Gate 1 审批后写入)
   INSERT INTO gate_approvals (req_id, gate_level, approver, decision, decision_data, created_at)
   VALUES ($1, 1, $2, 'approved', $3::jsonb, NOW());
   -- decision_data = {"decisions": {"arch-d1": "Redis", "arch-d2": "JWT"}, "review_id": "..."}
   ```

2. `context_build.py` 修改 — `build_context()` 中增加第 6 层: decisions context:
   ```python
   # After line 359 (rework context), insert:
   
   # 6. Decisions context (Gate resolutions from prior stages)
   decisions_context = await _extract_decisions_context(req_id, state, conn)
   
   # In the assembled context dict (after line 374), add:
   "decisions_context": decisions_context,
   
   # Backward-compatible key for A9:
   "decisions": decisions_context.get("resolved", {}),
   ```

3. 新增辅助函数:
   ```python
   async def _extract_decisions_context(req_id: str, state: str, conn) -> dict:
       """读取已审批的 Gate 决策。
       
       对于 DEVELOPING 阶段，读取 Gate 1 的架构决策。
       对于 TESTING 阶段，可能还需要读 Gate 2 的调度决策。
       """
       if state not in ("developing", "testing", "reviewing_code", "releasing"):
           return {}
       
       gates_to_read = {
           "developing": [1],          # Gate 1 的架构决策
           "testing": [1, 2],          # Gate 1 + Gate 2
       }.get(state, [1])
       
       rows = await conn.fetch(
           """SELECT gate_level, decision, decision_data
              FROM gate_approvals
              WHERE req_id = $1::uuid AND gate_level = ANY($2::int[])
              ORDER BY gate_level""",
           req_id, gates_to_read,
       )
       
       resolved = {}
       for row in rows:
           data = _parse_json(row["decision_data"])
           if data and "decisions" in data:
               resolved.update(data["decisions"])
       
       return {"resolved": resolved, "source_gates": [r["gate_level"] for r in rows]}
   ```

4. A9 侧无需改动 — `context.get("decisions", {})` 已经按新 spec 编写。

**验证方式**: 端到端测试 — 从 Gate 1 审批 decisions → A6 拆解 → Gate 2 → A9 收到 context，检查 `context.decisions` 包含正确的决策值。

---

### 🔴 Audit-02: A9 escalation → Workflow BLOCKED 路径缺失

**严重度**: P0 — 致命

**现状**: `requirement_workflow.py` 定义了 7 种 Signal (L412-465): `agent_completed`, `agent_status`, `approve_gate`, `reject_gate`, `gate_timeout`, `pause`, `resume`。**没有 `agent_escalated` 或等效的异常终止 Signal**。

当 A9 发布 `agent.escalated` NATS 消息时:
- NATS-Temporal Bridge 收到消息 → 尝试调用 `workflow.signal('agent_escalated', ...)` → Workflow 没有这个 Signal → Bridge 报错/忽略
- Workflow 继续在 `_dispatch_and_wait` 中等待 `self._agent_result is not None` → 等 4 小时超时 → 标记 timeout 后才继续
- A9 侧已经释放了 worktree 和 semaphore 资源，但 Orchrstrator 不知道

**影响**: escalation 消息被丢弃。A9 认为已经升级，但 Workflow 在空等 4 小时。这是完整的信令断裂。

**修复方案** — 选择方案 B (简单，不改 Signal 接口):

在 `_dispatch_and_wait` 中，`agent.result` 的处理已经存在。A9 返回 `{"status": "blocked"}` 作为正常的 agent result，Workflow 通过检查 result status 判断是否进入 BLOCKED:

```python
# requirement_workflow.py — _compute_next_state() 修改

def _compute_next_state(self, req_id: str, current: RS) -> RS:
    # NEW: 检查 agent result 是否要求 block
    if self._agent_result:
        agent_status = self._agent_result.get("status", "")
        if agent_status in ("blocked", "escalated"):
            workflow.logger.warning(
                "Agent %s requested block: %s",
                self._agent_id_expected,
                self._agent_result.get("reason", "unknown"),
            )
            return RS.BLOCKED
    
    # ... 其余逻辑不变
```

同时，在 `_dispatch_and_wait` 的超时分支后 (L283-284)，增加: 如果 `self._agent_result.get("status") == "blocked"`，不增加 `agent_failures` 计数（这不是 timeout 或错误，是合法升级）。

A9 侧保持不变 — `execute()` 中 `return {"status": "blocked", ...}` 已经写好了。

**验证方式**: 单元测试 — Mock A9 返回 `{"status": "blocked"}` → Workflow 应转换到 BLOCKED，不等待 timeout。

---

### 🟡 Audit-03: Claude Code CLI 非交互模式假设未验证

**严重度**: P1 — 严重

**现状**: `engine.py` 的设计依赖于以下 CLI flag:
- `--print` — headless 单次执行模式
- `--output-format stream-json` — 逐行 JSON 输出
- `--max-turns` — 限制 tool use 轮数

这些 flag 的名称和语义基于对 Claude Code CLI 的合理推断，但在公开文档中找不到直接验证。存在的实际风险:

**(a) Flag 名称差异**: 实际可能是 `--prompt` 而非 `--print`，或 `--output json` 而非 `--output-format stream-json`。

**(b) 输出结构未知**: `stream-json` 的 event type 名称 (`tool_use`, `assistant_message`, `result`) 是根据 Anthropic API 推断的，实际可能不同。`total_cost_usd` 字段的存在性也未确认。

**(c) 错误行为**: `--max-turns 50` 到达上限后的 fallback — 是优雅退出 (exit 0) 还是抛异常 (exit 1)？输出中如何体现 "未完成" 状态？

**(d) Windows 兼容性**: 当前宿主机是 Windows，Claude Code CLI 的 Windows 支持 (winget/npm) 与 `subprocess` 调用的兼容性。

**修复方案**:

1. Phase 2 开始前，先做 CLI 探测:

   ```python
   # a9/engine.py — 初始化时自检
   class A9CodingEngine:
       def __init__(self, runtime, llm_caller=None):
           self._claude_cli_config = self._probe_claude_cli()
           self._available = self._detect_available()
       
       def _probe_claude_cli(self) -> dict | None:
           """探测 Claude Code CLI 的可用性和 flag 名称。"""
           import shutil
           claude_path = shutil.which("claude")
           if not claude_path:
               return None
           
           # 尝试 claude --help 获取可用 flag
           import subprocess
           try:
               result = subprocess.run(
                   [claude_path, "--help"],
                   capture_output=True, text=True, timeout=10,
               )
               help_text = result.stdout + result.stderr
               
               # 探测 flag 名称
               has_print = "--print" in help_text or "--prompt" in help_text
               has_output = "--output" in help_text or "--output-format" in help_text
               
               if has_print and has_output:
                   return {
                       "path": claude_path,
                       "print_flag": "--print" if "--print" in help_text else "--prompt",
                       "output_flag": "--output-format" if "--output-format" in help_text else "--output",
                       "version": help_text.split("\n")[0],
                   }
               return None
           except Exception as e:
               logger.warning(f"Claude Code CLI probe failed: {e}")
               return None
   ```

2. 如果 CLI 不可用，自动降级:

   ```
   engine._available = ["claude-code", "anthropic-api"]  # 理想
   engine._available = ["anthropic-api"]                   # 探测失败后的实际
   ```

   此时 engine 使用 Anthropic Python SDK 的 tool use 模式做自主编码循环:
   
   ```python
   async def _run_anthropic_sdk_agent(self, task: str) -> EngineResult:
       """
       Fallback: 用 Anthropic SDK 的 tool use 模拟 Claude Code CLI。
       tools = [read_file, write_file, run_command, ...]
       while not done and turns < max_turns:
           response = anthropic.messages.create(
               model="claude-sonnet-4-20250514",
               messages=[...],
               tools=[read_file, write_file, run_command],
           )
           if response.stop_reason == "tool_use":
               execute_tool(response.content)
               continue
           else:
               done = True
       """
   ```

3. Phase 2 实现 `engine.py` 时: 先实现 `_probe_claude_cli()`，再实现 `_run_claude_code()`，确保分支覆盖 CLI 可用和不可用两种情况。

**验证方式**: 在任意有 Claude Code CLI 的环境中运行 `claude --help`，检查输出是否包含预期 flag。

---

### 🟡 Audit-04: DEVELOPING ↔ TESTING 内循环缺失

**严重度**: P1 — 严重

**现状**: `guards.py:64` 定义 `DEVELOPING` 和 `TESTING` 为 `"inner"` loop（max 2 轮），`transitions.py:13` 允许 `DEVELOPING → TESTING` 和 `DEVELOPING → BLOCKED`。但 `_compute_next_state()` (L542) 中只有 `REVIEWING → DESIGNING` 的 rework 逻辑。

当前 `DEVELOPING → TESTING → REVIEWING_CODE` 是单向的——A11 测试失败后没有路径回到 A9。

**影响**: 内循环名存实亡。A11 发现测试失败 → 直接进入 REVIEWING_CODE → A12 审查未通过的代码 → Gate 3 才暴露问题，而不是在 DEVELOPING/TESTING 阶段快速修复。违反快速反馈原则。

**修复方案**:

1. 在 `_compute_next_state()` 中增加 TESTING 的 rework 分支:

   ```python
   def _compute_next_state(self, req_id: str, current: RS) -> RS:
       # REVIEWING -> check A5 result for rework (existing)
       if current == RS.REVIEWING:
           # ... 现有逻辑不变
       
       # NEW: TESTING -> check A11 result, possible rework to DEVELOPING
       if current == RS.TESTING:
           a11_pass = self._agent_result.get("pass", False) if self._agent_result else False
           a11_score = self._agent_result.get("coverage_pct", 0) if self._agent_result else 0
           
           if not a11_pass:
               # 测试失败 → 回到 A9 带着失败报告
               self._inner_loop_count += 1
               if self._inner_loop_count <= 2:
                   workflow.logger.info(
                       "Inner loop #%d: TESTING -> DEVELOPING (rework)",
                       self._inner_loop_count,
                   )
                   # 保留 A11 的测试失败结果作为 rework feedback
                   self._last_test_result = self._agent_result
                   return RS.DEVELOPING
               else:
                   workflow.logger.warning(
                       "Inner loop exhausted: TESTING failures after %d rounds",
                       self._inner_loop_count - 1,
                   )
                   # 继续到 REVIEWING_CODE — A12 会在审查中发现残留问题
           
           # 重置 inner loop counter on pass
           self._inner_loop_count = 0
           return RS.REVIEWING_CODE
       
       # ... 其余线性映射不变
   ```

2. 在 `_run_agent_stage()` 的 context 注入中追加 A11 的测试失败报告:

   ```python
   if state == RS.DEVELOPING and self._last_test_result:
       # 这是 inner loop 的 rework — 注入 A11 测试失败信息
       context_str = context_str + "\n[TEST_FAILURE_FEEDBACK]\n" + json.dumps({
           "failed_tests": self._last_test_result.get("failed_tests", []),
           "coverage_pct": self._last_test_result.get("coverage_pct", 0),
           "error_messages": self._last_test_result.get("errors", [])[:10],
       }, ensure_ascii=False)
       self._last_test_result = None
   ```

3. Workflow `__init__` 新增状态变量:

   ```python
   def __init__(self) -> None:
       # ... 现有变量
       self._inner_loop_count: int = 0  # ← 新增
       self._last_test_result: dict | None = None  # ← 新增
   ```

**验证方式**: 模拟 A11 返回 `{"pass": false}` → Workflow 应回到 DEVELOPING；第二次再返回 false → 进入 REVIEWING_CODE。

---

### 🟡 Audit-05: AuditorModule 未接收 llm_caller + 子进程并发

**严重度**: P1 — 严重

**现状**:

1. `auditor.py:30` — `AuditorModule.__init__(self, enable_analysis: bool = True)` — **没有 `llm_caller` 参数**。spec 第 2 节承诺的 "LLM 用于语义审查(安全漏洞、业务逻辑)" 无法实现。

2. `auditor.py:187-188` — 每个 `_run_pylint` 调用启动独立子进程，Semaphore=3 时 3 个并发任务的 Auditor 同时跑 pylint，但没有子进程并发限制。pylint 本身也消耗不少 CPU/内存。

3. `coder.py:34` — `CoderModule.__init__(self, work_base=..., enable_llm=True)` — 同样没有 `llm_caller` 参数。虽然 spec 将 CoderModule 降级为 fallback，但仍需要 LLM 能力。

**修复方案**:

1. AuditorModule 签名改造:

   ```python
   class AuditorModule:
       def __init__(self, llm_caller=None, enable_analysis: bool = True,
                    max_parallel_tools: int = 2):
           """
           Args:
               llm_caller: Callable for LLM semantic review.
                           Inject from A9DevAgent.call_llm.
               enable_analysis: Whether to run pylint/eslint subprocess.
               max_parallel_tools: Max concurrent pylint/eslint instances.
           """
           self._llm_caller = llm_caller
           self.enable_analysis = enable_analysis
           self._tool_semaphore = asyncio.Semaphore(max_parallel_tools)
   
       async def review(self, diff: dict) -> dict:
           # Parallel: static analysis + LLM semantic review
           static_task = asyncio.create_task(self._analyze_files(
               diff.get("files_changed", [])))
           
           semantic_task = None
           if self._llm_caller:
               semantic_task = asyncio.create_task(
                   self._semantic_review(diff))
           
           static_results = await static_task
           semantic_issues = await semantic_task if semantic_task else []
           
           # Merge both into final decision
           return self._make_decision_with_semantics(
               static_results, semantic_issues)
       
       async def _semantic_review(self, diff: dict) -> list[dict]:
           """LLM 驱动的语义审查: 安全漏洞、业务逻辑、设计模式"""
           prompt = self._build_semantic_prompt(diff)
           content = await self._llm_caller(
               [{"role": "user", "content": prompt}],
               task_type="code_audit",
               temperature=0.1,
               max_tokens=2000,
           )
           return self._parse_semantic_issues(content)
   ```

2. 子进程并发控制:

   ```python
   async def _run_pylint(self, path: str, patch: str) -> list:
       async with self._tool_semaphore:  # ← 限制并发 pytlint 实例
           # ... 现有 subprocess 逻辑
   ```

3. CoderModule 签名改造 (同步的，不需要 Auditor 的完整重写):

   ```python
   class CoderModule:
       def __init__(self, llm_caller=None, work_base: str = "/tmp/a9-worktrees",
                    enable_llm: bool = True):
           self._llm_caller = llm_caller
           self.work_base = work_base
           self.enable_llm = enable_llm
           # ... 其余不变
   ```

4. A9DevAgent 注入时:

   ```python
   class A9DevAgent(BaseAgentWorker):
       def __init__(self, ...):
           super().__init__(...)
           self.coder = CoderModule(llm_caller=self.call_llm)
           self.auditor = AuditorModule(llm_caller=self.call_llm)
   ```

**验证方式**: 单元测试 — 传入 mock `llm_caller`，验证 Auditor 同时产出静态分析结果和 LLM 语义审查结果。

---

### 🟢 Audit-06: A9Runtime.start_service 网络绑定安全

**严重度**: P2 — 轻微

**现状**: spec 第 5.2 节的 `start_service` 示例代码中使用 `--host 0.0.0.0 --port {port}`。如果 VM-Dev 有外部可达网卡，worktree 中的待审代码会暴露在网络上。

**影响**: 低概率但高风险。smoke test 期间，worktree 代码可能包含未审查的 SQL 注入、硬编码密钥等。

**修复方案**:

```python
# runtime.py — start_service 修改
async def start_service(self, command: list[str],
                        health_check_url: str = "",
                        timeout: int = 30,
                        bind_host: str = "127.0.0.1") -> dict:
    """
    启动项目进程进行 smoke test。
    默认绑定 localhost — worktree 代码不应暴露在网络上。
    """
    import socket
    sock = socket.socket()
    sock.bind((bind_host, 0))  # ← 写死 localhost
    port = sock.getsockname()[1]
    sock.close()

    # 把 BIND_HOST 传给子进程
    env = {
        **os.environ,
        "PORT": str(port),
        "BIND_HOST": bind_host,
    }
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(self.worktree_path),
        env=env,
    )
    # ... 健康检查用 localhost:{port}
```

如果 e2e 测试确实需要外部可达 (如 Selenium 浏览器测试)，使用 Docker Compose 方案 (第 5.3 节) 做网络隔离，而非直接暴露宿主机端口。

---

### 🟢 Audit-07: A10 request-reply 架构与 BaseAgentWorker 冲突

**严重度**: P2 — 轻微

**现状**: `CICDAgent` 继承 `BaseAgentWorker`，通过 `subscribe_nats()` 订阅 pub-sub 通道（独立监听 `code.pushed` 事件）。A9 的 `_verify_ci_build()` 设计通过 `self.nc.request("ci.build", ...)` 调用，这是 **request-reply** 模式，与 pub-sub 完全不同。

同一个 `CICDAgent` 实例不能同时充当 pub-sub 的持久订阅者和 request-reply 的响应者——两个模式的 NATS subscription 生命周期不同。

**修复方案** — 选择方案 (a): A10 拆分为独立服务：

```
repos/agent-workers/
├── ci_agent.py              # 保留: pub-sub CICDAgent (监听 code.pushed)
├── ci_build_service.py      # ★ 新增: NATS request-reply service
```

`ci_build_service.py`:

```python
"""
CI Build Service — NATS request-reply handler.

不继承 BaseAgentWorker。不是 Agent — 是工具服务。
"""

import asyncio
import json
import logging
import nats

logger = logging.getLogger(__name__)

class CIBuildService:
    """Responds to ci.build NATS requests with Docker build results."""

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self.nats_url = nats_url
        self.nc = None

    async def init(self):
        self.nc = await nats.connect(self.nats_url)
        # NATS request-reply: subscribe to subject, auto-reply
        await self.nc.subscribe("ci.build", cb=self._handle_build_request)
        logger.info("[CIBuildService] Listening on ci.build (request-reply)")

    async def _handle_build_request(self, msg):
        try:
            data = json.loads(msg.data.decode())
            req_id = data.get("req_id", "unknown")
            repo_path = data.get("repo_path", "")
            dockerfile = data.get("dockerfile", "Dockerfile")
            tag = data.get("tag", f"build-{req_id}")

            logger.info(f"[CIBuildService] Build request: {tag}")

            # Docker build
            proc = await asyncio.create_subprocess_exec(
                "docker", "build", "-t", tag, "-f", dockerfile, repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=180,
            )

            result = {
                "success": proc.returncode == 0,
                "image_tag": tag,
                "logs": (stderr.decode()[:2000] if stderr else ""),
                "exit_code": proc.returncode,
            }
            await self.nc.publish(msg.reply, json.dumps(result).encode())

        except asyncio.TimeoutError:
            await self.nc.publish(msg.reply, json.dumps({
                "success": False, "error": "Build timeout (3 min)"
            }).encode())
        except Exception as e:
            logger.error(f"[CIBuildService] Build failed: {e}")
            await self.nc.publish(msg.reply, json.dumps({
                "success": False, "error": str(e)
            }).encode())

    async def close(self):
        if self.nc:
            await self.nc.close()
```

`worker_launcher.py` 中注册:

```python
# worker_launcher.py
# ...
from ci_build_service import CIBuildService  # ← 新增

async def main():
    # ... 现有 agents 注册 ...
    agents = register_agents()
    
    # Start CI Build Service (not an Agent — a request-reply service)
    ci_build = CIBuildService()
    await ci_build.init()
    
    # ... 其余不变
    
    finally:
        await ci_build.close()
        # ... 现有清理
```

A9 侧调用不变 (`self.nc.request("ci.build", ...)` ).

**验证方式**: 单元测试 — 向 `ci.build` 发送 request，验证收到 reply 且 Docker build 正常执行。

---

## 12. 跨文档审计：与 jap-plus-absorption-plan + orchestrator-completion-spec 对照 (2026-07-06)

以下是对照 `doc/specs/orchestrator-completion-spec.md`（Phase 0 当前实施 Spec）和 `doc/specs/jap-plus-absorption-plan.md`（Phase 2-4 远景三层架构蓝图）后的完整发现。

### 12.1 冲突项 (本 spec 需要修正的)

#### C1: A4 数据通路 gap — 已补充到 orchestrator-completion-spec T7

**来源**: `orchestrator-completion-spec.md` L32 + L119 — A4 在 `_AGENTS_THAT_PERSIST` skip set 中

**状态**: ✅ 已解决。`orchestrator-completion-spec.md` v1.1 新增 **T7: A4 Artifact 数据通路修复** (L1015-1063)。

T7 方案: `context_build._extract_artifact_context()` 对 A4 特殊处理，从 `spec.openapi`/`spec.erd` 根键读取并归一化注入 `artifact_context.A4`，向后兼容 `openapi_hint`/`erd_hint`。

本 spec 标注为: **取决于 orchestrator-completion-spec T4/T5/T7 完成**。

#### C2: A8 架构审查不在 developing 上游 — Phase 0 的设计决策，需要替代路径

**来源**: `orchestrator-completion-spec.md` L52-58 的 `_STATE_UPSTREAM`

**现状**: `developing` 上游 = `["A1", "A4", "A5", "A6", "A7"]`。A8 (architecture_review: 循环依赖检测、分层违规、DB 回滚风险) **不在任何状态的 artifact 上游中**。A8 不是漏了——Phase 0 规划没有把 A8 列入状态机主链路的 artifact consumer。

**但 A8 的审查内容对 A9 非常重要**: 循环依赖检测结果、分层违规告警、Gate 2 pass/fail 判定——这些都是 A9 编码时的硬约束。

**修正 (本 spec)**: 两种方案:
1. **方案 A**: 把 A8 加入 `_STATE_UPSTREAM["developing"]` — 简单但需要改 Phase 0 spec
2. **方案 B**: A8 的约束通过 A6 的 DAG 传递 — A6 在拆解任务时引用 A8 的约束，DAG node 的 `constraints` 字段携带 "此模块禁止循环依赖" 等信息

**本 spec 选择方案 B** — 不改 Phase 0 的 `_STATE_UPSTREAM`:
```python
# A6 SpecDecomposer 在构建 DAG node 时注入架构约束:
dag_node = {
    "id": "task-3",
    "title": "实现用户认证中间件",
    "constraints": [
        "禁止与 data 层循环依赖 (A8 检测到 auth↔data 风险)",
        "必须使用 JWT RS256 (Gate 1 决策 arch-d2)",
    ],
    ...
}
```
A9 从 `dag_hint` 的 node.constraints 中获取架构约束，不需要直接读 A8 产物。

#### C3: engine.py 不应重复做 context assembly — 统一使用 prepare_llm_context()

**来源**: `orchestrator-completion-spec.md` T4 — `ContextCompressionService`

**现状**: Phase 0 在 `BaseAgentWorker.prepare_llm_context()` 中实现了完整的分层压缩管道 (head/mid/tail + 去重 + 结构化提取 + 预算检查)。A9DevAgent 调用 `self.prepare_llm_context(context, state="developing")` 后拿到的是**已压缩的文本**。

但本 spec 的 `_build_task_prompt(spec, task, decisions)` 方法是基于原始 dict 重新拼接 prompt——绕过了压缩管道，相当于做了两次 assembly。

**修正 (本 spec)**: `_build_task_prompt()` 不应重新提取 spec_package，而是:
```python
def _build_task_prompt(self, context: dict, compressed_text: str, decisions: dict) -> str:
    """用压缩后的文本作为 engine 的上下文，只追加 decisions 约束。"""
    parts = [compressed_text]  # ← 来自 prepare_llm_context() 的产物
    if decisions:
        parts.append(f"\n[架构决策 - 必须遵守]\n{json.dumps(decisions, ensure_ascii=False)}")
    return "\n\n".join(parts)
```

A9Runtime 不需要再做 context assembly——那是 context_build + ContextCompressionService 的职责。A9 只负责追加 engine 自己需要的运行时信息 (decisions, feedback)。

#### C4: MCP 调用模式 — Phase 0 push vs Phase 3 pull 需明确阶段

**来源**: `jap-plus-absorption-plan.md` — `BaseAgentWorker.mcp_call()` design

**现状**: jap-plus 的设计是 Phase 3 Agent 主动调 MCP tools (`self.mcp_call("knowledge-base-mcp", "search_knowledge", ...)`)——即 "pull" 模式。但 Phase 0 的 T4 是 `build_context` 在 dispatch 前**预先注入**知识库结果——即 "push" 模式。

本 spec 当前描述混合模式——context 中收到压缩的知识库结果，同时 engine 在运行时也可能需要查知识库。这个混合没有明确边界。

**修正 (本 spec)**: 分两阶段描述:
- **Phase 0-2 (push)**: A9 的知识需求全部通过 `context_package` 中的 `knowledge_context` 满足。Engine 不主动查知识库。如果 knowledge_context 不够，在 `spec.feedback` 中标记缺失项
- **Phase 3+ (pull)**: Engine 通过 MCPClient 按需查询。实现 `lazy_load_enabled`。此时 engine 可以:
  ```python
  # engine.py Phase 3 扩展
  result = await self.mcp_call("knowledge-base-mcp", "search_knowledge",
      {"query": "SQLAlchemy async session best practices", "top_k": 3})
  ```

---

### 12.2 遗漏项 (本 spec 之前未覆盖的)

#### G1: Gate decisions 的持久化路径 — 已补充到 orchestrator-completion-spec T6

**来源**: 原 `orchestrator-completion-spec.md` — 全文无 decisions 相关设计

**状态**: ✅ 已解决。`orchestrator-completion-spec.md` v1.1 新增 **T6: Gate Decisions 持久化 + Context 注入** (L960-1013)。

T6 方案:
1. MC Backend `PUT /api/requirements/{req_id}/decisions` — Gate 审批通过时写入 `spec.decisions` JSONB 根键
2. `context_build.py` 新增 `_extract_decisions_context()` — 读取 `spec.decisions` 注入到 `decisions_context`
3. `build_context("developing")` 的 decisions 预算: 300 tokens
4. A9 消费: `context.get("decisions", {})` — 本 spec 已写好

#### G2: A9 的独立 Skills 文件内容尚未定义

**来源**: `jap-plus-absorption-plan.md` L101, L248

**现状**: jap-plus 规定 A9 有 3 个 `.skill.md`:
- `dev-guidelines.skill.md` — 开发规范
- `tdd-rules.skill.md` — TDD 规则
- `dual-brain.skill.md` — 双脑架构

但内容完全未定义，文件完全不存在。

**补充 (本 spec)**: 为 A9 定义 3 个 skill 的内容概要:

```markdown
# .ai-native/agents/A9/skills/dev-guidelines.skill.md
---
skill_id: a9-dev-guidelines-v1
applies_to: "A9"
version: 1.0
ttl_seconds: 3600
---

# A9 开发规范

## 通用编码规则
- 所有函数必须有类型注解 (Python 3.10+ syntax)
- 数据库操作必须使用 async session，禁止同步调用
- 异常必须区分业务异常 (BusinessError) 和系统异常 (SystemError)
- 所有 public API 必须有 docstring (Google style)

## 项目结构
- 路由 → src/routes/{resource}.py
- 模型 → src/models/{resource}.py
- 服务 → src/services/{resource}.py
- 测试 → tests/{unit|integration|e2e}/test_{resource}.py

## 依赖管理
- 优先使用项目已有的依赖，禁止随意引入新包
- 如需新增依赖，在代码注释中标注理由
```

```markdown
# .ai-native/agents/A9/skills/tdd-rules.skill.md
---
skill_id: a9-tdd-rules-v1
applies_to: "A9"
version: 1.0
ttl_seconds: 3600
---

# A9 TDD 规则

## 测试优先级
1. 先写 test（基于 A7 的 test_outline）
2. 再写实现 → 跑 test → 通过
3. 重构 → 跑 test → 仍然通过

## 质量门槛 (A9 内部自测)
- lint: pylint score >= 8.0
- build: compileall / tsc 通过
- unit test: 覆盖率 >= 80% (仅变更文件的增量覆盖率)
- smoke test: /health 返回 200

## 失败处理
- lint 失败 → Claude Code CLI 自动修复 (max 3 iter)
- unit test 失败 → 反馈 engine 修复 (max 3 iter)
- smoke test 失败 → 反馈 engine 修复 (max 2 iter)
- 最终失败 → escalate BLOCKED
```

```markdown
# .ai-native/agents/A9/skills/dual-brain.skill.md
---
skill_id: a9-dual-brain-v1
applies_to: "A9"
version: 1.0
ttl_seconds: 3600
---

# A9 双脑架构规则

## Coder (CodingEngine)
- 收到 task_spec + context → 生成代码
- 在 worktree 内自主工作: 读代码 → 写代码 → 跑 lint → 跑 test → 修错
- 不能看到 Auditor 的审查结果（在审查前）

## Auditor (AuditorModule)
- 只能看到 diff (files_changed + changes_summary)
- 不能看到 Coder 的 self_inspection / 内部推理
- 审查维度: 语法(pylint) + 语义(LLM 安全/业务/性能) + 规范(命名/类型/异常)

## 反馈循环
- Auditor approved → 产出 code_diff artifact
- Auditor rejected → feedback 注入下一轮 Coder 的 task prompt
- Max 3 轮 → 最终 rejected → escalate BLOCKED
```

这些 skill 文件在 Phase 2 加载，Phase 0 阶段 A9 不依赖它们。

#### G3: prepare_llm_context() → engine task_prompt 的 token 预算需要分配

**来源**: `orchestrator-completion-spec.md` L319 — `developing` 总预算 10000 tokens

**现状**: Phase 0 规定了 `developing` 状态的上下文预算为 10000 tokens (model_window=200K 的 5%)，压缩后约 4300-4500 tokens。但这个预算是给 `context_package` 的，不包括 engine 的 task_prompt、feedback、decisions 等附加信息。

**补充 (本 spec)**: A9 在实际使用中的 token 分配:

```
A9 向 engine (Claude Code CLI) 发送的完整上下文:
─────────────────────────────────────────────
system prompt (Claude Code):            ~500 tokens
compressed context (prepare_llm):       ~4500 tokens  ← 来自 context_build 压缩
decisions (追加):                        ~200 tokens   ← 本 spec 的 decisions 注入
task_prompt (引擎工作指令):              ~800 tokens   ← "生成用户管理模块..."
feedback (上一轮失败信息):                ~500 tokens   ← 只在 iteration > 1 时
─────────────────────────────────────────────
总计 (首轮):                             ~6000 tokens
总计 (带 feedback):                      ~6500 tokens
─────────────────────────────────────────────
```

在 200K 模型窗口中占比 ~3%，安全余量充足。

#### G4: build_enhanced_prompt() 的调用时机和顺序

**来源**: `jap-plus-absorption-plan.md` L862-891 — `BaseAgentWorker.build_enhanced_prompt()`

**现状**: jap-plus 设计 `build_enhanced_prompt()` 在 `prepare_llm_context()` **之前**运行——先注入 system prompt + Skills rules，再把组装好的内容送入压缩管道。本 spec 没有提及这个顺序。

**补充 (本 spec)**: Phase 2 接入 Skills 后的调用顺序:

```python
# A9DevAgent.execute() 中 — Phase 2+ 的完整调用链

# 1. Skills 注入到 system prompt
enhanced_system = await self.build_enhanced_prompt(
    base_prompt="你是一个全栈开发工程师...",
    workspace_path=str(runtime.worktree_path),  # 支持项目级 .ai-native/
)

# 2. 上下文压缩 (包含 knowledge + artifacts)
compressed_context = await self.prepare_llm_context(context, state="developing")

# 3. 组装 engine 的完整 prompt
engine_prompt = self._build_engine_prompt(
    system=enhanced_system,
    context=compressed_context,
    task=task_spec,
    decisions=decisions,
    feedback=feedback,
)

# 4. 启动引擎
result = await engine.execute(engine_prompt, ...)
```

Phase 0 阶段: 跳过步骤 1 (Skills 未实现)，`enhanced_system` = 原始 system prompt。

---

### 12.3 对齐确认 (本 spec 设计正确的部分)

以下设计在两份对照文档中得到验证:

| 本 spec 设计 | jap-plus 对应 | orchestrator-completion-spec 对应 | 状态 |
|---|---|---|---|
| A9 内部自测 (lint/build/unit/smoke) vs A11 正式测试 | sandbox-runner-mcp `run_tests` | T4 测试上下文注入 | ✅ 对齐 |
| A9 不直接调 A11/A13，Orchestrator 驱动 | 未直接描述 | L54 `A11→test_report` 通过 artifact 链传递 | ✅ 对齐 |
| A9Runtime 隔离环境 (worktree) | sandbox-runner-mcp 底层 | 未直接描述 (Phase 0 范围外) | ✅ 方向一致 |
| 三引擎降级 (Claude Code → Codex → API) | 未直接描述 (远景 MCP tools 可覆盖) | 未直接描述 | ✅ 无冲突 |
| 多实例并发 (NATS queue group + Semaphore) | Phase 4 全链路可观测性 | 未直接描述 | ✅ 无冲突 |
| 决策前置到 A5 + Gate 1 | shared/skills/quality-gates | 未直接描述 | ✅ 方向一致 |
| prepare_llm_context() 压缩上下文 | get_context_for_agent MCP tool | T4 ContextCompressionService | ✅ 完全对齐 |
| escalate → BLOCKED 路径 | 未直接描述 | T3 Agent 超时升级通知 | ✅ 方向一致 |

---

### 12.4 更新后的实现计划 (含跨文档依赖)

```
Phase 0: 基础设施 (依赖 orchestrator-completion-spec T1-T8)
─────────────────────────────────────────────────────────────
前提: 所有 T1-T8 完成后 A9 才能收到完整上下文 + decisions + 内循环

orchestrator-completion-spec 侧的改动 (不在本 spec 范围内实现):
  T1: Gate SLA 超时通知
  T2: notify_mc DB 同步
  T3: Agent 超时升级通知
  T4: build_context 富化 + 压缩 (含 prepare_llm_context)
  T5: store_agent_result 持久化
  T6: Gate decisions 持久化 + context 注入 (v1.1)
  T7: A4 artifact 数据通路修复 (v1.1)
  T8: DEVELOPING↔TESTING 内循环 + escalation→BLOCKED 路径 (v1.1)

本 spec 在 Phase 0 期间的改动:
  0.1 [agent-workers] CoderModule/AuditorModule 增加 llm_caller 参数 (签名改造)
  0.2 [agent-workers] 删除 a9_dev_agent_stub.py + a9_claude_code_bridge.py

Phase 1: A9 基础层 (P0 — 本 spec 独立实施)
─────────────────────────────────────────────
  1.1 a9/runtime.py — A9Runtime (worktree/lint/build/test/service/start_service)
  1.2 a9/engine.py — A9CodingEngine (C3: 使用 compressed context, 不自做 assembly)
  1.3 ci_build_service.py — 独立 NATS request-reply service
  1.4 worker_launcher.py — 多实例并发 (A9_WORKER_COUNT + Semaphore)

Phase 2: A9 集成 (P0)
─────────────────────
  前提: T4-T7 完成 (context 中有完整 artifact + decisions + A4 数据)
  2.1 改造 a9/a9_dev_agent.py — C3 完整调用链
  2.2 Prometheus 指标: a9_active_tasks, a9_cycle_time
  2.3 Engine CLI 探测 + 降级测试
  2.4 磁盘清理 cron

Phase 3: 数据通路 (P1)
───────────────────────
  前提: T6 完成 (spec.decisions 存储路径确立)
  3.1 A5 新增 decisions_required 输出
  3.2 A6 DAG node 注入 decisions + A8 约束 (C2 方案 B)
  3.3 Gate 1 MC Backend 决策审批 UI + API

Phase 4: Skills 系统 (P2 — 依赖 jap-plus-absorption-plan Phase 2)
──────────────────────────────────────────────────────────────────
  4.1 .ai-native/agents/A9/skills/{dev-guidelines,tdd-rules,dual-brain}.skill.md (G2)
  4.2 A9DevAgent.execute() 接入 build_enhanced_prompt() (G4)

Phase 5: MCP 集成 (P3 — 依赖 jap-plus-absorption-plan Phase 3)
──────────────────────────────────────────────────────────────
  5.1 engine.py 扩展 MCPClient 调用 (C4 pull 模式)
  5.2 lazy_load_enabled — A9 按需拉取知识库

Phase 6: IDE 辅助模式 (P3)
──────────────────────────
  6.1 A9ReviewAgent — assisted mode
  6.2 IDE 内联反馈 (NATS → MC Backend SSE → IDE 插件)
```

---

### 12.5 本 spec 对外部文档的依赖清单

| 序号 | 依赖项 | 来源 | 状态 | 阻塞等级 |
|---|---|---|---|---|
| D1 | `context_build.py` 修复 A4 数据读取 (方案 B) | orchestrator-spec T7 | ✅ 已补充 (v1.1) | 🔴 阻塞 Phase 2 |
| D2 | `store_agent_result` 部署 — `spec.artifacts.{A1,A5,A6,A7}` 可用 | orchestrator-spec T5 | 已有 | 🔴 阻塞 Phase 2 |
| D3 | `spec.decisions` 存储 + context 注入 | orchestrator-spec T6 | ✅ 已补充 (v1.1) | 🟡 阻塞 Phase 3 |
| D4 | `prepare_llm_context()` 在 BaseAgentWorker 中可用 | orchestrator-spec T4 | 已有 | 🟡 阻塞 Phase 2 |
| D5 | DEVELOPING↔TESTING inner loop | orchestrator-spec T8 | ✅ 已补充 (v1.1) | 🟡 阻塞 Phase 2 (A9 依赖返回路径) |
| D6 | SkillLoader 实现 + `.skill.md` 文件创建 | jap-plus Phase 2 | 规划中 | ⚪ 阻塞 Phase 4 |
| D7 | MCPClient Python 实现 | jap-plus Phase 3 | 规划中 | ⚪ 阻塞 Phase 5 |


