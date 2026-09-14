/**
 * client.ts — DreamOS HTTP 客户端（S1）
 * DreamOS 前端桥 · 20260829-bridge
 *
 * 职责：封装 DreamOS api_server（Flask :8000）的全部 HTTP 调用。
 * 纪律：
 *   - 零业务依赖（不 import 任何 @/lib 业务模块）
 *   - base URL 仅来自 env DREAMOS_API_URL（默认 http://127.0.0.1:8000）
 *   - AbortController 超时控制；只读端点 15s，同步编排 180s
 *   - 同步 /run 仅作降级兜底；生产路径走 run/async + result 轮询
 */

const BASE_URL = (process.env.DREAMOS_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const READ_TIMEOUT_MS = 15_000;
const RUN_TIMEOUT_MS = 180_000; // 实测最差 54s + buffer

// ============ 类型 ============

/** 外部意图提示（P0 正典对齐：网关正典 → DreamOS S 层） */
export interface DreamOSIntentHint {
  /** DreamOS IntentType（TREND_FOLLOWING/BREAKOUT/.../UNCERTAIN） */
  intent_type: string;
  confidence?: number;
  /** 建议主链（A/C/F），可空 */
  chain?: string;
  /** 来源标记：frontend_canon | mcp_canon | manual */
  provenance?: string;
  /** 网关正典原名（审计用，如 deep_analysis） */
  canon_intent?: string;
}

export interface DreamOSRunPayload {
  user_input: string;
  market_data?: Record<string, unknown>;
  context?: Record<string, unknown>;
  intent_hint?: DreamOSIntentHint;
}

export interface DreamOSRunResult {
  cycle_id?: string;
  action?: string;
  confidence?: number;
  rationale?: string[];
  intent?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  execution?: Record<string, unknown>;
  tokens_used?: number;
  latency_ms?: number;
  error?: string;
  [key: string]: unknown;
}

export interface DreamOSAsyncResult {
  cycle_id: string;
  status: "accepted" | "pending" | "running" | "done" | "error";
  result?: DreamOSRunResult;
  error?: string;
}

// ============ 内部 ============

async function fetchJson<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = READ_TIMEOUT_MS,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    const body = (await res.json().catch(() => null)) as T | null;
    if (!res.ok) {
      const errField =
        body && typeof body === "object" && "error" in body
          ? String((body as Record<string, unknown>).error)
          : `HTTP ${res.status}`;
      throw new Error(`DreamOS API ${path} 失败: ${errField}`);
    }
    return body as T;
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error(`DreamOS API ${path} 超时（${timeoutMs}ms）`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// ============ 客户端 ============

export const dreamos = {
  baseUrl: BASE_URL,

  /** 健康检查 */
  health: () =>
    fetchJson<{ service: string; status: string; version: string }>("/api/v1/health"),

  /** 运行状态 */
  status: () => fetchJson<Record<string, unknown>>("/api/v1/status"),

  /** 能力节点注册表 */
  listNodes: () => fetchJson<Record<string, unknown>>("/api/v1/nodes"),

  /** 只读意图识别（S 层） */
  recognizeIntent: (user_input: string) =>
    fetchJson<Record<string, unknown>>("/api/v1/intent", {
      method: "POST",
      body: JSON.stringify({ user_input }),
    }),

  /** 同步完整编排（降级兜底，生产走 runAsync） */
  run: (payload: DreamOSRunPayload) =>
    fetchJson<DreamOSRunResult>(
      "/api/v1/run",
      { method: "POST", body: JSON.stringify(payload) },
      RUN_TIMEOUT_MS,
    ),

  /** 异步编排：立即返回 cycle_id（S7） */
  runAsync: (payload: DreamOSRunPayload) =>
    fetchJson<DreamOSAsyncResult>("/api/v1/run/async", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** 轮询异步结果（S7） */
  getResult: (cycleId: string) =>
    fetchJson<DreamOSAsyncResult>(`/api/v1/result/${encodeURIComponent(cycleId)}`),
};
