# A10 CI/CD Agent 改造规格书

> 版本: v1.0 | 日期: 2026-07-08 | 状态: 待评审

---

## 1. 背景与目标

### 1.1 现状问题

| # | 问题 | 严重度 |
|---|------|--------|
| P1 | `ci_agent.py` 引入不存在的 `event_bus` 模块，**import 直接崩溃** | 阻断 |
| P2 | 所有 Pipeline 步骤均为 `asyncio.sleep()` 模拟，**无实际 CI/CD 能力** | 阻断 |
| P3 | A9 完成编码后**不发布任何事件**，A10 无法感知代码变更 | 阻断 |
| P4 | A11 运行的是 Stub（15% 随机失败），**非真实测试 Agent** | 高 |
| P5 | A9 → A10 → A11 链路**完全未串联** | 高 |
| P6 | 无 Webhook 接收能力，外部 Git 平台无法触发 CI | 中 |
| P7 | 无 MCP 工具暴露，开发 Agent 无法在开发过程中调用 CI/CD | 中 |

### 1.2 用户需求

1. **Jenkins 集成**：A9 完成编码或 Git 代码合并触发 webhook 后，A10 执行 CI/CD 流程，可对接 Jenkins
2. **MCP 服务**：开发 Agent 开发过程中可调用 CI/CD，部署最新代码以验证功能
3. **外部平台扩展**：支持对接已有 CI/CD 平台（Jenkins、GitHub Actions、GitLab CI），也支持自实现 Docker 部署

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────┐
│                    Git Platforms                         │
│  GitHub/GitLab/Gitee  ──webhook──→  mc-backend          │
│                                       │                 │
│                                       ↓ NATS            │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐          │
│  │   A9     │    │   A10    │    │   A11    │          │
│  │ Dev Agent│───→│ CI/CD    │───→│ Auto Test│          │
│  │          │    │ Agent    │    │ Agent    │          │
│  └──────────┘    └────┬─────┘    └──────────┘          │
│       │               │                                │
│       │         ┌─────┼─────┬──────────┐               │
│       │         ↓     ↓     ↓          ↓               │
│       │     Docker Jenkins GitHub  GitLab              │
│       │     Adapter Adapter Actions  CI                │
│       │                                               │
│       └──────── MCP Gateway ←── Dev Agent              │
│                     │                                  │
│                     ↓ HTTP                             │
│               mc-backend                               │
│               /api/v1/mcp/trigger_pipeline             │
│                     │                                  │
│                     ↓ NATS                             │
│                  context.ready.ci_cd                   │
└─────────────────────────────────────────────────────────┘
```

### 2.1 核心设计原则

- **遵循 BaseAgentWorker 模式**：A10 继承 BaseAgentWorker，不使用不存在的 event_bus
- **Adapter 模式**：每种 CI/CD 平台是一个独立 Adapter，实现统一接口
- **Orchestrator 为唯一调度者**：Agent 不互相直接订阅，由 Orchestrator 观察 agent.result 后分发
- **已有能力复用**：DockerAdapter 直接复用 `ci_build_service.py` 的 NATS request-reply

---

## 3. 文件变更清单

### 3.1 新建文件

```
agent-workers/a10/
├── __init__.py                 # 导出 A10CiCdAgent, CiCdAdapter, StepResult
├── agent.py                    # A10CiCdAgent(BaseAgentWorker) — 核心 Agent
├── pipeline.py                 # PipelineExecutor — 步骤编排引擎
├── config_loader.py            # PipelineConfigLoader — YAML + Jinja2 渲染
├── adapters/
│   ├── __init__.py             # Adapter 注册表
│   ├── base.py                 # CiCdAdapter(ABC) + StepResult dataclass
│   ├── docker.py               # DockerAdapter — NATS ci.build 请求-响应
│   ├── jenkins.py              # JenkinsAdapter — REST API 触发 + 轮询
│   └── github_actions.py       # GitHubActionsAdapter — workflow dispatch API
└── templates/
    └── ci-pipeline.yaml.j2     # Jinja2 Pipeline 模板（从根 templates/ 移入）

