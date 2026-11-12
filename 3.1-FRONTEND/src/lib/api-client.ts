// ============================================
// API Client — 统一信封 + 三形态向后兼容
// SPEC C §3.1 / §3.2 / §3.7 — T-C2 / T-C7
//
// 服务端响应并存 3 形态，本客户端全兼容：
//   ① { success: boolean, data?: T, error?: ApiError, trace_id?, version? } — 规范信封
//   ② { ok: boolean, data?: T, error? } — 旧 ok/error 信封（agent/plan degraded、market/yahoo）
//   ③ 裸 JSON — 旧路由直接返回数据
// 对外 api.get/post/put/patch/delete 签名零改动，向后兼容 35 个消费者。
// ============================================

const BASE_URL = '';

// === 标准错误码 ===
export const ERROR_CODE = {
  AUTH_REQUIRED: 401,
  NOT_FOUND: 404,
  VALIDATION_FAILED: 422,
  RATE_LIMITED: 429,
  UPSTREAM_TIMEOUT: 504,
  UPSTREAM_ERROR: 502,
  INTERNAL: 500,
  TIMEOUT: 408,
  UNKNOWN: 0,
} as const;

export type ErrorCode = (typeof ERROR_CODE)[keyof typeof ERROR_CODE] | number;

// === 错误类型 ===
export interface ApiError {
  code: number;
  message: string;
  details?: string;
}

export class ApiException extends Error {
  code: number;
  details?: string;
  traceId?: string;
  constructor(error: ApiError & { traceId?: string }) {
    super(error.message);
    this.code = error.code;
    this.details = error.details;
    this.traceId = error.traceId;
    this.name = 'ApiException';
  }
}

// === 信封类型（SPEC C §3.1） ===
export interface ApiEnvelope<T = unknown> {
  success: boolean;
  data?: T;
  error?: ApiError;
  trace_id?: string;
  version?: string;
}

// === 请求配置 ===
interface RequestOptions extends RequestInit {
  params?: Record<string, string>;
  timeout?: number;
  skipAuth?: boolean;
  /** 调用方指定的链路 ID；缺省自动生成。会作为 X-Request-Id 发出（GAP-2 trace_id 透传） */
  traceId?: string;
}

// === URL 去重 warn（避免裸 JSON 路由每请求刷屏） ===
const warnedBareUrls = new Set<string>();
function warnOnce(url: string, msg: string) {
  if (warnedBareUrls.has(url)) return;
  warnedBareUrls.add(url);
  // eslint-disable-next-line no-console
  console.warn(`[api-client] ${msg}: ${url}`);
}

// === HTTP → 标准错误码映射 ===
function mapHttpStatusToCode(status: number): number {
  switch (status) {
    case 401: return ERROR_CODE.AUTH_REQUIRED;
    case 404: return ERROR_CODE.NOT_FOUND;
    case 422: return ERROR_CODE.VALIDATION_FAILED;
    case 429: return ERROR_CODE.RATE_LIMITED;
    case 504: return ERROR_CODE.UPSTREAM_TIMEOUT;
    default:
      if (status >= 500) return ERROR_CODE.UPSTREAM_ERROR;
      return status;
  }
}

