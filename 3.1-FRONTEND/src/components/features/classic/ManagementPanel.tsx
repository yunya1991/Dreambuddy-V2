'use client';

import { useState, useEffect, useCallback } from 'react';
import { V3Card } from '@/components';
import { M26_API } from '@/lib/module-api-client';
import { FIELD_LABELS, FIELD_TOOLTIPS, ENUM_LABELS, TIER_COLORS, getNestedValue, formatValue } from './strategy-labels';

export function ManagementPanel() {
  const [health, setHealth] = useState<any>(null);
  const [tab, setTab] = useState<'lib' | 'user'>('user');
  const [tiers, setTiers] = useState<any[]>([]);
  const [strategies, setStrategies] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [tierFilter, setTierFilter] = useState<string | null>(null);
  const [selected, setSelected] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [tierRes, stratRes] = await Promise.all([
      M26_API.libTiers(),
      tab === 'lib' ? M26_API.libStrategies() : M26_API.userStrategies(),
    ]);
    setTiers(tierRes?.tiers || []);
    const items = Array.isArray(stratRes) ? stratRes : (stratRes?.strategies || stratRes?.items || []);
    setStrategies(items);
    setLoading(false);
  }, [tab]);

  useEffect(() => { M26_API.health().then(setHealth); }, []);
  useEffect(() => { load(); }, [load]);

  const showDetail = async (id: string) => {
    setSelected(id);
    if (tab === 'lib') {
      const res = await M26_API.libStrategyDetail(id);
      setDetail(res);
    } else {
      setDetail(strategies.find(s => s.id === id || s.strategy_id === id));
    }
  };

  const cloneStrategy = async (id: string) => {
    await M26_API.userClone(id);
    load();
  };

  const deleteStrategy = async (id: string) => {
    if (confirm('确认删除？')) {
      await M26_API.userDelete(id);
      load();
    }
  };

  const filtered = tierFilter ? strategies.filter(s => (s.tier || s.strategy_tier) === tierFilter) : strategies;

  return (
    <V3Card title="策略管理模块" badge="M26" padding="lg"
      actions={<span className={`text-[10px] px-1.5 py-0.5 rounded-full ${health?.ok ? 'bg-emerald-600/20 text-emerald-400' : 'bg-rose-600/20 text-rose-400'}`}>
        {health?.ok ? 'ONLINE' : 'OFFLINE'}
      </span>}
    >
      <div className="space-y-4">
        <p className="text-xs text-slate-500">中台策略注册表（只读）+ 用户策略空间（CRUD）</p>

        {/* 子切换：中台 / 用户 */}
        <div className="flex gap-1 p-1 rounded-lg bg-slate-900/50 border border-slate-700/30">
          <button onClick={() => setTab('user')}
            className={`flex-1 px-2 py-1 rounded text-[10px] font-medium ${tab === 'user' ? 'bg-cyan-600/20 text-cyan-400' : 'text-slate-500'}`}>
            用户策略
          </button>
          <button onClick={() => setTab('lib')}
            className={`flex-1 px-2 py-1 rounded text-[10px] font-medium ${tab === 'lib' ? 'bg-cyan-600/20 text-cyan-400' : 'text-slate-500'}`}>
            中台注册表
          </button>
        </div>

        {/* Tier 筛选 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <button onClick={() => setTierFilter(null)}
            className={`text-[10px] px-2 py-0.5 rounded-full border ${!tierFilter ? 'bg-cyan-600/20 border-cyan-500/30 text-cyan-400' : 'border-slate-700/30 text-slate-500'}`}>
            全部
          </button>
          {tiers.map(t => (
            <button key={t.tier} onClick={() => setTierFilter(t.tier)}
              className={`text-[10px] px-2 py-0.5 rounded-full border ${tierFilter === t.tier ? 'bg-cyan-600/20 border-cyan-500/30 text-cyan-400' : 'border-slate-700/30 text-slate-500'}`}>
              {t.tier}·{ENUM_LABELS.tier[t.tier] || t.label || '未评级'}
            </button>
          ))}
        </div>

        {/* 策略列表 */}
        {loading ? (
          <div className="text-center py-4 text-xs text-slate-500">加载中...</div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-4 text-xs text-slate-600">暂无策略</div>
        ) : (
          <div className="space-y-1.5 max-h-60 overflow-y-auto">
            {filtered.map((s, i) => {
              const id = s.id || s.strategy_id || `row-${i}`;
              const name = s.name || s.strategy_name || s.title || id;
              const tier = s.tier || s.strategy_tier || '-';
              const family = s.family || '';
              const stage = s.stage || '';
              return (
                <div key={id}
                  className={`flex items-center justify-between p-2 rounded-lg border text-xs cursor-pointer transition-colors ${
                    selected === id ? 'bg-cyan-600/10 border-cyan-500/30' : 'bg-slate-900/30 border-slate-700/20 hover:border-slate-600'
                  }`}
                  onClick={() => showDetail(id)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-slate-300 truncate">{name}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">
                      {(family || stage) && (
                        <>
                          {family && <span className="text-indigo-400/70">{ENUM_LABELS.family[family] || family}</span>}
                          {family && stage && <span className="text-slate-600 mx-1">·</span>}
                          {stage && <span className="text-slate-400/70">{ENUM_LABELS.stage[stage] || stage}</span>}
                        </>
                      )}
                      <span className="text-slate-600 ml-2 font-mono">{id}</span>
                    </div>
                  </div>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ml-2 ${TIER_COLORS[tier] || TIER_COLORS.unrated}`} title={FIELD_TOOLTIPS.tier}>{tier}</span>
                  {tab === 'user' && (
                    <div className="flex gap-1 ml-2" onClick={e => e.stopPropagation()}>
                      <button onClick={() => cloneStrategy(id)} className="text-[10px] text-cyan-500 hover:text-cyan-300">克隆</button>
                      <button onClick={() => deleteStrategy(id)} className="text-[10px] text-rose-500 hover:text-rose-300">删除</button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* 详情 */}
        {detail && (
          <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/30 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500">策略详情</span>
              <button onClick={() => setDetail(null)} className="text-[10px] text-slate-600 hover:text-slate-400">关闭</button>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
              {Object.entries(FIELD_LABELS).map(([key, label]) => {
                const value = getNestedValue(detail, key);
                if (value === undefined || value === null) return null;
                return (
                  <div key={key} className="flex items-center gap-1.5 text-[10px]">
                    <span className="text-slate-500 shrink-0">{label}</span>
                    <span className="text-slate-300 truncate" title={FIELD_TOOLTIPS[key] || ''}>
                      {formatValue(key, value)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </V3Card>
  );
}
