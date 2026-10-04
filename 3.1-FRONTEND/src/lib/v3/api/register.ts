// ============================================
// Register 域客户端 — 注册域 API
// ============================================

import api from '../../api-client';

export interface RegisterRequest {
  [key: string]: unknown;
}

export interface RegisterResult {
  success: boolean;
  [key: string]: unknown;
}

export const registerApi = {
  /** 用户注册 */
  register: (body: RegisterRequest) =>
    api.post<RegisterResult>('/api/register', body),
};
