'use client';

import { useState, useCallback } from 'react';
import { useTokenMonitor } from '@/lib/use-token-monitor';
import type { TokenMonitorConfig } from '@/lib/token-monitor';
import { TokenMonitorPanel } from '@/components/features/token-monitor/TokenMonitorPanel';

const DEFAULT_CONFIG: TokenMonitorConfig = {
  checkIntervalMs: 5 * 60 * 1000,
  lowBalanceThreshold: 10,
  criticalBalanceThreshold: 5,
  recoveryThreshold: 20,
  consecutiveLowChecks: 2,
  autoDowngradeEnabled: true,
  dailyQuota: 50000,
};

// Mock fetchBalance —— 实际应调用后端 /api/token/balance
async function fetchBalance() {
  // 模拟网络延迟
  await new Promise((r) => setTimeout(r, 300));
  return {
    balance: 32500,
    totalEarned: 120000,
    totalSpent: 87500,
  };
}

export default function TokenMonitorPage() {
  const [config, setConfig] = useState<TokenMonitorConfig>(DEFAULT_CONFIG);

  const {
    state,
    checkNow,
    pause,
    resume,
    updateConfig,
    triggerDowngrade,
    triggerRecovery,
  } = useTokenMonitor({
    fetchBalance,
    config: DEFAULT_CONFIG,
  });

  const handleUpdateConfig = useCallback(
    (partial: Partial<TokenMonitorConfig>) => {
      updateConfig(partial);
      setConfig((prev) => ({ ...prev, ...partial }));
    },
    [updateConfig]
  );

  return (
    <div className="px-6 py-4 max-w-3xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-1">Token 监控</h1>
      <p className="text-xs text-slate-400 mb-4">
        自动监测 Token 余额，低余额时降级到经典指标系统，充值后自动恢复 AI 驱动
      </p>

      <TokenMonitorPanel
        state={state}
        config={config}
        onCheckNow={checkNow}
        onPause={pause}
        onResume={resume}
        onUpdateConfig={handleUpdateConfig}
        onTriggerDowngrade={triggerDowngrade}
        onTriggerRecovery={triggerRecovery}
      />
    </div>
  );
}
