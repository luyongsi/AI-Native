# A3 UI 原型 Agent — 完整开发设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 开发设计（已通过 critical 审计）
- **参考**: [A3 完整设计规格](../Agent规格/A3-UI原型Agent完整设计.md) · [阶段二数据字典](../Agent规格/阶段二-数据字典.md) · [系统状态机 v2.4](../系统架构/系统状态机与信息流设计.md)
- **原则**: 以数据字典为唯一数据规范源；A3 从纯 NATS Worker 改造为 HTTP+SSE 双通道 Agent

---

## 一、现状分析与改造范围

### 1.1 当前实现 vs 目标架构

| 维度 | 当前实现 (`a3_ui_generator.py`) | 目标架构（规格 v1.0） | 差距 |
|------|-------------------------------|---------------------|------|
| **触发方式** | NATS `context.ready.A3` → `execute()` | HTTP+SSE（用户主动发起）+ NATS（打回收调度） | 需新增 MC Backend 路由层 |
| **用户交互** | 无（一次性生成） | 多轮标注迭代（生成→标注→修改→确认） | 需新增 SSE Stream + 标注 API |
| **产物存储** | `report_artifact()` 内存缓存 | `prototype_artifacts` 表 + `agent_results` 表 + S3 | 需新增 DB 写入 + S3 上传 |
| **版本管理** | 无 | 每次标注 version+=1，历史版本保留 | 需实现版本递增逻辑 |
| **NATS 发布** | `prototype.generated.{req_id}`（自定义 topic） | `agent.result.A3`（统一规范） | topic 名不对齐 |
| **确认机制** | 无 | `POST /api/prototype/confirm` 事务性确认 | 需新增确认 API |
| **打回处理** | 无 | Gate1 `a3_rework=true` → `context.ready.A3` → 原型页面 REOPENED | 需新增打回路由 |

### 1.2 现有可用模块

A3 子包 `repos/agent-workers/a3/` 已有以下模块。注意：这些模块的**实际接口与目标架构不一致**，需整体改造而非简单复用：

| 模块 | 文件 | 实际接口 | 目标接口 | 改造要点 |
|------|------|---------|---------|---------|
| `design_token_mapper` | `design_token_mapper.py` | `map_to_tokens(components, token_system) -> dict` | `map_domain(domain: str) -> dict` | 改签名为按领域映射 |
| `prototype_builder` | `prototype_builder.py` | `build(design_tokens, wireframe) -> dict`（同步） | `build(draft, templates, design_system) -> AsyncIterator[str]` | 全面重写为流式 |
| `annotation_handler` | `annotation_handler.py` | `process_annotation(annotation, current_design) -> dict` | `parse(annotations: list) -> dict` + `apply(current_html, parsed) -> AsyncIterator[str]` | 拆分为解析+应用两阶段 |
| `visual_diff` | `visual_diff.py` | 类名为 `VisualDiffer` | 类名 `VisualDiff`，接口相同 | 重命名类 |

> **结论**：四个模块均需要不同程度的重写。A3 的 HTTP+SSE 改造是全新的交互模式，现有 NATS Worker 代码可作为 LLM prompt 构造的参考，但不能直接复用。

---

## 二、数据库设计

### 2.1 新建 `prototype_artifacts` 表

```sql
CREATE TABLE prototype_artifacts (
    id              BIGSERIAL PRIMARY KEY,
    req_id          UUID NOT NULL REFERENCES requirements(id),
    cycle           INT NOT NULL DEFAULT 0,
    version         INT NOT NULL DEFAULT 1,
    prototype_url   TEXT,
    html_content    TEXT,
    screens         JSONB DEFAULT '[]'::jsonb,
    annotations     JSONB DEFAULT '[]'::jsonb,
    status          VARCHAR(20) DEFAULT 'draft',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (req_id, cycle, version)
);

CREATE INDEX idx_prototype_artifacts_req ON prototype_artifacts(req_id, cycle, version DESC);
```

**版本管理逻辑**：
- 首次 `POST /api/prototype/generate` → INSERT version=1, status='draft'
- 每次 `POST /api/prototype/annotate` → 读取 MAX(version)，INSERT 新行 version+1
- `POST /api/prototype/confirm` → UPDATE 当前 MAX(version) 行 status='confirmed'

