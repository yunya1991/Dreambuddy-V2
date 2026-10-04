// ============================================
// Intent 域客户端 — 意图识别域 API
// ============================================

import api from '../../api-client';

export interface SteerRequest {
  [key: string]: unknown;
}

export const intentApi = {
  /** 意图引导/转向 */
  steer: (body: SteerRequest) =>
    api.post<unknown>('/api/intent/steer', body),
};
