'use client';

import { useState, useEffect, useCallback } from 'react';
import { V3Card } from '@/components';
import { M25_API } from '@/lib/module-api-client';
import { ENUM_LABELS } from './strategy-labels';

// ===== 基线策略列表 =====
function BaselineList() {
  const [baselines, setBaselines] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await M25_API.baselineList();
    const items = res?.baselines || res?.items || (Array.isArray(res) ? res : []);
    setBaselines(items);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const showDetail = async (id: string) => {
    setSelected(id);
    const res = await M25_API.baselineGet(id);
    setDetail(res);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">基线策略库</span>
        <button onClick={load} className="text-[10px] text-indigo-400 hover:text-indigo-300">刷新</button>
      </div>

      {loading ? (
        <div className="text-center py-4 text-xs text-slate-500">加载中...</div>
      ) : baselines.length === 0 ? (
        <div className="text-center py-4 text-xs text-slate-600">暂无基线策略</div>
      ) : (
        <div className="space-y-1.5">
          {baselines.map((b: any) => (
            <button
              key={b.id || b.strategy_id}
              onClick={() => showDetail(b.id || b.strategy_id)}
              className={`w-full flex items-center justify-between p-2 rounded-lg border text-xs transition-colors ${
                selected === (b.id || b.strategy_id)
                  ? 'bg-indigo-600/10 border-indigo-500/30 text-indigo-300'
                  : 'bg-slate-900/30 border-slate-700/30 text-slate-400 hover:text-slate-300'
              }`}
            >
              <span className="font-mono">{b.id || b.strategy_id || '?'}</span>
              <span className="text-[10px] text-slate-500">{b.tier || b.status || '-'}</span>
            </button>
          ))}
        </div>
      )}

      {detail && (
        <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/30 space-y-2">
          <div className="text-[10px] text-slate-500">基线详情</div>
          <pre className="text-[10px] text-slate-400 font-mono overflow-auto max-h-40">
            {JSON.stringify(detail, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ===== 流水线执行结果 =====
function PipelineResults() {
  const [results, setResults] = useState<any[]>([]);
  const [running, setRunning] = useState(false);
  const [intent, setIntent] = useState('');

  const runPipeline = async () => {
    if (!intent.trim()) return;
    setRunning(true);
    const res = await M25_API.genPipeline(intent);
    setResults(prev => [{ ts: Date.now(), intent, result: res }, ...prev].slice(0, 5));
    setRunning(false);
    setIntent('');
  };

  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-400">流水线执行（生成→回测→对比→评分）</div>

      <div className="flex gap-2">
        <input
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && runPipeline()}
          placeholder="输入策略意图..."
          className="flex-1 px-2.5 py-1.5 rounded-lg bg-slate-900/50 border border-slate-700/50 text-xs text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-indigo-500/50"
        />
        <button
          onClick={runPipeline}
          disabled={running || !intent.trim()}
          className="px-3 py-1.5 rounded-lg bg-indigo-600/20 border border-indigo-500/30 text-xs text-indigo-300 hover:bg-indigo-600/30 disabled:opacity-40"
        >
          {running ? '执行中...' : '执行'}
        </button>
      </div>

      {results.length === 0 ? (
        <div className="text-center py-3 text-xs text-slate-600">暂无执行记录</div>
      ) : (
        <div className="space-y-2">
          {results.map((r, i) => {
            const strat = r.result?.result?.strategy || r.result?.strategy || {};
            const bt = r.result?.result?.backtest?.metrics_summary || r.result?.backtest?.metrics_summary || {};
            const steps = r.result?.result?.steps || r.result?.steps || {};
            return (
            <div key={i} className="p-2.5 rounded-lg bg-slate-900/30 border border-slate-700/20 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-slate-500 font-mono">
                  {new Date(r.ts).toLocaleTimeString()}
                </span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                  r.result?.ok ? 'bg-emerald-600/20 text-emerald-400' : 'bg-rose-600/20 text-rose-400'
                }`}>
                  {r.result?.ok ? 'OK' : 'FAIL'}
                </span>
              </div>
              <div className="text-xs text-slate-400 truncate">{r.intent}</div>

              {/* 策略名称 */}
              {strat.name && (
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="text-slate-500">策略:</span>
                  <span className="text-indigo-300 font-mono">{strat.name}</span>
                  {strat.family && (
                    <span className="text-[9px] text-slate-500">· {ENUM_LABELS.family[strat.family] || strat.family}</span>
                  )}
                  {strat.syntax_valid && (
                    <span className="text-emerald-400">✓语法</span>
                  )}
                  {strat.lookahead_issues?.length === 0 && (
                    <span className="text-emerald-400">✓无未来函数</span>
                  )}
                </div>
              )}

              {/* 回测指标 */}
              {bt.trades > 0 && (
                <div className="flex flex-wrap gap-2 text-[10px]">
                  <span className="text-slate-400" title="回测期间总交易笔数，<30笔统计意义不足">交易:<span className="text-slate-200 ml-1">{bt.trades}</span></span>
                  <span className="text-slate-400" title="盈利交易占总交易比例，>50%为良，趋势策略40%+也可接受">胜率:<span className={`ml-1 ${bt.winrate >= 0.5 ? 'text-emerald-400' : 'text-rose-400'}`}>{(bt.winrate * 100).toFixed(1)}%</span></span>
                  <span className="text-slate-400" title="回测期间总收益率">收益:<span className={`ml-1 ${bt.profit_total_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{bt.profit_total_pct?.toFixed(2)}%</span></span>
                  <span className="text-slate-400" title="从最高点到最低点的最大跌幅，<-20%为高风险">回撤:<span className="text-amber-400 ml-1">{bt.max_drawdown_pct?.toFixed(2)}%</span></span>
                  <span className="text-slate-400" title="风险调整后收益，>1为良，>2为优，<0为亏损">Sharpe:<span className="text-slate-200 ml-1">{bt.sharpe_ratio?.toFixed(2)}</span></span>
                </div>
              )}

              {/* S1-S5 步骤 */}
              {Object.keys(steps).length > 0 && (
                <div className="flex gap-1 flex-wrap mt-1">
                  {Object.entries(steps).map(([s, info]: [string, any]) => (
                    <span key={s} className={`text-[9px] px-1.5 py-0.5 rounded ${
                      info.status === 'done' ? 'bg-emerald-900/30 text-emerald-400' :
                      info.status === 'warning' ? 'bg-amber-900/30 text-amber-400' :
                      'bg-rose-900/30 text-rose-400'
                    }`} title={info.detail}>
                      {s.replace('S', 'S')}
                    </span>
                  ))}
                </div>
              )}
            </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function GenerationPanel() {
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    M25_API.health().then(setHealth);
  }, []);

  return (
    <V3Card title="用户策略生成系统" badge="M25" padding="lg"
      actions={<span className={`text-[10px] px-1.5 py-0.5 rounded-full ${health?.ok ? 'bg-emerald-600/20 text-emerald-400' : 'bg-rose-600/20 text-rose-400'}`}>
        {health?.ok ? 'ONLINE' : 'OFFLINE'}
      </span>}
    >
      <div className="space-y-4">
        <p className="text-xs text-slate-500">用户意图 → AI 生成 → 回测 → 基线对比 → 评分</p>
        <PipelineResults />
        <div className="border-t border-slate-700/30 pt-3">
          <BaselineList />
        </div>
      </div>
    </V3Card>
  );
}
