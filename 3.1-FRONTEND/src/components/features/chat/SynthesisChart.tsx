'use client';

// ============================================
// SynthesisChart — 渲染 subagent 产出的图表
// 后端 ChartSpec 格式: { type, title, data, config }
// 支持类型: gauge / line / bar / sankey / heatmap / candlestick / scatter / pie
// ============================================

import React from 'react';
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  RadialBarChart, RadialBar, Cell,
  CartesianGrid, ScatterChart, Scatter, PieChart, Pie,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from 'recharts';

export interface ChartSpec {
  type: string;
  title: string;
  data: Record<string, unknown> | number | unknown[];
  config?: Record<string, unknown>;
}

interface SynthesisChartProps {
  chart: ChartSpec;
}

const COLORS = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f87171'];

function buildSeriesData(data: Record<string, unknown>): { name: string; value: number }[] {
  return Object.entries(data)
    .filter(([, v]) => typeof v === 'number' && !isNaN(v as number))
    .map(([k, v]) => ({ name: k, value: v as number }));
}

export function SynthesisChart({ chart }: SynthesisChartProps) {
  const { type, title, data } = chart;

  if (data === null || data === undefined) {
    return (
      <div className="text-xs text-gray-500 italic p-2">
        {title}: 无数据
      </div>
    );
  }

  switch (type) {
    case 'gauge':
      return <GaugeChart title={title} data={data} />;
    case 'line':
      return <LineChartView title={title} data={data} />;
    case 'bar':
      return <BarChartView title={title} data={data} />;
    case 'sankey':
      return <SankeyChart title={title} data={data} />;
    case 'heatmap':
      return <HeatmapChart title={title} data={data} />;
    case 'candlestick':
      return <CandlestickChart title={title} data={data} />;
    case 'scatter':
      return <ScatterChartView title={title} data={data} />;
    case 'pie':
      return <PieChartView title={title} data={data} />;
    case 'radar':
      return <RadarChartView title={title} data={data} config={chart.config} />;
    case 'bullet':
      return <BulletChartView title={title} data={data} />;
    default:
      return <TextFallback title={title} data={data} />;
  }
}

