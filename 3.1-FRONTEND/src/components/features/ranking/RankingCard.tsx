'use client';

// ============================================
// 榜单卡片 — 排名 + 币种 + 信号 + 置信度 + 决策卡展开
// ============================================

import React, { useState } from 'react';
import Link from 'next/link';
import { V3Card, V3Badge } from '@/components';
import { TradingRankingItem, signalConfig, categoryConfig } from './types';
import { DecisionCard } from './DecisionCard';

interface RankingCardProps {
  item: TradingRankingItem;
}

export function RankingCard({ item }: RankingCardProps) {
  const [expanded, setExpanded] = useState(false);
  const sig = signalConfig[item.signal];
  const cat = categoryConfig[item.category];
  const confPct = (Number(item.confidence) * 100).toFixed(0);

  return (
    <V3Card padding="none" hover>
      {/* 头部：排名 + 币种 + 信号 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 p-3 text-left"
      >
        {/* 排名 */}
        <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold ${
          item.rank <= 3 ? 'bg-amber-500/20 text-amber-400' : 'bg-slate-700/50 text-slate-400'
        }`}>
          {item.rank}
        </div>

        {/* 币种 + 品类 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-slate-200">{item.symbol}</span>
            <span className={`text-[10px] ${cat.color}`}>{cat.label}</span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[10px] text-slate-500">评分 {Number(item.score).toFixed(2)}</span>
            <span className="text-[10px] text-slate-600">|</span>
            <span className="text-[10px] text-slate-500">置信度 {confPct}%</span>
          </div>
        </div>

        {/* 信号 badge */}
        <V3Badge variant={sig.variant} dot={sig.dot} pulse={sig.pulse}>
          {sig.label}
        </V3Badge>

        {/* 展开箭头 */}
        <span className={`text-slate-500 text-xs transition-transform ${expanded ? 'rotate-90' : ''}`}>
          ▶
        </span>
      </button>

      {/* 展开决策卡 */}
      {expanded && (
        <div className="border-t border-slate-700/30 px-3 pb-3">
          <DecisionCard data={item.decisionCard} symbol={item.symbol} />
          {/* 一键入场 */}
          <Link
            href={`/dashboard/trade?symbol=${encodeURIComponent(item.symbol)}&entry=${item.decisionCard.entry.price}&sl=${item.decisionCard.stopLoss}&tp=${item.decisionCard.takeProfit.join(',')}`}
            className="mt-3 flex items-center justify-center gap-1.5 w-full py-2 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 text-xs font-medium transition-colors"
          >
            <span>⚡</span> 一键入场
          </Link>
        </div>
      )}
    </V3Card>
  );
}

export default RankingCard;
