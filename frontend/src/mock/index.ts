// ============================================================
// Mock Data — 所有页面的模拟数据
// ============================================================

// --- 需求 (Requirements) ---
export interface Requirement {
  id: string;
  title: string;
  description: string;
  status: 'pool' | 'designing' | 'developing' | 'testing' | 'releasing' | 'done';
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  version: string;
  pm: string;
  assignees: string[];
  aiCompletion: number; // 0-100
  humanInterventions: number;
  createdAt: string;
  blocked: boolean;
  blockReason?: string;
  slaDeadline?: string;
  stages: RequirementStage[];
  specSections?: SpecSection[];
  relatedIds: string[];
}

export interface RequirementStage {
  name: string;
  status: 'done' | 'in_progress' | 'waiting' | 'pending';
  duration: string; // e.g. "0.5h"
  baseline: string; // e.g. "1h"
  assignee: string;
}

export interface SpecSection {
  id: string;
  title: string;
  status: 'pending' | 'generating' | 'done' | 'editing' | 'conflict';
  content: string;
  history: { time: string; action: string }[];
}

// --- Agent ---
export interface AgentInfo {
  id: string;
  name: string;
  type: string;
  status: 'running' | 'idle' | 'waiting' | 'error';
  taskId: string;
  taskName: string;
  runtime: string;
  toolCalls: number;
  toolSuccess: number;
  toolFailed: number;
  codeAdded: number;
  codeRemoved: number;
  lastActivity: AgentActivity[];
  anomaly?: string;
}

export interface AgentActivity {
  time: string;
  type: 'think' | 'tool_call' | 'code_gen' | 'commit' | 'test' | 'error' | 'wait';
  content: string;
  detail?: string;
  success?: boolean;
  diffId?: string;
}

// --- Code Diff ---
export interface DiffLine {
  type: 'add' | 'remove' | 'context';
  oldLineNumber?: number;
  newLineNumber?: number;
  content: string;
}

export interface DiffHunk {
  header: string;
  lines: DiffLine[];
}

export interface CodeDiff {
  id: string;
  agentId: string;
  file: string;
  language: string;
  hunks: DiffHunk[];
  addedLines: number;
  removedLines: number;
}

// --- 审批 ---
export interface ApprovalItem {
  id: string;
  gate: 'Gate1' | 'Gate2' | 'Gate3';
  requirementId: string;
  requirementTitle: string;
  submitter: string;
  submitterRole: string;
  priority: 'high' | 'medium' | 'low';
  createdAt: string;
  slaDeadline: string;
  status: 'pending' | 'approved' | 'rejected' | 'overdue';
  agentReviews: { agent: string; verdict: string; comment: string }[];
}

// --- 通知 ---
export interface Notification {
  id: string;
  type: 'approval' | 'agent_error' | 'requirement_change' | 'done' | 'system';
  level: 'critical' | 'warning' | 'info' | 'success';
  title: string;
  description: string;
  time: string;
  read: boolean;
  link?: string;
}

// --- 告警 ---
export interface Alert {
  id: string;
  level: 'critical' | 'warning';
  title: string;
  description: string;
  time: string;
  affected: string;
  rootCause: string;
  suggestion: string;
  acknowledged: boolean;
}

// --- 版本 ---
export interface Release {
  version: string;
  status: 'planning' | 'developing' | 'testing' | 'releasing' | 'released';
  releaseWindow: string;
  totalReqs: number;
  completedReqs: number;
  requirements: { id: string; title: string; status: string; pm: string }[];
  risks: { level: string; reqId: string; description: string }[];
}

// --- 效能 ---
export interface PerformanceMetrics {
  cycleTime: number; // 天
  cycleTimeTrend: number; // 变化百分比
  throughput: number; // 每周
  throughputTrend: number;
  aiContribution: number; // 百分比
  aiContributionTrend: number;
  codeQuality: number; // 0-100
  codeQualityTrend: number;
  bugEscapeRate: number; // 百分比
  bugEscapeRateTrend: number;
  cycleTimeHistory: { week: string; value: number }[];
  bottleneckDistribution: { name: string; percentage: number }[];
  aiVsHumanStages: { name: string; ai: number; human: number }[];
}

// ============================================================
// Mock Data Instances
// ============================================================

