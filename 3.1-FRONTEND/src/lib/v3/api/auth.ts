// ============================================
// Auth 域客户端 — 认证域 API
// ============================================
// NextAuth 路由（/api/auth/[...nextauth]），无自定义端点，仅导出常量

import api from '../../api-client';

/** 认证提供者列表 */
export const AUTH_PROVIDERS = ['credentials', 'google', 'github'] as const;

/** NextAuth 路由前缀 */
export const AUTH_BASE_PATH = '/api/auth';

export const authApi = {
  /** 认证提供者（常量，不做实际 HTTP 调用） */
  providers: AUTH_PROVIDERS,

  /** 会话端点（常量，不做实际 HTTP 调用） */
  session: `${AUTH_BASE_PATH}/session`,

  /** 获取会话信息（可选，走 NextAuth 标准 session 端点） */
  getSession: () =>
    api.get<unknown>(`${AUTH_BASE_PATH}/session`),
};
