# A9 Dev Agent — 开发任务拆解 (v1.0, 2026-07-06)

> 基于 `doc/bugs/a9-agent-design-analysis.md` v2.1
> 每个任务可独立开发、独立测试、独立 review

---

## 任务总览

```
A9 改造: 33 个任务，6 个 Phase
Phase 0: 8 个任务 (前置依赖: 删除 + 签名改造)    ~3 天
Phase 1: 8 个任务 (A9Runtime + Engine 基础层)    ~5 天
Phase 2: 7 个任务 (A9DevAgent 集成)              ~4 天
Phase 3: 5 个任务 (协作层: launcher + CI)        ~3 天
Phase 4: 3 个任务 (运维: 指标 + 清理 + 探测)     ~2 天
Phase 5: 3 个任务 (Skills + IDE 模式)            ~3 天 (远期)
```

---

# Phase 0: 前置依赖 (P0)

## 任务 0.1: 删除废弃文件

**描述**: 删除 `a9_dev_agent_stub.py` 和 `a9_claude_code_bridge.py`

**文件**: 
- 删除 `repos/agent-workers/a9_dev_agent_stub.py`
- 删除 `repos/agent-workers/a9_claude_code_bridge.py`

**前提**: 无

**验收标准**:
- [ ] `a9_dev_agent_stub.py` 已删除
- [ ] `a9_claude_code_bridge.py` 已删除
- [ ] `worker_launcher.py` 中不再导入 `a9_dev_agent_stub`
- [ ] `grep -r "a9_dev_agent_stub" repos/` 无残留引用
- [ ] `grep -r "a9_claude_code_bridge" repos/` 无残留引用

**测试方式**: 
```bash
# 检查无残留引用
grep -r "a9_dev_agent_stub\|a9_claude_code_bridge" repos/agent-workers/ repos/orchestrator/
# 应无输出
```

---

## 任务 0.2: CoderModule 签名改造

**描述**: CoderModule 增加 `llm_caller` 可选参数，修复 LLM 调用链

**文件**: `repos/agent-workers/a9/coder.py`

**改动**:
1. `__init__` 签名: `def __init__(self, llm_caller=None, work_base=..., enable_llm=True)`
2. 存储 `self._llm_caller = llm_caller`
3. `_call_llm_for_code_generation()` 中删除 `from a9_claude_code_bridge import ClaudeCodeBridge; bridge = ClaudeCodeBridge()` 
4. 改为调用 `self._llm_caller(messages, ...)` 或保留 mock fallback

**测试方式**:
```python
# test_coder_module.py
async def test_coder_with_llm_injection():
    captured = []
    async def mock_llm(messages, **kwargs):
        captured.append(messages)
        return '{"files": [{"path": "test.py", "content": "pass", "language": "python"}], "summary": "test", "dependencies": []}'
    
    coder = CoderModule(llm_caller=mock_llm, enable_llm=True)
    result = await coder.generate(
        {"type": "backend", "title": "test", "plan": {"files_to_create": ["src/test.py"]}},
        {}
    )
    assert len(captured) == 1
    assert result["status"] == "success"

async def test_coder_fallback_without_llm():
    coder = CoderModule(llm_caller=None, enable_llm=False)
    result = await coder.generate(
        {"type": "backend", "title": "test", "plan": {"files_to_create": ["src/test.py"], "files_to_modify": []}},
        {}
    )
    assert result["status"] == "success"
    assert len(result["diff"]["files_changed"]) >= 1  # mock code generated
```

**验收标准**:
- [ ] `CoderModule(llm_caller=mock_fn)` 不报错
- [ ] 传入 `llm_caller` 时走 LLM 路径
- [ ] 不传 `llm_caller` 时退到 mock 路径
- [ ] 不再 import `ClaudeCodeBridge`
- [ ] 现有 CoderModule 的 worktree 创建/代码生成/self-inspection 功能不变

---

## 任务 0.3: AuditorModule 签名改造 + 语义审查

**描述**: AuditorModule 增加 `llm_caller` 参数 + 子进程并发控制

**文件**: `repos/agent-workers/a9/auditor.py`

**改动**:
1. `__init__` 签名: `def __init__(self, llm_caller=None, enable_analysis=True, max_parallel_tools=2)`
2. 存储 `self._llm_caller` + `self._tool_semaphore = asyncio.Semaphore(max_parallel_tools)`
3. `review()` 中并行跑 static analysis + LLM semantic review
4. 新增 `_semantic_review(diff)` — LLM 审查安全/业务/性能/规范
5. `_run_pylint` / `_run_eslint` 内部加 `async with self._tool_semaphore:`

**测试方式**:
```python
# test_auditor_module.py
async def test_auditor_with_llm():
    mock_issues = [{"severity": "error", "message": "SQL injection risk"}]
    async def mock_llm(messages, **kwargs):
        return json.dumps({"issues": mock_issues})

    auditor = AuditorModule(llm_caller=mock_llm)
    result = await auditor.review({
        "files_changed": [{"path": "src/api.py", "language": "python", "patch_preview": "SELECT * FROM users WHERE id = %s"}],
        "changes_summary": "1 file changed"
    })
    assert "issues" in result
    assert result["decision"] in ("approved", "rejected")

async def test_auditor_without_llm():
    auditor = AuditorModule(llm_caller=None)
    result = await auditor.review({
        "files_changed": [{"path": "src/api.py", "language": "python", "patch_preview": "def test(): pass"}],
        "changes_summary": "1 file changed"
    })
    assert result["decision"] in ("approved", "rejected")
    assert result["analysis_detail"]["files_analyzed"] == 1

async def test_semaphore_limits_concurrent_tools():
    auditor = AuditorModule(max_parallel_tools=1)
    # 同时启动 3 个 pylint 任务，验证 semaphore 限制并发
    ...
```

**验收标准**:
- [ ] `AuditorModule(llm_caller=mock_fn)` 不报错
- [ ] 传入 `llm_caller` 时同时产出静态 + 语义审查结果
- [ ] 不传 `llm_caller` 时只产出静态分析结果 (行为不变)
- [ ] `_tool_semaphore` 限制 jest lint 进程数 (通过 mock subprocess 验证 semaphore acquire 次数)
- [ ] 审查决策融合了静态分析和语义审查两者的发现

---

## 任务 0.4: A9DevAgent 基类初始化

**描述**: 创建 A9DevAgent 类骨架，继承 BaseAgentWorker，注入 Coder + Auditor

**文件**: `repos/agent-workers/a9/a9_dev_agent.py` (重构现有文件)

