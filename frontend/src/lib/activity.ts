// ============================================================
// Activity Stream types for real-time agent activity updates
// ============================================================

export enum ConnectionStatus {
  Connected = 'connected',
  Disconnected = 'disconnected',
  Connecting = 'connecting',
  Error = 'error',
}

export type ActivityEventType = 'status' | 'progress' | 'artifact' | 'message';

export interface ActivityEvent {
  id: string;
  type: ActivityEventType;
  agentId: string;
  agentName?: string;
  status?: string;
  message?: string;
  timestamp: string;
  progress?: {
    step: string;
    percentage: number;
    total?: number;
    current?: number;
  };
  artifact?: {
    type: string;
    content: string;
    path?: string;
  };
  details?: Record<string, any>;
}

export interface Activity extends ActivityEvent {
  reqId?: string;
}

export interface ActivityStreamState {
  activities: Activity[];
  isConnected: ConnectionStatus;
  error: Error | null;
  lastUpdate?: string;
}
