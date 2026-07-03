# AI Native 研发协同系统 · 调研与立项报告

> **文档定位**：决策 / 立项向 · 面向高管、技术负责人、投资决策者
> **回答的问题**：为什么现在要做？对标谁？有哪些数据支撑？价值与 ROI 几何？风险与边界在哪？如何分期落地？
> **配套文档**：`02 · 多 Agent 编排架构与设计规格`（怎么建）、`03 · 人机协同与指挥舱产品总览`（人怎么用）、`00 · 总纲与导读`
> **版本**：v2.0 ｜ **数据基准时点**：2026 年 6 月

---

## 执行摘要（TL;DR）

软件工程正在经历从 **"AI 辅助编码（Copilot）"** 到 **"AI 原生研发（AI Native Agentic Engineering）"** 的范式转移。本报告论证一个核心判断：

> **单纯把更强的模型塞进开发者的编辑器，并不能稳定地提升交付效率；真正的杠杆在于"编排（Orchestration）"——用一套带门禁、带环境裁判、带防死循环的多 Agent 系统，把 AI 的能力组织成从需求到发布的可收敛闭环。**

支撑这一判断的三组关键事实：

1. **模型能力已"够强但不稳"**：前沿模型在 SWE-bench Verified 上已达 88%+，但在抗数据污染、标准化脚手架下的 SWE-bench Pro 上同款模型只能解决约 **59%** 的真实任务[^swebench][^swebenchpro]。能力到位，可靠性不够——这正是"编排与裁判"存在的理由。
2. **裸用 AI 会翻车**：METR 2025 年的随机对照试验显示，资深开源工程师在自己熟悉的成熟代码库上使用 AI，完成任务反而 **慢了 19%**，而他们主观以为快了 20%[^metr]。与此同时，受控企业实验里 Copilot 又能带来 **+26% 任务吞吐 / 55% 提速**[^copilot]。差异不在模型，而在**使用方式与工程上下文**。
3. **多 Agent 是把双刃剑**：Anthropic 的内部评测中，多 Agent 系统（Opus 主控 + Sonnet 子 Agent）比单 Agent 强 **90.2%**，但 token 消耗是普通对话的 **约 15 倍**[^multiagent]。这意味着：多 Agent 必须用在"价值足够高、且可并行"的环节，并配套严格的成本与熔断治理。

**结论与建议**：建议立项建设本系统，但采取 **"先闭环、后扩面"** 的分期策略（详见第八章）。优先打通"编码—测试—修复"的环境裁判闭环（投入产出比最高），再向需求左移与全局智能扩展。系统的差异化不在"又一个写代码的 Agent"，而在 **环境即裁判（Environment as Critic）+ 双脑自审 + 多级防死循环 + Human-in-the-Loop 门禁** 这套"让 AI 自我收敛"的工程机制。

---

## 一、看趋势：从 Copilot 到 AI Native 的三次范式转移

过去两年，行业共识已经从"模型能不能写对一段代码"转向"如何让一群 Agent 端到端地、可靠地交付一个需求"。三个不可逆的转移：

### 1.1 从"代码生成"到"任务闭环"

AI 不再是被动的代码补全器，而是具备 **"感知环境 → 调用工具 → 自我修正"** 能力的自治体（Agent）。Anthropic 在《Building Effective Agents》中明确区分了两类系统：**Workflow**（LLM 与工具按预定义代码路径编排）与 **Agent**（LLM 动态决定自己的流程与工具调用）[^bea]。本系统是二者的混合体——**用确定性的 Workflow 编排骨架（状态机/DAG/门禁），在每个节点内放置具备自治能力的 Agent**。

### 1.2 从"模型互评"到"环境裁判"

让一个 LLM 去 Review 另一个 LLM 的输出，是早期多 Agent 系统的常见做法，但它有一个致命缺陷：**当评审者无法可靠区分"好"与"坏"时，评审-优化循环会退化成"幻觉共振"**——两个模型互相点头，错误反而被加固。Anthropic 的 Evaluator-Optimizer 模式文档与社区实践都点明了这一边界：*该模式仅在"有清晰评判标准、且迭代精修能带来可度量价值"时才有效*[^bea]。

因此业界的重心转向 **"Environment as the Ultimate Critic（环境是最终裁判）"**：用编译器报错、Linter 结果、类型检查、自动化测试通过率、**变异测试得分**等**客观信号**来驱动 Agent 迭代，而不是靠模型的主观判断。本系统把这一原则作为第一设计公理（详见 1.5 与 `02` 文档）。

