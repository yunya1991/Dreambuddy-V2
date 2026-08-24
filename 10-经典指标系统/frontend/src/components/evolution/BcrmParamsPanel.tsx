import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine, Legend,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Badge } from '../ui/badge';
import {
  fetchRegimeEvolutionParams,
  type RegimeEvolutionParamsResponse,
} from '../../lib/api';

// ============================================================
// 参数中文标签 & 颜色映射
// ============================================================
const GLOBAL_PARAM_LABELS: Record<string, string> = {
  global_position_mult: '全局仓位乘数',
  ls_ratio_cap: '多空持仓比上限',
  long_bias: '多头偏置',
  short_bias: '空头偏置',
  long_threshold_mult: '多头阈值乘数',
  short_threshold_mult: '空头阈值乘数',
};

const GLOBAL_PARAM_DESC: Record<string, string> = {
  global_position_mult: 'L+4 加仓 / L-4 砍仓 / clip [0.30, 1.60]',
  ls_ratio_cap: '多空持仓比硬上限 / clip [0.20, 1.00]',
  long_bias: '多头方向加性偏置 / clip [-0.30, 0.30]',
  short_bias: '空头方向加性偏置 / clip [-0.30, 0.30]',
  long_threshold_mult: '牛市降做多门槛 / 熊市升门槛',
  short_threshold_mult: '熊市降做空门槛 / 牛市升门槛',
};

const SECTOR_LABELS: Record<string, string> = {
  defi: 'DeFi',
  ai: 'AI/WEB3',
  rwa: 'RWA',
  meme: 'MEME',
  l2: 'L2',
};

const SECTOR_COLORS: Record<string, string> = {
  defi: '#3b82f6',
  ai: '#8b5cf6',
  rwa: '#10b981',
  meme: '#f59e0b',
  l2: '#ec4899',
};

// ============================================================
// 子组件：输入快照条
// ============================================================
const InputsBar: React.FC<{ inputs: RegimeEvolutionParamsResponse['inputs'] }> = ({ inputs }) => {
  const lColor = inputs.level_smooth >= 0 ? '#16a34a' : '#ef4444';
  const tColor = inputs.trend_smooth >= 0 ? '#16a34a' : '#ef4444';
  return (
    <div className="flex flex-wrap items-center gap-3 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
      <span className="font-medium text-slate-500">输入 (L, T, C)</span>
      <span className="font-mono font-semibold" style={{ color: lColor }}>
        L = {inputs.level_smooth.toFixed(3)}
      </span>
      <span className="font-mono font-semibold" style={{ color: tColor }}>
        T = {inputs.trend_smooth.toFixed(3)}
      </span>
      <span className="font-mono font-semibold text-slate-700">
        C = {(inputs.consensus * 100).toFixed(1)}%
      </span>
      <span className="text-slate-400">→</span>
      <span className="text-slate-500">共识越高 → 6 参数带宽越窄</span>
    </div>
  );
};

