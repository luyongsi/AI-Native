# LLM Provider Audit — 端到端测试 Bug 记录

## 测试环境

| 项目 | 值 |
|------|-----|
| 日期 | 2026-07-03 |
| Spec 版本 | v3 (FINAL) |
| 测试需求 | `86fb9ff9` (v1) / `734bde59` (v2 最终) — 用户个人中心增加手机号绑定功能 |
| Workflow v2 | `req-734bde59-1783067830` — 完整走通到 DONE |

---

## 已修复（本次迭代验证通过）

### BUG-02: workflow_id 为空

| 严重度 | P1 |
|--------|-----|
| 修复后 | 28/34 (82%) — A12 仍缺，其余全部正常 |
| 修复文件 | `a1_requirement_intake.py`, `a4_spec_writer.py`, `a4/api_schema_generator.py`, `a4/erd_generator.py` |

### BUG-03: 审计日志缺少响应内容采样

| 严重度 | P2 |
|--------|-----|
| 修复后 | 34/34 (100%) 调用带有 response_preview |
| 修复文件 | `llm_provider/audit.py`, `llm_provider/adapter.py` |

### BUG-06: model 字段始终为 null

| 严重度 | P3 |
|--------|-----|
| 修复后 | 34/34 (100%) 显示 `deepseek-v4-pro-202606` |
| 修复文件 | `llm_provider/adapter.py` — `_chat_with_audit()` 中 `kwargs.get("model") or getattr(self, "default_model", "")` |

### BUG-09: A4 req_id=UNKNOWN

| 严重度 | P1 |
|--------|-----|
| 修复后 | 12/12 A4 调用 req_id 正确 (`734bde59`) |
| 修复文件 | `a4_spec_writer.py`, `a4/api_schema_generator.py`, `a4/erd_generator.py` |

### BUG-10: erd_gen 返回 0 chars

| 严重度 | P2 |
|--------|-----|
| 修复后 | 6/6 ERD 调用 >0 chars |
| 修复文件 | `llm_provider/deepseek_adapter.py` — `chat()` 中 `content or reasoning_content` |

### BUG-12: A5 评审输入 spec 为空 → 评分全 0

| 严重度 | P1 |
|--------|-----|
| 修复后 | 评分不为 0（6.7, 3.3, ~5），但仍 fail |
| 修复文件 | `a5_design_review.py` — 适配 A4 实际 spec 结构 |

---

## 新增（v2 测试发现）

---

### BUG-15: Agent 重复触发 (BUG-08 未完全修复)

| 维度 | 详情 |
|------|------|
| 严重度 | **P1** |
| 现象 | 每个 Agent 每轮仍被触发 2 次（A1 2x, A3 每轮 2x, A4 每轮 4x, A5 每轮 2x, A6 2x, A12 6x）。34 次调用 vs 理想 9 次 = 3.8x 浪费 |
| 实测 | v2 测试中 dedup 从 `clear()` 改为时间过期，但仍有重复触发。两种可能：(1) worker 进程重复（2 个 worker_launcher 同时消费同一 consumer）；(2) 基于时间的 dedup 在高并发时不一致（两个 _handle 同时检查 dedup set → 都判定为新消息 → 都执行） |
| 修复建议 | (1) 单进程启动检测（pidfile）；(2) dedup 加 `asyncio.Lock` 防止竞态；(3) event_id 改为 UUID |
| 关联 | BUG-08 |
| 状态 | 🔴 待修复 |

---

### BUG-16: A5 评分始终 fail，rework 陷入无效循环

| 维度 | 详情 |
|------|------|
| 严重度 | **P1** |
| 现象 | A5 3 轮评分均 fail（6.7 → 3.3 → ~5），每轮触发 DESIGNING rework。A3/A4 重新生成近似的产出、A5 再次 fail，直到 MAX_REWORK=2 耗尽强制推进 |
| 根因 | (1) A4 产出（OpenAPI/ERD）结构复杂嵌套，A5 提取 spec 文本的逻辑虽已适配但生成的 prompt 对 LLM 不够友好；(2) A5 的 `_read_spec_from_db` 读到空 spec（A4 写了独立表 api_schemas/erd_designs 而非 requirements.spec，MC Backend 的 spec 字段与 A4 写入的不同步）；(3) prompt 要求过严（任一维度 score<70 即 fail），且缺少 "通过条件" 的灵活性 |
| 修复建议 | (1) A4 同时更新 requirements.spec 的 openapi/erd 字段；或 A5 从 api_schemas 表读取；(2) A5 prompt 改为 "2/3 通过即可"；(3) 增加 "跳过评审" 选项 |
| 关联 | BUG-13, BUG-14 |
| 状态 | 🔴 待修复 |

---

### BUG-17: Rework 反馈闭环不完整