mc-backend/api/
├── webhooks.py                 # Git webhook 接收器 (GitHub/GitLab/Gitee)
└── mcp_bridge.py               # MCP-to-NATS 桥接 (CI/CD 工具后端)
```

### 3.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `worker_launcher.py` | 导入改为 `from a10.agent import A10CiCdAgent`；A11 改为 `A11AutoTestAgent` |
| `a11_auto_test_agent.py` | `agent_type` 从 `"auto_test"` 改为 `"test_agent"` |
| `release_agent.py` | 删除 `from event_bus import ...`，`pipeline_passed/failed` 改用 `self.nc.publish()` |
| `mc-backend/main.py` | 挂载 `webhooks` 和 `mcp_bridge` 路由 |
| `mcp-gateway/server/tool_registry.go` | 新增 4 个 CI/CD 工具定义 |
| `mcp-gateway/server/tool_router.go` | 真实后端路由（dev_mode 检查） |

### 3.3 删除文件

| 文件 | 原因 |
|------|------|
| `ci_agent.py` | 由 `a10/agent.py` 替代 |
| `templates/ci-pipeline.yaml.j2` | 移动到 `a10/templates/` |

---

## 4. 核心组件详细设计

### 4.1 CiCdAdapter 抽象接口 (`a10/adapters/base.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class StepResult:
    step_name: str          # "build" | "test" | "lint" | "deploy"
    success: bool
    duration_ms: float
    logs: str = ""
    artifact_url: str = ""  # Docker image tag / Jenkins build URL / etc.
    error_message: str = ""

class CiCdAdapter(ABC):
    """所有 CI/CD 平台适配器的抽象接口"""

    @abstractmethod
    async def build(self, req_id: str, config: dict) -> StepResult: ...

    @abstractmethod
    async def test(self, req_id: str, config: dict) -> StepResult: ...

    @abstractmethod
    async def lint(self, req_id: str, config: dict) -> StepResult: ...

    @abstractmethod
    async def deploy(self, req_id: str, config: dict) -> StepResult: ...

    @abstractmethod
    async def get_status(self, build_id: str) -> dict: ...

    @abstractmethod
    async def get_logs(self, build_id: str) -> str: ...
```

**扩展方式**：新增平台只需在 `adapters/` 下新建文件，实现 `CiCdAdapter` 接口，在 `A10CiCdAgent.init()` 中注册即可。

### 4.2 A10CiCdAgent (`a10/agent.py`)

```python
class A10CiCdAgent(BaseAgentWorker):
    agent_id = "A10"
    agent_type = "ci_cd"  # NATS 订阅 subject: context.ready.ci_cd

    def __init__(self, nats_url="nats://localhost:4222", pipeline_config_path=None):
        super().__init__(agent_id="A10", agent_type="ci_cd", nats_url=nats_url)
        self._adapters: dict[str, CiCdAdapter] = {}
        self._config_loader = PipelineConfigLoader()
        self._pipeline_config = None

    async def init(self):
        await super().init()
        self._adapters["docker"] = DockerAdapter(self.nc)
        self._adapters["jenkins"] = JenkinsAdapter()
        self._adapters["github_actions"] = GitHubActionsAdapter()
        # 加载 Pipeline 配置
        config_path = os.environ.get("A10_PIPELINE_CONFIG", "")
        if config_path and os.path.exists(config_path):
            self._pipeline_config = self._config_loader.load(config_path)

    async def execute(self, req_id: str, context_package: dict) -> dict:
        platform = context_package.get("platform") or \
                   os.environ.get("A10_DEFAULT_PLATFORM", "docker")
        adapter = self._adapters.get(platform)
        if not adapter:
            return {"status": "error", "reason": f"Unknown platform: {platform}"}

        executor = PipelineExecutor(adapter, self._config_loader, agent=self)
        result = await executor.run(req_id, context_package)

        # 使用 BaseAgentWorker 内置方法发布结果
        await self.report_artifact(req_id, "pipeline_result", result)

        # 发布事件供 Orchestrator 观测
        event_subject = "pipeline.passed" if result["status"] == "passed" else "pipeline.failed"
        await self.nc.publish(event_subject, json.dumps({
            "req_id": req_id, "agent_id": "A10", "result": result
        }).encode())

        return result
