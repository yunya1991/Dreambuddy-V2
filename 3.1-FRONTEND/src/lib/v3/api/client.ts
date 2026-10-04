// ============================================
// ApiClient 基类 — 封装统一请求方法
// ============================================
// 基于 api-client.ts 的 api 对象，提供类型安全的 HTTP 方法封装。
// 各域客户端可继承此类或直接使用 api 对象。

import api from '../../api-client';

// 重导出错误类型
export type { ApiError } from '../../api-client';
export { ApiException } from '../../api-client';

/**
 * ApiClient 基类
 * 封装 api-client 的 api 对象，提供 get/post/put/patch/delete 方法
 */
export class ApiClient {
  /** GET 请求 */
  get<T = unknown>(path: string, params?: Record<string, string>) {
    return api.get<T>(path, params);
  }

  /** POST 请求 */
  post<T = unknown>(path: string, body?: unknown) {
    return api.post<T>(path, body);
  }

  /** PUT 请求 */
  put<T = unknown>(path: string, body?: unknown) {
    return api.put<T>(path, body);
  }

  /** PATCH 请求 */
  patch<T = unknown>(path: string, body?: unknown) {
    return api.patch<T>(path, body);
  }

  /** DELETE 请求 */
  delete<T = unknown>(path: string, body?: unknown) {
    return api.delete<T>(path, body);
  }
}

export default ApiClient;
