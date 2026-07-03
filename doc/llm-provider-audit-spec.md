# LLM 调用统一 & 审计 — 详细规格 v3 (FINAL)

## 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-06 | 初版 |
| v2 | 2026-07 | 6 项 critical 审计修正（C1-C4, M1, H1） |
| **v3** | 2026-07-03 | 基于端到端测试实际观测数据更新：双调用路径盘点、A12 内部调用链、`req_id=unknown`、`_mock_llm` 消除 |

## 1. 目标

将 13 个 Agent 的 LLM 调用全部通过 `llm-provider` 统一层，在 provider 层内置全量审计日志，替代当前各 Agent 各自用裸 `httpx.AsyncClient` 直调 + 各自 `_call_llm` / `_mock_llm` 双路径的模式。

**v3 新增目标**：
- 每个 Agent 每轮最多 **1 次有效 LLM 调用**（消除当前的双调用/多调用浪费）
- 审计日志中 `req_id` 100% 不为 `unknown`
- 消除 `_mock_llm` 方法（与 `_call_llm` 合并为统一入口）

## 2. 当前状态（问题清单）

### 2.1 代码分散 — 13 个 Agent 各自实现 `_call_llm` + `_mock_llm`

每个 Agent 文件都复制了几乎相同的 ~25 行代码：

```python
async def _call_llm(self, messages, temperature=0.X):
    if not DEEPSEEK_API_KEY:
        return None
    async with httpx.AsyncClient(timeout=XX.0) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", ...},
            json={"model": DEEPSEEK_MODEL, "messages": messages, ...},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
```

| Agent | 文件 | 方法名 | timeout | 类继承 |
|-------|------|--------|---------|--------|
| A1 | a1_requirement_intake | `_call_llm` + `_mock_llm` | 60s | BaseAgentWorker |
| A2 | a2_knowledge_analyst | `_call_llm` | 60s | BaseAgentWorker |
| A3 | a3_ui_generator | `_call_llm` | 90s | BaseAgentWorker |
| A4 | a4_spec_writer | agent 层不调 LLM，委托给… | | BaseAgentWorker |
| A4 (API) | a4/api_schema_generator | `_call_llm` | 120s | **独立类** (非 BaseAgentWorker) |
| A4 (ERD) | a4/erd_generator | `_call_llm` | 120s | **独立类** (非 BaseAgentWorker) |
| A5 | a5_design_review | `_call_llm` | 180s | BaseAgentWorker |
| A6 | a6_spec_decomposer | `_call_llm` | 120s | BaseAgentWorker |
| A7 | a7_test_case_generator | `_call_llm` | 60s | BaseAgentWorker |
| A8 | a8_architecture_expert | `_call_llm` | 180s | BaseAgentWorker |
| A9 | a9_claude_code_bridge | `_call_llm` | 120s | BaseAgentWorker |
| A11 | a11_test_agent_stub | `_call_llm` | 90s | BaseAgentWorker |
| A12 | a12_code_review | `_call_llm` + 内部 `_handle_review_request` | 120s | BaseAgentWorker |
| FC | fast_channel_classifier | `_call_llm` | 60s | BaseAgentWorker |

### 2.2 端到端测试实测数据（2026-07-03）

一次完整流水线执行（`req-7a1a2c8f-1783057254`，含 3 轮返工）的 LLM 调用统计：

| Agent | 总调用发起 | 有效完成 (duration>0) | 浪费调用 (duration=0) | 浪费占比 |
|-------|-----------|----------------------|----------------------|----------|
| A1 | 6 | 1 | 5 | 83% |
| A3 | 6 | 3 | 3 | 50% |
| A5 | 8 | 4 | 4 | 50% |
| A6 | 2 | 1 | 1 | 50% |
| A12 | 6 | 3 | 3 | 50% |
| **合计** | **28** | **12** | **16** | **57%** |

**关键发现**：

1. **双调用模式**（2 START / 轮 / Agent）：A3/A5/A6 每轮发起 2 个并行 `LLM_CALL_START`，但只有 1 个完成（另一个 `duration=0.000s` 即 API key 未配或 fallback 返回 None）。根因：`_init_llm_audit()` 同时 wrap 了 `_call_llm` 和 `_mock_llm`，Agent 逻辑中两条路径都被触发。

