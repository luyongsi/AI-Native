# LLM Provider Audit — 端到端测试 Bug 记录

## 测试环境

| 项目 | 值 |
|------|-----|
| 日期 | 2026-07-03 |
| Spec 版本 | v3 (FINAL) |
| 测试需求 | `86fb9ff9-d8ce-4b00-9009-bd0643be12fd` - 用户个人中心增加手机号绑定功能 |
| Workflow | `req-86fb9ff9-1783062911` |

---

## BUG-01: A1 单轮 2 次 LLM 调用 (预期 1 次)

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | A1 execute()中调用了两次 _analyze_with_llm(), 导致每轮触发 2 个并行 LLM 调用 |
| 实测数据 | 调用 #1: 199 chars / 614 tokens / 10.1s; 调用 #2: 298 chars / 735 tokens / 11.3s |
| 目标 | 1 次/轮 |
| 根因分析 | A1 execute() 中只有一处 call_llm() 调用路径(第 97 行)。实测中看到的 "2 次调用" 实际是 BUG-08 导致的 NATS 消息重复投递, A1 _handle() 被触发了 2 次, 分别执行了完整的 execute()。修复 BUG-08(dedup)后此问题也一并解决 |
| 关联 Spec | 4.6 消除双调用、9 验证标准 |
| 关联 Bug | BUG-08(重复触发, 根本原因) |
| 状态 | ✅ 已修复 (通过 BUG-08 的 dedup 修复一并解决) |
| 修复文件 | `base_worker.py` — _handle() dedup 逻辑从清空改为时间过期 |

---

## BUG-02: workflow_id 为空字符串

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | LLM 审计日志中 workflow_id 始终为空 |
| 实测数据 | "workflow_id": "" (A1 和 A4 所有调用) |
| 目标 | 应为 req-86fb9ff9-1783062911 |
| 根因分析 | A1._analyze_with_llm() 方法签名只接受 (message, req_id), 不接受 workflow_id 参数。虽然 execute() 中 context_package 包含 workflow_id, 但未传给 _analyze_with_llm → call_llm() |
| 修复方案 | (1) _analyze_with_llm() 增加 workflow_id 参数; (2) execute() 传递 context_package.get("workflow_id", ""); (3) call_llm() 调用中显式传入 workflow_id |
| 关联 Spec | 4.5 call_llm 显式传参 |
| 状态 | ✅ 已修复 |
| 修复文件 | `a1_requirement_intake.py` |

---

## BUG-03: 审计日志缺少响应内容采样

| 维度 | 详情 |
|------|------|
| 严重度 | P2 |
| 现象 | 审计日志只记录 response_chars 字符数, 不记录实际文本内容 |
| 目标 | 应记录 response_preview (前 N 字符) |
| 根因 | LLMAuditor.record_end() 只记录 int 不采样内容 |
| 修复方案 | (1) LLMAuditor.record_end() 增加 response_preview 参数, 截取前 500 字符; (2) adapter._chat_with_audit() 调用 record_end 时传入 response.content 前 200 字符 |
| 状态 | ✅ 已修复 |
| 修复文件 | `llm_provider/audit.py`, `llm_provider/adapter.py` |

---

## BUG-04: A1 双调用 50% 浪费 (=BUG-01)

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | A1 每阶段发起 2 次 LLM 调用但只用 1 个结果 |
| 状态 | ✅ 已修复(与 BUG-01 合并, 根因是 BUG-08 去重失效) |

---

## BUG-05: DeepSeekAdapter 非 systemd 环境读不到 API Key

| 维度 | 详情 |
|------|------|
| 严重度 | P2 (已 workaround) |
| 现象 | Authorization: Bearer 空值导致 401 |
| Workaround | base_worker._init_llm() 显式传 api_key + worker_launcher.py 启动时加载 /etc/ai-native.env |
| 状态 | 已 workaround |

---

## BUG-06: model 字段始终为 null

| 维度 | 详情 |
|------|------|
| 严重度 | P3 |
| 现象 | 审计日志中 "model": null |
| 目标 | 应为 "deepseek-v4-pro-202606" |
| 根因 | adapter._chat_with_audit() 中 `model=kwargs.get("model", getattr(self, "default_model", ""))`。调用方 LLMProviderManager._execute_with_fallback() 传了 model=None 显式参数, Python dict.get() 只对不存在的 key 返回 default, 对值为 None 的 key 仍然返回 None |
| 修复方案 | 改为 `kwargs.get("model") or getattr(self, "default_model", "")` — 使用 `or` 运算符将 None 视为 falsy, fallback 到 default_model |
| 状态 | ✅ 已修复 |
| 修复文件 | `llm_provider/adapter.py` — _chat_with_audit() 第 112 行 |

---

## BUG-07: notify_mc Activity 是 Stub

