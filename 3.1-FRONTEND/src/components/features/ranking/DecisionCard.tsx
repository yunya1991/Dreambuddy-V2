'use client';

// ============================================
// 决策卡 — 7 模块渲染组件
// 入场策略 / 止损止盈 / 事件日历 / 可视化
// 风险分级 / 历史类比 / 逻辑推演
// ============================================

import React, { useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { DecisionCardData, riskConfig } from './types';

interface DecisionCardProps {
  data: DecisionCardData;
  symbol: string;
}

export function DecisionCard({ data, symbol }: DecisionCardProps) {
  const [activeTab, setActiveTab] = useState<'entry' | 'sl-tp' | 'events' | 'chart' | 'risk' | 'history' | 'logic'>('entry');

  const tabs = [
    { key: 'entry' as const, label: '入场', icon: '→' },
    { key: 'sl-tp' as const, label: '止损止盈', icon: '⊕' },
    { key: 'events' as const, label: '事件', icon: '📅' },
    { key: 'chart' as const, label: '可视化', icon: '▣' },
    { key: 'risk' as const, label: '风险', icon: '⚠' },
    { key: 'history' as const, label: '类比', icon: '⟲' },
    { key: 'logic' as const, label: '推演', icon: '∝' },
  ];

  const risk = riskConfig[data.riskLevel];

  return (
    <div className="mt-2">
      {/* Tab 栏 */}
      <div className="flex gap-1 flex-wrap mb-2">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
              activeTab === t.key
                ? 'bg-slate-700 text-slate-100'
                : 'bg-slate-800/50 text-slate-500 hover:text-slate-300'
            }`}
          >
            <span className="mr-0.5">{t.icon}</span>{t.label}
          </button>
        ))}
      </div>

      {/* 模块内容 */}
      <div className="bg-slate-900/40 rounded-lg p-3">
        {activeTab === 'entry' && <EntryModule data={data} />}
        {activeTab === 'sl-tp' && <SlTpModule data={data} />}
        {activeTab === 'events' && <EventsModule data={data} />}
        {activeTab === 'chart' && <ChartModule data={data} symbol={symbol} />}
        {activeTab === 'risk' && <RiskModule risk={risk} />}
        {activeTab === 'history' && <HistoryModule text={data.historicalAnalogy} />}
        {activeTab === 'logic' && <LogicModule data={data} />}
      </div>
    </div>
  );
}

// ---- 模块 1: 入场策略 ----
function EntryModule({ data }: { data: DecisionCardData }) {
  const { entry } = data;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">当前价格</span>
        <span className="text-sm font-semibold text-slate-200">${entry.price.toLocaleString()}</span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">入场区间</span>
        <span className="text-xs text-emerald-400">
          ${entry.range[0].toLocaleString()} ~ ${entry.range[1].toLocaleString()}
        </span>
      </div>
      <div>
        <p className="text-[10px] text-slate-500 mb-1">分批建仓</p>
        <div className="flex gap-1.5">
          {entry.batches.map((b, i) => (
            <div key={i} className="flex-1 bg-slate-800/60 rounded p-1.5 text-center">
              <p className="text-[10px] text-slate-400">${b.price.toLocaleString()}</p>
              <p className="text-xs font-medium text-slate-200">{(b.ratio * 100).toFixed(0)}%</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---- 模块 2: 止损止盈 ----
function SlTpModule({ data }: { data: DecisionCardData }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">止损位</span>
        <V3Badge variant="danger">${data.stopLoss.toLocaleString()}</V3Badge>
      </div>
      <div>
        <p className="text-[10px] text-slate-500 mb-1">止盈目标</p>
        <div className="flex gap-1.5">
          {data.takeProfit.map((tp, i) => (
            <div key={i} className="flex-1 bg-slate-800/60 rounded p-1.5 text-center">
              <p className="text-[9px] text-slate-500">TP{i + 1}</p>
              <p className="text-xs font-medium text-emerald-400">${tp.toLocaleString()}</p>
            </div>
          ))}
        </div>
      </div>
      <p className="text-[10px] text-slate-500 italic">基于 ATR 波动率自适应计算</p>
    </div>
  );
}

// ---- 模块 3: 事件日历 ----
function EventsModule({ data }: { data: DecisionCardData }) {
  if (!data.events.length) {
    return <p className="text-[10px] text-slate-500 text-center py-4">近期无重大事件</p>;
  }
  return (
    <div className="space-y-1.5">
      {data.events.map((e, i) => (
        <div key={i} className="flex items-center gap-2 bg-slate-800/40 rounded p-2">
          <span className="text-[10px] text-slate-400 font-mono w-20">{e.date}</span>
          <span className="text-xs text-slate-200 flex-1">{e.name}</span>
          <V3Badge variant={e.impact === '高' ? 'danger' : e.impact === '中' ? 'warning' : 'default'}>
            {e.impact}
          </V3Badge>
        </div>
      ))}
    </div>
  );
}

// ---- 模块 4: 可视化 ----
function ChartModule({ data, symbol }: { data: DecisionCardData; symbol: string }) {
  const { entry, stopLoss, takeProfit } = data;
  const all = [stopLoss, entry.range[0], entry.price, entry.range[1], ...takeProfit];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min;
  const pad = range * 0.1;
  const chartMin = min - pad;
  const chartMax = max + pad;
  const chartRange = chartMax - chartMin;

  const pct = (v: number) => ((v - chartMin) / chartRange) * 100;

  const entryLowPct = pct(entry.range[0]);
  const entryHighPct = pct(entry.range[1]);
  const slPct = pct(stopLoss);

  return (
    <div>
      <p className="text-[10px] text-slate-500 mb-2">{symbol} — 关键价位标注</p>
      <div className="relative h-40 bg-slate-800/30 rounded-lg overflow-hidden">
        {/* 入场区间 band */}
        <div
          className="absolute left-0 right-0 bg-emerald-500/15 border-y border-emerald-500/30"
          style={{ bottom: `${entryLowPct}%`, height: `${entryHighPct - entryLowPct}%` }}
        />
        {/* 入场价 */}
        <PriceLine pct={pct(entry.price)} color="bg-slate-300" label={`入场 $${entry.price.toLocaleString()}`} />
        {/* 止损 */}
        <PriceLine pct={slPct} color="bg-red-400" label={`止损 $${stopLoss.toLocaleString()}`} />
        {/* 止盈 */}
        {takeProfit.map((tp, i) => (
          <PriceLine key={i} pct={pct(tp)} color="bg-emerald-400" label={`TP${i + 1} $${tp.toLocaleString()}`} />
        ))}
      </div>
      <div className="flex justify-between mt-1">
        <span className="text-[9px] text-slate-600">${chartMin.toFixed(0)}</span>
        <span className="text-[9px] text-slate-600">${chartMax.toFixed(0)}</span>
      </div>
    </div>
  );
}

function PriceLine({ pct, color, label }: { pct: number; color: string; label: string }) {
  return (
    <div className="absolute left-0 right-0 flex items-center" style={{ bottom: `${pct}%` }}>
      <div className={`h-px ${color} flex-1`} />
      <span className={`text-[9px] ml-1 px-1 rounded ${color.replace('bg-', 'text-')} bg-slate-900/80`}>
        {label}
      </span>
    </div>
  );
}

// ---- 模块 5: 风险分级 ----
function RiskModule({ risk }: { risk: { label: string; variant: 'info' | 'warning' | 'danger'; position: string } }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">风险分级</span>
        <V3Badge variant={risk.variant} dot>{risk.label}</V3Badge>
      </div>
      <div className="bg-slate-800/40 rounded p-2">
        <p className="text-[10px] text-slate-400">{risk.position}</p>
      </div>
      <p className="text-[10px] text-slate-500 italic">
        分级依据：波动率 + 流动性 + 市场复杂度
      </p>
    </div>
  );
}

// ---- 模块 6: 历史类比 ----
function HistoryModule({ text }: { text: string }) {
  return (
    <div className="space-y-2">
      <p className="text-[10px] text-slate-500">相似历史行情</p>
      <p className="text-xs text-slate-300 leading-relaxed">{text}</p>
    </div>
  );
}

// ---- 模块 7: 逻辑推演 ----
function LogicModule({ data }: { data: DecisionCardData }) {
  const { logic } = data;
  const confPct = (Number(logic.confidence) * 100).toFixed(0);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">置信度</span>
        <div className="flex items-center gap-2">
          <div className="w-20 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${confPct}%` }} />
          </div>
          <span className="text-[10px] text-slate-300">{confPct}%</span>
        </div>
      </div>
      <div>
        <p className="text-[10px] text-emerald-400 mb-1">看多逻辑</p>
        <ul className="space-y-0.5">
          {logic.bullish.map((b, i) => (
            <li key={i} className="text-[11px] text-slate-300 flex gap-1">
              <span className="text-emerald-500">+</span>{b}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-[10px] text-red-400 mb-1">看空逻辑</p>
        <ul className="space-y-0.5">
          {logic.bearish.map((b, i) => (
            <li key={i} className="text-[11px] text-slate-300 flex gap-1">
              <span className="text-red-500">−</span>{b}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default DecisionCard;