### 1.3 从"Prompt Engineering"到"Loop / Context Engineering"

2026 年的工程共识是：核心壁垒不再是"写一个好 Prompt"，而是两件更难的事：

- **Loop Engineering**：设计能让 Agent 自主执行"生成 → 测试 → 修复"的收敛循环，并在不收敛时安全降级。
- **Context Engineering**：系统性地管理"什么进入上下文窗口"。LangChain 将其归纳为 **写入（write）、筛选（select）、压缩（compress）、隔离（isolate）** 四类策略；生产级 Agent 四者都要用[^contextrot]。

> **小结**：趋势不是"模型越大越好"，而是"**编排越精，收敛越快**"。这为本系统的立项提供了根本性的趋势依据。

---

## 二、看能力：AI 现在到底能做到什么（诚实基线）

立项的前提是对模型能力有**不被营销数字误导**的判断。

### 2.1 旗舰评测：SWE-bench 的两张面孔

SWE-bench 是衡量"模型能否修复真实 GitHub issue"的事实标准。关键在于要看两个版本：

| 评测 | 含义 | 头部模型表现（2026 中） | 解读 |
|---|---|---|---|
| **SWE-bench Verified** | 人工校验过的 500 题子集，厂商常用自有脚手架跑分 | Claude Opus 4.8 ≈ **88.6%**、GPT-5.5 ≈ **88.7%**[^swebench] | "实验室上限"，容易高估 |
| **SWE-bench Pro** | 41 个专业仓库、1865 个真实任务，**抗污染 + 标准化脚手架**，Pass@1 | 同档模型仅约 **59%**[^swebenchpro] | 更接近"真实战场" |

两个数字之间 **约 30 个百分点的落差**，正是本系统要填补的工程空间。Scale 的独立评测进一步指出：**厂商自有脚手架的跑分通常比标准化脚手架高 15–30 分**[^swebench]——这说明"脚手架/编排"对最终表现的贡献，可能不亚于模型本身。

> **决策含义**：不要把"模型已经 88 分"当作"可以放手让 AI 独立交付"的依据。**真实世界里约四成任务一次性做不对**，必须有"测试—修复—门禁"的工程兜底。这恰恰是本系统的核心价值，而非模型厂商能直接提供的。

### 2.2 一个反直觉的关键发现：token 量本身就是质量杠杆

Anthropic 在多 Agent 研究系统的复盘中给出一个重要量化结论：**token 用量可解释约 80% 的性能方差**；Agent 比普通对话多用约 4× token，多 Agent 系统多用约 15× token[^multiagent]。这意味着：

- "舍得在正确的环节花 token"（如多角度并行探索、对抗式验证）是有回报的；
- 但回报有上限和成本，必须用**预算与熔断**框住（见第七、八章）。

---

## 三、看效果：生产力的两面性（为什么"裸用 AI"不够）

这是本报告最重要的一章，因为它直接回答"为什么需要建一套系统，而不是发几个 Copilot 账号"。

### 3.1 正面证据：受控实验里的真实增益

| 研究 | 设计 | 关键结果 |
|---|---|---|
| GitHub Copilot 实验（4,800 名开发者）[^copilot] | 任务完成时间对照 | 平均完成时间 **2h41m → 1h11m（≈55% 提速）**，成功率 **70% → 78%** |
| Cui et al. 2024（微软/埃森哲等三家企业 RCT）[^copilot] | 随机分配 Copilot vs 对照组，以 PR/commit/build 为产出代理 | 完成任务数 **+26.08%** |
| GitHub 代码质量研究（2024-11）[^copilot] | 质量维度对照 | 可读性 +3.62%、可靠性 +2.94%、可维护性 +2.47%、简洁性 +4.16%（均显著） |

### 3.2 反面证据：成熟语境下 AI 反而拖慢

METR 2025 年 7 月的随机对照试验（16 名资深开源开发者、246 个真实 issue、平均 22k+ stars / 100 万+ 行的成熟仓库）发现[^metr]：

- **允许使用 AI 时，完成任务时间反而增加 19%**；
- **认知错觉极其顽固**：事前预期提速 24%，事后仍以为提速 20%，**而实际是慢了 19%**。

辅证：GitClear 2024 分析发现 **AI 生成代码的"churn（短期内被重写）率比人工代码高 41%**；Stack Overflow 2024 调查显示开发者对 AI 工具的满意度在下降[^copilot]。

