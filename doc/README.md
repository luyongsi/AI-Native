# AI-Native 研发协同系统文档目录

## 📂 目录结构

### 📘 系统架构（有效文档）
- `AI-Native研发协同系统-04-Agent协作与触发机制详规.md` - Agent 协作与触发机制（v3.0，当前最新）
- `Agent数据流架构.md` - Agent 数据流与编排架构
- `Orchestrator完整规格.md` - Orchestrator 状态机与调度逻辑
- `Orchestrator重构规格.md` - Orchestrator 重构规格
- `LLM-Provider审计规格.md` - LLM Provider 审计与修复

### 🤖 Agent规格（各Agent详细规格）
- `A1-需求分析Agent规格.md` - A1 需求分析 Agent
- *(待补充其他 Agent 规格)*

### 📦 部署文档
- `DEPLOY.md` - 部署指南
- `deploy/` - 各服务部署配置

### 📚 原始设计文档（总纲）
- `AI-Native研发协同系统-00-总纲与导读.md`
- `AI-Native研发协同系统-01-调研与立项报告.md`
- `AI-Native研发协同系统-02-多Agent编排架构与设计规格.md`
- `AI-Native研发协同系统-03-人机协同与指挥舱产品总览.md`
- `AI-Native研发协同系统-05-技术栈与工程落地详规.md`

### 🗄️ archive/（归档）

#### bug分析/
- `llm-provider-audit-bugs.md` - LLM Provider 审计发现的 bug
- `agent-implementation-audit.md` - Agent 实现审计
- `a9-agent-design-analysis.md` - A9 Agent 设计分析
- `a9-task-breakdown.md` - A9 任务分解

#### 历史计划/
- `A9实现计划.md` - A9 历史实现计划

#### 废弃规格/
- `A9-Agent设计规格.md` - A9 旧版设计规格（已被新实现替代）
- `JAP-Plus吸收计划.md` - JAP Plus 吸收计划（已废弃）
- `测试工具规格.md` - 测试工具规格
- `测试工具规格审计.md` - 测试工具规格审计

#### 其他归档
- `原始调研文档.md` - 最早的调研文档
- `剩余工作清单.md` - 历史工作清单

---

## 📝 文档更新规则

### 有效文档（系统架构 + Agent规格）
- **保持最新**：反映当前代码实现
- **版本标记**：重大变更需要标记版本号（如 v3.0）
- **审计机制**：发现与代码不一致时立即更新

### 原始设计文档（总纲 00-05）
- **冻结状态**：不再修改，保留历史设计思路
- **参考价值**：理解系统设计初衷和演进路径

### 归档文档
- **只读**：不再更新
- **保留原因**：历史记录、问题追溯、设计决策参考

---

## 🔄 最近更新

### 2026-07-08
- ✅ 创建 Agent规格 目录，补充 A1 规格
- ✅ 整理 doc 目录结构，归档废弃文档
- ✅ 移动部署文档到 doc/部署文档
- ✅ 将 bugs/、specs/、plan/ 按类型归档

### 待办
- [ ] 补充 A3、A4、A5、A6、A9、A11、A12 规格
- [ ] 更新 Orchestrator 工作模式文档（已生成，待整合）
- [ ] 标记 A2、A7、A8 为"未调度"状态
