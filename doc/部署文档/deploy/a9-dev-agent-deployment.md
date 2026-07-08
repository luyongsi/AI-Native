# A9 Dev Agent — 109 环境部署文档

> 部署日期: 2026-07-07
> 部署目标: 172.27.78.109

---

## 1. 环境信息

| 项目 | 值 |
|---|---|
| 服务器 | `root@172.27.78.109` |
| OS | Ubuntu 24.04 LTS |
| Python | 3.12.3 |
| Node.js | v22.23.1 |
| Claude Code CLI | v2.1.195 (`/usr/bin/claude`) |
| Git | 2.43.0 |
| Docker | 29.6.1 |
| NATS | Docker `ai-nats:2.10-alpine` |
| Temporal | Docker `ai-temporal:1.24` |
| 部署目录 | `/opt/ai-native/repos/agent-workers/` |

## 2. 部署步骤

```bash
# Step 1: 安装依赖
pip3 install --break-system-packages pytest pylint

# Step 2: 创建工作目录
mkdir -p /tmp/a9-runtimes

# Step 3: 同步 A9 代码到 109
scp a9/runtime.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/a9/
scp a9/engine.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/a9/
scp a9/a9_dev_agent.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/a9/
scp a9/coder.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/a9/
scp a9/auditor.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/a9/
scp a9/__init__.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/a9/
scp ci_build_service.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/
scp worker_launcher.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/

# Step 4: 删除废弃的旧文件
ssh root@172.27.78.109 "rm -f /opt/ai-native/repos/agent-workers/a9_dev_agent_stub.py"
ssh root@172.27.78.109 "rm -f /opt/ai-native/repos/agent-workers/a9_claude_code_bridge.py"

# Step 5: 验证文件没有残留引用
ssh root@172.27.78.109 "grep -r 'a9_dev_agent_stub\|a9_claude_code_bridge' /opt/ai-native/repos/agent-workers/*.py || echo 'NO REFERENCES'"

# Step 6: 验证语法
ssh root@172.27.78.109 "cd /opt/ai-native/repos/agent-workers && python3 -c '
import ast
for f in [\"a9/a9_dev_agent.py\",\"a9/runtime.py\",\"a9/engine.py\",\"a9/coder.py\",\"a9/auditor.py\",\"ci_build_service.py\",\"worker_launcher.py\"]:
    ast.parse(open(f,\"rb\").read().decode(\"utf-8\"))
    print(f\"  {f}: OK\")
print(\"ALL OK\")
'"

# Step 7: 重启 worker_launcher
ssh root@172.27.78.109 "kill \$(pgrep -f worker_launcher.py) 2>/dev/null; sleep 3"
ssh root@172.27.78.109 "cd /opt/ai-native/repos/agent-workers && nohup python3 worker_launcher.py > /var/log/ai-native-workers.log 2>&1 &"

# Step 8: 等待启动后验证
sleep 10
ssh root@172.27.78.109 "grep 'A9.*Registered\|A9.*Subscribed' /var/log/ai-native-workers.log | tail -3"
```

## 3. Claude Code CLI 兼容性对照

109 实际的 `claude --help` 输出与 engine.py 的对照：

| engine.py 使用的 flag | 109 实际 | 状态 |
|---|---|---|
| `--print` | `-p` / `--print` | ✅ |
| `--output-format stream-json` | `--output-format stream-json` | ✅ |
| `--verbose` | `--verbose` | ✅ (部署时新增) |
| `--add-dir` | `--add-dir` | ✅ |
| `--allowedTools` | `--allowedTools` | ✅ |
| `--max-turns` | **不存在** | ❌ (已从 engine.py 移除) |
| `--no-interactive` | **不存在** | ❌ (已从 engine.py 移除) |
| `--cwd` | **不存在** | ❌ (改为 `--add-dir`) |

