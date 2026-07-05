'use client';

// ============================================
// v3 useSSE Hook — 流式对话 Hook
// ============================================

import { useCallback, useRef } from 'react';
import { createSSEConnection, type SSEHandlerMap, type SSEConnection } from './sse-client';

interface UseSSEOptions {
  url?: string;
  handlers: SSEHandlerMap;
  onError?: (error: Error) => void;
}

interface UseSSEReturn {
  send: (body: unknown) => SSEConnection;
  close: () => void;
}

export function useSSE(options: UseSSEOptions): UseSSEReturn {
  const { url = '/api/chat', handlers, onError } = options;
  const connectionRef = useRef<SSEConnection | null>(null);

  const send = useCallback((body: unknown) => {
    // 关闭之前的连接
    connectionRef.current?.close();

    const connection = createSSEConnection(url, body, handlers, {
      onError: onError || console.error,
    });

    connectionRef.current = connection;
    return connection;
  }, [url, handlers, onError]);

  const close = useCallback(() => {
    connectionRef.current?.close();
    connectionRef.current = null;
  }, []);

  return { send, close };
}

export default useSSE;
