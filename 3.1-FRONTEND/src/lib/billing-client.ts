// SPEC-52 F4/F7 — 用量与 CU 客户端
import { api } from '@/lib/api-client';

export interface CuBalance {
  balance_cu: number;
  base_cu: number;
  spent_cu: number;
  reserved_cu: number;
  unit_price_cny: number;
}

export interface UsageRecord {
  id: string;
  user_id: string;
  product_id: string;
  dimension: string;
  quantity: number;
  cu_cost: number;
  ref: string;
  trace_id: string;
  created_at: string;
}

export interface UsageSummaryData extends CuBalance {
  totals: Record<string, { quantity: number; cu_cost: number }>;
  records: UsageRecord[];
}

export const billing = {
  balance: () => api.get<CuBalance>('/api/billing/balance'),
  usage: (limit = 50) => api.get<UsageSummaryData>(`/api/billing/usage?limit=${limit}`),
};

export default billing;