**改动**:
1. 保持 `agent_id = "A9"`, `agent_type = "dev_agent"`
2. `__init__` 中注入 `llm_caller`:
   ```python
   def __init__(self, nats_url=..., enable_llm=True, max_concurrent=3, instance_id=0):
       super().__init__("A9", "dev_agent", nats_url)
       self.coder = CoderModule(llm_caller=self.call_llm)
       self.auditor = AuditorModule(llm_caller=self.call_llm)
       self.max_iterations = 3
       self._semaphore = asyncio.Semaphore(max_concurrent)
       self._instance_id = instance_id
       self._active_tasks: dict[str, asyncio.Task] = {}
   ```
3. 实现 `_build_dev_plan()` (从现有代码迁移)
4. 实现 `_build_task_prompt()` 骨架 (先用 stub，Phase 2 完善)
5. `execute()` 先用 stub 实现 (只返回 mock result, Phase 2 完善)

**测试方式**:
```python
# test_a9_dev_agent_init.py
async def test_agent_initialization():
    agent = A9DevAgent(enable_llm=False)
    assert agent.agent_id == "A9"
    assert agent.agent_type == "dev_agent"
    assert agent.coder is not None
    assert agent.auditor is not None
    assert agent.max_iterations == 3
    assert agent._semaphore is not None

async def test_build_dev_plan():
    agent = A9DevAgent(enable_llm=False)
    plan = agent._build_dev_plan({
        "openapi": {"info": {"title": "test"}, "paths": {"/api/users": {}, "/api/orders": {}}},
        "erd": {"tables": [{"name": "users"}, {"name": "orders"}]}
    })
    assert "files_to_create" in plan
    assert len(plan["files_to_create"]) > 0
    assert "src/routes/" in str(plan["files_to_create"])
```

**验收标准**:
- [ ] A9DevAgent 成功继承 BaseAgentWorker
- [ ] `__init__` 中 Coder + Auditor 被正确注入 `llm_caller`
- [ ] `_build_dev_plan()` 返回与现有 stub 兼容的输出格式
- [ ] agent_id/agent_type 正确注册

---

## 任务 0.5: worker_launcher 切换到 A9DevAgent

**描述**: `worker_launcher.py` 中 `from a9_dev_agent_stub import DevAgent` 改为 `from a9.a9_dev_agent import A9DevAgent`

**文件**: `repos/agent-workers/worker_launcher.py`

**改动**:
```python
# 改前:
from a9_dev_agent_stub import DevAgent
DevAgent(),

# 改后:
from a9.a9_dev_agent import A9DevAgent
A9DevAgent(),
```

**测试方式**:
```bash
cd repos/agent-workers
python -c "from a9.a9_dev_agent import A9DevAgent; a = A9DevAgent(enable_llm=False); print('OK:', a.agent_id)"
```

**验收标准**:
- [ ] `worker_launcher.py` 不再 import `a9_dev_agent_stub`
- [ ] `A9DevAgent()` 实例化成功
- [ ] `python worker_launcher.py` 启动不报 import 错误
- [ ] `register_agents()` 返回的列表中包含 A9DevAgent 实例

---

## 任务 0.6: 更新 `a9/__init__.py` 导出

**描述**: 确保 `a9/__init__.py` 正确导出所有模块

**文件**: `repos/agent-workers/a9/__init__.py`

**改动**: 添加 `A9DevAgent` 的导出 (如果需要)

**测试方式**:
```python
from a9.a9_dev_agent import A9DevAgent  # 应成功
from a9.coder import CoderModule        # 应成功
from a9.auditor import AuditorModule     # 应成功
```

**验收标准**:
- [ ] 所有模块都能从 `a9.*` 正常 import
- [ ] 无循环 import

---

## 任务 0.7: NATS subject 验证

**描述**: 确认 A9 使用的 NATS subject 与其他 Agent 一致

**文件**: `repos/agent-workers/a9/a9_dev_agent.py`

**改动**: 
1. 确认 `subscribe_nats()` 订阅的 subject 是 `context.ready.dev_agent` (与 launcher 中 `agent_type = "dev_agent"` 一致)
2. 确认 `report_status` / `report_artifact` 的 subject 与 Bridge 预期一致

**测试方式**:
```python
# 验证 subject 拼接
from base_worker import BaseAgentWorker
agent = A9DevAgent(enable_llm=False)
assert agent.agent_type == "dev_agent"
# subscribe_nats 应订阅 context.ready.dev_agent
```

**验收标准**:
- [ ] A9 的 agent_type 与 worker_launcher 注册一致
- [ ] NATS subject 拼写正确: `context.ready.dev_agent`
- [ ] NATS 消息格式与 Bridge 兼容

---

## 任务 0.8: repo_url / branch / decisions 字段的 context 解析

**描述**: `execute()` 中正确解析 context dict 中的各级字段

**文件**: `repos/agent-workers/a9/a9_dev_agent.py`

**改动**: 实现 context 解析:
```python
async def execute(self, req_id: str, context_package: dict) -> dict:
    # context_package 由 build_context 构建，基层结构:
    # {req_id, state, agent_id, requirement_context, artifact_context,
    #  knowledge_context, decisions_context, environment_context, rework_context,
    #  title, spec_sections, openapi_hint, erd_hint, dag_hint, constraints, note,
    #  decisions, ...}

    # 提取 A9 需要的核心字段
    spec_package = {
        "openapi": context_package.get("openapi_hint", {}),
        "erd": context_package.get("erd_hint", {}),
    }
    task = {
        "title": context_package.get("title", ""),
        "description": context_package.get("note", ""),
        "dag_nodes": context_package.get("dag_hint", {}).get("nodes", []),
    }
    decisions = context_package.get("decisions", {})
    repo_url = context_package.get("environment_context", {}).get("project", {}).get("repo_url", "")
    branch = context_package.get("environment_context", {}).get("project", {}).get("branch", "main")
    ...
```

**测试方式**:
```python
async def test_context_parsing():
    agent = A9DevAgent(enable_llm=False)
    context = {
        "title": "用户管理模块",
        "decisions": {"arch-d1": "Redis", "arch-d2": "JWT"},
        "openapi_hint": {"endpoints": ["/api/users"]},
        "erd_hint": {"tables": ["users"]},
        "dag_hint": {"nodes": [{"id": "t1", "title": "CRUD API"}]},
        "environment_context": {"project": {"repo_url": "git@gitlab:team/proj.git"}},
    }
    # Phase 2 执行完整流程后再验证字段能被正确提取
    pass
```

**验收标准**:
- [ ] `repo_url` 从 `environment_context.project.repo_url` 正确提取
- [ ] `decisions` 从顶层 `decisions` key 正确提取
- [ ] `spec_package` 从 `openapi_hint` / `erd_hint` 正确提取
- [ ] 缺失字段不抛异常 (使用 `.get()` 安全取值)

---

# Phase 1: 基础层 (P0)

## 任务 1.1: A9Runtime — Git 操作

**描述**: 实现 `A9Runtime.setup()` / `cleanup()` — worktree 创建和清理

**文件**: `repos/agent-workers/a9/runtime.py` (新增)

