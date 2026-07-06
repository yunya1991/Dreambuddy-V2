/**
 * useTokenMonitor — Token 监控器 React Hook
 * ==========================================
 *
 * 将 TokenMonitor 封装为 React Hook，方便在组件中使用。
 *
 * 使用方式：
 *   const { state, isDowngraded, checkNow, pause, resume } = useTokenMonitor({
 *     fetchBalance: async () => { ... },
 *     onAutoDowngrade: (state) => { ... },
 *     onAutoRecovery: (state) => { ... },
 *   });
 */

import { useState, useEffect, useRef, useCallback } from "react";
import {
  TokenMonitor,
  type TokenMonitorState,
  type TokenMonitorConfig,
  type TokenMonitorCallbacks,
  type FetchBalanceFn,
} from "./token-monitor";

export interface UseTokenMonitorOptions {
  fetchBalance: FetchBalanceFn;
  config?: Partial<TokenMonitorConfig>;
  callbacks?: TokenMonitorCallbacks;
  /** 是否自动启动监控，默认 true */
  autoStart?: boolean;
}

export interface UseTokenMonitorReturn {
  state: TokenMonitorState;
  isDowngraded: boolean;
  isLowBalance: boolean;
  isCritical: boolean;
  isHealthy: boolean;
  checkNow: () => Promise<void>;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  updateConfig: (config: Partial<TokenMonitorConfig>) => void;
  triggerDowngrade: () => void;
  triggerRecovery: () => void;
}

export function useTokenMonitor(
  options: UseTokenMonitorOptions
): UseTokenMonitorReturn {
  const { fetchBalance, config, callbacks, autoStart = true } = options;

  const [state, setState] = useState<TokenMonitorState>({
    status: "idle",
    balance: 0,
    totalEarned: 0,
    totalSpent: 0,
    level: "healthy",
    lastChecked: 0,
    autoDowngradeEnabled: true,
    isDowngraded: false,
    checkCount: 0,
    consecutiveLowCount: 0,
  });

  const monitorRef = useRef<TokenMonitor | null>(null);
  const callbacksRef = useRef<TokenMonitorCallbacks>(callbacks || {});

  // 保持 callbacks 最新
  useEffect(() => {
    callbacksRef.current = callbacks || {};
    if (monitorRef.current) {
      monitorRef.current.setCallbacks(wrapCallbacks(callbacksRef.current, setState));
    }
  }, [callbacks]);

  // 初始化监控器
  useEffect(() => {
    const wrappedCallbacks = wrapCallbacks(callbacksRef.current, setState);
    const monitor = new TokenMonitor(fetchBalance, config, wrappedCallbacks);
    monitorRef.current = monitor;

    // 初始化状态
    setState(monitor.getState());

    // 自动启动
    if (autoStart) {
      monitor.start();
    }

    return () => {
      monitor.stop();
      monitorRef.current = null;
    };
    // 只在初始化时创建一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 手动检查
  const checkNow = useCallback(async () => {
    if (monitorRef.current) {
      await monitorRef.current.checkNow();
      setState(monitorRef.current.getState());
    }
  }, []);

  // 暂停
  const pause = useCallback(() => {
    if (monitorRef.current) {
      monitorRef.current.pause();
      setState(monitorRef.current.getState());
    }
  }, []);

  // 恢复
  const resume = useCallback(() => {
    if (monitorRef.current) {
      monitorRef.current.resume();
      setState(monitorRef.current.getState());
    }
  }, []);

  // 停止
  const stop = useCallback(() => {
    if (monitorRef.current) {
      monitorRef.current.stop();
      setState(monitorRef.current.getState());
    }
  }, []);

  // 更新配置
  const updateConfig = useCallback((newConfig: Partial<TokenMonitorConfig>) => {
    if (monitorRef.current) {
      monitorRef.current.updateConfig(newConfig);
      setState(monitorRef.current.getState());
    }
  }, []);

  // 手动触发降级（测试用）
  const triggerDowngrade = useCallback(() => {
    if (monitorRef.current) {
      monitorRef.current.triggerDowngrade();
      setState(monitorRef.current.getState());
    }
  }, []);

  // 手动恢复（测试用）
  const triggerRecovery = useCallback(() => {
    if (monitorRef.current) {
      monitorRef.current.triggerRecovery();
      setState(monitorRef.current.getState());
    }
  }, []);

  // 计算派生状态
  const isDowngraded = state.isDowngraded;
  const isLowBalance = state.level === "low" || state.level === "critical";
  const isCritical = state.level === "critical";
  const isHealthy = state.level === "healthy";

  return {
    state,
    isDowngraded,
    isLowBalance,
    isCritical,
    isHealthy,
    checkNow,
    pause,
    resume,
    stop,
    updateConfig,
    triggerDowngrade,
    triggerRecovery,
  };
}

// ============================================================
// 辅助：包装回调，确保每次回调后更新 React 状态
// ============================================================

function wrapCallbacks(
  callbacks: TokenMonitorCallbacks,
  setState: React.Dispatch<React.SetStateAction<TokenMonitorState>>
): TokenMonitorCallbacks {
  const makeWrapper = <K extends keyof TokenMonitorCallbacks>(
    key: K
  ): TokenMonitorCallbacks[K] => {
    const original = callbacks[key];
    return ((...args: any[]) => {
      // 先调用原始回调
      if (original) {
        (original as any)(...args);
      }
      // 最后一个参数通常是 state，用它来更新
      const lastArg = args[args.length - 1];
      if (lastArg && typeof lastArg === "object" && "level" in lastArg) {
        setState({ ...(lastArg as TokenMonitorState) });
      }
    }) as TokenMonitorCallbacks[K];
  };

  return {
    onBalanceChange: makeWrapper("onBalanceChange"),
    onLevelChange: makeWrapper("onLevelChange"),
    onLowBalance: makeWrapper("onLowBalance"),
    onCriticalBalance: makeWrapper("onCriticalBalance"),
    onRecovery: makeWrapper("onRecovery"),
    onAutoDowngrade: makeWrapper("onAutoDowngrade"),
    onAutoRecovery: makeWrapper("onAutoRecovery"),
    onError: makeWrapper("onError"),
  };
}
