import React, { useMemo } from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceArea, ReferenceLine,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Badge } from '../ui/badge';
import {
  REGIME_EVOLUTION_ORDER, REGIME_EVOLUTION_COLORS,
  type RegimeTrajectoryItem,
} from '../../lib/api';
import { useEvolution } from './EvolutionContext';

// 8 象限背景色块（L x T 平面）
const QUADRANTS: Array<{ x1: number; x2: number; y1: number; y2: number; color: string; label: string }> = [
  { x1: 0, x2: 4, y1: 0, y2: 4, color: '#16a34a', label: '牛市强趋势' },
  { x1: 0, x2: 4, y1: -4, y2: 0, color: '#8b5cf6', label: '派发/回调' },
  { x1: -4, x2: 0, y1: 0, y2: 4, color: '#f59e0b', label: '反转/筑底' },
  { x1: -4, x2: 0, y1: -4, y2: 0, color: '#78716c', label: '熊市/盘整' },
];

type TooltipPayloadItem = {
  payload: RegimeTrajectoryItem & { _top1: string; _top1p: number };
};

function TrajectoryTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload;
  const top3 = d.top3 || [];
  return (
    <div className="rounded border border-slate-300 bg-white p-2 text-xs shadow-lg">
      <div className="font-semibold text-slate-900">{d.t}</div>
      <div className="text-slate-600">价格: ${d.price?.toFixed(0)}</div>
      <div className="text-slate-600">Level: {d.level_smooth?.toFixed(2)} / Trend: {d.trend_smooth?.toFixed(2)}</div>
      <div className="mt-1 flex items-center gap-1">
        <span className="text-slate-500">主导:</span>
        <span style={{ color: REGIME_EVOLUTION_COLORS[d._top1] || '#333' }} className="font-medium">
          {d._top1} ({(d._top1p * 100).toFixed(1)}%)
        </span>
      </div>
      <div className="text-slate-500">共识度: {(d.consensus * 100).toFixed(1)}%</div>
      {top3.length > 1 && (
        <div className="mt-1 border-t border-slate-100 pt-1">
          <div className="text-slate-400">Top3:</div>
          {top3.map(([name, prob], i) => (
            <div key={i} className="text-slate-600">
              {name}: {(prob * 100).toFixed(1)}%
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const EvolutionTrajectoryPanel: React.FC = () => {
  const { data, focusDate, setFocusDate } = useEvolution();

  const chartData = useMemo(() => {
    if (!data?.trajectory) return [];
    return data.trajectory.map((item) => {
      const probs = item.regime_probs || {};
      let top1 = 'RANGE_BOUND';
      let top1p = 0;
      for (const r of REGIME_EVOLUTION_ORDER) {
        const p = probs[r] || 0;
        if (p > top1p) { top1p = p; top1 = r; }
      }
      return {
        ...item,
        x: item.level_smooth,
        y: item.trend_smooth,
        z: Math.max(20, item.consensus * 200),
        _top1: top1,
        _top1p: top1p,
      };
    });
  }, [data]);

  // 按 top1 分组，每组一条 Scatter（不同颜色）
  const groupedData = useMemo(() => {
    const groups: Record<string, Array<(typeof chartData)[0]>> = {};
    for (const d of chartData) {
      const key = d._top1;
      if (!groups[key]) groups[key] = [];
      groups[key].push(d);
    }
    return groups;
  }, [chartData]);

  const focusItem = useMemo(() => {
    if (!focusDate) return null;
    return chartData.find((d) => d.t === focusDate) || null;
  }, [chartData, focusDate]);

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Panel 1: Level-Trend 轨迹图</CardTitle>
        <div className="flex flex-wrap items-center gap-1 text-xs text-slate-500">
          <span>X=Level[-4,+4]</span>
          <span>·</span>
          <span>Y=Trend[-4,+4]</span>
          <span>·</span>
          <span>点大小=共识度</span>
          <span>·</span>
          <span>颜色=主导态</span>
          {focusItem && (
            <>
              <span className="ml-2">|</span>
              <Badge variant="outline" className="text-xs">{focusItem.t}</Badge>
              <span>L={focusItem.level_smooth?.toFixed(2)}</span>
              <span>T={focusItem.trend_smooth?.toFixed(2)}</span>
            </>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {chartData.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">暂无数据</div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              {/* 4 象限背景 */}
              {QUADRANTS.map((q, i) => (
                <ReferenceArea
                  key={i}
                  x1={q.x1} x2={q.x2} y1={q.y1} y2={q.y2}
                  fill={q.color} fillOpacity={0.06}
                />
              ))}
              <XAxis
                type="number" dataKey="x" name="Level"
                domain={[-4, 4]} tickCount={9}
                tick={{ fontSize: 10 }}
                label={{ value: 'Level', position: 'insideBottom', offset: -2, style: { fontSize: 11 } }}
              />
              <YAxis
                type="number" dataKey="y" name="Trend"
                domain={[-4, 4]} tickCount={9}
                tick={{ fontSize: 10 }}
                label={{ value: 'Trend', angle: -90, position: 'insideLeft', style: { fontSize: 11 } }}
              />
              <ZAxis type="number" dataKey="z" range={[20, 200]} />
              <ReferenceLine x={0} stroke="#94a3b8" strokeDasharray="4 4" />
              <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 4" />
              <Tooltip
                content={<TrajectoryTooltip />}
                cursor={{ strokeDasharray: '3 3' }}
              />
              {REGIME_EVOLUTION_ORDER.map((regime) => {
                const pts = groupedData[regime];
                if (!pts || !pts.length) return null;
                return (
                  <Scatter
                    key={regime}
                    name={regime}
                    data={pts}
                    fill={REGIME_EVOLUTION_COLORS[regime]}
                    fillOpacity={0.65}
                    stroke={REGIME_EVOLUTION_COLORS[regime]}
                    strokeWidth={0.5}
                    onClick={(e: unknown) => {
                      const item = e as { payload?: { t?: string } };
                      if (item?.payload?.t) setFocusDate(item.payload.t);
                    }}
                  />
                );
              })}
            </ScatterChart>
          </ResponsiveContainer>
        )}
        {/* 图例 */}
        <div className="mt-2 flex flex-wrap gap-2">
          {REGIME_EVOLUTION_ORDER.map((r) => (
            <div key={r} className="flex items-center gap-1 text-[10px] text-slate-500">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: REGIME_EVOLUTION_COLORS[r] }}
              />
              {r}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
};