**接口**:
```python
class A9Runtime:
    def __init__(self, config: RuntimeConfig | None = None): ...
    async def setup(self, repo_url: str, branch: str = "main") -> Path: ...
    async def cleanup(self): ...
```

**逻辑**:
1. `setup()` → `_create_worktree(repo_url, branch)` → `git clone --bare` → `git worktree add`
2. 无 repo_url 时 → temp directory + `git init`
3. `cleanup()` → `git worktree remove --force` 或 `shutil.rmtree`

**测试方式**:
```python
# test_runtime_git.py
async def test_setup_without_repo():
    runtime = A9Runtime()
    path = await runtime.setup("", "main")
    assert path.exists()
    assert (path / "src").exists()
    assert (path / "tests").exists()
    await runtime.cleanup()
    assert not path.exists()

async def test_setup_with_bare_repo():
    # 创建一个本地 bare repo 用于测试
    ...
    runtime = A9Runtime()
    path = await runtime.setup("file:///tmp/test-repo.git", "main")
    assert path.exists()
    assert (path / ".git").exists()
    await runtime.cleanup()

async def test_cleanup_removes_worktree():
    runtime = A9Runtime()
    path = await runtime.setup("", "main")
    assert path.exists()
    await runtime.cleanup()
    assert not path.exists()  # 目录已删除

async def test_session_id_unique():
    rt1 = A9Runtime()
    rt2 = A9Runtime()
    assert rt1.session_id != rt2.session_id
```

**验收标准**:
- [ ] `setup("", "main")` 创建 temp workspace with src/ tests/ dirs
- [ ] `setup(repo_url, branch)` 创建 git worktree
- [ ] `cleanup()` 删除 worktree 目录
- [ ] session_id 每次唯一
- [ ] worktree base dir 可配置 (`RuntimeConfig.work_base`)
- [ ] git 操作失败时抛 `RuntimeError` (含 stderr 信息)

---

## 任务 1.2: A9Runtime — Lint

**描述**: 实现 `A9Runtime.lint(files, language)` — 对指定文件运行 linter

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
async def lint(self, files: list[str], language: str) -> LintResult: ...
```

**逻辑**:
1. `language="python"` → `asyncio.create_subprocess_exec("pylint", "--output-format=json", *files)`
2. `language in ("javascript", "typescript")` → `eslint --format=json`
3. 解析 JSON stdout → `LintResult(errors=[], warnings=[], status="ok|warning|error", tool="pylint|eslint|none")`
4. pylint/eslint 未安装 → `LintResult(status="ok", tool="none")` (不抛异常)
5. 超时 30s → `LintResult(status="warning", warnings=[{message: "lint timeout"}])`

**测试方式**:
```python
# test_runtime_lint.py
async def test_lint_python_file():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    # 写入一个有 lint 问题的 python 文件
    (runtime.worktree_path / "src" / "bad.py").write_text("def f(x,y):return x+y\n")
    result = await runtime.lint(["src/bad.py"], "python")
    assert isinstance(result, LintResult)
    assert result.tool in ("pylint", "none")  # none if pylint not installed
    await runtime.cleanup()

async def test_lint_no_workspace():
    runtime = A9Runtime()
    result = await runtime.lint(["test.py"], "python")
    assert result.status == "error"
    assert "No workspace" in str(result.errors)

async def test_lint_unknown_language():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    result = await runtime.lint(["test.xyz"], "haskell")
    assert result.status == "ok"
    assert result.tool == "none"
    await runtime.cleanup()
```

**验收标准**:
- [ ] Python 文件正确调用 pylint (or 检测到 pylint 未安装时不报错)
- [ ] JS/TS 文件正确调用 eslint
- [ ] 未安装工具时返回 `tool="none"`, status="ok"
- [ ] 超时 30s 后返回 warning，不抛异常
- [ ] 无 workspace 时返回 error
- [ ] 返回值符合 `LintResult` dataclass 结构

---

## 任务 1.3: A9Runtime — Build

**描述**: 实现 `A9Runtime.build(language)` — 编译/类型检查

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
async def build(self, language: str, target: str = "") -> BuildResult: ...
```

**逻辑**:
1. Python → `python -m compileall -q <worktree>`
2. TypeScript → `npx tsc --noEmit`
3. Go → `go build ./...`
4. 超时: 120s

**测试方式**:
```python
async def test_build_python():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    (runtime.worktree_path / "src" / "valid.py").write_text("def hello(): return 'world'\n")
    result = await runtime.build("python")
    assert isinstance(result, BuildResult)
    assert result.success == True  # valid python 应编译通过
    await runtime.cleanup()

async def test_build_python_syntax_error():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    (runtime.worktree_path / "src" / "bad.py").write_text("def hello( return 'world'\n")  # 语法错误
    result = await runtime.build("python")
    assert result.success == False
    assert result.exit_code != 0
    await runtime.cleanup()

async def test_build_unknown_language():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    result = await runtime.build("haskell")
    assert result.success == True  # 无 build step 的语言默认通过
    await runtime.cleanup()
```

**验收标准**:
- [ ] Python `compileall` 正确检测语法错误
- [ ] 未知语言默认 success=True
- [ ] 超时 120s 后返回 success=False
- [ ] 无 workspace 时返回 stderr="No workspace"
- [ ] duration_ms 正确记录

---

## 任务 1.4: A9Runtime — Test Runner

**描述**: 实现 `A9Runtime.test(command)` — 运行测试并解析结果

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
async def test(self, command: list[str] | None = None) -> TestReport: ...
```

**逻辑**:
1. command 为 None → 自动检测: pytest if (worktree / "tests").exists() else jest if package.json else go test
2. 解析 stdout: 先试 pytest pattern (`N passed, M failed`), 再试 jest pattern (`Tests: N passed, M failed`), fallback 依赖 exit code
3. 超时: 300s

**测试方式**:
```python
async def test_pytest_integration():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    # 写入测试文件
    (runtime.worktree_path / "tests").mkdir(exist_ok=True)
    (runtime.worktree_path / "tests" / "test_example.py").write_text(
        "def test_pass(): assert True\n"
        "def test_pass2(): assert 1 + 1 == 2\n"
    )
    result = await runtime.test(["pytest", "tests/", "-v", "--tb=short"])
    assert isinstance(result, TestReport)
    assert result.passed >= 2
    assert result.failed == 0
    await runtime.cleanup()

async def test_pytest_with_failures():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    (runtime.worktree_path / "tests").mkdir(exist_ok=True)
    (runtime.worktree_path / "tests" / "test_fail.py").write_text(
        "def test_fail(): assert False, 'expected failure'\n"
    )
    result = await runtime.test(["pytest", "tests/", "-v", "--tb=short"])
    assert result.failed >= 1
    await runtime.cleanup()