```

**关键改变**：
- 不依赖不存在的 `event_bus`，只用 `self.nc.publish()`
- `report_artifact()` / `report_status()` 来自 BaseAgentWorker
- Adapter 按 `platform` 参数动态选择

### 4.3 PipelineExecutor (`a10/pipeline.py`)

```python
class PipelineExecutor:
    """按 Pipeline 配置顺序执行各步骤，首步失败即停止"""

    def __init__(self, adapter: CiCdAdapter, config_loader, agent: BaseAgentWorker):
        self.adapter = adapter
        self.config_loader = config_loader
        self.agent = agent

    async def run(self, req_id: str, context: dict) -> dict:
        pipeline = self.agent._pipeline_config or {}
        steps_order = ["build", "test", "lint", "deploy"]
        step_results = []

        for step_name in steps_order:
            cfg = pipeline.get(step_name, {})
            if not cfg.get("enabled", True):  # 默认启用
                continue

            await self.agent.report_status(req_id, "running", f"[{step_name.upper()}] Running...")
            result = await getattr(self.adapter, step_name)(req_id, cfg)
            step_results.append(result)

            if not result.success:
                await self._fail_pipeline(req_id, step_name, result, step_results)
                return {"status": "failed", "failed_step": step_name,
                        "error": result.error_message, "steps": step_results}

        await self.agent.report_status(req_id, "completed", "Pipeline passed")
        return {"status": "passed", "steps": step_results,
                "artifact_url": step_results[-1].artifact_url if step_results else ""}
```

### 4.4 DockerAdapter (`a10/adapters/docker.py`)

```python
class DockerAdapter(CiCdAdapter):
    """通过 NATS request-reply 调用 ci_build_service.py 执行 Docker 构建"""

    def __init__(self, nc):
        self.nc = nc  # NATS 连接（共享 BaseAgentWorker 的连接）

    async def build(self, req_id: str, config: dict) -> StepResult:
        start = time.time()
        try:
            reply = await asyncio.wait_for(
                self.nc.request("ci.build", json.dumps({
                    "req_id": req_id,
                    "repo_path": config.get("repo_path", ""),
                    "dockerfile": config.get("dockerfile", "Dockerfile"),
                    "tag": config.get("tag", f"a10-{req_id}"),
                }).encode(), timeout=300),
                timeout=310,
            )
            data = json.loads(reply.data.decode())
            return StepResult(
                step_name="docker_build",
                success=data.get("success", False),
                duration_ms=(time.time() - start) * 1000,
                logs=data.get("logs", ""),
                artifact_url=f"docker://{data.get('image_tag', '')}",
                error_message=data.get("error", ""),
            )
        except asyncio.TimeoutError:
            return StepResult("docker_build", False, 310000,
                              error_message="Docker build timeout (5 min)")

    async def deploy(self, req_id: str, config: dict) -> StepResult:
        # 自实现：Docker run / docker-compose up / kubectl apply
        tag = config.get("tag", f"a10-{req_id}")
        port = config.get("port", "8080")
        # ... subprocess 执行 docker run ...