export const mockRequirements: Requirement[] = [
  {
    id: 'REQ-795',
    title: '支付安全加固',
    description: '升级支付接口加密算法，增加二次验证流程',
    status: 'pool',
    priority: 'P0',
    version: 'V2.3.0',
    pm: '张三',
    assignees: [],
    aiCompletion: 0,
    humanInterventions: 0,
    createdAt: '2026-06-25 09:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'pending', duration: '-', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'pending', duration: '-', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'pending', duration: '-', baseline: '2h', assignee: '人工审批' },
      { name: '方案拆解', status: 'pending', duration: '-', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'pending', duration: '-', baseline: '8h', assignee: 'DevAgent' },
      { name: '测试', status: 'pending', duration: '-', baseline: '2h', assignee: 'TestAgent' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: 'CI Agent' },
    ],
  },
  {
    id: 'REQ-789',
    title: '订单批量导出功能',
    description: '在订单详情页新增批量导出功能，支持 Excel/CSV 格式，支持日期范围筛选',
    status: 'designing',
    priority: 'P1',
    version: 'V2.3.0',
    pm: '张三',
    assignees: ['PRD Agent', 'UI Agent'],
    aiCompletion: 35,
    humanInterventions: 1,
    createdAt: '2026-06-25 17:00',
    blocked: true,
    blockReason: '等待产品经理审批 Gate 1',
    slaDeadline: '2026-06-25 19:00',
    relatedIds: ['REQ-794'],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '1.0h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '0.5h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'waiting', duration: '等待2.0h', baseline: '2h', assignee: '张三(PM)' },
      { name: '方案拆解', status: 'pending', duration: '-', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'pending', duration: '-', baseline: '6h', assignee: 'DevAgent-1,2' },
      { name: '测试', status: 'pending', duration: '-', baseline: '2h', assignee: 'TestAgent' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: 'CI Agent' },
    ],
    specSections: [
      {
        id: 's1', title: '功能说明', status: 'done',
        content: '在订单列表页和订单详情页新增批量导出入口。用户可选择日期范围、订单状态进行筛选后导出。',
        history: [
          { time: '17:00', action: 'PRD Agent 从群聊提取需求' },
          { time: '17:15', action: '张三确认功能范围' },
        ],
      },
      {
        id: 's2', title: '用户故事', status: 'done',
        content: '作为运营人员，我希望导出指定时间范围内的订单数据，以便进行数据分析。',
        history: [
          { time: '17:05', action: 'PRD Agent 生成用户故事' },
        ],
      },
      {
        id: 's3', title: '接口契约', status: 'generating',
        content: 'POST /api/orders/export { startDate, endDate, status, format } → { downloadUrl }',
        history: [
          { time: '17:10', action: 'PRD Agent 分析现有接口' },
        ],
      },
      {
        id: 's4', title: '验收标准', status: 'editing',
        content: '1. 支持 Excel 和 CSV 两种格式\n2. 单次导出上限 10 万条\n3. 超出上限自动分批导出',
        history: [
          { time: '17:12', action: 'PRD Agent 生成验收标准草案' },
          { time: '17:30', action: '张三补充：增加分批导出需求' },
        ],
      },
      {
        id: 's5', title: 'UI原型说明', status: 'done',
        content: '导出按钮位于订单列表页右上角，与"筛选"、"刷新"按钮同组。',
        history: [
          { time: '17:20', action: 'UI Agent 生成原型并关联' },
        ],
      },
    ],
  },
  {
    id: 'REQ-785',
    title: '地址管理优化',
    description: '支持省市区级联选择，自动填充邮政编码',
    status: 'developing',
    priority: 'P1',
    version: 'V2.3.0',
    pm: '李四',
    assignees: ['DevAgent-1', 'DevAgent-2', '小李'],
    aiCompletion: 60,
    humanInterventions: 0,
    createdAt: '2026-06-24 14:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '0.8h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '0.3h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '0.5h', baseline: '2h', assignee: '李四(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.5h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'in_progress', duration: '进行中...', baseline: '6h', assignee: 'DevAgent-1,2 + 小李' },
      { name: '测试', status: 'pending', duration: '-', baseline: '2h', assignee: 'TestAgent' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: 'CI Agent' },
    ],
  },
  {
    id: 'REQ-780',
    title: '登录页重构',
    description: '优化登录注册流程UI，增加社交登录方式',
    status: 'testing',
    priority: 'P2',
    version: 'V2.3.0',
    pm: '赵六',
    assignees: ['测试小陈'],
    aiCompletion: 70,
    humanInterventions: 2,
    createdAt: '2026-06-23 10:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '1h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '1.5h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '1h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '1h', baseline: '2h', assignee: '赵六(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.5h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'done', duration: '4h', baseline: '8h', assignee: 'DevAgent-3' },
      { name: '测试', status: 'in_progress', duration: '进行中...', baseline: '2h', assignee: '测试小陈' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: 'CI Agent' },
    ],
  },
  {
    id: 'REQ-777',
    title: '支付流程优化',
    description: '优化支付完成页引导，减少支付流失率',
    status: 'releasing',
    priority: 'P1',
    version: 'V2.2.0',
    pm: '张三',
    assignees: ['小张'],
    aiCompletion: 65,
    humanInterventions: 1,
    createdAt: '2026-06-20 09:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '1h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '0.5h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '0.5h', baseline: '2h', assignee: '张三(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.3h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'done', duration: '3h', baseline: '6h', assignee: 'DevAgent-1' },
      { name: '测试', status: 'done', duration: '1.5h', baseline: '2h', assignee: 'TestAgent' },
      { name: '发布', status: 'in_progress', duration: '待部署', baseline: '0.5h', assignee: 'CI Agent' },
    ],
  },
  {
    id: 'REQ-770',
    title: '消息推送优化',
    description: '支持分时段推送和用户偏好设置',
    status: 'done',
    priority: 'P3',
    version: 'V2.2.0',
    pm: '李四',
    assignees: [],
    aiCompletion: 80,
    humanInterventions: 0,
    createdAt: '2026-06-15 10:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '0.5h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '0.3h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '0.2h', baseline: '2h', assignee: '李四(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.3h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'done', duration: '2h', baseline: '4h', assignee: 'DevAgent-2' },
      { name: '测试', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'TestAgent' },
      { name: '发布', status: 'done', duration: '0.2h', baseline: '0.5h', assignee: 'CI Agent' },
    ],
  },
  {
    id: 'REQ-794',
    title: '消息推送新渠道接入',
    description: '接入企业微信和钉钉推送渠道',
    status: 'pool',
    priority: 'P2',
    version: 'V2.3.0',
    pm: '李四',
    assignees: [],
    aiCompletion: 0,
    humanInterventions: 0,
    createdAt: '2026-06-25 11:00',
    blocked: false,
    relatedIds: ['REQ-789'],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.3h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'pending', duration: '-', baseline: '2h', assignee: '' },
      { name: 'UI原型', status: 'pending', duration: '-', baseline: '4h', assignee: '' },
      { name: '设计评审', status: 'pending', duration: '-', baseline: '2h', assignee: '' },
      { name: '方案拆解', status: 'pending', duration: '-', baseline: '0.5h', assignee: '' },
      { name: '开发', status: 'pending', duration: '-', baseline: '4h', assignee: '' },
      { name: '测试', status: 'pending', duration: '-', baseline: '1h', assignee: '' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: '' },
    ],
  },
  {
    id: 'REQ-790',
    title: '退款流程优化',
    description: '支持部分退款和原路返回，优化退款审批流程',
    status: 'designing',
    priority: 'P1',
    version: 'V2.3.0',
    pm: '赵六',
    assignees: ['PRD Agent'],
    aiCompletion: 20,
    humanInterventions: 0,
    createdAt: '2026-06-25 14:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'in_progress', duration: '进行中...', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'pending', duration: '-', baseline: '4h', assignee: '' },
      { name: '设计评审', status: 'pending', duration: '-', baseline: '2h', assignee: '' },
      { name: '方案拆解', status: 'pending', duration: '-', baseline: '0.5h', assignee: '' },
      { name: '开发', status: 'pending', duration: '-', baseline: '5h', assignee: '' },
      { name: '测试', status: 'pending', duration: '-', baseline: '2h', assignee: '' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: '' },
    ],
  },
  {
    id: 'REQ-783',
    title: '商品搜索优化',
    description: '接入 Elasticsearch，支持模糊搜索和搜索建议',
    status: 'developing',
    priority: 'P2',
    version: 'V2.3.0',
    pm: '王五',
    assignees: ['DevAgent-3'],
    aiCompletion: 55,
    humanInterventions: 0,
    createdAt: '2026-06-24 16:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '1h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '0.5h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '0.3h', baseline: '2h', assignee: '王五(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.5h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'in_progress', duration: '进行中...', baseline: '5h', assignee: 'DevAgent-3' },
      { name: '测试', status: 'pending', duration: '-', baseline: '2h', assignee: '' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: '' },
    ],
  },
  {
    id: 'REQ-781',
    title: '图片上传优化',
    description: '支持批量上传、拖拽上传，自动压缩和 CDN 分发',
    status: 'developing',
    priority: 'P0',
    version: 'V2.3.0',
    pm: '王五',
    assignees: ['小李'],
    aiCompletion: 40,
    humanInterventions: 1,
    createdAt: '2026-06-23 15:00',
    blocked: true,
    blockReason: '等待 CDN 配置变更审批',
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.5h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '0.5h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '0.5h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '0.5h', baseline: '2h', assignee: '王五(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.5h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'in_progress', duration: '阻塞中', baseline: '6h', assignee: '小李' },
      { name: '测试', status: 'pending', duration: '-', baseline: '2h', assignee: '' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: '' },
    ],
  },
  {
    id: 'REQ-779',
    title: '首页改版',
    description: '全新首页设计，增加个性化推荐模块',
    status: 'testing',
    priority: 'P2',
    version: 'V2.3.0',
    pm: '赵六',
    assignees: ['测试小刘'],
    aiCompletion: 50,
    humanInterventions: 3,
    createdAt: '2026-06-22 09:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '1h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '2h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '2h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '1h', baseline: '2h', assignee: '赵六(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.5h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'done', duration: '5h', baseline: '8h', assignee: 'DevAgent-1' },
      { name: '测试', status: 'in_progress', duration: '进行中...', baseline: '2h', assignee: '测试小刘' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: 'CI Agent' },
    ],
  },
  {
    id: 'REQ-778',
    title: '数据导出优化',
    description: '支持大文件分段导出，优化导出速度',
    status: 'developing',
    priority: 'P3',
    version: 'V2.3.0',
    pm: '王五',
    assignees: ['DevAgent-1'],
    aiCompletion: 45,
    humanInterventions: 0,
    createdAt: '2026-06-23 11:00',
    blocked: false,
    relatedIds: [],
    stages: [
      { name: '需求录入', status: 'done', duration: '0.3h', baseline: '1h', assignee: 'PRD Agent' },
      { name: '需求澄清', status: 'done', duration: '0.5h', baseline: '2h', assignee: 'PRD Agent' },
      { name: 'UI原型', status: 'done', duration: '0.3h', baseline: '4h', assignee: 'UI Agent' },
      { name: '设计评审', status: 'done', duration: '0.2h', baseline: '2h', assignee: '王五(PM)' },
      { name: '方案拆解', status: 'done', duration: '0.3h', baseline: '0.5h', assignee: 'Spec Decomposer' },
      { name: '开发', status: 'in_progress', duration: '进行中...', baseline: '4h', assignee: 'DevAgent-1' },
      { name: '测试', status: 'pending', duration: '-', baseline: '1h', assignee: '' },
      { name: '发布', status: 'pending', duration: '-', baseline: '0.5h', assignee: '' },
    ],
  },
];

export const stageColumns = [
  { key: 'pool', label: '需求池', count: 3, wipLimit: 20 },
  { key: 'designing', label: '设计中', count: 2, wipLimit: 3 },
  { key: 'developing', label: '开发中', count: 4, wipLimit: 4 },
  { key: 'testing', label: '测试中', count: 2, wipLimit: 3 },
  { key: 'releasing', label: '待发布', count: 1, wipLimit: 5 },
];

