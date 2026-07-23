// ============================================================
// Centralized API client
// ============================================================

import type {
  ApiListResponse,
  Requirement,
  AgentInfo,
  CodeDiff,
  ApprovalItem,
  Gate0Approval,
  ApprovalContext,
  DecideRequest,
  Gate2Context,
  Alert,
  Notification,
  TopologyNode,
  TopologyEdge,
  InsightsData,
  Release,
  DashboardStats,
  KnowledgeStatus,
  ChatMessage,
  ChatResponse,
  DialogueCycle,
  DialogueEvent,
  SpecSection,
  TestCase,
  LLMCallItem,
  LLMCallDetail,
  LLMCallListResponse,
  E2EEvent,
  E2ERunResult,
} from './types';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

async function fetchApi<T>(path: string, options?: RequestInit, baseOverride?: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${baseOverride || BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...options?.headers },
      ...options,
    });
  } catch (err) {
    throw new Error(`缃戠粶閿欒: 鏃犳硶杩炴帴鍒版湇鍔″櫒 (${BASE_URL})`);
  }

  if (!res.ok) {
    let errorMsg: string;
    try {
      const errorBody = await res.text();
      errorMsg = errorBody || res.statusText;
    } catch {
      errorMsg = res.statusText;
    }
    throw new Error(`API ${res.status}: ${errorMsg}`);
  }

  return res.json();
}

// Backend→Frontend field mapping for agents
interface BackendAgent {
  id: string; agent_id: string; agent_type: string; req_id?: string;
  task_id?: string | null; status: string; current_action?: string | null;
  tool_calls_json?: Record<string, any>; code_added?: number; code_removed?: number;
  anomaly?: string | null; session_id?: string | null; cost_usd?: number; created_at?: string;
}
function mapAgent(raw: BackendAgent): AgentInfo {
  if (!raw) return { id: '', name: '', type: '', status: 'idle', taskId: '', taskName: '', runtime: '', toolCalls: 0, toolSuccess: 0, toolFailed: 0, codeAdded: 0, codeRemoved: 0, lastActivity: [] };
  const toolCount = raw.tool_calls_json ? Object.keys(raw.tool_calls_json).length : 0;
  return {
    id: raw.id || '',
    name: raw.agent_id || '',
    type: raw.agent_type || '',
    status: (raw.status as AgentInfo['status']) || 'idle',
    taskId: raw.task_id || '',
    taskName: raw.req_id || '',
    runtime: raw.created_at || '',
    toolCalls: toolCount,
    toolSuccess: toolCount,
    toolFailed: 0,
    codeAdded: raw.code_added || 0,
    codeRemoved: raw.code_removed || 0,
    lastActivity: raw.current_action
      ? [{ time: raw.created_at || '', type: 'think', content: raw.current_action, success: true }]
      : [],
    anomaly: raw.anomaly || undefined,
  };
}