2. **A12 超量调用**（6 START / 轮）：A12 一轮发起 6 个 `LLM_CALL_START`，远超其他 Agent。4 个来自 `a12_code_review.py:57 in _handle_review_request` 内部事件循环，2 个来自 `base_worker.py:222 in _handle`。说明 A12 有独立的内部调用路径，双重触发 + 多路并发。

3. **`req_id=unknown`**：所有 28 条 LLM 审计日志中 `req_id` 均为 `unknown`。当前 audit wrapper 在 `_handle()` 层无法获取 req_id，Agent 未将其传入 `_call_llm`。

4. **A4 无真实调用**：`APISchemaGenerator` / `ERDGenerator` 读不到 `DEEPSEEK_API_KEY` 环境变量，每次都走 fallback → A5 评审输入为空 → 必然 fail → 3 轮返工直到 `_MAX_REWORK=2` 耗尽。

### 2.3 审计缺失

| 维度 | llm-provider (当前) | Agent (当前) | llm_audit wrapper |
|------|---------------------|-------------|-------------------|
| 调用日志 | 无 | 各 Agent 自己 logger.info | 有（START/END/FAIL） |
| token 统计 | `LLMResponse.usage` 字段存在 | 调用方不收集 | 无 |
| 耗时记录 | 无 | 无 | 有 |
| provider 信息 | 无 | 无 | 无 |
| agent_id/req_id | 无 | 部分 logger 有 | agent_id 有，req_id=unknown |
| 错误分类 | 无 | catch Exception 后 return None | 有 |
| 速率/配额 | 无 | 无 | 无 |
| 重试 | 无 | 无 | 无 |
| 重复调用检测 | 无 | 无 | 无 |

`llm_audit.py` 是绕开 llm-provider 在 Agent 层打的补丁，Agent 迁移后就该删掉。

### 2.4 llm-provider 设计良好但未启用

- 4 个 Adapter：DeepSeek / Qwen / GLM / Anthropic
- `LLMProviderManager`：task_type 路由 + fallback 链
- `LLMResponse`：已包含 `model`, `usage`, `finish_reason`
- 所有 Adapter **是同步的**（用 `httpx.Client`），Agent 是异步的 → 需要适配

## 3. 目标架构

```
Agent Worker                          llm-provider                        LLM API
────────────                          ────────────                        ──────

A1.execute(req_id="xxx", context_package={...})
  │
  ├─ content = await self.call_llm(          ← 唯一入口，替代 _call_llm + _mock_llm
  │      messages,
  │      task_type="requirement_analysis",
  │      req_id="xxx",                       ← 显式传入，不再 unknown
  │      workflow_id="yyy",
  │      temperature=0.3,
  │      max_tokens=2000)
  │
  │  BaseAgentWorker.call_llm():
  │    └─ asyncio.to_thread(
  │         self._llm.chat, messages, ctx=ctx, ...)
  │         │
  │         └─ LLMProviderManager.chat()
  │              ├─ auditor.record_start()    ← start + end 配对，不再有 50% 浪费
  │              ├─ DeepSeekAdapter.chat() → httpx POST
  │              └─ auditor.record_end()
  │
  └─ return content (str | None)
```

## 4. 关键设计决策

### 4.1 同步/异步桥接：`asyncio.to_thread` [修复 C1]

llm-provider 的 4 个 Adapter 全部使用 `httpx.Client`（同步），Agent 在 asyncio event loop 中运行。直接在 async 上下文中调同步 HTTP → 阻塞 event loop。

**修正**：`BaseAgentWorker.call_llm()` 用 `asyncio.to_thread` 把同步调用扔到线程池：

```python
async def call_llm(self, messages, *,
                   task_type="text", temperature=0.3, max_tokens=2000,
                   req_id="", workflow_id="") -> str | None:
    if self._llm is None:
        self._init_llm()
    
    ctx = LLMCallContext(
        agent_id=self.agent_id,
        req_id=req_id,
        workflow_id=workflow_id,
        task_type=task_type,
    )
    
    try:
        result = await asyncio.to_thread(
            self._llm.chat, messages,
            task_type=task_type,
            temperature=temperature,
            max_tokens=max_tokens,
            ctx=ctx,
        )
        return result.content
    except Exception as e:
        logger.error(f"[{self.agent_id}] LLM call failed: {e}")
        return None
```

