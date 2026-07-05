// ============================================
// v3 API Client — 统一请求封装
// ============================================

const BASE_URL = '';

// === 错误类型 ===
export interface ApiError {
  code: number;
  message: string;
  details?: string;
}

export class ApiException extends Error {
  code: number;
  details?: string;
  constructor(error: ApiError) {
    super(error.message);
    this.code = error.code;
    this.details = error.details;
    this.name = 'ApiException';
  }
}

// === 请求配置 ===
interface RequestOptions extends RequestInit {
  params?: Record<string, string>;
  timeout?: number;
  skipAuth?: boolean;
}

// === 统一响应 ===
interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: ApiError;
}

// === 核心请求方法 ===
async function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, timeout = 30000, headers: customHeaders, ...rest } = options;

  // 构建 URL
  let url = `${BASE_URL}${path}`;
  if (params) {
    const searchParams = new URLSearchParams(params);
    url += `?${searchParams.toString()}`;
  }

  // 合并 Headers
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(customHeaders as Record<string, string>),
  };

  // 超时控制器
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...rest,
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      let errorData: ApiError;
      try {
        errorData = await response.json();
      } catch {
        errorData = { code: response.status, message: `HTTP ${response.status}: ${response.statusText}` };
      }
      throw new ApiException(errorData);
    }

    // 204 No Content
    if (response.status === 204) return undefined as T;

    const data = await response.json();
    // 兼容 { success: true, data: ... } 和直接返回数据两种格式
    if (data && typeof data === 'object' && 'success' in data) {
      const apiResponse = data as ApiResponse<T>;
      if (!apiResponse.success && apiResponse.error) {
        throw new ApiException(apiResponse.error);
      }
      return apiResponse.data as T;
    }
    return data as T;
  } catch (error) {
    if (error instanceof ApiException) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiException({ code: 408, message: '请求超时' });
    }
    throw new ApiException({ code: 0, message: error instanceof Error ? error.message : '未知错误' });
  } finally {
    clearTimeout(timeoutId);
  }
}

// === 便捷方法 ===
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
};

export default api;
