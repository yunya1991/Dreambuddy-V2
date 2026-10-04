'use client';

import { ApiKeyManager } from '@/components/features/settings/ApiKeyManager';
import { TradingParamsPanel } from '@/components/features/settings/TradingParamsPanel';
import { CompletenessWizard } from '@/components/features/settings/CompletenessWizard';
import { ChannelManager } from '@/components/features/settings/ChannelManager';
import { StrategyManager } from '@/components/features/settings/StrategyManager';

export default function SettingsPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">设置</h1>
        <p className="text-xs text-slate-500">API 配置 · 交易参数 · 频道 · 策略 · 完整度向导</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ApiKeyManager />
        <TradingParamsPanel />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ChannelManager />
        <StrategyManager />
      </div>
      <div className="grid grid-cols-1 gap-4">
        <CompletenessWizard />
      </div>
    </div>
  );
}