### 2.2 requirements 表扩展

阶段二数据字典已定义，需在 migration 中追加：

```sql
ALTER TABLE requirements ADD COLUMN IF NOT EXISTS phase VARCHAR(20) DEFAULT 'requirement';
ALTER TABLE requirements ADD COLUMN IF NOT EXISTS design_status VARCHAR(30);
ALTER TABLE requirements ADD COLUMN IF NOT EXISTS design_revision_count INT DEFAULT 0;
```

### 2.3 agent_results 写入

确认时在同一事务中：

```sql
INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
VALUES ($1, 'A3', $2, 'completed', $3)
ON CONFLICT (req_id, agent_key, cycle) DO UPDATE
  SET artifact=EXCLUDED.artifact, status='completed', created_at=NOW();
-- artifact = {"prototype_url": "...", "screens": [...], "version": N, "annotation_count": M}
```

---

## 三、API 设计

### 3.0 认证

所有面向用户的 API 使用 **JWT Bearer Token**。`creator_user_id` 从 JWT claims 的 `sub` 提取。

### 3.1 `GET /api/prototype/context/{req_id}`

**职责**: 获取原型页面的完整上下文（需求摘要 + 当前原型状态）。

**响应** (200):
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "design_status": "prototyping",
  "requirement_summary": {
    "title": "用户管理系统",
    "domain": "企业后台",
    "acceptance_criteria": ["Given ... When ... Then ..."]
  },
  "prototype": {
    "has_existing": true,
    "current_version": 3,
    "status": "draft",
    "prototype_url": "https://s3/xxx/prototype_v3.html",
    "screens": [{"name": "列表页", "state": "default", "description": "用户列表含搜索和分页", "url": "https://s3/xxx/screen_list.png"}],
    "annotations": [{"annotation_id": "uuid", "element_id": "#table", "type": "layout_change", "comment": "..."}]
  },
  "revision_context": {"is_revision": false, "gate1_rejection": null}
}
```

当 Gate1 打回时，`revision_context` 填充：
```json
{
  "revision_context": {
    "is_revision": true,
    "gate1_rejection": {
      "reject_reasons": [{"category": "prototype_change_needed", "description": "..."}],
      "revision_guidance": "..."
    }
  }
}
```

**处理逻辑**:
1. 查询 `requirements` WHERE req_id → phase, design_status
2. 查询 `prototype_artifacts` WHERE req_id ORDER BY version DESC LIMIT 1
3. 若有 Gate1 打回记录（design_status='prototyping' + design_revision_count>0），查询 `approvals` WHERE gate_level=1 AND decision='reject' 获取最新拒绝原因
4. 组装返回

### 3.2 `POST /api/prototype/generate`

**职责**: 启动/重新生成原型（SSE Stream）。

**请求体**:
```json
{
  "req_id": "uuid",
  "session_id": "uuid"
}
```

**处理逻辑**:
1. 校验 `requirements.phase='design'` 且 `design_status='prototyping'`
2. 读取 A1 草案：`requirements.requirement_draft`
3. 读取 A2 分析：`agent_results` WHERE agent_key='A2' AND cycle=MAX
4. 读取 A1 线框图（如有）：`agent_results` WHERE agent_key='A1' → artifact.wireframe_url
5. 并行调用 MCP 知识库（5s 超时）：
   - `get_ui_templates(domain)` → UI 模板库
   - `get_design_system(platform='web')` → 设计系统组件
6. 构造 System Prompt（注入需求上下文 + MCP 结果）
7. 调用 LLM Stream，SSE 逐步返回

**SSE 事件流**:
```
event: thinking
data: {"message": "正在分析需求，匹配合适的UI模板..."}

event: knowledge
data: {"templates": [{"name": "后台管理模板", "match_score": 0.9}], "components": ["Table", "SearchBar", "Modal"]}

event: prototype_update
data: {"html_chunk": "<div class=\"header\">...", "progress": 0.3}

event: screens
data: {"screens": [{"name": "列表页-默认状态", "state": "default", "url": "https://s3/xxx/screen_default.png"}]}

event: done
data: {"prototype_url": "https://s3/xxx/prototype_v1.html", "version": 1, "screens": [...]}

