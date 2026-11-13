'use client';

// SPEC-52 F7 — 用量与审计（CU 余额 / 维度明细 / 账本 / venue + 插件审计）

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { billing } from '@/lib/billing-client';
import { plugins } from '@/lib/plugins-client';
import { venue } from '@/lib/venue-client';
import { V3Badge, V3Card } from '@/components';
import { queryKey, queryStaleTime } from '@/lib/query-keys';

const DIMENSION_LABELS: Record<string, string> = {
  llm_input: '输入 Token',
  llm_output: '输出 Token',
  tool_call: '工具调用',
  tool_call_heavy: '重工具调用',
  backtest_cpu: '回测 CPU',
  data_query: '数据查询',
  plugin_runtime: '插件运行时',
};

function fmt(value: number, digits = 2): string {
  return Number.isFinite(value) ? value.toFixed(digits) : '-';
}

export default function UsagePage() {
  const usageQuery = useQuery({
    queryKey: queryKey('billing', 'usage'),
    queryFn: () => billing.usage(100),
    staleTime: queryStaleTime('settings'),
    retry: false,
    refetchInterval: 30000,
  });

  const venueAuditQuery = useQuery({
    queryKey: queryKey('venue', 'audit'),
    queryFn: () => venue.audit(20),
    staleTime: queryStaleTime('settings'),
    retry: false,
  });

  const pluginAuditQuery = useQuery({
    queryKey: queryKey('plugins', 'audit'),
    queryFn: () => plugins.audit(20),
    staleTime: queryStaleTime('settings'),
    retry: false,
  });

  const usage = usageQuery.data;
  const dimensions = Object.entries(usage?.totals ?? {}).sort((a, b) => b[1].cu_cost - a[1].cu_cost);
  const maxCu = dimensions.reduce((max, [, v]) => Math.max(max, v.cu_cost), 0) || 1;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-100">用量与审计</h1>
          <p className="mt-1 text-xs text-gray-500">
            CU 计量（账本只追加）· 余额 = 初始额度 - 已结算 - 活跃预扣 · 审计覆盖用户 venue 与插件启停
          </p>
        </div>
        <V3Badge variant="info">F7</V3Badge>
      </div>

      {usageQuery.isError && (
        <div className="rounded-md border border-red-700/40 bg-red-900/15 px-3 py-2 text-xs text-red-300">
          {(usageQuery.error as Error).message}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <V3Card title="CU 余额" padding="sm">
          <div className="text-2xl font-semibold text-gray-100">{fmt(usage?.balance_cu ?? 0)}</div>
          <div className="mt-1 text-[11px] text-gray-500">
            约 ¥{fmt((usage?.balance_cu ?? 0) * (usage?.unit_price_cny ?? 0), 2)} · 单价{' '}
            {usage?.unit_price_cny ?? '-'} 元/CU
          </div>
        </V3Card>
        <V3Card title="已结算" padding="sm">
          <div className="text-2xl font-semibold text-gray-100">{fmt(usage?.spent_cu ?? 0)}</div>
          <div className="mt-1 text-[11px] text-gray-500">初始额度 {fmt(usage?.base_cu ?? 0)} CU</div>
        </V3Card>
        <V3Card title="活跃预扣" padding="sm">
          <div className="text-2xl font-semibold text-gray-100">{fmt(usage?.reserved_cu ?? 0)}</div>
          <div className="mt-1 text-[11px] text-gray-500">请求结束自动释放</div>
        </V3Card>
        <V3Card title="账本条数" padding="sm">
          <div className="text-2xl font-semibold text-gray-100">{usage?.records.length ?? 0}</div>
          <div className="mt-1 text-[11px] text-gray-500">最近 100 条</div>
        </V3Card>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <V3Card title="按维度聚合" subtitle="CU 成本归一，定价与计量分离" padding="sm">
          {dimensions.length === 0 ? (
            <p className="py-4 text-xs text-gray-500">暂无用量记录（发起一次 Agent 对话后产生）</p>
          ) : (
            <div className="space-y-2.5">
              {dimensions.map(([dimension, value]) => (
                <div key={dimension}>
                  <div className="mb-1 flex items-center justify-between text-[11px]">
                    <span className="text-gray-400">{DIMENSION_LABELS[dimension] ?? dimension}</span>
                    <span className="font-mono text-gray-300">
                      {fmt(value.cu_cost)} CU · {fmt(value.quantity, 0)}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-gray-800">
                    <div
                      className="h-full rounded-full bg-blue-500/70"
                      style={{ width: `${Math.max((value.cu_cost / maxCu) * 100, 2)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </V3Card>

        <V3Card title="最近账本" subtitle="usage_ledger.jsonl（只追加）" padding="sm">
          <div className="max-h-64 overflow-auto">
            <table className="w-full text-left text-[11px]">
              <thead className="text-gray-500">
                <tr>
                  <th className="pb-1 font-normal">时间</th>
                  <th className="pb-1 font-normal">维度</th>
                  <th className="pb-1 text-right font-normal">数量</th>
                  <th className="pb-1 text-right font-normal">CU</th>
                </tr>
              </thead>
              <tbody className="text-gray-400">
                {(usage?.records ?? []).map((record) => (
                  <tr key={record.id} className="border-t border-gray-800/60">
                    <td className="py-1 font-mono text-gray-500">{record.created_at.slice(5, 19)}</td>
                    <td className="py-1">{DIMENSION_LABELS[record.dimension] ?? record.dimension}</td>
                    <td className="py-1 text-right font-mono">{fmt(record.quantity, 0)}</td>
                    <td className="py-1 text-right font-mono">{fmt(record.cu_cost)}</td>
                  </tr>
                ))}
                {(usage?.records ?? []).length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-gray-500">
                      暂无记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </V3Card>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <V3Card title="用户 venue 审计" subtitle="51 runtime/audit/user_venue_calls.jsonl" padding="sm">
          <AuditList
            error={venueAuditQuery.isError ? (venueAuditQuery.error as Error).message : null}
            rows={(venueAuditQuery.data?.records ?? []).map((record) => ({
              key: `${record.ts}-${record.operation}-${record.trace_id ?? ''}`,
              time: record.ts ?? '',
              label: record.operation ?? 'operation',
              detail: `${record.mode ?? '-'} · ${record.ok === false ? record.error_code ?? 'failed' : 'ok'}`,
              ok: record.ok !== false,
            }))}
          />
        </V3Card>

        <V3Card title="插件启停审计" subtitle="plugin_audit.jsonl" padding="sm">
          <AuditList
            error={pluginAuditQuery.isError ? (pluginAuditQuery.error as Error).message : null}
            rows={(pluginAuditQuery.data ?? []).map((record) => ({
              key: record.id,
              time: record.created_at,
              label: `${record.action} · ${record.plugin_id}`,
              detail: `${record.profile} · ${record.result}`,
              ok: record.result === 'ok',
            }))}
          />
        </V3Card>
      </div>
    </div>
  );
}

function AuditList({
  rows,
  error,
}: {
  rows: Array<{ key: string; time: string; label: string; detail: string; ok: boolean }>;
  error: string | null;
}) {
  if (error) {
    return <p className="py-3 text-[11px] text-amber-400/80">审计不可用：{error}</p>;
  }
  if (rows.length === 0) {
    return <p className="py-3 text-[11px] text-gray-500">暂无审计记录</p>;
  }
  return (
    <ul className="max-h-56 space-y-1.5 overflow-auto text-[11px]">
      {rows.map((row) => (
        <li key={row.key} className="flex items-center justify-between gap-2 border-b border-gray-800/50 pb-1.5">
          <div className="min-w-0">
            <div className="truncate text-gray-300">{row.label}</div>
            <div className="font-mono text-[10px] text-gray-500">
              {row.time.slice(0, 19)} · {row.detail}
            </div>
          </div>
          <V3Badge variant={row.ok ? 'success' : 'danger'}>{row.ok ? 'ok' : 'failed'}</V3Badge>
        </li>
      ))}
    </ul>
  );
}