```

**复用说明**：`ci_build_service.py` 保持不变，DockerAdapter 通过 NATS request-reply 调用它，与 A9 的 `_verify_ci_build()` 使用完全相同的模式。

### 4.5 JenkinsAdapter (`a10/adapters/jenkins.py`)

```python
class JenkinsAdapter(CiCdAdapter):
    """通过 Jenkins REST API 触发 Job 并轮询状态"""

    def __init__(self):
        self.base_url = os.environ.get("JENKINS_URL", "")
        self.username = os.environ.get("JENKINS_USER", "")
        self.token = os.environ.get("JENKINS_TOKEN", "")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            auth = base64.b64encode(f"{self.username}:{self.token}".encode()).decode()
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Basic {auth}"},
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def build(self, req_id: str, config: dict) -> StepResult:
        job_name = config.get("jenkins_job", "a10-build")
        params = config.get("params", {})
        # POST /job/{job}/buildWithParameters → 获取 build number
        # 轮询 GET /job/{job}/{build}/api/json → 获取 status
        # 返回 StepResult

    async def get_status(self, build_id: str) -> dict:
        # GET /job/{job}/{build}/api/json
        ...

    async def get_logs(self, build_id: str) -> str:
        # GET /job/{job}/{build}/consoleText
        ...
```

### 4.6 GitHubActionsAdapter (`a10/adapters/github_actions.py`)

```python
class GitHubActionsAdapter(CiCdAdapter):
    """通过 GitHub REST API 触发 workflow dispatch 并轮询"""

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.owner = os.environ.get("GITHUB_OWNER", "")
        self.repo = os.environ.get("GITHUB_REPO", "")

    async def build(self, req_id: str, config: dict) -> StepResult:
        workflow_id = config.get("workflow_id", "ci.yml")
        ref = config.get("branch", "main")
        # POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches
        # 轮询 GET /repos/{owner}/{repo}/actions/runs?event=workflow_dispatch
        # 返回 StepResult
```

---

## 5. Webhook 接收器 (`mc-backend/api/webhooks.py`)

### 5.1 端点设计

| 端点 | 平台 | 签名验证 | 触发事件 |
|------|------|----------|----------|
| `POST /api/v1/webhooks/github` | GitHub | HMAC-SHA256 (`X-Hub-Signature-256`) | `push`, `pull_request` |
| `POST /api/v1/webhooks/gitlab` | GitLab | Header Token (`X-Gitlab-Token`) | `Push Hook`, `Merge Request Hook` |
| `POST /api/v1/webhooks/gitee` | Gitee | Header Token / Password | `Push Hook` |

### 5.2 处理流程

```
Webhook POST → 验证签名 → 解析平台特定 Payload → 标准化为内部 envelope → NATS publish
```

标准化 envelope:
```python
{
    "event_id": "webhook-{uuid}",
    "event_type": "code.pushed",
    "req_id": req_id,
    "payload": {
        "repo_url": "...",
        "branch": "main",
        "commit_sha": "abc123",
        "pusher": "username",
        "files_changed": ["..."],
        "platform": "github",
        "source": "webhook"
    }
}
# 发布到: context.ready.ci_cd
```

---

## 6. MCP 集成 (`mc-backend/api/mcp_bridge.py`)

### 6.1 新增 MCP 工具

| 工具名 | 描述 | 关键参数 |
|--------|------|----------|
| `trigger_pipeline` | 触发 CI/CD Pipeline | `repo_url`, `branch`, `platform`, `pipeline` |
| `check_build_status` | 查询构建状态 | `build_id`, `platform` |
| `get_build_logs` | 获取构建日志 | `build_id`, `platform` |
| `deploy_service` | 部署服务到目标环境 | `image_tag`, `environment`, `platform` |

### 6.2 桥接端点

```
POST /api/v1/mcp/trigger_pipeline     → NATS request context.ready.ci_cd → 等待 agent.result.A10
POST /api/v1/mcp/check_build_status   → 查询 A10 Adapter 的状态接口
POST /api/v1/mcp/get_build_logs       → 查询 A10 Adapter 的日志接口
POST /api/v1/mcp/deploy_service       → NATS publish context.ready.ci_cd (deploy 模式)
```

### 6.3 Go MCP Gateway 变更

**`tool_registry.go`**：在 `registerAll()` 中追加 4 个 CI/CD 工具定义。输入 schema 中 `platform` 字段支持 `docker`、`jenkins`、`github-actions`、`gitlab-ci`。

**`tool_router.go`**：`Route()` 方法增加真实后端路由。当 `config.DevMode == false` 时，根据工具名查 `BackendServices` 配置，HTTP 转发到 `mc-backend/api/v1/mcp/` 对应端点。

### 6.4 调用链路

```
Dev Agent (A9) → MCP Client → POST /tools/call (JWT Auth)
  → Go MCP Gateway (验证 JWT, 路由)
  → POST http://mc-backend:8000/api/v1/mcp/trigger_pipeline
  → NATS publish context.ready.ci_cd
  → A10 CiCdAgent.execute()
  → NATS reply agent.result.A10
  → mc-backend 返回结果 → Go Gateway → Dev Agent
