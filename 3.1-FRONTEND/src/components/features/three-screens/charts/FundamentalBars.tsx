'use client';

import React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';

interface FundamentalBarsProps {
  dimensions: Record<string, { direction: string; confidence: number; value?: number; weight: number }>;
  height?: number;
}

const dimNameMap: Record<string, string> = {
  fear_greed: '恐惧贪婪',
  fear_greed_enhanced: '增强情绪',
  etf_flow: 'ETF净流入',
  stablecoin_supply: '稳定币',
  funding_rate: '资金费率',
  deribit_oi: '期权持仓',
  fred_macro: '宏观利率',
  defillama_tvl: 'DeFi TVL',
};

/**
 * 基本面维度柱状图 — 使用 recharts Bar
 * 展示各基本面维度的方向（正值=看多，负值=看空）和置信度
 */
export function FundamentalBars({ dimensions, height = 240 }: FundamentalBarsProps) {
  const data = Object.entries(dimensions).map(([key, val]) => {
    const dir = (val.direction || 'NEUTRAL').toUpperCase();
    const sign = dir === 'BULL' ? 1 : dir === 'BEAR' ? -1 : 0;
    return {
      name: dimNameMap[key] || key,
      value: sign * (val.confidence || 0),
      confidence: val.confidence || 0,
      direction: dir,
      rawValue: val.value,
    };
  }).filter(d => d.confidence > 0);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-slate-500">
        暂无基本面数据
      </div>
    );
  }

  const getColor = (direction: string) => {
    if (direction === 'BULL') return '#10b981';
    if (direction === 'BEAR') return '#ef4444';
    return '#64748b';
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
        <XAxis
          dataKey="name"
          tick={{ fill: '#94a3b8', fontSize: 10 }}
          angle={-20}
          textAnchor="end"
          height={50}
        />
        <YAxis
          domain={[-100, 100]}
          tick={{ fill: '#64748b', fontSize: 9 }}
          tickFormatter={(v) => `${v > 0 ? '+' : ''}${v}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            borderRadius: '8px',
            fontSize: '12px',
          }}
          labelStyle={{ color: '#e2e8f0' }}
          formatter={(_value: any, _name: any, props: any) => {
            const d = props.payload;
            return [
              `置信度: ${d.confidence}% | 方向: ${d.direction === 'BULL' ? '看多' : d.direction === 'BEAR' ? '看空' : '中性'}${d.rawValue != null ? ` | 数值: ${d.rawValue}` : ''}`,
              '',
            ];
          }}
        />
        <Bar dataKey="value" radius={[4, 4, 0, 0]} barSize={24}>
          {data.map((entry, index) => (
            <Cell key={index} fill={getColor(entry.direction)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export default FundamentalBars;