async def test_auto_detect_pytest():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    (runtime.worktree_path / "tests").mkdir(exist_ok=True)
    (runtime.worktree_path / "tests" / "test_x.py").write_text("def test_x(): assert True\n")
    result = await runtime.test()  # 自动检测 pytest
    assert result.total > 0
    await runtime.cleanup()

async def test_test_timeout():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    # 创建死循环测试
    (runtime.worktree_path / "tests").mkdir(exist_ok=True)
    (runtime.worktree_path / "tests" / "test_sleep.py").write_text(
        "import time\ndef test_sleep(): time.sleep(400); assert True\n"
    )
    runtime.config.timeout_test = 5  # 5秒超时
    result = await runtime.test(["pytest", "tests/test_sleep.py", "-v"])
    assert result.errors > 0 or "timeout" in str(result.failures_detail).lower()
    await runtime.cleanup()
```

**验收标准**:
- [ ] 自动检测 pytest/jest/go test
- [ ] pytest 输出正确解析 (passed/failed/errors/skipped)
- [ ] pytest 失败时 failed > 0
- [ ] 超时 300s 返回 error
- [ ] 无 workspace 时返回 error
- [ ] duration_ms 正确记录

---

## 任务 1.5: A9Runtime — Start/Stop Service

**描述**: 实现 `start_service()` / `stop_all_services()` — 启动项目进程用于 smoke test

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
async def start_service(self, command: list[str], health_check_url: str = "",
                        timeout: int = 30, bind_host: str = "127.0.0.1") -> dict: ...
async def stop_all_services(self): ...
```

**逻辑**:
1. 找空闲端口 (bind 127.0.0.1:0)
2. 启动子进程，环境变量中注入 PORT + BIND_HOST
3. 等待 health_check_url 返回 200 (轮询最多 timeout 秒)
4. stop_all_services: terminate → wait(10s) → kill

**测试方式**:
```python
async def test_start_stop_service():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    # 写入一个简单的 HTTP server
    (runtime.worktree_path / "server.py").write_text("""
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
httpd = HTTPServer(('127.0.0.1', int(os.environ['PORT'])), H)
httpd.serve_forever()
""")
    service = await runtime.start_service(
        command=["python", "server.py"],
        health_check="/health",
        timeout=10,
        bind_host="127.0.0.1",
    )
    assert service["port"] > 0
    assert "localhost" in service["url"]
    await runtime.stop_all_services()
    await runtime.cleanup()

async def test_health_check_timeout():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    # 启动一个没有 /health 的服务
    (runtime.worktree_path / "noserver.py").write_text("import time; time.sleep(60)\n")
    service = await runtime.start_service(
        command=["python", "noserver.py"],
        health_check="/health",
        timeout=2,
    )
    # 超时后仍返回 dict，但 health check 未通过（不抛异常）
    assert service["port"] > 0
    await runtime.stop_all_services()
    await runtime.cleanup()

async def test_binds_localhost():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    # 验证端口绑定在 127.0.0.1 而非 0.0.0.0
    sock = runtime._find_free_port("127.0.0.1")
    # ...
    await runtime.cleanup()
```

**验收标准**:
- [ ] 服务启动后 health check 通过
- [ ] 端口绑定在 127.0.0.1 (非 0.0.0.0)
- [ ] health check 超时后不阻塞，返回 dict (不抛异常)
- [ ] stop_all_services 正确终止所有进程
- [ ] 进程异常退出时不抛异常

---

## 任务 1.6: A9Runtime — Context Manager

**描述**: 实现 `A9Runtime.__aenter__` / `__aexit__` — 支持 `async with`

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
async def __aenter__(self): return self
async def __aexit__(self, *args): await self.cleanup()
```

**测试方式**:
```python
async def test_context_manager():
    path = None
    async with A9Runtime() as runtime:
        path = await runtime.setup("", "main")
        assert path.exists()
    # __aexit__ 后
    assert not path.exists()  # cleanup 已调用
```

**验收标准**:
- [ ] `async with A9Runtime() as rt:` 语法可用
- [ ] exit 时自动调用 cleanup
- [ ] cleanup 异常不吞没（记录日志后继续）

---

## 任务 1.7: A9Runtime — LintResult/BuildResult/TestReport/RuntimeConfig dataclasses

**描述**: 定义 4 个 dataclass 类型，确保返回值类型安全

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
@dataclass
class LintResult:
    language: str
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    status: str = "ok"  # ok|warning|error
    tool: str = "none"

@dataclass
class BuildResult:
    language: str
    success: bool = True
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0

@dataclass
class TestReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: float = 0
    coverage_pct: float = 0.0
    failures_detail: list[dict] = field(default_factory=list)

@dataclass
class RuntimeConfig:
    work_base: str = "/tmp/a9-runtimes"
    timeout_lint: int = 30
    timeout_build: int = 120
    timeout_test: int = 300
    max_worktree_age: int = 3600
```

**测试方式**:
```python
def test_dataclass_defaults():
    r = LintResult(language="python")
    assert r.status == "ok"
    assert r.errors == []
    assert r.tool == "none"

    b = BuildResult(language="go")
    assert b.success == True

    t = TestReport()
    assert t.total == 0
    assert t.passed == 0
```

**验收标准**:
- [ ] 4 个 dataclass 可正常实例化
- [ ] 默认值正确
- [ ] JSON 序列化可用 (`dataclasses.asdict`)

---

## 任务 1.8: A9Runtime — 语言检测辅助方法

**描述**: 实现 `_detect_start_command(language)` / `_detect_test_command()` 等辅助方法

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
def _detect_start_command(self, language: str) -> list[str]: ...
def _detect_test_command(self) -> list[str]: ...
```

**逻辑**:
1. `_detect_start_command`: Python → `["python", "-m", "uvicorn", "main:app", "--port", "0"]` (or flask/django variants)
2. `_detect_test_command`: 检查 worktree 中存在的测试框架配置文件

**测试方式**:
```python
async def test_detect_start_command_python():
    runtime = A9Runtime()
    assert "python" in runtime._detect_start_command("python")[0]

async def test_detect_test_command_pytest():
    runtime = A9Runtime()
    await runtime.setup("", "main")
    (runtime.worktree_path / "tests").mkdir(exist_ok=True)
    cmd = runtime._detect_test_command()
    assert "pytest" in cmd
    await runtime.cleanup()
```

**验收标准**:
- [ ] Python 返回 uvicorn 命令
- [ ] test 检测逻辑正确
- [ ] 项目中有 jest.config.js 时返回 jest
- [ ] 项目中只有 tests/ 目录时返回 pytest

---

# Phase 2: 集成层 (P0)

## 任务 2.1: A9CodingEngine — EngineResult dataclass + 基础骨架

**描述**: 定义引擎返回类型 + 引擎主入口骨架

**文件**: `repos/agent-workers/a9/engine.py` (新增)

**接口**:
```python
@dataclass
class EngineResult:
    engine: str            # "claude-code" | "codex" | "anthropic-api"
    success: bool
    files_changed: list
    diff_raw: str
    summary: str
    session_id: str
    cost_estimate: float
    duration_ms: float
    tool_calls_count: int = 0
    test_results: dict | None = None
    ambiguities: list | None = None      # ← Type 1
    blocking_issues: list | None = None  # ← Type 3

