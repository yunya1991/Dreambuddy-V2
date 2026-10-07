"use client";

// ============================================================
// Daily Briefing 每日简报页面 (F7.2)
// 列表 + 详情双栏布局
// ============================================================

import { useEffect, useState } from "react";

interface Briefing {
  id: string;
  type: string;
  title: string;
  generated_at: string;
  date: string;
  summary?: string;
}

interface BriefingDetail extends Briefing {
  system_status?: Record<string, any>;
  scheduler_history?: Array<Record<string, any>>;
  bcrm2_status?: Record<string, any>;
  bdsm_status?: Record<string, any>;
  s3_s4_signals?: Record<string, any>;
  positions?: Record<string, any>;
}

const TYPE_META: Record<string, { label: string; color: string; icon: string }> = {
  pre_market: { label: "盘前", color: "bg-blue-500/20 text-blue-300 border-blue-800", icon: "🌅" },
  mid_market: { label: "盘中", color: "bg-amber-500/20 text-amber-300 border-amber-800", icon: "📈" },
  post_market: { label: "盘后", color: "bg-emerald-500/20 text-emerald-300 border-emerald-800", icon: "🌙" },
};

export default function BriefingPage() {
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [selected, setSelected] = useState<BriefingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    fetchList();
  }, []);

  async function fetchList() {
    setLoading(true);
    try {
      // TODO: migrate to domain client — non-standard response (uses data.briefings, not data.data)
      const res = await fetch("/api/briefings?limit=50");
      const data = await res.json();
      if (data.success) {
        setBriefings(data.briefings || []);
      }
    } catch (e) {
      console.error("加载简报列表失败:", e);
    } finally {
      setLoading(false);
    }
  }

  async function fetchDetail(id: string) {
    setDetailLoading(true);
    try {
      // TODO: migrate to domain client — non-standard response (uses data.briefing, not data.data)
      const res = await fetch(`/api/briefings/${id}`);
      const data = await res.json();
      if (data.success) {
        setSelected(data.briefing);
      }
    } catch (e) {
      console.error("加载简报详情失败:", e);
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="flex h-screen">
      {/* 左侧：简报列表 */}
      <div className="w-80 border-r border-slate-800 overflow-y-auto bg-slate-900/40">
        <div className="p-4 border-b border-slate-800">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold text-slate-100">📋 每日简报</h1>
            <button onClick={fetchList} className="text-xs text-indigo-400 hover:underline">
              刷新
            </button>
          </div>
          <p className="text-xs text-slate-500 mt-1">盘前综述 / 盘中异动 / 盘后总结</p>
        </div>

        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">加载中...</div>
        ) : briefings.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">暂无简报</div>
        ) : (
          <div className="divide-y divide-slate-800">
            {briefings.map((b) => {
              const meta = TYPE_META[b.type] || { label: b.type, color: "bg-slate-500/20 text-slate-300 border-slate-700", icon: "📄" };
              const isActive = selected?.id === b.id;
              return (
                <button
                  key={b.id}
                  onClick={() => fetchDetail(b.id)}
                  className={`w-full text-left p-3 hover:bg-slate-800/50 transition ${isActive ? "bg-slate-800/70 border-l-2 border-indigo-500" : ""}`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm">{meta.icon}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${meta.color}`}>
                      {meta.label}
                    </span>
                    <span className="text-[10px] text-slate-500 ml-auto">{b.date}</span>
                  </div>
                  <div className="text-sm font-medium text-slate-200 truncate">{b.title}</div>
                  <div className="text-[10px] text-slate-500 mt-0.5">
                    {new Date(b.generated_at).toLocaleString("zh-CN")}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* 右侧：简报详情 */}
      <div className="flex-1 overflow-y-auto">
        {detailLoading ? (
          <div className="p-8 text-center text-sm text-slate-500">加载中...</div>
        ) : !selected ? (
          <div className="p-12 text-center text-slate-500">
            <div className="text-4xl mb-3">📋</div>
            <p className="text-sm">选择左侧简报查看详情</p>
          </div>
        ) : (
          <div className="p-6 space-y-4">
            {/* 标题区 */}
            <div>
              <h2 className="text-xl font-semibold text-slate-100">{selected.title}</h2>
              <p className="text-xs text-slate-500 mt-1">
                生成时间: {new Date(selected.generated_at).toLocaleString("zh-CN")}
              </p>
            </div>

            {/* 摘要 */}
            {selected.summary && (
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
                <pre className="text-xs text-slate-300 whitespace-pre-wrap font-sans leading-relaxed">
                  {selected.summary}
                </pre>
              </div>
            )}

            {/* 系统状态 */}
            {selected.system_status && (
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-indigo-400 mb-2">⚙️ 系统状态</h3>
                <SystemStatusView status={selected.system_status} />
              </div>
            )}

            {/* 执行历史 */}
            {selected.scheduler_history && selected.scheduler_history.length > 0 && (
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-indigo-400 mb-2">
                  📊 调度执行历史 ({selected.scheduler_history.length})
                </h3>
                <div className="space-y-1.5 max-h-96 overflow-y-auto">
                  {selected.scheduler_history.map((h, i) => (
                    <HistoryRow key={i} item={h} />
                  ))}
                </div>
              </div>
            )}

            {/* 数据源状态 */}
            <div className="grid grid-cols-2 gap-3">
              <BcrmView data={selected.bcrm2_status} />
              <BdsmView data={selected.bdsm_status} />
              <PlaceholderCard title="S3/S4 战略信号" data={selected.s3_s4_signals} />
              <PositionsView data={selected.positions} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SystemStatusView({ status }: { status: Record<string, any> }) {
  if (status.status !== "ok") {
    return <p className="text-xs text-slate-500">状态不可用</p>;
  }
  return (
    <div className="space-y-1.5 text-xs">
      <div className="flex gap-4">
        <span className="text-slate-400">已启用任务:</span>
        <span className="text-slate-200">
          {status.enabled_jobs}/{status.total_jobs}
        </span>
      </div>
      <div className="flex gap-4">
        <span className="text-slate-400">任务类型:</span>
        <span className="text-slate-200">{(status.job_types as string[]).join(", ")}</span>
      </div>
    </div>
  );
}

function HistoryRow({ item }: { item: Record<string, any> }) {
  const result = item.result as Record<string, any> | undefined;
  const finalResult = result?.final_result as string | undefined;
  const color = finalResult?.includes("EXECUTED")
    ? "text-emerald-400"
    : finalResult?.includes("REJECTED")
      ? "text-amber-400"
      : finalResult?.includes("HOLD")
        ? "text-slate-400"
        : "text-slate-300";
  return (
    <div className="flex items-center gap-2 text-xs py-1 border-b border-slate-800 last:border-0">
      <span className="text-slate-500 shrink-0">
        {new Date(item.timestamp as string).toLocaleTimeString("zh-CN")}
      </span>
      <span className="text-slate-300 font-medium shrink-0">{item.symbol}</span>
      <span className={`shrink-0 ${color}`}>{finalResult || "—"}</span>
      <span className="text-slate-500 truncate">{item.action as string}</span>
    </div>
  );
}

function BcrmView({ data }: { data?: Record<string, any> }) {
  if (!data || data.status !== "ok") {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
        <div className="text-xs font-semibold text-slate-300 mb-1">BCRM2.0 推理</div>
        <div className="text-[10px] text-slate-500">{(data?.note as string) || "待接入"}</div>
      </div>
    );
  }
  const pnl = Number(data.total_pnl || 0);
  const pnlColor = pnl >= 0 ? "text-emerald-400" : "text-red-400";
  const consecLoss = Number(data.current_consecutive_losses || 0);
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-300">BCRM2.0 推理</span>
        <span className="text-[10px] text-slate-500">{data.date as string}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
        <span className="text-slate-400">交易数: <span className="text-slate-200">{data.total_trades}</span></span>
        <span className="text-slate-400">胜率: <span className="text-slate-200">{(Number(data.win_rate) * 100).toFixed(1)}%</span></span>
        <span className="text-slate-400">PnL: <span className={pnlColor}>{pnl.toFixed(2)}</span></span>
        <span className="text-slate-400">PF: <span className="text-slate-200">{Number(data.profit_factor).toFixed(2)}</span></span>
        <span className="text-slate-400">权益: <span className="text-slate-200">{Number(data.ending_equity).toFixed(0)}</span></span>
        <span className="text-slate-400">连亏: <span className={consecLoss >= 3 ? "text-red-400" : "text-slate-200"}>{consecLoss}</span></span>
      </div>
    </div>
  );
}

function BdsmView({ data }: { data?: Record<string, any> }) {
  if (!data || data.status !== "ok") {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
        <div className="text-xs font-semibold text-slate-300 mb-1">BDSM 出场巡检</div>
        <div className="text-[10px] text-slate-500">{(data?.note as string) || "待接入"}</div>
      </div>
    );
  }
  const top5 = (data.top5 as Array<Record<string, any>>) || [];
  const exitSignals = (data.exit_signals as Array<Record<string, any>>) || [];
  // §6.2 sector_valuation_summary（SPEC 2026-10-07）
  const summary = (data.sector_valuation_summary as Record<string, any>) || {};
  const overheatSectors = (summary.overheat_sectors as string[]) || [];
  const topOpps = (summary.top_opportunities as Array<Record<string, any>>) || [];
  const waterlines = (summary.waterlines as Array<Record<string, any>>) || [];
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-300">BDSM 出场巡检</span>
        <span className="text-[10px] text-slate-500">{data.snapshot_date as string}</span>
      </div>
      <div className="flex gap-4 text-[10px]">
        <span className="text-slate-400">币种: <span className="text-slate-200">{data.total_coins}</span></span>
        <span className="text-slate-400">出场信号: <span className={exitSignals.length > 0 ? "text-red-400" : "text-slate-200"}>{exitSignals.length}</span></span>
        <span className="text-slate-400">过热赛道: <span className={overheatSectors.length > 0 ? "text-red-400" : "text-slate-200"}>{overheatSectors.length}</span></span>
      </div>

      {/* §6.2 赛道估值概览 — 仅当有 waterlines/overheat/opportunities 时展示 */}
      {(overheatSectors.length > 0 || topOpps.length > 0 || waterlines.length > 0) && (
        <div className="border-t border-slate-800 pt-2 space-y-1.5">
          <div className="text-[10px] font-semibold text-slate-400">赛道估值概览</div>
          {overheatSectors.length > 0 && (
            <div className="flex items-center gap-1 text-[10px] flex-wrap">
              <span className="text-slate-500">过热:</span>
              {overheatSectors.map((s) => (
                <span key={s} className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-800 font-mono">{s}</span>
              ))}
            </div>
          )}
          {waterlines.length > 0 && (
            <div className="flex items-center gap-2 text-[10px] flex-wrap">
              <span className="text-slate-500">水位:</span>
              {waterlines.slice(0, 6).map((w) => {
                const pct = Number(w.median_percentile || 0);
                const hot = w.overheated === true;
                const cheap = w.undervalued === true;
                const color = hot ? "text-red-300" : cheap ? "text-emerald-300" : "text-slate-300";
                return (
                  <span key={w.sector} className={`font-mono ${color}`}>
                    {w.sector} {pct.toFixed(0)}{hot && "⚠"}{cheap && "↓"}
                  </span>
                );
              })}
            </div>
          )}
          {topOpps.length > 0 && (
            <div className="flex items-center gap-1 text-[10px] flex-wrap">
              <span className="text-slate-500">机会:</span>
              {topOpps.slice(0, 3).map((o) => (
                <span key={o.coin as string} className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-800 font-mono">
                  {o.coin} {(Number(o.opportunity_score || 0)).toFixed(2)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="space-y-1 border-t border-slate-800 pt-2">
        {top5.map((c, i) => {
          // §6.1 高亮过热币（overheat_signal.triggered=true）
          const oh = c.overheat_signal as Record<string, any> | undefined;
          const isOverheat = oh?.triggered === true;
          const wl = c.sector_waterline as Record<string, any> | undefined;
          const wlSector = wl?.sector as string | undefined;
          const wlPct = Number(wl?.median_percentile || 0);
          return (
            <div key={i} className={`flex items-center justify-between text-[10px] px-1 rounded ${isOverheat ? "bg-red-500/10 border border-red-800/50" : ""}`}>
              <div className="flex items-center gap-1.5">
                <span className="text-slate-200 font-mono">{c.symbol}</span>
                {wlSector && (
                  <span className={`font-mono text-[9px] ${wlPct >= 80 ? "text-red-400" : wlPct <= 20 ? "text-emerald-400" : "text-slate-500"}`}>
                    {wlSector} {wlPct.toFixed(0)}
                  </span>
                )}
                {isOverheat && <span className="text-red-400 text-[9px]">过热</span>}
              </div>
              <div className="flex gap-2">
                <span className="text-slate-400">{c.rank}</span>
                <span className="text-slate-300">{Number(c.score).toFixed(3)}</span>
                <span className={c.exit_action === "NONE" ? "text-slate-500" : "text-amber-400"}>{c.exit_action}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PositionsView({ data }: { data?: Record<string, any> }) {
  if (!data || data.status !== "ok") {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
        <div className="text-xs font-semibold text-slate-300 mb-1">持仓 PnL / 止损</div>
        <div className="text-[10px] text-slate-500">{(data?.note as string) || "待接入"}</div>
      </div>
    );
  }
  const positions = (data.positions as Array<Record<string, any>>) || [];
  const total = Number(data.total_positions || 0);
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-300">持仓 PnL / 止损</span>
        <span className="text-[10px] text-slate-500">{data.snapshot_date as string}</span>
      </div>
      <div className="flex gap-4 text-[10px] mb-2">
        <span className="text-slate-400">仓位: <span className="text-slate-200">{total}</span></span>
        <span className="text-slate-400">名义价值: <span className="text-slate-200">{Number(data.total_notional).toFixed(0)}</span></span>
      </div>
      {total === 0 ? (
        <div className="text-[10px] text-slate-500">当前无持仓</div>
      ) : (
        <div className="space-y-1 max-h-32 overflow-y-auto">
          {positions.slice(0, 5).map((p, i) => (
            <div key={i} className="flex items-center justify-between text-[10px]">
              <span className="text-slate-200 font-mono">{p.symbol}</span>
              <div className="flex gap-2">
                <span className="text-slate-400">{Number(p.accumulated_notional).toFixed(0)}</span>
                <span className={p.exit_action !== "NONE" ? "text-amber-400" : "text-slate-500"}>{p.exit_action}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PlaceholderCard({ title, data }: { title: string; data?: Record<string, any> }) {
  const isUnavailable = data?.status === "unavailable";
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
      <div className="text-xs font-semibold text-slate-300 mb-1">{title}</div>
      {isUnavailable ? (
        <div className="text-[10px] text-slate-500">{(data?.note as string) || "待接入"}</div>
      ) : (
        <div className="text-xs text-slate-300">{JSON.stringify(data).slice(0, 100)}</div>
      )}
    </div>
  );
}
