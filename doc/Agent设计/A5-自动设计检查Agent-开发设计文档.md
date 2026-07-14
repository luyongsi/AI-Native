# A5 自动设计检查 Agent — 开发设计文档

## 文档信息
- **版本**: v1.1
- **日期**: 2026-07-13
- **状态**: 开发设计（已通过 critical 审计）
- **参考**: [A5 自动设计检查Agent规格](../Agent规格/A5-自动设计检查Agent规格.md) · [阶段二数据字典](../Agent规格/阶段二-数据字典.md) · [系统状态机 v2.4](../系统架构/系统状态机与信息流设计.md)
- **原则**: 以数据字典为唯一数据规范源；A5 从当前三维检查改造为五维检查，明确非阻断语义

---

## 一、现状分析与差距

### 1.1 当前实现 vs 目标架构

| 维度 | 当前实现 (`a5_design_review.py`) | 目标架构（规格 v1.0） | 差距 |
|------|-------------------------------|---------------------|------|
| **检查维度** | 三维：UX 启发式 + API N+1 + 业务完整性 | 五维：API 一致性 + ERD 完整性 + 状态机闭合性 + 原型对齐 + 安全基线 | 维度和方法均不同 |
| **阻断语义** | 含 `overall_pass` 判定和 `pass/fail` 状态 | 非阻断——只出报告，不做 pass/fail 判断 | 需移除阻断语义 |
| **数据来源** | 从 `requirements.spec` JSONB 读 Spec（A4 写入） | 从 `context.ready.A5` payload 直接取 a3_output + a4_output | 输入方式变更 |
| **产物写入** | `report_artifact()` 内存缓存 | `agent_results` (A5) → `artifact.check_report` | 需新增 agent_results 写入 |
| **报告结构** | 三维 + average score + pass/fail | 五维 + overall_score + issue 列表，无 pass/fail | 结构需对齐 |
| **降级策略** | fallback_review() 返回评分 | 维度级降级：单维度超时→skip，全维度超时→整体 skip | 降级粒度不同 |

### 1.2 现有可复用模块

A5 子包 `repos/agent-workers/a5/` 含以下模块：

| 模块 | 文件 | 功能 | 改造要点 |
|------|------|------|---------|
| `UXEvaluator` | `ux_evaluator.py` | Nielsen 10 启发式 UX 检查 | 映射为 `prototype_spec_alignment` 维度 |
| `N1Detector` | `n1_detector.py` | API N+1 查询模式检测 | 合并到 `api_consistency` 维度 |
| `BusinessChecker` | `business_checker.py` | 业务规则完整性校验 | 合并到 `state_machine_closure` + `security_baseline` |

### 1.3 维度的重新映射

```
旧三维 → 新五维:
  UXEvaluator     → 其启发式检查逻辑合并到 prototype_spec_alignment 维度中，
                    在检查原型状态覆盖之外，额外调用 UXEvaluator 做启发式评分
  N1Detector      → api_consistency（API一致性，作为其中一个检查项）
  BusinessChecker → state_machine_closure（状态机闭合性，取业务规则中的状态相关部分）
                  + security_baseline（安全基线，新增）
                  + erd_completeness（ERD完整性，新增）

注意：UXEvaluator 的原职能（Nielsen 10 启发式）不可直接丢弃。
prototype_spec_alignment 维度在检查原型状态覆盖后，增加对 UX 启发式的
LLM 辅助检查（或复用 UXEvaluator 的规则检查逻辑）。
```

---

## 二、改造方案

### 2.1 DesignReviewAgent 主流程重构

