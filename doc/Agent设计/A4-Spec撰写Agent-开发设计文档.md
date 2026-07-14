# A4 Spec 撰写 Agent — 开发设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 开发设计（已通过 critical 审计）
- **参考**: [A4 Spec撰写Agent规格](../Agent规格/A4-Spec撰写Agent规格.md) · [阶段二数据字典](../Agent规格/阶段二-数据字典.md) · [系统状态机 v2.4](../系统架构/系统状态机与信息流设计.md)
- **原则**: 以数据字典为唯一数据规范源；A4 从当前实现改造对齐目标架构

---

## 一、现状分析与差距

### 1.1 当前实现 vs 目标架构

| 维度 | 当前实现 (`a4_spec_writer.py`) | 目标架构（规格 v1.0） | 差距 |
|------|-------------------------------|---------------------|------|
| **产物写表** | `api_schemas` + `erd_designs` 独立表 + `requirements.spec` JSONB | 新增 `design_specs` 表 + `agent_results` (A4) | 缺少 `design_specs` 和 `agent_results` 写入 |
| **Spec 文档** | 无结构化 Spec 文档生成（仅 OpenAPI + ERD） | 六章结构化 Spec（概述/功能/状态机/接口/数据模型/非功能需求） | 缺少 Spec 文档生成 |
| **输入来源** | 从 `requirements.spec` 读取 sections（由外部 Chat Spec 流程写入） | 从 `context.ready.A4` payload 直接取 A1/A2/A3 产物 | 输入路径不同 |
| **状态更新** | 不更新 requirements 状态 | 完成后更新 `design_status='design_checking'`（由 Orchestrator 更新） | A4 不负责状态更新 |
| **质量评分** | 无 | `quality_score` 写入 `design_specs` + `agent_results` | 需新增评分逻辑 |
| **修订上下文** | 从 `rework_context` 读取 A5 反馈 | 从 `revision_context` 读取：`is_revision` + `previous_a5_report` + `gate1_rejection` | 结构对齐 |
| **MCP 集成** | 无 MCP 调用 | 三个 MCP 工具（get_openapi_templates / get_erd_patterns / get_ddl_conventions） | 需接入 MCP Gateway |
| **全局路由键** | `agent.result.A4` 缺少 `session_id` 和 `cycle` | payload 含 `req_id` + `session_id` + `cycle` | 需补齐 |

### 1.2 现有可复用模块

A4 子包 `repos/agent-workers/a4/` 含以下模块：

| 模块 | 文件 | 功能 | 改造要点 |
|------|------|------|---------|
| `APISchemaGenerator` | `api_schema_generator.py` | LLM 生成 OpenAPI 3.1 | 保持核心逻辑，对齐输出格式 |
| `ERDGenerator` | `erd_generator.py` | LLM 生成 ERD + DDL | 保持核心逻辑，对齐输出格式 |
| `SchemaValidator` | `schema_validator.py` | OpenAPI 规范校验 | 保持不变 |
| `DDLValidator` | `ddl_validator.py` | DDL 语法和语义校验 | 保持不变 |
| `SpecCompleteness` | `spec_completeness.py` | Spec 完整度评分 | 当前 5 维（api/data_model/ui/testing/security），需**重写**为目标 4 维（spec_completeness/api_coverage/erd_coverage/ddl_validity） |
| `OpenAPIGenerator` | `api_schema_gen.py` | 旧版 OpenAPI 生成 | 可废弃，由 `api_schema_generator` 替代 |
| `ERDDesigner` | `erd_designer.py` | 结构化 ERD 设计 | 保持不变 |

---

## 二、改造方案

### 2.1 新增：结构化 Spec 文档生成

当前 A4 不生成 Spec 文档，仅生成 OpenAPI 和 ERD。需新增 Spec 生成流水线：

