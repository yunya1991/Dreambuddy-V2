'use client';

import React from 'react';
import { ApiKeyManager } from '@/components/features/settings/ApiKeyManager';
import { TradingParamsPanel } from '@/components/features/settings/TradingParamsPanel';

export default function SettingsPage() {
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <h1 className="text-lg font-semibold text-gray-100">系统设置</h1>
      <ApiKeyManager />
      <TradingParamsPanel />
    </div>
  );
}
