# 109 环境 Agent 逐步启用计划

## 🎯 目标
在 172.27.78.109 生产环境上，逐个验证并启用 Agent，确保每个 Agent 工作正常后再启用下一个。

## 📋 执行状态

### ✅ 已完成
1. **文档整理**
   - 创建 `doc/Agent规格/` 目录
   - 完成 `A1-需求分析Agent规格.md`
   - 整理 doc 目录：归档 bugs/、specs/、plan/ 到 archive/
   - 移动部署文档到 `doc/部署文档/`
   - 创建 `doc/README.md` 和 `doc/Agent规格/README.md`

2. **109 环境准备**
   - 决定：暂不启动任何 Agent（只保留 Orchestrator）

### 🚧 进行中
- 无

### 📝 待办

#### 第一阶段：补充 Agent 规格文档
按优先级编写 Agent 规格：

**P0 - 设计阶段核心**
- [ ] A3 - UI生成Agent规格.md
- [ ] A4 - 规格编写Agent规格.md
- [ ] A5 - 设计评审Agent规格.md
- [ ] A6 - 任务分解Agent规格.md

**P0 - 开发阶段核心**
- [ ] A9 - 开发Agent规格.md

**P1 - 测试与审查阶段**
- [ ] A11 - 自动化测试Agent规格.md
- [ ] A12 - 代码审查Agent规格.md

**P2 - 辅助功能（需先修复调度）**
- [ ] A7 - 测试用例生成Agent规格.md
- [ ] A2 - 知识检索Agent规格.md
- [ ] A8 - 架构评审Agent规格.md

#### 第二阶段：逐个启用 Agent（在 109 上）

**前置条件**：
- 109 环境已停止所有 Agent
- Orchestrator 保持运行
- 本地已完成对应 Agent 的规格文档

**启用顺序**（按依赖关系）：

1. **A1 - 需求分析Agent**
   ```bash
   # 在 109 上
   cd /opt/ai-native/repos/agent-workers
   nohup python a1_requirement_intake.py > logs/a1.log 2>&1 &
   
   # 验证：创建测试需求，检查 A1 是否正常处理
   # 验证通过后，继续下一个
   ```

2. **A3 - UI生成Agent**
   ```bash
   nohup python a3_ui_generator.py > logs/a3.log 2>&1 &
   # 验证：A1 完成后，A3 应接收到 context.ready.ui_generator 事件
   ```

3. **A4 - 规格编写Agent**
   ```bash
   nohup python a4_spec_writer.py > logs/a4.log 2>&1 &
   # 注意：A4 自持久化到 api_schemas 和 erd_designs 表
   ```

4. **A5 - 设计评审Agent**
   ```bash
   nohup python a5_design_review.py > logs/a5.log 2>&1 &
   # 验证：检查是否触发 rework（A5 返回 pass=false）
   ```

5. **A6 - 任务分解Agent**
   ```bash
   nohup python a6_spec_decomposer.py > logs/a6.log 2>&1 &
   # 验证：检查生成的任务列表
   ```

6. **A9 - 开发Agent**
   ```bash
   # A9 是复杂的双脑架构，需要额外验证
   cd /opt/ai-native/repos/agent-workers/a9
   nohup python main.py > logs/a9.log 2>&1 &
   # 验证：检查 Coder-Auditor 迭代日志
   ```

7. **A11 - 自动化测试Agent**
   ```bash
   nohup python a11_test_agent_stub.py > logs/a11.log 2>&1 &
   # ⚠️ 注意：当前是 stub 实现，15% 模拟失败率
   ```

8. **A12 - 代码审查Agent**
   ```bash
   nohup python a12_code_review.py > logs/a12.log 2>&1 &
   # 验证：检查审查报告的 verdict 和 issues
   ```

#### 第三阶段：修复未调度的 Agent

**问题**：A2、A7、A8 已实现但未在 `requirement_workflow.py` 的 `_AGENT_STATES` 中

**修复步骤**：
1. 阅读 A2、A7、A8 代码，理解其职责
2. 确定它们应该在哪个状态被调度
3. 修改 `requirement_workflow.py` 添加调度逻辑
4. 更新状态机图（在文档中）
5. 部署到 109 并验证

