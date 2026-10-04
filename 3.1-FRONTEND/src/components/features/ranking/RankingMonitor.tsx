'use client';

// ============================================
// 监控指标看板 — 推送/转化/弃单/满意度等
// ============================================

import React from 'react';
import { V3Card, V3Badge } from '@/components';
import { RankingMonitorMetrics } from './types';

interface RankingMonitorProps {
  metrics: RankingMonitorMetrics;
}

export function RankingMonitor({ metrics }: RankingMonitorProps) {
  const cards = [
    {
      label: '满意度',
      value: metrics.satisfaction != null ? `${metrics.satisfaction.toFixed(1)}★` : '—',
      desc: '用户评分 1-5',
      variant: 'success' as const,
    },
    {
      label: '转化率',
      value: metrics.conversionRate != null ? `${(metrics.conversionRate * 100).toFixed(1)}%` : '—',
      desc: '点击→下单',
      variant: 'info' as const,
    },
    {
      label: '弃单率',
      value: metrics.abandonRate != null ? `${(metrics.abandonRate * 100).toFixed(1)}%` : '—',
      desc: '点击未下单',
      variant: 'danger' as const,
    },
    {
      label: '推送到达率',
      value: metrics.pushReachRate != null ? `${(metrics.pushReachRate * 100).toFixed(1)}%` : '—',
      desc: '成功送达',
      variant: 'success' as const,
    },
    {
      label: '退订率',
      value: metrics.unsubscribeRate != null ? `${(metrics.unsubscribeRate * 100).toFixed(2)}%` : '—',
      desc: '取消订阅',
      variant: 'warning' as const,
    },
    {
      label: 'MATU',
      value: metrics.matu != null ? metrics.matu.toLocaleString() : '—',
      desc: '月活跃交易用户',
      variant: 'info' as const,
    },
    {
      label: 'K 因子',
      value: metrics.kFactor != null ? metrics.kFactor.toFixed(2) : '—',
      desc: '裂变系数 >1 增长',
      variant: (metrics.kFactor != null && metrics.kFactor > 1 ? 'success' : 'default') as 'success' | 'default',
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-slate-400">数据监控</h3>
        <span className="text-[10px] text-slate-600">{metrics.date}</span>
      </div>
      <div className="grid grid-cols-4 gap-2">
        {cards.map(c => (
          <V3Card key={c.label} padding="sm">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-slate-500">{c.label}</span>
              <V3Badge variant={c.variant}>{c.value}</V3Badge>
            </div>
            <p className="text-[9px] text-slate-600">{c.desc}</p>
          </V3Card>
        ))}
      </div>
    </div>
  );
}

export default RankingMonitor;
