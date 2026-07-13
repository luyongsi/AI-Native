/**
 * Zustand store for A1 Dialogue session state.
 *
 * Tracks: session_id, current cycle, accumulated draft, SSE streaming events,
 * clarification items, knowledge sources, and confirmation status.
 */
import { create } from 'zustand';
import type {
  DialogueEvent,
  RequirementDraft,
  KnowledgeSource,
  ClarificationItem,
  DialogueMessage,
  DialogueCycle,
} from '@/lib/types';

export interface DialogueState {
  // Session identity
  reqId: string | null;
  sessionId: string | null;
  cycle: number;
  status: 'no_session' | 'active' | 'reopened' | 'completed' | 'loading';

  // Streaming state
  isStreaming: boolean;
  thinkingText: string;
  knowledgeSources: KnowledgeSource[];
  clarifications: ClarificationItem[];
  wireframe: any;

  // Accumulated draft
  draft: RequirementDraft | null;
  confidenceScore: number | null;

  // Error
  error: string | null;

  // History
  cycles: DialogueCycle[];
  messages: DialogueMessage[];
  iterations: number;
  totalMessages: number;

  // Actions
  setSession: (reqId: string, sessionId: string | null, status: string, cycle: number) => void;
  startStreaming: () => void;
  handleEvent: (event: DialogueEvent) => void;
  stopStreaming: (sessionId: string, error?: string) => void;
  confirmDone: () => void;
  setHistory: (cycles: DialogueCycle[]) => void;
  setCurrentInfo: (info: { iterations?: number; total_messages?: number; confidence_score?: number | null }) => void;
  reset: () => void;
}

export const useDialogueStore = create<DialogueState>((set, get) => ({
  reqId: null,
  sessionId: null,
  cycle: 0,
  status: 'no_session',
  isStreaming: false,
  thinkingText: '',
  knowledgeSources: [],
  clarifications: [],
  wireframe: null,
  draft: null,
  confidenceScore: null,
  error: null,
  cycles: [],
  messages: [],
  iterations: 0,
  totalMessages: 0,

  setSession: (reqId, sessionId, status, cycle) =>
    set({
      reqId,
      sessionId,
      status: status as DialogueState['status'],
      cycle,
      error: null,
    }),

  startStreaming: () =>
    set({
      isStreaming: true,
      thinkingText: '正在连接 AI 模型...',
      knowledgeSources: [],
      clarifications: [],
      wireframe: null,
      error: null,
    }),

  handleEvent: (event) => {
    switch (event.type) {
      case 'thinking':
        set({ thinkingText: event.content || '' });
        break;
      case 'knowledge':
        set({ knowledgeSources: event.sources || [] });
        break;
      case 'draft_update':
        set({ draft: event.draft || null });
        break;
      case 'clarification':
        set({ clarifications: event.items || [] });
        break;
      case 'wireframe':
        set({ wireframe: event.data || null });
        break;
      case 'done': {
        const s = get();
        set({
          draft: event.draft || s.draft,
          confidenceScore: event.confidence_score ?? s.confidenceScore,
          knowledgeSources: event.knowledge_sources || s.knowledgeSources,
          thinkingText: '',
          isStreaming: false,
        });
        break;
      }
      case 'error':
        set({
          error: event.content || '分析出错',
          isStreaming: false,
        });
        break;
    }
  },

  stopStreaming: (sessionId, error?) =>
    set({
      isStreaming: false,
      thinkingText: '',
      sessionId: sessionId || get().sessionId,
      error: error || null,
    }),

  confirmDone: () =>
    set({
      status: 'completed',
      isStreaming: false,
    }),

  setHistory: (cycles) =>
    set({
      cycles,
      messages: cycles.flatMap((c) => c.messages),
    }),

  setCurrentInfo: (info) =>
    set({
      iterations: info.iterations ?? get().iterations,
      totalMessages: info.total_messages ?? get().totalMessages,
      confidenceScore: info.confidence_score ?? get().confidenceScore,
    }),

  reset: () =>
    set({
      reqId: null,
      sessionId: null,
      cycle: 0,
      status: 'no_session',
      isStreaming: false,
      thinkingText: '',
      knowledgeSources: [],
      clarifications: [],
      wireframe: null,
      draft: null,
      confidenceScore: null,
      error: null,
      cycles: [],
      messages: [],
      iterations: 0,
      totalMessages: 0,
    }),
}));