event: error
data: {"message": "生成失败，已降级到模板模式"}
```

**完成后持久化**（非事务，在 done 事件前）:
1. 上传 HTML 到 S3 → 获取 `prototype_url`
2. 生成多状态截图，上传 S3 → 获取 `screens[].url`
3. INSERT INTO `prototype_artifacts`（version=已有 MAX+1，或 1）

### 3.3 `POST /api/prototype/annotate`

**职责**: 提交标注，获取更新后的原型（SSE Stream）。

**请求体**:
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "annotations": [
    {
      "annotation_id": "uuid",
      "element_id": "#user-table-header",
      "type": "layout_change",
      "comment": "表格列宽需要调整为三列等宽",
      "position": {"x": 120, "y": 45}
    }
  ]
}
```

> `created_at` 由服务端在写入 DB 时自动生成（`NOW()`），不需要客户端传入。

**处理逻辑**:
1. 读取当前 MAX(version) 的 prototype_artifacts 行
2. 将新标注 append 到 annotations JSONB 数组
3. 读取当前 HTML 内容（从 S3 或 `html_content` 字段）
4. 构造 System Prompt（当前 HTML + 新标注 + 标注历史）
5. 调用 LLM Stream 生成增量更新 → SSE 返回
6. INSERT 新行 version=MAX+1，含更新后的 HTML + 完整 annotations 历史

**SSE 事件流**:
```
event: thinking
data: {"message": "正在解析标注..."}

event: annotation_parsed
data: {"parsed": [{"annotation_id": "uuid", "intent": "调整表格列宽为三列等宽"}]}

event: prototype_update
data: {"html_chunk": "<style>#user-table .col { width: 33.3%; }</style>", "progress": 0.5}

event: done
data: {"prototype_url": "https://s3/xxx/prototype_v4.html", "version": 4}
```

### 3.4 `POST /api/prototype/confirm`

**职责**: 确认原型定稿，持久化并发布 NATS。

**请求体**:
```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "final_notes": "原型确认，无额外修改意见（可选）"
}
```

**处理逻辑**（同一数据库事务）:
```
BEGIN
  1. UPDATE prototype_artifacts
     SET status='confirmed', updated_at=NOW()
     WHERE req_id=? AND version=(SELECT MAX(version) FROM prototype_artifacts WHERE req_id=? AND cycle=?)

  2. INSERT INTO agent_results (req_id, agent_key='A3', cycle, status='completed', artifact)
     VALUES (?, 'A3', ?, 'completed', ?::jsonb)
     -- artifact = {prototype_url, screens, version, annotation_count}

  3. UPDATE requirements SET design_status='spec_writing'
     WHERE id=?

  4. INSERT INTO event_log (req_id, session_id, cycle, event_name='agent.result.A3', direction='OUT', payload, outbox_status='pending')
COMMIT
```

**幂等保护**: 与 A4/A5 策略一致，使用 `INSERT ... ON CONFLICT (req_id, agent_key, cycle) DO UPDATE`（UPSERT）。A3 返工场景下同一 cycle 内重新确认，静默覆盖旧记录并返回 200。

### 3.5 `GET /api/prototype/history/{req_id}`

**职责**: 查看原型版本历史。

**响应** (200):
```json
{
  "req_id": "uuid",
  "versions": [
    {
      "version": 4,
      "status": "confirmed",
      "prototype_url": "https://s3/xxx/prototype_v4.html",
      "annotations": [{"annotation_id": "...", "type": "layout_change", "comment": "..."}],
      "created_at": "ISO 8601"
    },
    {
      "version": 3,
      "status": "draft",
      "prototype_url": "https://s3/xxx/prototype_v3.html",
      "annotations": [],
      "created_at": "ISO 8601"
    }
  ]
}
```

---

## 四、MC Backend 路由层

### 4.1 路由注册