### 3.3 矛盾的根因，正是系统要解决的问题

为什么同是 AI，结果天差地别？根因不在模型，而在**工程语境**：

| 失效根因 | 机理 | 本系统的对策 |
|---|---|---|
| **上下文迷失 / Context Rot** | 模型性能随上下文变长而衰减；信息处于中段被"忽视"（Lost-in-the-Middle）；Agent 把自己的旧错误当成"既定正确模式"自我强化 | 上下文工程 + 上下文污染清理（见 3.4） |
| **缺乏环境裁判** | 模型"自我感觉良好"，但没有客观信号纠偏 | 环境即裁判：编译/测试/变异测试硬卡 |
| **审查开销转移** | AI 写得快，但 Review/返工把时间又吃回去 | 双脑自审前置 + 自动修复，减少人工 Review 负担 |
| **无防死循环** | "修 A 坏 B"无限往复，token 爆炸 | 多级熔断 + 降级到人 |

> **立项的核心论点**：**AI 的价值不是自动兑现的，它取决于你把 AI 放进什么样的系统。** 本系统就是那个"让增益成为常态、把陷阱挡在门外"的系统。

### 3.4 上下文工程：被低估的工程深水区（痛点的量化证据）

"上下文迷失"不是模糊的感觉，而是有量化证据的物理规律：

- **Context Rot（Chroma 2025）**：测试 18 个前沿模型（含 GPT-4.1、Claude、Gemini），**全部** 随输入变长而退化，部分模型准确率"无预警地"从 **95% 跌到 60%**[^contextrot]。
- **Lost-in-the-Middle（Liu et al. 2023）**：把关键文档从 20 篇里的第 1 位移到第 5–15 位，准确率 **下降超 30%**，呈 U 型曲线，且 *无法靠 Prompt 指令纠正*[^contextrot]。
- **退化起点**：Databricks Mosaic 发现模型正确率在约 **32K token** 后开始下降；Factory.ai（2025-08）指出**即便百万 token 窗口也不足以容纳典型企业代码库**，无差别塞上下文反而损害推理[^contextrot]。
- **自条件化错误（self-conditioning）**：当 Agent 的上下文里包含它自己之前的错误时，后续出错概率**显著上升且加速**[^contextrot]。

这组数据直接论证了本系统两个设计的必要性：**① 子 Agent 上下文隔离**（用并行子 Agent 各自的独立窗口承载不同子任务）；**② 上下文污染清理**（外部循环连续失败后强制清空被污染的对话历史，重注入原始 Spec + 最新失败日志）。

---

## 四、看竞争：全球顶尖实践解码

下表把"行业痛点 → 巨头解法（含机制与数据）→ 对本方案的启示"串成一条逻辑链。

| 行业痛点 | 代表实践与机制 | 关键数据 / 出处 | 对本方案的启示 |
|---|---|---|---|
| Agent 自我审查产生幻觉共振 | **Anthropic《Building Effective Agents》**：Evaluator-Optimizer / Orchestrator-Workers 等 5 大模式，强调"清晰评判标准 + 上下文隔离"[^bea] | 社区共识：评判者无法分辨好坏时该模式失效 | 双脑中的 **Critic 必须由环境信号背书**，而非纯 LLM 互评 |
| 单 Agent 扛不住大型工程 | **Anthropic 多 Agent 研究系统**：Orchestrator-Worker，子 Agent 并行压缩 | 多 Agent 比单 Agent **+90.2%**，但 token **≈15×**；token 解释 **80%** 性能方差[^multiagent] | Control Plane + Spec Decomposer 拆 DAG 并行；但要做**成本/熔断治理** |
| 异步并行与沙箱隔离 | **OpenAI Codex / Factory AI（Missions/Droids）**：复杂任务拆 DAG，派发到独立云沙箱并行跑测试再合并 PR | Factory.ai：百万 token 窗口仍不足，需上下文工程[^contextrot] | Worker 节点 + 独立沙箱；DAG 调度 |
| AI 写"废话测试"（断言永真） | **Meta TestGen-LLM**：用变异测试 + 多级过滤逼出高质量断言 | Instagram 评测：**75% 编译通过、57% 稳定通过、25% 提升覆盖率**；test-a-thon 改进 **11.5%** 的类，**73%** 建议被工程师采纳上线[^testgen] | Auto Test Agent 的 Critic 采用**变异测试思想**，拒绝弱断言 |
| 需求歧义导致返工 | **Vercel v0 / 生成式 UI**："No UI, No Spec"，需求即可视化 | 生成式 UI 已成主流交互范式 | 需求阶段前置可视化：直接产出低保真草图 + 验收标准 |
| 执行前意图不对齐 | **阿里 Qoder / Quest Mode**：Agent 先与人共创 Spec，确认后再调 MCP 工具执行 | 强调"执行前对齐" | Gate 0/1 门禁 + Spec 共创 |
| 上下文丢失 | **字节 Trae / CUE 引擎**：全域抓取需求/代码/部署配置，任务状态机可视化 | 解决"只见树木不见森林" | Context Builder + 知识库 + Mission Control 可视化 |
| 极简工具 + 环境驱动 | **Anthropic Claude Code**：原子化 CLI（Read/Edit/Bash）+ `CLAUDE.md` 项目记忆 + stderr 驱动 ReAct | 拒绝高级黑盒工具 | Worker 接入用原子能力 + 项目级长期记忆 |
| 死循环与人类接管 | **Cognition Devin / 业界共识**：Agentic Loop + 硬性重试阈值 + 人类接管 | — | 多级熔断（内 2 / 外 3 / 辩论 3）+ 降级到 IDE |