export const mockAgents: AgentInfo[] = [
  {
    id: 'agent-3',
    name: 'DevAgent-3',
    type: '开发',
    status: 'running',
    taskId: 'TASK-456',
    taskName: '订单批量导出',
    runtime: '12min',
    toolCalls: 23,
    toolSuccess: 22,
    toolFailed: 1,
    codeAdded: 145,
    codeRemoved: 32,
    lastActivity: [
      { time: '17:00', type: 'think', content: '分析TASK-456任务需求，准备修改3个文件', detail: '需要修改 OrderDetail.tsx, order.ts, types.ts' },
      { time: '17:02', type: 'tool_call', content: 'read_file("src/pages/OrderDetail.tsx")', success: true, detail: '返回 342 行' },
      { time: '17:03', type: 'tool_call', content: 'read_file("src/api/order.ts")', success: true, detail: '返回 89 行' },
      { time: '17:04', type: 'think', content: '已理解现有代码结构，开始生成修改' },
      { time: '17:05', type: 'code_gen', content: '修改 OrderDetail.tsx (+45/-12)', detail: '新增 exportOrders 导入和导出按钮', diffId: 'diff-1' },
      { time: '17:06', type: 'tool_call', content: 'run_tests(["OrderDetail.test.tsx"])', success: true, detail: '全部通过 12/12' },
      { time: '17:07', type: 'commit', content: 'commit: feat: add batch export to order detail', detail: '3 files changed' },
      { time: '17:08', type: 'wait', content: '等待 MR Review...' },
    ],
  },
  {
    id: 'agent-1',
    name: 'DevAgent-1',
    type: '开发',
    status: 'running',
    taskId: 'TASK-455',
    taskName: '地址管理优化',
    runtime: '8min',
    toolCalls: 15,
    toolSuccess: 15,
    toolFailed: 0,
    codeAdded: 89,
    codeRemoved: 12,
    lastActivity: [
      { time: '17:00', type: 'tool_call', content: 'read_file("src/api/address.ts")', success: true },
      { time: '17:01', type: 'think', content: '分析地址API，准备增加省市区接口' },
      { time: '17:03', type: 'code_gen', content: '新增省市区数据接口', detail: '+67/-5 lines', diffId: 'diff-2' },
      { time: '17:03', type: 'code_gen', content: '扩展 address.ts API', detail: '+23/-0 lines', diffId: 'diff-3' },
      { time: '17:04', type: 'tool_call', content: 'write_file("src/components/AddressCascader.tsx")', success: true, detail: '创建级联选择组件' },
    ],
  },
  {
    id: 'agent-2',
    name: 'DevAgent-2',
    type: '开发',
    status: 'idle',
    taskId: '',
    taskName: '',
    runtime: '',
    toolCalls: 0,
    toolSuccess: 0,
    toolFailed: 0,
    codeAdded: 0,
    codeRemoved: 0,
    lastActivity: [],
  },
  {
    id: 'agent-test',
    name: 'TestAgent-1',
    type: '测试',
    status: 'waiting',
    taskId: 'TASK-453',
    taskName: '登录页测试',
    runtime: '5min',
    toolCalls: 47,
    toolSuccess: 44,
    toolFailed: 3,
    codeAdded: 0,
    codeRemoved: 0,
    lastActivity: [
      { time: '17:00', type: 'test', content: '执行测试套件 LoginPage.test.tsx', detail: '47个用例，44通过，3失败' },
      { time: '17:03', type: 'error', content: '3个用例失败：登录按钮样式断言不匹配', detail: '预期 "登录" 实际 "登 录"（空格差异）' },
      { time: '17:04', type: 'tool_call', content: '通知 DevAgent-3 修复测试失败' },
    ],
    anomaly: '3个测试失败',
  },
  {
    id: 'agent-ci',
    name: 'CIAgent-1',
    type: 'CI',
    status: 'error',
    taskId: 'TASK-452',
    taskName: '构建部署',
    runtime: '3min',
    toolCalls: 12,
    toolSuccess: 10,
    toolFailed: 2,
    codeAdded: 0,
    codeRemoved: 0,
    lastActivity: [
      { time: '16:55', type: 'tool_call', content: 'npm install', success: false, detail: '依赖冲突: react版本不一致' },
      { time: '16:57', type: 'error', content: '构建失败: Exit Code 1', detail: 'package.json 中 react: ^19.0.0 但 react-dom: ^18.3.0' },
    ],
    anomaly: '构建失败 - 依赖冲突',
  },
  {
    id: 'agent-prd',
    name: 'PRD Agent',
    type: '产品',
    status: 'running',
    taskId: 'TASK-458',
    taskName: 'REQ-790 退款流程 Spec',
    runtime: '5min',
    toolCalls: 8,
    toolSuccess: 8,
    toolFailed: 0,
    codeAdded: 0,
    codeRemoved: 0,
    lastActivity: [
      { time: '17:10', type: 'think', content: '分析退款流程需求，提取关键功能点' },
      { time: '17:12', type: 'code_gen', content: '生成 Spec 初稿', detail: '4个章节' },
      { time: '17:15', type: 'wait', content: '等待补充部分退款边界条件...' },
    ],
  },
];

export const mockTopologyNodes = [
  { id: 'orchestrator', type: 'orchestrator', label: 'Orchestrator', status: 'running', position: { x: 400, y: 20 } },
  { id: 'prd-agent', type: 'agent', label: 'PRD Agent', status: 'running', position: { x: 150, y: 150 } },
  { id: 'ui-agent', type: 'agent', label: 'UI Agent', status: 'running', position: { x: 400, y: 150 } },
  { id: 'test-agent', type: 'agent', label: 'Test Agent', status: 'waiting', position: { x: 650, y: 150 } },
  { id: 'spec-decomp', type: 'agent', label: 'Spec Decomposer', status: 'running', position: { x: 275, y: 280 } },
  { id: 'dev-1', type: 'agent', label: 'DevAgent-1', status: 'running', position: { x: 50, y: 400 } },
  { id: 'dev-2', type: 'agent', label: 'DevAgent-2', status: 'running', position: { x: 275, y: 400 } },
  { id: 'dev-3', type: 'agent', label: 'DevAgent-3', status: 'done', position: { x: 500, y: 400 } },
  { id: 'ci-agent', type: 'agent', label: 'CI Agent', status: 'error', position: { x: 160, y: 520 } },
];

export const mockTopologyEdges = [
  { id: 'e-orch-prd', source: 'orchestrator', target: 'prd-agent', type: 'data' },
  { id: 'e-orch-ui', source: 'orchestrator', target: 'ui-agent', type: 'data' },
  { id: 'e-orch-test', source: 'orchestrator', target: 'test-agent', type: 'trigger' },
  { id: 'e-prd-spec', source: 'prd-agent', target: 'spec-decomp', type: 'data' },
  { id: 'e-ui-spec', source: 'ui-agent', target: 'spec-decomp', type: 'data' },
  { id: 'e-spec-dev1', source: 'spec-decomp', target: 'dev-1', type: 'data' },
  { id: 'e-spec-dev2', source: 'spec-decomp', target: 'dev-2', type: 'data' },
  { id: 'e-spec-dev3', source: 'spec-decomp', target: 'dev-3', type: 'data' },
  { id: 'e-dev3-test', source: 'dev-3', target: 'test-agent', type: 'trigger' },
  { id: 'e-dev1-ci', source: 'dev-1', target: 'ci-agent', type: 'trigger' },
  { id: 'e-dev2-ci', source: 'dev-2', target: 'ci-agent', type: 'trigger' },
];

export const mockApprovals: ApprovalItem[] = [
  {
    id: 'appr-001',
    gate: 'Gate1',
    requirementId: 'REQ-789',
    requirementTitle: '订单批量导出功能',
    submitter: 'PRD Agent + UI Agent',
    submitterRole: 'Agent',
    priority: 'high',
    createdAt: '2026-06-25 17:00',
    slaDeadline: '2026-06-25 19:00',
    status: 'pending',
    agentReviews: [
      { agent: 'TechReviewer', verdict: 'pass', comment: '技术方案可行，接口设计合理' },
      { agent: 'UXReviewer', verdict: 'warn', comment: '建议导出按钮放到右上角，与筛选按钮同组' },
      { agent: 'BusinessReviewer', verdict: 'pass', comment: '业务逻辑完整，覆盖核心场景' },
    ],
  },
  {
    id: 'appr-002',
    gate: 'Gate1',
    requirementId: 'REQ-790',
    requirementTitle: '退款流程优化',
    submitter: 'PRD Agent',
    submitterRole: 'Agent',
    priority: 'high',
    createdAt: '2026-06-25 17:30',
    slaDeadline: '2026-06-25 21:30',
    status: 'pending',
    agentReviews: [
      { agent: 'TechReviewer', verdict: 'pass', comment: '部分退款逻辑清晰' },
      { agent: 'BusinessReviewer', verdict: 'warn', comment: '需补充退款手续费的业务规则' },
    ],
  },
  {
    id: 'appr-003',
    gate: 'Gate2',
    requirementId: 'REQ-785',
    requirementTitle: '地址管理优化',
    submitter: '架构师 李四',
    submitterRole: '架构师',
    priority: 'medium',
    createdAt: '2026-06-25 13:00',
    slaDeadline: '2026-06-26 13:00',
    status: 'pending',
    agentReviews: [
      { agent: 'SecurityReviewer', verdict: 'pass', comment: '无安全风险' },
    ],
  },
  {
    id: 'appr-004',
    gate: 'Gate3',
    requirementId: 'REQ-780',
    requirementTitle: '登录页重构',
    submitter: 'Tech Lead 王五',
    submitterRole: 'Tech Lead',
    priority: 'medium',
    createdAt: '2026-06-24 15:00',
    slaDeadline: '2026-06-26 15:00',
    status: 'overdue',
    agentReviews: [],
  },
];

export const mockNotifications: Notification[] = [
  {
    id: 'notif-1',
    type: 'approval',
    level: 'warning',
    title: 'Gate1 REQ-789 Spec 确认',
    description: 'PRD Agent 提交了订单批量导出功能的 Spec，等待您的审批',
    time: '1.5小时前',
    read: false,
    link: '/approvals/REQ-789',
  },
  {
    id: 'notif-2',
    type: 'approval',
    level: 'warning',
    title: 'Gate1 REQ-790 退款流程 Spec 确认',
    description: 'PRD Agent 提交了退款流程优化的 Spec，等待您的审批',
    time: '30分钟前',
    read: false,
    link: '/approvals/REQ-790',
  },
  {
    id: 'notif-3',
    type: 'agent_error',
    level: 'critical',
    title: 'CI Agent 构建失败',
    description: 'TASK-452: npm install 依赖冲突，react 版本不一致',
    time: '3分钟前',
    read: false,
    link: '/agents/agent-ci',
  },
  {
    id: 'notif-4',
    type: 'requirement_change',
    level: 'info',
    title: 'REQ-789: 验收标准第3条已更新',
    description: '新增"全量导出"选项，原型已自动更新',
    time: '2小时前',
    read: true,
    link: '/requirements/REQ-789',
  },
  {
    id: 'notif-5',
    type: 'requirement_change',
    level: 'info',
    title: 'REQ-785: 接口契约已变更',
    description: 'POST /api/address 新增 province 字段',
    time: '5小时前',
    read: true,
    link: '/requirements/REQ-785',
  },
  {
    id: 'notif-6',
    type: 'done',
    level: 'success',
    title: 'REQ-788: Gate 1 审批通过',
    description: '产品经理 张三 已通过 Spec 确认',
    time: '昨天 15:30',
    read: true,
  },
];