// ── Gauge ──────────────────────────────────
function GaugeChart({ title, data }: { title: string; data: unknown }) {
  const value = typeof data === 'number' ? data : Number(data);
  const pct = Math.max(0, Math.min(100, isNaN(value) ? 0 : value));
  const gaugeData = [{ name: title, value: pct, fill: COLORS[0] }];
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <div style={{ width: '100%', height: 120 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart innerRadius="60%" outerRadius="100%" data={gaugeData} startAngle={90} endAngle={-270}>
            <RadialBar background={{ fill: '#374151' }} dataKey="value" cornerRadius={6} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div className="text-center text-xs text-gray-300 -mt-8">
        {typeof data === 'number' ? data.toFixed(1) : String(value)}
      </div>
    </div>
  );
}

// ── Line ───────────────────────────────────
function LineChartView({ title, data }: { title: string; data: unknown }) {
  if (typeof data !== 'object' || Array.isArray(data) || data === null) {
    return <TextFallback title={title} data={data} />;
  }
  const series = buildSeriesData(data as Record<string, unknown>);
  if (series.length === 0) return <TextFallback title={title} data={data} />;
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <div style={{ width: '100%', height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.4} />
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6, fontSize: 11 }} />
            <Line type="monotone" dataKey="value" stroke={COLORS[0]} strokeWidth={2} dot={{ r: 3, fill: COLORS[0] }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Bar ────────────────────────────────────
function BarChartView({ title, data }: { title: string; data: unknown }) {
  const series = (() => {
    if (Array.isArray(data)) {
      // 数组格式: [{name, value}] 或 [name, value]
      return data
        .map((d: unknown) => {
          if (typeof d === 'object' && d !== null) {
            const o = d as Record<string, unknown>;
            return { name: String(o.name ?? o.key ?? ''), value: Number(o.value ?? o.val ?? 0) };
          }
          if (Array.isArray(d)) {
            return { name: String(d[0] ?? ''), value: Number(d[1] ?? 0) };
          }
          return null;
        })
        .filter((d): d is { name: string; value: number } => d !== null && !isNaN(d.value));
    }
    if (typeof data === 'object' && data !== null) {
      return buildSeriesData(data as Record<string, unknown>);
    }
    return [];
  })();
  if (series.length === 0) return <TextFallback title={title} data={data} />;
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <div style={{ width: '100%', height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={series} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.4} />
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6, fontSize: 11 }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {series.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Sankey (纯 SVG 实现) ────────────────────
interface SankeyNode { name: string }
interface SankeyLink { source: string; target: string; value: number }

function SankeyChart({ title, data }: { title: string; data: unknown }) {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return <TextFallback title={title} data={data} />;
  }
  const nodes = (data as Record<string, unknown>).nodes as SankeyNode[] | undefined;
  const links = (data as Record<string, unknown>).links as SankeyLink[] | undefined;
  if (!nodes || !links || nodes.length === 0) {
    return <TextFallback title={title} data={data} />;
  }

  const width = 360;
  const height = 180;
  const nodeWidth = 16;
  const nodeGap = 12;

  // 计算节点层级 (左侧: 只有出度的节点; 右侧: 只有入度的节点; 中间: 两者都有)
  const sourceSet = new Set(links.map(l => l.source));
  const targetSet = new Set(links.map(l => l.target));

  const leftNodes = nodes.filter(n => sourceSet.has(n.name) && !targetSet.has(n.name));
  const rightNodes = nodes.filter(n => targetSet.has(n.name) && !sourceSet.has(n.name));
  const middleNodes = nodes.filter(n => sourceSet.has(n.name) && targetSet.has(n.name));

  const layers = [leftNodes, middleNodes, rightNodes].filter(l => l.length > 0);
  const layerCount = layers.length;

  // 计算每个节点的总流量 (决定高度)
  const nodeFlow = new Map<string, number>();
  for (const n of nodes) nodeFlow.set(n.name, 0);
  for (const l of links) {
    nodeFlow.set(l.source, (nodeFlow.get(l.source) || 0) + l.value);
    nodeFlow.set(l.target, (nodeFlow.get(l.target) || 0) + l.value);
  }
  const maxFlow = Math.max(...Array.from(nodeFlow.values()), 1);

  // 布局节点
  const nodePositions = new Map<string, { x: number; y: number; h: number }>();
  const layerGap = layerCount > 1 ? (width - nodeWidth) / (layerCount - 1) : 0;

  layers.forEach((layer, li) => {
    const totalH = layer.reduce((s, n) => s + Math.max(8, (nodeFlow.get(n.name) || 0) / maxFlow * 100), 0);
    const totalGap = (layer.length - 1) * nodeGap;
    const startY = (height - totalH - totalGap) / 2;
    let y = Math.max(10, startY);
    const x = layerCount > 1 ? li * layerGap : (width - nodeWidth) / 2;
    for (const n of layer) {
      const h = Math.max(8, (nodeFlow.get(n.name) || 0) / maxFlow * 100);
      nodePositions.set(n.name, { x, y, h });
      y += h + nodeGap;
    }
  });

  // 生成 links 路径
  const linkPaths = links.map((l, i) => {
    const s = nodePositions.get(l.source);
    const t = nodePositions.get(l.target);
    if (!s || !t) return null;
    const sx = s.x + nodeWidth;
    const sy = s.y + s.h / 2;
    const tx = t.x;
    const ty = t.y + t.h / 2;
    const cx = (sx + tx) / 2;
    const path = `M${sx},${sy} C${cx},${sy} ${cx},${ty} ${tx},${ty}`;
    const opacity = Math.max(0.15, Math.min(0.8, l.value / maxFlow));
    return { path, color: COLORS[i % COLORS.length], opacity, value: l.value, source: l.source, target: l.target };
  }).filter(Boolean) as { path: string; color: string; opacity: number; value: number; source: string; target: string }[];

  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ maxHeight: 200 }}>
        {/* links */}
        {linkPaths.map((lp, i) => (
          <path
            key={i}
            d={lp.path}
            fill="none"
            stroke={lp.color}
            strokeWidth={Math.max(2, lp.value / maxFlow * 20)}
            strokeOpacity={lp.opacity}
          >
            <title>{`${lp.source} → ${lp.target}: ${lp.value}`}</title>
          </path>
        ))}
        {/* nodes */}
        {Array.from(nodePositions.entries()).map(([name, pos]) => (
          <g key={name}>
            <rect
              x={pos.x}
              y={pos.y}
              width={nodeWidth}
              height={pos.h}
              fill={COLORS[nodes.findIndex(n => n.name === name) % COLORS.length]}
              rx={3}
            />
            <text
              x={pos.x < width / 2 ? pos.x + nodeWidth + 4 : pos.x - 4}
              y={pos.y + pos.h / 2}
              textAnchor={pos.x < width / 2 ? 'start' : 'end'}
              dominantBaseline="middle"
              fill="#9ca3af"
              fontSize={10}
            >
              {name}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ── Heatmap (矩阵格式: rows/cols/values + current 高亮) ─────
function HeatmapChart({ title, data }: { title: string; data: unknown }) {
  // 支持两种格式: 矩阵格式 {rows, cols, values, current} 或数组格式 [[row,col,val], ...]
  let rows: string[] = [];
  let cols: string[] = [];
  let values: number[][] = [];
  let current: { row: string; col: string; value: number; label: string } | null = null;

  if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
    const d = data as Record<string, unknown>;
    rows = (d.rows as string[]) || [];
    cols = (d.cols as string[]) || [];
    values = (d.values as number[][]) || [];
    current = (d.current as any) || null;
  } else if (Array.isArray(data)) {
    const cells = data
      .map((d: unknown) => {
        if (Array.isArray(d) && d.length >= 3) {
          return { row: String(d[0]), col: String(d[1]), value: Number(d[2]) };
        }
        return null;
      })
      .filter((c): c is { row: string; col: string; value: number } => c !== null && !isNaN(c.value));
    rows = Array.from(new Set(cells.map(c => c.row)));
    cols = Array.from(new Set(cells.map(c => c.col)));
    values = rows.map(r => cols.map(c => cells.find(cc => cc.row === r && cc.col === c)?.value ?? 0));
  }

  if (rows.length === 0 || cols.length === 0) return <TextFallback title={title} data={data} />;

  const maxVal = Math.max(...values.flat().map(v => Math.abs(v)), 1);

  const colorFor = (v: number) => {
    if (v === 0) return '#1f2937';
    const ratio = Math.min(1, Math.abs(v) / maxVal);
    if (v >= 3) return '#dc2626'; // 高风险-红
    if (v >= 2) return `rgba(251, 146, 60, ${0.4 + ratio * 0.5})`; // 矛盾-橙
    if (v >= 1) return `rgba(55, 65, 81, ${0.3 + ratio * 0.3})`; // 一致-暗灰
    return '#1f2937';
  };

  const cellW = 68;
  const cellH = 26;

  return (
    <div className="my-2 overflow-x-auto">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      {current && (
        <div className="text-[10px] text-amber-400 mb-1">
          ▸ {current.row} × {current.col}: {current.label}
        </div>
      )}
      <table className="border-collapse" style={{ minWidth: '100%' }}>
        <thead>
          <tr>
            <th style={{ width: 64, padding: '2px 4px' }} className="text-[10px] text-gray-500 text-left" />
            {cols.map(c => (
              <th key={c} style={{ width: cellW, padding: '2px 4px' }} className="text-[9px] text-gray-400 text-center font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={r}>
              <td style={{ padding: '2px 4px' }} className="text-[9px] text-gray-400 whitespace-nowrap font-medium">
                {r}
              </td>
              {cols.map((c, ci) => {
                const v = values[ri]?.[ci] ?? 0;
                const isCurrent = current?.row === r && current?.col === c;
                const label = v >= 3 ? '⚠' : v >= 2 ? '⚡' : v >= 1 ? '✓' : '—';
                return (
                  <td key={c} style={{ padding: '2px' }}>
                    <div
                      className="rounded text-center text-[10px] font-bold flex items-center justify-center"
                      style={{
                        width: cellW - 6,
                        height: cellH,
                        backgroundColor: colorFor(v),
                        color: v >= 2 ? '#fff' : '#9ca3af',
                        border: isCurrent ? '2px solid #fbbf24' : '1px solid #374151',
                        boxShadow: isCurrent ? '0 0 6px rgba(251,191,36,0.4)' : 'none',
                      }}
                      title={`${r} / ${c}: ${v}`}
                    >
                      {label}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="text-[9px] text-gray-500 mt-1 flex gap-3">
        <span>✓ 一致</span><span>⚡ 矛盾</span><span>⚠ 高风险</span>
      </div>
    </div>
  );
}

// ── Candlestick (OHLC SVG 可视化) ──────────
function CandlestickChart({ title, data }: { title: string; data: unknown }) {
  // 支持两种格式: 单个 OHLC 对象 {open, high, low, close, change} 或数组 [{time, o, h, l, c}, ...]
  let ohlc: { open: number; high: number; low: number; close: number; change?: number } | null = null;
  let arr: any[] = [];

  if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
    const d = data as Record<string, unknown>;
    if (d.open || d.close || d.high || d.low) {
      ohlc = {
        open: Number(d.open ?? d.o ?? 0),
        high: Number(d.high ?? d.h ?? 0),
        low: Number(d.low ?? d.l ?? 0),
        close: Number(d.close ?? d.c ?? 0),
        change: d.change !== undefined ? Number(d.change) : undefined,
      };
    }
  } else if (Array.isArray(data)) {
    arr = data;
  }

  // 单根蜡烛图（24h OHLC）
  if (ohlc) {
    const { open, high, low, close, change } = ohlc;
    const up = close >= open;
    const color = up ? '#34d399' : '#f87171';
    const w = 280, h = 140;
    const pad = 20;
    const allVals = [open, high, low, close].filter(v => v > 0);
    if (allVals.length === 0) return <TextFallback title={title} data={data} />;
    const min = Math.min(...allVals);
    const max = Math.max(...allVals);
    const range = max - min || 1;
    const scaleY = (v: number) => h - pad - ((v - min) / range) * (h - pad * 2);

    const bodyTop = scaleY(Math.max(open, close));
    const bodyBot = scaleY(Math.min(open, close));
    const bodyH = Math.max(4, bodyBot - bodyTop);
    const wickX = w / 2;
    const bodyW = 40;
    const bodyX = wickX - bodyW / 2;
    const chgText = change !== undefined ? `${change >= 0 ? '+' : ''}${change.toFixed(2)}%` : '';
    const chgColor = (change ?? 0) >= 0 ? '#34d399' : '#f87171';

    return (
      <div className="my-2">
        <div className="text-[11px] text-gray-400 mb-1">{title}</div>
        <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ maxHeight: 160 }}>
          {/* 高低影线 */}
          <line x1={wickX} y1={scaleY(high)} x2={wickX} y2={scaleY(low)} stroke={color} strokeWidth={1.5} />
          {/* 蜡烛实体 */}
          <rect x={bodyX} y={bodyTop} width={bodyW} height={bodyH} fill={color} fillOpacity={0.7} stroke={color} rx={2} />
          {/* 价格标注 */}
          <text x={wickX + bodyW / 2 + 6} y={scaleY(high) + 4} fill="#9ca3af" fontSize={9}>H {high.toFixed(2)}</text>
          <text x={wickX + bodyW / 2 + 6} y={scaleY(low) + 4} fill="#9ca3af" fontSize={9}>L {low.toFixed(2)}</text>
          <text x={bodyX - 4} y={bodyTop + 4} fill={color} fontSize={9} textAnchor="end">{(open >= close ? open : close).toFixed(2)}</text>
          <text x={bodyX - 4} y={bodyBot + 10} fill={color} fontSize={9} textAnchor="end">{(open < close ? open : close).toFixed(2)}</text>
          {/* 涨跌幅 */}
          {chgText && (
            <text x={w / 2} y={pad - 6} fill={chgColor} fontSize={11} fontWeight="bold" textAnchor="middle">{chgText}</text>
          )}
        </svg>
      </div>
    );
  }

  // 数组格式：表格展示
  if (arr.length === 0) {
    return <div className="text-xs text-gray-500 italic p-2">{title}: 无 OHLC 数据</div>;
  }
  const rows = arr.map((item: any, i: number) => {
    const t = item.time || item.t || item.date || `#${i + 1}`;
    const o = item.open ?? item.o;
    const h = item.high ?? item.h;
    const l = item.low ?? item.l;
    const c = item.close ?? item.c;
    const up = c >= o;
    return (
      <tr key={i} className="border-b border-gray-700/40">
        <td className="py-0.5 pr-2 text-[10px] text-gray-400">{String(t)}</td>
        <td className="py-0.5 pr-2 text-[10px] text-gray-300">{o?.toFixed?.(2) ?? o}</td>
        <td className="py-0.5 pr-2 text-[10px] text-gray-300">{h?.toFixed?.(2) ?? h}</td>
        <td className="py-0.5 pr-2 text-[10px] text-gray-300">{l?.toFixed?.(2) ?? l}</td>
        <td className={`py-0.5 text-[10px] font-medium ${up ? 'text-emerald-400' : 'text-red-400'}`}>{c?.toFixed?.(2) ?? c}</td>
      </tr>
    );
  });
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <table className="w-full text-left">
        <thead>
          <tr className="text-[10px] text-gray-500 border-b border-gray-700/60">
            <th className="py-0.5 pr-2">时间</th>
            <th className="py-0.5 pr-2">开</th>
            <th className="py-0.5 pr-2">高</th>
            <th className="py-0.5 pr-2">低</th>
            <th className="py-0.5">收</th>
          </tr>
        </thead>
        <tbody>{rows.slice(0, 20)}</tbody>
      </table>
    </div>
  );
}

// ── Scatter ────────────────────────────────
function ScatterChartView({ title, data }: { title: string; data: unknown }) {
  // data: array of { x, y } or { name, value }
  const arr = Array.isArray(data) ? data : buildSeriesData(data as Record<string, unknown>).map(d => ({ x: d.name, y: d.value }));
  if (arr.length === 0) {
    return <div className="text-xs text-gray-500 italic p-2">{title}: 无散点数据</div>;
  }
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <ResponsiveContainer width="100%" height={180}>
        <ScatterChart margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="x" tick={{ fontSize: 10, fill: '#9ca3af' }} />
          <YAxis dataKey="y" tick={{ fontSize: 10, fill: '#9ca3af' }} />
          <Tooltip />
          <Scatter data={arr} fill={COLORS[0]} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Pie ────────────────────────────────────
function PieChartView({ title, data }: { title: string; data: unknown }) {
  const arr = Array.isArray(data) ? data : buildSeriesData(data as Record<string, unknown>);
  if (arr.length === 0) {
    return <div className="text-xs text-gray-500 italic p-2">{title}: 无饼图数据</div>;
  }
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={arr}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            outerRadius={70}
            label={(entry: any) => `${entry.name}`}
            labelLine={false}
          >
            {arr.map((_: any, i: number) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Radar (多维评分雷达) ───────────────────
function RadarChartView({ title, data, config }: { title: string; data: unknown; config?: Record<string, unknown> }) {
  let radarData: { axis: string; value: number }[] = [];
  if (Array.isArray(data)) {
    radarData = data
      .map((d: any) => {
        if (typeof d === 'object' && d !== null) {
          return { axis: String(d.axis ?? d.name ?? d.key ?? ''), value: Number(d.value ?? d.val ?? 0) };
        }
        return null;
      })
      .filter((d): d is { axis: string; value: number } => d !== null && !!d.axis);
  } else if (typeof data === 'object' && data !== null) {
    radarData = buildSeriesData(data as Record<string, unknown>).map(d => ({ axis: d.name, value: d.value }));
  }
  if (radarData.length < 3) return <TextFallback title={title} data={data} />;

  const maxVal = (config?.max as number) || 100;

  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <ResponsiveContainer width="100%" height={220}>
        <RadarChart data={radarData} margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
          <PolarGrid stroke="#374151" strokeOpacity={0.4} />
          <PolarAngleAxis dataKey="axis" tick={{ fill: '#9ca3af', fontSize: 10 }} />
          <PolarRadiusAxis angle={90} domain={[0, maxVal]} tick={{ fill: '#6b7280', fontSize: 8 }} />
          <Radar
            name={title}
            dataKey="value"
            stroke={COLORS[0]}
            fill={COLORS[0]}
            fillOpacity={0.25}
            strokeWidth={2}
            dot={{ r: 3, fill: COLORS[0] }}
          />
          <Tooltip
            contentStyle={{
              background: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 6,
              fontSize: 11,
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Bullet (回测 vs 行业基准) ──────────────
function BulletChartView({ title, data }: { title: string; data: unknown }) {
  if (!Array.isArray(data)) return <TextFallback title={title} data={data} />;
  const items = data
    .map((d: any) => ({
      name: String(d.name ?? d.label ?? ''),
      value: Number(d.value ?? 0),
      thresholds: (d.thresholds ?? []).map((t: any) => Number(t)),
      max: Number(d.max ?? 100),
      inverted: Boolean(d.inverted),
    }))
    .filter(d => d.name && !isNaN(d.value));

  if (items.length === 0) return <TextFallback title={title} data={data} />;

  const tierColor = (val: number, thresholds: number[], inverted: boolean) => {
    if (inverted) {
      // 回撤：越小越好
      if (val <= thresholds[2]) return { color: '#34d399', tier: 'Elite' };
      if (val <= thresholds[1]) return { color: '#60a5fa', tier: 'Excellent' };
      if (val <= thresholds[0]) return { color: '#fbbf24', tier: 'Safe' };
      return { color: '#f87171', tier: 'Over Risk' };
    }
    // 胜率/夏普：越大越好
    if (val >= thresholds[2]) return { color: '#34d399', tier: 'Elite' };
    if (val >= thresholds[1]) return { color: '#60a5fa', tier: 'Excellent' };
    if (val >= thresholds[0]) return { color: '#fbbf24', tier: 'Qualified' };
    return { color: '#f87171', tier: 'Below' };
  };

  return (
    <div className="my-2 space-y-3">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      {items.map((item, idx) => {
        const { color, tier } = tierColor(item.value, item.thresholds, item.inverted);
        const valPct = Math.max(0, Math.min(100, (item.value / item.max) * 100));
        const barW = 300;
        const thresholds = item.inverted
          ? item.thresholds.map(t => (t / item.max) * 100).reverse()
          : item.thresholds.map(t => (t / item.max) * 100);
        return (
          <div key={idx}>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[10px] text-gray-400">{item.name}</span>
              <span className="text-[10px] font-bold" style={{ color }}>
                {item.value.toFixed(item.max > 10 ? 1 : 2)} <span className="text-gray-500">/ {tier}</span>
              </span>
            </div>
            <svg width="100%" viewBox={`0 0 ${barW} 14`} style={{ maxHeight: 14 }}>
              {/* 基准区域背景 */}
              {item.inverted ? (
                <>
                  <rect x={0} y={0} width={(thresholds[0] / 100) * barW} height={14} fill="#f87171" fillOpacity={0.15} rx={2} />
                  <rect x={(thresholds[0] / 100) * barW} y={0} width={((thresholds[1] - thresholds[0]) / 100) * barW} height={14} fill="#fbbf24" fillOpacity={0.15} rx={0} />
                  <rect x={(thresholds[1] / 100) * barW} y={0} width={((thresholds[2] - thresholds[1]) / 100) * barW} height={14} fill="#60a5fa" fillOpacity={0.15} rx={0} />
                  <rect x={(thresholds[2] / 100) * barW} y={0} width={barW - (thresholds[2] / 100) * barW} height={14} fill="#34d399" fillOpacity={0.15} rx={2} />
                </>
              ) : (
                <>
                  <rect x={0} y={0} width={(thresholds[0] / 100) * barW} height={14} fill="#f87171" fillOpacity={0.15} rx={2} />
                  <rect x={(thresholds[0] / 100) * barW} y={0} width={((thresholds[1] - thresholds[0]) / 100) * barW} height={14} fill="#fbbf24" fillOpacity={0.15} />
                  <rect x={(thresholds[1] / 100) * barW} y={0} width={((thresholds[2] - thresholds[1]) / 100) * barW} height={14} fill="#60a5fa" fillOpacity={0.15} />
                  <rect x={(thresholds[2] / 100) * barW} y={0} width={barW - (thresholds[2] / 100) * barW} height={14} fill="#34d399" fillOpacity={0.15} rx={2} />
                </>
              )}
              {/* 阈值标记线 */}
              {thresholds.map((t, i) => (
                <line key={i} x1={(t / 100) * barW} y1={0} x2={(t / 100) * barW} y2={14} stroke="#6b7280" strokeWidth={0.5} strokeDasharray="2 2" />
              ))}
              {/* 实际值条 */}
              <rect x={0} y={3} width={(valPct / 100) * barW} height={8} fill={color} fillOpacity={0.8} rx={2} />
              {/* 值标记 */}
              <line x1={(valPct / 100) * barW} y1={0} x2={(valPct / 100) * barW} y2={14} stroke={color} strokeWidth={1.5} />
            </svg>
          </div>
        );
      })}
    </div>
  );
}

// ── Text Fallback ──────────────────────────
function TextFallback({ title, data }: { title: string; data: unknown }) {
  let text = '';
  if (typeof data === 'object' && data !== null) {
    text = Object.entries(data as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : String(v)}`)
      .join(' | ');
  } else {
    text = String(data);
  }
  return (
    <div className="text-xs text-gray-400 p-2 bg-gray-800/30 rounded">
      <span className="text-gray-500">{title}: </span>{text}
    </div>
  );
}

export default SynthesisChart;
