// ============================================================
// Centralized API client
// ============================================================

import type {
  ApiListResponse,
  Requirement,
  AgentInfo,
  CodeDiff,
  ApprovalItem,
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
  SpecSection,
  TestCase,
} from './types';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...options?.headers },
      ...options,
    });
  } catch (err) {
    throw new Error(`网络错误: 无法连接到服务器 (${BASE_URL})`);
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

export const api = {
  // Dashboard
  getDashboardStats: () => fetchApi<DashboardStats>('/api/dashboard/stats'),

  // Requirements
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
    return fetchApi<ApiListResponse<Requirement>>(
      `/api/requirements${query ? `?${query}` : ''}`
    );
  },

  getRequirement: (id: string) =>
    fetchApi<Requirement & { approvals: any[]; activities: any[] }>(
      `/api/requirements/${id}`
    ),

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

  // ── Dialogue (A1 HTTP+SSE) ────────────────────────────────────────
  createDialogueRequirement: (title?: string) =>
    fetchApi<{ req_id: string; status: string; title: string | null; created_at: string }>(
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
  ): Promise<void> => {
    const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';
    return new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/api/dialogue/chat`);
      xhr.setRequestHeader('Content-Type', 'application/json');

      let lastProcessedPos = 0;
      // Track accumulated draft across stream
      let accumulatedDraft: any = null;

      xhr.onprogress = () => {
        const newText = xhr.responseText.substring(lastProcessedPos);
        lastProcessedPos = xhr.responseText.length;

        const lines = newText.split('\n');
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const dataStr = line.slice(6).trim();
          if (!dataStr) continue;
          try {
            const event = JSON.parse(dataStr);
            // 'draft_update' events carry full draft in event.draft
            if (event.draft && !event.type) {
              // Inline draft from draft_update event
              accumulatedDraft = event.draft;
              onEvent({ type: 'draft_update', draft: event.draft });
            } else if (event.type) {
              if (event.type === 'draft_update') {
                accumulatedDraft = event.draft;
              }
              onEvent(event as DialogueEvent);
            }
          } catch {}
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new Error(`API ${xhr.status}: ${xhr.responseText}`));
        }
      };

      xhr.onerror = () => reject(new Error('网络错误'));
      xhr.ontimeout = () => reject(new Error('请求超时'));
      xhr.timeout = 300000; // 5 min timeout for SSE

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
  getAgents: (params?: { agent_type?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.agent_type) qs.set('agent_type', params.agent_type);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString();
    return fetchApi<ApiListResponse<AgentInfo>>(
      `/api/agents${query ? `?${query}` : ''}`
    );
  },

  getAgentDiffs: (agentId: string) =>
    fetchApi<{ agent_id: string; diffs: CodeDiff[] }>(
      `/api/agents/${agentId}/diffs`
    ),

  getTopology: () =>
    fetchApi<{ nodes: TopologyNode[]; edges: TopologyEdge[] }>('/api/topology'),

  // Approvals
  getApprovals: (params?: { gate?: number; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.gate !== undefined) qs.set('gate', String(params.gate));
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString();
    return fetchApi<ApiListResponse<ApprovalItem>>(
      `/api/approvals${query ? `?${query}` : ''}`
    );
  },

  approve: (id: string) =>
    fetchApi<any>(`/api/approvals/${id}/approve`, { method: 'POST' }),

  submitApproval: (reqId: string, gate?: number) =>
    fetchApi<any>(`/api/approvals?req_id=${reqId}&gate=${gate || 1}`, { method: 'POST' }),

  reject: (id: string, reason?: string) =>
    fetchApi<any>(`/api/approvals/${id}/reject${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`, {
      method: 'POST',
    }),

  checkOverdueApprovals: () =>
    fetchApi<any>('/api/approvals/check-overdue'),

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
  getKnowledge: () => fetchApi<KnowledgeStatus>('/api/knowledge'),

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

      xhr.onerror = () => reject(new Error('网络错误'));
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
};
