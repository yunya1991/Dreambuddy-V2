/**
 * TokenMonitorProvider — Token 监控器全局 Provider
 * ==================================================
 *
 * 在应用根组件中使用，全局共享 TokenMonitor 实例。
 * 任何子组件都可以通过 useTokenMonitorContext 获取监控器状态和方法。
 *
 * 使用方式：
 *   // 根组件
 *   <TokenMonitorProvider fetchBalance={fetchBalance}>
 *     <App />
 *   </TokenMonitorProvider>
 *
 *   // 子组件
 *   const { state, isDowngraded } = useTokenMonitorContext();
 */

import React, { createContext, useContext, useMemo } from "react";
import { useTokenMonitor } from "./use-token-monitor";
import type { UseTokenMonitorReturn, UseTokenMonitorOptions } from "./use-token-monitor";

const TokenMonitorContext = createContext<UseTokenMonitorReturn | null>(null);

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

  const value = useMemo(() => monitor, [monitor]);

  return (
    <TokenMonitorContext.Provider value={value}>
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