```python
# a5_design_review.py — 改造后的 execute()

class DesignReviewAgent(BaseAgentWorker):
    agent_id = "A5"
    agent_type = "design_review"

    DIMENSIONS = [
        {'key': 'api_consistency',       'label': 'API 一致性',       'weight': 0.25},
        {'key': 'erd_completeness',      'label': 'ERD 完整性',       'weight': 0.25},
        {'key': 'state_machine_closure', 'label': '状态机闭合性',      'weight': 0.20},
        {'key': 'prototype_spec_alignment', 'label': '原型-Spec 对齐', 'weight': 0.15},
        {'key': 'security_baseline',     'label': '安全基线',         'weight': 0.15},
    ]

    async def execute(self, req_id: str, context_package: dict) -> dict:
        a3 = context_package.get('a3_output', {})
        a4 = context_package.get('a4_output', {})
        cycle = context_package.get('cycle', 0)

        a4_missing = a4.get('a4_missing', False)  # 数据字典 §6.5：a4_missing 在 a4_output 内部

        logger.info(f"[A5] Starting design review for req={req_id}, a4_missing={a4_missing}")

        if a4_missing:
            # A4 缺失时仅检查 prototype_spec_alignment
            return await self._check_prototype_only(req_id, cycle, a3)

        # 五维检查（顺序执行，无外部依赖）
        dimensions = []
        for dim_def in self.DIMENSIONS:
            try:
                result = await asyncio.wait_for(
                    self._run_dimension(dim_def['key'], a3, a4),
                    timeout=180.0  # 每维度 3 分钟超时（与 A5 规格 §4 一致）
                )
                dimensions.append(result)
            except asyncio.TimeoutError:
                dimensions.append({
                    'dimension': dim_def['key'],
                    'label': dim_def['label'],
                    'score': None,
                    'status': 'skipped',
                    'issues': [],
                    'skip_reason': 'llm_timeout'
                })
                logger.warning(f"[A5] Dimension {dim_def['key']} timed out, skipped")

        # 汇总评分
        scored = [d for d in dimensions if d['score'] is not None]
        total_weight = sum(self._weight_of(d['dimension']) for d in scored)
        overall_score = round(
            sum(d['score'] * self._weight_of(d['dimension']) for d in scored) / max(total_weight, 0.01),
            2
        ) if scored else None

        check_report = {
            'overall_score': overall_score,
            'total_issues': sum(len(d.get('issues', [])) for d in dimensions),
            'dimensions': dimensions,
            'summary': self._generate_summary(dimensions, overall_score),
            'generated_at': datetime.now(timezone.utc).isoformat()
        }

        # 持久化
        await self._persist_report(req_id, cycle, check_report)

        return {
            'req_id': req_id,
            'session_id': context_package.get('session_id', ''),
            'cycle': cycle,
            'check_report': check_report,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

    async def _run_dimension(self, dim_key: str, a3: dict, a4: dict) -> dict:
        """执行单个检查维度，返回维度结果"""
        checkers = {
            'api_consistency':       self._check_api_consistency,
            'erd_completeness':      self._check_erd_completeness,
            'state_machine_closure': self._check_state_machine,
            'prototype_spec_alignment': self._check_prototype_alignment,
            'security_baseline':     self._check_security,
        }
        return await checkers[dim_key](a3, a4)

    def _weight_of(self, dim_key: str) -> float:
        """从 DIMENSIONS 列表中查找维度权重"""
        for d in self.DIMENSIONS:
            if d['key'] == dim_key:
                return d['weight']
        return 0.0
```

### 2.2 五维检查实现