export const mockAlerts: Alert[] = [
  {
    id: 'alert-1',
    level: 'critical',
    title: 'CI Agent 构建连续失败 3 次',
    description: 'TASK-452, TASK-453, TASK-455 无法部署',
    time: '3分钟前',
    affected: '3个任务',
    rootCause: 'npm install 依赖冲突 (package.json 中 react 版本不一致)',
    suggestion: '检查 package.json 中 react 和 react-dom 版本对齐',
    acknowledged: false,
  },
  {
    id: 'alert-2',
    level: 'warning',
    title: 'Gate 1 审批超时: REQ-789',
    description: '审批人 张三 已超过 SLA 45分钟，已发送3次催促',
    time: '15分钟前',
    affected: '1个需求',
    rootCause: '审批人未及时处理',
    suggestion: '已自动升级给产品总监 李四',
    acknowledged: false,
  },
  {
    id: 'alert-3',
    level: 'warning',
    title: '开发中需求数量超过 WIP 限制',
    description: '当前 7 个需求处于开发阶段，WIP 限制为 4',
    time: '1小时前',
    affected: 'DevAgent-1,2,3 + 4 位开发者',
    rootCause: '并发需求过多',
    suggestion: '暂缓低优先级需求开发，或增加开发资源',
    acknowledged: true,
  },
];

export const mockRelease: Release = {
  version: 'V2.3.0',
  status: 'developing',
  releaseWindow: '2026-07-10',
  totalReqs: 15,
  completedReqs: 3,
  requirements: [
    { id: 'REQ-795', title: '支付安全加固', status: '阻塞', pm: '张三' },
    { id: 'REQ-789', title: '订单批量导出功能', status: '设计评审中', pm: '张三' },
    { id: 'REQ-785', title: '地址管理优化', status: '开发中(35%)', pm: '李四' },
    { id: 'REQ-783', title: '商品搜索优化', status: '开发中(60%)', pm: '王五' },
    { id: 'REQ-780', title: '登录页重构', status: '测试中', pm: '赵六' },
    { id: 'REQ-779', title: '首页改版', status: '测试中', pm: '赵六' },
  ],
  risks: [
    { level: 'critical', reqId: 'REQ-795', description: '阻塞超过 3 天，可能影响发布窗口' },
    { level: 'warning', reqId: 'REQ-789', description: '设计评审等待超过 SLA (2h)，已超时 30min' },
  ],
};

export const mockPerformance: PerformanceMetrics = {
  cycleTime: 2.3,
  cycleTimeTrend: -15,
  throughput: 12,
  throughputTrend: 20,
  aiContribution: 68,
  aiContributionTrend: 5,
  codeQuality: 92,
  codeQualityTrend: 3,
  bugEscapeRate: 8,
  bugEscapeRateTrend: -12,
  cycleTimeHistory: [
    { week: 'W1', value: 5.2 },
    { week: 'W2', value: 4.8 },
    { week: 'W3', value: 4.5 },
    { week: 'W4', value: 4.1 },
    { week: 'W5', value: 3.8 },
    { week: 'W6', value: 3.5 },
    { week: 'W7', value: 3.2 },
    { week: 'W8', value: 2.9 },
    { week: 'W9', value: 2.7 },
    { week: 'W10', value: 2.5 },
    { week: 'W11', value: 2.4 },
    { week: 'W12', value: 2.3 },
  ],
  bottleneckDistribution: [
    { name: '设计评审等待', percentage: 35 },
    { name: '代码审核等待', percentage: 20 },
    { name: '环境部署等待', percentage: 15 },
    { name: 'Bug 修复', percentage: 12 },
    { name: '需求澄清', percentage: 8 },
    { name: '其他', percentage: 10 },
  ],
  aiVsHumanStages: [
    { name: '需求录入', ai: 45, human: 55 },
    { name: '编码开发', ai: 75, human: 25 },
    { name: '测试验证', ai: 60, human: 40 },
    { name: '代码审查', ai: 30, human: 70 },
    { name: '部署发布', ai: 90, human: 10 },
  ],
};

export const mockKnowledgeStatus = {
  projects: [
    { name: '订单系统', coverage: 98 },
    { name: '用户系统', coverage: 95 },
    { name: '支付系统', coverage: 67 },
    { name: '商品系统', coverage: 72 },
    { name: '消息系统', coverage: 85 },
  ],
  apiStats: {
    indexed: 234,
    deprecated: 12,
    undocumented: 45,
    conflicts: 3,
  },
};

export const myTasks = {
  name: '张三',
  role: '产品经理',
  myRequirements: 5,
  pendingApprovals: 2,
  overdueApprovals: 1,
  requirementChanges: 3,
  unreadMessages: 8,
  weeklyStats: {
    created: 4,
    approved: 7,
    avgApprovalTime: '1.2h',
    teamAvgApprovalTime: '2.5h',
    rejectRate: 15,
    teamRejectRate: 22,
    specCompleteness: 91,
  },
};

// ============================================================
// 测试工作台 (Testing Workbench) — Types & Mock Data
// ============================================================

export type TestCaseType = 'api' | 'ui' | 'manual';
export type TestCasePriority = 'P0' | 'P1' | 'P2' | 'P3';
export type TestCaseStatus = 'draft' | 'ready' | 'running' | 'passed' | 'failed' | 'blocked';
export type TestReadinessStatus = 'not_started' | 'in_review' | 'approved' | 'rejected';
export type UITestActionType = 'navigate' | 'click' | 'fill' | 'assert' | 'screenshot' | 'wait';

export interface TestStep {
  order: number;
  action: string;
  expectedResult: string;
  data?: Record<string, unknown>;
}

export interface TestCase {
  id: string;
  requirementId: string;
  title: string;
  description: string;
  type: TestCaseType;
  priority: TestCasePriority;
  status: TestCaseStatus;
  preconditions: string;
  steps: TestStep[];
  tags: string[];
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
  lastRunStatus?: 'passed' | 'failed';
}

export interface ApiMockConfig {
  id: string;
  requirementId: string;
  endpoint: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  requestBody: string;
  expectedResponseStatus: number;
  expectedResponseBody: string;
  mockLatencyMs: number;
}

export interface ApiTestResult {
  id: string;
  testCaseId: string;
  endpoint: string;
  method: string;
  responseStatus: number;
  responseBody: string;
  latencyMs: number;
  passed: boolean;
  assertionResults: { field: string; expected: string; actual: string; passed: boolean }[];
  executedAt: string;
}

export interface UITestStepResult {
  order: number;
  actionType: UITestActionType;
  description: string;
  playwrightCode: string;
  status: 'pending' | 'active' | 'passed' | 'failed' | 'skipped';
  screenshotB64?: string;
  errorMessage?: string;
  durationMs?: number;
  coordinates?: { x: number; y: number };
}

export interface UITestExecution {
  id: string;
  testCaseId: string;
  status: 'idle' | 'generating_script' | 'running' | 'completed' | 'failed';
  startedAt?: string;
  completedAt?: string;
  totalSteps: number;
  completedSteps: number;
  steps: UITestStepResult[];
}

export interface TestReadinessReview {
  requirementId: string;
  status: TestReadinessStatus;
  reviewedBy: string;
  reviewedAt: string;
  comment: string;
  acceptanceCriteriaMet: boolean;
  interfaceContractReady: boolean;
  prototypeReady: boolean;
}

export interface TestChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  timestamp: string;
  thinking?: string[];
  suggestions?: TestCaseSuggestion[];
}

export interface TestCaseSuggestion {
  title: string;
  type: TestCaseType;
  priority: TestCasePriority;
  steps: TestStep[];
  accepted: boolean;
  rejected: boolean;
}

// ============================================================
// Mock Data: Test Cases
// ============================================================

