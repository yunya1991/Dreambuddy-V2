'use client';

// ============================================
// 预填订单 Banner — 从榜单一键入场跳转时显示
// 读取 URL 参数 (symbol/entry/sl/tp) 并展示预填订单
// ============================================

import { useSearchParams } from 'next/navigation';
import { V3Card, V3Badge } from '@/components';

export function PrefillOrderBanner() {
  const searchParams = useSearchParams();
  const symbol = searchParams.get('symbol');
  const entry = searchParams.get('entry');
  const sl = searchParams.get('sl');
  const tp = searchParams.get('tp');

  if (!symbol || !entry) return null;

  const tpList = tp ? tp.split(',').filter(Boolean) : [];

  return (
    <V3Card padding="sm" className="border-indigo-500/30 bg-indigo-500/5">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-200">{symbol}</span>
          <V3Badge variant="info" dot>榜单推荐</V3Badge>
        </div>
        <span className="text-[10px] text-slate-500">来自交易榜单</span>
      </div>
      <div className="grid grid-cols-3 gap-2 mb-2">
        <div className="bg-slate-800/40 rounded p-1.5 text-center">
          <p className="text-[9px] text-slate-500">入场价</p>
          <p className="text-xs font-medium text-slate-200">${Number(entry).toLocaleString()}</p>
        </div>
        <div className="bg-slate-800/40 rounded p-1.5 text-center">
          <p className="text-[9px] text-slate-500">止损</p>
          <p className="text-xs font-medium text-red-400">${Number(sl).toLocaleString()}</p>
        </div>
        <div className="bg-slate-800/40 rounded p-1.5 text-center">
          <p className="text-[9px] text-slate-500">止盈</p>
          <p className="text-xs font-medium text-emerald-400">
            {tpList.length > 0 ? tpList.map(t => `$${Number(t).toLocaleString()}`).join(' / ') : '—'}
          </p>
        </div>
      </div>
      <div className="flex gap-2">
        <button className="flex-1 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 text-xs font-medium transition-colors">
          确认下单
        </button>
        <button className="px-3 py-1.5 rounded-lg bg-slate-800/50 hover:bg-slate-700/50 border border-slate-700/30 text-slate-400 text-xs transition-colors">
          修改
        </button>
      </div>
    </V3Card>
  );
}

export default PrefillOrderBanner;