```python
async def _check_api_consistency(self, a3: dict, a4: dict) -> dict:
    """OpenAPI 自身的端点完整性 —— 检查 paths 中每个 method 是否定义了 responses"""
    openapi = a4.get('openapi_schema', {})

    issues = []

    # 从 OpenAPI paths 中提取已定义的接口
    for path, methods in openapi.get('paths', {}).items():
        for method, details in methods.items():
            if method.upper() in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                # 检查响应定义完整性
                if 'responses' not in details or '200' not in details.get('responses', {}):
                    issues.append({
                        'id': f'api_{len(issues)+1:03d}',
                        'severity': 'minor',
                        'description': f'{method.upper()} {path} 缺少 200 响应定义',
                        'suggestion': '补充成功响应 schema',
                        'location': f'openapi_schema.paths.{path}.{method}'
                    })
                # 检查错误响应
                if '400' not in details.get('responses', {}) and '4XX' not in details.get('responses', {}):
                    issues.append({
                        'id': f'api_{len(issues)+1:03d}',
                        'severity': 'minor',
                        'description': f'{method.upper()} {path} 缺少 4XX 错误响应定义',
                        'suggestion': '补充客户端错误响应 schema',
                        'location': f'openapi_schema.paths.{path}.{method}.responses'
                    })

    # N+1 检测（使用 N1Detector 现有实现）
    has_n1 = self.n1_detector.detect(openapi)
    if has_n1:
        for n1_item in has_n1.get('n1_queries', []):
            issues.append({
                'id': f'api_{len(issues)+1:03d}',
                'severity': 'major',
                'description': f'N+1 风险: {n1_item.get("pattern_type", "")} — '
                               f'{n1_item.get("path", "")} 预估 {n1_item.get("estimated_queries", "?")} 次级联查询',
                'suggestion': n1_item.get('suggestion', ''),
                'location': n1_item.get('path', '')
            })

    score = max(0, 100 - len(issues) * 10)
    return {
        'dimension': 'api_consistency',
        'label': 'API 一致性',
        'score': score / 100,
        'issues': issues
    }


async def _check_erd_completeness(self, a3: dict, a4: dict) -> dict:
    """检查 ERD 是否覆盖 Spec 数据模型中所有实体"""
    spec_doc = a4.get('spec_doc', {})
    erd = a4.get('erd_diagram', {})

    spec_entities = set()
    for model in spec_doc.get('data_models', []):
        spec_entities.add(model.get('name', ''))

    erd_entities = set()
    for entity in erd.get('entities', []):
        erd_entities.add(entity.get('name', ''))

    missing = spec_entities - erd_entities
    issues = []

    for name in missing:
        issues.append({
            'id': f'erd_{len(issues)+1:03d}',
            'severity': 'critical' if len(missing) <= 2 else 'major',
            'description': f'数据模型 {name} 在 ERD 中缺失',
            'suggestion': f'在 ERD 中补充 {name} 实体定义',
            'location': 'erd_diagram.entities'
        })

    # 检查每个实体的主键定义
    for entity in erd.get('entities', []):
        fields = entity.get('fields', entity.get('attributes', []))
        has_pk = any(f.get('primary_key') for f in fields)
        if not has_pk:
            issues.append({
                'id': f'erd_{len(issues)+1:03d}',
                'severity': 'major',
                'description': f'实体 {entity["name"]} 缺少主键定义',
                'suggestion': '为实体添加主键字段',
                'location': f'erd_diagram.entities.{entity["name"]}'
            })

    score = max(0, 100 - len(issues) * 12)
    return {
        'dimension': 'erd_completeness',
        'label': 'ERD 完整性',
        'score': score / 100,
        'issues': issues
    }


async def _check_state_machine(self, a3: dict, a4: dict) -> dict:
    """检查 Spec 中的状态机是否所有状态都有入口/出口"""
    spec_doc = a4.get('spec_doc', {})
    issues = []

    for module in spec_doc.get('modules', []):
        sm = module.get('state_machine', {})
        if not sm:
            continue

        states = set(sm.get('states', []))
        transitions = sm.get('transitions', [])
        in_edges = {t['to'] for t in transitions}
        out_edges = {t['from'] for t in transitions}
        terminal_states = set(sm.get('terminal_states', []))

        # 检查可达性（非初始状态需有入边）
        for state in states:
            # 初始状态从 transitions 中推断：出现在 from 但不在 to 中的第一个
            if state not in in_edges and state not in terminal_states and len(transitions) > 0:
                issues.append({
                    'id': f'sm_{len(issues)+1:03d}',
                    'severity': 'major',
                    'description': f'模块 {module["name"]} 的状态 {state} 没有入边（不可达）',
                    'suggestion': f'添加一条指向 {state} 的 transition',
                    'location': f'spec_doc.modules.{module["name"]}.state_machine'
                })

        # 检查可出性（非终态需有出边）
        for state in states:
            if state not in out_edges and state not in terminal_states:
                issues.append({
                    'id': f'sm_{len(issues)+1:03d}',
                    'severity': 'major',
                    'description': f'模块 {module["name"]} 的状态 {state} 没有出边（死锁状态）',
                    'suggestion': f'添加一条从 {state} 出发的 transition 或将其标记为终态',
                    'location': f'spec_doc.modules.{module["name"]}.state_machine'
                })

        # 检查 trigger 完整性
        for t in transitions:
            if not t.get('trigger'):
                issues.append({
                    'id': f'sm_{len(issues)+1:03d}',
                    'severity': 'minor',
                    'description': f'{t.get("from")} → {t.get("to")} 的 transition 缺少 trigger 定义',
                    'suggestion': '为 transition 补充 trigger 事件',
                    'location': f'spec_doc.modules.{module["name"]}.state_machine.transitions'
                })

    score = max(0, 100 - len(issues) * 10)
    return {
        'dimension': 'state_machine_closure',
        'label': '状态机闭合性',
        'score': score / 100,
        'issues': issues
    }


async def _check_prototype_alignment(self, a3: dict, a4: dict) -> dict:
    """检查原型是否覆盖 Spec 中的用例"""
    prototype_screens = a3.get('screens', [])
    spec_doc = a4.get('spec_doc', {})

    issues = []

    # 检查原型状态覆盖（同时检查 module.states 和 module.state_machine.states）
    screen_states = {s.get('state') for s in prototype_screens}
    for module in spec_doc.get('modules', []):
        all_module_states = set(module.get('states', [])) | set(
            module.get('state_machine', {}).get('states', [])
        )
        for state in all_module_states:
            if state not in screen_states:
                issues.append({
                    'id': f'align_{len(issues)+1:03d}',
                    'severity': 'major',
                    'description': f'模块 {module["name"]} 的状态 {state} 在原型中缺少对应截图',
                    'suggestion': f'为 {state} 状态生成原型截图',
                    'location': f'prototype.screens (missing state: {state})'
                })

    # 检查必需状态
    required_states = {'default', 'loading', 'empty', 'error'}
    missing = required_states - screen_states
    for state in missing:
        issues.append({
            'id': f'align_{len(issues)+1:03d}',
            'severity': 'minor',
            'description': f'原型缺少 {state} 通用状态的截图',
            'suggestion': f'补充原型 {state} 状态的截图',
            'location': 'prototype.screens'
        })

    score = max(0, 100 - len(issues) * 12)
    return {
        'dimension': 'prototype_spec_alignment',
        'label': '原型-Spec 对齐',
        'score': score / 100,
        'issues': issues
    }


async def _check_security(self, a3: dict, a4: dict) -> dict:
    """检查 API 设计是否满足基本安全要求"""
    openapi = a4.get('openapi_schema', {})
    issues = []

    # 1. 认证定义
    security = openapi.get('components', {}).get('securitySchemes', {})
    if not security:
        issues.append({
            'id': 'sec_001',
            'severity': 'critical',
            'description': 'OpenAPI 未定义 securitySchemes（认证方案）',
            'suggestion': '在 components.securitySchemes 中定义 Bearer Token 或其他认证方案',
            'location': 'openapi_schema.components.securitySchemes'
        })

    # 2. 全局 HTTPS
    if not any(s.get('scheme') == 'https' for s in openapi.get('servers', [])):
        issues.append({
            'id': 'sec_002',
            'severity': 'info',
            'description': '未显式声明 HTTPS server',
            'suggestion': '在 servers 中添加 https 协议的 server 声明',
            'location': 'openapi_schema.servers'
        })

    # 3. 敏感接口标注
    mutating_methods = {'post', 'put', 'patch', 'delete'}
    for path, methods in openapi.get('paths', {}).items():
        for method, details in methods.items():
            if method.lower() in mutating_methods:
                if 'security' not in details:
                    issues.append({
                        'id': f'sec_{len(issues)+1:03d}',
                        'severity': 'major',
                        'description': f'{method.upper()} {path} 缺少 security 声明',
                        'suggestion': '为该接口添加 security 引用',
                        'location': f'openapi_schema.paths.{path}.{method}'
                    })

    # 4. 业务规则关键信号检查（安全检查不需要完整 BusinessChecker，仅检查
    #    spec_doc 中是否包含安全相关业务规则的关键信号词）
    spec_text = json.dumps(a4.get('spec_doc', {}))
    security_signals = ['auth', 'permission', 'role', 'rbac', 'audit', 'log', 'pii', 'encrypt']
    missing_signals = [s for s in security_signals if s not in spec_text.lower()]
    if missing_signals:
        issues.append({
            'id': f'sec_{len(issues)+1:03d}',
            'severity': 'major',
            'description': f'Spec 中缺少以下安全相关概念: {", ".join(missing_signals)}',
            'suggestion': '在 Spec 中补充认证授权、审计日志、数据加密等相关描述',
            'location': 'spec_doc'
        })

    score = max(0, 100 - len(issues) * 10)
    return {
        'dimension': 'security_baseline',
        'label': '安全基线',
        'score': score / 100,
        'issues': issues
    }
```

