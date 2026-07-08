# AI Native 研发协同系统 — 部署与运维指南

> 写给新接手项目的开发者：从零开始在 109 服务器上部署并运行完整系统。

---

## 一、系统概览

```
┌─────────────────────────────────────────────────────────┐
│                    109 服务器 (172.27.78.109)            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │ Frontend │  │ MC Backend   │  │ Agent Workers   │   │
│  │ Next.js  │  │ FastAPI      │  │ (16 Agents +    │   │
│  │ :3000    │  │ :8000        │  │  NATS Bridge)   │   │
│  └──────────┘  └──────┬───────┘  └────────┬────────┘   │
│                       │                    │            │
│              ┌────────┼────────────────────┼──┐         │
│              │        ▼                    ▼  │         │
│              │   ┌─────────┐    ┌──────────┐  │         │
│              │   │  NATS   │◄──►│ Temporal │  │         │
│  Docker      │   │ :4222   │    │ :7233    │  │         │
│  Containers  │   └─────────┘    └──────────┘  │         │
│              │                                 │         │
│              │  ┌──────────┐  ┌────────────┐  │         │
│              │  │PostgreSQL│  │ Orchestrator│  │         │
│              │  │ :5432    │  │ Worker      │  │         │
│              │  └──────────┘  └────────────┘  │         │
│              └─────────────────────────────────┘         │
└─────────────────────────────────────────────────────────┘
```

---

## 二、首次部署（从零开始）

### 2.1 前置条件

```bash
# 确认 Python 版本 >= 3.12
python3 --version

# 确认 pip3 可用
pip3 --version

# 确认 Docker 已安装并运行
docker --version
docker ps
```

### 2.2 代码部署

```bash
# 克隆或同步代码到 109 服务器
# 代码树结构:
# /opt/ai-native/
#   repos/
#     mc-backend/        # FastAPI 后端
#     agent-workers/     # 16 个 Agent + NATS Bridge
#     orchestrator/      # Temporal Workflow
#     llm-provider/      # LLM 抽象层
#     event-bus/         # NATS 工具
#     gate-state-machine/ # Gate 审批状态机
#     infra/             # Docker Compose
#     tests/             # 测试脚本
#   frontend/            # Next.js 前端
#   data/                # 持久化数据

# ⚠️ 注意: 服务器上不需要 node_modules 和 Python .pyc/__pycache__
# scp 前先清理:
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find . -name '*.pyc' -delete 2>/dev/null
```

### 2.3 安装 llm-provider

```bash
cd /opt/ai-native/repos/llm-provider

# 方式1: .pth 文件 (推荐, 不依赖 pip/setuptools)
echo '/opt/ai-native/repos/llm-provider' > /usr/local/lib/python3.12/dist-packages/llm_provider.pth

# 验证
python3 -c 'from llm_provider.audit import get_auditor; print("OK")'
```

### 2.4 环境变量

创建 `/etc/ai-native.env`：

```bash
# LLM API Keys
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Service URLs
MC_BACKEND_URL=http://localhost:8000
NATS_URL=nats://localhost:4222
DATABASE_URL=postgresql://ai_native:ai_native_dev@localhost:5432/ai_native
REDIS_URL=redis://localhost:6379

# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=ai-native
TEMPORAL_TASK_QUEUE=orchestrator-task-queue

# LLM Audit Log path
LLM_AUDIT_LOG=/opt/ai-native/logs/llm_audit.jsonl
```

### 2.5 启动 Docker 基础设施

```bash
cd /opt/ai-native/repos/infra
docker compose up -d

# 确认所有容器运行中
docker ps --format 'table {{.Names}}\t{{.Status}}'
# 预期: ai-postgres, ai-nats, ai-temporal, ai-redis (以及其他监控容器)
```

### 2.6 创建 NATS Stream（首次必须）

```bash
python3 -c "
import asyncio, nats
async def main():
    nc = await nats.connect('nats://localhost:4222')
    js = nc.jetstream()
    await js.add_stream(
        name='AI_NATIVE_EVENTS',
        subjects=['context.ready.>','agent.result.>','agent.status.changed.>','orchestrator.>'],
        retention='interest',
        storage='file',
    )
    print('NATS stream created')
    await nc.close()
asyncio.run(main())
"
```

### 2.7 创建 systemd Service

```bash
# 复制 service 文件到 systemd 目录
cp /opt/ai-native/deploy/*.service /etc/systemd/system/

# 重新加载 systemd
systemctl daemon-reload
```