**Claude CLI 关键发现**:
- `--output-format stream-json` 需要同时使用 `--verbose`，否则报错
- 非交互模式通过 `--print` 自然启用，无需单独的 `--no-interactive` flag
- `--allowed-tools` 也可用 (兼容两种写法)
- CLI 需要有效的 Anthropic API key；109 使用的是 DeepSeek 兼容 key，导致 403 认证失败 → engine.py 已实现自动降级到 Anthropic API fallback
- `--bare` flag (最小模式) 可减少启动时间，未来可考虑启用

## 4. 环境变量配置

`/etc/ai-native.env` 中的关键配置：

```bash
# LLM API Keys
DEEPSEEK_API_KEY=sk-suHjSP2DOgyyp7NHSrLVPQf3nVaJrYsivYtyeEJdsaOER1X9
ANTHROPIC_API_KEY=sk-suHjSP2DOgyyp7NHSrLVPQf3nVaJrYsivYtyeEJdsaOER1X9

# Service URLs
NATS_URL=nats://localhost:4222
DATABASE_URL=postgresql://ai_native:ai_native_dev@localhost:5432/ai_native

# Claude Code
CLAUDE_CODE_ENABLED=true
```

注意：`ANTHROPIC_API_KEY` 与 `DEEPSEEK_API_KEY` 使用相同的 key 值，但 Claude Code CLI 的 Anthropic 官方 API 不接受此 key（返回 403）。engine.py 已实现自动探测失败后降级到 Anthropic API fallback（通过 base_worker.py 的 `call_llm` → `LLMProviderManager` → DeepSeek uniapi）。

## 5. 运行时部署状态

### 5.1 服务进程

| 服务 | 状态 | 日志 |
|---|---|---|
| worker_launcher | 运行中 | `/var/log/ai-native-workers.log` |
| A9 Dev Agent | 已注册 ✅ | `Registered: A9 -> A9_dev_agent` |
| A9 NATS 订阅 | 已订阅 ✅ | `Subscribed to NATS subject: context.ready.dev_agent` |
| CI Build Service | 未启动 (Docker daemon 可用) | 按需执行 `python3 ci_build_service.py &` |

### 5.2 文件部署清单

```
/opt/ai-native/repos/agent-workers/a9/
├── __init__.py              ✅ 导出 A9DevAgent, CoderModule, AuditorModule 等
├── a9_dev_agent.py          ✅ 主流程: Runtime + Engine + Auditor 完整流水线 (537 行)
├── runtime.py               ✅ 隔离环境: git/lint/build/test/service/dataclasses (694 行)
├── engine.py                ✅ 三引擎: Claude Code CLI / Codex CLI / Anthropic API (525 行, 含 fallback)
├── coder.py                 ✅ LLM 注入 fallback 代码生成器 (422 行)
├── auditor.py               ✅ 静态分析 + LLM 语义审查 + 并发控制 (439 行)
├── metrics.py               ✅ Prometheus 指标
├── static_analyzer.py       ✅ pylint/eslint 封装
├── workflow.py              ✅ Temporal workflow 定义

/opt/ai-native/repos/agent-workers/
├── worker_launcher.py       ✅ 多实例 A9 (A9_WORKER_COUNT 环境变量)
├── ci_build_service.py      ✅ 独立 NATS request-reply CI 服务 (129 行)
└── (已删除) a9_dev_agent_stub.py, a9_claude_code_bridge.py

/tmp/a9-runtimes/            ✅ A9 worktree 工作目录
/opt/ai-native/logs/llm_calls/ ✅ LLM 调用日志 (A9 数据源)
```

### 5.3 新增服务：LLM 调用日志查看器

A9 生成并部署的 Web 日志查看器：

```
地址: http://172.27.78.109:8400/
代码: /opt/ai-native/tools/llm-viewer/main.py
日志: /var/log/llm-viewer.log
进程: python3 main.py (port 8400)

功能:
  - 左侧: 按 req_id 分组浏览
  - 右侧表格: agent_id / task_type / model / status / duration / tokens / timestamp
  - 筛选: agent 下拉 + task_type 输入 + status 下拉
  - 点击行展开完整 prompt/response (JSON 自动格式化)
  - 暗色主题, 等宽字体, 响应式布局
```

