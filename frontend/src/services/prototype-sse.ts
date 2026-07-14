// ============================================================
// Prototype SSE stream handler
// ============================================================

export interface PrototypeSSEHandlers {
  thinking?: (data: { message: string }) => void;
  knowledge?: (data: { templates: any[]; components: string[] }) => void;
  annotation_parsed?: (data: { parsed: any[] }) => void;
  prototype_update?: (data: { html_chunk: string; progress: number }) => void;
  screens?: (data: { screens: any[] }) => void;
  done?: (data: {
    prototype_url: string;
    version: number;
    screens?: any[];
    annotation_count?: number;
    upload_failed?: boolean;
  }) => void;
  error?: (data: { message: string }) => void;
}

export async function streamPrototype(
  apiUrl: string,
  body: object,
  handlers: PrototypeSSEHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';
  const token = typeof localStorage !== 'undefined'
    ? localStorage.getItem('token') || ''
    : '';

  const response = await fetch(`${BASE_URL}${apiUrl}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const errorText = await response.text();
    let errorMsg: string;
    try {
      const err = JSON.parse(errorText);
      errorMsg = err.detail || errorText;
    } catch {
      errorMsg = errorText;
    }
    throw new Error(`API ${response.status}: ${errorMsg}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';
  let currentData = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        // Process previous event if any
        if (currentEvent && currentData) {
          _dispatch(currentEvent, currentData, handlers);
        }
        currentEvent = line.slice(7).trim();
        currentData = '';
      } else if (line.startsWith('data: ')) {
        currentData = line.slice(6);
      }
    }

    // Process last event in chunk
    if (currentEvent && currentData) {
      _dispatch(currentEvent, currentData, handlers);
      currentEvent = '';
      currentData = '';
    }
  }

  // Process any remaining event
  if (currentEvent && currentData) {
    _dispatch(currentEvent, currentData, handlers);
  }
}

function _dispatch(
  event: string,
  dataStr: string,
  handlers: PrototypeSSEHandlers,
) {
  try {
    const data = JSON.parse(dataStr);
    switch (event) {
      case 'thinking':
        handlers.thinking?.(data);
        break;
      case 'knowledge':
        handlers.knowledge?.(data);
        break;
      case 'annotation_parsed':
        handlers.annotation_parsed?.(data);
        break;
      case 'prototype_update':
        handlers.prototype_update?.(data);
        break;
      case 'screens':
        handlers.screens?.(data);
        break;
      case 'done':
        handlers.done?.(data);
        break;
      case 'error':
        handlers.error?.(data);
        break;
    }
  } catch {
    // Ignore JSON parse errors for partial chunks
  }
}