---

## 🔍 验证方法

### 单个 Agent 验证清单
每启用一个 Agent 后，执行以下检查：

1. **进程检查**
   ```bash
   ps aux | grep "python.*{agent_file}.py" | grep -v grep
   ```

2. **日志检查**
   ```bash
   tail -f /opt/ai-native/repos/agent-workers/logs/{agent_id}.log
   # 查看是否有错误、是否正常订阅 NATS 事件
   ```

3. **NATS 事件检查**
   ```bash
   # 使用 nats-cli 监听事件
   nats sub "context.ready.{agent_type}"
   nats sub "agent.result.{agent_id}"
   ```

4. **数据库检查**
   ```sql
   -- 检查产物是否正确写入
   SELECT id, current_state, 
          spec->'artifacts'->'{agent_id}' AS agent_output
   FROM requirements 
   WHERE id = '{test_req_id}';
   ```

5. **端到端测试**
   ```bash
   # 创建测试需求，观察完整流程
   curl -X POST http://172.27.78.109:8000/requirements \
     -H "Content-Type: application/json" \
     -d '{"title": "测试需求", "description": "验证Agent是否正常工作"}'
   
   # 查看需求状态变化
   curl http://172.27.78.109:8000/requirements/{req_id}
   ```

### 常见问题排查

**问题1：Agent 启动后无响应**
- 检查 NATS 连接：`nats://172.27.78.109:4222` 是否可达
- 检查订阅的 subject 是否正确
- 查看日志中的 `[{agent_id}] Subscribed to ...` 消息

**问题2：Agent 处理超时**
- 检查 LLM Provider 配置（`DATABASE_URL` 环境变量）
- 检查 LLM API 可用性（DeepSeek/OpenAI）
- 查看 `llm_provider/audit.py` 中的调用日志

**问题3：产物未持久化**
- 检查 Orchestrator 是否调用了 `store_agent_result` Activity
- 确认 Agent 不在 `_AGENTS_THAT_PERSIST` 列表中（只有 A4）
- 查看 PostgreSQL 的 `requirements.spec.artifacts` 字段

---

## 📊 进度追踪

| Agent | 规格文档 | 109启用 | 验证通过 | 备注 |
|-------|---------|---------|---------|------|
| A1    | ✅      | ⏸️      | ⏸️      | 已完成规格 |
| A3    | ⏸️      | ⏸️      | ⏸️      | 待编写规格 |
| A4    | ⏸️      | ⏸️      | ⏸️      | 待编写规格 |
| A5    | ⏸️      | ⏸️      | ⏸️      | 待编写规格 |
| A6    | ⏸️      | ⏸️      | ⏸️      | 待编写规格 |
| A9    | ⏸️      | ⏸️      | ⏸️      | 待编写规格 |
| A11   | ⏸️      | ⏸️      | ⏸️      | Stub实现 |
| A12   | ⏸️      | ⏸️      | ⏸️      | 待编写规格 |
| A2    | ⏸️      | ❌      | ❌      | 未调度 |
| A7    | ⏸️      | ❌      | ❌      | 未调度 |
| A8    | ⏸️      | ❌      | ❌      | 未调度 |

**图例**：
- ✅ 已完成
- ⏸️ 待执行
- ❌ 不可用/需修复
- 🚧 进行中

---

## 🎯 下一步行动

1. 补充 A3 Agent 规格文档
2. 补充 A4 Agent 规格文档
3. 补充 A5 Agent 规格文档
4. 补充 A6 Agent 规格文档
5. 补充 A9 Agent 规格文档
6. 规格完成后，开始在 109 上逐个启用 Agent

**预计时间**：
- 每个规格文档：30-60 分钟
- 每个 Agent 启用+验证：15-30 分钟
- 总计：约 6-10 小时

**负责人**：待分配

**环境信息（保留）**：
- **部署目标**: root@172.27.78.109
- **远程路径**: /opt/ai-native/repos/agent-workers/
- **服务**: ai-native-agents (systemd)
- **部署方法**: scp + systemctl restart
