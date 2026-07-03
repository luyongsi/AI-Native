// ============================================================
// Shared TypeScript interfaces matching backend API responses
// Aligned with mock/index.ts types for seamless migration
// ============================================================

// API response wrappers
export interface ApiListResponse<T> {
  items: T[];
  total: number;
  limit?: number;
  offset?: number;
}

// --- Requirement ---
export interface RequirementStage {
  name: string;
  status: 'done' | 'in_progress' | 'waiting' | 'pending';
  duration: string;
  baseline: string;
  assignee: string;
}

export interface SpecSection {
  id: string;
  title: string;
  status: 'pending' | 'generating' | 'done' | 'editing' | 'conflict';
  content: string;
  history: { time: string; action: string }[];
}

export interface Requirement {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  version: string;
  pm: string;
  assignees: string[];
  aiCompletion: number;
  humanInterventions: number;
  createdAt: string;
  created_at?: string;   // snake_case from API
  updated_at?: string;
  blocked: boolean;
  blockReason?: string;
  slaDeadline?: string;
  stages: RequirementStage[];
  specSections?: SpecSection[];
  relatedIds: string[];
  sourceType?: string;
  source_type?: string;
  spec?: any;
  tasks?: any[];
}

// --- Agent ---
export interface AgentActivity {
  time: string;
  type: string;
  content: string;
  detail?: string;
  success?: boolean;
  diffId?: string;
}

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

// --- Approval ---
export interface ApprovalItem {
  id: string;
  gate: string;
  requirementId: string;
  requirementTitle: string;
  submitter: string;
  priority: string;
  createdAt: string;
  slaDeadline: string;
  status: string;
  agentReviews: { agent: string; verdict: string; comment: string }[];
  reviewSummary?: string;
}

// --- Notification ---
export interface Notification {
  id: string;
  type: string;
  level: 'critical' | 'warning' | 'info' | 'success';
  title: string;
  description: string;
  time: string;
  read: boolean;
  link?: string;
}

// --- Alert ---
export interface Alert {
  id: string;
  level: 'critical' | 'warning';
  title: string;
  description: string;
  source?: string;
  affected: string;
  rootCause: string;
  aiSuggestion?: string;
  acknowledged: boolean;
  time: string;
}

// --- Dashboard ---
export interface DashboardStats {
  pool: number;
  designing: number;
  developing: number;
  testing: number;
  releasing: number;
  total: number;
}

// --- Insights ---
export interface InsightsData {
  cycle_time_days: number;
  throughput: number;
  ai_contribution_pct: number;
  code_quality_score: number;
  bug_escape_rate_pct: number;
  bottleneck_distribution: { name: string; percentage: number }[];
  total_requirements: number;
  active_agents: number;
  avg_loop_rounds: number;
  ai_vs_human: { name: string; ai: number; human: number }[];
  trends: any;
  source: string;
}

// --- Topology ---
export interface TopologyNode {
  id: string;
  label: string;
  type: string;
  status: string;
  agentType?: string;
  taskName?: string;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  label?: string;
}

// --- Release ---
export interface Release {
  id?: string;
  version: string;
  status: string;
  releaseWindow: string;
  totalReqs: number;
  completedReqs: number;
  progress?: number;
  requirements?: { id: string; title: string; status: string; pm: string }[];
  risks?: { level: string; reqId: string; description: string }[];
  stages?: any[];
}

// --- Test Case ---
export interface TestCase {
  id: string;
  req_id?: string;
  requirementId?: string;
  title: string;
  description?: string;
  steps?: any[];
  preconditions?: string;
  priority: string;
  status: string;
  tags?: string[];
  ai_generated?: boolean;
  last_run_at?: string;
  created_at?: string;
  updated_at?: string;
  createdBy?: string;
  createdAt?: string;
  updatedAt?: string;
  lastRunAt?: string;
  lastRunStatus?: string;
  type?: string;
}

// --- Knowledge ---
export interface KnowledgeStatus {
  projects: { name: string; coverage: number }[];
  apiStats: { indexed: number; deprecated: number; undocumented: number; conflicts: number };
  todos?: any[];
}

// --- Chat ---
export interface ChatMessage {
  role: string;
  content: string;
  time: string;
  type?: string;
}

export interface ChatResponse {
  reply: string;
  options?: string[];
  spec_updates?: any[];
}
