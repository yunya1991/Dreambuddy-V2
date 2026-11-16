'use client';

// 信号反馈表（TASKS-20261116 T9-4）：信号 → 后 5/20 日，分档命中率
// 数据来自 `/api/visual/signal-feedback`（只读 signal_journal + 日线，脚本内非重叠采样）。
// 分母 = n_eff（非重叠窗口数），与表格展示的样本数严格一致，不用重叠样本放大命中率。

import { useEffect, useState } from 'react';
import { V3Badge, V3Empty } from '@/components';

export interface FeedbackTarget {
  target: string;
  n_raw: number;
  n_eff: number;
  hits: number;
  hit_rate: number | null;
  base_rate: number | null;
  excess_hit: number | null;
  avg_forward: number | null;
}

export interface FeedbackBucket {
  strength: string;
  n_eff: number;
  hits: number;
  hit_rate: number | null;
}

export interface FeedbackHorizon {
  horizon: number;
  totals: { n_raw: number; n_eff: number; hits: number; hit_rate: number | null };
  targets: FeedbackTarget[];
  buckets: FeedbackBucket[];
}

export interface FeedbackPayload {
  ok: boolean;
  as_of?: string;
  horizons?: FeedbackHorizon[];
  answer?: string;
  quality?: { status?: string; sample_n?: number; degraded_reason?: string };
  error?: string;
}

const STRENGTH_LABEL: Record<string, string> = {
  strong: '强',
  medium: '中',
  weak: '弱',
  unknown: '未分档',
};

function pct(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(digits)}%`;
}

function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

export function SignalFeedback() {
  const [payload, setPayload] = useState<FeedbackPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch('/api/visual/signal-feedback?horizons=5,20', { cache: 'no-store' })
      .then(async (response) => (await response.json()) as FeedbackPayload)
      .then((data) => {
        if (alive) setPayload(data);
      })
      .catch((err: unknown) => {
        if (alive) {
          setPayload({ ok: false, error: err instanceof Error ? err.message : 'fetch_failed' });
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return <div className="h-24 animate-pulse rounded-lg bg-slate-800/40" />;
  }

  if (!payload || !payload.ok) {
    return (
      <V3Empty
        title="信号反馈不可用"
        description={payload?.error || '反馈脚本未返回结果（FAIL-OPEN，不伪造命中率）'}
      />
    );
  }

  const horizons = payload.horizons ?? [];
  if (horizons.length === 0 || horizons.every((block) => block.totals.n_eff === 0)) {
    return (
      <V3Empty
        title="暂无已结算信号"
        description={
          payload.answer || payload.quality?.degraded_reason || '信号账本为空：先让 D-K03 产出信号再回填'
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
        <V3Badge variant="default" label={`${payload.as_of ?? '—'} 结算`} />
        <span>分母 = n_eff（非重叠窗口），与表格样本一致</span>
        {payload.quality?.status === 'empty' && <V3Badge variant="warning" label="样本为空" />}
      </div>

      {horizons.map((block) => (
        <section key={block.horizon} className="rounded-xl border border-slate-800 bg-slate-900/40">
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 px-3.5 py-2.5">
            <div>
              <p className="text-[12.5px] font-medium text-slate-200">信号 → 后 {block.horizon} 日</p>
              <p className="mt-0.5 text-[10px] text-slate-500">
                原始 {block.totals.n_raw} 条 · 非重叠 n_eff {block.totals.n_eff} · 命中{' '}
                {block.totals.hits}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[12px] text-slate-100">
                {pct(block.totals.hit_rate)}
              </span>
              <span className="text-[10px] text-slate-500">命中率</span>
            </div>
          </header>

          <div className="px-3.5 py-2.5">
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              {block.buckets.map((bucket) => (
                <span
                  key={bucket.strength}
                  className="rounded border border-slate-700 bg-slate-950/50 px-1.5 py-0.5 text-[10px] text-slate-300"
                >
                  {STRENGTH_LABEL[bucket.strength] ?? bucket.strength} · n_eff {bucket.n_eff} · 命中{' '}
                  {pct(bucket.hit_rate)}
                </span>
              ))}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] border-collapse text-[11px]">
                <thead>
                  <tr className="text-left text-[10px] text-slate-500">
                    <th className="py-1 pr-2 font-normal">标的</th>
                    <th className="py-1 pr-2 font-normal">样本 n_eff</th>
                    <th className="py-1 pr-2 font-normal">命中</th>
                    <th className="py-1 pr-2 font-normal">命中率</th>
                    <th className="py-1 pr-2 font-normal">同向基准</th>
                    <th className="py-1 pr-2 font-normal">超额命中</th>
                    <th className="py-1 font-normal">平均前瞻收益</th>
                  </tr>
                </thead>
                <tbody>
                  {block.targets.map((row) => (
                    <tr key={row.target} className="border-t border-slate-800/60 text-slate-300">
                      <td className="py-1 pr-2">{row.target}</td>
                      <td className="py-1 pr-2 font-mono">{row.n_eff}</td>
                      <td className="py-1 pr-2 font-mono">{row.hits}</td>
                      <td className="py-1 pr-2 font-mono">{pct(row.hit_rate)}</td>
                      <td className="py-1 pr-2 font-mono">{pct(row.base_rate)}</td>
                      <td
                        className={`py-1 pr-2 font-mono ${
                          (row.excess_hit ?? 0) > 0 ? 'text-emerald-400' : 'text-slate-400'
                        }`}
                      >
                        {signedPct(row.excess_hit)}
                      </td>
                      <td className="py-1 font-mono">{signedPct(row.avg_forward, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ))}

      <p className="text-[10px] text-slate-500">
        只统计 signal_journal 里 decision=allowed 的信号；blocked 信号不计入命中率，避免把未执行信号算成收益。
      </p>
    </div>
  );
}

export default SignalFeedback;