// ============================================================
// 子组件：6 全局参数表
// ============================================================
const GlobalParamsTable: React.FC<{ items: RegimeEvolutionParamsResponse['global_params'] }> = ({ items }) => {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500">
            <th className="py-1.5 pr-2 font-medium">参数</th>
            <th className="py-1.5 px-2 font-medium">中心</th>
            <th className="py-1.5 px-2 font-medium">范围 [lo, hi]</th>
            <th className="py-1.5 px-2 font-medium">带宽</th>
            <th className="py-1.5 px-2 font-medium">直通中心</th>
            <th className="py-1.5 pl-2 font-medium">偏移</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const offset = it.center - it.identity_center;
            const offsetColor = Math.abs(offset) < 1e-4
              ? 'text-slate-400'
              : offset > 0 ? 'text-green-600' : 'text-red-600';
            const offsetSign = offset > 0 ? '+' : '';
            return (
              <tr key={it.name} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-1.5 pr-2">
                  <div className="font-medium text-slate-700">{GLOBAL_PARAM_LABELS[it.name] || it.name}</div>
                  <div className="text-[10px] text-slate-400">{GLOBAL_PARAM_DESC[it.name] || ''}</div>
                </td>
                <td className="py-1.5 px-2 font-mono font-semibold text-slate-800">{it.center.toFixed(4)}</td>
                <td className="py-1.5 px-2 font-mono text-slate-600">
                  [{it.lo.toFixed(4)}, {it.hi.toFixed(4)}]
                </td>
                <td className="py-1.5 px-2 font-mono text-slate-500">{it.bandwidth.toFixed(4)}</td>
                <td className="py-1.5 px-2 font-mono text-slate-400">{it.identity_center.toFixed(4)}</td>
                <td className={`py-1.5 pl-2 font-mono font-semibold ${offsetColor}`}>
                  {offsetSign}{offset.toFixed(4)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

// ============================================================
// 子组件：板块权重对比柱状图
// ============================================================
const SectorWeightsChart: React.FC<{ items: RegimeEvolutionParamsResponse['sector_weights'] }> = ({ items }) => {
  const chartData = useMemo(
    () => items.map((it) => ({
      name: SECTOR_LABELS[it.name] || it.name.toUpperCase(),
      current: Number((it.weight * 100).toFixed(2)),
      identity: Number((it.identity_weight * 100).toFixed(2)),
      fill: SECTOR_COLORS[it.name] || '#94a3b8',
    })),
    [items],
  );

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
        <span>当前权重 vs 直通基线 (identity = 20%)</span>
        <span>单位：%</span>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <XAxis dataKey="name" tick={{ fontSize: 10 }} stroke="#94a3b8" />
          <YAxis tick={{ fontSize: 10 }} stroke="#94a3b8" domain={[0, 100]} />
          <Tooltip
            cursor={{ fill: '#f1f5f9' }}
            contentStyle={{ fontSize: 11, padding: '4px 8px' }}
            formatter={(v, name) => [`${v}%`, name === 'current' ? '当前' : '直通']}
          />
          <Legend wrapperStyle={{ fontSize: 10 }} formatter={(v: string) => (v === 'current' ? '当前' : '直通')} />
          <ReferenceLine y={20} stroke="#cbd5e1" strokeDasharray="3 3" />
          <Bar dataKey="identity" name="identity" fill="#e2e8f0" radius={[2, 2, 0, 0]} barSize={14} />
          <Bar dataKey="current" name="current" radius={[2, 2, 0, 0]} barSize={14}>
            {chartData.map((entry, idx) => (
              <Cell key={idx} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

// ============================================================
// 子组件：Identity 不变量校验徽章
// ============================================================
const IdentityCheck: React.FC<{ data: RegimeEvolutionParamsResponse }> = ({ data }) => {
  const sumOk = Math.abs(data.sector_weights_sum - 1.0) < 1e-3;
  const identitySum = data.identity.sector_weights.reduce((acc, w) => acc + w.weight, 0);
  const identityOk = Math.abs(identitySum - 1.0) < 1e-3;
  const identityUniform = data.identity.sector_weights.every(
    (w) => Math.abs(w.weight - 0.2) < 1e-3,
  );
  const allOk = sumOk && identityOk && identityUniform;

  return (
    <div className="flex flex-wrap items-center gap-2 text-[10px]">
      <Badge variant={allOk ? 'default' : 'destructive'} className="text-[10px]">
        {allOk ? '三层兼容不变量 ✓' : '不变量异常 ✗'}
      </Badge>
      <span className={sumOk ? 'text-green-600' : 'text-red-600'}>
        Σ当前权重 = {data.sector_weights_sum.toFixed(4)} {sumOk ? '✓' : '✗'}
      </span>
      <span className={identityOk ? 'text-green-600' : 'text-red-600'}>
        Σ直通权重 = {identitySum.toFixed(4)} {identityOk ? '✓' : '✗'}
      </span>
      <span className={identityUniform ? 'text-green-600' : 'text-red-600'}>
        直通均匀 0.20/板块 {identityUniform ? '✓' : '✗'}
      </span>
    </div>
  );
};

// ============================================================
// 主组件：BCRM 参数输出面板
// ============================================================
export const BcrmParamsPanel: React.FC<{ symbol?: string }> = ({ symbol = 'BTCUSDT' }) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['regime-evolution-params', symbol],
    queryFn: () => fetchRegimeEvolutionParams({ symbol }),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">Panel 5: BCRM 2.0 参数输出</CardTitle>
            <p className="mt-0.5 text-[10px] text-slate-400">
              ParameterMapper 方案 A · Level-Trend 纯连续函数映射 → 核心层 BCRM 2.0 输入
            </p>
          </div>
          {data && <IdentityCheck data={data} />}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && !data ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">加载中...</div>
        ) : error ? (
          <div className="flex h-64 items-center justify-center text-sm text-red-500">
            加载失败: {String(error)}
          </div>
        ) : !data ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">暂无数据</div>
        ) : (
          <div className="space-y-3">
            <InputsBar inputs={data.inputs} />

            <div>
              <div className="mb-1 text-xs font-medium text-slate-600">
                ① 6 个全局参数范围（中心 + 带宽随 C 收窄）
              </div>
              <GlobalParamsTable items={data.global_params} />
            </div>

            <div>
              <div className="mb-1 text-xs font-medium text-slate-600">
                ② 5 板块资金权重（Σ=1，softmax((1-C)·uniform + C·score)）
              </div>
              <SectorWeightsChart items={data.sector_weights} />
            </div>

            <div className="rounded border border-slate-200 bg-slate-50 p-2 text-[10px] text-slate-500">
              <span className="font-medium text-slate-600">说明：</span>
              当前板块权重基于 identity betas (β=1.0, α=0, corr=0.5)，仅反映 (L, T, C) 影响；
              接入真实板块 betas 后，权重将叠加 β/α/corr 项。无偏 (L=0,T=0,C=0) 时所有参数直通。
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
