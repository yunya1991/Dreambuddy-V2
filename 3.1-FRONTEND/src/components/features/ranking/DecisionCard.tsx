'use client';

// ============================================
// 决策卡 — 7 模块渲染组件
// 入场策略 / 止损止盈 / 事件日历 / 可视化
// 风险分级 / 历史类比 / 逻辑推演
// ============================================

import React, { useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { DecisionCardData, riskConfig } from './types';

// 后端在行情/ATR 数据缺失时会返回 null，渲染必须空值安全（否则整页崩溃）
const fmtPrice = (v: number | null | undefined) =>
  typeof v === 'number' && isFinite(v) ? `$${v.toLocaleString()}` : '待定';
const hasPrice = (v: number | null | undefined): v is number =>
  typeof v === 'number' && isFinite(v);

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

  const risk = riskConfig[data.riskLevel] ?? riskConfig.intermediate;

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
  const [low, high] = entry?.range ?? [null, null];
  const batches = entry?.batches ?? [];
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">当前价格</span>
        <span className="text-sm font-semibold text-slate-200">{fmtPrice(entry?.price)}</span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">入场区间</span>
        <span className="text-xs text-emerald-400">
          {hasPrice(low) && hasPrice(high) ? `${fmtPrice(low)} ~ ${fmtPrice(high)}` : '待定'}
        </span>
      </div>
      <div>
        <p className="text-[10px] text-slate-500 mb-1">分批建仓</p>
        {batches.length === 0 ? (
          <p className="text-[10px] text-slate-600">暂无分批方案，等待入场区间模型输出</p>
        ) : (
          <div className="flex gap-1.5">
            {batches.map((b, i) => (
              <div key={i} className="flex-1 bg-slate-800/60 rounded p-1.5 text-center">
                <p className="text-[10px] text-slate-400">{fmtPrice(b.price)}</p>
                <p className="text-xs font-medium text-slate-200">{(b.ratio * 100).toFixed(0)}%</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---- 模块 2: 止损止盈 ----
function SlTpModule({ data }: { data: DecisionCardData }) {
  const targets = data.takeProfit ?? [];
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">止损位</span>
        <V3Badge variant="danger">{fmtPrice(data.stopLoss)}</V3Badge>
      </div>
      <div>
        <p className="text-[10px] text-slate-500 mb-1">止盈目标</p>
        {targets.length === 0 ? (
          <p className="text-[10px] text-slate-600">待定，等待 ATR 波动率模型输出</p>
        ) : (
          <div className="flex gap-1.5">
            {targets.map((tp, i) => (
              <div key={i} className="flex-1 bg-slate-800/60 rounded p-1.5 text-center">
                <p className="text-[9px] text-slate-500">TP{i + 1}</p>
                <p className="text-xs font-medium text-emerald-400">{fmtPrice(tp)}</p>
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="text-[10px] text-slate-500 italic">基于 ATR 波动率自适应计算</p>
    </div>
  );
}

// ---- 模块 3: 事件日历 ----
function EventsModule({ data }: { data: DecisionCardData }) {
  if (!data.events?.length) {
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
  // 入场价/止损任一缺失时无法定位坐标轴，直接降级为文案，避免 NaN/空指针
  if (!hasPrice(entry?.price) || !hasPrice(stopLoss)) {
    return (
      <p className="text-[10px] text-slate-500 text-center py-6">
        {symbol} 行情或止损数据不足，暂无可视化
      </p>
    );
  }
  const low = hasPrice(entry.range?.[0]) ? entry.range[0] : entry.price;
  const high = hasPrice(entry.range?.[1]) ? entry.range[1] : entry.price;
  const targets = (takeProfit ?? []).filter(hasPrice);
  const all = [stopLoss, low, entry.price, high, ...targets];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min;
  const pad = range * 0.1;
  const chartMin = min - pad;
  const chartMax = max + pad;
  const chartRange = chartMax - chartMin;
  if (!isFinite(chartRange) || chartRange <= 0) {
    return <p className="text-[10px] text-slate-500 text-center py-6">{symbol} 价位数据不足，暂无可视化</p>;
  }

  const pct = (v: number) => ((v - chartMin) / chartRange) * 100;

  const entryLowPct = pct(low);
  const entryHighPct = pct(high);
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
        <PriceLine pct={pct(entry.price)} color="bg-slate-300" label={`入场 ${fmtPrice(entry.price)}`} />
        {/* 止损 */}
        <PriceLine pct={slPct} color="bg-red-400" label={`止损 ${fmtPrice(stopLoss)}`} />
        {/* 止盈 */}
        {targets.map((tp, i) => (
          <PriceLine key={i} pct={pct(tp)} color="bg-emerald-400" label={`TP${i + 1} ${fmtPrice(tp)}`} />
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
  const confPct = (Number(logic?.confidence ?? 0) * 100).toFixed(0);
  const bullish = logic?.bullish ?? [];
  const bearish = logic?.bearish ?? [];
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
          {bullish.map((b, i) => (
            <li key={i} className="text-[11px] text-slate-300 flex gap-1">
              <span className="text-emerald-500">+</span>{b}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-[10px] text-red-400 mb-1">看空逻辑</p>
        <ul className="space-y-0.5">
          {bearish.map((b, i) => (
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