```python
# mc-backend/api/prototype.py

router = APIRouter(prefix="/api/prototype", tags=["prototype"])

@router.get("/context/{req_id}")
async def get_prototype_context(req_id: str, current_user: User = Depends(get_current_user)):
    """获取原型页面上下文"""
    ...

@router.post("/generate")
async def generate_prototype(req: PrototypeGenerateRequest, current_user: User = Depends(get_current_user)):
    """启动原型生成（SSE Stream）"""
    return StreamingResponse(
        a3_service.generate_prototype_stream(req.req_id, req.session_id),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
    )

@router.post("/annotate")
async def annotate_prototype(req: PrototypeAnnotateRequest, current_user: User = Depends(get_current_user)):
    """提交标注（SSE Stream）"""
    return StreamingResponse(
        a3_service.handle_annotation_stream(req.req_id, req.session_id, req.annotations),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
    )

@router.post("/confirm")
async def confirm_prototype(req: PrototypeConfirmRequest, current_user: User = Depends(get_current_user)):
    """确认原型定稿"""
    ...

@router.get("/history/{req_id}")
async def get_prototype_history(req_id: str, current_user: User = Depends(get_current_user)):
    """查看原型版本历史"""
    ...
```

### 4.2 SSE 格式化器

```python
# mc-backend/services/sse_formatter.py — 共享工具，A1 和 A3 共用

def format_sse_event(event_type: str, data: dict) -> str:
    """将 dict 格式化为 SSE 事件字符串。A1 和 A3 均使用此函数。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
```

---

## 五、A3 Agent 核心改造

### 5.1 子模块接口

| 模块 | 文件 | 签名 | 职责 |
|------|------|------|------|
| `PrototypeBuilder` | `a3/prototype_builder.py` | `build(draft, templates, design_system) -> AsyncIterator[str]` | LLM 流式生成 HTML 原型 |
| `AnnotationHandler` | `a3/annotation_handler.py` | `parse(annotations: list) -> dict` | 解析标注为结构化 UI 需求 |
| `AnnotationHandler` | | `apply(current_html: str, parsed: dict) -> AsyncIterator[str]` | LLM 增量更新 HTML |
| `DesignTokenMapper` | `a3/design_token_mapper.py` | `map_domain(domain: str) -> dict` | 领域→设计 Token 映射 |
| `VisualDiff` | `a3/visual_diff.py` | `compare(v1_url, v2_url) -> dict` | 版本间视觉差异 |

### 5.2 原型生成器核心流程

```python
# a3/prototype_builder.py — 扩展版

class PrototypeBuilder:
    async def build_stream(
        self,
        draft: dict,
        templates: list[dict],
        design_system: dict,
        revision_context: dict | None = None
    ) -> AsyncIterator[tuple[str, dict]]:
        """
        Yields (event_type, payload) tuples for SSE streaming.

        Pipeline:
        1. Load context (draft + A2 + MCP results)
        2. Construct system prompt with domain-specific design tokens
        3. Stream LLM response → yield 'thinking', 'prototype_update', 'done'
        """
        # Phase 1: thinking
        yield ('thinking', {'message': '正在分析需求结构...'})

        # Phase 2: knowledge (if MCP results available)
        if templates or design_system:
            yield ('knowledge', {
                'templates': templates,
                'design_system': design_system
            })

        # Phase 3: generate HTML stream
        prompt = self._build_prompt(draft, templates, design_system, revision_context)
        html_buffer = []

        async for chunk in self.llm.stream(prompt, temperature=0.4, max_tokens=8000):
            html_buffer.append(chunk)
            yield ('prototype_update', {
                'html_chunk': chunk,
                'progress': min(len(''.join(html_buffer)) / 8000, 0.95)
            })

        # Phase 4: upload to S3
        html = ''.join(html_buffer)
        url = await self.s3.upload(html, f"prototypes/{req_id}/v{version}.html")

        # Phase 5: generate screenshots
        screens = await self.screenshotter.capture_states(url)

        yield ('screens', {'screens': screens})
        yield ('done', {
            'prototype_url': url,
            'version': version,
            'screens': screens
        })

    def _build_prompt(self, draft, templates, design_system, revision_context) -> str:
        """构建 System Prompt，注入需求上下文 + MCP 知识 + 修订反馈"""
        ...
```

### 5.3 S3 上传服务

```python
# mc-backend/services/s3_service.py

class S3PrototypeStorage:
    """原型文件存储服务"""

    async def upload_html(self, req_id: str, version: int, html: str) -> str:
        """上传 HTML 到 S3，返回公开 URL"""
        key = f"prototypes/{req_id}/v{version}.html"
        await self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=html.encode(),
            ContentType='text/html; charset=utf-8'
        )
        return f"{self.base_url}/{key}"

    async def upload_screenshot(self, req_id: str, version: int, state: str, png_bytes: bytes) -> str:
        """上传截图到 S3"""
        key = f"prototypes/{req_id}/v{version}/screens/{state}.png"
        await self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=png_bytes,
            ContentType='image/png'
        )
        return f"{self.base_url}/{key}"
```