```

---

## 7. Pipeline 事件串联

### 7.1 A9 → A10 → A11 完整链路

```
1. A9 完成编码
   → A9 在 execute() 末尾 publish "code.pushed" 到 NATS
   → A9 report_artifact("code_diff", ...)

2. Orchestrator 观测到 agent.result.A9 → 分发 context.ready.ci_cd

3. A10 执行 Pipeline
   → DockerAdapter 调用 ci_build_service (真实 docker build)
   → 或 JenkinsAdapter 触发 Jenkins Job 并轮询
   → 成功: publish "pipeline.passed" + report_artifact("pipeline_result", ...)
   → 失败: publish "pipeline.failed"

4. Orchestrator 观测到 agent.result.A10 → 分发 context.ready.test_agent

5. A11 (真实 A11AutoTestAgent) 执行测试
   → VisAgent HTTP API 执行视觉测试
   → mutation testing (mutmut/Stryker)
   → 覆盖率测量
   → publish "test.tdd_complete" + report_artifact("test_report", ...)
```

### 7.2 A11 Stub → 真实 Agent 切换

**`worker_launcher.py`**:
```python
# 之前
from a11_test_agent_stub import A11TestAgentStub
# ...
A11TestAgentStub(),

# 之后
from a11_auto_test_agent import A11AutoTestAgent
# ...
A11AutoTestAgent(),
```

**`a11_auto_test_agent.py`**: 将 `AGENT_TYPE = "auto_test"` 改为 `"test_agent"`，保持 NATS subject 为 `context.ready.test_agent`，与 Stub 兼容。

---

## 8. release_agent.py 修复

删除第 21 行 `from event_bus import EventPublisher, EventSubscriber`。

将 `self._publisher.pipeline_passed(...)` 和 `self._publisher.pipeline_failed(...)` 替换为：
```python
await self.nc.publish("pipeline.passed", json.dumps({...}).encode())
```

与 A10 发布的 `pipeline.passed`/`pipeline.failed` 事件格式对齐。

---

## 9. 实施阶段

| 阶段 | 内容 | 文件数 |
|------|------|--------|
| **Phase 1: 基础** | `base.py`, `docker.py`, `config_loader.py`, `pipeline.py`, `agent.py`, `__init__.py` | 6 新建 |
| **Phase 1: 修复** | `worker_launcher.py`, `a11_auto_test_agent.py`, `release_agent.py` | 3 修改 |
| **Phase 1: 清理** | 删除 `ci_agent.py`, 移动模板 | 2 |
| **Phase 2: 扩展** | `jenkins.py`, `github_actions.py` | 2 新建 |
| **Phase 3: Webhook** | `mc-backend/api/webhooks.py`, `mc-backend/main.py` | 1 新建 + 1 修改 |
| **Phase 3: MCP** | `mc-backend/api/mcp_bridge.py`, `tool_registry.go`, `tool_router.go` | 1 新建 + 2 修改 |
| **Phase 4: 串联** | A9 `code.pushed` 发布 + A10 `pipeline.passed` 发布 | 2 修改 |

---

## 10. 环境变量

```bash
# /etc/ai-native.env 新增配置

# A10 Pipeline
A10_PIPELINE_CONFIG=/opt/ai-native/config/pipeline.yaml
A10_DEFAULT_PLATFORM=docker

# Jenkins (可选)
JENKINS_URL=http://jenkins.internal:8080
JENKINS_USER=ai-agent
JENKINS_TOKEN=<jenkins-api-token>