Service 文件内容见 [附录 A](#附录-a-systemd-service-文件)。

### 2.8 启动所有服务

```bash
# 按顺序启动
systemctl start ai-native-backend    # MC Backend API (:8000)
systemctl start ai-native-frontend   # Next.js Frontend (:3000)
systemctl start ai-native-agents     # Agent Workers (NATS 订阅)
systemctl start ai-native-orchestrator # Temporal Worker

# 设置开机自启
systemctl enable ai-native-backend ai-native-frontend ai-native-agents ai-native-orchestrator

# 确认所有服务正常
systemctl status ai-native-backend ai-native-frontend ai-native-agents ai-native-orchestrator
```

---

## 三、日常运维

### 3.1 重启单个服务

```bash
# Agent Workers (改动 agent-workers 代码后)
systemctl restart ai-native-agents

# Orchestrator (改动 workflow/activity 代码后)
systemctl restart ai-native-orchestrator

# MC Backend (改动 API 代码后)
systemctl restart ai-native-backend
```

### 3.2 部署代码变更

```bash
# 从本地推送文件到 109
scp local_file.py root@172.27.78.109:/opt/ai-native/repos/agent-workers/

# 清除 Python 缓存（重要！）
ssh root@172.27.78.109 "find /opt/ai-native/repos -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null"

# 如果有 worker_launcher 或 base_worker 变化，重启 agents
ssh root@172.27.78.109 "systemctl restart ai-native-agents"

# 验证启动成功
ssh root@172.27.78.109 "strings /var/log/agent-workers.log | grep 'LLM provider initialized' | head -1"
```

### 3.3 查看日志

```bash
# Agent Workers (含 LLM 审计 stdout)
tail -f /var/log/agent-workers.log

# LLM 审计 JSONL (结构化数据)
tail -f /opt/ai-native/logs/llm_audit.jsonl | python3 -m json.tool

# Orchestrator Workflow 执行
tail -f /var/log/orchestrator-worker.log

# 查看特定需求的执行过程
strings /var/log/agent-workers.log | grep 'req=<req_id>'
```

### 3.4 查看 Temporal UI

浏览器打开: **http://172.27.78.109:8088**

- Namespace: `ai-native`
- 可查看所有 Workflow 的执行历史、Activity 输入/输出、Signal 和 Query

### 3.5 LLM 审计数据分析

```bash
# 统计当日每个 agent 的 token 消耗
cat /opt/ai-native/logs/llm_audit.jsonl | python3 -c "
import sys, json
agents = {}
for line in sys.stdin:
    r = json.loads(line)
    if r.get('status') == 'success':
        a = r.get('agent_id','?')
        if a not in agents: agents[a] = {'calls':0,'tokens':0}
        agents[a]['calls'] += 1
        agents[a]['tokens'] += r.get('total_tokens',0)
for a in sorted(agents.keys()):
    print(f'{a}: {agents[a][\"calls\"]} calls, {agents[a][\"tokens\"]} tokens')
"

# 查看所有失败的调用
cat /opt/ai-native/logs/llm_audit.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    if r.get('status') == 'error':
        print(f'{r.get(\"agent_id\")} | {r.get(\"error_type\")} | {r.get(\"error_message\",\"\")[:150]}')
"

# 按 req_id 统计单个需求的成本
cat /opt/ai-native/logs/llm_audit.jsonl | python3 -c "
import sys, json
reqs = {}
for line in sys.stdin:
    r = json.loads(line)
    rid = (r.get('req_id','') or 'UNKNOWN')[:8]
    if rid not in reqs: reqs[rid] = {'calls':0,'tokens':0}
    reqs[rid]['calls'] += 1
    reqs[rid]['tokens'] += r.get('total_tokens',0)
for rid in sorted(reqs.keys()):
    print(f'{rid}: {reqs[rid][\"calls\"]} calls, {reqs[rid][\"tokens\"]} tokens')
"
```

### 3.6 查看 Workflow 状态

```bash
# 查询当前 workflow
python3 -c "
import asyncio
from temporalio.client import Client
async def main():
    client = await Client.connect('localhost:7233', namespace='ai-native')
    async for wf in client.list_workflows('WorkflowType=\"RequirementWorkflow\"'):
        h = client.get_workflow_handle(wf.id)
        try:
            s = await h.query('get_state')
            print(f'{wf.id}: state={s[\"state\"]} log={s[\"log_len\"]} rework={s[\"rework_count\"]}')
        except:
            print(f'{wf.id}: COMPLETED/ERROR')
asyncio.run(main())
"

# 终止某个卡住的 workflow
python3 -c "
import asyncio
from temporalio.client import Client
async def main():
    client = await Client.connect('localhost:7233', namespace='ai-native')
    h = client.get_workflow_handle('<workflow_id>')
    await h.terminate(reason='Manual termination')
    print('Terminated')
asyncio.run(main())
"
```

### 3.7 重置环境（测试前推荐）

```bash
# 完全重置脚本 — 清除所有旧数据，干净的启动状态
ssh root@172.27.78.109 << 'RESET'
# 1. 停止所有 workers
systemctl stop ai-native-agents ai-native-orchestrator 2>/dev/null
kill -9 $(ps aux | grep -E '(worker_launcher|worker\.py)' | grep -v grep | awk '{print $2}') 2>/dev/null
sleep 2

# 2. 终止所有运行中的 workflow
python3 -c "
import asyncio
from temporalio.client import Client
async def main():
    c = await Client.connect('localhost:7233', namespace='ai-native')
    count = 0
    async for wf in c.list_workflows('WorkflowType=\"RequirementWorkflow\" and ExecutionStatus=\"Running\"'):
        h = c.get_workflow_handle(wf.id)
        await h.terminate(reason='Reset')
        count += 1
    print(f'Terminated {count} workflows')
asyncio.run(main())
"

# 3. 清除 Python 缓存
find /opt/ai-native/repos -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find /opt/ai-native/repos -name '*.pyc' -delete 2>/dev/null

# 4. 重置 NATS stream
python3 -c "
import asyncio, nats
async def p():
    nc = await nats.connect('nats://localhost:4222')
    js = nc.jetstream()
    try: await js.delete_stream('AI_NATIVE_EVENTS')
    except: pass
    await js.add_stream(name='AI_NATIVE_EVENTS',
        subjects=['context.ready.>','agent.result.>','agent.status.changed.>','orchestrator.>'],
        retention='interest', storage='file')
    await nc.close()
asyncio.run(p())
"

# 5. 重置审计日志
rm -f /opt/ai-native/logs/llm_audit.jsonl

# 6. 重启服务
systemctl start ai-native-agents ai-native-orchestrator
sleep 10
echo "=== Agents ==="
strings /var/log/agent-workers.log | grep 'LLM provider initialized' | tail -1
echo "=== Orchestrator ==="
strings /var/log/orchestrator-worker.log | grep 'Worker running' | tail -1
echo "=== Reset Complete ==="
RESET
```

---

## 四、触发端到端测试

```bash
# 1. 创建需求
curl -s -X POST http://localhost:8000/api/requirements \
  -H 'Content-Type: application/json' \
  -d '{"title":"用户个人中心增加手机号绑定功能","description":"用户可绑定/解绑手机号"}' \
  | python3 -m json.tool

# 2. 启动工作流 (记下 workflow_id)
curl -s -X POST http://localhost:8000/api/requirements/<req_id>/trigger \
  | python3 -m json.tool

# 3. 等待 A1 完成 (约 15s)，查看 Gate 0
sleep 15
curl -s http://localhost:8000/api/requirements/<req_id> \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(a['id']) for a in d.get('approvals',[]) if a['status']=='pending']"

# 4. 审批 Gate 0
curl -s -X POST http://localhost:8000/api/approvals/<gate_id>/approve \
  -H 'Content-Type: application/json' \
  -d '{"comment":"通过"}'

# 5. 依次审批 Gate 1, Gate 2, Gate 3（每步等待约 90s）
# ... 重复 3-4 直到所有 Gate 审批完成

# 6. 查看 LLM 调用统计
cat /opt/ai-native/logs/llm_audit.jsonl | python3 -c "..." # 见 §3.5
```

---

## 五、故障排查

### 5.1 Agent 启动失败

```bash
# 查看启动日志
tail -50 /var/log/agent-workers.log

# 常见问题:
# 1. "No module named 'llm_provider'" → 检查 .pth 文件 (§2.3)
# 2. "NameError: name 'os' is not defined" → 检查 import os
# 3. "DEEPSEEK_API_KEY not configured" → 检查 /etc/ai-native.env
# 4. "consumer is already bound" → 重启 NATS 容器 (docker restart ai-nats)
```

### 5.2 Workflow 卡住

```bash
# 查看 Temporal UI: http://172.27.78.109:8088
# 或查询当前状态:

python3 -c "
import asyncio
from temporalio.client import Client
async def main():
    c = await Client.connect('localhost:7233', namespace='ai-native')
    h = c.get_workflow_handle('<workflow_id>')
    p = await h.query('get_progress')
    import json; print(json.dumps(p, indent=2, ensure_ascii=False))
asyncio.run(main())
"

# 卡住原因:
# - "Waiting for Gate X approval" → 去 API 审批对应 Gate
# - state=releasing 超过 1 分钟 → A13 stub 异常, 手动 signal:
#   python3 -c "await h.signal('agent_completed', args=['A13', {'status':'completed'}])"
```

### 5.3 LLM 调用失败 (401/403)

```bash
# 检查 API Key 是否加载
python3 -c "import os; print('KEY:', os.environ.get('DEEPSEEK_API_KEY','NOT FOUND')[:10])"

# systemd 启动时检查
systemctl show ai-native-agents --property=EnvironmentFiles

# 非 systemd 启动时加载 env:
source /etc/ai-native.env
python3 worker_launcher.py  # 或在文件头部加 env 加载代码
```

### 5.4 Temporal "Namespace default is not found"

```bash
# 这是 worker 尝试用默认 namespace 连接时产生的告警，不影响功能
# 检查 Temporal namespace 是否存在:
docker exec ai-temporal tctl --namespace ai-native namespace describe
# 如不存在则创建:
docker exec ai-temporal tctl --namespace ai-native namespace register
```

---

## 六、代码同步清单

从本地 push 到 109 时，以下是关键文件：

### agent-workers/
```
base_worker.py          ← Agent 基类 (LLM 共享 + dedup + NATS 处理)
worker_launcher.py      ← 启动器 (env 加载 + 注册 + 订阅)
nats_temporal_bridge.py ← NATS → Temporal Signal 桥接
a1_requirement_intake.py ← A1 需求分析
a2_knowledge_analyst.py
a3_ui_generator.py
a4_spec_writer.py
a4/api_schema_generator.py
a4/erd_generator.py
a5_design_review.py
a6_spec_decomposer.py
a7_test_case_generator.py
a8_architecture_expert.py
a9_dev_agent_stub.py
a11_test_agent_stub.py
a12_code_review.py
release_agent.py        ← A13
ci_agent.py             ← A10
fast_channel_classifier.py
k14_knowledge_keeper.py
k15_change_propagation.py
```

### orchestrator/
```
worker.py
workflows/requirement_workflow.py  ← 核心状态机
activities/dispatch_agent.py
activities/gate_await.py
activities/context_build.py
activities/notify_mc.py
```

### llm-provider/
```
llm_provider/audit.py           ← 审计单例
llm_provider/context.py         ← LLMCallContext
llm_provider/adapter.py         ← 基类 + _chat_with_audit
llm_provider/deepseek_adapter.py
llm_provider/manager.py         ← LLMProviderManager
llm_provider/__init__.py
```

---

## 附录 A: systemd Service 文件

### ai-native-backend.service
```ini
[Unit]
Description=AI Native Backend (FastAPI uvicorn)
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai-native/repos/mc-backend
EnvironmentFile=/etc/ai-native.env
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=append:/var/log/ai-native-backend.log
StandardError=append:/var/log/ai-native-backend.log

[Install]
WantedBy=multi-user.target
```

### ai-native-frontend.service
```ini
[Unit]
Description=AI Native Frontend (Next.js)
After=network.target ai-native-backend.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai-native/frontend
EnvironmentFile=/etc/ai-native.env
ExecStart=/usr/bin/npm start -- -p 80
Restart=always
RestartSec=5
StandardOutput=append:/var/log/ai-native-frontend.log
StandardError=append:/var/log/ai-native-frontend.log

[Install]
WantedBy=multi-user.target
```

### ai-native-agents.service
```ini
[Unit]
Description=AI Native Agent Workers (NATS subscribers)
After=network.target docker.service ai-native-backend.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai-native/repos/agent-workers
EnvironmentFile=/etc/ai-native.env
ExecStart=/usr/bin/python3 worker_launcher.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/agent-workers.log
StandardError=append:/var/log/agent-workers.log

[Install]
WantedBy=multi-user.target
```

### ai-native-orchestrator.service
```ini
[Unit]
Description=AI Native Orchestrator Worker (Temporal)
After=network.target docker.service ai-native-backend.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai-native/repos/orchestrator
EnvironmentFile=/etc/ai-native.env
ExecStart=/usr/bin/python3 worker.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/orchestrator-worker.log
StandardError=append:/var/log/orchestrator-worker.log

[Install]
WantedBy=multi-user.target
```