### 5.4 A9 已有的 LLM 调用记录

A9 在 109 上真实执行了代码生成 (code_generation)，通过 Anthropic API fallback 路径：

```
16 A9 code_generation calls, all success
平均耗时: ~75s/call
```

## 6. 触发 A9 开发任务

通过 NATS 手动 dispatch 触发 A9：

```python
import json, asyncio, nats, uuid

async def dispatch():
    nc = await nats.connect('nats://localhost:4222')
    msg = {
        'event_id': f'dispatch-a9-{uuid.uuid4().hex[:8]}',
        'event_type': 'context.ready',
        'req_id': 'my-dev-task',
        'agent_id': 'A9',
        'payload': {
            'req_id': 'my-dev-task',
            'workflow_id': 'manual',
            'title': '任务标题',
            'note': '任务描述',
            'decisions': {},
            'openapi_hint': {'endpoints': ['/api/xxx'], 'info': {'title': 'API'}},
            'erd_hint': {'tables': []},
            'dag_hint': {'nodes': [{'id': 't1', 'title': '任务', 'type': 'backend'}]},
            'environment_context': {'project': {'repo_url': '', 'branch': 'main'}}
        }
    }
    await nc.publish('context.ready.dev_agent', json.dumps(msg, ensure_ascii=False).encode())
    await nc.close()

asyncio.run(dispatch())
```

或使用部署在 109 上的脚本：

```bash
ssh root@172.27.78.109 "cat > /tmp/a9_task.json << 'EOF'
{...JSON payload...}
EOF
python3 -c \"
import json,asyncio,nats
nc = asyncio.run(nats.connect('nats://localhost:4222'))
asyncio.run(nc.publish('context.ready.dev_agent', open('/tmp/a9_task.json','rb').read()))
asyncio.run(nc.close())
\""
```

## 7. 运维命令

```bash
# 查看 A9 运行状态
ssh root@172.27.78.109 "grep 'A9' /var/log/ai-native-workers.log | tail -20"

# 查看 A9 引擎执行
ssh root@172.27.78.109 "grep 'Engine\|claude\|API' /var/log/ai-native-workers.log | tail -20"

# 清理过期 worktree (>2h)
ssh root@172.27.78.109 "find /tmp/a9-runtimes -maxdepth 1 -name 'wt-a9rt-*' -mmin +120 -exec rm -rf {} \;"

# 重启 worker_launcher
ssh root@172.27.78.109 "kill \$(pgrep -f worker_launcher.py); sleep 3; cd /opt/ai-native/repos/agent-workers && nohup python3 worker_launcher.py > /var/log/ai-native-workers.log 2>&1 &"

# 多实例部署 (2 个 Worker × 3 并发)
ssh root@172.27.78.109 "A9_WORKER_COUNT=2 A9_CONCURRENT=3 cd /opt/ai-native/repos/agent-workers && python3 worker_launcher.py"

# 查看 LLM 日志
http://172.27.78.109:8400/

# 启动 CI Build Service
ssh root@172.27.78.109 "cd /opt/ai-native/repos/agent-workers && nohup python3 ci_build_service.py > /var/log/ci-build.log 2>&1 &"
```

## 8. 已知限制

| 限制 | 影响 | 缓解 |
|---|---|---|
| Claude Code CLI API key 不兼容 (DeepSeek key) | CLI 模式不可用 | 自动降级到 Anthropic API fallback |
| API fallback JSON parse 偶发失败 | 截断的 JSON 无法解析 | 已添加截断容错 + 3 轮重试 → escalate |
| Temporal namespace `default` 不存在 | Agent 以 standalone 模式运行 | 不影响 Agent 功能，NATS 队列正常运行 |
| 无 pytest/eslint/go 工具 | lint/build 自动跳过 | 所有方法返回 "tool not installed" 而非崩溃 |
| `/tmp/a9-runtimes` 并发极限 | 3 个 worktree × 500MB ≈ 1.5GB | Semaphore 控制在 3 |