不需要改 llm-provider 的任何代码，Adapter 保持同步。`asyncio.to_thread` 使用默认线程池，16 个 Agent 并发时线程池自动管理。

### 4.2 `LLMAuditor` 模块级单例 [修复 C2 + C3]

**问题 1**：每个 Agent 各自创建 Auditor → 16 个实例 → 16 个 `_pending` dict → 16 把不同的 `Lock` → JSONL 文件写入无互斥，行交错损坏。

**问题 2**：`_pending` dict 无上限，`record_start` 后如果从不 `record_end`，内存泄漏。

**修正**：Auditor 改为模块级单例，`_pending` 设硬上限：

```python
# audit.py
import threading
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_auditor_instance: "LLMAuditor | None" = None
_auditor_lock = threading.Lock()

MAX_PENDING = 1000  # 硬上限，防止内存泄漏

def get_auditor(outputs=None) -> "LLMAuditor":
    """返回模块级单例 Auditor（线程安全）。"""
    global _auditor_instance
    if _auditor_instance is None:
        with _auditor_lock:
            if _auditor_instance is None:
                _auditor_instance = LLMAuditor(outputs=outputs)
    return _auditor_instance


class LLMAuditor:
    def __init__(self, outputs=None):
        self.outputs = outputs or ["file", "stdout"]
        self._lock = threading.Lock()  # ← 单例，全局唯一的锁
        self._log_path = Path(os.environ.get(
            "LLM_AUDIT_LOG", "/opt/ai-native/logs/llm_audit.jsonl"
        ))
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._pending: dict[str, dict] = {}

    def record_start(self, agent_id, req_id, workflow_id, task_type,
                     provider, model, prompt_chars) -> str:
        call_id = str(uuid4())
        record = {
            "call_id": call_id, "agent_id": agent_id, "req_id": req_id,
            "workflow_id": workflow_id, "task_type": task_type,
            "provider": provider, "model": model, "prompt_chars": prompt_chars,
            "status": "started",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            # 内存泄漏防护
            if len(self._pending) >= MAX_PENDING:
                oldest = next(iter(self._pending))
                logger.warning(f"Auditor pending overflow, dropping call_id={oldest}")
                del self._pending[oldest]
            self._pending[call_id] = record
        return call_id

    def record_end(self, call_id, response_chars, prompt_tokens,
                   completion_tokens, duration_ms, error=None):
        with self._lock:
            record = self._pending.pop(call_id, {})
        if not record:
            logger.warning(f"Auditor: call_id={call_id} not found in pending")
            return
        record.update({
            "status": "error" if error else "success",
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "response_chars": response_chars,
            "error_type": type(error).__name__ if error else None,
            "error_message": str(error)[:500] if error else None,
        })
        self._write(record)

    def _write(self, record):
        line = json.dumps(record, ensure_ascii=False)
        if "file" in self.outputs:
            with self._lock:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        if "stdout" in self.outputs:
            status_icon = "X" if record["status"] == "error" else "OK"
            tokens = record.get("total_tokens", 0)
            dur = record.get("duration_ms", 0) / 1000
            print(f"[LLM] {record.get('agent_id','?')} | "
                  f"task={record.get('task_type','?')} | "
                  f"{record.get('prompt_chars',0)}->{record.get('response_chars',0)} chars | "
                  f"{dur:.1f}s | tokens={tokens} | {status_icon}")
```

**不输出 NATS**。NATS publish 需要 asyncio event loop，Auditor 是同步的。如未来需要前端实时看 LLM 调用，可以加一个独立的小进程 tail JSONL 文件并转发到 NATS。

### 4.3 `LLMProviderManager` 类级共享 [修复 C3]

16 个 Agent 不应各自创建 `DeepSeekAdapter` + 连接池。Manager 改为类级共享：