> **解读**：本方案不是对某一家的模仿，而是**把"环境裁判（Meta/Anthropic）+ DAG 并行（Factory/OpenAI）+ Spec 共创（阿里）+ 全域上下文（字节）+ 前置可视化（Vercel）"组合成一条端到端流水线**，并补上了大多数厂商方案中缺失的一环——**面向人类的全局可观测与门禁（Mission Control）**。

---

## 五、看痛点：当前研发场景的核心瓶颈（量化）

| 痛点 | 表现 | 量化证据 | 本系统对策（详见 `02`） |
|---|---|---|---|
| **上下文迷失** | 改 A 文件破坏 B 文件逻辑 | Context Rot：18/18 模型退化；Lost-in-Middle 降幅 >30%[^contextrot] | 上下文隔离 + Change Propagation 变更传播 |
| **死循环与 token 爆炸** | "修改-报错-再修改"无效往复 | 自条件化错误加速；多 Agent token ≈15×[^multiagent][^contextrot] | 内 2 / 外 3 / 辩论 3 级熔断 + 上下文清理 |
| **资产无法沉淀** | 产出为"阅后即焚"的对话与临时补丁 | 行业普遍痛点 | Knowledge Keeper 全局旁路结构化沉淀 |
| **安全与合规失控** | Agent 随意执行 `rm -rf` / `git push` 等高危命令 | 缺乏企业级 HITL | 4 道 Gate + 高危命令白名单 + 沙箱 |
| **测试质量虚高** | 断言过弱、永远 Pass | TestGen-LLM 证明需变异测试兜底[^testgen] | 变异测试 Critic + 测试质量雷达图 |

---

## 六、本方案的差异化主张

把上述趋势、能力、效果、竞品、痛点收敛为五条**可执行**的设计主张（在 `02` 文档展开为架构与规格）：

1. **环境即裁判（Environment as Critic）——第一公理。** 所有"质量判定"最终都要落到客观信号：编译/类型/Lint/单测/集成/E2E/变异测试得分/安全扫描。LLM 只负责"生成"和"解释失败"，**不负责给自己打通过分**。这条主张直接化解了原始构想中"既要抛弃 LLM 互评、又要双脑互审"的逻辑矛盾：**双脑里的 Critic 是"环境信号的组织者与解释者"，不是"自封的法官"。**
2. **双脑自审（Generator–Critic）——把返工左移到 Agent 内部。** Dev/Test Agent 内部拆为 Coder/Tester（生成者）与 Auditor/Critic（环境锚定审查者），**Critic 看不到 Generator 的思考过程，只看最终产物 + 环境信号**，强制上下文隔离，避免幻觉共振。
3. **多级防死循环 + 优雅降级。** 内部微循环 ≤2、外部大循环 ≤3、设计辩论 ≤3 轮；超限即清理上下文、升级模型/CoT、最终降级到人。把"token 爆炸"从风险变成被治理的有界量。
4. **Human-in-the-Loop 四道门禁。** Gate 0 需求 / Gate 1 设计 / Gate 2 架构 / Gate 3 发布，配 SLA 与超时升级，守住方向性、设计、技术债与生产四条底线。
5. **需求前置可视化 + 全局可观测。** 需求即出低保真原型与验收标准（消除歧义）；Mission Control 指挥舱让"AI 在干什么、卡在哪、要不要我拍板"一目了然。