| 维度 | 详情 |
|------|------|
| 严重度 | **P1** |
| 现象 | Workflow 代码中有 `[REWORK_FEEDBACK]` 标记向 context_str 注入评审数据（第 148 行：`review_feedback = self._last_a5_result if self._rework_count > 0 else None`），但实际效果有限：(1) `_last_a5_result` 中存储的是完整 A5 返回值（包含 pass/scores/summary/issues），但 context_str 拼接时只取了 `scores` 和 `issues`；(2) A3/A4 的 prompt 中没有处理 `[REWORK_FEEDBACK]` 标记的代码（只当做纯文本拼接在 context 末尾）；(3) A3/A4 的 LLM prompt 模板不包含 "上一轮评审反馈" 部分 |
| 实测 | 代码中有注入逻辑但 A3/A4 的 prompt 未利用这些信息。两轮 A3 产出内容量相近（11303 vs 7262 chars），A5 评分相似（6.7 vs 3.3 vs ~5），说明反馈未生效 |
| 修复建议 | (1) A3/A4 的 prompt 模板中增加 "上一轮评审反馈:" 章节，将 issues 按优先级列出；(2) 明确要求 "修复所有 critical 和 major 级别的 issues" |
| 关联 | BUG-13, BUG-16 |
| 状态 | 🔴 待修复 |

---

### BUG-18: A12 单轮 6 次 LLM 调用（超标 6x）

| 维度 | 详情 |
|------|------|
| 严重度 | **P2** |
| 现象 | A12 单轮发起 6 次 LLM 调用（#29-#34），每次 ~4-13s、132-383 chars。3 次 pass、3 次 fail |
| 根因 | A12 有独立内部事件循环 `_handle_review_request` + `_consume_test_passed`，监听 `test.passed` NATS 主题。当收到测试结果时触发异步任务，多个任务并发调用 `execute()` → `self.call_llm()`。加上 base_worker 的 NATS dispatch 路径也被触发，叠加后产生 6 次调用 |
| 修复建议 | (1) 确认 A12 是否需要独立事件循环，是否可以收归到 Orchestrator 调度；(2) 短期：加互斥锁确保同时只有 1 个 execute() 在执行；(3) 对 `_handle_review_request` 产生的调用通过独立的 task_type 区分 |
| 关联 | BUG-08, BUG-15 |
| 状态 | 🔴 待修复 |

---

### BUG-19: A13 Release stub 异常后未发布 agent.result

| 维度 | 详情 |
|------|------|
| 严重度 | **P1** |
| 现象 | A13 canary-5% 阶段模拟失败 → `execute()` 中 `return self._abort_release()` 返回 dict → 但 base_worker._handle 中捕获到 `nats: no response from stream` 异常 → `execute() failed` → 不执行后续的 `nc.publish(agent.result.A13)` → Workflow 永久等待 A13（超时 30 分钟） |
| 实测 | workaround: 手动 `handle.signal("agent_completed", args=["A13", ...])` 让 workflow 推进到 DONE |
| 根因 | `release_agent.execute()` 中 `_abort_release` 返回正常 dict，但之后 `report_status("failed")` 发了 NATS 请求 JetStream 但没有 stream，导致 `nats: no response from stream` 异常。该异常被 base_worker._handle 的 except 捕获，整个 execute() 被标记为 failed，后面的 `nc.publish(agent.result.A13)` 不执行 |
| 修复 | (1) `report_status` 改为容错（NATS publish 失败不抛异常）；(2) `_handle` 中即使 execute() 抛异常也尝试 publish agent.result（含 error 信息）；(3) Workflow 中 A13 超时降级逻辑：超时后自动推进到 DONE |
| 状态 | 🔴 待修复 |

---

### BUG-20: A12 workflow_id 为空

| 维度 | 详情 |
|------|------|
| 严重度 | P2 |
| 现象 | A12 6 次 LLM 调用全部 `workflow_id=""`，其余 Agent 28/28 正常 |
| 根因 | A12 的 `_handle_review_request` → `execute()` 路径中 `context_package` 不包含 `workflow_id`（来自 `test.passed` NATS 事件，非 Orchestrator dispatch） |
| 修复 | `_handle_review_request` 生成 context_package 时从 req_id 反向查找 active workflow_id |
| 状态 | 🔴 待修复 |

---

## 汇总

| Bug ID | 标题 | 严重度 | 状态 |
|--------|------|--------|------|
| BUG-02 | workflow_id 为空 (A1/A4) | P1 | ✅ 已修复 (82%) |
| BUG-03 | 审计日志缺响应内容采样 | P2 | ✅ 已修复 |
| BUG-05 | API Key 缺失 | P2 | 🟢 workaround |
| BUG-06 | model 字段为 null | P3 | ✅ 已修复 |
| BUG-07 | notify_mc Stub | P2 | 🟡 遗留 |
| BUG-09 | A4 req_id=UNKNOWN | P1 | ✅ 已修复 |
| BUG-10 | erd_gen 0 chars | P2 | ✅ 已修复 |
| BUG-12 | A5 评分全 0 | P1 | ✅ 已修复 |
| BUG-14 | Spec 结构不匹配 | P1 | ✅ 已修复 |
| **BUG-15** | Agent 重复触发 (3.8x 浪费) | **P1** | 🔴 |
| **BUG-16** | A5 始终 fail，无效 rework | **P1** | 🔴 |
| **BUG-17** | Rework 反馈闭环不完整 | **P1** | 🔴 |
| **BUG-18** | A12 单轮 6 次 LLM 调用 | **P2** | 🔴 |
| **BUG-19** | A13 异常后不发布 agent.result | **P1** | 🔴 |
| **BUG-20** | A12 workflow_id 为空 | **P2** | 🔴 |

**已修复 8 个 / 新增 6 个 / 遗留 2 个 = 共 8 个待修复 (5 个 P1)**