```python
# base_worker.py
class BaseAgentWorker:
    _shared_llm: object = None      # 类级共享 LLMProviderManager
    _shared_llm_lock = threading.Lock()

    def _init_llm(self):
        """初始化 LLM provider，所有 Agent 实例共享同一个 Manager 和 Auditor。"""
        if BaseAgentWorker._shared_llm is not None:
            self._llm = BaseAgentWorker._shared_llm
            return

        with BaseAgentWorker._shared_llm_lock:
            if BaseAgentWorker._shared_llm is not None:
                self._llm = BaseAgentWorker._shared_llm
                return

            from llm_provider.audit import get_auditor
            from llm_provider.manager import LLMProviderManager
            from llm_provider.deepseek_adapter import DeepSeekAdapter

            auditor = get_auditor(outputs=["file", "stdout"])
            manager = LLMProviderManager(
                adapters={"deepseek": DeepSeekAdapter()},
                default_routes={"text": "deepseek"},
                auditor=auditor,
            )
            BaseAgentWorker._shared_llm = manager
            self._llm = manager
            logger.info(f"[{self.agent_id}] LLM provider initialized (shared)")
```

### 4.4 `APISchemaGenerator` / `ERDGenerator` 注入 callable [修复 C4]

这两个类不是 `BaseAgentWorker` 子类，无法调 `self.call_llm()`。改为构造函数注入 llm_caller。

**`a4/api_schema_generator.py`** 和 **`a4/erd_generator.py`**：

```python
class APISchemaGenerator:
    def __init__(self, llm_caller: Callable | None = None):
        self._llm = llm_caller  # 外部注入的 call_llm

    async def _call_llm(self, prompt: str, task_type: str = "openapi_gen",
                        max_tokens: int = 4000) -> str | None:
        if self._llm:
            return await self._llm(
                [{"role": "user", "content": prompt}],
                task_type=task_type,
                max_tokens=max_tokens,
            )
        # Fallback: 直接调 httpx（仅当未注入时，过渡用）
        ...
```

**`a4_spec_writer.py`** 的 `A4SpecWriter` 在构造时注入：

```python
class A4SpecWriter(BaseAgentWorker):
    def __init__(self, nats_url="nats://localhost:4222"):
        super().__init__(...)
        self.api_schema_gen = APISchemaGenerator(
            llm_caller=self.call_llm  # ← 注入 BaseAgentWorker 的 call_llm
        )
        self.erd_gen = ERDGenerator(
            llm_caller=self.call_llm
        )
```

`call_llm` 签名需要支持以 callable 方式传入 `messages` + kwargs，在 §4.5 中已定义。

### 4.5 `call_llm` 显式传参替代实例属性 [修复 M1 + `req_id=unknown`]

`req_id` 和 `workflow_id` 不作为实例属性存储，而是由 `execute()` 显式传入：

```python
# base_worker.py
async def call_llm(self, messages: list, *,
                   task_type: str = "text",
                   temperature: float = 0.3,
                   max_tokens: int = 2000,
                   req_id: str = "",
                   workflow_id: str = "") -> str | None:
    ...

# ⚠️ 要求：所有 Agent 的 execute(req_id) 调用 call_llm 时必须传入 req_id
# 如果 req_id 为空字符串，审计日志中将记录 "UNKNOWN" 作为告警标记
```

Agent `execute()` 中：
```python
content = await self.call_llm(
    [{"role": "user", "content": prompt}],
    task_type="requirement_analysis",
    req_id=req_id,                                    # ← 必须传入
    workflow_id=context_package.get("workflow_id", ""), # ← 必须传入
    temperature=0.3,
    max_tokens=2000,
)
```

`_handle()` 中不再需要设置 `self._req_id` / `self._workflow_id`。

### 4.6 消除 `_mock_llm` — 统一入口 [修复 v3 新增]

当前 `base_worker.py` 的 `_init_llm_audit()` 同时 wrap `_call_llm` 和 `_mock_llm`，导致 Agent 每轮发起 2 次 LLM 调用（一个真实、一个 mock/fallback）。

**修正**：迁移后各 Agent 只保留 `self.call_llm()` 作为唯一 LLM 入口：
- 删除 Agent 中的 `_call_llm()` 方法定义
- 删除 Agent 中的 `_mock_llm()` 方法定义（如 A1）
- 删除环境变量直读（`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`）
- Agent 调用处统一改为 `await self.call_llm(...)`
- `call_llm` 内部处理 fallback（API key 未配置时 auditor 记录 + return None）
- `base_worker._init_llm_audit()` 删除（不再需要 monkey-patch wrapper）