export const mockTestCases: TestCase[] = [
  {
    id: 'TC-001',
    requirementId: 'REQ-789',
    title: '导出接口-正常流程验证',
    description: '验证订单导出接口在正常参数下的响应',
    type: 'api',
    priority: 'P0',
    status: 'passed',
    preconditions: '订单表有有效数据',
    steps: [
      { order: 1, action: 'POST /api/orders/export 传入 {startDate:"2026-06-01", endDate:"2026-06-25", format:"xlsx"}', expectedResult: '返回 200，downloadUrl 不为空' },
      { order: 2, action: '验证返回的 Content-Type', expectedResult: 'application/json' },
      { order: 3, action: '验证 type 字段为 "sync"', expectedResult: 'response.type === "sync"' },
      { order: 4, action: '验证 downloadUrl 可访问', expectedResult: 'HTTP GET downloadUrl 返回 200' },
    ],
    tags: ['接口', '冒烟'],
    createdBy: 'AI',
    createdAt: '2026-06-25 18:00',
    updatedAt: '2026-06-25 18:30',
    lastRunAt: '2026-06-26 09:00',
    lastRunStatus: 'passed',
  },
  {
    id: 'TC-002',
    requirementId: 'REQ-789',
    title: '导出按钮-交互验证',
    description: '验证订单列表页导出按钮的展示和交互',
    type: 'ui',
    priority: 'P1',
    status: 'ready',
    preconditions: '用户已登录，具有运营角色权限',
    steps: [
      { order: 1, action: '打开订单列表页 /orders', expectedResult: '页面正常加载' },
      { order: 2, action: '检查右上角操作栏', expectedResult: '存在"批量导出"按钮，与筛选/刷新按钮同组' },
      { order: 3, action: '点击"批量导出"按钮', expectedResult: '弹出导出配置对话框' },
      { order: 4, action: '验证对话框内容', expectedResult: '包含日期范围选择器、状态多选、格式单选(Excel/CSV)' },
    ],
    tags: ['UI', '交互'],
    createdBy: '张三',
    createdAt: '2026-06-25 19:00',
    updatedAt: '2026-06-26 08:00',
  },
  {
    id: 'TC-003',
    requirementId: 'REQ-789',
    title: '导出接口-参数校验-缺失必填字段',
    description: '验证缺少必填参数时接口返回400错误',
    type: 'api',
    priority: 'P1',
    status: 'failed',
    preconditions: '无',
    steps: [
      { order: 1, action: 'POST /api/orders/export 不传 format 字段', expectedResult: 'HTTP 400 Bad Request' },
      { order: 2, action: '验证错误响应体', expectedResult: '包含 "format is required" 错误信息' },
      { order: 3, action: 'POST /api/orders/export 不传 startDate', expectedResult: 'HTTP 400 Bad Request' },
      { order: 4, action: 'POST /api/orders/export 传入无效日期格式', expectedResult: 'HTTP 400 Bad Request，提示日期格式错误' },
    ],
    tags: ['接口', '异常场景'],
    createdBy: 'AI',
    createdAt: '2026-06-25 20:00',
    updatedAt: '2026-06-26 09:30',
    lastRunAt: '2026-06-26 09:00',
    lastRunStatus: 'failed',
  },
  {
    id: 'TC-004',
    requirementId: 'REQ-789',
    title: '导出按钮-权限控制',
    description: '验证无权限用户不可见导出按钮',
    type: 'ui',
    priority: 'P1',
    status: 'draft',
    preconditions: '使用普通用户账号登录(非运营/管理员角色)',
    steps: [
      { order: 1, action: '以普通用户身份打开订单列表页', expectedResult: '页面正常加载' },
      { order: 2, action: '检查右上角操作栏', expectedResult: '不存在"批量导出"按钮' },
      { order: 3, action: '直接访问导出接口 POST /api/orders/export', expectedResult: 'HTTP 403 Forbidden' },
    ],
    tags: ['UI', '权限'],
    createdBy: '张三',
    createdAt: '2026-06-26 08:30',
    updatedAt: '2026-06-26 08:30',
  },
  {
    id: 'TC-005',
    requirementId: 'REQ-789',
    title: '大文件异步导出-超过1万条',
    description: '验证超过1万条时系统自动切换为异步导出',
    type: 'api',
    priority: 'P1',
    status: 'ready',
    preconditions: '订单表至少有10001条记录',
    steps: [
      { order: 1, action: 'POST /api/orders/export 设置日期范围覆盖全部订单', expectedResult: 'HTTP 200' },
      { order: 2, action: '验证响应 type 字段', expectedResult: 'response.type === "async"' },
      { order: 3, action: '验证 taskId 不为空', expectedResult: 'response.taskId 存在且为有效UUID' },
      { order: 4, action: '验证 estimatedTime 字段', expectedResult: 'response.estimatedTime > 0' },
      { order: 5, action: '轮询 GET /api/orders/export/{taskId}', expectedResult: 'status 从 processing → completed' },
    ],
    tags: ['接口', '异步', '边界'],
    createdBy: 'AI',
    createdAt: '2026-06-25 21:00',
    updatedAt: '2026-06-26 08:00',
  },
  {
    id: 'TC-006',
    requirementId: 'REQ-789',
    title: '导出交互-空数据状态',
    description: '验证筛选条件下无订单时的表现',
    type: 'manual',
    priority: 'P2',
    status: 'draft',
    preconditions: '选择一个无订单的日期范围',
    steps: [
      { order: 1, action: '设置日期范围为无订单的区间', expectedResult: '列表显示"暂无数据"' },
      { order: 2, action: '点击"批量导出"按钮', expectedResult: '按钮应为禁用状态，显示 tooltip"暂无可导出订单"' },
    ],
    tags: ['边界', '空状态'],
    createdBy: '张三',
    createdAt: '2026-06-26 08:00',
    updatedAt: '2026-06-26 08:00',
  },
  {
    id: 'TC-007',
    requirementId: 'REQ-780',
    title: '登录页-社交登录按钮验证',
    description: '验证微信/支付宝登录按钮展示和跳转',
    type: 'ui',
    priority: 'P1',
    status: 'running',
    preconditions: '未登录状态',
    steps: [
      { order: 1, action: '打开登录页 /login', expectedResult: '页面展示登录表单' },
      { order: 2, action: '检查社交登录区域', expectedResult: '存在微信和支付宝登录按钮' },
      { order: 3, action: '点击微信登录', expectedResult: '跳转至微信授权页面' },
      { order: 4, action: '验证授权回调', expectedResult: '成功登录并跳转至首页' },
    ],
    tags: ['UI', '登录'],
    createdBy: 'AI',
    createdAt: '2026-06-24 16:00',
    updatedAt: '2026-06-25 10:00',
    lastRunAt: '2026-06-26 08:30',
    lastRunStatus: 'passed',
  },
  {
    id: 'TC-008',
    requirementId: 'REQ-780',
    title: '登录接口-密码加密传输',
    description: '验证登录接口密码以加密形式传输',
    type: 'api',
    priority: 'P0',
    status: 'passed',
    preconditions: '存在测试账号 test@example.com / Test1234!',
    steps: [
      { order: 1, action: 'POST /api/auth/login {email, password}', expectedResult: 'HTTP 200, 返回 JWT token' },
      { order: 2, action: '检查请求体中 password 字段', expectedResult: '密码已通过 RSA 公钥加密，非明文传输' },
      { order: 3, action: '使用错误密码登录', expectedResult: 'HTTP 401, 连续5次后账号锁定15分钟' },
    ],
    tags: ['接口', '安全'],
    createdBy: 'AI',
    createdAt: '2026-06-24 15:00',
    updatedAt: '2026-06-25 09:00',
    lastRunAt: '2026-06-26 09:00',
    lastRunStatus: 'passed',
  },
  {
    id: 'TC-009',
    requirementId: 'REQ-785',
    title: '地址管理-省市区级联选择',
    description: '验证新增地址时省市区级联选择功能',
    type: 'ui',
    priority: 'P1',
    status: 'ready',
    preconditions: '用户已登录',
    steps: [
      { order: 1, action: '进入地址管理页面，点击"新增地址"', expectedResult: '弹出地址表单' },
      { order: 2, action: '选择省份"广东省"', expectedResult: '城市下拉框加载广东的城市列表' },
      { order: 3, action: '选择城市"深圳市"', expectedResult: '区县下拉框加载深圳的区县列表' },
      { order: 4, action: '选择区县"南山区"', expectedResult: '邮政编码自动填充为 518051' },
    ],
    tags: ['UI', '表单'],
    createdBy: '李四',
    createdAt: '2026-06-25 10:00',
    updatedAt: '2026-06-25 14:00',
  },
  {
    id: 'TC-010',
    requirementId: 'REQ-785',
    title: '地址接口-区域数据查询',
    description: '验证区域数据接口返回正确的级联数据',
    type: 'api',
    priority: 'P2',
    status: 'draft',
    preconditions: '无',
    steps: [
      { order: 1, action: 'GET /api/regions', expectedResult: '返回所有省份列表' },
      { order: 2, action: 'GET /api/regions?parent=440000', expectedResult: '返回广东省下所有城市' },
      { order: 3, action: 'GET /api/regions/440305/postcode', expectedResult: '返回南山区邮政编码 518051' },
    ],
    tags: ['接口'],
    createdBy: 'AI',
    createdAt: '2026-06-25 11:00',
    updatedAt: '2026-06-25 11:00',
  },
];

// ============================================================
// Mock Data: API Mock Configs
// ============================================================

