// ============================================
// Trade 域客户端 — 交易域 API
// ============================================

import api from '../../api-client';

export interface TradeOrder {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  status: string;
  [key: string]: unknown;
}

export interface Position {
  id: string;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  [key: string]: unknown;
}

export const tradeApi = {
  /** 获取交易订单列表 */
  listOrders: () =>
    api.get<TradeOrder[]>('/api/trade-orders'),

  /** 获取持仓列表 */
  getPositions: () =>
    api.get<Position[]>('/api/positions'),
};