### 4.7 A12 内部调用路径审计 [修复 v3 新增]

A12 (`a12_code_review.py`) 实测单轮 6 次 LLM 调用，根因：

```
base_worker._handle → execute() → _call_llm           ← 2 次（双调用）
a12._handle_review_request → internal event loop → _call_llm  ← 4 次（内部事件循环）
```

**修正**：
1. `_handle_review_request` 改为调用 `self.call_llm()`，传 `req_id` 和 `workflow_id`
2. 确认 A12 不需要内部事件循环的多轮审查（如确实需要，应通过 Orchestrator 调度而非 Agent 内部循环）
3. 审计所有 Agent 是否有额外的内部 LLM 调用路径（`grep -rn '_call_llm\|_mock_llm\|httpx.*chat\|AsyncClient.*post' --include='*.py'`）

### 4.8 去 NATS 输出 [修复 H1 + C2]

Auditor 是同步对象，NATS publish 需要 asyncio loop。**去掉 NATS 输出**，只保留 file + stdout。如需前端实时面板，方案：独立的轻量进程 tail JSONL 文件并转发到 NATS（未来再加，现在先不搞）。

## 5. 改动清单

### 5.1 新建文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `repos/llm-provider/llm_provider/audit.py` | ~100 | `LLMAuditor` + `get_auditor()` 单例，file + stdout 输出，线程安全 |
| `repos/llm-provider/llm_provider/context.py` | ~20 | `LLMCallContext` dataclass (agent_id, req_id, workflow_id, task_type) |

### 5.2 修改 llm-provider

| 文件 | 改动摘要 |
|------|---------|
| `adapter.py` | `LLMAdapter.__init__` 新增 `auditor` 参数；新增 `_chat_with_audit()` 同步方法；`LLMResponse` 新增 `call_id` 字段 |
| `manager.py` | `chat()` 新增 `ctx` 参数；`_execute_with_fallback()` 透传 ctx；`__init__` 注入 auditor 到所有 adapter |

### 5.3 修改 Agent 层

| 文件 | 改动摘要 |
|------|---------|
| `base_worker.py` | 新增 `_shared_llm` 类属性 + `_init_llm()` + `call_llm()`；**删除 `_init_llm_audit()`** |
| `a4/api_schema_generator.py` | 构造函数新增 `llm_caller` 参数；`_call_llm` 改用注入的 callable |
| `a4/erd_generator.py` | 同 api_schema_generator |
| `a4_spec_writer.py` | 构造 `APISchemaGenerator` / `ERDGenerator` 时注入 `self.call_llm` |

### 5.4 Agent 逐个迁移（13 个 → `_call_llm` + `_mock_llm` 全部替换为 `self.call_llm`）

**迁移前审计**（每个 Agent 先跑以下命令，确认调用路径清单）：

```bash
grep -n '_call_llm\|_mock_llm\|httpx.*chat\|AsyncClient.*post' {agent_file}.py
```

**A12 特别关注**：`_handle_review_request` 内部调用链需额外确认。

**每个 Agent 改动模式一致**：

**改前**（当前状态）：
```python
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "...")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")

async def _call_llm(self, messages, temperature=0.3) -> str | None:
    if not DEEPSEEK_API_KEY: return None
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(...)
        ...

# A1 还有 _mock_llm 方法 — 同样要删
async def _mock_llm(self, messages, temperature=0.3) -> str | None:
    if not DEEPSEEK_API_KEY: return None
    ...
```

**改后**（以 A1 为例）：
```python
# 删除模块级 DEEPSEEK_* 常量和 _call_llm / _mock_llm 方法

# execute() 中改为:
content = await self.call_llm(
    [{"role": "system", ...}, {"role": "user", ...}],
    task_type="requirement_analysis",
    req_id=req_id,                                    # ← 从 execute() 参数传入
    workflow_id=context_package.get("workflow_id", ""),
    temperature=0.3,
    max_tokens=2000,
)
```

迁移列表 + task_type：