class A9CodingEngine:
    def __init__(self, runtime, llm_caller=None):
        self.runtime = runtime
        self._llm_caller = llm_caller
        self._available = self._detect_available()
        self._claude_cli_config = self._probe_claude_cli()

    def _detect_available(self) -> list[str]: ...
    def _probe_claude_cli(self) -> dict | None: ...
    async def execute(self, task: str, engine: str = "auto",
                      language: str = "python", max_turns: int = 50,
                      feedback: str = "") -> EngineResult: ...
```

**测试方式**:
```python
def test_engine_result_dataclass():
    r = EngineResult(engine="anthropic-api", success=True, files_changed=[], 
                     diff_raw="", summary="", session_id="", cost_estimate=0.0, duration_ms=0)
    assert r.engine == "anthropic-api"
    assert r.ambiguities is None

def test_engine_init_without_cli():
    # 在没有 claude CLI 的环境中
    rt = A9Runtime()
    engine = A9CodingEngine(rt, llm_caller=None)
    assert "anthropic-api" in engine._available  # fallback 总是可用
    # claude-code 可能不在 available 中(取决于环境)
```

**验收标准**:
- [ ] EngineResult dataclass 包含所有字段
- [ ] `_detect_available()` 返回可用的引擎列表
- [ ] `_probe_claude_cli()` 在无 CLI 时返回 None
- [ ] `execute(engine="auto")` 选择优先级最高的可用引擎

---

## 任务 2.2: A9CodingEngine — Claude Code CLI 模式

**描述**: 实现 `_run_claude_code()` — 启动 Claude Code CLI 子进程

**文件**: `repos/agent-workers/a9/engine.py`

**逻辑**:
1. 使用 `self._claude_cli_config` 中探测到的正确 flag 名称
2. `asyncio.create_subprocess_exec("claude", print_flag, task, output_flag, "stream-json", "--max-turns", str(max_turns), ...)`
3. 解析 NDJSON 输出 → events 列表
4. 从 events 中提取: files_changed, total_cost_usd, session_id, summary
5. 从 worktree 获取 `git diff --cached`
6. 超时: 600s

**测试方式**:
```python
async def test_claude_code_mock():
    """如果环境有 claude CLI"""
    rt = A9Runtime()
    await rt.setup("", "main")
    engine = A9CodingEngine(rt, llm_caller=None)
    if "claude-code" in engine._available:
        result = await engine.execute(
            "Create a hello.py file that prints 'hello world'",
            language="python", max_turns=5,
        )
        assert isinstance(result, EngineResult)
        assert result.engine == "claude-code"
    await rt.cleanup()

async def test_cli_not_available_falls_back():
    rt = A9Runtime()
    await rt.setup("", "main")
    # mock _detect_available 返回空
    engine = A9CodingEngine(rt, llm_caller=None)
    engine._available = ["anthropic-api"]  # force fallback
    result = await engine.execute("test task")
    assert result.engine == "anthropic-api"
    await rt.cleanup()
```

**验收标准**:
- [ ] CLI 可用时成功启动子进程
- [ ] CLI 不可用时正确降级
- [ ] NDJSON 解析正确提取 event 字段
- [ ] git diff 正确捕获 worktree 变更
- [ ] 超时 600s 后返回 EngineResult(success=False)
- [ ] 非零 exit code 被正确记录

---

## 任务 2.3: A9CodingEngine — Anthropic API Fallback

**描述**: 实现 `_run_anthropic_api()` — 用 LLM callable 生成代码

**文件**: `repos/agent-workers/a9/engine.py`

**逻辑**:
1. 构建 prompt → 调用 `self._llm_caller()`
2. 解析 JSON → 提取 files[{path, content, language}]
3. 写入 worktree
4. 返回 `EngineResult(engine="anthropic-api", ...)`

**测试方式**:
```python
async def test_anthropic_api_fallback():
    rt = A9Runtime()
    await rt.setup("", "main")
    
    captured = []
    async def mock_llm(messages, **kwargs):
        captured.append(messages)
        return json.dumps({
            "files": [{"path": "src/hello.py", "content": "def hello(): return 'world'", "language": "python"}],
            "summary": "Created hello.py",
            "dependencies": [],
        })
    
    engine = A9CodingEngine(rt, llm_caller=mock_llm)
    result = await engine.execute("create hello world", language="python")
    
    assert result.engine == "anthropic-api"
    assert result.success == True
    assert len(result.files_changed) == 1
    assert result.files_changed[0]["path"] == "src/hello.py"
    assert (rt.worktree_path / "src" / "hello.py").exists()
    
    await rt.cleanup()

async def test_api_fallback_bad_json():
    rt = A9Runtime()
    await rt.setup("", "main")
    
    async def bad_llm(messages, **kwargs):
        return "not valid json ```json {bad} ```"
    
    engine = A9CodingEngine(rt, llm_caller=bad_llm)
    result = await engine.execute("test", language="python")
    assert result.success == False  # JSON parse 失败
    await rt.cleanup()
```

**验收标准**:
- [ ] LLM 返回合法 JSON 时正确写入 worktree
- [ ] JSON 格式错误时返回 success=False
- [ ] markdown code block 包裹的 JSON 正确解析
- [ ] LLM callable 为 None 时返回 EngineResult(success=False)

---

## 任务 2.4: A9CodingEngine — CLI Probe 探测

**描述**: 实现 `_probe_claude_cli()` — 运行时探测 CLI flag

**文件**: `repos/agent-workers/a9/engine.py`

**逻辑**:
1. `shutil.which("claude")` → 无 → 返回 None
2. `subprocess.run(["claude", "--help"], timeout=10)` → 解析 help 输出
3. 寻找 `--print` / `--prompt` → `print_flag`
4. 寻找 `--output-format` / `--output` → `output_flag`
5. 返回 `{path, print_flag, output_flag, version}`

**测试方式**:
```python
def test_probe_no_claude():
    engine = A9CodingEngine.__new__(A9CodingEngine)
    # mock shutil.which 返回 None
    result = engine._probe_claude_cli()
    assert result is None

def test_probe_claude_help_output():
    # mock subprocess.run 返回模拟 help 文本
    ...
