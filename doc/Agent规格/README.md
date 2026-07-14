# Agent规格文档清单

## 📋 已完成规格

### 阶段一：需求分析
- ✅ `A1-需求分析Agent完整设计.md` (v3.5) - 多轮对话需求引导与结构化分析
- ✅ `A2-知识分析Agent规格.md` (v3.5) - 知识库检索与可行性评估
- ✅ `Gate0-产品审批设计.md` (v3.5) - 产品审批节点
- ✅ `阶段一-数据字典.md` (v1.3) - 阶段一全链路数据规范

### 阶段二：设计
- ✅ `A3-UI原型Agent完整设计.md` (v1.0) - 高保真原型生成与多轮标注迭代
- ✅ `A4-Spec撰写Agent规格.md` (v1.0) - Spec/OpenAPI/ERD/DDL 四件套撰写
- ✅ `A5-自动设计检查Agent规格.md` (v1.0) - 五维自动化设计检查（非阻断）
- ✅ `Gate1-产品审批设计.md` (v1.0) - 设计审批节点
- ✅ `阶段二-数据字典.md` (v1.0) - 阶段二全链路数据规范（阶段一增量扩展）

## 🚧 待编写规格

### 主流程 Agent（按调度顺序）
1. **A3 - UI生成Agent** (DESIGNING 阶段)
   - 职责: 根据需求生成 UI 状态图和交互流程
   - 代码: `repos/agent-workers/a3_ui_generator.py`
   - 状态: ✅ 已实现并调度

2. **A4 - 规格编写Agent** (DESIGNING 阶段)
   - 职责: 生成 OpenAPI 规格和 ERD 设计
   - 代码: `repos/agent-workers/a4_spec_writer.py`
   - 状态: ✅ 已实现并调度（自持久化到 api_schemas/erd_designs 表）

3. **A5 - 设计评审Agent** (REVIEWING 阶段)
   - 职责: 评审 A3+A4 的设计产物，决定是否 rework
   - 代码: `repos/agent-workers/a5_design_review.py`
   - 状态: ✅ 已实现并调度

4. **A6 - 任务分解Agent** (DECOMPOSING 阶段)
   - 职责: 将 spec 分解为开发任务列表
   - 代码: `repos/agent-workers/a6_spec_decomposer.py`
   - 状态: ✅ 已实现并调度

5. **A9 - 开发Agent** (DEVELOPING 阶段)
   - 职责: 双脑架构（Coder + Auditor）生成代码
   - 代码: `repos/agent-workers/a9/` (engine.py, coder.py, auditor.py)
   - 状态: ✅ 已实现并调度

6. **A11 - 自动化测试Agent** (TESTING 阶段)
   - 职责: 生成测试策略并执行测试
   - 代码: `repos/agent-workers/a11_test_agent_stub.py`
   - 状态: ⚠️ Stub 实现（15% 模拟失败率，生产不可用）

7. **A12 - 代码审查Agent** (REVIEWING_CODE 阶段)
   - 职责: 审查代码质量、安全性、规范性
   - 代码: `repos/agent-workers/a12_code_review.py`
   - 状态: ✅ 已实现并调度

### 辅助 Agent（未调度）
8. **A2 - 知识检索Agent**
   - 职责: 从知识库检索相关历史需求和技术文档
   - 代码: ⚠️ 未找到实现文件
   - 状态: ❌ 未在 `requirement_workflow.py` 的 `_AGENT_STATES` 中

9. **A7 - 测试用例生成Agent**
   - 职责: 根据 spec 生成测试用例
   - 代码: `repos/agent-workers/a7_test_case_generator.py`
   - 状态: ❌ 已实现但未调度

10. **A8 - 架构评审Agent**
    - 职责: 评审系统架构设计
    - 代码: `repos/agent-workers/a8_architecture_expert.py`
    - 状态: ❌ 已实现但未调度

### 其他 Agent
11. **A10 - TDD编码Agent**
    - 职责: 测试驱动开发模式
    - 代码: `repos/agent-workers/a9_tdd_coder.py`
    - 状态: 🤔 存在但未集成到主流程

12. **A13 - 发布Agent**
    - 职责: 代码发布与部署
    - 代码: ⚠️ 未找到实现文件
    - 状态: ❌ 未实现

---

## 📐 规格模板结构

每个 Agent 规格包含：

1. **基本信息**: Agent ID, Type, 订阅/发布事件, 代码位置
2. **职责**: 3-5 句话核心描述
3. **输入**: Context Package 结构 + 关键字段
4. **处理流程**: Phase 1/2/3... 的详细步骤
5. **输出**: 返回结构 + 持久化位置
6. **LLM 调用**: 任务类型、温度、Prompt 结构
7. **依赖**: 上游/下游/外部服务
8. **当前实现状态**: ✅已实现 / ⚠️部分实现 / ❌未实现
9. **已知问题**: 问题 + 影响 + 建议
10. **测试方法**: 单元测试 / NATS 触发 / 端到端测试

参考: `A1-需求分析Agent规格.md`

---

## 🎯 编写优先级

### P0（立即编写）
- A3, A4, A5, A6 - 设计阶段核心 Agent
- A9 - 开发阶段核心 Agent

### P1（短期补充）
- A11, A12 - 测试与审查阶段
- A7 - 测试用例生成（需先修复调度）

### P2（中期补充）
- A2, A8 - 辅助功能（需先修复调度）

### P3（长期规划）
- A10, A13 - 可选功能
