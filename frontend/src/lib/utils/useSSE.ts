"use client";

import { useState, useEffect, useRef, useCallback } from "react";

// ============================================================================
// Types
// ============================================================================

export interface UseSSEOptions<T> {
  onEvent?: (event: T) => void;
  onError?: (error: Error) => void;
  onComplete?: () => void;
  enabled?: boolean;
}

export interface UseSSEReturn<T> {
  isConnected: boolean;
  error: Error | null;
  lastEvent: T | null;
  reconnect: () => void;
}

// ============================================================================
// Constants
// ============================================================================

const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;
const RECONNECT_BACKOFF_MULTIPLIER = 2;

// ============================================================================
// Parser helpers
// ============================================================================

function parseSSEChunk(chunk: string): Array<{ event: string; data: unknown }> {
  const events: Array<{ event: string; data: unknown }> = [];
  const parts = chunk.split("\n\n");

  for (const part of parts) {
    const trimmed = part.trim();
    if (trimmed === "") continue;

    let eventType = "message";
    let dataLines: string[] = [];

    for (const line of trimmed.split("\n")) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      } else if (line.startsWith(":")) {
        // SSE comment — ignore
        continue;
      }
      // Unknown fields are silently ignored per SSE spec
    }

    if (dataLines.length === 0) continue;

    const rawData = dataLines.join("\n");
    let parsed: unknown;
    try {
      parsed = JSON.parse(rawData);
    } catch {
      parsed = rawData;
    }

    events.push({ event: eventType, data: parsed });
  }

  return events;
}

// ============================================================================
// Hook
// ============================================================================

export function useSSE<T>(url: string, options?: UseSSEOptions<T>): UseSSEReturn<T> {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastEvent, setLastEvent] = useState<T | null>(null);

  // Refs to avoid re-triggering effect when callbacks change
  const onEventRef = useRef(options?.onEvent);
  const onErrorRef = useRef(options?.onError);
  const onCompleteRef = useRef(options?.onComplete);
  const enabledRef = useRef(options?.enabled ?? true);

  onEventRef.current = options?.onEvent;
  onErrorRef.current = options?.onError;
  onCompleteRef.current = options?.onComplete;
  enabledRef.current = options?.enabled ?? true;

  const abortRef = useRef<AbortController | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY_MS);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef(true);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsConnected(false);
    setError(null);

    fetch(url, {
      headers: { Accept: "text/event-stream" },
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`SSE connection failed: ${response.status} ${response.statusText}`);
        }

        if (!isMountedRef.current) return;

        setIsConnected(true);
        reconnectDelayRef.current = INITIAL_RECONNECT_DELAY_MS;

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("ReadableStream not supported");
        }

        const decoder = new TextDecoder();
        let buffer = "";

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              // Stream ended cleanly
              if (isMountedRef.current) {
                setIsConnected(false);
                onCompleteRef.current?.();
              }
              return;
            }

            buffer += decoder.decode(value, { stream: true });

            // SSE events are separated by \n\n — only parse complete events
            // to avoid splitting multi-line data across chunks
            const lastDoubleNewline = buffer.lastIndexOf("\n\n");
            if (lastDoubleNewline === -1) continue;

            const completePart = buffer.slice(0, lastDoubleNewline + 2);
            buffer = buffer.slice(lastDoubleNewline + 2);

            const events = parseSSEChunk(completePart);
            for (const ev of events) {
              if (isMountedRef.current) {
                setLastEvent(ev.data as T);
                onEventRef.current?.(ev.data as T);
              }
            }
          }
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") {
            // Intentional abort — no reconnect
            return;
          }
          throw err;
        }
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;

        if (isMountedRef.current) {
          const errorObj = err instanceof Error ? err : new Error(String(err));
          setError(errorObj);
          setIsConnected(false);
          onErrorRef.current?.(errorObj);
        }

        // Exponential backoff reconnect
        if (isMountedRef.current && enabledRef.current) {
          const delay = reconnectDelayRef.current;
          reconnectDelayRef.current = Math.min(
            delay * RECONNECT_BACKOFF_MULTIPLIER,
            MAX_RECONNECT_DELAY_MS
          );

          reconnectTimerRef.current = setTimeout(() => {
            connect();
          }, delay);
        }
      });
  }, [url]);

  const reconnect = useCallback(() => {
    reconnectDelayRef.current = INITIAL_RECONNECT_DELAY_MS;
    clearReconnectTimer();
    abortRef.current?.abort();
    setError(null);
    connect();
  }, [connect, clearReconnectTimer]);

  useEffect(() => {
    isMountedRef.current = true;

    if (enabledRef.current) {
      connect();
    }

    return () => {
      isMountedRef.current = false;
      clearReconnectTimer();
      abortRef.current?.abort();
    };
  }, [connect, clearReconnectTimer]);

  return { isConnected, error, lastEvent, reconnect };
}