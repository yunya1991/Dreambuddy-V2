// SPEC-52 F2 — 产品包状态前端客户端（只读展示；真实门禁在服务端）
import { api } from '@/lib/api-client';

export type EntitlementStatus = 'active' | 'inactive';

export interface ProductEntitlement {
  user_id: string;
  product_id: string;
  status: EntitlementStatus;
  balance_cu: number;
  source: 'env' | 'default';
  updated_at: string;
}

export const product = {
  entitlement: () => api.get<ProductEntitlement>('/api/product/entitlement'),
};

export default product;