export const mockApiMockConfigs: ApiMockConfig[] = [
  {
    id: 'mock-api-1',
    requirementId: 'REQ-789',
    endpoint: 'POST /api/orders/export',
    method: 'POST',
    requestBody: JSON.stringify({ startDate: '2026-06-01', endDate: '2026-06-25', format: 'xlsx', status: ['paid', 'shipped'] }, null, 2),
    expectedResponseStatus: 200,
    expectedResponseBody: JSON.stringify({ type: 'sync', downloadUrl: 'https://cdn.example.com/exports/order_20260625.xlsx', totalCount: 2345 }, null, 2),
    mockLatencyMs: 234,
  },
  {
    id: 'mock-api-2',
    requirementId: 'REQ-789',
    endpoint: 'POST /api/orders/export (async)',
    method: 'POST',
    requestBody: JSON.stringify({ startDate: '2026-01-01', endDate: '2026-06-25', format: 'csv' }, null, 2),
    expectedResponseStatus: 200,
    expectedResponseBody: JSON.stringify({ type: 'async', taskId: 'exp_abc123', estimatedTime: 45 }, null, 2),
    mockLatencyMs: 312,
  },
  {
    id: 'mock-api-3',
    requirementId: 'REQ-785',
    endpoint: 'GET /api/regions?parent=440000',
    method: 'GET',
    requestBody: '',
    expectedResponseStatus: 200,
    expectedResponseBody: JSON.stringify([{ code: '440300', name: '深圳市' }, { code: '440100', name: '广州市' }, { code: '440400', name: '珠海市' }], null, 2),
    mockLatencyMs: 156,
  },
  {
    id: 'mock-api-4',
    requirementId: 'REQ-785',
    endpoint: 'PUT /api/address/:id',
    method: 'PUT',
    requestBody: JSON.stringify({ province: '广东省', city: '深圳市', district: '南山区', detail: '科技园路1号', postcode: '518051' }, null, 2),
    expectedResponseStatus: 200,
    expectedResponseBody: JSON.stringify({ success: true, addressId: 'addr_789' }, null, 2),
    mockLatencyMs: 198,
  },
];

// ============================================================
// Mock Data: API Test Results (History)
// ============================================================

export const mockApiTestResults: ApiTestResult[] = [
  {
    id: 'api-result-1',
    testCaseId: 'TC-001',
    endpoint: 'POST /api/orders/export',
    method: 'POST',
    responseStatus: 200,
    responseBody: JSON.stringify({ type: 'sync', downloadUrl: 'https://cdn.example.com/exports/order_20260625.xlsx', totalCount: 2345 }),
    latencyMs: 234,
    passed: true,
    assertionResults: [
      { field: 'status', expected: '200', actual: '200', passed: true },
      { field: 'body.type', expected: 'sync', actual: 'sync', passed: true },
      { field: 'body.downloadUrl', expected: 'not null', actual: 'https://cdn...', passed: true },
    ],
    executedAt: '2026-06-26 09:00',
  },
  {
    id: 'api-result-2',
    testCaseId: 'TC-003',
    endpoint: 'POST /api/orders/export',
    method: 'POST',
    responseStatus: 500,
    responseBody: JSON.stringify({ error: 'Internal Server Error', message: 'Unexpected token in JSON at position 0' }),
    latencyMs: 89,
    passed: false,
    assertionResults: [
      { field: 'status', expected: '400', actual: '500', passed: false },
      { field: 'body.error', expected: 'format is required', actual: 'Internal Server Error', passed: false },
    ],
    executedAt: '2026-06-26 09:00',
  },
  {
    id: 'api-result-3',
    testCaseId: 'TC-008',
    endpoint: 'POST /api/auth/login',
    method: 'POST',
    responseStatus: 200,
    responseBody: JSON.stringify({ token: 'eyJhbGciOiJSUzI1NiIs...', expiresIn: 7200, user: { id: 'u_001', role: 'operator' } }),
    latencyMs: 312,
    passed: true,
    assertionResults: [
      { field: 'status', expected: '200', actual: '200', passed: true },
      { field: 'body.token', expected: 'not null', actual: 'eyJhbG...', passed: true },
      { field: 'body.expiresIn', expected: '7200', actual: '7200', passed: true },
    ],
    executedAt: '2026-06-26 09:00',
  },
  {
    id: 'api-result-4',
    testCaseId: 'TC-005',
    endpoint: 'POST /api/orders/export',
    method: 'POST',
    responseStatus: 200,
    responseBody: JSON.stringify({ type: 'async', taskId: 'exp_abc123', estimatedTime: 45 }),
    latencyMs: 312,
    passed: true,
    assertionResults: [
      { field: 'status', expected: '200', actual: '200', passed: true },
      { field: 'body.type', expected: 'async', actual: 'async', passed: true },
      { field: 'body.taskId', expected: 'not null', actual: 'exp_abc123', passed: true },
      { field: 'body.estimatedTime', expected: '> 0', actual: '45', passed: true },
    ],
    executedAt: '2026-06-26 08:30',
  },
  {
    id: 'api-result-5',
    testCaseId: 'TC-010',
    endpoint: 'GET /api/regions',
    method: 'GET',
    responseStatus: 200,
    responseBody: JSON.stringify([{ code: '110000', name: '北京市' }, { code: '440000', name: '广东省' }, { code: '310000', name: '上海市' }]),
    latencyMs: 156,
    passed: true,
    assertionResults: [
      { field: 'status', expected: '200', actual: '200', passed: true },
      { field: 'body.length', expected: '> 0', actual: '3', passed: true },
    ],
    executedAt: '2026-06-25 17:00',
  },
];

// ============================================================
// Mock Data: UI Test Executions
// ============================================================

// Generate a simple SVG screenshot placeholder in data URI format
// Uses manual base64 encoding to avoid btoa issues with non-Latin characters in SSR
function toBase64(str: string): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const bytes = new TextEncoder().encode(str);
  let result = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b1 = bytes[i];
    const b2 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b3 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    result += chars[b1 >> 2];
    result += chars[((b1 & 3) << 4) | (b2 >> 4)];
    result += i + 1 < bytes.length ? chars[((b2 & 15) << 2) | (b3 >> 6)] : '=';
    result += i + 2 < bytes.length ? chars[b3 & 63] : '=';
  }
  return result;
}

function mockScreenshotB64(action: string, step: number): string {
  const lines = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">',
    '<rect width="800" height="500" fill="#f8fafc"/>',
    '<rect x="0" y="0" width="800" height="36" fill="#e2e8f0"/>',
    '<circle cx="10" cy="18" r="4" fill="#ef4444"/>',
    '<circle cx="24" cy="18" r="4" fill="#f59e0b"/>',
    '<circle cx="38" cy="18" r="4" fill="#10b981"/>',
    '<rect x="60" y="8" width="200" height="20" rx="4" fill="#cbd5e1"/>',
    '<rect x="40" y="60" width="720" height="60" rx="8" fill="white" stroke="#e2e8f0"/>',
    '<text x="60" y="95" font-size="14" fill="#64748b" font-family="monospace">ORD-20260625-001 | Paid | $1,299</text>',
    '<rect x="40" y="140" width="720" height="280" rx="8" fill="white" stroke="#e2e8f0"/>',
    '<text x="60" y="170" font-size="13" fill="#334155" font-family="sans-serif">Order Items</text>',
    '<line x1="40" y1="185" x2="760" y2="185" stroke="#e2e8f0"/>',
    '<text x="60" y="215" font-size="12" fill="#64748b" font-family="sans-serif">iPhone 16  x1  $6,999</text>',
    '<text x="60" y="240" font-size="12" fill="#64748b" font-family="sans-serif">AirPods Pro  x1  $1,299</text>',
    '<rect x="620" y="340" width="120" height="36" rx="8" fill="#2563eb"/>',
    '<text x="680" y="363" font-size="12" fill="white" text-anchor="middle" font-family="sans-serif">Export</text>',
    `<text x="680" y="410" font-size="11" fill="#2563eb" text-anchor="middle" font-family="sans-serif">Step ${step}: ${action}</text>`,
    '</svg>',
  ];
  return 'data:image/svg+xml;base64,' + toBase64(lines.join(''));
}

