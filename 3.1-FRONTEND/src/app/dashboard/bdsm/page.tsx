'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import BdsmAPI, {
  BdsmSnapshot,
  BdsmCoinEntry,
  SectorWaterline,
  SectorValuationSummary,
} from '@/lib/bdsm-api';

/**
 * BDSM 独立页面 — 完整展示每日快照
 *
 * 数据源：http://127.0.0.1:8765/api/bdsm/snapshot
 * 路由：/dashboard/bdsm
 *
 * 展示 §6 sector_valuation 全字段：
 *   1. 赛道估值概览（sector_valuation_summary）
 *      - 过热赛道列表
 *      - 全赛道水位表
 *      - Top 机会币
 *   2. 全币种巡检表（含 sector_waterline / multi_dim_valuation / overheat_signal）
 *   3. 低估伙伴候选合并视图（undervalued_peers 跨币合并去重）
 */

const REFRESH_INTERVAL_MS = 60_000; // 60s 自动刷新

export default function BdsmPage() {
  const [snapshot, setSnapshot] = useState<BdsmSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  const fetchSnapshot = useCallback(async () => {
    try {
      setError(null);
      const data = await BdsmAPI.fetchSnapshot();
      setSnapshot(data);
      setLastFetch(new Date());
    } catch (e: any) {
      setError(e?.message || '获取 BDSM 快照失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshot();
    const id = setInterval(fetchSnapshot, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchSnapshot]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        {/* 顶部导航 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              href="/dashboard"
              className="text-slate-400 hover:text-slate-200 text-sm"
            >
              ← 仪表盘
            </Link>
            <h1 className="text-xl font-bold text-slate-100">BDSM 每日快照</h1>
            {snapshot?.snapshot_date && (
              <span className="text-xs text-slate-500 font-mono">
                {snapshot.snapshot_date}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {lastFetch && (
              <span>更新于 {lastFetch.toLocaleTimeString('zh-CN')}</span>
            )}
            <button
              onClick={fetchSnapshot}
              disabled={loading}
              className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200"
            >
              {loading ? '加载中…' : '刷新'}
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm text-red-300">
            <div className="font-semibold mb-1">后端连接失败</div>
            <div className="text-xs font-mono text-red-400/80">{error}</div>
            <div className="text-xs mt-2 text-slate-400">
              请确认 8765 端口服务已启动：
              <code className="ml-1 px-1 bg-slate-800 rounded">
                cd 11-易经推理系统 && python data_server_fixed.py
              </code>
            </div>
          </div>
        )}

        {snapshot && snapshot.status === 'error' && (
          <div className="bg-amber-900/30 border border-amber-700 rounded-lg p-3 text-sm text-amber-300">
            <div className="font-semibold">快照不可用</div>
            <div className="text-xs mt-1">{snapshot.note || snapshot.neutral_fallback_reason}</div>
            <div className="text-xs mt-2 text-slate-400">
              请先生成今日快照：
              <code className="ml-1 px-1 bg-slate-800 rounded">
                cd 11-易经推理系统/scripts/memory_l4 && python -m force_vector.bdsm_snapshot_writer
              </code>
            </div>
          </div>
        )}

        {snapshot && snapshot.status === 'ok' && (
          <>
            <SectorValuationOverview summary={snapshot.sector_valuation_summary} />
            <CoinInspectionTable coins={snapshot.coins} />
            <UndervaluedPeersAggregated coins={snapshot.coins} />
          </>
        )}

        {!snapshot && !error && loading && (
          <div className="text-center text-slate-500 py-12 text-sm">
            正在拉取 BDSM 快照…
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// §6.2 赛道估值概览
// ============================================================

function SectorValuationOverview({
  summary,
}: {
  summary?: SectorValuationSummary | Record<string, any>;
}) {
  if (!summary) return null;
  const s = summary as Record<string, any>;
  const overheatSectors: string[] = (s.overheat_sectors as string[]) || [];
  const waterlines: SectorWaterline[] = (s.waterlines as SectorWaterline[]) || [];
  const topOpps = (s.top_opportunities as Array<Record<string, any>>) || [];

  return (
    <section className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">赛道估值概览</h2>
        {s.generated_at && (
          <span className="text-[10px] text-slate-500 font-mono">
            {String(s.generated_at).slice(0, 19)}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* 过热赛道 */}
        <div className="bg-slate-950/60 rounded p-3 border border-slate-800">
          <div className="text-[11px] font-semibold text-slate-400 mb-2">
            过热赛道 ({overheatSectors.length})
          </div>
          {overheatSectors.length === 0 ? (
            <div className="text-[10px] text-slate-500">无</div>
          ) : (
            <div className="flex flex-wrap gap-1">
              {overheatSectors.map((sec) => (
                <span
                  key={sec}
                  className="px-2 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-800 text-[10px] font-mono"
                >
                  {sec}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* 赛道水位 */}
        <div className="bg-slate-950/60 rounded p-3 border border-slate-800 md:col-span-2">
          <div className="text-[11px] font-semibold text-slate-400 mb-2">
            赛道水位（{waterlines.length} 赛道）
          </div>
          {waterlines.length === 0 ? (
            <div className="text-[10px] text-slate-500">无</div>
          ) : (
            <div className="space-y-1">
              {waterlines.map((w) => {
                const pct = Number(w.median_percentile || 0);
                const hot = w.overheated === true;
                const cheap = w.undervalued === true;
                const barColor = hot
                  ? 'bg-red-500'
                  : cheap
                  ? 'bg-emerald-500'
                  : pct > 60
                  ? 'bg-amber-500'
                  : 'bg-slate-500';
                return (
                  <div key={w.sector} className="flex items-center gap-2 text-[11px]">
                    <span className="text-slate-300 font-mono w-20">{w.sector}</span>
                    <div className="flex-1 h-2 bg-slate-800 rounded overflow-hidden">
                      <div
                        className={`h-full ${barColor}`}
                        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                      />
                    </div>
                    <span
                      className={`font-mono w-10 text-right ${
                        hot ? 'text-red-400' : cheap ? 'text-emerald-400' : 'text-slate-300'
                      }`}
                    >
                      {pct.toFixed(0)}
                    </span>
                    <span className="text-slate-500 w-16 text-[10px]">
                      {w.leader && `→ ${w.leader}`}
                    </span>
                    <span
                      className={`font-mono w-14 text-[10px] ${
                        w.leader_momentum_7d >= 0
                          ? 'text-emerald-400'
                          : 'text-red-400'
                      }`}
                    >
                      {w.leader_momentum_7d >= 0 ? '+' : ''}
                      {Number(w.leader_momentum_7d || 0).toFixed(2)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Top 机会币 */}
      {topOpps.length > 0 && (
        <div className="mt-3 bg-slate-950/60 rounded p-3 border border-slate-800">
          <div className="text-[11px] font-semibold text-slate-400 mb-2">
            Top 机会币（低估候选）
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {topOpps.slice(0, 10).map((o) => (
              <div
                key={o.coin as string}
                className="flex items-center justify-between px-2 py-1 rounded bg-emerald-500/10 border border-emerald-800/40 text-[10px]"
              >
                <div className="flex items-center gap-1">
                  <span className="text-emerald-300 font-mono">{o.coin}</span>
                  {o.sector && (
                    <span className="text-slate-500 text-[9px]">{o.sector}</span>
                  )}
                </div>
                <span className="text-emerald-300 font-mono">
                  {Number(o.opportunity_score || 0).toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

// ============================================================
// 全币种巡检表
// ============================================================

function CoinInspectionTable({ coins }: { coins: Record<string, BdsmCoinEntry> }) {
  const entries = Object.entries(coins || {}).map(([symbol, info]) => ({
    symbol,
    ...info,
  }));
  // 按 score 降序
  entries.sort((a, b) => (b.score || 0) - (a.score || 0));

  return (
    <section className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">
          全币种巡检（{entries.length}）
        </h2>
        <div className="text-[10px] text-slate-500">
          按 BDS Score 降序 · 含 §6.1 sector_valuation 字段
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-slate-400 border-b border-slate-800">
              <th className="text-left py-2 px-2">币种</th>
              <th className="text-left py-2 px-2">Rank</th>
              <th className="text-right py-2 px-2">Score</th>
              <th className="text-left py-2 px-2">Phase</th>
              <th className="text-left py-2 px-2">方向</th>
              <th className="text-left py-2 px-2">出场</th>
              <th className="text-left py-2 px-2">赛道水位</th>
              <th className="text-right py-2 px-2">多维分</th>
              <th className="text-center py-2 px-2">过热信号</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((c) => {
              const wl = (c.sector_waterline as Record<string, any>) || {};
              const md = (c.multi_dim_valuation as Record<string, any>) || {};
              const oh = (c.overheat_signal as Record<string, any>) || {};
              const mdScore = Number(md.multi_dim_score || 0);
              const wlPct = Number(wl.median_percentile || 0);
              const isOverheat = oh.triggered === true;
              return (
                <tr
                  key={c.symbol}
                  className={`border-b border-slate-800/60 hover:bg-slate-800/30 ${
                    isOverheat ? 'bg-red-500/10' : ''
                  }`}
                >
                  <td className="py-2 px-2">
                    <span className="font-mono text-slate-200">{c.symbol}</span>
                    {c.available === false && (
                      <span className="ml-1 text-[9px] text-slate-600">
                        ({c._unavailable_reason || 'unavailable'})
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                        c.rank === 'S'
                          ? 'bg-amber-500/20 text-amber-300'
                          : c.rank === 'A'
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : 'bg-slate-700/40 text-slate-400'
                      }`}
                    >
                      {c.rank}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right font-mono text-slate-300">
                    {Number(c.score || 0).toFixed(3)}
                  </td>
                  <td className="py-2 px-2 text-slate-400 text-[10px]">
                    {String(c.phase || '').slice(0, 20)}
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`text-[10px] font-mono ${
                        c.direction_constraint === 'LONG_ONLY'
                          ? 'text-emerald-400'
                          : c.direction_constraint === 'SHORT_ONLY'
                          ? 'text-red-400'
                          : 'text-slate-400'
                      }`}
                    >
                      {c.direction_constraint}
                    </span>
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`text-[10px] font-mono ${
                        c.exit_action && c.exit_action !== 'NONE'
                          ? 'text-amber-400'
                          : 'text-slate-500'
                      }`}
                    >
                      {c.exit_action}
                    </span>
                    {c.exit_triggers && c.exit_triggers.length > 0 && (
                      <span className="ml-1 text-[9px] text-amber-500/60">
                        [{c.exit_triggers.length}]
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-2">
                    {wl.sector ? (
                      <span
                        className={`text-[10px] font-mono ${
                          wlPct >= 80
                            ? 'text-red-400'
                            : wlPct <= 20
                            ? 'text-emerald-400'
                            : 'text-slate-400'
                        }`}
                      >
                        {wl.sector} {wlPct.toFixed(0)}
                      </span>
                    ) : (
                      <span className="text-slate-600 text-[10px]">—</span>
                    )}
                  </td>
                  <td className="py-2 px-2 text-right">
                    {mdScore !== 0 ? (
                      <span
                        className={`font-mono text-[10px] ${
                          mdScore > 0.3
                            ? 'text-emerald-400'
                            : mdScore < -0.3
                            ? 'text-red-400'
                            : 'text-slate-300'
                        }`}
                      >
                        {mdScore.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-slate-600 text-[10px]">—</span>
                    )}
                  </td>
                  <td className="py-2 px-2 text-center">
                    {isOverheat ? (
                      <span className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-800 text-[9px] font-mono">
                        过热 {Number(oh.waterline || 0).toFixed(0)}
                      </span>
                    ) : (
                      <span className="text-slate-600 text-[10px]">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ============================================================
// §6.1 低估伙伴候选合并视图（跨币合并去重）
// ============================================================

function UndervaluedPeersAggregated({ coins }: { coins: Record<string, BdsmCoinEntry> }) {
  const aggregated: Array<{
    coin: string;
    opportunity_score: number;
    sources: string[];
  }> = [];
  const seen = new Map<string, { coin: string; opportunity_score: number; sources: string[] }>();

  for (const [symbol, info] of Object.entries(coins || {})) {
    const peers = (info.undervalued_peers as Array<Record<string, any>>) || [];
    for (const p of peers) {
      const coin = (p.coin as string) || '';
      if (!coin) continue;
      const score = Number(p.opportunity_score || 0);
      const existing = seen.get(coin);
      if (existing) {
        existing.sources.push(symbol);
        // 取最高分
        if (score > existing.opportunity_score) {
          existing.opportunity_score = score;
        }
      } else {
        const entry = { coin, opportunity_score: score, sources: [symbol] };
        seen.set(coin, entry);
        aggregated.push(entry);
      }
    }
  }

  if (aggregated.length === 0) {
    return null;
  }

  aggregated.sort((a, b) => b.opportunity_score - a.opportunity_score);

  return (
    <section className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">
          低估伙伴候选（跨币合并去重，{aggregated.length} 个）
        </h2>
        <div className="text-[10px] text-slate-500">按 opportunity_score 降序</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
        {aggregated.map((p) => (
          <div
            key={p.coin}
            className="flex items-center justify-between px-3 py-2 rounded bg-slate-950/60 border border-slate-800"
          >
            <div className="flex items-center gap-2">
              <span className="text-emerald-300 font-mono text-sm">{p.coin}</span>
              <div className="flex flex-wrap gap-0.5">
                {p.sources.map((s) => (
                  <span
                    key={s}
                    className="px-1 rounded bg-slate-700/40 text-slate-400 text-[9px] font-mono"
                  >
                    ← {s}
                  </span>
                ))}
              </div>
            </div>
            <span className="text-emerald-300 font-mono">
              {p.opportunity_score.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