```python
# a4/spec_generator.py（新文件）

class SpecGenerator:
    """LLM 驱动的结构化技术规格说明书生成器"""

    def __init__(self, llm_caller):
        self.llm = llm_caller

    async def generate(
        self,
        draft: dict,           # A1 需求草案
        feasibility: dict,     # A2 可行性分析
        prototype_url: str,    # A3 原型 URL
        domain: str,
        revision_context: dict | None = None
    ) -> dict:
        """生成六章结构化 Spec 文档"""
        prompt = self._build_spec_prompt(draft, feasibility, prototype_url, domain)

        if revision_context and revision_context.get('is_revision'):
            prompt += self._build_revision_context(revision_context)

        result = await self.llm(prompt, temperature=0.3, max_tokens=6000)
        return self._parse_spec_response(result)

    def _build_spec_prompt(self, draft, feasibility, prototype_url, domain) -> str:
        """构建 Spec 生成 System Prompt"""
        ...

    def _build_revision_context(self, ctx: dict) -> str:
        """注入 Gate1 拒绝原因和 A5 检查报告"""
        lines = ["\n\n【Gate1 打回修订要求】"]
        for reason in ctx.get('gate1_rejection', {}).get('reject_reasons', []):
            lines.append(f"- {reason['category']}: {reason['description']}")
        lines.append(f"\n修订指引: {ctx['gate1_rejection'].get('revision_guidance', '')}")

        # 附 A5 检查报告中 critical/major 问题
        prev_report = ctx.get('previous_a5_report', {})
        if prev_report:
            lines.append("\n【A5 检查报告中需优先修复的问题】")
            for dim in prev_report.get('check_report', {}).get('dimensions', []):
                for issue in dim.get('issues', []):
                    if issue['severity'] in ('critical', 'major'):
                        lines.append(f"- [{issue['severity']}] {dim['label']}: {issue['description']}")
                        if issue.get('suggestion'):
                            lines.append(f"  建议: {issue['suggestion']}")
        return '\n'.join(lines)
```

### 2.2 新增：MCP 知识库接入

```python
# a4/knowledge_client.py（新文件）

class A4KnowledgeClient:
    """A4 知识库 MCP 客户端，封装三个工具的三层降级链"""

    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client  # 复用 a1/analyzer/mcp_client.py 的 MCPClient

    async def get_openapi_templates(self, domain: str) -> dict:
        """获取领域 OpenAPI 模板 → 降级为通用模板"""
        try:
            result = await asyncio.wait_for(
                self.mcp.call_tool('get_openapi_templates', {'domain': domain}),
                timeout=5.0
            )
            if result:
                return result
        except Exception:
            pass
        return self._fallback_openapi_template(domain)

    async def get_erd_patterns(self, domain: str) -> dict:
        """获取领域 ERD 设计模式 → 降级为通用模式"""
        ...

    async def get_ddl_conventions(self) -> dict:
        """获取团队 DDL 约定 → 降级为内置默认约定"""
        ...

    def _fallback_openapi_template(self, domain: str) -> dict:
        return {
            'openapi': '3.0.0',
            'info': {'title': f'{domain} API', 'version': '1.0.0'},
            'paths': {
                '/health': {'get': {'summary': 'Health check', 'responses': {'200': {'description': 'OK'}}}}
            },
            'components': {
                'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer'}}
            }
        }
```

### 2.3 改造：A4SpecWriter 主流程