// Requirement field mapping (backend snake_case → frontend camelCase)
function mapRequirement(raw: any): Requirement {
  if (!raw) return {} as Requirement;
  return {
    id: raw.id || '',
    title: raw.title || '',
    description: (raw.requirement_draft && raw.requirement_draft.description) || raw.description || '',
    status: raw.status || 'draft',
    priority: 'P2',
    version: '1.0',
    pm: raw.creator_name || '',
    assignees: [],
    aiCompletion: 0,
    humanInterventions: raw.gate_rejection_count || 0,
    blocked: false,
    createdAt: raw.created_at || '',
    created_at: raw.created_at,
    updated_at: raw.updated_at,
    stages: [],
    relatedIds: [],
    stage: raw.status || 'pool',
  };
}
export const api = {
  // Dashboard
  getDashboardStats: () => fetchApi<DashboardStats>('/api/dashboard/stats'),

  // Requirements (with snake_case→camelCase mapping)
  getRequirements: (params?: {
    status?: string;
    priority?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.priority) qs.set('priority', params.priority);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const query = qs.toString();
    return fetchApi<ApiListResponse<any>>(
      `/api/requirements${query ? `?${query}` : ''}`
    ).then(raw => ({ ...raw, items: raw.items.map(mapRequirement) }));
  },

  getRequirement: (id: string) =>
    fetchApi<any>(
      `/api/requirements/${id}`
    ).then(mapRequirement) as Promise<Requirement & { approvals: any[]; activities: any[] }>,

  createRequirement: (data: {
    title: string;
    priority?: string;
    description?: string;
    source_type?: string;
  }) =>
    fetchApi<Requirement>('/api/requirements', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 鈹€鈹€ Dialogue (A1 HTTP+SSE) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
  createDialogueRequirement: (title?: string) =>
    fetchApi<{ req_id: string; session_id?: string; status: string; title: string | null; created_at: string }>(
      '/api/requirements',
      {
        method: 'POST',
        body: JSON.stringify({ title: title || '' }),
      }
    ),

  sendDialogueMessage: (
    reqId: string,
    message: string,
    sessionId: string | null,
    onEvent: (event: DialogueEvent) => void,
    onComplete?: () => void,
    onError?: (error: Error) => void,
  ): Promise<void> => {
    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';
    return new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/api/dialogue/chat`);
      xhr.setRequestHeader('Content-Type', 'application/json');

      let lastProcessedPos = 0;

      // Shared SSE parsing: processes raw text lines and dispatches typed events
      const processSSELines = (lines: string[]) => {
        let currentEventType = '';
        for (const line of lines) {
          if (line === '' || line === '\r') {
            currentEventType = '';
            continue;
          }
          if (line.startsWith('event: ')) {
            currentEventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (!dataStr) continue;
            try {
              const payload = JSON.parse(dataStr);
              // Event type comes from the SSE `event:` line (backend uses _format_sse which strips type from payload)
              const eventType = currentEventType || payload.type;
              const event = { type: eventType, ...payload };
              onEvent(event as DialogueEvent);
            } catch {}
            currentEventType = '';
          }
        }
      };

      xhr.onprogress = () => {
        const newText = xhr.responseText.substring(lastProcessedPos);
        lastProcessedPos = xhr.responseText.length;
        processSSELines(newText.split('\n'));
      };

      xhr.onload = () => {
        // Process any remaining data that may not have fired onprogress
        const newText = xhr.responseText.substring(lastProcessedPos);
        if (newText) {
          processSSELines(newText.split('\n'));
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new Error(`API ${xhr.status}: ${xhr.responseText}`));
        }
      };

      xhr.onerror = () => reject(new Error('缃戠粶閿欒'));
      xhr.ontimeout = () => reject(new Error('请求超时'));
      xhr.timeout = 300000;

      xhr.send(JSON.stringify({
        req_id: reqId,
        message,
        session_id: sessionId,
      }));
    });
  },

  confirmDialogue: (sessionId: string, finalNotes?: string) =>
    fetchApi<{
      ok: boolean;
      req_id: string;
      session_id: string;
      cycle: number;
      status: string;
      already_confirmed?: boolean;
    }>('/api/dialogue/confirm', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, final_notes: finalNotes }),
    }),

  getDialogueHistory: (sessionId: string) =>
    fetchApi<{
      session_id: string;
      req_id: string;
      cycles: DialogueCycle[];
      current_draft?: any;
      current_wireframe?: any;
    }>(`/api/dialogue/history/${sessionId}`),

  getDialogueCurrent: (reqId: string) =>
    fetchApi<{
      req_id: string;
      session_id: string | null;
      status: string;
      cycle: number;
      iterations?: number;
      total_messages?: number;
      confidence_score?: number | null;
    }>(`/api/dialogue/current/${reqId}`),

  // Agents
  getAgents: async (params?: { agent_type?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.agent_type) qs.set('agent_type', params.agent_type);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString();
    const raw = await fetchApi<ApiListResponse<BackendAgent>>(
      `/api/agents${query ? `?${query}` : ''}`
    );
    return { items: raw.items.map(mapAgent), total: raw.total, limit: raw.limit, offset: raw.offset };
  },

  getAgentDiffs: (agentId: string) =>
    fetchApi<{ agent_id: string; diffs: CodeDiff[] }>(
      `/api/agents/${agentId}/diffs`
    ),

  getTopology: () =>
    fetchApi<{ nodes: TopologyNode[]; edges: TopologyEdge[] }>('/api/topology'),

  // Approvals
  getApprovals: (params?: { gate_level?: number; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.gate_level !== undefined) qs.set('gate_level', String(params.gate_level));
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString();
    return fetchApi<ApiListResponse<Gate0Approval>>(
      `/api/approvals${query ? `?${query}` : ''}`
    );
  },

  getApproval: (id: string) =>
    fetchApi<Gate0Approval>(`/api/approvals/${id}`),

  getApprovalContext: (id: string) =>
    fetchApi<ApprovalContext>(`/api/approvals/${id}/context`),

  // Gate2 specialized context (aggregated A6+A7+A8 data)
  getGate2Context: (reqId: string) =>
    fetchApi<Gate2Context>(`/api/gate2/${reqId}/context`),

  decideApproval: (id: string, data: DecideRequest) =>
    fetchApi<Gate0Approval>(`/api/approvals/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Deprecate -...use decideApproval(id, {decision: 'pass'}) instead
  approve: (id: string) =>
    fetchApi<any>(`/api/approvals/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision: 'pass' }),
    }),

  // Deprecated ...MC Backend /api/approvals POST is for internal NATS subscriber use
  submitApproval: (reqId: string, gate?: number) =>
    fetchApi<any>('/api/approvals', {
      method: 'POST',
      body: JSON.stringify({ req_id: reqId, gate_level: gate || 0, cycle: 0, session_id: '' }),
    }),

  // Deprecated ...use decideApproval(id, {decision: 'reject', ...}) instead
  reject: (id: string, reason?: string) =>
    fetchApi<any>(`/api/approvals/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({
        decision: 'reject',
        reject_reasons: [{ category: 'other', description: reason || 'Rejected' }],
        revision_guidance: reason || 'Please revise',
      }),
    }),

  checkOverdueApprovals: () =>
    fetchApi<any>('/api/approvals'),

  // Insights
  getInsights: () => fetchApi<InsightsData>('/api/insights'),

  // Releases
  getReleases: () => fetchApi<ApiListResponse<Release>>('/api/releases'),

  // Alerts
  getAlerts: () => fetchApi<ApiListResponse<Alert>>('/api/alerts'),

  acknowledgeAlert: (id: string) =>
    fetchApi<any>(`/api/alerts/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ acknowledged: true }),
    }),

  // Notifications
  getNotifications: (params?: { unread?: boolean }) => {
    const qs = params?.unread ? '?unread=true' : '';
    return fetchApi<ApiListResponse<Notification>>(`/api/notifications${qs}`);
  },

  // Knowledge
  getKnowledge: async () => {
    try {
      const raw: any = await fetchApi<any>('/api/knowledge');
      // Backend returns api_stats (snake_case), map to apiStats (camelCase)
      return {
        projects: raw.projects || [],
        apiStats: raw.api_stats || raw.apiStats || { indexed: 0, deprecated: 0, undocumented: 0, conflicts: 0 },
        todos: raw.todos || [],
      } as KnowledgeStatus;
    }
    catch { return { projects: [], apiStats: { indexed: 0, deprecated: 0, undocumented: 0, conflicts: 0 } }; }
  },

  // Chat + Spec
  getChatMessages: (reqId: string) =>
    fetchApi<{ messages: ChatMessage[]; req_id: string }>(
      `/api/chat/${reqId}/chat`
    ),

  sendChatMessage: (reqId: string, message: string, mode?: string,
    onChunk?: (text: string) => void,
    onDone?: (options: any[], specUpdates: any[]) => void,
  ) => {
    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';
    // Use XMLHttpRequest instead of fetch+ReadableStream for better Next.js compat
    return new Promise<ChatResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/api/chat/${reqId}/chat`);
      xhr.setRequestHeader('Content-Type', 'application/json');

      let fullReply = '';
      let options: any[] = [];
      let specUpdates: any[] = [];
      let lastProcessedPos = 0;

      xhr.onprogress = () => {
        // Read new text since last read position
        const newText = xhr.responseText.substring(lastProcessedPos);
        lastProcessedPos = xhr.responseText.length;

        // Parse SSE events from new text
        const lines = newText.split('\n');
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const dataStr = line.slice(6).trim();
          if (!dataStr) continue;
          try {
            const event = JSON.parse(dataStr);
            if (event.type === 'text') {
              fullReply += event.content;
              onChunk?.(event.content);
            } else if (event.type === 'thinking') {
              // skip thinking events in display
            } else if (event.type === 'done') {
              options = event.options || [];
              specUpdates = event.spec_updates || [];
            } else if (event.type === 'error') {
              reject(new Error(event.content));
              return;
            }
          } catch {}
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          // Call onDone BEFORE resolving so UI updates first
          onDone?.(options, specUpdates);
          resolve({ reply: fullReply, options, spec_updates: specUpdates });
        } else {
          reject(new Error(`API ${xhr.status}: ${xhr.responseText}`));
        }
      };

      xhr.onerror = () => reject(new Error('缃戠粶閿欒'));
      xhr.ontimeout = () => reject(new Error('请求超时'));
      xhr.timeout = 180000;  // 3 min timeout

      xhr.send(JSON.stringify({ message, mode }));
    });
  },

  getSpecSections: (reqId: string) =>
    fetchApi<{ sections: SpecSection[] }>(`/api/chat/${reqId}/spec`),

  updateSpecSections: (reqId: string, sections: SpecSection[]) =>
    fetchApi<any>(`/api/chat/${reqId}/spec`, {
      method: 'PUT',
      body: JSON.stringify({ sections }),
    }),

  // Test Cases
  getTestCases: (reqId: string) =>
    fetchApi<ApiListResponse<TestCase>>(`/api/tests/${reqId}/cases`),

  createTestCase: (reqId: string, data: any) =>
    fetchApi<TestCase>(`/api/tests/${reqId}/cases`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateTestCase: (reqId: string, caseId: string, data: any) =>
    fetchApi<TestCase>(`/api/tests/${reqId}/cases/${caseId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteTestCase: (reqId: string, caseId: string) =>
    fetchApi<void>(`/api/tests/${reqId}/cases/${caseId}`, {
      method: 'DELETE',
    }),

  // LLM Calls
  getLLMCalls: async (params?: {
    agent_id?: string;
    req_id?: string;
    task_type?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.agent_id) qs.set('agent_id', params.agent_id);
    if (params?.req_id) qs.set('req_id', params.req_id);
    if (params?.task_type) qs.set('task_type', params.task_type);
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const query = qs.toString();
    return fetchApi<LLMCallListResponse>(
      `/api/llm-calls${query ? `?${query}` : ''}`
    );
  },


  // E2E Pipeline Tests (testing-tool port 8500)
  e2e: {
    run: (title: string, message: string) => {
      const E2E_BASE = process.env.NEXT_PUBLIC_TESTING_TOOL_URL || 'http://localhost:8500';
      return fetchApi<{ ok: boolean; run_id: string }>(
        '/api/tests/e2e/run',
        { method: 'POST', body: JSON.stringify({ title, message }) },
        E2E_BASE
      );
    },
    results: (runId: string) => {
      const E2E_BASE = process.env.NEXT_PUBLIC_TESTING_TOOL_URL || 'http://localhost:8500';
      return fetchApi('/api/tests/e2e/results/' + runId, {}, E2E_BASE);
    },
    history: (limit = 20) => {
      const E2E_BASE = process.env.NEXT_PUBLIC_TESTING_TOOL_URL || 'http://localhost:8500';
      return fetchApi<{ items: E2ERunResult[] }>('/api/tests/e2e/history?limit=' + limit, {}, E2E_BASE);
    },
    stream: (runId: string, eventHandler: (event: E2EEvent) => void): Promise<void> => {
      const E2E_BASE = process.env.NEXT_PUBLIC_TESTING_TOOL_URL || 'http://localhost:8500';
      return new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", E2E_BASE + "/api/tests/e2e/stream/" + runId);
        xhr.setRequestHeader("Accept", "text/event-stream");
        xhr.timeout = 600000;
        let lastPos = 0;
        xhr.onprogress = () => {
          const newText = xhr.responseText.substring(lastPos);
          lastPos = xhr.responseText.length;
          const lines = newText.split("\n");
          for (let i = 0; i < lines.length; i++) {
            if (lines[i].startsWith("event: ")) {
              const type = lines[i].slice(7).trim();
              const next = lines[i + 1];
              if (next && next.startsWith("data: ")) {
                try {
                  const data = JSON.parse(next.slice(6).trim());
                  eventHandler({ type, data } as E2EEvent);
                } catch {}
              }
            }
          }
        };
        xhr.onload = () => xhr.status < 300 ? resolve() : reject(new Error(String(xhr.status)));
        xhr.onerror = () => reject(new Error("Connection failed"));
        xhr.ontimeout = () => reject(new Error("Timeout"));
        xhr.send();
      });
    },
  },
  getLLMCall: (callId: string) =>
    fetchApi<LLMCallDetail>(`/api/llm-calls/${callId}`),
};