function generateTraceId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `trace_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

// === 核心请求方法（返回完整信封） ===
async function requestEnvelope<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiEnvelope<T>> {
  const {
    params,
    timeout = 30000,
    headers: customHeaders,
    traceId: callerTraceId,
    signal: externalSignal,
    ...rest
  } = options;

  let url = `${BASE_URL}${path}`;
  if (params) {
    const searchParams = new URLSearchParams(params);
    url += `?${searchParams.toString()}`;
  }

  // 链路 ID：调用方指定优先，否则本地生成；必须随请求发出，服务端才能原样回显（GAP-2 全链透传）
  const requestTraceId = callerTraceId ?? generateTraceId();

  // 自动注入版本头 + 链路头（SPEC C §3.7）
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-API-Version': '1',
    ...(customHeaders as Record<string, string>),
  };
  if (!headers['X-Request-Id'] && !headers['x-request-id']) {
    headers['X-Request-Id'] = requestTraceId;
  }

  const controller = new AbortController();
  let abortedByCaller = false;
  // 调用方 signal（如组件卸载）与内部超时共用同一个 fetch signal
  const onExternalAbort = () => {
    abortedByCaller = true;
    controller.abort();
  };
  if (externalSignal) {
    if (externalSignal.aborted) onExternalAbort();
    else externalSignal.addEventListener('abort', onExternalAbort);
  }
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...rest,
      headers,
      signal: controller.signal,
    });

    const traceId =
      response.headers.get('X-Request-Id') ??
      response.headers.get('X-Trace-Id') ??
      requestTraceId;
    const version = response.headers.get('X-API-Version') ?? 'legacy';
    if (version === 'legacy') warnOnce(url, '服务端未返回 X-API-Version（legacy）');

    if (!response.ok) {
      let errorData: ApiError;
      try {
        const body = await response.json();
        // 404 某些路由返回 { success:false, error:"xxx" }
        if (body && typeof body === 'object' && 'error' in body && typeof body.error === 'object') {
          const e = body.error as ApiError;
          errorData = { code: e.code ?? mapHttpStatusToCode(response.status), message: e.message ?? response.statusText, details: e.details };
        } else if (body && typeof body === 'object' && typeof (body as { error?: unknown }).error === 'string') {
          errorData = { code: mapHttpStatusToCode(response.status), message: (body as { error: string }).error };
        } else {
          errorData = { code: mapHttpStatusToCode(response.status), message: `HTTP ${response.status}: ${response.statusText}` };
        }
      } catch {
        errorData = { code: mapHttpStatusToCode(response.status), message: `HTTP ${response.status}: ${response.statusText}` };
      }
      throw new ApiException({ ...errorData, traceId });
    }

    if (response.status === 204) {
      return { success: true, data: undefined as unknown as T, trace_id: traceId, version };
    }

    const body = await response.json();

    // 形态 ①: 规范信封 —— 有 success 字段
    if (body && typeof body === 'object' && 'success' in body) {
      const envelope = body as ApiEnvelope<T>;
      if (!envelope.success) {
        const err = envelope.error ?? { code: ERROR_CODE.INTERNAL, message: (envelope as unknown as { error?: string }).error ?? '请求失败' };
        throw new ApiException({ ...err, traceId });
      }
      return {
        success: true,
        data: envelope.data as T,
        trace_id: traceId,
        version,
      };
    }

    // 形态 ②: 旧 ok 信封（agent/plan degraded、market/yahoo）
    if (body && typeof body === 'object' && 'ok' in body && !('success' in body)) {
      const okEnvelope = body as { ok: boolean; data?: T; error?: unknown };
      if (!okEnvelope.ok) {
        const msg = typeof okEnvelope.error === 'string' ? okEnvelope.error : '请求失败';
        throw new ApiException({ code: ERROR_CODE.INTERNAL, message: msg, traceId });
      }
      // ok:true → data 可能在 data 字段或整个 body（部分路由 ok:true 后直接 data 在 body 顶层）
      const data = okEnvelope.data !== undefined ? okEnvelope.data : (body as unknown as T);
      warnOnce(url, '服务端返回 ok 信封（非 success），已自动兼容');
      return { success: true, data: data as T, trace_id: traceId, version };
    }

    // 形态 ③: 裸 JSON —— 自动包装
    warnOnce(url, '服务端返回裸 JSON（非信封），已自动包装');
    return { success: true, data: body as T, trace_id: traceId, version };
  } catch (error) {
    if (error instanceof ApiException) throw error;
    if (abortedByCaller) {
      throw new ApiException({ code: ERROR_CODE.TIMEOUT, message: '请求已取消', traceId: requestTraceId });
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiException({ code: ERROR_CODE.UPSTREAM_TIMEOUT, message: '请求超时', traceId: requestTraceId });
    }
    throw new ApiException({ code: ERROR_CODE.INTERNAL, message: error instanceof Error ? error.message : '未知错误', traceId: requestTraceId });
  } finally {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener('abort', onExternalAbort);
  }
}

// === 便捷方法（只返回 data，签名零改动） ===
function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  return requestEnvelope<T>(path, options).then((env) => env.data as T);
}

export const api = {
  get: <T = unknown>(path: string, params?: Record<string, string>, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET', params }),

  post: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body: body ? JSON.stringify(body) : undefined }),

  put: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PUT', body: body ? JSON.stringify(body) : undefined }),

  patch: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),

  delete: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE', body: body ? JSON.stringify(body) : undefined }),

  /** 高级：拿完整信封（含 trace_id / version / error） */
  envelope: <T = unknown>(path: string, options: RequestOptions = {}) =>
    requestEnvelope<T>(path, options),
};

export default api;