**降级策略**: S3 不可用时，HTML 以 Base64 inline 方式存入 `prototype_artifacts.html_content`，`prototype_url` 设为 null，标注 `upload_failed=true`。

---

## 六、NATS 集成

### 6.1 MC Backend 订阅 `context.ready.A3`

MC Backend 在启动时订阅此 topic，收到消息后：

```python
# mc-backend/services/nats_service.py

async def on_context_ready_a3(msg):
    data = json.loads(msg.data)
    req_id = data['req_id']
    session_id = data['session_id']
    cycle = data['cycle']

    if data.get('revision_context', {}).get('is_revision'):
        # Gate1 打回 A3 返工
        async with db.transaction():
            # 更新 dialogue_sessions: status='reopened'
            await db.execute(
                "UPDATE dialogue_sessions SET status='reopened', last_updated=NOW() WHERE req_id=$1",
                req_id
            )
            # 注入 system 消息到 dialogue_messages
            rejection = data['revision_context']['gate1_rejection']
            await db.execute(
                "INSERT INTO dialogue_messages (session_id, role, content, cycle, sequence_number) "
                "VALUES ((SELECT id FROM dialogue_sessions WHERE req_id=$1), 'system', $2, $3, "
                "(SELECT COALESCE(MAX(sequence_number),0)+1 FROM dialogue_messages WHERE session_id=(SELECT id FROM dialogue_sessions WHERE req_id=$1)))",
                req_id,
                json.dumps({
                    'type': 'gate1_rejection',
                    'reject_reasons': rejection['reject_reasons'],
                    'revision_guidance': rejection['revision_guidance'],
                    'gate_level': 1
                }),
                cycle
            )

        # WebSocket 通知前端（Redis Pub/Sub 跨实例）
        await redis.publish(f"user:{user_id}", json.dumps({
            'type': 'prototype_revision_required',
            'req_id': req_id,
            'revision_guidance': rejection['revision_guidance']
        }))
```

### 6.2 Outbox Publisher 发布 `agent.result.A3`

确认接口写入 `event_log`（outbox_status='pending'）后，Outbox Publisher 定时轮询并发布：

```python
# mc-backend/services/outbox_publisher.py

async def publish_pending():
    rows = await db.fetch(
        "SELECT id, event_name, payload FROM event_log "
        "WHERE outbox_status='pending' ORDER BY created_at LIMIT 50"
    )
    for row in rows:
        try:
            await nats.publish(row['event_name'], json.dumps(row['payload']).encode())
            await db.execute(
                "UPDATE event_log SET outbox_status='published', published_at=NOW() WHERE id=$1",
                row['id']
            )
        except Exception as e:
            # 重试 5 次（指数退避），然后标记 failed
            ...
```

---

## 七、前端集成

### 7.1 原型页面组件

```
frontend/src/pages/prototype/
├── PrototypeWorkspace.tsx    # 主工作区（双栏：原型预览 + 标注面板）
├── PrototypeViewer.tsx       # iframe 嵌入 S3 原型
├── AnnotationPanel.tsx       # 标注工具面板（类型选择 + 评论输入）
├── AnnotationBubble.tsx      # 原型上的标注气泡组件
├── StateSwitcher.tsx         # 状态切换器（default/loading/empty/error/hover/active）
├── VersionHistory.tsx        # 版本历史列表
└── PrototypeConfirm.tsx      # 确认定稿按钮 + 最终备注
```

### 7.2 SSE 事件处理

```typescript
// frontend/src/services/prototype-sse.ts

type SSEEventHandler = {
  thinking: (data: { message: string }) => void;
  knowledge: (data: { templates: any[]; design_system: any }) => void;
  prototype_update: (data: { html_chunk: string; progress: number }) => void;
  annotation_parsed: (data: { parsed: any[] }) => void;
  screens: (data: { screens: any[] }) => void;
  done: (data: { prototype_url: string; version: number }) => void;
  error: (data: { message: string }) => void;
};

async function streamPrototypeGeneration(
  apiUrl: string,
  body: object,
  handlers: SSEEventHandler,
  signal: AbortSignal
): Promise<void> {
  const response = await fetch(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify(body),
    signal,
  });

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    let currentEvent = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ') && currentEvent) {
        const data = JSON.parse(line.slice(6));
        handlers[currentEvent]?.(data);
        currentEvent = '';
      }
    }
  }
}
```