---

## 七、价值与 ROI 测算

> ⚠️ **数据性质说明**：本章的"节省比例/周期时间"为 **基于配套原型（见 `03` 文档与已实现的 Mission Control）建立的设计目标值与示例模型**，并以第三章的外部受控实验（Copilot +26%~55%、METR −19%）作为**上下界 sanity check**。落地后须以真实埋点替换，**不应作为承诺值对外引用**。

### 7.1 单需求价值流：目标 vs 传统基线

取一个中等需求（如"订单批量导出"）为例，配套原型中的价值流目标如下：

| 阶段 | 传统基线 | 目标（AI 编排） | 主责 |
|---|---|---|---|
| 需求录入 | 1.0h | 0.5h | 需求 Agent |
| 需求澄清/可行性 | 2.0h | 1.0h | 需求/知识 Agent |
| UI 原型 | 4.0h | 0.5h | UI Agent |
| 设计评审（含人工 Gate） | — | ~2.0h（含等待） | 人 + 评审组 |
| 方案拆解 | 1.0h | 0.5h | Spec Decomposer |
| 开发 | 6.0h | ~3.0h | Dev Agent×N |
| 测试 | 2.0h | 1.0h | Auto Test Agent |
| 发布 | 0.5h | 0.5h | Release Agent |

对应的团队级目标指标（原型中的示例）：**周期时间 5.2 天 → 2.3 天**、**吞吐量 +20%**、**AI 贡献度 ≈68%**（编码环节高达 75%、部署 90%、代码审查仅 30% 由 AI）、**Bug 逃逸率 8% 并下降**。这些数字与外部实验的量级（Copilot +26% 吞吐 / 55% 提速）相容，可信区间合理。

### 7.2 简化 ROI 模型（示例）

设一支 20 人研发团队，人均全负荷成本 80 万元/年：

- **保守情景**（采纳 METR 式谨慎假设，仅在适配环节增益，整体净提效 **15%**）：等效释放约 3 个 FTE ≈ **240 万元/年** 的产能。
- **中性情景**（净提效 **30%**，接近 Copilot 企业 RCT 量级）：≈ **480 万元/年**。
- **成本侧**：多 Agent 的 token 成本（≈15× 对话）+ 平台研发与运维。**关键治理点**：通过"只在高价值、可并行环节启用多 Agent + 熔断预算"把 token 成本压在收益的零头量级。

> **结论**：即使按保守情景，**净收益为正**；真正的风险不是"省不出钱"，而是"治理不好 token 与死循环导致成本失控"——这恰恰是本系统第 3 条主张（防死循环）的价值所在。

---

## 八、风险、边界与合规（诚实清单）

立项必须正视边界，避免"全自动神话"。

| 风险 / 边界 | 证据 | 缓解措施 |
|---|---|---|
| **多 Agent 不是万能** | Anthropic：编码任务的"可真正并行子任务"少于研究类任务；Agent 间实时协调能力仍弱[^multiagent] | 编码环节以"少量 Dev Agent + 强环境裁判"为主，不盲目堆 Agent 数量 |
| **token 成本失控** | 多 Agent ≈15× 对话 token[^multiagent] | 预算上限 + 熔断 + 仅高价值环节启用 |
| **认知错觉导致误判收益** | METR：事后仍高估提速[^metr] | 用客观埋点（DORA 类指标）度量，不靠主观问卷 |
| **AI 代码 churn 偏高** | GitClear：+41% churn[^copilot] | 双脑自审 + 变异测试 + Code Review Agent 前置拦截 |
| **上下文退化引入隐性 bug** | Context Rot / Lost-in-Middle[^contextrot] | 上下文隔离 + 污染清理 + 关键信息置于首尾 |
| **安全/合规越权** | 高危命令风险 | 4 道 Gate + 命令白名单 + 沙箱 + 审计日志 |
| **过度自动化、人失去掌控** | 黑盒不可信 | Mission Control 全程可观测 + 可"暂停/接管"任一 Agent |

