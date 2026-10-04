// ============================================================
// SSE Client — 可复用的 Server-Sent Events 连接模块
// 从 dashboard/page.tsx 和 v2/page.tsx 的内联 SSE 逻辑提取
// 版本: v1.0 | 日期: 2026-09-23
// ============================================================

/** SSE 事件处理器接口 */
export interface SSEHandlers {
  onStarted?: (data: Record<string, unknown>) => void;
  onProgress?: (data: Record<string, unknown>) => void;
  onDone?: (data: Record<string, unknown>) => void;
  onError?: (error: Error) => void;
}

/** 连接选项 */
export interface SSEConnectOptions {
  thinking_mode?: string;
  llm_model?: string;
  intent_method?: string;
  lang?: string;
  trading_mode?: string;
  session_id?: string;
  /** 超时毫秒数（默认 180000 = 3 分钟） */
  timeoutMs?: number;
}

/** 任务流连接结果 */
export interface SSEConnectResult {
  /** AbortController，用于取消连接 */
  controller: AbortController;
  /** Promise，在流结束时 resolve（done 或 error 或 stream 结束） */
  done: Promise<{ finalData: Record<string, unknown> | null; status: 'completed' | 'processing' | 'error' | 'no_result' }>;
}

/**
 * 连接 /api/task/stream SSE 端点
 *
 * 使用方式：
 * ```ts
 * const { controller, done } = connectTaskStream("分析 BTC", options, handlers);
 * // 取消：controller.abort()
 * // 等待完成：const result = await done;
 * ```
 */
export function connectTaskStream(
  message: string,
  options: SSEConnectOptions = {},
  handlers: SSEHandlers,
): SSEConnectResult {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 180000;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const done = (async () => {
    try {
      const response = await fetch("/api/task/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: options.session_id ?? "default",
          thinking_mode: options.thinking_mode ?? "quick",
          llm_model: options.llm_model,
          intent_method: options.intent_method,
          lang: options.lang ?? "zh",
          trading_mode: options.trading_mode ?? "ai_skill",
        }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok || !response.body) {
        const err = new Error(`HTTP ${response.status}`);
        handlers.onError?.(err);
        return { finalData: null, status: 'error' as const };
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalData: Record<string, unknown> | null = null;

      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE 事件以 \n\n 分隔
        const eventBlocks = buffer.split("\n\n");
        buffer = eventBlocks.pop() || "";

        for (const block of eventBlocks) {
          if (!block.trim()) continue;

          let eventType = "message";
          let eventData = "";

          for (const line of block.split("\n")) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith("data: ")) {
              eventData += line.slice(6);
            }
          }

          if (!eventData) continue;

          try {
            const data = JSON.parse(eventData) as Record<string, unknown>;
            switch (eventType) {
              case "started":
                handlers.onStarted?.(data);
                break;
              case "progress":
                handlers.onProgress?.(data);
                break;
              case "done":
                finalData = data;
                handlers.onDone?.(data);
                break;
              case "error":
                const errMsg = (data as any).error || "Unknown error";
                handlers.onError?.(new Error(errMsg));
                return { finalData: null, status: 'error' as const };
            }
          } catch {
            // JSON 解析失败，忽略
          }
        }
      }

      if (finalData && (finalData as any).status === "completed") {
        return { finalData, status: 'completed' as const };
      } else if (finalData && (finalData as any).status === "processing") {
        return { finalData, status: 'processing' as const };
      } else {
        return { finalData, status: 'no_result' as const };
      }
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (err.name === "AbortError") {
        // 用户取消，不算错误
        return { finalData: null, status: 'no_result' as const };
      }
      handlers.onError?.(err);
      return { finalData: null, status: 'error' as const };
    }
  })();

  return { controller, done };
}

/**
 * 连接常驻监控流 /api/monitor/stream
 *
 * 与 connectTaskStream 不同，这是一个长连接，持续接收事件直到关闭。
 */
export function connectMonitorStream(
  onEvent: (data: Record<string, unknown>) => void,
  onError?: (error: Error) => void,
): { close: () => void } {
  let closed = false;
  let reconnectDelay = 1000;
  let eventSource: EventSource | null = null;

  const connect = () => {
    if (closed) return;
    eventSource = new EventSource("/api/monitor/stream");

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as Record<string, unknown>;
        onEvent(data);
      } catch {
        // 忽略非 JSON 数据
      }
    };

    eventSource.onerror = () => {
      eventSource?.close();
      if (closed) return;

      // 指数退避重连
      reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
      setTimeout(connect, reconnectDelay);
    };

    eventSource.onopen = () => {
      // 重置退避
      reconnectDelay = 1000;
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      eventSource?.close();
    },
  };
}