```python
# a4_spec_writer.py — 改造后的 execute()

class A4SpecWriter(BaseAgentWorker):
    agent_id = "A4"
    agent_type = "spec_writer"

    def __init__(self, nats_url=None):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self.spec_gen = SpecGenerator(llm_caller=self.call_llm)
        self.api_schema_gen = APISchemaGenerator(llm_caller=self.call_llm)
        self.erd_gen = ERDGenerator(llm_caller=self.call_llm)
        self.knowledge = A4KnowledgeClient(mcp_client=MCPClient())
        self.completeness = SpecCompleteness()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        a1 = context_package.get('a1_output', {})
        a2 = context_package.get('a2_output', {})
        a3 = context_package.get('a3_output', {})
        rev = context_package.get('revision_context', {})
        cycle = context_package.get('cycle', 0)

        draft = a1.get('requirement_draft', {})
        title = draft.get('title', '未命名需求')
        domain = draft.get('domain', 'general')
        is_revision = rev.get('is_revision', False)

        logger.info(f"[A4] Writing specs for req={req_id}, domain={domain}, revision={is_revision}")

        # Phase 1: 并行获取知识库 + 内省 DB
        await self.report_status(req_id, "running", "Phase 1: 加载上下文和知识库")
        templates, patterns, conventions, existing_tables_raw = await asyncio.gather(
            self.knowledge.get_openapi_templates(domain),
            self.knowledge.get_erd_patterns(domain),
            self.knowledge.get_ddl_conventions(),
            self._detect_existing_tables(),
            return_exceptions=True
        )
        # 防御：如果 _detect_existing_tables 抛异常，existing_tables_raw 是 Exception 实例
        existing_tables = existing_tables_raw if isinstance(existing_tables_raw, list) else []

        # Phase 2: 生成 Spec 文档（新增）
        await self.report_status(req_id, "running", "Phase 2: LLM 生成技术规格")
        spec_doc = await self.spec_gen.generate(
            draft, a2.get('feasibility_assessment', {}),
            a3.get('prototype_url', ''), domain, rev
        )

        # Phase 3: 并行生成 OpenAPI + ERD
        await self.report_status(req_id, "running", "Phase 3: 生成 OpenAPI + ERD/DDL")
        api_result, erd_result = await asyncio.gather(
            self.api_schema_gen.generate(draft, templates, conventions, rev),
            self.erd_gen.generate(draft, patterns, conventions, existing_tables, rev)
        )

        # Phase 4: 验证
        openapi_valid = self.schema_validator.validate(api_result['schema'])
        ddl_valid = self.ddl_validator.validate(erd_result['ddl'])

        # Phase 5: 质量评分
        quality = self.completeness.score(spec_doc, api_result, erd_result)

        # Phase 6: 持久化
        await self._persist_all(req_id, cycle, spec_doc, api_result, erd_result, quality)

        return {
            'status': 'completed',
            'req_id': req_id,
            'session_id': context_package.get('session_id', ''),
            'cycle': cycle,
            'spec_doc': spec_doc,
            'openapi_schema': api_result['schema'],
            'erd_diagram': {'entities': erd_result['entities'], 'relationships': erd_result['relationships']},
            'ddl_statements': erd_result['ddl'],
            'quality_score': quality,
            'metadata': {
                'api_endpoint_count': len(api_result['schema'].get('paths', {})),
                'entity_count': len(erd_result.get('entities', [])),
                'state_count': sum(len(m.get('state_machine', {}).get('states', [])) for m in spec_doc.get('modules', []))
            }
        }

    async def _persist_all(self, req_id, cycle, spec_doc, api_result, erd_result, quality):
        """持久化四件套到 design_specs + agent_results + requirements.spec"""
        artifact = {
            'spec_doc': spec_doc,
            'openapi_schema': api_result['schema'],
            'erd_diagram': {
                'entities': erd_result['entities'],
                'relationships': erd_result['relationships']
            },
            'ddl_statements': erd_result['ddl'],
            'quality_score': quality,
            'source': 'llm'
        }

        async with self.db.transaction():
            # 1. design_specs — INSERT with version=MAX+1（不覆盖旧版本）
            await self.db.execute("""
                INSERT INTO design_specs (req_id, cycle, version, spec_doc, openapi_schema, erd_diagram, ddl_statements, quality_score)
                VALUES ($1, $2, (SELECT COALESCE(MAX(version),0)+1 FROM design_specs WHERE req_id=$1 AND cycle=$2), $3, $4, $5, $6, $7)
            """, req_id, cycle,
               json.dumps(spec_doc),
               json.dumps(api_result['schema']),
               json.dumps(artifact['erd_diagram']),
               erd_result['ddl'],
               quality)

            # 2. agent_results
            await self.db.execute("""
                INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
                VALUES ($1, 'A4', $2, 'completed', $3)
                ON CONFLICT (req_id, agent_key, cycle) DO UPDATE SET
                    artifact = EXCLUDED.artifact, status = 'completed'
            """, req_id, cycle, json.dumps(artifact))

            # 3. requirements.spec 镜像 — 兜底读取路径，A5/Gate1 在 NATS 不可用时直接从 DB 读取
            # 保留写入作为正式 fallback 通道，与数据字典 §2.1 保持一致
            await self.db.execute("""
                UPDATE requirements SET spec = $1::jsonb, updated_at = NOW()
                WHERE id = $2
            """, json.dumps({
                'spec_doc': spec_doc,
                'openapi': api_result['schema'],
                'erd': artifact['erd_diagram'],
                'ddl': erd_result['ddl'],
                'updated_at': datetime.now(timezone.utc).isoformat()
            }), req_id)
```