```

**验收标准**:
- [ ] `claude` 不在 PATH → 返回 None
- [ ] help 含 `--print` → print_flag="--print"
- [ ] help 含 `--prompt` 不含 `--print` → print_flag="--prompt"
- [ ] help 含 `--output-format` → output_flag="--output-format"
- [ ] subprocess 超时 10s 内返回

---

## 任务 2.5: A9CodingEngine — Codex CLI 模式 (可选)

**描述**: 实现 `_run_codex()` — 备选引擎

**文件**: `repos/agent-workers/a9/engine.py`

**优先级**: 可选 (Codex CLI 仅在有 OpenAI key 时使用，且优先级低于 Claude Code)

**逻辑**:
1. `asyncio.create_subprocess_exec("codex", "exec", task, "--workdir", worktree, "--no-sandbox")`
2. 超时: 600s

**测试方式**:
```python
async def test_codex_skipped_if_not_installed():
    rt = A9Runtime()
    await rt.setup("", "main")
    engine = A9CodingEngine(rt, llm_caller=None)
    engine._available = [e for e in engine._available if e != "codex"]
    result = await engine.execute("test", language="python")
    assert result.engine != "codex"
    await rt.cleanup()
```

**验收标准**:
- [ ] Codex 不可用时无声跳过
- [ ] 可通过环境变量 `CODEX_ENABLED` 开关
- [ ] 失败时降级到下一个引擎

---

## 任务 2.6: A9DevAgent.execute() 完整流程 — Gate 循环

**描述**: 实现 `execute()` 中的主迭代循环和质量门控

**文件**: `repos/agent-workers/a9/a9_dev_agent.py`

**逻辑** (对应 spec 第 7 节):
```
for iteration in 1..3:
  1. engine.execute(task_prompt, feedback=feedback)
  2. [Type 3] → _escalate_blocking_issue → return {status: "blocked"}
  3. [Type 1] → _record_ambiguity
  4. runtime.lint(files, lang) → [error? → feedback, continue]
  5. runtime.build(lang) → [fail? → feedback, continue]
  6. runtime.test() → [fail? → feedback, continue]
  7. runtime.start_service() → runtime.test(smoke) → runtime.stop_all_services()
     [fail? → feedback, continue]
  8. auditor.review(diff) → [approved? → break]
     [rejected? → feedback = format_audit_feedback, continue]
return result
```

**测试方式**: (集成测试 — 这是核心流程)
```python
async def test_execute_happy_path():
    agent = A9DevAgent(enable_llm=False)
    # mock engine to return successful result
    # mock linter to pass
    # mock build to pass
    # mock tester to pass (0 failures)
    # mock auditor to approve
    result = await agent.execute("req-001", full_context)
    assert result["status"] == "completed"
    assert result["iterations"] == 1

async def test_execute_lint_failure_retry():
    agent = A9DevAgent(enable_llm=False)
    # mock: 第1轮 lint fail → 第2轮 lint pass → auditor approve
    result = await agent.execute("req-001", full_context)
    assert result["status"] == "completed"
    assert result["iterations"] == 2

async def test_execute_max_iterations_exhausted():
    agent = A9DevAgent(enable_llm=False)
    agent.max_iterations = 3
    # mock: 3轮全部审计拒绝
    result = await agent.execute("req-001", full_context)
    assert result["status"] == "escalated"

async def test_execute_blocking_issue():
    agent = A9DevAgent(enable_llm=False)
    # mock engine 返回 blocking_issues
    result = await agent.execute("req-001", full_context)
    assert result["status"] == "blocked"
```

**验收标准**:
- [ ] 一次通过: iterations=1, status=completed
- [ ] lint 失败 → 下一轮修复后通过
- [ ] build 失败 → 下一轮修复后通过
- [ ] test 失败 → 下一轮修复后通过
- [ ] smoke test 失败 → 下一轮修复后通过
- [ ] auditor reject → 下一轮带 feedback
- [ ] 3 轮全部失败 → status=escalated
- [ ] blocking_issue → status=blocked (不等待 max_iterations)
- [ ] 每一轮都通过 `report_status()` 上报进度

---

## 任务 2.7: A9DevAgent — _build_task_prompt + _format_feedback

**描述**: 实现 prompt 构建和 feedback 格式化辅助方法

**文件**: `repos/agent-workers/a9/a9_dev_agent.py`

**方法**:
1. `_build_task_prompt(spec, task, decisions)` → str
2. `_format_feedback(lint, build, tests)` → str
3. `_format_audit_feedback(audit)` → str
4. `_detect_language(files_or_task)` → str

**测试方式**:
```python
def test_build_task_prompt():
    agent = A9DevAgent(enable_llm=False)
    prompt = agent._build_task_prompt(
        {"openapi": {"endpoints": ["/api/users"]}, "erd": {"tables": ["users"]}},
        {"title": "用户CRUD"},
        {"arch-d1": "Redis"},
    )
    assert "用户CRUD" in prompt
    assert "Redis" in prompt
    assert "/api/users" in prompt

def test_format_feedback():
    agent = A9DevAgent(enable_llm=False)
    lint = LintResult(language="python", status="error", 
                      errors=[{"line": 10, "message": "undefined variable"}])
    fb = agent._format_feedback(lint, None, None)
    assert "lint" in fb.lower()
    assert "undefined variable" in fb

def test_format_audit_feedback():
    agent = A9DevAgent(enable_llm=False)
    audit = {"decision": "rejected", "issues": [
        {"severity": "error", "message": "SQL injection risk in line 42"}
    ]}
    fb = agent._format_audit_feedback(audit)
    assert "SQL injection" in fb

def test_detect_language_from_files():
    agent = A9DevAgent(enable_llm=False)
    assert agent._detect_language([{"path": "src/api.py"}]) == "python"
    assert agent._detect_language([{"path": "src/app.ts"}]) == "typescript"
    assert agent._detect_language([{"path": "src/main.go"}]) == "go"
    assert agent._detect_language([]) == "python"  # default
```

**验收标准**:
- [ ] prompt 包含 decisions 约束
- [ ] prompt 包含 spec 信息 (API endpoints + ERD tables)
- [ ] feedback 格式化 lint 错误为引擎可理解的文本
- [ ] feedback 格式化 audit issues 为引擎可理解的文本
- [ ] language 检测基于文件扩展名

---

# Phase 3: 协作层 (P1)

## 任务 3.1: worker_launcher 多实例支持

**描述**: 支持通过环境变量控制 A9 Worker 实例数

**文件**: `repos/agent-workers/worker_launcher.py`

**改动**:
```python
A9_WORKER_COUNT = int(os.environ.get("A9_WORKER_COUNT", "1"))
A9_CONCURRENT_PER_INSTANCE = int(os.environ.get("A9_CONCURRENT", "3"))

def register_agents():
    agents = [
        A1RequirementIntake(),
        # ...
    ]
    # 多个 A9 实例
    for i in range(A9_WORKER_COUNT):
        agents.append(A9DevAgent(instance_id=i, max_concurrent=A9_CONCURRENT_PER_INSTANCE))
    return agents
