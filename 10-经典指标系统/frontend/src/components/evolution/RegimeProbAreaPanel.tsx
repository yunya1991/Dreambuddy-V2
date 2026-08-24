import React, { useMemo } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Brush,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import {
  REGIME_EVOLUTION_ORDER, REGIME_EVOLUTION_COLORS,
  type RegimeTrajectoryItem,
} from '../../lib/api';
import { useEvolution } from './EvolutionContext';

type ChartRow = {
  t: string;
  date: string;
  consensus: number;
  divergence: number;
  bocpd: number;
  [key: string]: number | string;
};

function ProbTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string; payload?: ChartRow }>;
  label?: string;
}) {
  if (!active || !payload || !payload.length) return null;
  const sorted = [...payload].filter((p) => typeof p.value === 'number' && p.value > 0.01)
    .sort((a, b) => b.value - a.value).slice(0, 5);
  const consensusVal = payload[0]?.payload?.consensus;
  return (
    <div className="rounded border border-slate-300 bg-white p-2 text-xs shadow-lg">
      <div className="font-semibold text-slate-900">{label}</div>
      <div className="text-slate-500">共识度: {(typeof consensusVal === 'number' ? consensusVal * 100 : 0).toFixed(1)}%</div>
      <div className="mt-1 border-t border-slate-100 pt-1">
        {sorted.map((p) => (
          <div key={p.name} style={{ color: p.color }}>
            {p.name}: {(p.value * 100).toFixed(1)}%
          </div>
        ))}
      </div>
    </div>
  );
}

export const RegimeProbAreaPanel: React.FC = () => {
  const { data, selectedRange, setSelectedRange } = useEvolution();

  const chartData: ChartRow[] = useMemo(() => {
    if (!data?.trajectory) return [];
    return data.trajectory.map((item: RegimeTrajectoryItem) => {
      const row: ChartRow = {
        t: item.t,
        date: item.t,
        consensus: item.consensus,
        divergence: 1 - item.consensus,
        bocpd: item.bocpd_cp_prob || 0,
      };
      for (const r of REGIME_EVOLUTION_ORDER) {
        row[r] = item.regime_probs?.[r] || 0;
      }
      return row;
    });
  }, [data]);

  // BOCPD 变点日（cp_prob >= 0.7）
  const changePoints = useMemo(() => {
    return chartData.filter((d) => d.bocpd >= 0.7);
  }, [chartData]);

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Panel 3: 8态概率堆叠面积图</CardTitle>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>Y轴=8态概率(0-1)</span>
          <span>·</span>
          <span>黑色虚线=分歧度(1-共识度)</span>
          <span>·</span>
          <span>红色竖线=BOCPD变点(P≥0.7)</span>
          {selectedRange && (
            <>
              <span className="ml-2">|</span>
              <span className="font-medium text-slate-700">
                选中区间: {selectedRange[0]} → {selectedRange[1]}
              </span>
            </>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {chartData.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">暂无数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={340}>
            <AreaChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
              <defs>
                {REGIME_EVOLUTION_ORDER.map((r) => (
                  <linearGradient key={r} id={`grad-${r}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={REGIME_EVOLUTION_COLORS[r]} stopOpacity={0.85} />
                    <stop offset="95%" stopColor={REGIME_EVOLUTION_COLORS[r]} stopOpacity={0.5} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 9 }}
                interval="preserveStartEnd"
                minTickGap={40}
              />
              <YAxis
                domain={[0, 1]} tick={{ fontSize: 10 }}
                label={{ value: 'P', angle: -90, position: 'insideLeft', style: { fontSize: 11 } }}
              />
              <Tooltip content={<ProbTooltip />} />
              {REGIME_EVOLUTION_ORDER.map((r) => (
                <Area
                  key={r}
                  type="monotone"
                  dataKey={r}
                  stackId="1"
                  stroke={REGIME_EVOLUTION_COLORS[r]}
                  strokeWidth={0.5}
                  fill={`url(#grad-${r})`}
                />
              ))}
              {/* 分歧度参考线 */}
              <ReferenceLine y={0.5} stroke="#1e293b" strokeDasharray="6 4" strokeOpacity={0.4} />
              {/* BOCPD 变点竖线 */}
              {changePoints.map((cp, i) => (
                <ReferenceLine
                  key={`cp-${i}`}
                  x={cp.date}
                  stroke="#ef4444"
                  strokeDasharray="3 3"
                  strokeOpacity={0.5}
                  label={{ value: 'CP', fontSize: 8, fill: '#ef4444' }}
                />
              ))}
              {/* Brush 区间选择 */}
              <Brush
                dataKey="date"
                height={20}
                stroke="#64748b"
                fill="#f1f5f9"
                travellerWidth={8}
                onChange={(e: { startIndex?: number; endIndex?: number }) => {
                  if (e && typeof e.startIndex === 'number' && typeof e.endIndex === 'number') {
                    const s = chartData[e.startIndex];
                    const en = chartData[e.endIndex];
                    if (s && en) {
                      setSelectedRange([s.t, en.t]);
                    }
                  } else {
                    setSelectedRange(null);
                  }
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
};
