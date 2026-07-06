// Trading Hook - 交易功能React Hook
// 封装交易相关的状态管理和API调用

import { useState, useCallback, useEffect } from 'react';
import { TradeAPI, MarketAPI, IntentAPI, SkillAPI } from './bridge-client';
import { routeIntent, RoutingResult } from './intent-router';

interface Order {
  ord_id: string;
  inst_id: string;
  side: string;
  pos_side: string;
  sz: string;
  px: string;
  state: string;
  timestamp: string;
}

interface Position {
  inst_id: string;
  pos_side: string;
  sz: string;
  avg_px: string;
  pnl: string;
  upl: string;
  leverage: string;
}

interface Balance {
  total_equity: string;
  available: string;
  margin_used: string;
  unrealized_pnl: string;
  currency: string;
}

export function useTrading() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载订单
  const loadOrders = useCallback(async () => {
    try {
      const response = await TradeAPI.getOrders();
      if (response.success) {
        setOrders(response.orders || []);
      }
    } catch (err) {
      console.error('Failed to load orders:', err);
    }
  }, []);

  // 加载持仓
  const loadPositions = useCallback(async () => {
    try {
      const response = await TradeAPI.getPositions();
      if (response.success) {
        setPositions(response.positions || []);
      }
    } catch (err) {
      console.error('Failed to load positions:', err);
    }
  }, []);

  // 加载余额
  const loadBalance = useCallback(async () => {
    try {
      const response = await TradeAPI.getBalance();
      if (response.success) {
        setBalance(response.balance);
      }
    } catch (err) {
      console.error('Failed to load balance:', err);
    }
  }, []);

  // 刷新所有数据
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([loadOrders(), loadPositions(), loadBalance()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [loadOrders, loadPositions, loadBalance]);

  // 下单
  const placeOrder = useCallback(async (params: {
    inst_id: string;
    side: 'buy' | 'sell';
    pos_side: 'long' | 'short' | 'net';
    sz: string;
    px: string;
  }) => {
    setLoading(true);
    setError(null);
    try {
      const response = await TradeAPI.placeOrder(params);
      if (response.success) {
        await loadOrders();
        return response.order;
      } else {
        setError(response.error || 'Order failed');
        return null;
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Order failed';
      setError(msg);
      return null;
    } finally {
      setLoading(false);
    }
  }, [loadOrders]);

  // 取消订单
  const cancelOrder = useCallback(async (orderId: string) => {
    try {
      const response = await TradeAPI.cancelOrder(orderId);
      if (response.success) {
        await loadOrders();
        return true;
      }
      return false;
    } catch (err) {
      console.error('Failed to cancel order:', err);
      return false;
    }
  }, [loadOrders]);

  // 平仓
  const closePosition = useCallback(async (instId: string, posSide?: string) => {
    try {
      const response = await TradeAPI.closePosition(instId, posSide);
      if (response.success) {
        await loadPositions();
        return true;
      }
      return false;
    } catch (err) {
      console.error('Failed to close position:', err);
      return false;
    }
  }, [loadPositions]);

  // 初始加载
  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    orders,
    positions,
    balance,
    loading,
    error,
    placeOrder,
    cancelOrder,
    closePosition,
    refresh,
  };
}

export function useIntentRouter() {
  const [result, setResult] = useState<RoutingResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const route = useCallback(async (text: string) => {
    setLoading(true);
    setError(null);
    try {
      const routingResult = await routeIntent(text);
      setResult(routingResult);
      return routingResult;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Routing failed';
      setError(msg);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return {
    result,
    loading,
    error,
    route,
    clear,
  };
}

export function useMarketData(instId: string = 'BTC-USDT-SWAP') {
  const [ticker, setTicker] = useState<any>(null);
  const [candles, setCandles] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTicker = useCallback(async () => {
    try {
      const response = await MarketAPI.getTicker(instId);
      if (response.success) {
        setTicker(response.data);
      }
    } catch (err) {
      console.error('Failed to load ticker:', err);
    }
  }, [instId]);

  const loadCandles = useCallback(async (bar: string = '1H', limit: number = 100) => {
    setLoading(true);
    try {
      const response = await MarketAPI.getCandles(instId, bar, limit);
      if (response.success) {
        setCandles(response.data || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load candles');
    } finally {
      setLoading(false);
    }
  }, [instId]);

  useEffect(() => {
    loadTicker();
    const interval = setInterval(loadTicker, 30000); // 每30秒刷新
    return () => clearInterval(interval);
  }, [loadTicker]);

  return {
    ticker,
    candles,
    loading,
    error,
    loadTicker,
    loadCandles,
  };
}

export default {
  useTrading,
  useIntentRouter,
  useMarketData,
};