```

**测试方式**:
```python
def test_a9_worker_count_env():
    import os
    os.environ["A9_WORKER_COUNT"] = "3"
    # reload launcher, verify 3 A9 instances in registry
    ...

def test_a9_concurrent_from_env():
    os.environ["A9_CONCURRENT"] = "2"
    agent = A9DevAgent(instance_id=0, max_concurrent=int(os.environ.get("A9_CONCURRENT", "3")))
    assert agent._semaphore._value == 2
```

**验收标准**:
- [ ] `A9_WORKER_COUNT=3` → 3 个 A9DevAgent 实例
- [ ] 每个实例有不同的 `instance_id` (0, 1, 2)
- [ ] `A9_CONCURRENT` 控制 semaphore 初始值
- [ ] 默认值: A9_WORKER_COUNT=1, A9_CONCURRENT=3
- [ ] `worker_launcher.py` 启动时所有实例正确初始化 NATS

---

## 任务 3.2: A9DevAgent — 并发控制 (Semaphore)

**描述**: 用 asyncio.Semaphore 限制单进程并发任务数

**文件**: `repos/agent-workers/a9/a9_dev_agent.py`

**逻辑**:
```python
# _handle() 中:
async def _handle(self, msg):
    await self._semaphore.acquire()
    try:
        # ... 现有 _handle 逻辑 ...
        task = asyncio.create_task(self._handle_message(msg))
        self._active_tasks[req_id] = task
    finally:
        # semaphore 在 task 完成时释放
        task.add_done_callback(lambda t: self._release_task(req_id))
```

**测试方式**:
```python
async def test_semaphore_limits_concurrency():
    agent = A9DevAgent(enable_llm=False, max_concurrent=2)
    # 同时发 5 个任务
    # 验证同时运行的 <= 2
    assert len(agent._active_tasks) <= 2

async def test_semaphore_releases_on_completion():
    agent = A9DevAgent(enable_llm=False, max_concurrent=1)
    # 完成任务 → semaphore 释放 → 下一个任务可以开始
    ...
```

**验收标准**:
- [ ] semaphore acquire 阻塞直到有空位
- [ ] 任务完成 (成功或失败) 后 semaphore 被释放
- [ ] 异常不会导致 semaphore 泄漏
- [ ] `_active_tasks` 正确追踪进行中的任务

---

## 任务 3.3: CIBuildService (独立 NATS request-reply)

**描述**: 实现独立的 CI Build Service，与 A10 CICDAgent 分离

**文件**: `repos/agent-workers/ci_build_service.py` (新增)

**接口**: 同 spec 第 10 节 Audit-07 修复方案

**测试方式**:
```python
async def test_ci_build_service_request_reply():
    import nats
    nc = await nats.connect("nats://localhost:4222")
    service = CIBuildService()
    await service.init()
    
    try:
        reply = await nc.request("ci.build", json.dumps({
            "req_id": "test-001",
            "repo_path": "/tmp/test-repo",
            "dockerfile": "Dockerfile",
        }).encode(), timeout=10)
        result = json.loads(reply.data.decode())
        assert "success" in result or "error" in result
    except asyncio.TimeoutError:
        pass  # Docker 可能不可用，timeout 也是合法结果
    finally:
        await service.close()
        await nc.close()
```

**验收标准**:
- [ ] 订阅 NATS subject `ci.build`
- [ ] 收到 request 后执行 Docker build
- [ ] 结果通过 NATS reply 返回
- [ ] 超时 180s 返回 error
- [ ] Docker 不可用时返回 error (不崩溃)
- [ ] 不继承 BaseAgentWorker
- [ ] `worker_launcher.py` 中作为独立服务启动

---

## 任务 3.4: A9DevAgent — _verify_ci_build()

**描述**: 实现 A9 调用 CI Build Service 进行 Docker build 验证

**文件**: `repos/agent-workers/a9/a9_dev_agent.py`

**逻辑**:
```python
async def _verify_ci_build(self, worktree_path: Path, req_id: str) -> bool:
    try:
        reply = await self.nc.request("ci.build", json.dumps({...}).encode(), timeout=180)
        result = json.loads(reply.data.decode())
        return result.get("success", False)
    except Exception:
        return True  # CI 不可用时跳过
```

**测试方式**:
```python
async def test_verify_ci_build_unavailable():
    agent = A9DevAgent(enable_llm=False)
    # CI service 不可用 → 不阻断
    result = await agent._verify_ci_build(Path("/tmp/test"), "req-001")
    assert result == True  # 不可用时 skip

async def test_verify_ci_build_timeout():
    agent = A9DevAgent(enable_llm=False)
    # mock NATS request timeout → 不阻断
    ...
```

**验收标准**:
- [ ] CI service 可用 → 调用成功并返回 Docker build 结果
- [ ] CI service 不可用 → 返回 True (不阻断)
- [ ] 超时 → 返回 True (不阻断)
- [ ] 不阻塞主流程超过 180s

---

## 任务 3.5: _record_ambiguity + spec.feedback NATS 发布

**描述**: 实现 spec 模糊点记录和发布

**文件**: `repos/agent-workers/a9/a9_dev_agent.py`

**逻辑**: 同 spec 第 2.4 节 Type 1

**测试方式**:
```python
async def test_record_ambiguity_publishes_nats():
    agent = A9DevAgent(enable_llm=False)
    # spy on NATS publish
    agent._record_ambiguity("req-001", {
        "field": "auth_method", "chosen": "JWT",
        "reason": "Spec 未指定认证方式,使用 Gate 1 决策默认值",
    })
    # 验证 NATS 发布了 spec.feedback 消息
```

**验收标准**:
- [ ] 发布到 NATS subject `spec.feedback`
- [ ] 消息包含 req_id, agent_id, field, chosen, reason, timestamp
- [ ] 异常不阻塞主流程 (使用 `asyncio.create_task` 发布)

---

# Phase 4: 运维层 (P1)

## 任务 4.1: A9Metrics 接入

**描述**: 在 A9DevAgent.execute() 中接入 Prometheus 指标

**文件**: `repos/agent-workers/a9/a9_dev_agent.py` + `repos/agent-workers/a9/metrics.py`

**改动**:
1. 任务开始 → `a9_active_tasks.inc()`
2. 任务结束 → `a9_active_tasks.dec()`
3. 每轮迭代 → `a9_coder_iterations_total.inc()`
4. Auditor 审查 → `a9_auditor_reviews_total.inc()`
5. 完成 → `a9_cycle_time.observe(duration)`
6. escalate → `a9_escalations_total.inc()`

**测试方式**:
```python
async def test_metrics_incremented():
    agent = A9DevAgent(enable_llm=False)
    await agent.execute("req-001", full_context)
    # 验证 metrics 被调用 (通过 spy)
    ...