> **边界声明**：本系统的目标是 **"大部分确定性执行由 AI 完成（约 80%）、人聚焦 20% 的决策与创造"**，而非"100% 无人化"。门禁与可观测性是为了让人**在关键点保持掌控**，而不是被流程淹没。

---

## 九、分期演进路线（落地建议）

遵循"先闭环、后扩面"，每期都有独立可验证的价值，避免"大爆炸式"上线。

### Phase 1（MVP，0–3 月）：打通"编码—测试—修复"环境裁判闭环
- **落地**：Dev Agent（内部双脑）、Auto Test Agent（变异测试 Critic）、CI/CD Agent、防死循环熔断、Mission Control 的 Agent 活动直播 + 测试洞察。
- **为什么先做这里**：开发-测试是最耗时、增益最确定的环节；环境裁判在这里信号最强（编译/测试天然客观）。
- **成功指标**：闭环内"测试通过且无人工介入"的任务占比、平均修复轮次 ≤2、token 成本/需求落在预算内。

### Phase 2（设计左移，3–6 月）：需求到设计自动化
- **落地**：需求 Intake Agent（前置可视化）、知识 Analyst、UI Generator、Spec Writer、Design Review Panel、Gate 0/1、需求录入工作台（见 `03`）。
- **成功指标**：需求澄清耗时下降、Gate 1 打回率下降、Spec 完整度达标率。

### Phase 3（全局智能，6–12 月）：让系统"越用越聪明 + 抗变更"
- **落地**：Knowledge Keeper（资产沉淀）、Change Propagation（变更传播）、Spec Decomposer 的复杂任务 DAG、Architecture Expert、Release Agent 的金丝雀 + 自动回滚、效能仪表盘全量指标。
- **成功指标**：知识库覆盖度、变更影响识别准确率、发布回滚 MTTR。

---

## 参考文献

[^swebench]: SWE-bench Verified Leaderboard / SEAL 标准化评测；vendor scaffold 与标准化脚手架差异说明。SWE-bench 官方：https://www.swebench.com/ ；LLM-Stats：https://llm-stats.com/benchmarks/swe-bench-verified
[^swebenchpro]: SWE-bench Pro（Scale AI）——41 个专业仓库、1865 个真实任务、抗污染、标准化脚手架，Pass@1 ≈59%。https://labs.scale.com/leaderboard/swe_bench_pro_public
[^bea]: Anthropic, *Building Effective Agents*（五大工作流模式：Prompt Chaining / Routing / Parallelization / Orchestrator-Workers / Evaluator-Optimizer；及其适用边界）。https://www.anthropic.com/research/building-effective-agents
[^multiagent]: Anthropic Engineering, *How we built our multi-agent research system*（多 Agent +90.2%；token ≈15× 对话、Agent ≈4×；token 解释 ~80% 性能方差；编码任务并行性低于研究类）。https://www.anthropic.com/engineering/multi-agent-research-system
[^testgen]: Alshahwan et al., *Automated Unit Test Improvement using Large Language Models at Meta*, FSE 2024（TestGen-LLM：75% 编译通过 / 57% 稳定通过 / 25% 提升覆盖率；test-a-thon 改进 11.5% 类、73% 建议被采纳；变异测试 + 多级过滤）。arXiv:2402.09171 ｜ https://arxiv.org/abs/2402.09171
[^metr]: METR, *Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity*（RCT：允许 AI 反而慢 19%；事前预期 +24%、事后自评 +20%）。arXiv:2507.09089 ｜ https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
[^copilot]: GitHub Copilot 生产力与质量研究合集——GitHub Blog（55% 提速、质量四维显著提升）：https://github.blog/news-insights/research/research-quantifying-github-copilots-impact-on-developer-productivity-and-happiness/ ；Cui et al. 2024 企业 RCT（+26% 完成任务）；GitClear 2024（AI 代码 churn +41%）。
[^contextrot]: 上下文工程证据合集——Chroma 2025 *Context Rot*（18 模型全部退化）；Liu et al. 2023 *Lost in the Middle*（中段降幅 >30%，U 型曲线）；Databricks Mosaic（~32K token 后退化）；Factory.ai 2025-08（百万 token 仍不足）；LangChain 上下文工程四策略（write/select/compress/isolate）。综述参考：https://blog.logrocket.com/context-rot-slowing-down-your-ai-agent-how-fix/

> 注：以上为公开来源在 2026 年 6 月时点的检索结论；榜单类数据（如 SWE-bench）随时间快速变动，引用时请以原始链接的最新值为准。
