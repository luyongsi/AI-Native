// ============================================================
// WebSocket client for real-time agent status updates
// ============================================================

type MessageHandler = (data: any) => void;

class WSClient {
  private ws: WebSocket | null = null;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private url: string = '';
  private shouldReconnect: boolean = true;

  connect(token: string, reqId?: string) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const base = process.env.NEXT_PUBLIC_WS_URL || `${protocol}//${location.host}/ws/gateway`;
    this.url = `${base}?token=${token}${reqId ? `&req_id=${reqId}` : ''}`;
    this.shouldReconnect = true;
    this._doConnect();
  }

  private _doConnect() {
    if (!this.url) return;
    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('[WS] Connected');
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const type = data.type || data.event_type;
          if (type) {
            this.handlers.get(type)?.forEach((h) => h(data));
            this.handlers.get('*')?.forEach((h) => h(data));
          }
        } catch {
          // Ignore non-JSON messages
        }
      };

      this.ws.onclose = () => {
        console.log('[WS] Disconnected');
        if (this.shouldReconnect) {
          this.reconnectTimer = setTimeout(() => this._doConnect(), 3000);
        }
      };

      this.ws.onerror = () => {
        // onclose will handle reconnect
      };
    } catch {
      // Connection failed, retry
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => this._doConnect(), 3000);
      }
    }
  }

  on(eventType: string, handler: MessageHandler) {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler);
  }

  off(eventType: string, handler: MessageHandler) {
    this.handlers.get(eventType)?.delete(handler);
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }

  subscribe(reqId: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ subscribe: reqId }));
    }
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export const wsClient = new WSClient();
