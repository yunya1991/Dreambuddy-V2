import { create } from "zustand";
import type { TokenLevel, MonitorStatus } from "@/lib/token-monitor";

interface CreditsState {
  balance: number;
  totalEarned: number;
  totalSpent: number;
  isLoading: boolean;

  // Token 监控器相关状态
  monitorStatus: MonitorStatus;
  tokenLevel: TokenLevel;
  lastChecked: number;
  isDowngraded: boolean;
  downgradedAt?: number;
  autoDowngradeEnabled: boolean;
  lastError?: string;

  setBalance: (balance: number, totalEarned: number, totalSpent: number) => void;
  deduct: (amount: number) => void;
  add: (amount: number) => void;
  setLoading: (loading: boolean) => void;

  // Token 监控器相关方法
  setMonitorStatus: (status: MonitorStatus) => void;
  setTokenLevel: (level: TokenLevel) => void;
  setDowngraded: (isDowngraded: boolean, downgradedAt?: number) => void;
  setAutoDowngradeEnabled: (enabled: boolean) => void;
  setLastError: (error?: string) => void;
  updateLastChecked: () => void;
}

export const useCreditsStore = create<CreditsState>((set) => ({
  balance: 0,
  totalEarned: 0,
  totalSpent: 0,
  isLoading: false,

  monitorStatus: "idle",
  tokenLevel: "healthy",
  lastChecked: 0,
  isDowngraded: false,
  autoDowngradeEnabled: true,

  setBalance: (balance, totalEarned, totalSpent) =>
    set({ balance, totalEarned, totalSpent, isLoading: false }),

  deduct: (amount) =>
    set((state) => ({
      balance: state.balance - amount,
      totalSpent: state.totalSpent + amount,
    })),

  add: (amount) =>
    set((state) => ({
      balance: state.balance + amount,
      totalEarned: state.totalEarned + amount,
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  // Token 监控器相关
  setMonitorStatus: (status) => set({ monitorStatus: status }),
  setTokenLevel: (level) => set({ tokenLevel: level }),
  setDowngraded: (isDowngraded, downgradedAt) =>
    set({ isDowngraded, downgradedAt: downgradedAt ?? Date.now() }),
  setAutoDowngradeEnabled: (enabled) => set({ autoDowngradeEnabled: enabled }),
  setLastError: (error) => set({ lastError: error }),
  updateLastChecked: () => set({ lastChecked: Date.now() }),
}));
