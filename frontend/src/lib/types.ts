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
  stage?: string;
  type?: string;
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

// Gate0 approval 鈥?aligned with new approvals table (migration 008)
export interface Gate0Approval {
  id: string;
  req_id: string;
  req_title?: string;
  session_id: string | null;
  gate_level: number;
  cycle: number;
  status: 'pending' | 'decided';
  decision?: 'pass' | 'reject';
  reject_reasons?: RejectReason[];
  revision_guidance?: string;
  a3_rework?: boolean;
  a6_rework?: boolean;
  a7_rework?: boolean;
  reviewer_user_id?: string;
  reviewer_name?: string;
  reviewed_at?: string;
  created_at?: string;
  gate_meta?: { label: string; icon: string; description: string };
  // Gate2 specific context
  gate2_context?: Gate2Context;
}

export interface RejectReason {
  category: string;
  description: string;
}

export interface ApprovalContext {
  req_id: string;
  session_id: string | null;
  cycle: number;
  gate_level: number;
  a1_output: {
    requirement_draft: RequirementDraft | null;
    wireframe_url: string | null;
    confidence_score: number | null;
  };
  a2_output: {
    feasibility_assessment: FeasibilityAssessment | null;
    confirmation_checklist: ConfirmationChecklistItem[];
    conflicts: ConflictItem[];
    quality_score: number | null;
    a2_missing: boolean;
  };
  gate_meta?: { label: string; icon: string; description: string };
}

export interface FeasibilityAssessment {
  technical: { feasible: boolean; assessment: string; concerns: string[] };
  business: { feasible: boolean; assessment: string; concerns: string[] };
  risk_level: 'low' | 'medium' | 'high';
  risk_rationale: string;
}

export interface ConfirmationChecklistItem {
  id: string;
  category: 'requirement_clarity' | 'technical_risk' | 'dependency';
  item: string;
  priority: 'high' | 'medium' | 'low';
  related_req_field?: string;
}

export interface ConflictItem {
  id: string;
  related_system: string;
  type: 'field_naming' | 'business_flow' | 'data_model' | 'service_boundary';
  description: string;
  severity: 'high' | 'medium' | 'low';
}

export interface DecideRequest {
  decision: 'pass' | 'reject';
  reject_reasons?: RejectReason[];
  revision_guidance?: string;
  a3_rework?: boolean;
  a6_rework?: boolean;
  a7_rework?: boolean;
}

// Gate2 specific context — matches GET /api/gate2/{req_id}/context response
export interface Gate2Context {
  req_id: string;
  cycle: number;
  requirement_info: {
    title: string;
    phase?: string;
    tech_prep_status?: string;
    tech_prep_revision_count?: number;
  };
  a6_output: {
    dag: any;
    dag_detail?: {
      task_dags_id?: number;
      version: number;
      dag_json: any;
      node_count?: number;
      critical_path_length?: number;
      total_estimated_hours?: number;
      human_review_nodes?: number;
      source?: string;
    } | null;
    validation?: any;
    a6_missing: boolean;
  };
  a7_output: {
    test_plan: any;
    test_assets: any;
    dag_coverage?: any;
    a7_missing: boolean;
  };
  a8_output: {
    review: any;
    violations: any[];
    checks?: any;
    score: number;
    verdict: string;
    suggestions: any[];
    summary: string;
    a8_missing: boolean;
  };
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

// 鈹€鈹€ Dialogue (A1 HTTP+SSE) types 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

export interface DialogueEvent {
  type: 'thinking' | 'knowledge' | 'draft_update' | 'clarification' | 'wireframe' | 'done' | 'error';
  content?: string;
  draft?: RequirementDraft;
  sources?: KnowledgeSource[];
  items?: ClarificationItem[];
  data?: WireframeData;
  confidence_score?: number;
  knowledge_sources?: KnowledgeSource[];
  mcp_tools_used?: string[];
  session_id?: string;
  message_id?: number;
}

export interface RequirementDraft {
  title: string;
  description: string;
  domain: string;
  entities: DraftEntity[];
  use_cases: string[];
  acceptance_criteria: string[];
  constraints: string[];
  risks: string[];
  estimated_cost: string | null;
  // Extended fields for ArtifactPreview
  overview?: string;
  background?: string;
  objectives?: string;
  functional_requirements?: string;
  non_functional_requirements?: string;
  category?: string;
  confidence?: number;
}

export interface DraftEntity {
  name: string;
  attributes: string[];
  description: string;
}

export interface KnowledgeSource {
  name: string;
  count?: number;
  available?: boolean;
  type?: string;       // doc | code | api | spec
  title?: string;      // display title
  relevance?: number;  // 0-1 relevance score
}

export interface ClarificationItem {
  question: string;
  suggestion: string;
  field: string;
}

export interface WireframeData {
  type: string;
  pages: WireframePage[];
  components: WireframeComponent[];
  generated_at?: string;
}

export interface WireframePage {
  id: string;
  route: string;
  title: string;
  zones: string[];
}

export interface WireframeComponent {
  page_id: string;
  zone: string;
  component: string;
  type: string;
  props: Record<string, any>;
}

export interface DialogueMessage {
  id: number;
  role: 'human' | 'ai' | 'system';
  content: DialogueMessageContent;
  timestamp: string | null;
  sequence_number: number;
}

export interface DialogueMessageContent {
  text?: string;
  draft_preview?: Record<string, any>;
  clarifications?: { question: string; suggestion: string }[];
  type?: string;
  reject_reasons?: { category: string; description: string }[];
  revision_guidance?: string;
  cycle?: number;
}

export interface DialogueCycle {
  cycle: number;
  status: string;
  confirmed_at?: string;
  messages: DialogueMessage[];
  draft_snapshot?: RequirementDraft | null;
}

// 鈹€鈹€ LLM Call Monitoring 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

export interface LLMCallItem {
  call_id: string;
  agent_id: string;
  req_id: string;
  workflow_id: string;
  task_type: string;
  provider: string;
  model: string;
  prompt_chars: number;
  status: string;
  started_at: string;
  ended_at: string;
  duration_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  response_chars: number;
  response_preview: string;
  error_type: string | null;
  error_message: string | null;
}

export interface LLMCallDetail extends LLMCallItem {
  prompt: string | null;
  response: string | null;
  tokens_detail?: { prompt: number; completion: number; total: number };
}

export interface LLMCallListResponse {
  items: LLMCallItem[];
  total: number;
  limit: number;
  offset: number;
}

// E2E Pipeline types
export interface E2EEvent { type: string; data: Record<string, any>; }
export interface E2ERunResult { run_id: string; title: string; verdict: string; started_at: string; finished_at: string; steps: Record<string, any>; }

