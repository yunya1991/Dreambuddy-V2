'use client';

import { useState, useEffect, useCallback } from 'react';
import { V3Card } from '@/components';
import { M28_API } from '@/lib/module-api-client';

export function SignalsPanel() {
  const [health, setHealth] = useState<any>(null);
  const [subView, setSubView] = useState<'screen' | 'events'>('events');
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  // 筛选表单
  const [symbols, setSymbols] = useState('BTC,ETH,SOL');
  const [screenResult, setScreenResult] = useState<any>(null);
  const [screening, setScreening] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await M28_API.webhookEvents();
    const items = Array.isArray(res) ? res : (res?.events || res?.items || []);
    setEvents(items);
    setLoading(false);
  }, []);

  useEffect(() => {
    M28_API.health().then(setHealth);
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  const runScreen = async () => {
    setScreening(true);
    const pairs = symbols.split(',').map(s => s.trim()).filter(Boolean);
    // 为每个币种生成简单收盘价序列（实际应由数据源提供）
    const candidates = pairs.map(p => ({
      pair: p.includes('/') ? p : `${p}/USDT`,
      close: Object.fromEntries(Array.from({ length: 30 }, (_, i) => [i + 1, 50000 + Math.random() * 10000])),
    }));
    const btcClose = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [i + 1, 50000 + i * 100]));
    const res = await M28_API.universeScreen(candidates, btcClose, { min: 0.5, max: 1.5 });
    setScreenResult(res);
    setScreening(false);
  };

  return (
    <V3Card title="策略信号触发模块" badge="M28" padding="lg"
      actions={<span className={`text-[10px] px-1.5 py-0.5 rounded-full ${health?.ok ? 'bg-emerald-600/20 text-emerald-400' : 'bg-rose-600/20 text-rose-400'}`}>
        {health?.ok ? 'ONLINE' : 'OFFLINE'}
      </span>}
    >
      <div className="space-y-4">
        <p className="text-xs text-slate-500">代币筛选 + Freqtrade Webhook 事件路由</p>

        {/* 子视图切换 */}
        <div className="flex gap-1 p-1 rounded-lg bg-slate-900/50 border border-slate-700/30">
          <button onClick={() => setSubView('events')}
            className={`flex-1 px-2 py-1 rounded text-[10px] font-medium ${subView === 'events' ? 'bg-amber-600/20 text-amber-400' : 'text-slate-500'}`}>
            Webhook 事件流
          </button>
          <button onClick={() => setSubView('screen')}
            className={`flex-1 px-2 py-1 rounded text-[10px] font-medium ${subView === 'screen' ? 'bg-amber-600/20 text-amber-400' : 'text-slate-500'}`}>
            代币筛选
          </button>
        </div>

        {subView === 'events' ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">实时事件 ({events.length})</span>
              <button onClick={load} className="text-[10px] text-amber-400 hover:text-amber-300">刷新</button>
            </div>
            {loading && events.length === 0 ? (
              <div className="text-center py-4 text-xs text-slate-500">加载中...</div>
            ) : events.length === 0 ? (
              <div className="text-center py-4 text-xs text-slate-600">暂无事件</div>
            ) : (
              <div className="space-y-1 max-h-60 overflow-y-auto">
                {events.slice(0, 20).map((e, i) => (
                  <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-slate-900/30 border border-slate-700/20 text-xs">
                    <div className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${
                      (e.event_type || e.type || '').includes('entry') ? 'bg-emerald-400' :
                      (e.event_type || e.type || '').includes('exit') ? 'bg-rose-400' :
                      (e.event_type || e.type || '').includes('fill') ? 'bg-cyan-400' : 'bg-slate-500'
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-slate-300 font-medium">{e.event_type || e.type || '?'}</span>
                        <span className="text-[10px] text-slate-500">
                          {e.ts ? new Date(typeof e.ts === 'number' ? e.ts * 1000 : e.ts).toLocaleTimeString() : ''}
                        </span>
                      </div>
                      {e.pair && <span className="text-[10px] text-slate-500 font-mono">{e.pair}</span>}
                      {e.strategy && <span className="text-[10px] text-slate-600 ml-1">[{e.strategy}]</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="text-xs text-slate-400">代币筛选（universe/screen）</div>
            <div className="flex gap-2">
              <input value={symbols} onChange={e => setSymbols(e.target.value)}
                placeholder="BTC,ETH,SOL..."
                className="flex-1 px-2.5 py-1.5 rounded-lg bg-slate-900/50 border border-slate-700/50 text-xs text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-amber-500/50"
              />
              <button onClick={runScreen} disabled={screening || !symbols.trim()}
                className="px-3 py-1.5 rounded-lg bg-amber-600/20 border border-amber-500/30 text-xs text-amber-300 hover:bg-amber-600/30 disabled:opacity-40">
                {screening ? '筛选中...' : '筛选'}
              </button>
            </div>

            {screenResult && (
              <div className="space-y-2">
                <div className={`p-2 rounded-lg border text-xs ${
                  screenResult.ok ? 'bg-emerald-600/10 border-emerald-500/30 text-emerald-300' : 'bg-rose-600/10 border-rose-500/30 text-rose-300'
                }`}>
                  {screenResult.ok ? `✓ 筛选完成` : `✗ ${screenResult.error || '失败'}`}
                  {screenResult.stats && ` (通过: ${screenResult.stats.passed || 0}/${screenResult.stats.total || 0})`}
                </div>

                {screenResult.passed && screenResult.passed.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-emerald-500">通过筛选</span>
                    {screenResult.passed.map((p: any, i: number) => (
                      <div key={i} className="flex items-center justify-between p-1.5 rounded bg-emerald-600/5 border border-emerald-500/20 text-xs">
                        <span className="text-slate-300">{p.pair || p.alias || '?'}</span>
                        <span className="text-[10px] text-slate-500">β={p.beta?.toFixed(2) || '-'} ρ={p.corr?.toFixed(2) || '-'}</span>
                      </div>
                    ))}
                  </div>
                )}

                {screenResult.rejected && screenResult.rejected.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-rose-500">被筛掉</span>
                    {screenResult.rejected.map((r: any, i: number) => (
                      <div key={i} className="flex items-center justify-between p-1.5 rounded bg-rose-600/5 border border-rose-500/20 text-xs">
                        <span className="text-slate-400">{r.pair || r.alias || '?'}</span>
                        <span className="text-[10px] text-slate-600">{r.reasons?.join(', ') || '-'}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </V3Card>
  );
}