export const mockUITestExecutions: UITestExecution[] = [
  {
    id: 'ui-exec-1',
    testCaseId: 'TC-002',
    status: 'completed',
    startedAt: '2026-06-26 09:15',
    completedAt: '2026-06-26 09:16',
    totalSteps: 4,
    completedSteps: 4,
    steps: [
      {
        order: 1,
        actionType: 'navigate',
        description: '打开订单列表页 /orders',
        playwrightCode: "await page.goto('https://app.example.com/orders');\nawait page.waitForLoadState('networkidle');",
        status: 'passed',
        screenshotB64: mockScreenshotB64('打开页面', 1),
        durationMs: 1230,
      },
      {
        order: 2,
        actionType: 'assert',
        description: '验证右上角存在"批量导出"按钮',
        playwrightCode: "const exportBtn = page.locator('button:has-text(\"批量导出\")');\nawait expect(exportBtn).toBeVisible();",
        status: 'passed',
        screenshotB64: mockScreenshotB64('检查导出按钮', 2),
        durationMs: 450,
        coordinates: { x: 680, y: 358 },
      },
      {
        order: 3,
        actionType: 'click',
        description: '点击"批量导出"按钮',
        playwrightCode: "await page.click('button:has-text(\"批量导出\")');\nawait page.waitForSelector('.export-dialog');",
        status: 'passed',
        screenshotB64: mockScreenshotB64('点击导出', 3),
        durationMs: 820,
        coordinates: { x: 680, y: 358 },
      },
      {
        order: 4,
        actionType: 'assert',
        description: '验证弹出导出配置对话框',
        playwrightCode: "const dialog = page.locator('.export-dialog');\nawait expect(dialog).toBeVisible();\nawait expect(dialog.locator('.date-range-picker')).toBeVisible();\nawait expect(dialog.locator('.format-select')).toBeVisible();",
        status: 'passed',
        screenshotB64: mockScreenshotB64('验证对话框', 4),
        durationMs: 380,
      },
    ],
  },
  {
    id: 'ui-exec-2',
    testCaseId: 'TC-007',
    status: 'completed',
    startedAt: '2026-06-26 09:00',
    completedAt: '2026-06-26 09:01',
    totalSteps: 4,
    completedSteps: 4,
    steps: [
      {
        order: 1,
        actionType: 'navigate',
        description: '打开登录页 /login',
        playwrightCode: "await page.goto('https://app.example.com/login');",
        status: 'passed',
        screenshotB64: mockScreenshotB64('打开登录页', 1),
        durationMs: 980,
      },
      {
        order: 2,
        actionType: 'fill',
        description: '输入邮箱和密码',
        playwrightCode: "await page.fill('input[name=\"email\"]', 'test@example.com');\nawait page.fill('input[name=\"password\"]', 'Test1234!');",
        status: 'passed',
        screenshotB64: mockScreenshotB64('输入账号', 2),
        durationMs: 650,
        coordinates: { x: 400, y: 220 },
      },
      {
        order: 3,
        actionType: 'click',
        description: '点击"登录"按钮',
        playwrightCode: "await page.click('button:has-text(\"登录\")');\nawait page.waitForURL('**/dashboard');",
        status: 'passed',
        screenshotB64: mockScreenshotB64('点击登录', 3),
        durationMs: 1500,
        coordinates: { x: 400, y: 310 },
      },
      {
        order: 4,
        actionType: 'assert',
        description: '验证跳转至首页并显示用户名',
        playwrightCode: "await expect(page).toHaveURL(/dashboard/);\nawait expect(page.locator('.user-name')).toContainText('测试用户');",
        status: 'failed',
        screenshotB64: mockScreenshotB64('验证失败', 4),
        durationMs: 320,
        errorMessage: 'Expected .user-name to contain "测试用户" but got "加载中..." (页面渲染延迟)',
      },
    ],
  },
];

// ============================================================
// Mock Data: Test Readiness Reviews
// ============================================================

export const mockTestReadinessReviews: TestReadinessReview[] = [
  {
    requirementId: 'REQ-789',
    status: 'in_review',
    reviewedBy: '',
    reviewedAt: '',
    comment: '',
    acceptanceCriteriaMet: true,
    interfaceContractReady: true,
    prototypeReady: true,
  },
  {
    requirementId: 'REQ-780',
    status: 'approved',
    reviewedBy: '测试小陈',
    reviewedAt: '2026-06-25 14:30',
    comment: '验收标准清晰，接口文档完整，可以开始测试',
    acceptanceCriteriaMet: true,
    interfaceContractReady: true,
    prototypeReady: true,
  },
  {
    requirementId: 'REQ-785',
    status: 'rejected',
    reviewedBy: '李四',
    reviewedAt: '2026-06-25 16:00',
    comment: '接口契约中缺少错误响应格式说明，需要补充后再提交测试',
    acceptanceCriteriaMet: true,
    interfaceContractReady: false,
    prototypeReady: true,
  },
];

// ============================================================
// Mock Data: Test Chat Messages (AI Generation)
// ============================================================

export const mockTestChatMessages: TestChatMessage[] = [
  {
    id: 'tmsg-1',
    role: 'system',
    content: '已加载需求 REQ-789 "订单批量导出功能" 的上下文。\n验收标准: 7条 | 接口契约: 3个端点 | 边界条件: 5个场景',
    timestamp: '09:00',
  },
  {
    id: 'tmsg-2',
    role: 'agent',
    content: '我已分析了需求 REQ-789 的 Spec 和验收标准。发现以下测试覆盖缺口：\n\n1. **接口测试**: 导出接口缺乏参数校验测试\n2. **UI测试**: 导出按钮的权限控制未覆盖\n3. **边界测试**: 大文件异步导出场景未覆盖\n\n需要我帮你生成这些测试用例吗？',
    timestamp: '09:01',
    thinking: [
      '读取 Spec 4个章节',
      '分析7条验收标准的可测试性',
      '交叉比对现有测试用例(6条)',
      '识别3个覆盖缺口',
    ],
  },
  {
    id: 'tmsg-3',
    role: 'user',
    content: '好的，帮我生成这 3 方面的高优先级测试用例',
    timestamp: '09:03',
  },
  {
    id: 'tmsg-4',
    role: 'agent',
    content: '我已生成了 3 条测试用例建议，覆盖了接口参数校验、UI权限控制、大文件异步导出场景。请逐条审核：',
    timestamp: '09:04',
    thinking: [
      '针对缺口1: 生成参数校验测试（正常+异常+边界）',
      '针对缺口2: 生成权限控制UI测试',
      '针对缺口3: 生成大文件异步导出测试',
      '每个用例包含: 标题、类型、优先级、前置条件、测试步骤',
    ],
    suggestions: [
      {
        title: '导出接口-参数校验-缺失必填字段',
        type: 'api',
        priority: 'P1',
        steps: [
          { order: 1, action: 'POST /api/orders/export 不传 format 字段', expectedResult: 'HTTP 400 Bad Request' },
          { order: 2, action: 'POST /api/orders/export 不传 startDate', expectedResult: 'HTTP 400 Bad Request' },
          { order: 3, action: 'POST /api/orders/export 传入无效日期格式', expectedResult: 'HTTP 400, 提示日期格式错误' },
        ],
        accepted: true,
        rejected: false,
      },
      {
        title: '导出按钮-权限控制验证',
        type: 'ui',
        priority: 'P1',
        steps: [
          { order: 1, action: '以普通用户身份打开订单列表页', expectedResult: '导出按钮不可见' },
          { order: 2, action: '直接调用接口 POST /api/orders/export', expectedResult: 'HTTP 403 Forbidden' },
        ],
        accepted: true,
        rejected: false,
      },
      {
        title: '大文件异步导出-超过1万条记录',
        type: 'api',
        priority: 'P1',
        steps: [
          { order: 1, action: 'POST /api/orders/export 日期范围覆盖>10000条', expectedResult: 'HTTP 200, type: "async"' },
          { order: 2, action: '轮询 GET /api/orders/export/{taskId}', expectedResult: 'status → completed, downloadUrl 可用' },
        ],
        accepted: true,
        rejected: false,
      },
    ],
  },
  {
    id: 'tmsg-5',
    role: 'system',
    content: '✅ 3条测试用例已添加到用例列表中 (TC-003, TC-004, TC-005)',
    timestamp: '09:05',
  },
];

// ============================================================
// Mock Code Diffs
// ============================================================