# GitHub Actions (可选)
GITHUB_TOKEN=<github-pat>
GITHUB_OWNER=ai-native
GITHUB_REPO=app

# Webhook
WEBHOOK_SECRET=<shared-hmac-secret>
```

---

## 11. 验证 Checklist

- [ ] `python3 -c "from a10.agent import A10CiCdAgent"` — 无 ImportError
- [ ] `python3 worker_launcher.py` — A10 注册成功，日志显示 `Registered: A10 -> A10_ci_cd`
- [ ] A9 完成编码后日志显示 `Published code.pushed`
- [ ] A10 接收 `context.ready.ci_cd` 后执行 Docker 构建
- [ ] DockerAdapter 成功调用 `ci_build_service.py`
- [ ] A10 完成后发布 `pipeline.passed`
- [ ] A11 收到 `context.ready.test_agent` 后执行真实 VisAgent 测试
- [ ] `release_agent.py` 无 event_bus 导入错误
- [ ] Webhook: `curl` POST 到 `/api/v1/webhooks/github` → A10 被触发
- [ ] MCP: Go Gateway 可路由 CI/CD 工具调用到 mc-backend

---

## 12. 依赖关系

### 12.1 Python 依赖 (新增)

```txt
jinja2>=3.1.0        # Pipeline 配置模板渲染
```

已有依赖（无需新增）：
- `pyyaml>=6.0.1` — YAML 解析
- `httpx>=0.27.0` — HTTP 客户端（Jenkins/GitHub API）
- `nats-py>=2.10.0` — NATS 连接

### 12.2 Go 依赖 (mcp-gateway)

无新增依赖，仅修改已有代码。

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Jenkins/GitHub API 认证失败 | 外部平台 Adapter 不可用 | 优雅降级到 DockerAdapter，记录错误日志 |
| Webhook 签名验证失败 | 拒绝非法请求 | 返回 403，记录详细日志用于调试 |
| A10 执行超时 | Pipeline 卡住 | 每个 Adapter 设置独立超时（5-10 min），超时返回失败 |
| A11 真实 Agent VisAgent 不可用 | 测试失败 | A11 内已有 mock fallback，优雅降级 |
| MCP Gateway Go 服务重启 | Dev Agent 调用中断 | 客户端重试机制（3 次，指数退避） |

---

## 14. 后续演进

### 14.1 Phase 5: 更多平台适配器

- `GitLabCIAdapter` — GitLab CI/CD API
- `ArgoCD Adapter` — GitOps 部署
- `AzureDevOpsAdapter` — Azure Pipelines

### 14.2 Phase 6: 可观测性增强

- Prometheus 指标：pipeline_duration_seconds, pipeline_failure_rate
- OpenTelemetry Trace：端到端 Pipeline 追踪
- 构建日志持久化到对象存储（S3/MinIO）

### 14.3 Phase 7: 智能调度

- Pipeline 优先级队列
- 资源感知调度（CPU/内存/并发数）
- 失败自动重试（exponential backoff）

---

**审批流程**：
1. 技术架构师评审 — 架构合理性
2. A9/A11 负责人评审 — 集成点正确性
3. DevOps 评审 — Jenkins/外部平台可行性
4. 安全评审 — Webhook 签名、MCP JWT 认证

**预估工作量**：
- Phase 1: 3-4 人日（基础 + 修复 + 清理）
- Phase 2: 2-3 人日（外部平台适配器）
- Phase 3: 3-4 人日（Webhook + MCP 集成 + Go 代码修改）
- Phase 4: 1-2 人日（事件串联 + 端到端测试）
- **总计**: 9-13 人日

---

**附录**：
- [A9 Dev Agent 部署文档](../../deploy/a9-dev-agent-deployment.md)
- [BaseAgentWorker 架构说明](../系统架构/BaseAgentWorker架构.md)
- [NATS 事件总线设计](../系统架构/NATS事件总线.md)
- [MCP Gateway API 文档](../../mcp-gateway/README.md)
