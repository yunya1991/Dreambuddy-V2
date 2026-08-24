import React, { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import {
  REGIME_EVOLUTION_ORDER, REGIME_EVOLUTION_COLORS,
  DOTPLOT_INDICATOR_NAMES, DOTPLOT_INDICATOR_LABELS,
  type RegimeDotplot,
} from '../../lib/api';
import { useEvolution } from './EvolutionContext';

function supportColor(v: number): string {
  if (v >= 0.8) return '#16a34a';
  if (v >= 0.6) return '#84cc16';
  if (v >= 0.4) return '#eab308';
  if (v >= 0.2) return '#f97316';
  return '#ef4444';
}

export const DotplotPanel: React.FC = () => {
  const { data } = useEvolution();
  const dotplot: RegimeDotplot = data?.dotplot ?? null;

  const rows = dotplot?.rows || [...DOTPLOT_INDICATOR_NAMES];
  const cols = dotplot?.cols || [...REGIME_EVOLUTION_ORDER];
  const matrix = dotplot?.matrix || [];
  const marginal = dotplot?.marginal_probs || Array(8).fill(0.125);

  const snapshot = data?.snapshot;
  const currentIndicators = snapshot?.indicators || {};

  const cellSize = 36;
  const labelWidth = 130;
  const barHeight = 28;
  const svgWidth = labelWidth + cols.length * cellSize + 60;
  const svgHeight = rows.length * cellSize + barHeight + 20;

  const indicatorValues = useMemo(() => {
    const vals: Record<string, number> = {};
    for (const name of rows) {
      const v = currentIndicators[name];
      vals[name] = typeof v === 'number' ? v : 0;
    }
    return vals;
  }, [currentIndicators, rows]);

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Panel 2: 共识点阵图 (12×8 支持度矩阵)</CardTitle>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>圆点大小/颜色 = 指标对形态的支持度</span>
          <span>·</span>
          <span>底部柱 = 8态边际概率</span>
          <span>·</span>
          <span>右侧 = 当前指标值</span>
        </div>
      </CardHeader>
      <CardContent>
        {!dotplot ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">暂无点阵图数据</div>
        ) : (
          <div className="overflow-x-auto">
            <svg width={svgWidth} height={svgHeight} className="mx-auto">
              {/* 列头：8 态名称 */}
              {cols.map((regime, j) => {
                const x = labelWidth + j * cellSize + cellSize / 2;
                return (
                  <g key={`col-${j}`}>
                    <text
                      x={x} y={12} textAnchor="middle"
                      className="fill-slate-600"
                      style={{ fontSize: 8, fontWeight: 600 }}
                      transform={`rotate(-35 ${x} 12)`}
                    >
                      {regime.replace(/_/g, ' ').substring(0, 14)}
                    </text>
                  </g>
                );
              })}

              {/* 行：12 指标 */}
              {rows.map((indName, i) => {
                const y = barHeight + i * cellSize;
                const label = DOTPLOT_INDICATOR_LABELS[indName] || indName;
                return (
                  <g key={`row-${i}`}>
                    {/* 指标名 */}
                    <text
                      x={labelWidth - 6} y={y + cellSize / 2 + 3}
                      textAnchor="end" className="fill-slate-700"
                      style={{ fontSize: 9 }}
                    >
                      {label}
                    </text>
                    {/* 单元格 */}
                    {cols.map((_regime, j) => {
                      const v = matrix[i]?.[j] ?? 0.5;
                      const cx = labelWidth + j * cellSize + cellSize / 2;
                      const cy = y + cellSize / 2;
                      const r = 3 + v * 12;
                      return (
                        <g key={`cell-${i}-${j}`}>
                          <rect
                            x={labelWidth + j * cellSize} y={y}
                            width={cellSize} height={cellSize}
                            fill="#f8fafc" stroke="#e2e8f0" strokeWidth={0.5}
                          />
                          <circle
                            cx={cx} cy={cy} r={r}
                            fill={supportColor(v)} fillOpacity={0.7}
                            stroke={supportColor(v)} strokeWidth={0.5}
                          />
                        </g>
                      );
                    })}
                    {/* 当前值 */}
                    <text
                      x={labelWidth + cols.length * cellSize + 8}
                      y={y + cellSize / 2 + 3}
                      className="fill-slate-600"
                      style={{ fontSize: 9, fontFamily: 'monospace' }}
                    >
                      {indicatorValues[indName]?.toFixed(2)}
                    </text>
                  </g>
                );
              })}

              {/* 底部边际概率柱 */}
              {cols.map((regime, j) => {
                const p = marginal[j] || 0;
                const barH = Math.max(2, p * 60);
                const x = labelWidth + j * cellSize + cellSize / 2;
                const y0 = barHeight + rows.length * cellSize + 4;
                return (
                  <g key={`bar-${j}`}>
                    <rect
                      x={x - 8} y={y0 - barH}
                      width={16} height={barH}
                      fill={REGIME_EVOLUTION_COLORS[regime]}
                      fillOpacity={0.8}
                      rx={2}
                    />
                    <text
                      x={x} y={y0 + 10}
                      textAnchor="middle" className="fill-slate-500"
                      style={{ fontSize: 8 }}
                    >
                      {(p * 100).toFixed(0)}%
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