| Agent | 文件 | 需删除的方法 | task_type | max_tokens |
|-------|------|-------------|-----------|------------|
| A1 | a1_requirement_intake | `_call_llm` **+ `_mock_llm`** | `requirement_analysis` | 2000 |
| A2 | a2_knowledge_analyst | `_call_llm` | `knowledge_analysis` | 2000 |
| A3 | a3_ui_generator | `_call_llm` | `ui_prototype` | 4000 |
| A4 (API) | **a4/api_schema_generator** | `_call_llm` → 注入 callable | `openapi_gen` | 4000 |
| A4 (ERD) | **a4/erd_generator** | `_call_llm` → 注入 callable | `erd_gen` | 3000 |
| A5 | a5_design_review | `_call_llm` | `design_review` | 3000 |
| A6 | a6_spec_decomposer | `_call_llm` | `task_decomposition` | 4000 |
| A7 | a7_test_case_generator | `_call_llm` | `test_case_gen` | 2000 |
| A8 | a8_architecture_expert | `_call_llm` | `architecture_review` | 2000 |
| A9 | a9_claude_code_bridge | `_call_llm` | `code_generation` | 4000 |
| A11 | a11_test_agent_stub | `_call_llm` | `test_execution` | 2000 |
| A12 | a12_code_review | `_call_llm` + **审查 `_handle_review_request`** | `code_review` | 2000 |
| FC | fast_channel_classifier | `_call_llm` | `complexity_classify` | 1000 |

> A4 的 API Schema Generator 和 ERD Generator 通过注入 callable 迁移（见 4.4）。
> A12 需额外处理内部 `_handle_review_request` 调用链（见 4.7）。

### 5.5 删除文件

| 文件 | 原因 |
|------|------|
| `repos/agent-workers/llm_audit.py` | 功能被 llm-provider audit 层替代 |

## 6. 调用流程（改后）

```
Agent.execute(req_id="xxx", context_package={...})
  │
  ├─ content = await self.call_llm(messages,
  │       task_type="requirement_analysis",
  │       req_id=req_id, workflow_id=wf_id,
  │       temperature=0.3, max_tokens=2000)
  │       ← 唯一入口，每轮最多 1 次调用
  │
  │  BaseAgentWorker.call_llm():
  │    ├─ 构造 LLMCallContext(agent_id, req_id, workflow_id, task_type)
  │    │  ← req_id 来自 execute() 参数，不再是 "unknown"
  │    ├─ await asyncio.to_thread(self._llm.chat, messages, ctx=ctx, ...)
  │    │    │
  │    │    └─ [线程池线程]
  │    │       LLMProviderManager.chat()
  │    │         ├─ adapter._chat_with_audit(messages, ctx=ctx, ...)
  │    │         │    ├─ auditor.record_start(...)     ← start
  │    │         │    ├─ DeepSeekAdapter.chat(messages, ...)
  │    │         │    │    └─ httpx.Client.post(...)
  │    │         │    └─ auditor.record_end(...)       ← end
  │    │         └─ return LLMResponse
  │    │
  │    └─ return result.content (str | None)
  │
  ├─ if content is None: fallback...    ← 基类已处理，Agent 不再自己 fallback
  └─ return result
```

## 7. 审计输出

3 种输出（去掉 NATS 后剩 2 种）：

| 输出 | 格式 | 用途 |
|------|------|------|
| File | JSON lines，`/opt/ai-native/logs/llm_audit.jsonl` | 排查问题、成本分析 |
| stdout | 一行摘要 | 实时 tail -f 监控 |

示例：
```
[LLM] A1 | task=requirement_analysis | req=7a1a2c8f | 550→88 chars | 8.6s | tokens=250 | OK
[LLM] A4 | task=openapi_gen | req=7a1a2c8f | 1200→3500 chars | 22.3s | tokens=1650 | OK
[LLM] A5 | task=design_review | req=7a1a2c8f | 3600→1800 chars | 42.0s | tokens=1800 | X
```

> stdout 示例中 `req=7a1a2c8f` 取 req_id 前 8 字符，不再显示 `unknown`。

## 8. 监控能力