```

**验收标准**:
- [ ] a9_active_tasks 在 execute 开始 +1, 结束 -1
- [ ] a9_cycle_time 记录总耗时
- [ ] prometheus_client 未安装时不崩溃 (已有 mock 支持)

---

## 任务 4.2: 磁盘清理 Cron

**描述**: 清理过期的 worktree 残留

**文件**: `repos/agent-workers/a9/runtime.py`

**接口**:
```python
@staticmethod
async def cleanup_stale_worktrees(work_base: str = "/tmp/a9-runtimes", max_age_minutes: int = 120):
    """清理超过 max_age_minutes 的残留 worktree"""
```

**测试方式**:
```python
async def test_cleanup_stale():
    # 创建过期 worktree
    # 调用 cleanup_stale_worktrees(max_age_minutes=0)
    # 验证目录已删除
    ...
```

**验收标准**:
- [ ] 过期 worktree 被删除
- [ ] 活跃 worktree 不被删除
- [ ] 异常不抛 (记录 warning 继续)
- [ ] 可以在 worker_launcher 中作为定期任务或独立 cron job 运行

---

## 任务 4.3: Engine CLI Probe 集成测试

**描述**: 在实际环境中验证 CLI 探测逻辑

**文件**: `repos/agent-workers/a9/engine.py`

**测试方式**:
```bash
# 在实际环境中运行
python -c "
from a9.engine import A9CodingEngine
e = A9CodingEngine.__new__(A9CodingEngine)
config = e._probe_claude_cli()
print('Claude CLI config:', config)
print('Available engines:', e._detect_available())
"
```

**验收标准**:
- [ ] 在安装 Claude Code CLI 的环境中探测成功
- [ ] 在未安装的环境中正确返回 None
- [ ] `--help` 输出被正确解析
- [ ] 探测超时不阻塞启动 (>10s)

---

# Phase 5: 远期 (P2-P3)

## 任务 5.1: A9 Skills 文件

**描述**: 创建 3 个 `.skill.md` 文件

**文件**:
- `.ai-native/agents/A9/skills/dev-guidelines.skill.md`
- `.ai-native/agents/A9/skills/tdd-rules.skill.md`
- `.ai-native/agents/A9/skills/dual-brain.skill.md`

**依赖**: jap-plus-absorption-plan Phase 2 (SkillLoader 实现)

**内容**: 同 spec 第 12.2 节 G2

**验收标准**:
- [ ] 3 个文件存在且可被 SkillLoader 解析
- [ ] frontmatter 格式正确 (skill_id, applies_to, version, ttl_seconds)
- [ ] 内容覆盖: 编码规范 / TDD 规则 / 双脑架构

---

## 任务 5.2: A9ReviewAgent (Assisted Mode)

**描述**: 实现 IDE 辅助审查模式

**文件**: `repos/agent-workers/a9/a9_review_agent.py` (新增)

**接口**:
```python
class A9ReviewAgent(BaseAgentWorker):
    agent_id = "A9R"
    agent_type = "dev_review"
    # 接收 commit SHA → git pull → lint → test → Auditor.review → publish result
```

**依赖**: Phase 2 完成后的完整 AuditorModule

**验收标准**:
- [ ] 接收 `mode: "assisted"` 的 context
- [ ] 从 commit SHA 检出代码
- [ ] 运行 lint + test
- [ ] 返回审查结果

---

## 任务 5.3: IDE 内联反馈

**描述**: 审查结果通过 NATS → MC Backend SSE → IDE 插件

**依赖**: A9ReviewAgent 完成 + MC Backend SSE 支持 + IDE 插件

**范围**: 前端 + MC Backend + IDE 插件，不在 Agent Workers 内

**验收标准**:
- [ ] NATS `review.feedback` 消息格式正确
- [ ] MC Backend SSE 推送审查结果到 IDE

---

# 测试矩阵

## 单元测试清单

| 模块 | 测试文件 | 覆盖内容 |
|------|---------|---------|
| CoderModule | `tests/test_coder_module.py` | LLM 注入、mock fallback、文件生成、diff 构建 |
| AuditorModule | `tests/test_auditor_module.py` | LLM 注入、静态分析、语义审查、semaphore 并发 |
| A9Runtime | `tests/test_runtime.py` | setup/cleanup, lint, build, test, start_service, dataclasses |
| A9CodingEngine | `tests/test_engine.py` | CLI probe, Claude Code mode, API fallback, 引擎降级 |
| A9DevAgent | `tests/test_a9_dev_agent.py` | execute 完整流程, prompt 构建, feedback 格式化, 并发控制 |
| CIBuildService | `tests/test_ci_build_service.py` | NATS request-reply, Docker build, 错误处理 |

## 集成测试清单

| 场景 | 覆盖内容 |
|------|---------|
| A9 happy path | 一次迭代: engine → lint → build → test → smoke → auditor approve |
| A9 retry | lint 失败 1 次 → 修复 → 通过 |
| A9 max exhaust | 3 轮全部 auditor reject → escalate |
| A9 blocking | engine 返回 blocking_issue → 立即 BLOCKED |
| A9 CI unavailable | CI service 不可用 → 跳过 Docker build 验证 |
| A9 concurrent | 3 个并发任务 → semaphore 限制 + worktree 隔离 |
| Engine fallback | Claude CLI 不可用 → 降级 Anthropic API |
| Engine API fail | Anthropic API 返回 bad JSON → success=False |
| Runtime git | setup + cleanup + stale cleanup |
| Runtime test | pytest pass/fail/timeout 场景 |

---

# 风险与依赖矩阵

| 任务 | 外部依赖 | 风险 | 缓解 |
|------|---------|------|------|
| 0.5 | worker_launcher 现有 import 路径 | 低 — 一行改动 | 先做 0.1, 0.4 确保类存在 |
| 1.1-1.8 | git/pylint/eslint/pytest 在 PATH | 中 — 工具不可用 | 所有方法容错: 工具不可用时返回 "none" 或 "skipped" |
| 2.2 | Claude Code CLI 安装 + API key | 高 — CLI flag 未验证 | _probe_claude_cli 运行时探测; 自动降级 |
| 2.2 | NDJSON 解析 | 中 — event 格式未知 | 从 `git diff` 提取最终结果，不依赖 events |
| 2.6 | prepare_llm_context 可用 | 中 — 取决于 orch-spec T4 | Phase 2 用 mock context 开发; T4 完成后再对接 |
| 3.1 | NATS queue group | 低 — 已有基础设施 | 仅加环境变量 + for 循环 |
| 3.3 | Docker daemon | 中 — Docker 不可用 | CIBuildService 容错: Docker 不可用时返回 error 不崩溃 |
| 4.1 | prometheus_client 库 | 低 — 已有 mock | 未安装时用 mock 类 |
| 5.x | SkillLoader + MCPClient | 中 — 远景依赖 | Phase 5 标注为 P2+，不阻塞 P0/P1 |
