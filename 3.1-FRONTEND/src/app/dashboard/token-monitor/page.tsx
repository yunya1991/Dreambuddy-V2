'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import {
  useTokenMonitorContext,
  DEFAULT_TOKEN_MONITOR_CONFIG,
} from '@/lib/token-monitor-provider';
import type { TokenMonitorConfig } from '@/lib/token-monitor';
import { TokenMonitorPanel } from '@/components/features/token-monitor/TokenMonitorPanel';

export default function TokenMonitorPage() {
  // 全局单实例（dashboard/layout.tsx 挂载的 TokenMonitorProvider），本页只做展示与配置
  const {
    state,
    isLowBalance,
    isCritical,
    isDowngraded,
    checkNow,
    pause,
    resume,
    updateConfig,
    triggerDowngrade,
    triggerRecovery,
  } = useTokenMonitorContext();

  const needsRecharge = isLowBalance || isCritical || isDowngraded;

  const [config, setConfig] = useState<TokenMonitorConfig>(DEFAULT_TOKEN_MONITOR_CONFIG);

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
        自动监测积分余额，低余额时降级到经典指标系统，充值后自动恢复 AI 驱动
      </p>

      {needsRecharge && (
        <div className="mb-4 flex items-center justify-between rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
          <span className="text-xs text-amber-400">积分不足，AI 能力可能已降级</span>
          <Link
            href="/recharge"
            className="text-xs font-medium text-amber-300 hover:text-amber-200 underline-offset-2 hover:underline"
          >
            去充值 →
          </Link>
        </div>
      )}

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
