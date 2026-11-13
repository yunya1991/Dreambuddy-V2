// 用户交易场所（51 OKX CLI venue）前端客户端
// SPEC-52 F2/F3 落地：前端/产品专用通道，与后端 11 旁路隔离。
// 所有请求经 /api/venue/* BFF 转发，bridge token 只在服务端使用。

import { api } from '@/lib/api-client';

export interface VenueConfigInfo {
  cli_path: string;
  profile: string;
  mode: 'demo' | 'live';
  auth: string;
  read_allowed: boolean;
  write_allowed: boolean;
  allow_live_write: boolean;
}

export interface VenueLiveState {
  unlocked: boolean;
  expires_in_s: number;
}

export interface VenueCredentialsPublic {
  configured: boolean;
  exchange?: string;
  label?: string;
  demo?: boolean;
  api_key_hint?: string;
  permissions?: string;
  saved_at?: number;
}

export interface VenueCredentialInput {
  api_key: string;
  secret_key: string;
  passphrase: string;
  demo: boolean;
  label?: string;
}

export interface VenueConnectionTest {
  ok: boolean;
  mode: 'demo' | 'live';
  permissions: string;
  balance: number;
  total_eq?: number;
}

export interface VenueHealth {
  bridge: string;
  config: VenueConfigInfo;
  effective_mode: 'demo' | 'live';
  live: VenueLiveState;
  credentials: VenueCredentialsPublic;
  paths?: { dir: string; credential_file: string };
  audit_path: string;
  max_order_size: number;
  quote_currencies: string[];
}

export interface VenueBalance {
  ok: boolean;
  balance: number;
  total_eq?: number;
  ccy: string;
  details?: Array<Record<string, unknown>>;
}

export interface VenuePosition {
  inst_id: string;
  coin: string;
  pos_side: string;
  side: string;
  pos: number;
  avg_px: number;
  mark_px: number;
  upl: number;
}

export interface VenuePositions {
  ok: boolean;
  positions: VenuePosition[];
  count: number;
}

export interface VenueTicker {
  ok: boolean;
  inst_id: string;
  last: number;
  bid?: number;
  ask?: number;
}

export interface OrderIntentInput {
  inst_id: string;
  side: 'buy' | 'sell';
  size: number;
  order_type?: 'market' | 'limit';
  price?: number;
  td_mode?: string;
  pos_side?: string;
  source?: string;
}

export interface VenueOrderIntent {
  id: string;
  inst_id: string;
  side: 'buy' | 'sell';
  size: number;
  order_type: 'market' | 'limit';
  price: number | null;
  mode: 'demo' | 'live';
  status: 'pending' | 'executed' | 'rejected' | 'failed' | 'expired';
  created_at: number;
  expires_at: number;
  risk: {
    max_order_size: number;
    quote: string;
    notional_hint: number | null;
    source: string;
  };
  result?: { order_id?: string; cl_ord_id?: string; s_code?: string; s_msg?: string };
  error?: { code: string; message: string };
}

export interface VenueOrderReceipt {
  intent: VenueOrderIntent;
  order: { order_id?: string; cl_ord_id?: string; s_code?: string; s_msg?: string };
}

export interface VenueAuditRecord {
  ts?: string;
  trace_id?: string;
  operation?: string;
  mode?: string;
  ok?: boolean;
  error_code?: string;
  [key: string]: unknown;
}

export const venue = {
  health: () => api.get<VenueHealth>('/api/venue/health'),
  credentials: () => api.get<VenueCredentialsPublic>('/api/venue/credentials'),
  saveCredentials: (input: VenueCredentialInput) =>
    api.post<VenueCredentialsPublic>('/api/venue/credentials', input),
  deleteCredentials: () => api.delete<VenueCredentialsPublic>('/api/venue/credentials'),
  testCredentials: () => api.post<VenueConnectionTest>('/api/venue/credentials/test'),
  balance: (ccy = 'USDT') => api.get<VenueBalance>('/api/venue/account/balance', { ccy }),
  positions: () => api.get<VenuePositions>('/api/venue/account/positions'),
  ticker: (instId: string) => api.get<VenueTicker>('/api/venue/market/ticker', { inst_id: instId }),
  createIntent: (input: OrderIntentInput) =>
    api.post<VenueOrderIntent>('/api/venue/order-intents', input),
  confirmIntent: (id: string) =>
    api.post<VenueOrderReceipt>(`/api/venue/order-intents/${encodeURIComponent(id)}/confirm`),
  liveStatus: () => api.get<VenueLiveState>('/api/venue/live/status'),
  unlockLive: (phrase: string, ttlS = 1800) =>
    api.post<VenueLiveState>('/api/venue/live/unlock', { phrase, ttl_s: ttlS }),
  lockLive: () => api.post<VenueLiveState>('/api/venue/live/lock'),
  audit: (limit = 20) => api.get<{ records: VenueAuditRecord[]; path: string }>('/api/venue/audit', {
    limit: String(limit),
  }),
};

export default venue;