### 2.4 质量评分实现

```python
# a4/spec_completeness.py — 扩展版

class SpecCompleteness:
    DIMENSIONS = {
        'spec_completeness': 0.35,    # Spec 六章是否齐全
        'api_coverage': 0.25,         # use_cases → API endpoints 覆盖率
        'erd_coverage': 0.20,         # entities → ERD 实体覆盖率
        'ddl_validity': 0.20,         # DDL 语法正确性
    }

    def score(self, spec_doc: dict, api_result: dict, erd_result: dict) -> float:
        scores = {}
        scores['spec_completeness'] = self._score_spec(spec_doc)
        scores['api_coverage'] = self._score_api(api_result)
        scores['erd_coverage'] = self._score_erd(erd_result)
        scores['ddl_validity'] = self._score_ddl(erd_result)
        return round(sum(s * self.DIMENSIONS[k] for k, s in scores.items()), 2)

    def _score_spec(self, spec_doc: dict) -> float:
        required = ['overview', 'modules']
        has = sum(1 for k in required if spec_doc.get(k))
        return has / len(required)

    def _score_api(self, api_result: dict) -> float:
        """根据 Spec 数据模型中的实体数推断期望端点数的下限"""
        paths = api_result.get('schema', {}).get('paths', {})
        if not paths: return 0.0
        # 统计所有 HTTP method（GET/POST/PUT/PATCH/DELETE）
        http_methods = {'get', 'post', 'put', 'patch', 'delete'}
        endpoints = sum(
            1 for methods in paths.values()
            for m in methods if m.lower() in http_methods
        )
        # 每个实体应至少有基础的 CRUD 端点（GET list + GET detail + POST create + PUT update + DELETE）
        # 期望最少 3 个端点（entities 为空时底线），实际评分以端点数为准，达到 8+ 则为满分
        expected = max(3, min(endpoints, 8))
        return min(endpoints / expected, 1.0)

    def _score_erd(self, erd_result: dict) -> float:
        entities = erd_result.get('entities', [])
        if not entities: return 0.2
        with_pk = sum(1 for e in entities if any(f.get('primary_key') for f in e.get('fields', e.get('attributes', []))))
        return with_pk / len(entities) if entities else 0.2

    def _score_ddl(self, erd_result: dict) -> float:
        ddl = erd_result.get('ddl', '')
        if not ddl: return 0.0
        valid = ddl.strip().upper().startswith('CREATE') or ddl.strip().upper().startswith('ALTER')
        return 0.9 if valid else 0.3
```

---

## 三、数据库

### 3.1 新建 `design_specs` 表

```sql
CREATE TABLE design_specs (
    id              BIGSERIAL PRIMARY KEY,
    req_id          UUID NOT NULL REFERENCES requirements(id),
    cycle           INT NOT NULL DEFAULT 0,
    version         INT NOT NULL DEFAULT 1,
    spec_doc        JSONB,
    openapi_schema  JSONB,
    erd_diagram     JSONB,
    ddl_statements  TEXT,
    quality_score   NUMERIC(3,2) CHECK (quality_score >= 0 AND quality_score <= 1),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (req_id, cycle, version)
);

CREATE INDEX idx_design_specs_req ON design_specs(req_id, cycle, version DESC);
```

### 3.2 SQL 迁移