### 2.3 持久化

```python
async def _persist_report(self, req_id: str, cycle: int, check_report: dict):
    """写入 agent_results (A5)"""
    artifact = {'check_report': check_report, 'non_blocking': True, 'generated_at': datetime.now(timezone.utc).isoformat()}

    async with self.db.transaction():
        await self.db.execute("""
            INSERT INTO agent_results (req_id, agent_key, cycle, status, artifact)
            VALUES ($1, 'A5', $2, 'completed', $3)
            ON CONFLICT (req_id, agent_key, cycle) DO UPDATE SET
                artifact = EXCLUDED.artifact, status = 'completed'
        """, req_id, cycle, json.dumps(artifact))
```

### 2.4 A4 缺失处理

```python
async def _check_prototype_only(self, req_id: str, cycle: int, a3: dict) -> dict:
    """A4 缺失时仅做 prototype_spec_alignment 维度的基础检查"""
    screens = a3.get('screens', [])
    required = {'default', 'loading', 'empty', 'error'}
    missing = required - {s.get('state') for s in screens}

    issues = []
    if missing:
        issues.append({
            'id': 'align_001',
            'severity': 'minor',
            'description': f'原型缺少状态截图: {", ".join(missing)}',
            'suggestion': '补充缺失状态的截图',
            'location': 'prototype.screens'
        })

    check_report = {
        'overall_score': None,
        'total_issues': len(issues),
        'dimensions': [
            {'dimension': 'prototype_spec_alignment', 'label': '原型-Spec 对齐', 'score': None, 'status': 'skipped', 'issues': issues, 'skip_reason': 'a4_missing'},
            {'dimension': 'api_consistency', 'label': 'API 一致性', 'score': None, 'status': 'skipped', 'issues': [], 'skip_reason': 'a4_missing'},
            {'dimension': 'erd_completeness', 'label': 'ERD 完整性', 'score': None, 'status': 'skipped', 'issues': [], 'skip_reason': 'a4_missing'},
            {'dimension': 'state_machine_closure', 'label': '状态机闭合性', 'score': None, 'status': 'skipped', 'issues': [], 'skip_reason': 'a4_missing'},
            {'dimension': 'security_baseline', 'label': '安全基线', 'score': None, 'status': 'skipped', 'issues': [], 'skip_reason': 'a4_missing'},
        ],
        'summary': 'A4 Spec 未产出，仅检查了原型状态覆盖。其余维度已跳过。',
        'generated_at': datetime.now(timezone.utc).isoformat()
    }

    await self._persist_report(req_id, cycle, check_report)
    return {
        'req_id': req_id,
        'session_id': '',
        'cycle': cycle,
        'check_report': check_report,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
```