export const mockCodeDiffs: CodeDiff[] = [
  {
    id: 'diff-1',
    agentId: 'agent-3',
    file: 'src/pages/OrderDetail.tsx',
    language: 'tsx',
    addedLines: 45,
    removedLines: 12,
    hunks: [
      {
        header: '@@ -12,7 +12,15 @@ import { OrderStatus } from \'./types\';',
        lines: [
          { type: 'context', oldLineNumber: 12, newLineNumber: 12, content: "import { OrderStatus } from './types';" },
          { type: 'context', oldLineNumber: 13, newLineNumber: 13, content: "import { useRouter } from 'next/navigation';" },
          { type: 'context', oldLineNumber: 14, newLineNumber: 14, content: "import { formatCurrency, formatDate } from '@/utils';" },
          { type: 'add', newLineNumber: 15, content: "import { exportOrders } from '@/api/order';" },
          { type: 'add', newLineNumber: 16, content: "import { ExportDialog } from '@/components/ExportDialog';" },
          { type: 'add', newLineNumber: 17, content: "import type { ExportFormat, ExportOptions } from '@/types/export';" },
          { type: 'context', oldLineNumber: 15, newLineNumber: 18, content: '' },
          { type: 'context', oldLineNumber: 16, newLineNumber: 19, content: 'export default function OrderDetailPage() {' },
          { type: 'context', oldLineNumber: 17, newLineNumber: 20, content: '  const router = useRouter();' },
        ],
      },
      {
        header: '@@ -35,6 +43,25 @@ export default function OrderDetailPage() {',
        lines: [
          { type: 'context', oldLineNumber: 35, newLineNumber: 43, content: '  const [order, setOrder] = useState<Order | null>(null);' },
          { type: 'context', oldLineNumber: 36, newLineNumber: 44, content: '  const [loading, setLoading] = useState(true);' },
          { type: 'add', newLineNumber: 45, content: '  const [showExportDialog, setShowExportDialog] = useState(false);' },
          { type: 'add', newLineNumber: 46, content: '  const [exporting, setExporting] = useState(false);' },
          { type: 'add', newLineNumber: 47, content: '' },
          { type: 'add', newLineNumber: 48, content: '  const handleExport = async (options: ExportOptions) => {' },
          { type: 'add', newLineNumber: 49, content: '    setExporting(true);' },
          { type: 'add', newLineNumber: 50, content: '    try {' },
          { type: 'add', newLineNumber: 51, content: '      const result = await exportOrders({' },
          { type: 'add', newLineNumber: 52, content: '        orderId: order!.id,' },
          { type: 'add', newLineNumber: 53, content: '        ...options,' },
          { type: 'add', newLineNumber: 54, content: '      });' },
          { type: 'add', newLineNumber: 55, content: '      downloadBlob(result, `order_${order!.id}.${options.format}`);' },
          { type: 'add', newLineNumber: 56, content: '    } catch (err) {' },
          { type: 'add', newLineNumber: 57, content: '      console.error(\'Export failed:\', err);' },
          { type: 'add', newLineNumber: 58, content: '      toast.error(\'导出失败，请重试\');' },
          { type: 'add', newLineNumber: 59, content: '    } finally {' },
          { type: 'add', newLineNumber: 60, content: '      setExporting(false);' },
          { type: 'add', newLineNumber: 61, content: '    }' },
          { type: 'add', newLineNumber: 62, content: '  };' },
          { type: 'context', oldLineNumber: 37, newLineNumber: 63, content: '' },
          { type: 'context', oldLineNumber: 38, newLineNumber: 64, content: '  useEffect(() => {' },
          { type: 'remove', oldLineNumber: 39, content: '    fetchOrder(id).then(setOrder).finally(() => setLoading(false));' },
          { type: 'remove', oldLineNumber: 40, content: '  }, [id]);' },
          { type: 'add', newLineNumber: 65, content: '    fetchOrder(id)' },
          { type: 'add', newLineNumber: 66, content: '      .then((data) => setOrder(data))' },
          { type: 'add', newLineNumber: 67, content: '      .catch(() => toast.error(\'加载订单失败\'))' },
          { type: 'add', newLineNumber: 68, content: '      .finally(() => setLoading(false));' },
          { type: 'add', newLineNumber: 69, content: '  }, [id]);' },
          { type: 'context', oldLineNumber: 41, newLineNumber: 70, content: '' },
          { type: 'context', oldLineNumber: 42, newLineNumber: 71, content: '  if (loading) return <LoadingSkeleton />;' },
        ],
      },
      {
        header: '@@ -55,6 +89,14 @@ export default function OrderDetailPage() {',
        lines: [
          { type: 'context', oldLineNumber: 55, newLineNumber: 89, content: '          <OrderTimeline order={order} />' },
          { type: 'context', oldLineNumber: 56, newLineNumber: 90, content: '          <OrderActions order={order} />' },
          { type: 'remove', oldLineNumber: 57, content: '        </div>' },
          { type: 'add', newLineNumber: 91, content: '' },
          { type: 'add', newLineNumber: 92, content: '          <div className="flex items-center gap-2 mt-4 pt-4 border-t border-slate-100">' },
          { type: 'add', newLineNumber: 93, content: '            <button' },
          { type: 'add', newLineNumber: 94, content: '              onClick={() => setShowExportDialog(true)}' },
          { type: 'add', newLineNumber: 95, content: '              className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 transition-colors"' },
          { type: 'add', newLineNumber: 96, content: '            >' },
          { type: 'add', newLineNumber: 97, content: '              <DownloadIcon className="w-4 h-4" />' },
          { type: 'add', newLineNumber: 98, content: '              批量导出' },
          { type: 'add', newLineNumber: 99, content: '            </button>' },
          { type: 'add', newLineNumber: 100, content: '          </div>' },
          { type: 'add', newLineNumber: 101, content: '        </div>' },
        ],
      },
    ],
  },
  {
    id: 'diff-2',
    agentId: 'agent-1',
    file: 'src/components/AddressCascader.tsx',
    language: 'tsx',
    addedLines: 67,
    removedLines: 5,
    hunks: [
      {
        header: '@@ -1,0 +1,35 @@',
        lines: [
          { type: 'add', newLineNumber: 1, content: "'use client';" },
          { type: 'add', newLineNumber: 2, content: '' },
          { type: 'add', newLineNumber: 3, content: "import { useState, useEffect, useCallback } from 'react';" },
          { type: 'add', newLineNumber: 4, content: "import { fetchRegionData, RegionNode } from '@/api/address';" },
          { type: 'add', newLineNumber: 5, content: "import { ChevronDownIcon } from '@/components/icons';" },
          { type: 'add', newLineNumber: 6, content: '' },
          { type: 'add', newLineNumber: 7, content: 'interface AddressCascaderProps {' },
          { type: 'add', newLineNumber: 8, content: '  value?: { province: string; city: string; district: string };"' },
          { type: 'add', newLineNumber: 9, content: '  onChange?: (value: { province: string; city: string; district: string; postcode: string }) => void;' },
          { type: 'add', newLineNumber: 10, content: '  className?: string;' },
          { type: 'add', newLineNumber: 11, content: '}' },
          { type: 'add', newLineNumber: 12, content: '' },
          { type: 'add', newLineNumber: 13, content: 'export default function AddressCascader({ value, onChange, className }: AddressCascaderProps) {' },
          { type: 'add', newLineNumber: 14, content: '  const [provinces, setProvinces] = useState<RegionNode[]>([]);' },
          { type: 'add', newLineNumber: 15, content: '  const [cities, setCities] = useState<RegionNode[]>([]);' },
          { type: 'add', newLineNumber: 16, content: '  const [districts, setDistricts] = useState<RegionNode[]>([]);' },
          { type: 'add', newLineNumber: 17, content: '  const [selectedProvince, setSelectedProvince] = useState(value?.province || \'\');' },
          { type: 'add', newLineNumber: 18, content: '  const [selectedCity, setSelectedCity] = useState(value?.city || \'\');' },
          { type: 'add', newLineNumber: 19, content: '  const [selectedDistrict, setSelectedDistrict] = useState(value?.district || \'\');' },
          { type: 'add', newLineNumber: 20, content: '  const [postcode, setPostcode] = useState(\'\');' },
          { type: 'add', newLineNumber: 21, content: '' },
          { type: 'add', newLineNumber: 22, content: '  // Fetch provinces on mount' },
          { type: 'add', newLineNumber: 23, content: '  useEffect(() => {' },
          { type: 'add', newLineNumber: 24, content: '    fetchRegionData().then((data) => setProvinces(data));' },
          { type: 'add', newLineNumber: 25, content: '  }, []);' },
        ],
      },
    ],
  },
  {
    id: 'diff-3',
    agentId: 'agent-1',
    file: 'src/api/address.ts',
    language: 'ts',
    addedLines: 23,
    removedLines: 0,
    hunks: [
      {
        header: '@@ -5,6 +5,29 @@ export async function getAddressList(userId: string): Promise<Address[]> {',
        lines: [
          { type: 'context', oldLineNumber: 5, newLineNumber: 5, content: 'export async function getAddressList(userId: string): Promise<Address[]> {' },
          { type: 'context', oldLineNumber: 6, newLineNumber: 6, content: "  return api.get(`/users/${userId}/addresses`);" },
          { type: 'context', oldLineNumber: 7, newLineNumber: 7, content: '}' },
          { type: 'add', newLineNumber: 8, content: '' },
          { type: 'add', newLineNumber: 9, content: 'export interface RegionNode {' },
          { type: 'add', newLineNumber: 10, content: '  code: string;' },
          { type: 'add', newLineNumber: 11, content: '  name: string;' },
          { type: 'add', newLineNumber: 12, content: '  postcode?: string;' },
          { type: 'add', newLineNumber: 13, content: '  children?: RegionNode[];' },
          { type: 'add', newLineNumber: 14, content: '}' },
          { type: 'add', newLineNumber: 15, content: '' },
          { type: 'add', newLineNumber: 16, content: '/**' },
          { type: 'add', newLineNumber: 17, content: ' * 获取省市区级联数据' },
          { type: 'add', newLineNumber: 18, content: ' * 自动填充邮政编码' },
          { type: 'add', newLineNumber: 19, content: ' */' },
          { type: 'add', newLineNumber: 20, content: 'export async function fetchRegionData(parentCode?: string): Promise<RegionNode[]> {' },
          { type: 'add', newLineNumber: 21, content: "  const params = parentCode ? { parent: parentCode } : {};" },
          { type: 'add', newLineNumber: 22, content: "  return api.get('/regions', params);" },
          { type: 'add', newLineNumber: 23, content: '}' },
          { type: 'add', newLineNumber: 24, content: '' },
          { type: 'add', newLineNumber: 25, content: '/**' },
          { type: 'add', newLineNumber: 26, content: ' * 根据区县 code 查询邮政编码' },
          { type: 'add', newLineNumber: 27, content: ' */' },
          { type: 'add', newLineNumber: 28, content: "export async function getPostcode(districtCode: string): Promise<string> {" },
          { type: 'add', newLineNumber: 29, content: "  return api.get(`/regions/${districtCode}/postcode`);" },
          { type: 'add', newLineNumber: 30, content: '}' },
        ],
      },
    ],
  },
];