```bash
# 实时看所有调用
tail -f /opt/ai-native/logs/llm_audit.jsonl | jq '.'

# 只看错误
tail -f /opt/ai-native/logs/llm_audit.jsonl | jq 'select(.status=="error")'

# 按 agent 统计当日 token
cat /opt/ai-native/logs/llm_audit.jsonl | jq -r '[.agent_id, .total_tokens] | @tsv' \
  | awk '{s[$1]+=$2} END {for(k in s) print k, s[k]}' | sort -k2 -nr

# 按 task_type 统计平均耗时
cat /opt/ai-native/logs/llm_audit.jsonl | jq -r '[.task_type, .duration_ms] | @tsv' \
  | awk '{s[$1]+=$2; c[$1]++} END {for(k in s) printf "%s: %.1fs avg\n", k, s[k]/c[k]/1000}'

# 按 req_id 统计单个需求的总 token 成本
cat /opt/ai-native/logs/llm_audit.jsonl | jq -r '[.req_id, .total_tokens] | @tsv' \
  | awk '{s[$1]+=$2} END {for(k in s) print k, s[k]}' | sort -k2 -nr

# 检测异常：req_id 为空的调用（迁移后应为 0）
cat /opt/ai-native/logs/llm_audit.jsonl | jq 'select(.req_id == "" or .req_id == "unknown")'
```

## 9. 验证标准（新增）

迁移完成后，以下指标必须达标：

| 指标 | 当前值（实测） | 目标值 |
|------|-------------|--------|
| 单轮 A1 LLM 调用数 | 2 | **1** |
| 单轮 A3 LLM 调用数 | 2 | **1** |
| 单轮 A5 LLM 调用数 | 2 | **1** |
| 单轮 A12 LLM 调用数 | **6** | **1** |
| `req_id` 覆盖率 | 0% | **100%** |
| `workflow_id` 覆盖率 | 0% | **100%** |
| JSONL 行完整性（`jq .` 可解析） | N/A | **100%** |
| 完整流水线 LLM 总调用数（无返工） | 28 | **≤ 9** (1 per agent stage) |
| A4 真实 LLM 调用 | 0 | **≥ 2** (openapi_gen + erd_gen) |

## 10. 实施策略（4 个 Phase）

### Phase A: llm-provider 加审计层（~1.5h）
1. 新建 `audit.py` + `context.py`
2. 修改 `adapter.py`：`_chat_with_audit()`
3. 修改 `manager.py`：`ctx` 参数透传
4. 本地单元测试：`python3 -c "from llm_provider.audit import LLMAuditor; ..."`

### Phase B: BaseAgentWorker 集成（~1h）
1. 改 `base_worker.py`：`_shared_llm` + `_init_llm()` + `call_llm()`
2. 删 `_init_llm_audit()`
3. 改 `a4/api_schema_generator.py` + `a4/erd_generator.py`：注入 callable
4. 改 `a4_spec_writer.py`：构造时注入

### Phase C: Agent 逐个迁移（~3h）

**迁移前审计**：对每个 Agent 运行：
```bash
grep -n '_call_llm\|_mock_llm\|httpx.*AsyncClient.*post\|_handle_review' {agent}.py
```
记录所有 LLM 调用点，确保迁移后每个都被替换。

**迁移顺序**：A1 先（验证 `_mock_llm` 消除）→ A2/A3/A4/A5/A6/A7/A8 → **A12（特别关注）** → A9/A11/FC

每批：审计调用路径 → 删 `DEEPSEEK_*` 常量 → 删 `_call_llm` / `_mock_llm` → 替换为 `self.call_llm(..., req_id=req_id)` → 推 109 验证 JSONL 有记录且 req_id 不为 unknown

### Phase D: 清理 + 验证（~0.5h）
1. 删 `llm_audit.py`
2. `base_worker.py` 中搜 `llm_audit` 确保无残留引用
3. 按 §9 验证标准逐项检查
4. 跑完整流水线确认 LLM 调用数 ≤ 9（无返工情况）

## 11. 与调度收归 Spec 的关系

两个 Spec 正交，互不阻塞：

| 维度 | 调度收归 | LLM 审计统一 |
|------|---------|-------------|
| 改动范围 | Workflow + Bridge + approvals | llm-provider + base_worker |
| Agent 改动 | 删自级联代码 | 替换 `_call_llm` + `_mock_llm` |
| 建议顺序 | **已完成** | 本次实施 |

唯一交集：`base_worker.py`。调度收归已做，`workflow_id` 已在 context 中，LLM 审计时 `execute()` 从同一字段读取传入。
