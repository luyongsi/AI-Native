# A1 - 需求分析 Agent 规格

## 基本信息
- **Agent ID**: A1
- **Agent Type**: requirement_intake
- **订阅事件**: `context.ready.requirement_intake`
- **发布事件**: `agent.result.A1`
- **代码位置**: `repos/agent-workers/a1_requirement_intake.py`

## 职责
A1 是系统的入口 Agent，负责接收用户原始需求消息，通过 LLM 或关键词匹配提取意图、领域、实体和验收标准，生成结构化的需求草案。这是整个需求流程的第一阶段，为后续的 UI 生成（A3）和规格编写（A4）提供基础信息。

## 输入

### Context Package 结构
```json
{
  "message": "用户原始消息（优先级最高）",
  "msg_received": {"text": "备用消息字段"},
  "title": "需求标题",
  "description": "需求描述",
  "requirement_draft": {
    "title": "上游传递的草案标题",
    "description": "上游传递的草案描述"
  },
  "workflow_id": "Temporal Workflow ID（用于审计）"
}
```

### 输入优先级逻辑
1. `context_package.message`（最高优先级）
2. `context_package.msg_received.text`
3. `context_package.title` + `context_package.description`（拼接）
4. `context_package.requirement_draft.title` + `requirement_draft.description`（最低优先级）

### 关键输入字段
- **raw_message** (string): 用户原始需求描述，作为 LLM 分析的输入

## 处理流程

### Phase 1: LLM 需求分析
1. 调用 `self.call_llm()` 发送系统 prompt + 用户消息
2. 系统 prompt 要求输出严格 JSON 格式：
   - `title`: 15字以内的简短标题
   - `domain`: 业务领域（order_management/payment/user_management/product_catalog/inventory/auth/notification/reporting/general）
   - `summary`: 50字以内的需求概括
   - `entities`: 提取的实体（user_role/entity_name/deadline/quantity）
   - `acceptance_criteria`: 验收标准数组
   - `tech_stack_suggestion`: 技术栈建议（backend/frontend/database）
   - `risk_points`: 风险点数组
   - `priority_suggestion`: 优先级（P0/P1/P2/P3）
3. 解析 LLM 返回的 JSON（支持 markdown 代码块清理）
4. 如果 LLM 失败或返回无效 JSON，fallback 到关键词匹配

### Phase 2: Fallback 关键词匹配（当 LLM 不可用时）
1. `_detect_domain()`: 通过 `DOMAIN_KEYWORDS` 字典匹配领域
2. `_extract_entities()`: 通过正则表达式 `ENTITY_PATTERNS` 提取实体
3. `_build_mock_draft()`: 生成默认的验收标准和优先级

### Phase 3: 发布需求草案
1. 调用 `self.report_artifact(req_id, "requirement_draft", draft)` 发布到 NATS
2. 返回执行结果

## 输出

### 返回结构
```json
{
  "status": "completed",
  "domain": "order_management",
  "entities": {
    "user_role": ["管理员"],
    "entity_name": ["订单表"],
    "deadline": ["3天"]
  },
  "requirement_draft": {
    "title": "订单管理系统开发",
    "domain": "order_management",
    "summary": "开发订单创建、查询、状态流转功能，支持管理员和普通用户操作",
    "entities": {...},
    "acceptance_criteria": [
      "管理员应能创建、修改、删除订单",
      "普通用户应能查询自己的订单",
      "订单状态流转应记录完整日志"
    ],
    "tech_stack_suggestion": {
      "backend": "FastAPI + PostgreSQL",
      "frontend": "React",
      "database": "PostgreSQL with JSONB"
    },
    "risk_points": ["并发订单创建可能冲突", "支付接口超时处理"],
    "priority_suggestion": "P1"
  },
  "source": "llm"
}
```

### 持久化位置
- **DB**: `requirements.spec.artifacts.A1`（通过 Orchestrator 的 `store_agent_result` Activity）
- **NATS**: 发布 `agent.result.A1` 事件（由 BaseAgentWorker 自动处理）
- **审计**: 通过 `report_artifact` 记录到 `audit_logs` 表

## LLM 调用

### 调用参数
- **任务类型**: `requirement_analysis`
- **温度**: `0.3`（低创造性，保证稳定输出）
- **Max Tokens**: `2000`
- **模型**: 继承自 LLM Provider 配置（默认 DeepSeek）

### Prompt 结构
**System Prompt**:
```
你是一个需求分析师。分析用户的需求描述，输出 JSON 格式的结构化需求草案。

输出格式（严格 JSON）：
{
  "title": "简短的需求标题（15字以内）",
  "domain": "order_management|payment|...|general",
  "summary": "一段话概括需求（50字以内）",
  "entities": {...},
  "acceptance_criteria": [...],
  "tech_stack_suggestion": {...},
  "risk_points": [...],
  "priority_suggestion": "P0|P1|P2|P3"
}

只输出 JSON，不要其他内容。
```

