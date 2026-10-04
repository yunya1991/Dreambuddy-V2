// ============================================
// User 域客户端 — 用户域 API
// ============================================

import api from '../../api-client';

export interface UserProfile {
  id: string;
  name: string;
  [key: string]: unknown;
}

export interface Customer {
  id: string;
  [key: string]: unknown;
}

export interface KycInfo {
  status: string;
  [key: string]: unknown;
}

export interface RechargeRequest {
  amount: number;
  [key: string]: unknown;
}

export const userApi = {
  /** 获取当前用户信息 */
  getProfile: () =>
    api.get<UserProfile>('/api/user/me'),

  /** 用户签到（登录记录） */
  signin: (body: unknown) =>
    api.post<{ success: boolean }>('/api/user/signin', body),

  /** 用户每日打卡 */
  checkin: () =>
    api.post<{ success: boolean }>('/api/user/checkin'),

  /** 获取客户信息 */
  getCustomer: () =>
    api.get<Customer>('/api/customer'),

  /** 获取 KYC 信息 */
  getKyc: () =>
    api.get<KycInfo>('/api/kyc'),

  /** 充值 */
  recharge: (body: RechargeRequest) =>
    api.post<{ success: boolean }>('/api/recharge', body),
};