### 7.3 标注交互流程

```
用户在原型预览区点击元素
  → 弹出 AnnotationBubble（浮层）
  → 选择标注类型（layout_change / content_change / style_change / add_element / remove_element / flow_change）
  → 输入修改意见
  → 点击"提交标注"
  → POST /api/prototype/annotate → SSE Stream
  → 原型预览区收到增量更新 → 热刷新 iframe
  → 标注历史面板追加新记录
```

---

## 八、异常处理

| 场景 | 策略 |
|------|------|
| LLM API 不可用 | 降级到 `_fallback_html()` 生成预设模板，标注 `source='fallback'` |
| MCP 知识库超时（5s） | 跳过知识增强，仅用需求上下文 |
| S3 上传失败 | HTML 以 Base64 inline 存入 `html_content`，`prototype_url=null`，`upload_failed=true` |
| 标注解析失败 | 返回 `annotation_parsed` 事件含 errors，标注保留但标注处理失败 |
| 并发 confirm | SELECT FOR UPDATE 锁 prototype_artifacts 当前行；幂等检查 agent_results 已存在 |
| SSE 连接中断 | finally 块持久化已生成的 HTML 到 prototype_artifacts；标记 `status='draft'` |
| NATS 投递失败 | Outbox 重试 5 次（指数退避 1s/2s/4s/8s/16s），failed 后需人工重置 |

---

## 九、实施计划

### Phase 1：基础流程（~5 天）
- [ ] DB migration：prototype_artifacts 建表 + requirements 加列
- [ ] MC Backend 路由：`GET /api/prototype/context`、`POST /api/prototype/generate`（SSE）
- [ ] A3 PrototypeBuilder 改造：流式 LLM 生成 + S3 上传
- [ ] 前端 PrototypeWorkspace（原型查看 + 状态切换）
- [ ] Fallback 模板（3-5 套后台/移动端/数据看板模板）

### Phase 2：标注迭代（~4 天）
- [ ] MC Backend 路由：`POST /api/prototype/annotate`（SSE）+ `GET /api/prototype/history`
- [ ] A3 AnnotationHandler 改造：LLM 增量更新
- [ ] 前端 AnnotationPanel + AnnotationBubble + VersionHistory
- [ ] `POST /api/prototype/confirm`（事务性确认 + Outbox）

### Phase 3：MCP 增强 + Gate1 集成（~3 天）
- [ ] MCP Gateway 注册 `get_ui_templates`、`get_design_system`（需参照 A2 MCP改造设计新增工具定义 + KnowledgeClient 方法 + ToolRouter 路由）
- [ ] A3 生成流程中调用 MCP（`asyncio.gather` 并行 5s 超时）
- [ ] MC Backend 订阅 `context.ready.A3`（Gate1 打回路由）
- [ ] 多状态截图自动生成（Puppeteer/Playwright headless）
- [ ] E2E 全链路：Gate0 pass → A3 → A4 → A5 → Gate1 pass/reject(a3_rework)

---

## 十、关键设计决策

| 决策 | 理由 |
|------|------|
| A3 走 HTTP+SSE 而非纯 NATS | A3 是用户交互密集型（标注迭代），需要实时 SSE 反馈 |
| 原型 HTML 存 S3 而非 DB | HTML 体积大（10-50KB），S3 更合适；仅在 S3 不可用时 fallback 到 DB |
| prototype_artifacts 每版一行 | 版本历史全保留，支持 diff 对比和回退 |
| confirm 时仅标记最新版，不删旧版 | 审计需求——可追溯完整迭代过程 |
| Gate1 打回 A3 时 cycle 不变 | cycle 只计 Gate0 打回；阶段内迭代用 design_revision_count |
| MSE 事件使用标准 SSE 格式 | `event:` + `data:` 双行格式，浏览器 EventSource 原生支持 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