---

## 三、NATS 事件

### context.ready.A5 输入

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "a3_output": {
    "prototype_url": "string",
    "screens": [{"name": "...", "state": "default", "url": "..."}]
  },
  "a4_output": {
    "a4_missing": false,
    "spec_doc": {},
    "openapi_schema": {},
    "erd_diagram": {},
    "ddl_statements": "string"
  }
}
```

### agent.result.A5 输出

```json
{
  "req_id": "uuid",
  "session_id": "uuid",
  "cycle": 0,
  "check_report": {},
  "timestamp": "ISO 8601"
}
```

**关键：`agent.result.A5` 不含 `pass`/`fail` 字段。Orchestrator 始终继续进入 Gate1。**

---

## 四、降级策略

| 层次 | 策略 |
|------|------|
| **完整检查** | LLM 可用 + A4 完整 → 五维全部执行 |
| **维度级降级** | 单维度 LLM 超时（2min）→ 标记 `skipped`，其余维度继续 |
| **整体降级** | 全部维度超时（10min）→ 重试 1 次 → Orchestrator 写入 agent_results (A5, status='skipped') |
| **A4 缺失** | 仅检查 prototype_spec_alignment，其余标记 `skipped`，reason='a4_missing' |

---

## 五、实施计划

### Phase 1：五维重构（~3 天）
- [ ] `DesignReviewAgent.execute()` 重构为五维 check runner
- [ ] 新增 `erd_completeness`、`state_machine_closure`、`security_baseline` 三维实现
- [ ] 解析 `context.ready.A5` payload（a3_output + a4_output）
- [ ] agent_results (A5) 持久化

### Phase 2：非阻断 + 降级（~2 天）
- [ ] 移除 `overall_pass` / `pass`/`fail` 判定
- [ ] 维度级超时降级（180s per dimension）
- [ ] A4 缺失场景处理
- [ ] Gate1 审批页集成 A5 报告展示

### Phase 3：全链路联调（~2 天）
- [ ] A4 → A5 → Gate1 串联
- [ ] Gate1 拒绝 → A4 修订 → A5 重检（含 revision_context）
- [ ] E2E 测试（三场景：全部通过 / A4 缺失 / 个别维度超时）

---

## 六、关键设计决策

| 决策 | 理由 |
|------|------|
| A5 不输出 pass/fail | A5 是参考信息不是决策节点；Gate1 审批人自行判断 |
| 检查维度顺序执行 | 无外部依赖，耗时短，避免并行复杂性 |
| 每维度独立 2 分钟超时 | 5×120s=600s，对齐 10min 总超时；单维度不阻塞其余 |
| 报告写入 agent_results | 审计可追溯；每轮 cycle 保留独立检查报告 |
| A4 缺失时不阻塞 | Gate1 审批人仍可基于原型做判断 |

---

**文档维护**: AI-Native团队
**最后更新**: 2026-07-13
**版本**: v1.0