| 维度 | 详情 |
|------|------|
| 严重度 | P2 |
| 现象 | 需求 API 显示 "status":"pool", 实际 Workflow 已到 analyzing |
| 根因 | notify_mc.py 只发 NATS 不更新 DB |
| 状态 | 已知遗留项 |

---

## BUG-08: A3/A4 重复触发 - 同一条 dispatch 收到 2 次

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | Orchestrator 对 A3/A4 各 dispatch 一次, 但每个 Agent 的 _handle() 被触发 2 次 |
| 实测数据 | A3: 2次 ui_prototype, A4: 2次 openapi_gen + 2次 erd_gen, 总共 6 次 LLM 调用(实际只需 3 次) |
| 根因 | base_worker._handle() 的去重机制存在严重缺陷: dedup set 累积到 500 条后调用 .clear() 清空全集, 丢失所有去重保护。此后任何消息都会被认为是"新消息"并重复处理 |
| 修复方案 | 改为基于时间的过期淘汰: 每个 event_id 存储时附带时间戳, 仅淘汰 5 分钟前的旧条目, 不丢失近期保护。同时 dedup 检查改为线性扫描(set of tuples 不能直接用 `in` 检查 event_id) |
| 状态 | ✅ 已修复 |
| 修复文件 | `base_worker.py` — _handle() 第 277-303 行 |

---

## BUG-09: A4 req_id=UNKNOWN - 注入的 llm_caller 未传 req_id

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | A4 子模块(APISchemaGenerator/ERDGenerator) 通过注入的 llm_caller 调 LLM 时, 所有调用 req_id=UNKNOWN |
| 实测数据 | A4 8次调用全部 req_id=UNKNOWN, 同阶段 A3 正常(req_id=86fb9ff9) |
| 根因 | APISchemaGenerator._call_llm() 和 ERDGenerator._call_llm() 调用注入的 llm_caller 时只传 task_type/temperature/max_tokens, 未传 req_id 和 workflow_id |
| 修复方案 | (1) A4SpecWriter.execute() 在 context dict 中加入 req_id 和 workflow_id; (2) APISchemaGenerator/ERDGenerator 在 generate() 中将 context 存到 self._context; (3) _call_llm() 从 self._context 提取 req_id/workflow_id 并传入 llm_caller |
| 状态 | ✅ 已修复 |
| 修复文件 | `a4_spec_writer.py`, `a4/api_schema_generator.py`, `a4/erd_generator.py` |

---

## BUG-10: erd_gen 返回 0 chars - response.content 为空

| 维度 | 详情 |
|------|------|
| 严重度 | P2 |
| 现象 | erd_gen 调用消耗 4671 tokens 但 response_chars=0, 且空结果覆盖了上一版本有内容的 ERD |
| 根因 | DeepSeek R1 模型返回 reasoning_content 而非 content; Adapter 只取 content 字段 |
| 修复方案 | DeepSeekAdapter.chat() 中 content 为空时 fallback 到 reasoning_content: `message.get("content", "") or message.get("reasoning_content", "") or ""` |
| 状态 | ✅ 已修复 |
| 修复文件 | `llm_provider/deepseek_adapter.py` — chat() 第 90-93 行 |

---

## BUG-11: worker_launcher 进程重复启动

| 维度 | 详情 |
|------|------|
| 严重度 | P2 |
| 现象 | 有 2 个 worker_launcher.py 进程 + 2 个 worker.py 进程同时运行, Bridge consumer 冲突 |
| 根因 | systemctl restart + nohup 手动启动叠加, 没有先 kill 旧进程 |
| 状态 | 操作合规问题, 后续加 pidfile |

---

## BUG-12: A5 评审输入 spec 为空 - 三项评分全 0

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | A5 评审三项目评分全 0(ux=0, api=0, biz=0), 非 fallback(fallback 会评 50/45/40) |
| 实测数据 | 两轮评审均 average: 0.0, LLM 收到有效 prompt(1123 chars)但输入数据为空 |
| 根因 | A5 期望 spec 结构为 `{sections: [...], openapi: {paths: ...}, erd: {tables: ...}}`, 但 A4 实际写入的结构为 `{openapi: {openapi:"3.1.0", schema: {info, paths, components}}, erd: {erd_mermaid, ddl, entities, relationships}}`。A5 从错误路径取值(取 openapi.paths 而非 openapi.schema.paths, 取 erd.tables 而非 erd.entities), 导致 prompt 中 API 和 ERD 部分为空 JSON |
| 关联 | BUG-14(数据结构不匹配) |
| 修复方案 | 重写 A5 的 spec 提取逻辑, 适配 A4 实际结构: sections 缺失时从 openapi.schema.info 构建, openapi_text 取 openapi.schema.paths, erd_text 取 erd.entities + erd.relationships。fallback_review 的判断逻辑也同步更新 |
| 状态 | ✅ 已修复 |
| 修复文件 | `a5_design_review.py` — execute() 第 66-95 行, _fallback_review() 第 214-233 行 |

