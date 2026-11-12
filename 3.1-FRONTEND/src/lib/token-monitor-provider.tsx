/**
 * TokenMonitorProvider — Token 监控器全局 Provider
 * ==================================================
 *
 * 在 dashboard 布局中挂载，全局共享唯一 TokenMonitor 实例（单一轮询源）。
 * 任何子组件都可以通过 useTokenMonitorContext 获取监控器状态和方法。
 *
 * 使用方式：
 *   // dashboard/layout.tsx
 *   <TokenMonitorProvider fetchBalance={fetchTokenBalance} config={DEFAULT_TOKEN_MONITOR_CONFIG}>
 *     <App />
 *   </TokenMonitorProvider>
 *
 *   // 子组件
 *   const { state, isDowngraded } = useTokenMonitorContext();
 *   // 或（等价，Provider 内自动复用全局实例）
 *   const { state } = useTokenMonitor({ fetchBalance });
 */

import React, { useContext } from "react";
import { useTokenMonitor, TokenMonitorContext } from "./use-token-monitor";
import type { UseTokenMonitorReturn, UseTokenMonitorOptions } from "./use-token-monitor";
import type { FetchBalanceFn, TokenMonitorConfig } from "./token-monitor";
import api from "./api-client";

/**
 * 全局默认配置（dashboard 级共享）
 *
 * 余额单位是「积分」（prisma.creditsAccount），不是 LLM token。
 * 阈值按积分口径：dailyQuota 作为健康刻度（专业包 5000 积分），
 * 余额 ÷ 5000 得百分比 → <5%（250）严重、<10%（500）偏低、<50%（2500）中等。
 */
export const DEFAULT_TOKEN_MONITOR_CONFIG: TokenMonitorConfig = {
  checkIntervalMs: 5 * 60 * 1000,
  lowBalanceThreshold: 10,
  criticalBalanceThreshold: 5,
  recoveryThreshold: 20,
  consecutiveLowChecks: 2,
  autoDowngradeEnabled: true,
  dailyQuota: 5000,
};

// 余额来自 prisma.creditsAccount（经 /api/token/balance 暴露）；未登录时上层会收到 401 并记录错误
export const fetchTokenBalance: FetchBalanceFn = async () => {
  const data = await api.get<{
    balance: number;
    totalEarned?: number;
    totalSpent?: number;
  }>('/api/token/balance');
  return {
    balance: data?.balance ?? 0,
    totalEarned: data?.totalEarned ?? 0,
    totalSpent: data?.totalSpent ?? 0,
  };
};

export interface TokenMonitorProviderProps extends UseTokenMonitorOptions {
  children: React.ReactNode;
}

export function TokenMonitorProvider({
  children,
  fetchBalance,
  config,
  callbacks,
  autoStart = true,
}: TokenMonitorProviderProps) {
  const monitor = useTokenMonitor({
    fetchBalance,
    config,
    callbacks,
    autoStart,
  });

  return (
    <TokenMonitorContext.Provider value={monitor}>
      {children}
    </TokenMonitorContext.Provider>
  );
}

export function useTokenMonitorContext(): UseTokenMonitorReturn {
  const context = useContext(TokenMonitorContext);
  if (!context) {
    throw new Error(
      "useTokenMonitorContext must be used within a TokenMonitorProvider"
    );
  }
  return context;
}
