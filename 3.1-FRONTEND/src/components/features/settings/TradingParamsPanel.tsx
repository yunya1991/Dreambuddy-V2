'use client';

import React, { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { useApiConfigStore } from '@/stores';
import { V3Card } from '@/components';
import { V3Button } from '@/components';
import { V3Badge } from '@/components';

export function TradingParamsPanel() {
  const { profile, isLoading } = useApiConfigStore();
  const [saving, setSaving] = useState(false);

  const params = profile?.tradingConfig;

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.put('/api/config/trading-params', { params });
    } catch {
      // 错误处理
    } finally {
      setSaving(false);
    }
  };

  if (!params) {
    return (
      <V3Card title="交易参数" padding="sm">
        <div className="text-center py-8 text-gray-500 text-xs">加载中...</div>
      </V3Card>
    );
  }

  const paramRows = [
    { label: '交易类型', value: params.tradeType },
    { label: '交易模式', value: params.tradeMode },
    { label: '最大杠杆', value: `${params.leverageMax}x` },
    { label: '仓位比例', value: `${params.capitalPercentage}%` },
    { label: '单日亏损限额', value: `${params.dailyLossLimit} USDT` },
    { label: '账户亏损限额', value: `${params.accountLossLimit} USDT` },
    { label: '风险偏好', value: params.riskTolerance },
    { label: '交易状态', value: params.isTradingEnabled ? '启用' : '禁用' },
  ];

  return (
    <V3Card
      title="交易参数"
      actions={
        <V3Button variant="primary" size="sm" onClick={handleSave} loading={saving}>
          保存
        </V3Button>
      }
      padding="sm"
    >
      <div className="space-y-1.5">
        {paramRows.map((row) => (
          <div key={row.label} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800/20">
            <span className="text-xs text-gray-400">{row.label}</span>
            <span className={`text-xs font-medium ${row.label === '交易状态' ? (params.isTradingEnabled ? 'text-emerald-400' : 'text-red-400') : 'text-gray-200'}`}>
              {row.value}
            </span>
          </div>
        ))}
      </div>
      {params.allowedSymbols.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700/20">
          <span className="text-xs text-gray-400 mb-1.5 block">允许交易品种</span>
          <div className="flex flex-wrap gap-1.5">
            {params.allowedSymbols.map((s) => (
              <V3Badge key={s} variant="default">{s}</V3Badge>
            ))}
          </div>
        </div>
      )}
    </V3Card>
  );
}

export default TradingParamsPanel;