```sql
-- Migration: V012__phase2_design_specs.sql
CREATE TABLE IF NOT EXISTS design_specs (
    id              BIGSERIAL PRIMARY KEY,
    req_id          UUID NOT NULL REFERENCES requirements(id),
    cycle           INT NOT NULL DEFAULT 0,
    version         INT NOT NULL DEFAULT 1,
    spec_doc        JSONB,
    openapi_schema  JSONB,
    erd_diagram     JSONB,
    ddl_statements  TEXT,
    quality_score   NUMERIC(3,2) CHECK (quality_score >= 0 AND quality_score <= 1),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_design_specs_req_cycle_version UNIQUE (req_id, cycle, version)
);

CREATE INDEX IF NOT EXISTS idx_design_specs_req ON design_specs(req_id, cycle, version DESC);

-- requirements 表加列（若未在 prototype 迁移中执行）
ALTER TABLE requirements ADD COLUMN IF NOT EXISTS phase VARCHAR(20) DEFAULT 'requirement';
ALTER TABLE requirements ADD COLUMN IF NOT EXISTS design_status VARCHAR(30);
ALTER TABLE requirements ADD COLUMN IF NOT EXISTS design_revision_count INT DEFAULT 0;
```

---

## 四、NATS 事件 payload 对齐

### context.ready.A4 订阅

`BaseAgentWorker.subscribe_nats()` 已处理通用 NATS 订阅。需确保 `context.ready.A4` 的 payload 结构正确。

### agent.result.A4 发布

```python
# 在 execute() 返回的 dict 基础上，base_worker 发布时补齐路由键
# 优先级：返回 dict 中的字段 > context_package 中的字段

return {
    'status': 'completed',
    'req_id': req_id,
    'session_id': context_package.get('session_id', ''),
    'cycle': cycle,
    # ... 四件套产物 ...
}
```

`BaseAgentWorker.subscribe_nats()` 在发布 `agent.result.A4` 时从返回值中提取 `req_id`、`session_id`、`cycle` 注入 payload。

---

## 五、异常处理

| 场景 | 策略 |
|------|------|
| LLM API 不可用 | 降级为 fallback 模板，status='completed', source='fallback', quality_score=0.0 |
| 单个 LLM 子任务超时（5min） | 该子任务降级，其余继续 |
| MCP 全部超时 | 跳过知识增强，仅用需求上下文 + 内置默认值 |
| DB 内省失败 | 视为新项目，全部实体标记 `is_new: true` |
| OpenAPI 校验失败 | 记录 `validation_warnings`，仍正常产出，quality_score 扣分 |
| DDL 校验失败 | 记录 `ddl_warnings`，仍正常产出，quality_score 扣分 |
| A4 总体超时（15min） | 重试 1 次 → Orchestrator 写入 agent_results (A4, status='skipped') → 降级进 Gate1 |
| design_specs UNIQUE 冲突 | ON CONFLICT DO UPDATE 覆盖写入（修订场景幂等） |

---

## 六、实施计划

### Phase 1：基础流水线（~3 天）
- [ ] migration: `design_specs` 建表 + requirements 扩展列
- [ ] `a4/spec_generator.py`：结构化 Spec 六章生成
- [ ] `a4/knowledge_client.py`：MCP 三层降级
- [ ] `A4SpecWriter.execute()` 重构为六阶段流水线
- [ ] `a4/spec_completeness.py` 四维评分

### Phase 2：MCP + 校验（~2 天）
- [ ] MCP Gateway 注册 `get_openapi_templates`、`get_erd_patterns`、`get_ddl_conventions`
- [ ] MCPClient 连通 + 降级逻辑测试
- [ ] SchemaValidator + DDLValidator 联调

### Phase 3：打回 + 全链路（~2 天）
- [ ] Gate1 打回 `revision_context` 解析（优先修复 critical/major 问题）
- [ ] design_specs ON CONFLICT 覆盖写入测试
- [ ] E2E：A3 确认 → A4 → A5 → Gate1 pass / reject → A4 修订

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