**User Prompt**:
```
{raw_message}
```

## 依赖

### 上游
- **无**（A1 是入口 Agent）

### 下游
- **A3** (UI 生成): 依赖 A1 的 `requirement_draft.domain` 和 `entities`
- **A4** (规格编写): 依赖 A1 的 `requirement_draft.acceptance_criteria` 和 `tech_stack_suggestion`

### 外部服务
- **PostgreSQL**: 通过 Orchestrator 间接写入 `requirements.spec.artifacts.A1`
- **NATS**: 订阅 `context.ready.requirement_intake`，发布 `agent.result.A1`
- **LLM Provider**: 通过 `self.call_llm()` 调用（支持 DeepSeek/OpenAI/Anthropic）

## 当前实现状态
- ✅ **已实现并部署**: A1 代码完整，LLM + Fallback 双路径可用
- ✅ **已在 Orchestrator 调度**: `requirement_workflow.py` 第一个调度的 Agent（ANALYZING 状态）

## 已知问题

### 1. 输入字段优先级复杂
**影响**: 多个字段来源导致逻辑分支较多（45-67 行），容易遗漏边界情况
**建议**: Context Builder 统一输出 `message` 字段，A1 只读该字段

### 2. Fallback 关键词词典覆盖不足
**影响**: `DOMAIN_KEYWORDS` 只有 20 个关键词，复杂需求可能误分类为 `general`
**建议**: 扩展词典或增加模糊匹配（如 Jieba 分词 + TF-IDF）

### 3. JSON 解析容错有限
**影响**: LLM 返回非标准 JSON（如多余注释）时解析失败，直接 fallback
**当前处理**: 支持 markdown 代码块清理（131-135 行），但不支持注释、尾逗号等
**建议**: 使用 `json5` 库或正则预处理

### 4. Entity 提取正则过于简单
**影响**: `ENTITY_PATTERNS` 只能提取固定格式（如"3天"、"管理员"），无法处理复杂表达（如"最迟本周五"、"具有审核权限的用户"）
**建议**: LLM 模式下直接让 LLM 提取实体，Fallback 模式保持当前逻辑

## 测试方法

### 1. 单元测试
```bash
# 运行 A1 单元测试（需创建）
python -m pytest repos/agent-workers/tests/test_a1.py -v
```

### 2. 手动 NATS 事件触发
```python
import asyncio
import json
from nats.aio.client import Client as NATS

async def test_a1():
    nc = NATS()
    await nc.connect("nats://localhost:4222")
    
    context = {
        "req_id": "test-req-001",
        "message": "开发一个订单管理系统，管理员可以创建订单，用户可以查询自己的订单",
        "workflow_id": "test-workflow-001"
    }
    
    await nc.publish("context.ready.requirement_intake", 
                     json.dumps(context).encode())
    
    # 订阅结果
    async def result_handler(msg):
        print("A1 Result:", msg.data.decode())
    
    await nc.subscribe("agent.result.A1", cb=result_handler)
    await asyncio.sleep(10)
    await nc.close()

asyncio.run(test_a1())
```

### 3. 端到端测试
```bash
# 通过 MC Backend 创建需求，触发完整流程
curl -X POST http://172.27.78.109:8000/requirements \
  -H "Content-Type: application/json" \
  -d '{
    "title": "订单管理系统",
    "description": "开发订单CRUD功能，支持管理员和用户操作"
  }'

# 查看 A1 执行结果
curl http://172.27.78.109:8000/requirements/{req_id}
```

## 性能指标

### 正常场景
- **LLM 响应时间**: 2-5 秒（DeepSeek）
- **Fallback 响应时间**: <100ms
- **成功率**: >95%（LLM 可用时）

### 异常场景
- **LLM 超时**: 30 秒后 fallback（由 LLM Provider 控制）
- **LLM 服务不可用**: 直接 fallback，不阻塞流程

## 改进建议

### 短期（P1）
1. 扩展 `DOMAIN_KEYWORDS` 词典到 100+ 关键词
2. 增加 JSON 解析容错（支持 json5）
3. 添加单元测试覆盖（pytest）

### 中期（P2）
1. Context Builder 统一输入字段为 `message`
2. Entity 提取改为纯 LLM 模式（Fallback 不提取）
3. 增加"需求澄清"交互（如需求过于模糊时返回 `status: "blocked"` + 澄清问题列表）

### 长期（P3）
1. 支持多轮对话式需求分析（类似 Claude Code 的 /ask 模式）
2. 接入知识库（A2）提供历史需求相似度匹配
3. 输出增加"需求风险评分"（0-100）用于 Gate 0 决策