---

## BUG-13: Rework 无反馈闭环 - A3/A4 收不到 A5 评审建议

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | A5 fail -> rework -> 重新 dispatch A3/A4, 但 A3/A4 的 context_package 中无上次 A5 评审结果(issues/建议), rework 是盲重试 |
| 实测数据 | 两轮 A3 产出量相近(13466 vs 12905 chars), A5 评分完全一致(0/0/0) |
| 根因 | RequirementWorkflow._compute_next_state() 中 REVIEWING → DESIGNING 时将 _agent_result 存到 _last_a5_result, 但 _run_designing_parallel() 未接收和使用该数据, 也未传给 build_context() 或 dispatch_agent() |
| 修复方案 | (1) _run_agent_stage() 在 rework_count > 0 时将 _last_a5_result 传给 _run_designing_parallel(); (2) _run_designing_parallel() 增加 review_feedback 参数, 将评审分数和 issues 序列化为 JSON 追加到 context_str 末尾(带 [REWORK_FEEDBACK] 标记), 这样 A3/A4 收到的 context_package 中包含上次评审的反馈 |
| 状态 | ✅ 已修复 |
| 修复文件 | `orchestrator/workflows/requirement_workflow.py` — _run_agent_stage(), _run_designing_parallel() |

---

## BUG-14: A4 -> A5 spec 数据结构不匹配

| 维度 | 详情 |
|------|------|
| 严重度 | P1 |
| 现象 | A4 写入: {openapi: {openapi:"3.1.0", schema: {...}}, erd: {erd_mermaid:"...", ddl:"..."}}; A5 期望: {sections: [...], openapi: {paths: ...}, erd: {tables: ...}}。层级不对 |
| 根因 | 无统一 Spec Schema。A4 产出包装了一层(schema 嵌套), A5 按另一种结构读取 |
| 修复方案 | A5 适配 A4 实际结构: openapi.schema.paths 取 API 路径, erd.entities 取数据表。详见 BUG-12 修复 |
| 关联 | BUG-12(评分全 0), BUG-13(rework 无反馈) |
| 状态 | ✅ 已修复 (与 BUG-12 合并修复) |
| 修复文件 | `a5_design_review.py` |

---

## 汇总

| Bug ID | 标题 | 严重度 | 阶段 | 状态 |
|--------|------|--------|------|------|
| BUG-01/04 | A1 双调用 | P1 | ANALYZING | ✅ 已修复 (根因是 BUG-08) |
| BUG-02 | workflow_id 为空 | P1 | 全局 | ✅ 已修复 |
| BUG-03 | 审计缺少内容采样 | P2 | 全局 | ✅ 已修复 |
| BUG-05 | API Key 缺失 | P2 | 全局 | 已 workaround |
| BUG-06 | model 为 null | P3 | 全局 | ✅ 已修复 |
| BUG-07 | notify_mc Stub | P2 | 全局 | 遗留项 |
| BUG-08 | A3/A4 重复触发 | P1 | DESIGNING | ✅ 已修复 |
| BUG-09 | A4 req_id=UNKNOWN | P1 | DESIGNING | ✅ 已修复 |
| BUG-10 | erd_gen 0 chars | P2 | DESIGNING | ✅ 已修复 |
| BUG-11 | 进程重复 | P2 | 全局 | 操作合规 |
| BUG-12 | A5 评分全 0 | P1 | REVIEWING | ✅ 已修复 |
| BUG-13 | Rework 无反馈 | P1 | REVIEWING | ✅ 已修复 |
| BUG-14 | Spec 结构不匹配 | P1 | REVIEWING | ✅ 已修复 (与 BUG-12 合并) |

**共 14 个 Bug: 11 个已修复 / 1 个已 workaround / 1 个遗留项 / 1 个操作合规**

### 修改文件清单

| 文件 | 涉及 Bug |
|------|----------|
| `repos/agent-workers/base_worker.py` | BUG-08 |
| `repos/agent-workers/a1_requirement_intake.py` | BUG-02 |
| `repos/agent-workers/a4_spec_writer.py` | BUG-09 |
| `repos/agent-workers/a4/api_schema_generator.py` | BUG-09 |
| `repos/agent-workers/a4/erd_generator.py` | BUG-09 |
| `repos/agent-workers/a5_design_review.py` | BUG-12, BUG-14 |
| `repos/llm-provider/llm_provider/adapter.py` | BUG-03, BUG-06 |
| `repos/llm-provider/llm_provider/audit.py` | BUG-03 |
| `repos/llm-provider/llm_provider/deepseek_adapter.py` | BUG-10 |
| `repos/orchestrator/workflows/requirement_workflow.py` | BUG-13 |
