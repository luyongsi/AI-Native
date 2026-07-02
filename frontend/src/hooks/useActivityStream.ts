'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import type { Activity, ActivityEvent, ConnectionStatus } from '@/lib/activity';
import { ConnectionStatus as ConnStatus } from '@/lib/activity';

interface UseActivityStreamOptions {
  reqId?: string;
  autoReconnect?: boolean;
  reconnectDelay?: number;
  maxRetries?: number;
}

interface UseActivityStreamReturn {
  activities: Activity[];
  isConnected: ConnectionStatus;
  error: Error | null;
  lastUpdate?: string;
}

export function useActivityStream({
  reqId,
  autoReconnect = true,
  reconnectDelay = 3000,
  maxRetries = 5,
}: UseActivityStreamOptions = {}): UseActivityStreamReturn {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [isConnected, setIsConnected] = useState<ConnectionStatus>(ConnStatus.Disconnected);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdate, setLastUpdate] = useState<string>();

  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectCountRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef(true);

  const buildStreamUrl = useCallback(() => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';
    let url = `${baseUrl}/api/activity/stream`;
    if (reqId) {
      url += `?req_id=${encodeURIComponent(reqId)}`;
    }
    return url;
  }, [reqId]);

  const parseActivityEvent = useCallback((data: any): Activity | null => {
    try {
      if (typeof data === 'string') {
        data = JSON.parse(data);
      }

      const event: Activity = {
        id: data.id || `${Date.now()}-${Math.random()}`,
        type: data.type || 'message',
        agentId: data.agent_id || data.agentId || 'unknown',
        agentName: data.agent_name || data.agentName,
        status: data.status,
        message: data.message || data.content,
        timestamp: data.timestamp || new Date().toISOString(),
        progress: data.progress,
        artifact: data.artifact,
        details: data.details || data.data,
        reqId: data.req_id || data.reqId,
      };

      return event;
    } catch {
      return null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;

    // Prevent multiple simultaneous connections
    if (eventSourceRef.current) {
      return;
    }

    try {
      setIsConnected(ConnStatus.Connecting);
      setError(null);

      const url = buildStreamUrl();
      const eventSource = new EventSource(url);

      eventSource.addEventListener('open', () => {
        if (isMountedRef.current) {
          setIsConnected(ConnStatus.Connected);
          reconnectCountRef.current = 0;
        }
      });

      eventSource.addEventListener('activity', (event: Event) => {
        if (!isMountedRef.current) return;

        const customEvent = event as any;
        const activity = parseActivityEvent(customEvent.data);

        if (activity) {
          setActivities((prev) => {
            // Avoid duplicates by checking ID
            if (prev.some((a) => a.id === activity.id)) {
              return prev;
            }
            // Keep last 100 activities to avoid memory bloat
            return [...prev, activity].slice(-100);
          });
          setLastUpdate(new Date().toISOString());
        }
      });

      eventSource.addEventListener('error', () => {
        if (!isMountedRef.current) return;

        eventSource.close();
        eventSourceRef.current = null;
        setIsConnected(ConnStatus.Error);

        if (autoReconnect && reconnectCountRef.current < maxRetries) {
          reconnectCountRef.current += 1;
          reconnectTimerRef.current = setTimeout(connect, reconnectDelay);
        } else if (reconnectCountRef.current >= maxRetries) {
          setError(new Error(`Failed to connect after ${maxRetries} attempts`));
        }
      });

      eventSource.addEventListener('close', () => {
        if (!isMountedRef.current) return;

        eventSource.close();
        eventSourceRef.current = null;
        setIsConnected(ConnStatus.Disconnected);

        if (autoReconnect && reconnectCountRef.current < maxRetries) {
          reconnectCountRef.current += 1;
          reconnectTimerRef.current = setTimeout(connect, reconnectDelay);
        }
      });

      eventSourceRef.current = eventSource;
    } catch (err) {
      if (isMountedRef.current) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        setIsConnected(ConnStatus.Error);

        if (autoReconnect && reconnectCountRef.current < maxRetries) {
          reconnectCountRef.current += 1;
          reconnectTimerRef.current = setTimeout(connect, reconnectDelay);
        }
      }
    }
  }, [buildStreamUrl, parseActivityEvent, autoReconnect, reconnectDelay, maxRetries]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setIsConnected(ConnStatus.Disconnected);
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    connect();

    return () => {
      isMountedRef.current = false;
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    activities,
    isConnected,
    error,
    lastUpdate,
  };
}
